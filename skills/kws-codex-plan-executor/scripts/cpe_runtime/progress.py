"""Canonical durable-progress snapshots and checkpoint decisions."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
import subprocess
from typing import Literal


MAX_WORKTREE_CHANGED_FILES = 4_096
MAX_WORKTREE_FILE_BYTES = 16 * 1024 * 1024
MAX_WORKTREE_TOTAL_BYTES = 128 * 1024 * 1024
_CLEAN_WORKTREE_DIGEST = sha256(b"cpe-worktree-clean-v1").hexdigest()


@dataclass(frozen=True)
class WorktreeChangeObservation:
    changed: bool
    digest: str | None
    regular_file_count: int
    total_bytes: int | None
    reason_code: str | None


@dataclass(frozen=True)
class ProgressSnapshot:
    head: str
    completed_task_ids: tuple[str, ...]
    current_task_id: str | None
    worktree_changed: bool = False
    worktree_change_digest: str | None = _CLEAN_WORKTREE_DIGEST


@dataclass(frozen=True)
class CheckpointBudget:
    max_controller_launches: int
    plan_wall_seconds: int


@dataclass(frozen=True)
class CheckpointDecision:
    action: Literal[
        "continue", "checkpoint", "block", "fail",
        "stop_stalled", "stop_budget", "finish",
    ]
    reason_code: str
    progress_fingerprint: str


def _identifier_set(value: object, *, name: str) -> list[str]:
    if not isinstance(value, tuple) or not all(
        isinstance(item, str) and item for item in value
    ):
        raise ValueError(f"progress snapshot {name} is invalid")
    return sorted(set(value))


def progress_fingerprint(snapshot: ProgressSnapshot) -> str:
    """Hash only canonical, durable plan-progress fields."""
    if not isinstance(snapshot, ProgressSnapshot):
        raise ValueError("progress snapshot is invalid")
    if not isinstance(snapshot.head, str) or not snapshot.head:
        raise ValueError("progress snapshot head is invalid")
    if snapshot.current_task_id is not None and (
        not isinstance(snapshot.current_task_id, str) or not snapshot.current_task_id
    ):
        raise ValueError("progress snapshot current task is invalid")
    if not isinstance(snapshot.worktree_changed, bool):
        raise ValueError("progress snapshot worktree changed is invalid")
    if snapshot.worktree_change_digest is not None and (
        not isinstance(snapshot.worktree_change_digest, str)
        or len(snapshot.worktree_change_digest) != 64
        or any(character not in "0123456789abcdef" for character in snapshot.worktree_change_digest)
    ):
        raise ValueError("progress snapshot worktree digest is invalid")
    if not snapshot.worktree_changed and snapshot.worktree_change_digest is None:
        raise ValueError("progress snapshot worktree digest is invalid")
    payload = {
        "head": snapshot.head,
        "completed_task_ids": _identifier_set(
            snapshot.completed_task_ids, name="completed task IDs"
        ),
        "current_task_id": snapshot.current_task_id,
        "worktree_changed": snapshot.worktree_changed,
        "worktree_change_digest": snapshot.worktree_change_digest,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(encoded).hexdigest()


def _non_negative_int(value: object, *, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"checkpoint {name} is invalid")
    return value


def _positive_budget(value: object, *, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"checkpoint budget {name} is invalid")
    return value


def decide_checkpoint(
    *,
    previous: ProgressSnapshot | None,
    current: ProgressSnapshot,
    timed_out: bool,
    controller_launches: int,
    plan_elapsed_seconds: int,
    budget: CheckpointBudget,
    child_completed: bool = False,
) -> CheckpointDecision:
    """Apply the bounded, progress-aware checkpoint decision table."""
    fingerprint = progress_fingerprint(current)
    if not isinstance(timed_out, bool) or not isinstance(child_completed, bool):
        raise ValueError("checkpoint boolean input is invalid")
    if not isinstance(budget, CheckpointBudget):
        raise ValueError("checkpoint budget is invalid")
    _non_negative_int(controller_launches, name="controller launch count")
    _non_negative_int(plan_elapsed_seconds, name="plan elapsed seconds")
    _positive_budget(budget.max_controller_launches, name="controller launches")
    _positive_budget(budget.plan_wall_seconds, name="wall seconds")

    if child_completed:
        return CheckpointDecision("finish", "child_completed", fingerprint)
    if controller_launches >= budget.max_controller_launches:
        return CheckpointDecision("stop_budget", "launch_budget_exhausted", fingerprint)
    if plan_elapsed_seconds >= budget.plan_wall_seconds:
        return CheckpointDecision("stop_budget", "wall_budget_exhausted", fingerprint)

    changed = previous is None or progress_fingerprint(previous) != fingerprint
    if timed_out and changed:
        return CheckpointDecision("continue", "productive_timeout", fingerprint)
    if timed_out:
        return CheckpointDecision("stop_stalled", "no_progress_timeout", fingerprint)
    return CheckpointDecision("stop_stalled", "child_stopped_without_completion", fingerprint)


def decide_child_outcome(
    *,
    previous: ProgressSnapshot | None,
    current: ProgressSnapshot,
    timed_out: bool,
    controller_launches: int,
    plan_elapsed_seconds: int,
    budget: CheckpointBudget,
    child_status: Literal["completed", "checkpointed", "blocked", "failed"] | None,
) -> CheckpointDecision:
    """Map every trusted child slice to one canonical parent decision."""
    if child_status not in {None, "completed", "checkpointed", "blocked", "failed"}:
        raise ValueError("child status is invalid")
    baseline = decide_checkpoint(
        previous=previous,
        current=current,
        timed_out=timed_out,
        controller_launches=controller_launches,
        plan_elapsed_seconds=plan_elapsed_seconds,
        budget=budget,
        child_completed=child_status == "completed",
    )
    if timed_out or child_status in {None, "completed"}:
        return baseline
    if child_status == "checkpointed":
        if baseline.action == "stop_budget":
            return baseline
        return CheckpointDecision(
            "checkpoint", "child_checkpointed", baseline.progress_fingerprint,
        )
    if child_status == "failed":
        return CheckpointDecision("fail", "child_failed", baseline.progress_fingerprint)
    return CheckpointDecision("block", "child_blocked", baseline.progress_fingerprint)


def observe_worktree_changes(worktree: Path) -> WorktreeChangeObservation:
    """Observe only bounded Git-dirty facts without exposing names or content."""
    try:
        root_mode = os.lstat(worktree).st_mode
        if stat.S_ISLNK(root_mode) or not stat.S_ISDIR(root_mode):
            raise ValueError("worktree is unsafe")
        staged = subprocess.run(
            [
                "git", "-C", str(worktree), "diff", "--cached", "--raw",
                "--no-abbrev", "-z", "--no-renames", "HEAD", "--",
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        worktree_only = subprocess.run(
            [
                "git", "-C", str(worktree), "ls-files", "--modified", "--deleted",
                "--others", "--exclude-standard", "-z",
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        index_entries = _staged_index_entries(worktree, staged.stdout)
        worktree_entries = {
            entry for entry in worktree_only.stdout.split(b"\0") if entry
        }
        entries = set(index_entries) | worktree_entries
        if not entries:
            return WorktreeChangeObservation(
                False, _CLEAN_WORKTREE_DIGEST, 0, 0, None,
            )
        if len(entries) > MAX_WORKTREE_CHANGED_FILES:
            return _unavailable_observation()
        digest = sha256(b"cpe-worktree-change-v1\0")
        regular_file_count = 0
        total_bytes = 0
        for entry in sorted(entries):
            relative = _safe_relative_path(entry)
            digest.update(len(entry).to_bytes(8, "big"))
            digest.update(entry)
            regular = False
            index_entry = index_entries.get(entry)
            if index_entry is not None:
                index_record, index_bytes = index_entry
                digest.update(b"I\0")
                digest.update(len(index_record).to_bytes(8, "big"))
                digest.update(index_record)
                if index_bytes is not None:
                    regular = True
                    total_bytes += index_bytes
            if entry in worktree_entries:
                path = worktree / relative
                status, content = _read_worktree_entry(worktree, relative, path)
                digest.update(b"W\0")
                digest.update(status)
                if content is not None:
                    regular = True
                    total_bytes += len(content)
                    digest.update(len(content).to_bytes(8, "big"))
                    digest.update(sha256(content).digest())
            if total_bytes > MAX_WORKTREE_TOTAL_BYTES:
                return _unavailable_observation()
            if regular:
                regular_file_count += 1
        return WorktreeChangeObservation(
            True, digest.hexdigest(), regular_file_count, total_bytes, None,
        )
    except (OSError, subprocess.CalledProcessError, ValueError):
        return _unavailable_observation()


def _unavailable_observation() -> WorktreeChangeObservation:
    return WorktreeChangeObservation(
        True, None, 0, None, "dirty_inventory_unavailable",
    )


def _safe_relative_path(entry: bytes) -> Path:
    if not entry or entry.startswith(b"/") or b"\0" in entry:
        raise ValueError("dirty inventory path is invalid")
    relative = Path(os.fsdecode(entry))
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("dirty inventory path is invalid")
    return relative


def _staged_index_entries(
    worktree: Path,
    payload: bytes,
) -> dict[bytes, tuple[bytes, int | None]]:
    fields = payload.split(b"\0")
    if fields and fields[-1] == b"":
        fields.pop()
    if len(fields) % 2:
        raise ValueError("staged inventory is invalid")
    entries: dict[bytes, tuple[bytes, int | None]] = {}
    for position in range(0, len(fields), 2):
        header = fields[position]
        path = fields[position + 1]
        if not header.startswith(b":") or path in entries:
            raise ValueError("staged inventory is invalid")
        metadata = header[1:].split(b" ")
        if len(metadata) != 5:
            raise ValueError("staged inventory is invalid")
        _old_mode, new_mode, _old_object, new_object, status_name = metadata
        if status_name not in {b"A", b"M", b"D", b"T"}:
            raise ValueError("staged inventory is unsafe")
        size: int | None = None
        if status_name != b"D":
            if new_mode not in {b"100644", b"100755"}:
                raise ValueError("staged inventory entry is not regular")
            size = _git_object_size(worktree, new_object)
            if size > MAX_WORKTREE_FILE_BYTES:
                raise ValueError("staged inventory file exceeds limit")
        entries[path] = (header, size)
    return entries


def _git_object_size(worktree: Path, object_id: bytes) -> int:
    if not object_id or any(character not in b"0123456789abcdef" for character in object_id):
        raise ValueError("staged inventory object is invalid")
    completed = subprocess.run(
        ["git", "-C", str(worktree), "cat-file", "-s", os.fsdecode(object_id)],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    raw_size = completed.stdout.strip()
    if not raw_size.isdigit():
        raise ValueError("staged inventory object size is invalid")
    return int(raw_size)


def _read_worktree_entry(worktree: Path, relative: Path, path: Path) -> tuple[bytes, bytes | None]:
    current = worktree
    for component in relative.parts:
        current = current / component
        try:
            mode = os.lstat(current).st_mode
        except FileNotFoundError:
            return b"D\0", None
        if stat.S_ISLNK(mode):
            raise ValueError("dirty inventory symlink is unsafe")
    if not stat.S_ISREG(os.lstat(path).st_mode):
        raise ValueError("dirty inventory entry is not regular")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("dirty inventory entry changed")
        content = bytearray()
        while len(content) <= MAX_WORKTREE_FILE_BYTES:
            chunk = os.read(descriptor, min(65_536, MAX_WORKTREE_FILE_BYTES + 1 - len(content)))
            if not chunk:
                break
            content.extend(chunk)
        if len(content) > MAX_WORKTREE_FILE_BYTES:
            raise ValueError("dirty inventory file exceeds limit")
        return b"F\0", bytes(content)
    finally:
        os.close(descriptor)
