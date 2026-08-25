"""Mechanical Git identity, worktree, and status boundaries for CPE."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .state import RUN_ID, SHA40, GitIdentity, RunStore

_IDENT = re.compile(r"^(.+) <([^<>]+)> [0-9]+ [+-][0-9]{4}$")
_ZERO_OID = "0" * 40


@dataclass(frozen=True)
class WorktreeAssignment:
    repository: Path
    worktree: Path
    branch: str
    base_commit: str
    git_common_dir: Path

@dataclass(frozen=True)
class GitFacts:
    head: str
    tracked_clean: bool
    untracked_present: bool
    status_digest: str

def _git(directory: Path, *arguments: str, binary: bool = False) -> str | bytes:
    result = subprocess.run(
        ["git", *arguments], cwd=directory, check=True,
        capture_output=True, text=not binary,
    )
    return result.stdout if binary else result.stdout.strip()

def _parse_ident(value: str) -> tuple[str, str]:
    """Extract the bounded name and email from one `git var` identity."""
    if any(control in value for control in ("\n", "\r", "\x00")):
        raise ValueError("Git identity is invalid")
    match = _IDENT.fullmatch(value)
    if match is None:
        raise ValueError("Git identity is invalid")
    name, email = match.groups()
    if not name.strip() or not email.strip() or max(len(name), len(email)) > 320:
        raise ValueError("Git identity is invalid")
    return name, email

def capture_git_identity(repository: Path) -> GitIdentity:
    """Seal Git's configured author and committer names and emails."""
    try:
        configured = tuple(_git(repository, "config", "--get", name)
                           for name in ("user.name", "user.email"))
        if not all(configured):
            raise ValueError("Git identity is unavailable")
        author_name, author_email = _parse_ident(_git(repository, "var", "GIT_AUTHOR_IDENT"))
        committer_name, committer_email = _parse_ident(_git(repository, "var", "GIT_COMMITTER_IDENT"))
    except (OSError, subprocess.CalledProcessError, UnicodeError) as exc:
        raise ValueError("Git identity is unavailable") from exc
    return GitIdentity(author_name, author_email, committer_name, committer_email)

def _resolved_directory(path: Path, name: str) -> Path:
    if not isinstance(path, Path) or path.is_symlink():
        raise ValueError(f"{name} is invalid")
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"{name} is invalid") from exc
    if not resolved.is_dir():
        raise ValueError(f"{name} is invalid")
    return resolved

def _absolute_git_path(directory: Path, flag: str) -> Path:
    try:
        return Path(_git(directory, "rev-parse", "--path-format=absolute", flag)).resolve(strict=True)
    except OSError as exc:
        raise ValueError("Git repository is invalid") from exc

def _common_repository(repository: Path) -> tuple[Path, Path]:
    """Require the declared source to be the common repository worktree."""
    resolved = _resolved_directory(repository, "Git repository")
    try:
        top_level = Path(_git(resolved, "rev-parse", "--show-toplevel")).resolve(strict=True)
        common = _absolute_git_path(resolved, "--git-common-dir")
        git_directory = _absolute_git_path(resolved, "--git-dir")
        bare = _git(resolved, "rev-parse", "--is-bare-repository")
    except (OSError, subprocess.CalledProcessError, UnicodeError, ValueError) as exc:
        raise ValueError("Git repository is invalid") from exc
    if top_level != resolved or common != git_directory or bare != "false":
        raise ValueError("Git repository must be the worktree's common repository")
    return resolved, common

def _commit_at(worktree: Path, revision: str) -> str:
    try:
        commit = _git(worktree, "rev-parse", "--verify", f"{revision}^{{commit}}")
    except (OSError, subprocess.CalledProcessError, UnicodeError) as exc:
        raise ValueError("Git ancestry is invalid") from exc
    if not SHA40.fullmatch(commit):
        raise ValueError("Git ancestry is invalid")
    return commit

def require_ancestor(worktree: Path, base: str, head: str) -> None:
    """Require two exact commits and prove base is an ancestor of head."""
    if not all(isinstance(value, str) and SHA40.fullmatch(value)
               for value in (base, head)):
        raise ValueError("Git ancestry is invalid")
    if _commit_at(worktree, base) != base or _commit_at(worktree, head) != head:
        raise ValueError("Git ancestry is invalid")
    try:
        _git(worktree, "merge-base", "--is-ancestor", base, head)
    except (OSError, subprocess.CalledProcessError, UnicodeError) as exc:
        raise ValueError("Git ancestry is invalid") from exc

def _directory_identity(path: Path) -> tuple[int, int] | None:
    try:
        metadata = path.lstat()
    except OSError:
        return None
    if not stat.S_ISDIR(metadata.st_mode):
        return None
    return metadata.st_dev, metadata.st_ino

def _cleanup_claimed_worktree(
    repository: Path, *, worktree: Path, branch: str, path_claimed: bool,
) -> None:
    """Clean atomic claims with non-force native operations or fail closed."""
    if path_claimed:
        try:
            _git(repository, "worktree", "remove", str(worktree))
        except (OSError, subprocess.CalledProcessError):
            try:
                worktree.rmdir()
            except OSError as directory_error:
                raise RuntimeError(
                    "claimed Git worktree cleanup failed; artifacts were preserved"
                ) from directory_error
    try:
        _git(repository, "branch", "-d", branch)
    except (OSError, subprocess.CalledProcessError) as branch_error:
        raise RuntimeError(
            "claimed Git branch cleanup failed; branch was preserved"
        ) from branch_error

def create_worktree(
    repository: Path, *, base: str, run_id: str, root: Path,
) -> WorktreeAssignment:
    """Create one exact run branch and linked worktree from an ancestor base."""
    source, common = _common_repository(repository)
    if not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id):
        raise ValueError("CPE run ID is invalid")
    current_head = _commit_at(source, "HEAD")
    require_ancestor(source, base, current_head)
    if not isinstance(root, Path) or root.is_symlink():
        raise ValueError("worktree root is invalid")
    root = root.resolve()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    branch = f"codex/{run_id}"
    worktree = (root / run_id).resolve()
    _git(source, "update-ref", "--no-deref", f"refs/heads/{branch}", base, _ZERO_OID)
    path_claimed = False
    try:
        worktree.mkdir(mode=0o700)
        path_claimed = True
        if _directory_identity(worktree) is None:
            raise ValueError("worktree path claim is invalid")
        _git(source, "worktree", "add", str(worktree), branch)
    except Exception:
        _cleanup_claimed_worktree(source, worktree=worktree, branch=branch,
                                  path_claimed=path_claimed)
        raise
    return WorktreeAssignment(source, worktree, branch, base, common)

def _regular_file_descriptor(path: Path) -> int | None:
    if path.is_symlink():
        return None
    descriptor: int | None = None
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        if stat.S_ISREG(os.fstat(descriptor).st_mode):
            return descriptor
    except OSError:
        pass
    if descriptor is not None:
        os.close(descriptor)
    return None

def _read_manifest(path: Path) -> dict[str, object] | None:
    descriptor = _regular_file_descriptor(path)
    if descriptor is None:
        return None
    try:
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            payload = stream.read(65537)
        if len(payload) > 65536:
            return None
        return RunStore.validate_manifest_payload(json.loads(payload.decode("utf-8")))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        return None
    finally:
        os.close(descriptor)

def _lock_is_held(path: Path) -> bool:
    descriptor = _regular_file_descriptor(path)
    if descriptor is None:
        return False
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        return False
    except OSError:
        return False
    finally:
        os.close(descriptor)

def _has_live_v3_lock(worktree: Path) -> bool:
    codex_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    runs = codex_home / "cpe-v3" / "runs"
    if runs.is_symlink() or not runs.is_dir():
        return False
    try:
        run_roots = sorted(runs.iterdir())
    except OSError:
        return False
    for run_root in run_roots:
        if run_root.is_symlink() or not run_root.is_dir():
            continue
        manifest = _read_manifest(run_root / "manifest.json")
        if (manifest is not None
                and manifest["worktree"] == str(worktree)
                and _lock_is_held(run_root / "run.lock")):
            return True
    return False

def adopt_worktree(
    repository: Path, *, worktree: Path, base: str,
) -> WorktreeAssignment:
    """Validate and adopt an existing worktree without mutating it."""
    source, common = _common_repository(repository)
    candidate = _resolved_directory(worktree, "Git worktree")
    try:
        top_level = Path(_git(candidate, "rev-parse", "--show-toplevel")).resolve(strict=True)
        candidate_common = _absolute_git_path(candidate, "--git-common-dir")
        branch = _git(candidate, "symbolic-ref", "--quiet", "--short", "HEAD")
        head = _commit_at(candidate, "HEAD")
    except (OSError, subprocess.CalledProcessError, UnicodeError, ValueError) as exc:
        raise ValueError("Git worktree is invalid") from exc
    if (top_level != candidate or candidate_common != common or not branch
            or "\n" in branch or "\x00" in branch):
        raise ValueError("Git worktree does not belong to the declared repository")
    require_ancestor(candidate, base, head)
    if _has_live_v3_lock(candidate):
        raise ValueError("live v3 worktree lock owns the worktree")
    return WorktreeAssignment(source, candidate, branch, base, common)

def _status_flags(status: bytes) -> tuple[bool, bool]:
    tracked_dirty = untracked_present = False
    records = status.split(b"\x00")
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record:
            continue
        if len(record) < 3 or record[2:3] != b" ":
            raise ValueError("Git status is invalid")
        code = record[:2]
        if code == b"??":
            untracked_present = True
        elif code != b"!!":
            tracked_dirty = True
        if b"R" in code or b"C" in code:
            index += 1
    return tracked_dirty, untracked_present

def observe_git(worktree: Path) -> GitFacts:
    """Observe exact HEAD and raw porcelain status facts."""
    directory = _resolved_directory(worktree, "Git worktree")
    head = _commit_at(directory, "HEAD")
    try:
        status = _git(directory, "status", "--porcelain=v1", "-z",
                      "--untracked-files=all", binary=True)
        tracked_dirty, untracked_present = _status_flags(status)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError("Git status is unavailable") from exc
    return GitFacts(head, not tracked_dirty, untracked_present,
                    hashlib.sha256(status).hexdigest())
