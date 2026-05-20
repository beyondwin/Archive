from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .db import AgentRunwayDb
from .models import ProcessSnapshot
from .reconciliation import plan_reconciliation


def classify_stall(started_at: datetime, *, timeout_seconds: int) -> str:
    now = datetime.now(timezone.utc)
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    if (now - started_at).total_seconds() > timeout_seconds:
        return "wall_clock_timeout"
    return "healthy"


def classify_worker_snapshot(snapshot: ProcessSnapshot, *, result_exists: bool) -> str:
    if snapshot.state == "timed_out":
        return "timeout"
    if snapshot.state == "missing":
        return "stalled"
    if snapshot.state == "exited" and snapshot.returncode not in {0, None}:
        return "adapter_crashed"
    if snapshot.state == "exited" and snapshot.returncode == 0 and not result_exists:
        return "malformed_result"
    if snapshot.state == "running":
        return "running"
    return "unknown"


def plan_watchdog_actions(*, run_id: str, run_dir: Path, db: AgentRunwayDb) -> dict[str, Any]:
    return plan_reconciliation(run_id=run_id, run_dir=run_dir, db=db)
