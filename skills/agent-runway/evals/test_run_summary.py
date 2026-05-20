from __future__ import annotations

import json
from pathlib import Path

from agentrunway import runner
from agentrunway.db import AgentRunwayDb
from agentrunway.invocation import COMMANDS, parse_run_args
from agentrunway.models import FileClaim, TaskSpec
from agentrunway.run_summary import build_run_summary, reconstruct_run_json
from agentrunway.status import build_inspect_payload, format_run_status
from agentrunway.workflow_store import ActivityStatus, WorkflowStore


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


def _task(task_id: str) -> TaskSpec:
    return TaskSpec(
        task_id=task_id,
        title=task_id,
        risk="low",
        phase="implementation",
        dependencies=(),
        spec_refs=("S1.1",),
        file_claims=(FileClaim(f"src/{task_id}.py", "owned"),),
        acceptance_commands=("python -m pytest",),
    )


def _blocked_human_decision_run(tmp_path: Path) -> tuple[AgentRunwayDb, dict[str, object]]:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    db = _db(run_dir / "state.sqlite")
    store = WorkflowStore(db)
    db.upsert_task(_task("task_001"))
    store.start_activity(
        run_id="run-1",
        activity_id="task_001.review.001",
        idempotency_key="run-1:task_001:review:001",
        task_id="task_001",
        activity_type="review",
        input_refs={"candidate_id": 7},
    )
    store.complete_activity(
        activity_id="task_001.review.001",
        status=ActivityStatus.BLOCKED,
        output_refs={"candidate_id": 7, "review_status": "changes_requested"},
        failure_class="needs_plan_fix",
    )
    store.create_decision_packet(
        run_id="run-1",
        decision_id="task_001.review.001.decision",
        task_id="task_001",
        failure_class="needs_plan_fix",
        summary="review requires plan correction",
        payload={"candidate_id": 7},
    )
    run_json = {
        "run_id": "run-1",
        "status": "blocked",
        "run_dir": str(run_dir),
        "state_db": str(run_dir / "state.sqlite"),
        "base_commit_sha": "base",
    }
    return db, run_json


def _repeated_rebase_decision_run(tmp_path: Path) -> tuple[AgentRunwayDb, dict[str, object]]:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    db = _db(run_dir / "state.sqlite")
    store = WorkflowStore(db)
    db.upsert_task(_task("task_001"))
    store.start_activity(
        run_id="run-1",
        activity_id="task_001.review.002",
        idempotency_key="run-1:task_001:review:002",
        task_id="task_001",
        activity_type="review",
        input_refs={"candidate_id": 8},
    )
    store.complete_activity(
        activity_id="task_001.review.002",
        status=ActivityStatus.BLOCKED,
        output_refs={"candidate_id": 8, "review_status": "needs_rebase"},
        failure_class="needs_rebase",
    )
    store.create_decision_packet(
        run_id="run-1",
        decision_id="task_001.review.002.decision",
        task_id="task_001",
        failure_class="needs_rebase",
        summary="review requires repeated rebase decision",
        payload={"candidate_id": 8},
    )
    run_json = {
        "run_id": "run-1",
        "status": "blocked",
        "run_dir": str(run_dir),
        "state_db": str(run_dir / "state.sqlite"),
        "base_commit_sha": "base",
    }
    return db, run_json


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


def test_run_summary_includes_checkpoint_graph_and_failure_class(tmp_path: Path) -> None:
    db = AgentRunwayDb.open(tmp_path / "state.sqlite")
    db.create_run(
        run_id="run-1",
        workspace_id="ws",
        repo_root=str(tmp_path),
        plan_path=str(tmp_path / "plan.md"),
        spec_path=None,
        plan_hash="plan",
        spec_hash=None,
        base_commit_sha="base",
        model_profile="default",
        allowed_dirty=False,
        apply_to_source=False,
    )
    db.insert_checkpoint(
        run_id="run-1",
        checkpoint_id="cp-000",
        commit_sha="base",
        parent_checkpoint_id=None,
        merged_candidate_id=None,
        reason="initial",
    )
    db.insert_activity(
        activity_id="task_001.review.001",
        run_id="run-1",
        idempotency_key="run-1:task_001:review:001",
        task_id="task_001",
        activity_type="review",
        status="failed",
        input_refs={},
    )
    db.update_activity(
        activity_id="task_001.review.001",
        status="failed",
        output_refs={"review_result": "artifacts/task_001/review_result.json"},
        failure_class="needs_plan_fix",
    )
    run_json = {
        "run_id": "run-1",
        "status": "blocked",
        "run_dir": str(tmp_path),
        "state_db": str(tmp_path / "state.sqlite"),
        "base_commit_sha": "base",
    }

    summary = build_run_summary(run_json=run_json, db=db)

    assert summary["latest_checkpoint"] == {"id": "cp-000", "commit": "base", "reason": "initial"}
    assert summary["graph"]["blocked"] == 1
    assert summary["blocked_node"] == "task_001.review.001"
    assert summary["failure_class"] == "needs_plan_fix"
    assert summary["required_human_decision"] == "fix plan"


def test_summarize_and_inspect_use_durable_human_decision_next_action(tmp_path: Path) -> None:
    db, run_json = _blocked_human_decision_run(tmp_path)

    summary = build_run_summary(run_json=run_json, db=db)
    inspect = build_inspect_payload(run_json=run_json, db=db)

    assert summary["durable"]["required_human_decision"] == "fix plan"
    assert inspect["durable"]["required_human_decision"] == "fix plan"
    assert summary["next_action"] == "await_human_decision"
    assert inspect["next_action"] == "await_human_decision"


def test_summarize_and_inspect_surface_repeated_rebase_decision_packet(tmp_path: Path) -> None:
    db, run_json = _repeated_rebase_decision_run(tmp_path)

    summary = build_run_summary(run_json=run_json, db=db)
    inspect = build_inspect_payload(run_json=run_json, db=db)

    assert summary["durable"]["required_human_decision"] == "inspect decision packet"
    assert inspect["durable"]["required_human_decision"] == "inspect decision packet"
    assert summary["next_action"] == "await_human_decision"
    assert inspect["next_action"] == "await_human_decision"


def test_run_summary_includes_hybrid_scheduler_diagnostics(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    db = AgentRunwayDb.open(run_dir / "state.sqlite")
    db.upsert_task(
        TaskSpec(
            task_id="task_001",
            title="Task 1",
            risk="low",
            phase="implementation",
            dependencies=(),
            spec_refs=("S1",),
            file_claims=(FileClaim("skills/agent-runway/scripts/agentrunway/runner.py", "owned"),),
            acceptance_commands=("python -m pytest",),
        )
    )
    run_json = {
        "run_id": "run-1",
        "status": "running",
        "run_dir": str(run_dir),
        "state_db": str(run_dir / "state.sqlite"),
        "events": str(run_dir / "events.jsonl"),
    }
    (run_dir / "run.json").write_text(json.dumps(run_json), encoding="utf-8")
    (run_dir / "events.jsonl").write_text("", encoding="utf-8")

    summary = build_run_summary(run_json=run_json, db=db)

    assert summary["scheduler"]["projection_status"] == "running"
    assert summary["scheduler"]["safe_wave"] == ["task_001"]
    assert summary["scheduler"]["task_classes"][0]["execution_class"] == "shared_core"
