from __future__ import annotations

import subprocess
from pathlib import Path

from agentrunway.db import AgentRunwayDb
from agentrunway.git_ops import Git
from agentrunway.integration_manager import IntegrationManager
from agentrunway.merge_queue import MergeCandidate
from agentrunway.workflow_store import WorkflowStore


def _commit(path: Path, rel: str, text: str, message: str) -> str:
    target = path / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    subprocess.run(["git", "add", rel], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", message], cwd=path, check=True, capture_output=True, text=True)
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=path, check=True, capture_output=True, text=True).stdout.strip()


def test_merge_selected_candidate_records_checkpoint(git_repo: Path, tmp_path: Path) -> None:
    db = AgentRunwayDb.open(tmp_path / "state.sqlite")
    store = WorkflowStore(db)
    main = tmp_path / "main"
    subprocess.run(["git", "worktree", "add", "-b", "agentrunway/test/main", str(main), "HEAD"], cwd=git_repo, check=True, capture_output=True, text=True)
    initial = Git(main).rev_parse("HEAD")
    store.create_checkpoint(
        run_id="run-1",
        checkpoint_id="cp-000",
        commit_sha=initial,
        parent_checkpoint_id=None,
        merged_candidate_id=None,
        reason="initial",
    )

    worker = tmp_path / "worker"
    subprocess.run(["git", "worktree", "add", "-b", "agentrunway/test/worker", str(worker), "HEAD"], cwd=git_repo, check=True, capture_output=True, text=True)
    commit = _commit(worker, "src/merged.py", "VALUE = 'merged'\n", "candidate")
    candidate_id = db.enqueue_merge_candidate(
        task_id="task_001",
        worker_id="task_001-implementer-001",
        commits=(commit,),
        changed_files=("src/merged.py",),
        status="merge_ready",
    )

    manager = IntegrationManager(db=db, store=store, run_id="run-1", main_worktree=main)
    checkpoint = manager.merge_selected_candidate(
        candidate_id=candidate_id,
        candidate=MergeCandidate(
            task_id="task_001",
            worker_id="task_001-implementer-001",
            commits=(commit,),
            changed_files=("src/merged.py",),
        ),
    )

    assert (main / "src" / "merged.py").read_text(encoding="utf-8") == "VALUE = 'merged'\n"
    assert checkpoint["parent_checkpoint_id"] == "cp-000"
    assert checkpoint["merged_candidate_id"] == candidate_id
    assert db.list_merge_candidates()[0]["status"] == "merged"
    assert store.latest_checkpoint("run-1")["checkpoint_id"] == checkpoint["checkpoint_id"]


def test_merge_conflict_records_failed_activity(git_repo: Path, tmp_path: Path) -> None:
    db = AgentRunwayDb.open(tmp_path / "state.sqlite")
    store = WorkflowStore(db)
    main = tmp_path / "main"
    subprocess.run(["git", "worktree", "add", "-b", "agentrunway/test-conflict/main", str(main), "HEAD"], cwd=git_repo, check=True, capture_output=True, text=True)
    initial = Git(main).rev_parse("HEAD")
    store.create_checkpoint(
        run_id="run-1",
        checkpoint_id="cp-000",
        commit_sha=initial,
        parent_checkpoint_id=None,
        merged_candidate_id=None,
        reason="initial",
    )
    _commit(main, "src/conflict.py", "VALUE = 'main'\n", "main change")

    worker = tmp_path / "worker"
    subprocess.run(["git", "worktree", "add", "-b", "agentrunway/test-conflict/worker", str(worker), initial], cwd=git_repo, check=True, capture_output=True, text=True)
    commit = _commit(worker, "src/conflict.py", "VALUE = 'worker'\n", "worker change")
    candidate_id = db.enqueue_merge_candidate(
        task_id="task_001",
        worker_id="task_001-implementer-001",
        commits=(commit,),
        changed_files=("src/conflict.py",),
        status="merge_ready",
    )

    manager = IntegrationManager(db=db, store=store, run_id="run-1", main_worktree=main)

    try:
        manager.merge_selected_candidate(
            candidate_id=candidate_id,
            candidate=MergeCandidate(
                task_id="task_001",
                worker_id="task_001-implementer-001",
                commits=(commit,),
                changed_files=("src/conflict.py",),
            ),
        )
    except Exception as exc:
        assert "conflict" in str(exc).lower()
    else:
        raise AssertionError("expected merge conflict")

    candidate = db.list_merge_candidates()[0]
    assert candidate["status"] == "merge_conflict"
    events = store.list_workflow_events("run-1")
    assert "ActivityFailed" in [event["event_type"] for event in events]
