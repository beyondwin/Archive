from __future__ import annotations

from pathlib import Path

import pytest
import json
import subprocess

from agentrunway.apply import ApplyError, apply_commits_to_source
from agentrunway.db import AgentRunwayDb
from agentrunway.models import FileClaim, TaskSpec
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


def test_resume_executes_merge_boundary_from_verified_candidate(git_repo: Path, isolated_home: Path) -> None:
    subprocess.run(["git", "checkout", "-b", "worker"], cwd=git_repo, check=True, capture_output=True)
    target = git_repo / "src" / "resume_merge.py"
    target.parent.mkdir()
    target.write_text("VALUE = 'resume'\n", encoding="utf-8")
    subprocess.run(["git", "add", "src/resume_merge.py"], cwd=git_repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "worker change"], cwd=git_repo, check=True, capture_output=True)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=git_repo, text=True, capture_output=True, check=True).stdout.strip()
    subprocess.run(["git", "checkout", "main"], cwd=git_repo, check=True, capture_output=True)

    run_dir = isolated_home / "runs" / "workspace" / "run-merge"
    run_dir.mkdir(parents=True)
    state_db = run_dir / "state.sqlite"
    db = AgentRunwayDb.open(state_db)
    db.create_run(
        run_id="run-merge",
        workspace_id="workspace",
        repo_root=str(git_repo),
        plan_path=str(git_repo / "plan.md"),
        spec_path=None,
        plan_hash="plan-hash",
        spec_hash=None,
        base_commit_sha=subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=git_repo, text=True, capture_output=True, check=True
        ).stdout.strip(),
        model_profile="default",
    )
    db.upsert_task(
        TaskSpec(
            task_id="task_001",
            title="Task",
            risk="low",
            phase="implementation",
            dependencies=(),
            spec_refs=(),
            file_claims=(FileClaim("src/resume_merge.py", "owned"),),
            acceptance_commands=("pytest",),
        )
    )
    candidate_id = db.enqueue_merge_candidate(
        task_id="task_001",
        worker_id="task_001-implementer-001",
        commits=(commit,),
        changed_files=("src/resume_merge.py",),
        status="merge_ready",
    )
    store = WorkflowStore(db)
    store.create_checkpoint(
        run_id="run-merge",
        checkpoint_id="cp-000",
        commit_sha=subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=git_repo, text=True, capture_output=True, check=True
        ).stdout.strip(),
        parent_checkpoint_id=None,
        merged_candidate_id=None,
        reason="initial",
    )
    store.start_activity(
        run_id="run-merge",
        activity_id="task_001.verification.001",
        idempotency_key="run-merge:task_001:verification:001",
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
                "run_id": "run-merge",
                "status": "running",
                "run_dir": str(run_dir),
                "state_db": str(state_db),
                "repo_root": str(git_repo),
                "main_worktree": str(git_repo),
            }
        ),
        encoding="utf-8",
    )

    result = resume("run-merge")

    updated_run_json = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))

    assert result["status"] == "finished"
    assert result["execution"]["blocked"] is None
    assert result["execution"]["executed"][0]["action"] == "schedule_merge"
    assert result["execution"]["executed"][0]["result"]["checkpoint_id"] == "cp-001"
    assert db.get_task("task_001")["status"] == "merged"
    assert db.get_run("run-merge")["status"] == "finished"
    assert updated_run_json["status"] == "finished"
    assert (git_repo / "src" / "resume_merge.py").read_text(encoding="utf-8") == "VALUE = 'resume'\n"


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
