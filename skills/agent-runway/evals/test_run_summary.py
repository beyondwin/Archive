from __future__ import annotations

import json
from pathlib import Path

from agentrunway import runner
from agentrunway.db import AgentRunwayDb
from agentrunway.invocation import COMMANDS, parse_run_args
from agentrunway.run_summary import build_run_summary, reconstruct_run_json
from agentrunway.status import format_run_status


def _db(path: Path) -> AgentRunwayDb:
    db = AgentRunwayDb.open(path)
    db.create_run(
        run_id="run-1",
        workspace_id="ws",
        repo_root=str(path.parent),
        plan_path=str(path.parent / "plan.md"),
        spec_path=None,
        plan_hash="sha256:plan",
        spec_hash=None,
        base_commit_sha="abc123",
        model_profile="default",
        allowed_dirty=False,
        apply_to_source=False,
    )
    return db


def _sqlite_only_run(tmp_path: Path) -> Path:
    run_dir = tmp_path / "home" / "runs" / "ws" / "run-1"
    run_dir.mkdir(parents=True)
    _db(run_dir / "state.sqlite")
    (run_dir / "events.jsonl").write_text(
        json.dumps({"event_type": "agentrunway.run_started"}) + "\n",
        encoding="utf-8",
    )
    return run_dir


def test_summary_is_bounded_and_contains_next_action(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    db = _db(run_dir / "state.sqlite")
    run_json = {
        "run_id": "run-1",
        "status": "running",
        "run_dir": str(run_dir),
        "state_db": str(run_dir / "state.sqlite"),
        "tasks": [],
    }

    summary = build_run_summary(run_json=run_json, db=db, event_tail=3)

    assert summary["run_id"] == "run-1"
    assert summary["status"] == "running"
    assert summary["next_action"]
    assert "artifact_refs" in summary


def test_reconstruct_run_json_from_sqlite_when_run_json_missing(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _db(run_dir / "state.sqlite")
    (run_dir / "events.jsonl").write_text(
        json.dumps({"event_type": "agentrunway.run_started"}) + "\n",
        encoding="utf-8",
    )

    reconstructed = reconstruct_run_json(run_id="run-1", run_dir=run_dir)

    assert reconstructed["run_id"] == "run-1"
    assert reconstructed["status"] == "created"
    assert reconstructed["run_dir"] == str(run_dir)
    assert reconstructed["base_commit_sha"] == "abc123"
    assert "run.json" in reconstructed["reconstructed_from"]
    assert "state.sqlite" in reconstructed["reconstructed_from"]


def test_summary_marks_agentlens_disabled_notice(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    db = _db(run_dir / "state.sqlite")
    run_json = {
        "run_id": "run-1",
        "status": "finished",
        "run_dir": str(run_dir),
        "state_db": str(run_dir / "state.sqlite"),
        "tasks": [],
    }

    summary = build_run_summary(run_json=run_json, db=db)

    assert summary["agentlens_notice"] == "AgentLens disabled; local SQLite and artifacts are authoritative."


def test_status_formatter_renders_agentlens_disabled_notice() -> None:
    text = format_run_status(
        {
            "run_id": "run-1",
            "status": "running",
            "agentlens": {"last_status": "none", "run_status": "disabled"},
            "next_action": "continue monitoring",
        }
    )

    assert "AgentLens disabled; local SQLite and artifacts are authoritative." in text


def test_summarize_preserves_base_commit_from_sqlite_only_run(tmp_path: Path, monkeypatch) -> None:
    _sqlite_only_run(tmp_path)
    monkeypatch.setenv("AGENTRUNWAY_HOME", str(tmp_path / "home"))

    summary = runner.summarize("run-1")

    assert summary["base_commit"] == "abc123"
    assert "state.sqlite" in summary["reconstructed_from"]


def test_status_and_inspect_include_sqlite_reconstruction_provenance(tmp_path: Path, monkeypatch) -> None:
    _sqlite_only_run(tmp_path)
    monkeypatch.setenv("AGENTRUNWAY_HOME", str(tmp_path / "home"))

    status = runner.status("run-1")
    inspect = runner.inspect("run-1")

    assert status["reconstructed_from"] == ["run.json", "state.sqlite"]
    assert inspect["reconstructed_from"] == ["run.json", "state.sqlite"]


def test_invocation_keeps_lint_plan_and_summarize_commands() -> None:
    assert "lint-plan" in COMMANDS
    assert "summarize" in COMMANDS
    assert parse_run_args(["summarize", "--run", "run-1"]).run == "run-1"
    assert parse_run_args(["lint-plan", "--plan", "plan.md", "--spec", "spec.md"]).plan == Path("plan.md")
