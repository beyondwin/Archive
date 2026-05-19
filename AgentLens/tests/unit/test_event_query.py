"""Unit tests for ``agentlens.store.event_query`` pure helpers (spec §4.2.4).

Pure-function tests: no I/O. Cover the three primitives that
``commands/events.py`` composes:
* ``glob_type_match`` — fnmatch-based event-type filter
* ``filter_since`` — ISO8601-UTC lower-bound filter (inclusive)
* ``merge_events_by_ts_run`` — deterministic ordering across siblings
"""
from __future__ import annotations

from agentlens.store.event_query import (
    filter_since,
    glob_type_match,
    merge_events_by_ts_run,
)


def _evt(ts: str, run_id: str = "run_a", type_: str = "kws-cme.task_started") -> dict:
    return {
        "schema": "agentlens.event.v1",
        "event_id": "evt_" + ("0" * 12),
        "run_id": run_id,
        "ts": ts,
        "type": type_,
        "payload": {},
    }


# ---------------------------------------------------------------------------
# glob_type_match
# ---------------------------------------------------------------------------

def test_glob_type_match_namespace_wildcard() -> None:
    assert glob_type_match("kws-cme.*", "kws-cme.task_started") is True


def test_glob_type_match_namespace_wildcard_negative() -> None:
    assert glob_type_match("kws-cme.*", "other.evt") is False


def test_glob_type_match_exact() -> None:
    assert glob_type_match("run.started", "run.started") is True
    assert glob_type_match("run.started", "run.finalized") is False


def test_glob_type_match_star() -> None:
    assert glob_type_match("*", "any.event") is True


def test_glob_type_match_suffix() -> None:
    assert glob_type_match("*.started", "run.started") is True
    assert glob_type_match("*.started", "kws-cme.task_started") is False


def test_glob_type_match_none_pattern_passes_all() -> None:
    # No pattern means no filtering — every type passes.
    assert glob_type_match(None, "kws-cme.task_started") is True


# ---------------------------------------------------------------------------
# filter_since
# ---------------------------------------------------------------------------

def test_filter_since_inclusive_cutoff() -> None:
    events = [
        _evt("2026-05-18T23:59:59Z"),
        _evt("2026-05-19T00:00:00Z"),
        _evt("2026-05-19T00:00:01Z"),
    ]
    out = filter_since(events, "2026-05-19T00:00:00Z")
    assert [e["ts"] for e in out] == [
        "2026-05-19T00:00:00Z",
        "2026-05-19T00:00:01Z",
    ]


def test_filter_since_none_returns_all() -> None:
    events = [_evt("2026-05-18T00:00:00Z"), _evt("2026-05-19T00:00:00Z")]
    assert filter_since(events, None) == events


# ---------------------------------------------------------------------------
# merge_events_by_ts_run
# ---------------------------------------------------------------------------

def test_merge_orders_by_ts_then_run_id() -> None:
    a = _evt("2026-05-19T00:00:00Z", run_id="run_b")
    b = _evt("2026-05-19T00:00:00Z", run_id="run_a")
    c = _evt("2026-05-19T00:00:01Z", run_id="run_b")
    d = _evt("2026-05-19T00:00:00.500Z", run_id="run_a")
    merged = merge_events_by_ts_run([[a, c], [b, d]])
    assert [(e["ts"], e["run_id"]) for e in merged] == [
        ("2026-05-19T00:00:00Z", "run_a"),
        ("2026-05-19T00:00:00Z", "run_b"),
        ("2026-05-19T00:00:00.500Z", "run_a"),
        ("2026-05-19T00:00:01Z", "run_b"),
    ]


def test_merge_handles_empty_inputs() -> None:
    assert merge_events_by_ts_run([]) == []
    assert merge_events_by_ts_run([[], []]) == []
