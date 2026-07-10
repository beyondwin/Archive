from __future__ import annotations

import hashlib
import os
import stat
import subprocess
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath


INVALID_GIT_HEAD = "!invalid-or-missing-git-head!"
UNBORN_GIT_HEAD = "!unborn-git-head!"
MISSING_GIT_INDEX = b"!missing-git-index!"
INVALID_GIT_INDEX = b"!invalid-git-index!"
DETACHED_GIT_HEAD = b"!detached-git-head!"


@dataclass(frozen=True)
class GitSnapshot:
    head: str
    files: tuple[tuple[str, str], ...]
    cumulative_patch_sha256: str
    _git_identity_sha256: str = field(default="", repr=False)
    _git_metadata_valid: bool = field(default=True, repr=False)


@dataclass(frozen=True)
class GitDelta:
    changed_files: tuple[str, ...]
    patch_sha256: str
    patch_bytes: bytes
    head_changed: bool


def _git_result(worktree: Path, args: list[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *args],
        cwd=worktree,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _field(label: bytes, value: bytes) -> bytes:
    return label + len(value).to_bytes(8, "big") + value


def _path_bytes(path: str) -> bytes:
    return os.fsencode(path)


def _safe_path(path: str) -> PurePosixPath:
    value = PurePosixPath(path)
    if value.is_absolute() or not value.parts or ".." in value.parts:
        raise ValueError(f"unsafe git path: {path!r}")
    return value


def _read_file_no_follow(path: Path) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            return handle.read()
    finally:
        os.close(descriptor)


def _content_record(worktree: Path, relative: str) -> tuple[str, bytes]:
    parts = _safe_path(relative).parts
    path = worktree.joinpath(*parts)
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return "deleted", b""
    mode = stat.S_IMODE(metadata.st_mode)
    if stat.S_ISLNK(metadata.st_mode):
        target = os.readlink(os.fsencode(path))
        raw = target if isinstance(target, bytes) else os.fsencode(target)
        return f"symlink:{mode:o}:{hashlib.sha256(raw).hexdigest()}", raw
    if stat.S_ISREG(metadata.st_mode):
        raw = _read_file_no_follow(path)
        return f"file:{mode:o}:{hashlib.sha256(raw).hexdigest()}", raw
    marker = f"other:{metadata.st_mode:o}".encode("ascii")
    return f"other:{mode:o}:{hashlib.sha256(marker).hexdigest()}", marker


def _listed_paths(
    worktree: Path,
    *,
    tolerate_invalid_git: bool,
) -> tuple[tuple[str, ...], bool]:
    tracked_result = _git_result(worktree, ["ls-files", "-z", "--cached"])
    if tracked_result.returncode:
        if not tolerate_invalid_git:
            raise RuntimeError("git snapshot command failed: ls-files")
        tracked: set[str] = set()
        git_valid = False
    else:
        tracked = {
            os.fsdecode(item)
            for item in tracked_result.stdout.split(b"\0")
            if item
        }
        git_valid = True
    filesystem: set[str] = set()

    def walk(directory: bytes, prefix: bytes = b"") -> None:
        with os.scandir(directory) as entries:
            for entry in entries:
                name = entry.name
                if name == b".git":
                    continue
                relative = name if not prefix else prefix + b"/" + name
                if entry.is_dir(follow_symlinks=False):
                    walk(entry.path, relative)
                else:
                    filesystem.add(os.fsdecode(relative))

    walk(os.fsencode(worktree))
    return tuple(sorted(tracked | filesystem)), git_valid


def _capture_head(worktree: Path, *, tolerate_invalid_git: bool) -> tuple[str, bool]:
    head_result = _git_result(worktree, ["rev-parse", "--verify", "HEAD"])
    head = os.fsdecode(head_result.stdout).strip()
    if head_result.returncode == 0 and head:
        return head, True

    inside = _git_result(worktree, ["rev-parse", "--is-inside-work-tree"])
    status = _git_result(worktree, ["status", "--porcelain=v1", "-z"])
    symbolic = _git_result(worktree, ["symbolic-ref", "-q", "HEAD"])
    if (
        inside.returncode == 0
        and inside.stdout.strip() == b"true"
        and status.returncode == 0
        and symbolic.returncode == 0
    ):
        return UNBORN_GIT_HEAD, True
    if tolerate_invalid_git:
        return INVALID_GIT_HEAD, False
    raise RuntimeError("git snapshot failed: invalid repository metadata")


def _capture_git_identity(
    worktree: Path,
    *,
    head: str,
    tolerate_invalid_git: bool,
) -> tuple[str, bool]:
    path_result = _git_result(worktree, ["rev-parse", "--git-path", "index"])
    raw_path = path_result.stdout.rstrip(b"\r\n")
    if path_result.returncode or not raw_path:
        if tolerate_invalid_git:
            raw_path = INVALID_GIT_INDEX
            index_present = False
        else:
            raise RuntimeError("git snapshot failed: index path unavailable")
    else:
        index_path = Path(os.fsdecode(raw_path))
        if not index_path.is_absolute():
            index_path = worktree / index_path
        try:
            metadata = index_path.lstat()
        except FileNotFoundError:
            if head == UNBORN_GIT_HEAD:
                index_present = False
            elif tolerate_invalid_git:
                index_present = False
            else:
                raise RuntimeError("git snapshot failed: index unavailable") from None
        else:
            if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
                if not tolerate_invalid_git:
                    raise RuntimeError("git snapshot failed: index is not a regular file")
                index_present = False
                raw_path = INVALID_GIT_INDEX
            else:
                index_present = True

    stage = _git_result(worktree, ["ls-files", "--stage", "-z"])
    flags = _git_result(worktree, ["ls-files", "-v", "-z"])
    symbolic = _git_result(worktree, ["symbolic-ref", "-q", "HEAD"])
    commands_valid = stage.returncode == 0 and flags.returncode == 0
    index_valid = commands_valid and (
        index_present or head == UNBORN_GIT_HEAD
    )
    if not index_valid and not tolerate_invalid_git:
        raise RuntimeError("git snapshot failed: index unavailable or invalid")
    symbolic_identity = (
        symbolic.stdout.rstrip(b"\r\n")
        if symbolic.returncode == 0 and symbolic.stdout.strip()
        else DETACHED_GIT_HEAD
    )
    presence = b"present" if index_present else MISSING_GIT_INDEX
    stage_identity = stage.stdout if stage.returncode == 0 else INVALID_GIT_INDEX
    flags_identity = flags.stdout if flags.returncode == 0 else INVALID_GIT_INDEX
    payload = bytearray(b"CPE-GIT-IDENTITY-V1\0")
    payload.extend(_field(b"H", head.encode("ascii")))
    payload.extend(_field(b"R", symbolic_identity))
    payload.extend(_field(b"P", presence))
    payload.extend(_field(b"S", stage_identity))
    payload.extend(_field(b"V", flags_identity))
    return hashlib.sha256(bytes(payload)).hexdigest(), index_valid


def _snapshot_bytes(
    head: str,
    files: tuple[tuple[str, str], ...],
    git_identity_sha256: str,
) -> bytes:
    payload = bytearray(b"CPE-GIT-SNAPSHOT-V1\0")
    payload.extend(_field(b"H", head.encode("ascii")))
    payload.extend(_field(b"I", git_identity_sha256.encode("ascii")))
    for path, fingerprint in files:
        payload.extend(_field(b"P", _path_bytes(path)))
        payload.extend(_field(b"F", fingerprint.encode("ascii")))
    return bytes(payload)


def capture_snapshot(
    worktree: Path,
    *,
    tolerate_invalid_git: bool = False,
) -> GitSnapshot:
    worktree = worktree.expanduser().resolve()
    head, head_valid = _capture_head(
        worktree, tolerate_invalid_git=tolerate_invalid_git
    )
    listed, index_valid = _listed_paths(
        worktree, tolerate_invalid_git=tolerate_invalid_git
    )
    git_identity, identity_valid = _capture_git_identity(
        worktree,
        head=head,
        tolerate_invalid_git=tolerate_invalid_git,
    )
    if not head_valid:
        head = INVALID_GIT_HEAD
    files = tuple((path, _content_record(worktree, path)[0]) for path in listed)
    digest = hashlib.sha256(_snapshot_bytes(head, files, git_identity)).hexdigest()
    return GitSnapshot(
        head,
        files,
        digest,
        git_identity,
        head_valid and index_valid and identity_valid,
    )


def capture_binary_patch(worktree: Path, changed_files: tuple[str, ...] | list[str]) -> bytes:
    worktree = worktree.expanduser().resolve()
    payload = bytearray(b"CPE-GIT-CONTENT-V1\0")
    for path in sorted(set(changed_files)):
        fingerprint, raw = _content_record(worktree, path)
        payload.extend(_field(b"P", _path_bytes(path)))
        payload.extend(_field(b"F", fingerprint.encode("ascii")))
        payload.extend(_field(b"C", raw))
    return bytes(payload)


def diff_snapshots(before: GitSnapshot, after: GitSnapshot, worktree: Path) -> GitDelta:
    before_map = dict(before.files)
    after_map = dict(after.files)
    changed = tuple(
        sorted(
            path
            for path in before_map.keys() | after_map.keys()
            if before_map.get(path) != after_map.get(path)
        )
    )
    payload = bytearray(b"CPE-GIT-DELTA-V1\0")
    payload.extend(_field(b"B", before.head.encode("ascii")))
    payload.extend(_field(b"A", after.head.encode("ascii")))
    payload.extend(_field(b"S", before.cumulative_patch_sha256.encode("ascii")))
    payload.extend(_field(b"T", after.cumulative_patch_sha256.encode("ascii")))
    payload.extend(_field(b"I", before._git_identity_sha256.encode("ascii")))
    payload.extend(_field(b"J", after._git_identity_sha256.encode("ascii")))
    for path in changed:
        payload.extend(_field(b"P", _path_bytes(path)))
        payload.extend(_field(b"B", before_map.get(path, "absent").encode("ascii")))
        payload.extend(_field(b"A", after_map.get(path, "absent").encode("ascii")))
    payload.extend(_field(b"D", capture_binary_patch(worktree, changed)))
    patch = bytes(payload)
    return GitDelta(
        changed,
        hashlib.sha256(patch).hexdigest(),
        patch,
        before.head != after.head
        or before._git_identity_sha256 != after._git_identity_sha256,
    )


def _matches(path: str, patterns: list[str] | tuple[str, ...]) -> bool:
    candidate = PurePosixPath(path)
    return any(path == pattern or candidate.match(pattern) for pattern in patterns)


def scope_errors(
    delta: GitDelta,
    allowed: list[str] | tuple[str, ...],
    forbidden: list[str] | tuple[str, ...],
) -> list[str]:
    forbidden_paths = sorted(path for path in delta.changed_files if _matches(path, forbidden))
    unclaimed_paths = sorted(
        path
        for path in delta.changed_files
        if path not in forbidden_paths and not _matches(path, allowed)
    )
    errors = [f"forbidden_write:{path}" for path in forbidden_paths]
    errors.extend(f"unclaimed_write:{path}" for path in unclaimed_paths)
    if delta.head_changed:
        errors.append("worktree_head_changed")
    return errors
