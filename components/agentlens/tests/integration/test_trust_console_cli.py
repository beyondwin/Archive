from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agentlens.cli import app


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    al_home = tmp_path / "agentlens_home"
    ws = tmp_path / "workspace"
    ws.mkdir()
    monkeypatch.setenv("AGENTLENS_HOME", str(al_home))
    monkeypatch.chdir(ws)
    return ws


def _run_dir(workspace: Path, run_id: str) -> Path:
    return Path(
        (workspace / ".agentlens" / "current-runs" / run_id / "run_dir").read_text(
            encoding="utf-8"
        )
    )


def test_event_append_accepts_raw_agentlens_v2_envelope(
    runner: CliRunner, workspace: Path
) -> None:
    opened = runner.invoke(app, ["run-open", "--agent", "waygent"])
    assert opened.exit_code == 0, opened.output
    run_id = opened.stdout.strip()
    event = {
        "schema": "agentlens.event.v2",
        "event_id": "evt_000001",
        "run_id": run_id,
        "event_type": "runway.run_finished",
        "producer": {"name": "waygent", "version": "0.1.0"},
        "occurred_at": "2026-05-21T00:00:00Z",
        "sequence": 1,
        "phase": "finish",
        "outcome": "success",
        "severity": "info",
        "trust_impact": "supports_success",
        "summary": "finished",
        "payload": {"run_id": "run_waygent", "status": "finished"},
    }

    result = runner.invoke(
        app,
        ["event", "append", "--run", run_id, "--type", "runway.run_finished", "--payload-stdin"],
        input=json.dumps(event),
    )

    assert result.exit_code == 0, result.output
    lines = (_run_dir(workspace, run_id) / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[-1])["schema"] == "agentlens.event.v2"


def test_waygent_cli_reports_trust_report_json(
    runner: CliRunner, workspace: Path
) -> None:
    opened = runner.invoke(app, ["run-open", "--agent", "waygent"])
    assert opened.exit_code == 0, opened.output
    run_id = opened.stdout.strip()
    run_dir = _run_dir(workspace, run_id)
    artifacts = run_dir / "artifacts"
    artifacts.mkdir()
    (artifacts / "trust_report.json").write_text(
        json.dumps(
            {
                "schema": "agentlens.trust_report.v1",
                "run_id": run_id,
                "waygent_run_id": "run_waygent",
                "claimed_outcome": "success",
                "trust_verdict": "trusted",
                "evidence_strength": "strong",
                "blocking_evidence": [],
                "missing_evidence": [],
                "residual_risks": [],
                "operator_actions": [],
                "projection_issues": [],
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["waygent", run_id, "--format", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["trust_verdict"] == "trusted"
