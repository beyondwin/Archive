from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from agentrunway.db import AgentRunwayDb
from agentrunway.models import FileClaim, TaskSpec
from agentrunway.runner import resume
from agentrunway.workflow_store import ActivityStatus, WorkflowStore
from agentrunway.worktrees import workspace_id


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "agentrunway.py"
FAKE_BIN = ROOT / "evals" / "fixtures" / "fake-bin"


def _write_plan(repo: Path, *, target: str = "src/trust_events.py") -> tuple[Path, Path]:
    spec = repo / "spec.md"
    plan = repo / "plan.md"
    spec.write_text("# Spec\n\n## A\n\nAdd trust event file.\n", encoding="utf-8")
    plan.write_text(
        "## Task 1: A\n\n"
        "```yaml agentrunway-task\n"
        "task_id: task_001\n"
        "title: A\n"
        "risk: low\n"
        "phase: implementation\n"
        "dependencies: []\n"
        "spec_refs: [S1.1]\n"
        "file_claims:\n"
        f"  - {{path: {target}, mode: owned}}\n"
        "acceptance_commands: [python -m pytest]\n"
        "required_skills: [test-driven-development]\n"
        "```\n"
        "Add trust event file.\n",
        encoding="utf-8",
    )
    return plan, spec


def _event_rows(state_db: str) -> list[dict[str, object]]:
    conn = sqlite3.connect(state_db)
    conn.row_factory = sqlite3.Row
    return [
        {"event_type": row["event_type"], "payload": json.loads(row["payload_json"]), "status": row["status"]}
        for row in conn.execute("SELECT event_type, payload_json, status FROM agentlens_events ORDER BY id")
    ]


def test_local_simulation_records_degraded_agentlens_and_simulation_completed(
    git_repo: Path,
    isolated_home: Path,
) -> None:
    plan, spec = _write_plan(git_repo)
    env = os.environ.copy()
    env["PATH"] = "/usr/bin:/bin"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "run",
            "--plan",
            str(plan),
            "--spec",
            str(spec),
            "--adapter",
            "local",
            "--fake-success",
        ],
        cwd=git_repo,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    events = _event_rows(payload["state_db"])
    by_type = {str(row["event_type"]): row["payload"] for row in events}

    assert payload["status"] == "simulated_finished"
    assert "agentrunway.agentlens_sink_unavailable" in by_type
    assert by_type["agentrunway.agentlens_sink_unavailable"]["event_name"] == "agentrunway.agentlens_sink_unavailable"
    assert by_type["agentrunway.agentlens_sink_unavailable"]["evidence"]["sink"] == "disabled"
    assert "events.jsonl" in by_type["agentrunway.agentlens_sink_unavailable"]["evidence"]["local_journal"]
    assert "agentrunway.simulation_completed" in by_type
    assert by_type["agentrunway.simulation_completed"]["spec_refs"] == ["S1.1"]
    assert "agentrunway.run_finished" in by_type


def test_production_run_records_trust_ready_events(git_repo: Path, isolated_home: Path) -> None:
    plan, spec = _write_plan(git_repo, target="src/production_events.py")
    env = os.environ.copy()
    env["PATH"] = f"{FAKE_BIN}{os.pathsep}{env['PATH']}"
    env["AGENTRUNWAY_FAKE_TARGET"] = "src/production_events.py"

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "run", "--plan", str(plan), "--spec", str(spec), "--adapter", "codex"],
        cwd=git_repo,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    events = _event_rows(payload["state_db"])
    by_type = {str(row["event_type"]): row["payload"] for row in events}

    assert payload["status"] == "finished"
    for event_type in (
        "agentrunway.worker_dispatched",
        "agentrunway.worker_result",
        "agentrunway.review_result",
        "agentrunway.verification_result",
        "agentrunway.merge_applied",
        "agentrunway.run_finished",
    ):
        assert event_type in by_type
        assert by_type[event_type]["event_name"] == event_type
    assert by_type["agentrunway.worker_result"]["spec_refs"] == ["S1.1"]
    assert by_type["agentrunway.merge_applied"]["evidence"]["status"] == "merged"
    assert by_type["agentrunway.merge_applied"]["evidence"]["commits"]


def test_resume_merge_evidence_block_records_merge_blocked_event(
    git_repo: Path,
    isolated_home: Path,
) -> None:
    run_id = "run-merge-blocked"
    wsid = workspace_id(git_repo)
    run_dir = isolated_home / "runs" / wsid / run_id
    run_dir.mkdir(parents=True)
    state_db = run_dir / "state.sqlite"
    db = AgentRunwayDb.open(state_db)
    base_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=git_repo, text=True, capture_output=True, check=True
    ).stdout.strip()
    db.create_run(
        run_id=run_id,
        workspace_id=wsid,
        repo_root=str(git_repo),
        plan_path=str(git_repo / "plan.md"),
        spec_path=None,
        plan_hash="plan-hash",
        spec_hash=None,
        base_commit_sha=base_commit,
        model_profile="default",
    )
    db.upsert_task(
        TaskSpec(
            task_id="task_001",
            title="Task",
            risk="low",
            phase="implementation",
            dependencies=(),
            spec_refs=("S1.1",),
            file_claims=(FileClaim("src/missing.py", "owned"),),
            acceptance_commands=("pytest",),
        )
    )
    candidate_id = db.enqueue_merge_candidate(
        task_id="task_001",
        worker_id="task_001-implementer-001",
        commits=(),
        changed_files=(),
        status="merge_ready",
    )
    store = WorkflowStore(db)
    store.create_checkpoint(
        run_id=run_id,
        checkpoint_id="cp-000",
        commit_sha=base_commit,
        parent_checkpoint_id=None,
        merged_candidate_id=None,
        reason="initial",
    )
    store.start_activity(
        run_id=run_id,
        activity_id="task_001.verification.001",
        idempotency_key=f"{run_id}:task_001:verification:001",
        task_id="task_001",
        activity_type="verification",
        input_refs={"candidate_id": candidate_id},
    )
    store.complete_activity(
        activity_id="task_001.verification.001",
        status=ActivityStatus.COMPLETED,
        output_refs={"candidate_id": candidate_id, "verification_status": "passed"},
        failure_class=None,
    )
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "status": "running",
                "run_dir": str(run_dir),
                "state_db": str(state_db),
                "repo_root": str(git_repo),
                "main_worktree": str(git_repo),
            }
        ),
        encoding="utf-8",
    )

    result = resume(run_id)
    events = _event_rows(str(state_db))
    blocked = [row["payload"] for row in events if row["event_type"] == "agentrunway.merge_blocked"]

    assert result["execution"]["blocked"]["reason"].startswith("merge_evidence_missing")
    assert blocked[-1]["event_name"] == "agentrunway.merge_blocked"
    assert blocked[-1]["evidence"]["reasons"] == ["missing_commit", "missing_changed_files"]
    assert blocked[-1]["spec_refs"] == ["S1.1"]
