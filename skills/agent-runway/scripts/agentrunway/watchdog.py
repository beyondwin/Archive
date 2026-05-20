from __future__ import annotations

from datetime import datetime, timezone


def classify_stall(started_at: datetime, *, timeout_seconds: int) -> str:
    now = datetime.now(timezone.utc)
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    if (now - started_at).total_seconds() > timeout_seconds:
        return "wall_clock_timeout"
    return "healthy"
