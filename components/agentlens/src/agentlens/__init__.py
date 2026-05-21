"""AgentLens — agent-agnostic recording/evaluation contract (v0)."""
from __future__ import annotations

from .ids import (
    compute_workspace_id,
    make_event_id,
    make_run_id,
    run_id,
)
from .time import (
    normalize_for_diff,
    now_iso,
    parse_iso,
    utc_now_iso,
    validate_iso8601_utc,
)

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "compute_workspace_id",
    "make_event_id",
    "make_run_id",
    "normalize_for_diff",
    "now_iso",
    "parse_iso",
    "run_id",
    "utc_now_iso",
    "validate_iso8601_utc",
]
