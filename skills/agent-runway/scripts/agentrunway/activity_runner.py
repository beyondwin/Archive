from __future__ import annotations

from typing import Any

from .workflow_store import ActivityStatus, WorkflowStore


class ActivityRunner:
    def __init__(self, *, store: WorkflowStore, run_id: str):
        self.store = store
        self.run_id = run_id

    def start(
        self,
        *,
        activity_id: str,
        idempotency_key: str,
        task_id: str | None,
        activity_type: str,
        input_refs: dict[str, Any],
    ) -> dict[str, Any]:
        return self.store.start_activity(
            run_id=self.run_id,
            activity_id=activity_id,
            idempotency_key=idempotency_key,
            task_id=task_id,
            activity_type=activity_type,
            input_refs=input_refs,
        )

    def complete(
        self,
        *,
        activity_id: str,
        status: ActivityStatus,
        output_refs: dict[str, Any],
        failure_class: str | None,
    ) -> dict[str, Any]:
        return self.store.complete_activity(
            activity_id=activity_id,
            status=status,
            output_refs=output_refs,
            failure_class=failure_class,
        )
