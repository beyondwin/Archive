from __future__ import annotations

from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .models import TaskSpec


def resource_conflicts(tasks: list[TaskSpec]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for task in tasks:
        for key in task.resource_keys:
            grouped[key].append(task.task_id)
    return {key: ids for key, ids in grouped.items() if len(ids) > 1}


@contextmanager
def runtime_slot(lock_root: Path, runtime: str, holder: str) -> Iterator[Path]:
    lock_root.mkdir(parents=True, exist_ok=True)
    path = lock_root / f"{runtime}.{holder}.slot"
    path.write_text(holder, encoding="utf-8")
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)
