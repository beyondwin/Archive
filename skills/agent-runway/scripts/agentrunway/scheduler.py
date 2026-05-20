from __future__ import annotations

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
