from __future__ import annotations

from enum import Enum
from typing import Any

from .db import AgentRunwayDb


class ActivityStatus(str, Enum):
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


class WorkflowStore:
    def __init__(self, db: AgentRunwayDb):
        self.db = db

    def record_event(self, *, run_id: str, event_type: str, node_id: str | None, payload: dict[str, Any]) -> int:
        return self.db.insert_workflow_event(
            run_id=run_id,
            event_type=event_type,
            node_id=node_id,
            payload=payload,
        )

    def list_workflow_events(self, run_id: str) -> list[dict[str, Any]]:
        return self.db.list_workflow_events(run_id)

    def start_activity(
        self,
        *,
        run_id: str,
        activity_id: str,
        idempotency_key: str,
        task_id: str | None,
        activity_type: str,
        input_refs: dict[str, Any],
    ) -> dict[str, Any]:
        existing = self.db.get_activity_by_idempotency_key(idempotency_key)
        if existing is not None:
            return existing
        activity = self.db.insert_activity(
            activity_id=activity_id,
            run_id=run_id,
            idempotency_key=idempotency_key,
            task_id=task_id,
            activity_type=activity_type,
            status=ActivityStatus.STARTED.value,
            input_refs=input_refs,
        )
        self.record_event(
            run_id=run_id,
            event_type="ActivityStarted",
            node_id=activity_id,
            payload={"activity_id": activity_id, "activity_type": activity_type, "task_id": task_id},
        )
        return activity

    def complete_activity(
        self,
        *,
        activity_id: str,
        status: ActivityStatus,
        output_refs: dict[str, Any],
        failure_class: str | None,
    ) -> dict[str, Any]:
        activity = self.db.update_activity(
            activity_id=activity_id,
            status=status.value,
            output_refs=output_refs,
            failure_class=failure_class,
        )
        self.record_event(
            run_id=str(activity["run_id"]),
            event_type="ActivityCompleted" if status == ActivityStatus.COMPLETED else "ActivityFailed",
            node_id=activity_id,
            payload={
                "activity_id": activity_id,
                "activity_type": activity["activity_type"],
                "task_id": activity.get("task_id"),
                "status": status.value,
                "failure_class": failure_class,
            },
        )
        return activity

    def get_activity(self, activity_id: str) -> dict[str, Any]:
        return self.db.get_activity(activity_id)

    def create_checkpoint(
        self,
        *,
        run_id: str,
        checkpoint_id: str,
        commit_sha: str,
        parent_checkpoint_id: str | None,
        merged_candidate_id: int | None,
        reason: str,
    ) -> dict[str, Any]:
        checkpoint = self.db.insert_checkpoint(
            run_id=run_id,
            checkpoint_id=checkpoint_id,
            commit_sha=commit_sha,
            parent_checkpoint_id=parent_checkpoint_id,
            merged_candidate_id=merged_candidate_id,
            reason=reason,
        )
        self.record_event(
            run_id=run_id,
            event_type="CheckpointCreated",
            node_id=checkpoint_id,
            payload={
                "checkpoint_id": checkpoint_id,
                "commit_sha": commit_sha,
                "parent_checkpoint_id": parent_checkpoint_id,
                "merged_candidate_id": merged_candidate_id,
                "reason": reason,
            },
        )
        return checkpoint

    def latest_checkpoint(self, run_id: str) -> dict[str, Any] | None:
        return self.db.latest_checkpoint(run_id)

    def list_checkpoints(self, run_id: str) -> list[dict[str, Any]]:
        return self.db.list_checkpoints(run_id)

    def create_decision_packet(
        self,
        *,
        run_id: str,
        decision_id: str,
        task_id: str | None,
        failure_class: str,
        summary: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        packet = self.db.insert_decision_packet(
            run_id=run_id,
            decision_id=decision_id,
            task_id=task_id,
            failure_class=failure_class,
            summary=summary,
            payload=payload,
        )
        self.record_event(
            run_id=run_id,
            event_type="HumanDecisionRequired",
            node_id=decision_id,
            payload={
                "decision_id": decision_id,
                "task_id": task_id,
                "failure_class": failure_class,
                "summary": summary,
            },
        )
        return packet

    def list_decision_packets(self, run_id: str) -> list[dict[str, Any]]:
        return self.db.list_decision_packets(run_id)
