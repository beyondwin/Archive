"""Tests for agentlens.store.query (spec §S1.6.9, §5.8a).

Covers SQLite happy path + fallback (missing, corrupt) for ``latest``,
plus the failures / risks / list_runs / get_run / full_scan_runs surface.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agentlens.store import query
from agentlens.store.query import (
    failures,
    full_scan_runs,
    get_run,
    latest,
    list_failures,
    list_risks,
    list_runs,
    latest_run,
    risks,
)
from agentlens.store.sqlite_index import rebuild_index


WS_A = "ws_aaaaaaaaaaaaaaa1"
WS_B = "ws_bbbbbbbbbbbbbbb2"
RUN_OLD = "run_20260101_000000_aaaaaa"
RUN_NEW = "run_20260301_000000_bbbbbb"
RUN_OTHER_WS = "run_20260201_000000_cccccc"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_run(
    home: Path,
    run_id: str,
    *,
    workspace_id: str = WS_A,
    started_at: str = "2026-01-01T00:00:00Z",
    ended_at: str | None = "2026-01-01T00:00:05Z",
    agent_outcome: str | None = "success",
    eval_status: str | None = "passed",
    sealed_phase: str = "final",
    failures_list: list[dict] | None = None,
    residual_risks: list[dict] | None = None,
    evaluated_at: str = "1970-01-01T00:00:00Z",
    skip_eval: bool = False,
    skip_final: bool = False,
    skip_manifest: bool = False,
    bad_run_json: bool = False,
) -> Path:
    run_dir = home / "runs" / workspace_id / run_id
    run_dir.mkdir(parents=True)
    if bad_run_json:
        (run_dir / "run.json").write_text("{not-json", encoding="utf-8")
        return run_dir
    run_doc = {
        "schema": "agentlens.run.v1",
        "run_id": run_id,
        "workspace_id": workspace_id,
        "started_at": started_at,
        "agent": {"name": "generic", "mode": "cli"},
        "workspace": {
            "root_label": "./workspace",
            "root_hash": "sha256:" + "0" * 64,
            "id_basis": "path",
        },
        "recording": {"mode": "minimal", "adapter": "generic"},
    }
    (run_dir / "run.json").write_text(json.dumps(run_doc), encoding="utf-8")

    if not skip_final:
        final_doc = {
            "schema": "agentlens.final.v1",
            "run_id": run_id,
            "ended_at": ended_at,
            "agent_outcome": agent_outcome,
            "residual_risks": residual_risks or [],
        }
        (run_dir / "final.json").write_text(json.dumps(final_doc), encoding="utf-8")

    if not skip_eval:
        eval_doc = {
            "schema": "agentlens.eval.v1",
            "run_id": run_id,
            "evaluated_at": evaluated_at,
            "status": eval_status,
            "agent_outcome": agent_outcome,
            "checks": [{"name": "schema_valid", "status": "passed"}],
            "failures": failures_list or [],
        }
        (run_dir / "eval.json").write_text(json.dumps(eval_doc), encoding="utf-8")

    if not skip_manifest:
        manifest_doc = {
            "schema": "agentlens.manifest.v1",
            "run_id": run_id,
            "sealed_at": "2026-01-01T00:00:10Z",
            "sealed": True,
            "sealed_phase": sealed_phase,
            "files": [],
            "redaction": {},
        }
        (run_dir / "manifest.json").write_text(json.dumps(manifest_doc), encoding="utf-8")

    return run_dir


def _build_two_runs(home: Path) -> None:
    _write_run(home, RUN_OLD, workspace_id=WS_A, started_at="2026-01-01T00:00:00Z")
    _write_run(home, RUN_NEW, workspace_id=WS_A, started_at="2026-03-01T00:00:00Z")


# ---------------------------------------------------------------------------
# latest() — SQLite happy path + fallback
# ---------------------------------------------------------------------------


def test_latest_sqlite_path_returns_newest(tmp_path: Path) -> None:
    _build_two_runs(tmp_path)
    rebuild_index(tmp_path)
    row = latest(tmp_path)
    assert row is not None
    assert row["run_id"] == RUN_NEW
    assert row["workspace_id"] == WS_A
    assert row["started_at"] == "2026-03-01T00:00:00Z"


def test_latest_fallback_when_db_missing(tmp_path: Path) -> None:
    _build_two_runs(tmp_path)
    rebuild_index(tmp_path)
    (tmp_path / "index.db").unlink()
    row = latest(tmp_path)
    assert row is not None
    assert row["run_id"] == RUN_NEW


def test_latest_fallback_when_db_corrupt(tmp_path: Path) -> None:
    _build_two_runs(tmp_path)
    rebuild_index(tmp_path)
    # Inject garbage bytes — SQLite open OR query should fail.
    (tmp_path / "index.db").write_bytes(b"NOT A SQLITE FILE \x00\x01\x02" * 64)
    row = latest(tmp_path)
    assert row is not None
    assert row["run_id"] == RUN_NEW


def test_latest_workspace_filter_sqlite(tmp_path: Path) -> None:
    _build_two_runs(tmp_path)
    _write_run(tmp_path, RUN_OTHER_WS, workspace_id=WS_B, started_at="2026-02-01T00:00:00Z")
    rebuild_index(tmp_path)
    row = latest(tmp_path, workspace_id=WS_B)
    assert row is not None
    assert row["run_id"] == RUN_OTHER_WS
    # Filter on WS_A only returns WS_A runs
    row_a = latest(tmp_path, workspace_id=WS_A)
    assert row_a is not None
    assert row_a["run_id"] == RUN_NEW


def test_latest_workspace_filter_fallback(tmp_path: Path) -> None:
    _build_two_runs(tmp_path)
    _write_run(tmp_path, RUN_OTHER_WS, workspace_id=WS_B, started_at="2026-02-01T00:00:00Z")
    # No SQLite index built — pure fallback.
    row = latest(tmp_path, workspace_id=WS_B)
    assert row is not None
    assert row["run_id"] == RUN_OTHER_WS


def test_latest_empty_home_returns_none(tmp_path: Path) -> None:
    assert latest(tmp_path) is None


# ---------------------------------------------------------------------------
# failures()
# ---------------------------------------------------------------------------


def test_failures_flattens_eval_failures(tmp_path: Path) -> None:
    fails_a = [
        {
            "category": "MISSING_FINAL",
            "severity": "blocker",
            "source": "evaluator",
            "blame_scope": "agent",
            "summary": "no final.json",
        }
    ]
    fails_b = [
        {
            "category": "UNKNOWN",
            "severity": "minor",
            "source": "evaluator",
            "blame_scope": "unknown",
            "summary": "x",
        }
    ]
    _write_run(
        tmp_path,
        RUN_OLD,
        started_at=_iso(datetime.now(timezone.utc) - timedelta(days=1)),
        failures_list=fails_a,
        evaluated_at=_iso(datetime.now(timezone.utc) - timedelta(days=1)),
    )
    _write_run(
        tmp_path,
        RUN_NEW,
        started_at=_iso(datetime.now(timezone.utc)),
        failures_list=fails_b,
        evaluated_at=_iso(datetime.now(timezone.utc)),
    )
    result = failures(tmp_path)
    assert len(result) == 2
    categories = sorted(f["category"] for f in result)
    assert categories == ["MISSING_FINAL", "UNKNOWN"]
    # Each carries run_id + workspace_id metadata.
    for f in result:
        assert "run_id" in f
        assert "workspace_id" in f


def test_failures_same_result_with_or_without_sqlite(tmp_path: Path) -> None:
    _write_run(
        tmp_path,
        RUN_OLD,
        started_at=_iso(datetime.now(timezone.utc)),
        failures_list=[
            {
                "category": "MISSING_FINAL",
                "severity": "blocker",
                "source": "evaluator",
                "blame_scope": "agent",
                "summary": "x",
            }
        ],
        evaluated_at=_iso(datetime.now(timezone.utc)),
    )
    rebuild_index(tmp_path)
    with_db = failures(tmp_path)
    (tmp_path / "index.db").unlink()
    without_db = failures(tmp_path)
    assert with_db == without_db
    # Corrupt DB → identical result.
    (tmp_path / "index.db").write_bytes(b"\x00\x01\x02garbage" * 32)
    corrupt_db = failures(tmp_path)
    assert with_db == corrupt_db


# ---------------------------------------------------------------------------
# risks()
# ---------------------------------------------------------------------------


def test_risks_aggregates_three_sources(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc)
    # Run with residual_risks (from final.json)
    _write_run(
        tmp_path,
        RUN_OLD,
        started_at=_iso(now - timedelta(days=2)),
        residual_risks=[{"summary": "watch for drift"}],
    )
    # Run with eval failures
    _write_run(
        tmp_path,
        RUN_NEW,
        started_at=_iso(now - timedelta(days=1)),
        failures_list=[
            {
                "category": "MISSING_FINAL",
                "severity": "blocker",
                "source": "evaluator",
                "blame_scope": "agent",
                "summary": "no final",
            }
        ],
    )
    # Run with recording_incomplete manifest
    _write_run(
        tmp_path,
        RUN_OTHER_WS,
        workspace_id=WS_B,
        started_at=_iso(now),
        sealed_phase="recording_incomplete",
    )
    result = risks(tmp_path)
    sources = sorted(r["source"] for r in result)
    assert sources == ["eval.failures", "final.residual_risks", "manifest.sealed_phase"]
    recording_incomplete = [r for r in result if r["source"] == "manifest.sealed_phase"]
    assert recording_incomplete[0]["category"] == "RECORDING_INCOMPLETE"
    assert recording_incomplete[0]["run_id"] == RUN_OTHER_WS


def test_risks_includes_schema_invalid(tmp_path: Path) -> None:
    _write_run(tmp_path, RUN_NEW, started_at=_iso(datetime.now(timezone.utc)))
    # Schema-invalid run.json
    bad_run = "run_20260401_000000_dddddd"
    _write_run(tmp_path, bad_run, bad_run_json=True)
    result = risks(tmp_path)
    schema_invalid = [r for r in result if r.get("category") == "SCHEMA_INVALID"]
    assert len(schema_invalid) == 1
    assert schema_invalid[0]["source"] == "store.full_scan"


# ---------------------------------------------------------------------------
# full_scan_runs() — schema_invalid surfacing
# ---------------------------------------------------------------------------


def test_full_scan_runs_surfaces_invalid_as_risk(tmp_path: Path) -> None:
    _write_run(tmp_path, RUN_NEW, started_at=_iso(datetime.now(timezone.utc)))
    bad_run = "run_20260401_000000_dddddd"
    _write_run(tmp_path, bad_run, bad_run_json=True)
    result = full_scan_runs(tmp_path)
    invalid = [r for r in result if r.get("schema_invalid")]
    assert len(invalid) == 1
    assert invalid[0]["run_id"] == bad_run
    # Healthy run is a full dict
    healthy = [r for r in result if not r.get("schema_invalid")]
    assert len(healthy) == 1
    assert healthy[0]["run_id"] == RUN_NEW


# ---------------------------------------------------------------------------
# get_run()
# ---------------------------------------------------------------------------


def test_get_run_returns_merged_dict(tmp_path: Path) -> None:
    _write_run(tmp_path, RUN_NEW)
    row = get_run(tmp_path, RUN_NEW)
    assert row is not None
    assert row["run_id"] == RUN_NEW
    # run.json + final.json + eval.json + manifest.json merged
    assert row.get("ended_at") == "2026-01-01T00:00:05Z"
    assert row.get("agent_outcome") == "success"
    assert row.get("status") == "passed"  # from eval.json
    assert row.get("sealed_phase") == "final"


def test_get_run_missing_returns_none(tmp_path: Path) -> None:
    _write_run(tmp_path, RUN_NEW)
    assert get_run(tmp_path, "no_such_run") is None


# ---------------------------------------------------------------------------
# list_runs()
# ---------------------------------------------------------------------------


def test_list_runs_no_filter_returns_all(tmp_path: Path) -> None:
    _build_two_runs(tmp_path)
    rows = list_runs(tmp_path)
    run_ids = sorted(r["run_id"] for r in rows if not r.get("schema_invalid"))
    assert run_ids == sorted([RUN_OLD, RUN_NEW])


def test_list_runs_filter_by_workspace(tmp_path: Path) -> None:
    _build_two_runs(tmp_path)
    _write_run(tmp_path, RUN_OTHER_WS, workspace_id=WS_B)
    rows = list_runs(tmp_path, {"workspace_id": WS_B})
    assert len(rows) == 1
    assert rows[0]["run_id"] == RUN_OTHER_WS


def test_list_runs_filter_by_agent_outcome(tmp_path: Path) -> None:
    _write_run(tmp_path, RUN_OLD, agent_outcome="success")
    _write_run(tmp_path, RUN_NEW, agent_outcome="failed")
    rows = list_runs(tmp_path, {"agent_outcome": "failed"})
    assert len(rows) == 1
    assert rows[0]["run_id"] == RUN_NEW


def test_list_runs_unknown_filter_key_ignored(tmp_path: Path) -> None:
    _build_two_runs(tmp_path)
    rows = list_runs(tmp_path, {"bogus_key": "whatever"})
    assert len(rows) == 2


# ---------------------------------------------------------------------------
# Plan aliases
# ---------------------------------------------------------------------------


def test_plan_aliases_point_to_canonical() -> None:
    assert latest_run is latest
    assert list_failures is failures
    assert list_risks is risks


def test_module_exposes_expected_api() -> None:
    for name in (
        "latest",
        "failures",
        "risks",
        "full_scan_runs",
        "get_run",
        "list_runs",
        "latest_run",
        "list_failures",
        "list_risks",
    ):
        assert hasattr(query, name), f"query.{name} missing"
