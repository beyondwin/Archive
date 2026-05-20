from __future__ import annotations

import json
import os
from datetime import timedelta
from pathlib import Path

from agentrunway.db import AgentRunwayDb
from agentrunway.models import FileClaim, TaskSpec
from agentrunway.retention import plan_retention_clean
from agentrunway.worktree_lifecycle import (
    archive_candidate_evidence,
    lifecycle_for_worker,
    reviewer_mode_for_task,
)


def _task(*, risk: str = "low", path: str = "src/app.py") -> TaskSpec:
    return TaskSpec(
        task_id="task_001",
        title="Task",
        risk=risk,  # type: ignore[arg-type]
        phase="implementation",
        dependencies=(),
        spec_refs=(),
        file_claims=(FileClaim(path=path, mode="owned"),),
        acceptance_commands=("python -m pytest",),
    )


def test_lifecycle_keeps_quality_evidence_before_cleanup() -> None:
    assert lifecycle_for_worker(role="implementer", state="merge_ready") == "retained_for_apply"
    assert lifecycle_for_worker(role="implementer", state="not_selected") == "evidence_archived"
    assert lifecycle_for_worker(role="reviewer", state="validated") == "cleanup_eligible"
    assert lifecycle_for_worker(role="verifier", state="validated") == "cleanup_eligible"
    assert lifecycle_for_worker(role="verifier", state="malformed_result") == "retained_for_diagnosis"
    assert lifecycle_for_worker(role="implementer", state="cancelled") == "retained_for_diagnosis"


def test_reviewer_mode_escalates_for_high_risk_schema_and_generated_surface() -> None:
    assert reviewer_mode_for_task(_task()) == "diff"
    assert reviewer_mode_for_task(_task(risk="high")) == "full_tree"
    assert reviewer_mode_for_task(_task(path="migrations/001_add_table.sql")) == "full_tree"
    assert reviewer_mode_for_task(_task(path="src/generated/client.py")) == "full_tree"


def test_reviewer_mode_uses_diff_for_independent_task() -> None:
    assert reviewer_mode_for_task(_task(path="src/a.py")) == "diff"


def test_reviewer_mode_uses_full_tree_for_shared_core_task() -> None:
    assert reviewer_mode_for_task(_task(path="skills/agent-runway/scripts/agentrunway/runner.py")) == "full_tree"


def test_archive_candidate_evidence_persists_non_selected_metadata(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    db = AgentRunwayDb.open(run_dir / "state.sqlite")
    db.create_worker_attempt(
        worker_id="task_001-implementer-002",
        task_id="task_001",
        role="implementer",
        runtime="codex",
        model="gpt-5.5",
        reasoning_effort="xhigh",
        attempt=2,
        worktree_path=str(tmp_path / "worker"),
        branch="agentrunway/run/task_001-implementer-002",
        state="not_selected",
        handle_json={"pid": 123},
    )

    evidence_dir = archive_candidate_evidence(
        run_dir=run_dir,
        db=db,
        candidate={
            "task_id": "task_001",
            "worker_id": "task_001-implementer-002",
            "commits": ["abc", "def"],
            "changed_files": ["src/app.py"],
        },
    )

    assert json.loads((evidence_dir / "commits.json").read_text(encoding="utf-8")) == ["abc", "def"]
    assert json.loads((evidence_dir / "changed_files.json").read_text(encoding="utf-8")) == ["src/app.py"]
    worker = json.loads((evidence_dir / "worker.json").read_text(encoding="utf-8"))
    assert worker["worker_id"] == "task_001-implementer-002"


def test_retention_uses_lifecycle_registry_for_worker_worktrees(tmp_path: Path) -> None:
    home = tmp_path / "home"
    run_dir = home / "runs" / "ws" / "run-1"
    run_dir.mkdir(parents=True)
    db = AgentRunwayDb.open(run_dir / "state.sqlite")
    db.create_run(
        run_id="run-1",
        workspace_id="ws",
        repo_root=str(tmp_path / "repo"),
        plan_path=str(tmp_path / "plan.md"),
        spec_path=None,
        plan_hash="sha256:plan",
        spec_hash=None,
        base_commit_sha="abc123",
        model_profile="default",
        allowed_dirty=False,
        apply_to_source=False,
    )
    db.set_run_status("run-1", "finished")
    cleanup = home / "worktrees" / "ws" / "run-1" / "workers" / "reviewer"
    diagnosis = home / "worktrees" / "ws" / "run-1" / "workers" / "failed"
    cleanup.mkdir(parents=True)
    diagnosis.mkdir(parents=True)
    db.register_worktree(path=str(cleanup), run_id="run-1", branch="reviewer", lifecycle="cleanup_eligible")
    db.register_worktree(path=str(diagnosis), run_id="run-1", branch="failed", lifecycle="retained_for_diagnosis")
    (run_dir / "run.json").write_text(json.dumps({"run_id": "run-1", "status": "finished"}), encoding="utf-8")
    old = cleanup.stat().st_mtime - timedelta(days=30).total_seconds()
    for path in (run_dir, cleanup, diagnosis):
        os.utime(path, (old, old))

    plan = plan_retention_clean(home, older_than="14d", successful=True)

    candidates = {(item["kind"], item["path"], item["reason"]) for item in plan["candidates"]}
    retained = {(item["kind"], item["path"], item["reason"]) for item in plan["retained"]}
    assert ("worktree", str(cleanup), "lifecycle_cleanup_eligible") in candidates
    assert ("worktree", str(diagnosis), "lifecycle_retained_for_diagnosis") in retained
