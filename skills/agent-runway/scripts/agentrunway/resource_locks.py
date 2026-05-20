from __future__ import annotations

from collections import defaultdict

from .models import TaskSpec


def resource_conflicts(tasks: list[TaskSpec]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for task in tasks:
        for key in task.resource_keys:
            grouped[key].append(task.task_id)
    return {key: ids for key, ids in grouped.items() if len(ids) > 1}
