"""Pure helpers for the ``agentlens events`` query path (spec §4.2.4).

Side-effect-free filter/merge primitives so ``commands/events.py`` can keep
its I/O thin. The query reads ``events.jsonl`` directly (JSON-first); the
SQLite index is acceleration only and never authoritative for the body.

Public API
----------
* :func:`event_type` — canonical event type across v1/v2 envelopes.
* :func:`glob_type_match` — fnmatch wrapper, ``None`` pattern matches all.
* :func:`filter_since` — inclusive lower-bound ISO8601 filter.
* :func:`merge_events_by_ts_run` — stable ``(timestamp, run_id)`` ordering across
  multiple per-run event streams.
"""
from __future__ import annotations

import fnmatch
from datetime import datetime
from typing import Iterable, Sequence

from agentlens.time import parse_iso


def _ts_key(ts: str) -> datetime:
    """Parse an event ``ts`` for ordering; fall back to ``datetime.min`` aware."""
    try:
        return parse_iso(ts)
    except (ValueError, TypeError):
        # Treat malformed timestamps as earlier than any well-formed one.
        from datetime import timezone

        return datetime.min.replace(tzinfo=timezone.utc)


def event_type(event: dict) -> str:
    """Return the canonical event type from v2 or v1 event envelopes."""
    value = event.get("event_type") or event.get("type")
    return value if isinstance(value, str) else ""


def _event_ts(event: dict) -> str:
    value = event.get("occurred_at") or event.get("ts")
    return value if isinstance(value, str) else ""


def _event_run_id(event: dict) -> str:
    value = event.get("run_id") or event.get("agentlens_run_id") or event.get("orchestrator_run_id")
    return value if isinstance(value, str) else ""


def glob_type_match(pattern: str | None, event_type: str) -> bool:
    """Return True iff *event_type* matches *pattern*.

    ``None`` means "no filter" (every type passes). Uses :mod:`fnmatch` so
    ``*``, ``prefix.*``, ``*.suffix``, and exact names all work.
    """
    if pattern is None:
        return True
    return fnmatch.fnmatchcase(event_type, pattern)


def filter_since(events: Iterable[dict], since: str | None) -> list[dict]:
    """Return events with event timestamp >= since (parsed UTC compare, inclusive).

    ``None`` cutoff means "no filter". Lexicographic ordering of ISO8601-UTC
    is **not** reliable across fractional and non-fractional timestamps
    (``.`` < ``Z``), so we parse before comparing.
    """
    if since is None:
        return list(events)
    cutoff = _ts_key(since)
    return [e for e in events if _ts_key(_event_ts(e)) >= cutoff]


def merge_events_by_ts_run(streams: Sequence[Sequence[dict]]) -> list[dict]:
    """Merge several event lists into one ordered by ``(timestamp, run_id)``.

    Stable across siblings sharing a timestamp: ties break on ``run_id``
    ascending. Each stream may be in any order — the merge sorts the union.
    Timestamps are parsed into tz-aware ``datetime`` for correct ordering
    across fractional / non-fractional forms.
    """
    merged: list[dict] = []
    for s in streams:
        merged.extend(s)
    merged.sort(key=lambda e: (_ts_key(_event_ts(e)), _event_run_id(e)))
    return merged


__all__ = ["event_type", "filter_since", "glob_type_match", "merge_events_by_ts_run"]
