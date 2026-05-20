from __future__ import annotations

from collections import Counter


def format_run_status(run: dict[str, object]) -> str:
    tasks = run.get("tasks") if isinstance(run.get("tasks"), list) else []
    counts = Counter(str(task.get("status", "unknown")) for task in tasks if isinstance(task, dict))
    suffix = " ".join(f"{key}={value}" for key, value in sorted(counts.items()))
    return f"{run.get('run_id')} status={run.get('status')} {suffix}".strip()
