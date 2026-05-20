from __future__ import annotations

from pathlib import Path

import pytest
import subprocess

from agentrunway.apply import ApplyError, apply_commits_to_source
from agentrunway.db import AgentRunwayDb
from agentrunway.runner import resume
from agentrunway.workflow_store import ActivityStatus, WorkflowStore


def test_resume_missing_run_is_idempotent(isolated_home: Path) -> None:
    assert resume("missing-run") == {"run_id": "missing-run", "status": "missing"}
    assert resume("missing-run") == {"run_id": "missing-run", "status": "missing"}


def test_resume_dry_run_includes_activity_boundary(isolated_home: Path) -> None:
    run_dir = isolated_home / "runs" / "workspace" / "run-1"
    run_dir.mkdir(parents=True)
    state_db = run_dir / "state.sqlite"
    db = AgentRunwayDb.open(state_db)
    store = WorkflowStore(db)
    store.start_activity(
        run_id="run-1",
        activity_id="task_001.implement.001",
        idempotency_key="run-1:task_001:implement:001",
        task_id="task_001",
        activity_type="implement",
        input_refs={"checkpoint_id": "cp-000"},
    )
    store.complete_activity(
        activity_id="task_001.implement.001",
        status=ActivityStatus.COMPLETED,
        output_refs={"candidate_id": 9},
        failure_class=None,
    )
    (run_dir / "run.json").write_text(
        '{"run_id": "run-1", "status": "running", "run_dir": "%s", "state_db": "%s"}'
        % (run_dir, state_db),
        encoding="utf-8",
    )

    plan = resume("run-1", dry_run=True)

    assert plan["activity_resume"]["next_action"] == "schedule_review"
    assert plan["activity_resume"]["candidate_id"] == 9


def test_apply_refuses_dirty_source(git_repo: Path) -> None:
    (git_repo / "dirty.txt").write_text("dirty\n", encoding="utf-8")
    with pytest.raises(ApplyError, match="dirty source checkout"):
        apply_commits_to_source(git_repo, ("abc123",), strategy="cherry-pick")


def test_apply_conflict_error_names_failing_commit(git_repo: Path) -> None:
    readme = git_repo / "README.md"
    subprocess.run(["git", "checkout", "-b", "worker"], cwd=git_repo, check=True, capture_output=True)
    readme.write_text("# Worker\n", encoding="utf-8")
    subprocess.run(["git", "commit", "-am", "worker change"], cwd=git_repo, check=True, capture_output=True)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=git_repo, text=True, capture_output=True, check=True).stdout.strip()
    subprocess.run(["git", "checkout", "main"], cwd=git_repo, check=True, capture_output=True)
    readme.write_text("# Main\n", encoding="utf-8")
    subprocess.run(["git", "commit", "-am", "main change"], cwd=git_repo, check=True, capture_output=True)

    with pytest.raises(ApplyError) as exc_info:
        apply_commits_to_source(git_repo, (commit,), strategy="cherry-pick")

    message = str(exc_info.value)
    assert commit in message
    assert "cherry-pick conflict" in message
