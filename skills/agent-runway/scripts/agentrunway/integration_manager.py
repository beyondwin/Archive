from __future__ import annotations

from pathlib import Path

from .db import AgentRunwayDb
from .git_ops import Git
from .merge_queue import MergeCandidate, MergeConflictError, apply_candidate
from .workflow_store import ActivityStatus, WorkflowStore


class IntegrationManager:
    def __init__(self, *, db: AgentRunwayDb, store: WorkflowStore, run_id: str, main_worktree: Path):
        self.db = db
        self.store = store
        self.run_id = run_id
        self.main_worktree = main_worktree

    def _next_checkpoint_id(self) -> str:
        count = len(self.store.list_checkpoints(self.run_id))
        return f"cp-{count:03d}"

    def merge_selected_candidate(self, *, candidate_id: int, candidate: MergeCandidate) -> dict[str, object]:
        activity_id = f"{candidate.task_id}.merge.{candidate_id}"
        self.store.start_activity(
            run_id=self.run_id,
            activity_id=activity_id,
            idempotency_key=f"{self.run_id}:{candidate.task_id}:merge:{candidate_id}",
            task_id=candidate.task_id,
            activity_type="merge",
            input_refs={"candidate_id": candidate_id, "commits": list(candidate.commits)},
        )
        latest = self.store.latest_checkpoint(self.run_id)
        main_git = Git(self.main_worktree)
        try:
            apply_candidate(main_git, candidate)
        except MergeConflictError as exc:
            self.db.set_merge_candidate_status(candidate_id, "merge_conflict", str(exc))
            self.store.complete_activity(
                activity_id=activity_id,
                status=ActivityStatus.FAILED,
                output_refs={"error": str(exc)},
                failure_class="needs_rebase",
            )
            raise
        self.db.set_merge_candidate_status(candidate_id, "merged")
        self.db.set_worker_state(candidate.worker_id, "merged")
        checkpoint_id = self._next_checkpoint_id()
        checkpoint = self.store.create_checkpoint(
            run_id=self.run_id,
            checkpoint_id=checkpoint_id,
            commit_sha=main_git.rev_parse("HEAD"),
            parent_checkpoint_id=str(latest["checkpoint_id"]) if latest else None,
            merged_candidate_id=candidate_id,
            reason=f"merged:{candidate.task_id}",
        )
        self.store.complete_activity(
            activity_id=activity_id,
            status=ActivityStatus.COMPLETED,
            output_refs={"checkpoint_id": checkpoint_id, "commit_sha": checkpoint["commit_sha"]},
            failure_class=None,
        )
        return checkpoint
