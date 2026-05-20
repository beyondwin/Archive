from __future__ import annotations

from dataclasses import asdict
from typing import Any, Callable

from .db import AgentRunwayDb
from .resume_planner import ResumeAction
from .workflow_store import WorkflowStore


class ResumeExecutor:
    def __init__(
        self,
        *,
        db: AgentRunwayDb,
        run_id: str,
        handlers: dict[str, Callable[[ResumeAction], dict[str, Any]]] | None = None,
    ):
        self.db = db
        self.run_id = run_id
        self.handlers = dict(handlers or {})

    def _latest_decision_packet(self) -> dict[str, Any] | None:
        packets = self.db.list_decision_packets(self.run_id)
        return packets[-1] if packets else None

    def _block(self, *, executed: list[dict[str, Any]], action: ResumeAction, reason: str) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "executed": executed,
            "blocked": {
                "action": action.action,
                "task_id": action.task_id,
                "candidate_id": action.candidate_id,
                "reason": reason,
            },
        }

    def _latest_completed_merge_activity(self, task_id: str | None) -> dict[str, Any] | None:
        if task_id is None:
            return None
        for activity in reversed(self.db.list_activities(self.run_id)):
            if (
                activity.get("task_id") == task_id
                and activity.get("activity_type") == "merge"
                and activity.get("status") == "completed"
            ):
                return activity
        return None

    def _checkpoint_exists(self, checkpoint_id: str) -> bool:
        try:
            self.db.get_checkpoint(checkpoint_id)
        except KeyError:
            return False
        return True

    def _verify_checkpoint(self, action: ResumeAction) -> dict[str, Any]:
        merge_activity = self._latest_completed_merge_activity(action.task_id)
        if merge_activity is None:
            raise RuntimeError("missing_completed_merge_activity")
        output_refs = merge_activity.get("output_refs") or {}
        checkpoint_id = output_refs.get("checkpoint_id")
        commit_sha = output_refs.get("commit_sha")
        if not checkpoint_id or not commit_sha:
            raise RuntimeError("missing_checkpoint_output_refs")
        checkpoint_id = str(checkpoint_id)
        commit_sha = str(commit_sha)
        if self._checkpoint_exists(checkpoint_id):
            return {"checkpoint_id": checkpoint_id, "commit_sha": commit_sha, "reconstructed": False}
        latest = self.db.latest_checkpoint(self.run_id)
        input_refs = merge_activity.get("input_refs") or {}
        candidate_id = action.candidate_id if action.candidate_id is not None else input_refs.get("candidate_id")
        WorkflowStore(self.db).create_checkpoint(
            run_id=self.run_id,
            checkpoint_id=checkpoint_id,
            commit_sha=commit_sha,
            parent_checkpoint_id=str(latest["checkpoint_id"]) if latest else None,
            merged_candidate_id=int(candidate_id) if candidate_id is not None else None,
            reason=f"merged:{action.task_id}",
        )
        return {"checkpoint_id": checkpoint_id, "commit_sha": commit_sha, "reconstructed": True}

    def _run_action(self, action: ResumeAction) -> dict[str, Any]:
        if action.action == "verify_checkpoint":
            return self._verify_checkpoint(action)
        handler = self.handlers.get(action.action)
        if handler is None:
            raise RuntimeError("missing_resume_handler")
        return handler(action)

    def execute(self, *, actions: list[ResumeAction]) -> dict[str, Any]:
        executed: list[dict[str, Any]] = []
        for action in actions:
            if action.action == "await_human_decision":
                return {"run_id": self.run_id, "executed": executed, "blocked": self._latest_decision_packet()}
            try:
                result = self._run_action(action)
            except RuntimeError as exc:
                return self._block(executed=executed, action=action, reason=str(exc))
            payload = asdict(action)
            payload["result"] = result
            self.db.insert_workflow_event(
                run_id=self.run_id,
                event_type="ResumeActionExecuted",
                node_id=f"{action.task_id}.{action.action}" if action.task_id else action.action,
                payload=payload,
            )
            executed.append(payload)
        return {"run_id": self.run_id, "executed": executed, "blocked": None}
