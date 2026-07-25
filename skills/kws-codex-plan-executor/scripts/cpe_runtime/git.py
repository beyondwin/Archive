"""Mechanical Git identity, worktree, and status boundaries for CPE."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .state import RUN_ID, SHA40, GitIdentity, RunStore


_IDENT = re.compile(r"^(.+) <([^<>]+)> [0-9]+ [+-][0-9]{4}$")


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


def _run_git(
    directory: Path,
    *arguments: str,
    text: bool,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *arguments],
        cwd=directory,
        check=True,
        capture_output=True,
        text=text,
    )


def _git(directory: Path, *arguments: str) -> str:
    return _run_git(directory, *arguments, text=True).stdout.strip()


def _git_bytes(directory: Path, *arguments: str) -> bytes:
    return _run_git(directory, *arguments, text=False).stdout


def _parse_ident(value: str) -> tuple[str, str]:
    """Extract the bounded name and email from one `git var` identity."""

    if "\n" in value or "\r" in value or "\x00" in value:
        raise ValueError("Git identity is invalid")
    match = _IDENT.fullmatch(value)
    if match is None:
        raise ValueError("Git identity is invalid")
    name, email = match.groups()
    if (
        not name.strip()
        or not email.strip()
        or len(name) > 320
        or len(email) > 320
    ):
        raise ValueError("Git identity is invalid")
    return name, email


def capture_git_identity(repository: Path) -> GitIdentity:
    """Seal Git's configured author and committer names and emails."""

    try:
        configured_name = _git(repository, "config", "--get", "user.name")
        configured_email = _git(repository, "config", "--get", "user.email")
        if not configured_name or not configured_email:
            raise ValueError("Git identity is unavailable")
        author = _git(repository, "var", "GIT_AUTHOR_IDENT")
        committer = _git(repository, "var", "GIT_COMMITTER_IDENT")
        author_name, author_email = _parse_ident(author)
        committer_name, committer_email = _parse_ident(committer)
    except (OSError, subprocess.CalledProcessError, UnicodeError) as exc:
        raise ValueError("Git identity is unavailable") from exc
    return GitIdentity(
        author_name=author_name,
        author_email=author_email,
        committer_name=committer_name,
        committer_email=committer_email,
    )


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
    raw = _git(directory, "rev-parse", "--path-format=absolute", flag)
    try:
        return Path(raw).resolve(strict=True)
    except OSError as exc:
        raise ValueError("Git repository is invalid") from exc


def _common_repository(repository: Path) -> tuple[Path, Path]:
    """Require the declared source to be the common repository worktree."""

    resolved = _resolved_directory(repository, "Git repository")
    try:
        top_level = Path(
            _git(resolved, "rev-parse", "--show-toplevel")
        ).resolve(strict=True)
        common = _absolute_git_path(resolved, "--git-common-dir")
        git_directory = _absolute_git_path(resolved, "--git-dir")
        bare = _git(resolved, "rev-parse", "--is-bare-repository")
    except (OSError, subprocess.CalledProcessError, UnicodeError, ValueError) as exc:
        raise ValueError("Git repository is invalid") from exc
    if (
        top_level != resolved
        or common != git_directory
        or bare != "false"
    ):
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

    if (
        not isinstance(base, str)
        or not isinstance(head, str)
        or not SHA40.fullmatch(base)
        or not SHA40.fullmatch(head)
    ):
        raise ValueError("Git ancestry is invalid")
    if _commit_at(worktree, base) != base or _commit_at(worktree, head) != head:
        raise ValueError("Git ancestry is invalid")
    try:
        _git(worktree, "merge-base", "--is-ancestor", base, head)
    except (OSError, subprocess.CalledProcessError, UnicodeError) as exc:
        raise ValueError("Git ancestry is invalid") from exc


def _branch_exists(repository: Path, branch: str) -> bool:
    try:
        _git(repository, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}")
    except subprocess.CalledProcessError as exc:
        if exc.returncode == 1:
            return False
        raise
    return True


def _cleanup_partial_worktree(
    repository: Path,
    *,
    worktree: Path,
    branch: str,
    base: str,
) -> None:
    """Best-effort cleanup limited to identities absent before this call."""

    try:
        _git(repository, "worktree", "remove", "--force", str(worktree))
    except (OSError, subprocess.CalledProcessError):
        if worktree.exists() and not worktree.is_symlink():
            shutil.rmtree(worktree)
    try:
        branch_commit = _git(
            repository,
            "rev-parse",
            "--verify",
            f"refs/heads/{branch}^{{commit}}",
        )
    except (OSError, subprocess.CalledProcessError):
        return
    if branch_commit == base:
        try:
            _git(repository, "branch", "-D", branch)
        except (OSError, subprocess.CalledProcessError):
            pass


def create_worktree(
    repository: Path,
    *,
    base: str,
    run_id: str,
    root: Path,
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
    if worktree.exists() or worktree.is_symlink():
        raise ValueError("worktree path already exists")
    if _branch_exists(source, branch):
        raise ValueError("worktree branch already exists")
    try:
        _git(
            source,
            "worktree",
            "add",
            "-b",
            branch,
            str(worktree),
            base,
        )
    except Exception:
        _cleanup_partial_worktree(
            source,
            worktree=worktree,
            branch=branch,
            base=base,
        )
        raise
    return WorktreeAssignment(
        repository=source,
        worktree=worktree,
        branch=branch,
        base_commit=base,
        git_common_dir=common,
    )


def _read_manifest(path: Path) -> dict[str, object] | None:
    if path.is_symlink():
        return None
    descriptor: int | None = None
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        )
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            return None
        with os.fdopen(descriptor, "rb", closefd=True) as stream:
            descriptor = None
            payload = stream.read(65537)
        if len(payload) > 65536:
            return None
        decoded = json.loads(payload.decode("utf-8"))
        return RunStore.validate_manifest_payload(decoded)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        return None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _lock_is_held(path: Path) -> bool:
    if path.is_symlink():
        return False
    descriptor: int | None = None
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        )
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            return False
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        return False
    except OSError:
        return False
    finally:
        if descriptor is not None:
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
        if manifest is None or manifest["worktree"] != str(worktree):
            continue
        if _lock_is_held(run_root / "run.lock"):
            return True
    return False


def _worktree_details(
    source: Path,
    common: Path,
    worktree: Path,
) -> tuple[Path, str, str]:
    candidate = _resolved_directory(worktree, "Git worktree")
    try:
        top_level = Path(
            _git(candidate, "rev-parse", "--show-toplevel")
        ).resolve(strict=True)
        candidate_common = _absolute_git_path(candidate, "--git-common-dir")
        branch = _git(candidate, "symbolic-ref", "--quiet", "--short", "HEAD")
        head = _commit_at(candidate, "HEAD")
    except (OSError, subprocess.CalledProcessError, UnicodeError, ValueError) as exc:
        raise ValueError("Git worktree is invalid") from exc
    if (
        top_level != candidate
        or candidate_common != common
        or not branch
        or "\n" in branch
        or "\x00" in branch
    ):
        raise ValueError("Git worktree does not belong to the declared repository")
    return candidate, branch, head


def adopt_worktree(
    repository: Path,
    *,
    worktree: Path,
    base: str,
) -> WorktreeAssignment:
    """Validate and adopt an existing worktree without mutating it."""

    source, common = _common_repository(repository)
    candidate, branch, head = _worktree_details(source, common, worktree)
    require_ancestor(candidate, base, head)
    if _has_live_v3_lock(candidate):
        raise ValueError("live v3 worktree lock owns the worktree")
    return WorktreeAssignment(
        repository=source,
        worktree=candidate,
        branch=branch,
        base_commit=base,
        git_common_dir=common,
    )


def _status_flags(status: bytes) -> tuple[bool, bool]:
    tracked_dirty = False
    untracked_present = False
    records = status.split(b"\x00")
    index = 0
    while index < len(records):
        record = records[index]
        if not record:
            index += 1
            continue
        if len(record) < 3 or record[2:3] != b" ":
            raise ValueError("Git status is invalid")
        code = record[:2]
        if code == b"??":
            untracked_present = True
        elif code != b"!!":
            tracked_dirty = True
        index += 2 if b"R" in code or b"C" in code else 1
    return tracked_dirty, untracked_present


def observe_git(worktree: Path) -> GitFacts:
    """Observe exact HEAD and raw porcelain status facts."""

    directory = _resolved_directory(worktree, "Git worktree")
    head = _commit_at(directory, "HEAD")
    try:
        status = _git_bytes(
            directory,
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
        )
        tracked_dirty, untracked_present = _status_flags(status)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError("Git status is unavailable") from exc
    return GitFacts(
        head=head,
        tracked_clean=not tracked_dirty,
        untracked_present=untracked_present,
        status_digest=hashlib.sha256(status).hexdigest(),
    )
