from __future__ import annotations

import fnmatch

from .models import TaskSpec


RISK_ORDER = {"high": 0, "medium": 1, "low": 2}


def schedule_waves(tasks: list[TaskSpec]) -> list[tuple[str, ...]]:
    by_id = {task.task_id: task for task in tasks}
    remaining = set(by_id)
    completed: set[str] = set()
    waves: list[tuple[str, ...]] = []
    while remaining:
        ready = [by_id[task_id] for task_id in remaining if set(by_id[task_id].dependencies) <= completed]
        if not ready:
            raise ValueError("cycle detected in task dependencies")
        if any(task.serial for task in ready):
            ready = ready[:1]
        ready.sort(key=lambda task: (RISK_ORDER.get(task.risk, 9), task.task_id))
        ids = tuple(task.task_id for task in ready)
        waves.append(ids)
        completed.update(ids)
        remaining.difference_update(ids)
    return waves


def ready_tasks_after_checkpoints(
    tasks: list[TaskSpec],
    *,
    completed_checkpoints: set[str],
    completed_tasks: set[str],
) -> list[TaskSpec]:
    ready = [
        task
        for task in tasks
        if task.task_id not in completed_tasks and set(task.dependencies) <= completed_checkpoints
    ]
    return sorted(ready, key=lambda task: (RISK_ORDER.get(task.risk, 9), task.task_id))


def schedule_safe_wave(ready: list[TaskSpec]) -> list[TaskSpec]:
    ordered = sorted(ready, key=lambda task: (RISK_ORDER.get(task.risk, 9), task.task_id))
    wave: list[TaskSpec] = []
    for task in ordered:
        if any(_tasks_conflict(task, selected) for selected in wave):
            if not wave:
                return [task]
            continue
        wave.append(task)
    return wave


def _claim_patterns(task: TaskSpec) -> list[str]:
    return [claim.path for claim in task.file_claims if claim.mode in {"owned", "shared_append"}]


def _has_broad_claim(task: TaskSpec) -> bool:
    return any(any(ch in claim for ch in "*?[") for claim in _claim_patterns(task))


def _claim_overlaps(left: str, right: str) -> bool:
    if left == right:
        return True
    if any(ch in left for ch in "*?[") and fnmatch.fnmatch(right, left):
        return True
    if any(ch in right for ch in "*?[") and fnmatch.fnmatch(left, right):
        return True
    if left.endswith("/**") and right.startswith(left[:-3]):
        return True
    if right.endswith("/**") and left.startswith(right[:-3]):
        return True
    return False


def _tasks_conflict(left: TaskSpec, right: TaskSpec) -> bool:
    if left.serial or right.serial:
        return True
    if left.risk == "high" or right.risk == "high":
        return True
    if _has_broad_claim(left) or _has_broad_claim(right):
        return True
    for left_claim in _claim_patterns(left):
        for right_claim in _claim_patterns(right):
            if _claim_overlaps(left_claim, right_claim):
                return True
    return bool(set(left.resource_keys) & set(right.resource_keys))
