from __future__ import annotations

import hashlib
import os
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


@dataclass(frozen=True)
class GitSnapshot:
    head: str
    files: tuple[tuple[str, str], ...]
    cumulative_patch_sha256: str


@dataclass(frozen=True)
class GitDelta:
    changed_files: tuple[str, ...]
    patch_sha256: str
    patch_bytes: bytes
    head_changed: bool


def _git(worktree: Path, args: list[str], *, allow_failure: bool = False) -> bytes:
    result = subprocess.run(
        ["git", *args],
        cwd=worktree,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode and not allow_failure:
        raise RuntimeError(os.fsdecode(result.stderr).strip() or "git command failed")
    return result.stdout if result.returncode == 0 else b""


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


def _listed_paths(worktree: Path) -> tuple[str, ...]:
    tracked = {
        os.fsdecode(item)
        for item in _git(worktree, ["ls-files", "-z", "--cached"]).split(b"\0")
        if item
    }
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
    return tuple(sorted(tracked | filesystem))


def _snapshot_bytes(head: str, files: tuple[tuple[str, str], ...]) -> bytes:
    payload = bytearray(b"CPE-GIT-SNAPSHOT-V1\0")
    payload.extend(_field(b"H", head.encode("ascii")))
    for path, fingerprint in files:
        payload.extend(_field(b"P", _path_bytes(path)))
        payload.extend(_field(b"F", fingerprint.encode("ascii")))
    return bytes(payload)


def capture_snapshot(worktree: Path) -> GitSnapshot:
    worktree = worktree.expanduser().resolve()
    head = os.fsdecode(_git(worktree, ["rev-parse", "--verify", "HEAD"], allow_failure=True)).strip()
    files = tuple((path, _content_record(worktree, path)[0]) for path in _listed_paths(worktree))
    digest = hashlib.sha256(_snapshot_bytes(head, files)).hexdigest()
    return GitSnapshot(head, files, digest)


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
        before.head != after.head,
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
