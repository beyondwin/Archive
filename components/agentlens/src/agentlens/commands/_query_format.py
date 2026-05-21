"""Shared formatting helpers for query commands (task_11).

Text output of query commands MUST NOT leak absolute paths (spec §10.2).
We expose a short ``workspace_id`` form ("git short SHA" style) and helpers
to pick canonical fields with sensible placeholders.
"""
from __future__ import annotations

from typing import Any


def workspace_short(workspace_id: str | None) -> str:
    """Return a compact ``workspace_id`` display label.

    Format: first 11 characters (``ws_`` prefix + 8 hex chars), mirroring
    the git short-SHA convention. Returns ``"-"`` for missing/empty input.
    """
    if not workspace_id:
        return "-"
    return workspace_id[:11]


def field(row: dict[str, Any] | None, key: str, default: str = "-") -> str:
    """Return ``row[key]`` as a printable string, or *default* for missing."""
    if row is None:
        return default
    val = row.get(key)
    if val is None or val == "":
        return default
    return str(val)


def render_one_line(row: dict[str, Any]) -> str:
    """Render a single run row as the canonical ``latest``/``status`` line.

    Columns: run_id  workspace_short  agent_outcome  eval_status  sealed_phase
    """
    return (
        f"{field(row, 'run_id')}  "
        f"{workspace_short(row.get('workspace_id'))}  "
        f"{field(row, 'agent_outcome')}  "
        f"{field(row, 'eval_status')}  "
        f"{field(row, 'sealed_phase')}"
    )


__all__ = ["field", "render_one_line", "workspace_short"]
