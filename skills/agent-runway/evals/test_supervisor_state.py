from __future__ import annotations

from pathlib import Path

from agentrunway.db import AgentRunwayDb
from agentrunway.models import ProcessState, WorkerRole, WorkerState


def test_worker_lifecycle_enums_cover_production_states() -> None:
    assert WorkerRole.IMPLEMENTER.value == "implementer"
    assert WorkerRole.REVIEWER.value == "reviewer"
    assert WorkerRole.VERIFIER.value == "verifier"
    assert WorkerState.QUEUED.value == "queued"
    assert WorkerState.WORKTREE_CREATED.value == "worktree_created"
    assert WorkerState.DISPATCHED.value == "dispatched"
    assert WorkerState.RUNNING.value == "running"
    assert WorkerState.RESULT_COLLECTED.value == "result_collected"
    assert WorkerState.VALIDATED.value == "validated"
    assert WorkerState.MERGE_READY.value == "merge_ready"
    assert WorkerState.MERGED.value == "merged"
    assert WorkerState.ADAPTER_CRASHED.value == "adapter_crashed"
    assert WorkerState.TIMEOUT.value == "timeout"
    assert WorkerState.DIFF_SCOPE_FAILED.value == "diff_scope_failed"
    assert ProcessState.RUNNING.value == "running"
    assert ProcessState.EXITED.value == "exited"
    assert ProcessState.MISSING.value == "missing"


def test_db_records_worker_attempt_state_and_handle(tmp_path: Path) -> None:
    db = AgentRunwayDb.open(tmp_path / "state.sqlite")
    db.create_worker_attempt(
        worker_id="task_001-implementer-001",
        task_id="task_001",
        role="implementer",
        runtime="codex",
        model="gpt-5.5",
        reasoning_effort="xhigh",
        attempt=1,
        worktree_path="/tmp/worker",
        branch="agentrunway/run/task_001-implementer-001",
        state="queued",
        handle_json={"pid": None, "session_id": None},
    )
    db.set_worker_state("task_001-implementer-001", "running")
    db.update_worker_handle("task_001-implementer-001", {"pid": 123, "session_id": "abc"})

    row = db.get_worker("task_001-implementer-001")
    assert row["state"] == "running"
    assert row["attempt"] == 1
    assert row["handle_json"]["pid"] == 123
    assert row["worktree_path"] == "/tmp/worker"


def test_db_records_merge_candidate_and_applied_commits(tmp_path: Path) -> None:
    db = AgentRunwayDb.open(tmp_path / "state.sqlite")
    candidate_id = db.enqueue_merge_candidate(
        task_id="task_001",
        worker_id="task_001-implementer-001",
        commits=("abc123", "def456"),
        changed_files=("src/a.py",),
        status="pending_review",
    )
    db.set_merge_candidate_status(candidate_id, "merge_ready")
    db.record_applied_commit(run_id="run-1", commit_sha="abc123", strategy="cherry-pick")

    candidates = db.list_merge_candidates()
    applied = db.list_applied_commits("run-1")
    assert candidates[0]["commits"] == ["abc123", "def456"]
    assert candidates[0]["changed_files"] == ["src/a.py"]
    assert candidates[0]["status"] == "merge_ready"
    assert applied == [{"commit_sha": "abc123", "strategy": "cherry-pick"}]
