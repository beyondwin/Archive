"""Canonical durable-progress snapshots and checkpoint decisions."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Literal


@dataclass(frozen=True)
class ProgressSnapshot:
    head: str
    completed_task_ids: tuple[str, ...]
    current_task_id: str | None
    accepted_review_ids: tuple[str, ...]
    closed_finding_ids: tuple[str, ...]


@dataclass(frozen=True)
class CheckpointBudget:
    max_progress_checkpoints: int
    max_controller_launches: int
    plan_wall_seconds: int


@dataclass(frozen=True)
class CheckpointDecision:
    action: Literal["continue", "stop_stalled", "stop_budget", "finish"]
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
    payload = {
        "head": snapshot.head,
        "completed_task_ids": _identifier_set(
            snapshot.completed_task_ids, name="completed task IDs"
        ),
        "current_task_id": snapshot.current_task_id,
        "accepted_review_ids": _identifier_set(
            snapshot.accepted_review_ids, name="accepted review IDs"
        ),
        "closed_finding_ids": _identifier_set(
            snapshot.closed_finding_ids, name="closed finding IDs"
        ),
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
    consecutive_no_progress: int,
    progress_checkpoints: int,
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
    _non_negative_int(consecutive_no_progress, name="consecutive no-progress count")
    _non_negative_int(progress_checkpoints, name="progress checkpoint count")
    _non_negative_int(controller_launches, name="controller launch count")
    _non_negative_int(plan_elapsed_seconds, name="plan elapsed seconds")
    _positive_budget(budget.max_progress_checkpoints, name="progress checkpoints")
    _positive_budget(budget.max_controller_launches, name="controller launches")
    _positive_budget(budget.plan_wall_seconds, name="wall seconds")

    if child_completed:
        return CheckpointDecision("finish", "child_completed", fingerprint)
    if progress_checkpoints >= budget.max_progress_checkpoints:
        return CheckpointDecision("stop_budget", "checkpoint_budget_exhausted", fingerprint)
    if controller_launches >= budget.max_controller_launches:
        return CheckpointDecision("stop_budget", "launch_budget_exhausted", fingerprint)
    if plan_elapsed_seconds >= budget.plan_wall_seconds:
        return CheckpointDecision("stop_budget", "wall_budget_exhausted", fingerprint)

    changed = previous is None or progress_fingerprint(previous) != fingerprint
    if timed_out and changed:
        return CheckpointDecision("continue", "productive_timeout", fingerprint)
    if timed_out and consecutive_no_progress >= 1:
        return CheckpointDecision("stop_stalled", "second_no_progress_slice", fingerprint)
    if timed_out:
        return CheckpointDecision("continue", "first_no_progress_slice", fingerprint)
    return CheckpointDecision("stop_stalled", "child_stopped_without_completion", fingerprint)
