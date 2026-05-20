from __future__ import annotations

from collections import defaultdict

from .models import FileClaim, TaskSpec


class ClaimConflictError(ValueError):
    pass


def _write_conflicts(left: FileClaim, right: FileClaim) -> bool:
    if left.path != right.path:
        return False
    if "forbidden" in {left.mode, right.mode}:
        return True
    writers = {"owned"}
    if left.mode in writers and right.mode in writers:
        return True
    if left.mode == "shared_append" and right.mode == "shared_append":
        return False
    return False


def validate_claims_compatible(tasks: list[TaskSpec]) -> None:
    seen: list[tuple[str, FileClaim]] = []
    for task in tasks:
        for claim in task.file_claims:
            for other_task, other in seen:
                if _write_conflicts(claim, other):
                    raise ClaimConflictError(f"{task.task_id} conflicts with {other_task} on {claim.path}")
            seen.append((task.task_id, claim))


def claims_by_path(tasks: list[TaskSpec]) -> dict[str, list[tuple[str, str]]]:
    grouped: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for task in tasks:
        for claim in task.file_claims:
            grouped[claim.path].append((task.task_id, claim.mode))
    return dict(grouped)
