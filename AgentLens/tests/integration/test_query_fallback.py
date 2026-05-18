"""End-to-end SQLite-fallback integration for query CLI verbs (spec §S1.6.9,
§5.8a, §10.4).

The query facade (:mod:`agentlens.store.query`) prefers ``index.db`` for
performance but must transparently full-scan the runs tree when SQLite is
absent or corrupt. This test exercises that contract through the *CLI*
verbs ``latest``, ``status``, ``show``, ``failures``, ``risks`` — i.e. the
exact path an operator hits when ``~/.agentlens/index.db`` is missing
because they wiped it, never ran the indexer, or the file is corrupt.

Unit-level coverage of the facade itself lives in
``tests/unit/test_query_fallback.py``; this integration test focuses on
the operator surface (Typer commands, formatted output, exit codes).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agentlens.cli import app


# ---------------------------------------------------------------------------
# Fixture data — minimal but realistic run trees written directly to disk.
# ---------------------------------------------------------------------------

WS_A = "ws_aaaaaaaaaaaaaaa1"
WS_B = "ws_bbbbbbbbbbbbbbb2"
RUN_OLD = "run_20260101_000000_aaaaaa"
RUN_NEW = "run_20260301_000000_bbbbbb"
RUN_FAIL = "run_20260201_000000_cccccc"


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_run(
    home: Path,
    run_id: str,
    *,
    workspace_id: str = WS_A,
    started_at: str = "2026-01-01T00:00:00Z",
    ended_at: str | None = "2026-01-01T00:00:05Z",
    agent_outcome: str = "success",
    eval_status: str = "passed",
    sealed_phase: str = "final",
    failures_list: list[dict] | None = None,
    residual_risks: list[dict] | None = None,
    evaluated_at: str = "2026-01-01T00:00:10Z",
) -> Path:
    """Write a fully-formed run tree (run.json + final.json + eval.json +
    manifest.json) so the full-scan path yields a canonical row."""
    run_dir = home / "runs" / workspace_id / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(
        json.dumps(
            {
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
                "recording": {"mode": "minimal", "adapter": "generic_shim"},
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "final.json").write_text(
        json.dumps(
            {
                "schema": "agentlens.final.v1",
                "run_id": run_id,
                "ended_at": ended_at,
                "agent_outcome": agent_outcome,
                "residual_risks": residual_risks or [],
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "eval.json").write_text(
        json.dumps(
            {
                "schema": "agentlens.eval.v1",
                "run_id": run_id,
                "evaluated_at": evaluated_at,
                "status": eval_status,
                "agent_outcome": agent_outcome,
                "checks": [{"name": "schema_valid", "status": "passed"}],
                "failures": failures_list or [],
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schema": "agentlens.manifest.v1",
                "run_id": run_id,
                "sealed_at": "2026-01-01T00:00:15Z",
                "sealed": True,
                "sealed_phase": sealed_phase,
                "files": [],
                "redaction": {},
            }
        ),
        encoding="utf-8",
    )
    return run_dir


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture()
def home_with_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Pin AGENTLENS_HOME and populate it with three runs.

    Critically, **no** ``index.db`` is created — the query commands MUST
    full-scan to surface correct results.
    """
    home = tmp_path / "agentlens_home"
    home.mkdir()
    monkeypatch.setenv("AGENTLENS_HOME", str(home))

    now = datetime.now(timezone.utc)
    # Older successful run on WS_A.
    _write_run(
        home,
        RUN_OLD,
        workspace_id=WS_A,
        started_at=_iso(now - timedelta(days=10)),
        agent_outcome="success",
        eval_status="passed",
    )
    # Newest successful run on WS_A (latest target).
    _write_run(
        home,
        RUN_NEW,
        workspace_id=WS_A,
        started_at=_iso(now - timedelta(hours=1)),
        agent_outcome="success",
        eval_status="passed",
    )
    # Failure run on WS_B with both an eval failure and a residual_risk.
    _write_run(
        home,
        RUN_FAIL,
        workspace_id=WS_B,
        started_at=_iso(now - timedelta(days=2)),
        agent_outcome="failed",
        eval_status="failed",
        failures_list=[
            {
                "category": "MISSING_FINAL",
                "severity": "blocker",
                "source": "evaluator",
                "blame_scope": "agent",
                "summary": "no final.json detected",
            }
        ],
        residual_risks=[{"summary": "watch for drift", "category": "DRIFT"}],
    )

    # Sanity: NO index.db. The CLI must fall back to full-scan.
    assert not (home / "index.db").exists()
    return home


# ---------------------------------------------------------------------------
# latest — newest run surfaced via full-scan
# ---------------------------------------------------------------------------


def test_latest_works_without_sqlite_index(
    runner: CliRunner, home_with_runs: Path
) -> None:
    result = runner.invoke(app, ["latest", "--format", "json"])
    assert result.exit_code == 0, result.stdout
    row = json.loads(result.stdout)
    assert row is not None
    assert row["run_id"] == RUN_NEW
    assert row["workspace_id"] == WS_A
    # Index file MUST still be absent (full-scan should not create it).
    assert not (home_with_runs / "index.db").exists()


def test_latest_text_format_no_sqlite(
    runner: CliRunner, home_with_runs: Path
) -> None:
    result = runner.invoke(app, ["latest"])
    assert result.exit_code == 0, result.stdout
    # One-line format: run_id begins each line.
    line = result.stdout.strip().splitlines()[-1]
    assert RUN_NEW in line


# ---------------------------------------------------------------------------
# status — full list including in-progress (none here, but all three runs)
# ---------------------------------------------------------------------------


def test_status_lists_all_runs_without_sqlite(
    runner: CliRunner, home_with_runs: Path
) -> None:
    result = runner.invoke(app, ["status", "--format", "json"])
    assert result.exit_code == 0, result.stdout
    rows = json.loads(result.stdout)
    run_ids = sorted(r["run_id"] for r in rows)
    assert run_ids == sorted([RUN_OLD, RUN_NEW, RUN_FAIL])


# ---------------------------------------------------------------------------
# show — single run resolved without index
# ---------------------------------------------------------------------------


def test_show_latest_without_sqlite(
    runner: CliRunner, home_with_runs: Path
) -> None:
    result = runner.invoke(app, ["show", "--latest", "--format", "json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["run_id"] == RUN_NEW
    assert payload["agent_outcome"] == "success"
    assert payload["eval_status"] == "passed"
    assert payload["sealed_phase"] == "final"


def test_show_specific_run_without_sqlite(
    runner: CliRunner, home_with_runs: Path
) -> None:
    """``show <run_id>`` must resolve via full-scan when no index exists."""
    result = runner.invoke(app, ["show", RUN_FAIL, "--format", "json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["run_id"] == RUN_FAIL
    assert payload["agent_outcome"] == "failed"
    # The failure list is included.
    assert any(
        f.get("category") == "MISSING_FINAL" for f in payload.get("failures", [])
    )


# ---------------------------------------------------------------------------
# failures — eval failures aggregated from disk (no index path)
# ---------------------------------------------------------------------------


def test_failures_returns_eval_failures_without_sqlite(
    runner: CliRunner, home_with_runs: Path
) -> None:
    result = runner.invoke(app, ["failures", "--format", "json"])
    assert result.exit_code == 0, result.stdout
    items = json.loads(result.stdout)
    assert len(items) == 1
    f = items[0]
    assert f["category"] == "MISSING_FINAL"
    assert f["run_id"] == RUN_FAIL


# ---------------------------------------------------------------------------
# risks — aggregated indicators from three sources
# ---------------------------------------------------------------------------


def test_risks_aggregates_without_sqlite(
    runner: CliRunner, home_with_runs: Path
) -> None:
    result = runner.invoke(app, ["risks", "--format", "json"])
    assert result.exit_code == 0, result.stdout
    items = json.loads(result.stdout)
    # Expect at least the residual_risk + eval.failures entries for RUN_FAIL.
    sources = {r.get("source") for r in items}
    assert "final.residual_risks" in sources
    assert "eval.failures" in sources
    # RUN_FAIL should be referenced.
    assert any(r.get("run_id") == RUN_FAIL for r in items)


# ---------------------------------------------------------------------------
# Corrupt index — same answers, fallback still triggers
# ---------------------------------------------------------------------------


def test_query_commands_survive_corrupt_index(
    runner: CliRunner, home_with_runs: Path
) -> None:
    """Inject garbage bytes at ``index.db`` and confirm every command still
    returns the canonical answer via full-scan."""
    (home_with_runs / "index.db").write_bytes(b"NOT A SQLITE FILE \x00\x01\x02" * 64)

    latest = runner.invoke(app, ["latest", "--format", "json"])
    assert latest.exit_code == 0
    assert json.loads(latest.stdout)["run_id"] == RUN_NEW

    status = runner.invoke(app, ["status", "--format", "json"])
    assert status.exit_code == 0
    status_rows = json.loads(status.stdout)
    assert len(status_rows) == 3

    failures = runner.invoke(app, ["failures", "--format", "json"])
    assert failures.exit_code == 0
    assert len(json.loads(failures.stdout)) == 1

    risks = runner.invoke(app, ["risks", "--format", "json"])
    assert risks.exit_code == 0
    risk_items = json.loads(risks.stdout)
    assert any(r.get("source") == "final.residual_risks" for r in risk_items)

    show = runner.invoke(app, ["show", "--latest", "--format", "json"])
    assert show.exit_code == 0
    assert json.loads(show.stdout)["run_id"] == RUN_NEW


# ---------------------------------------------------------------------------
# Empty home — graceful "(no runs)" / null / empty list
# ---------------------------------------------------------------------------


def test_query_commands_on_empty_home(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the home dir is bare (no runs, no index), every query command
    must exit cleanly with an empty-friendly payload."""
    home = tmp_path / "empty_home"
    home.mkdir()
    monkeypatch.setenv("AGENTLENS_HOME", str(home))

    latest = runner.invoke(app, ["latest", "--format", "json"])
    assert latest.exit_code == 0
    assert json.loads(latest.stdout) is None

    status = runner.invoke(app, ["status", "--format", "json"])
    assert status.exit_code == 0
    assert json.loads(status.stdout) == []

    failures = runner.invoke(app, ["failures", "--format", "json"])
    assert failures.exit_code == 0
    assert json.loads(failures.stdout) == []

    risks = runner.invoke(app, ["risks", "--format", "json"])
    assert risks.exit_code == 0
    assert json.loads(risks.stdout) == []
