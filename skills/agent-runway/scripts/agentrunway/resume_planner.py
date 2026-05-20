from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .db import AgentRunwayDb
from .durable_resume import plan_activity_resume


ResumeActionName = Literal[
    "schedule_review",
    "schedule_verification",
    "schedule_merge",
    "verify_checkpoint",
    "schedule_implementer_retry",
    "await_human_decision",
    "classify_stale_activity",
]


@dataclass(frozen=True)
class ResumeAction:
    action: ResumeActionName
    task_id: str | None
    candidate_id: int | None
    writes: bool
    reason: str


def _task_id_from_node(node: object) -> str | None:
    if not isinstance(node, str) or "." not in node:
        return None
    return node.split(".", 1)[0]


def plan_resume_actions(*, run_id: str, db: AgentRunwayDb) -> list[ResumeAction]:
    plan = plan_activity_resume(run_id=run_id, db=db)
    action = plan.get("next_action")
    node = plan.get("next_node")
    task_id = _task_id_from_node(node)
    candidate_id = plan.get("candidate_id")
    candidate_int = int(candidate_id) if candidate_id is not None else None
    if action == "await_human_decision":
        return [
            ResumeAction(
                action="await_human_decision",
                task_id=task_id,
                candidate_id=candidate_int,
                writes=False,
                reason=str(plan.get("reason") or "blocked_activity_requires_human_decision"),
            )
        ]
    if action in {
        "schedule_review",
        "schedule_verification",
        "schedule_merge",
        "verify_checkpoint",
        "schedule_implementer_retry",
    }:
        return [
            ResumeAction(
                action=action,
                task_id=task_id,
                candidate_id=candidate_int,
                writes=True,
                reason=str(plan.get("reason") or action),
            )
        ]
    return []
