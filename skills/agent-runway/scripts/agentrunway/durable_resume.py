from __future__ import annotations

from typing import Any

from .db import AgentRunwayDb


_HUMAN_DECISION_FAILURE_CLASSES = {
    "needs_plan_fix",
    "needs_split",
    "needs_human_decision",
    "needs_infra_fix",
    "terminal_rejected",
}


def _compact_activity(activity: dict[str, Any] | None) -> dict[str, Any] | None:
    if activity is None:
        return None
    return {
        "activity_id": activity.get("activity_id"),
        "activity_type": activity.get("activity_type"),
        "task_id": activity.get("task_id"),
        "status": activity.get("status"),
        "failure_class": activity.get("failure_class"),
        "output_refs": activity.get("output_refs") or {},
    }


def _latest_by_type(activities: list[dict[str, Any]], task_id: str, activity_type: str) -> dict[str, Any] | None:
    matches = [
        activity
        for activity in activities
        if activity.get("task_id") == task_id and activity.get("activity_type") == activity_type
    ]
    return matches[-1] if matches else None


def _has_activity_after(
    activities: list[dict[str, Any]],
    *,
    task_id: str,
    activity_type: str,
    after_activity_id: str,
) -> bool:
    seen = False
    for activity in activities:
        if activity.get("activity_id") == after_activity_id:
            seen = True
            continue
        if seen and activity.get("task_id") == task_id and activity.get("activity_type") == activity_type:
            return True
    return False


def _decision_for_activity(db: AgentRunwayDb, run_id: str, activity: dict[str, Any]) -> dict[str, Any] | None:
    activity_id = str(activity.get("activity_id"))
    for packet in db.list_decision_packets(run_id):
        if str(packet.get("decision_id")).startswith(activity_id):
            return packet
    packets = db.list_decision_packets(run_id)
    return packets[-1] if packets else None


def _base_payload(run_id: str, db: AgentRunwayDb, last_activity: dict[str, Any] | None) -> dict[str, Any]:
    latest = db.latest_checkpoint(run_id)
    return {
        "run_id": run_id,
        "latest_checkpoint": {
            "checkpoint_id": latest["checkpoint_id"],
            "commit_sha": latest["commit_sha"],
            "reason": latest["reason"],
        }
        if latest
        else None,
        "last_activity": _compact_activity(last_activity),
        "reuse_completed_activity": False,
    }


def plan_activity_resume(*, run_id: str, db: AgentRunwayDb) -> dict[str, Any]:
    activities = db.list_activities(run_id)
    last_activity = activities[-1] if activities else None
    payload = _base_payload(run_id, db, last_activity)
    if last_activity is None:
        payload.update(
            {
                "next_node": None,
                "next_action": "inspect_worker_state",
                "reason": "no_durable_activity",
            }
        )
        return payload

    blocked = next(
        (activity for activity in reversed(activities) if activity.get("status") in {"failed", "blocked"}),
        None,
    )
    if blocked is not None:
        failure_class = str(blocked.get("failure_class") or "")
        if failure_class in _HUMAN_DECISION_FAILURE_CLASSES:
            packet = _decision_for_activity(db, run_id, blocked)
            payload.update(
                {
                    "next_node": packet["decision_id"] if packet else f"{blocked['activity_id']}.decision",
                    "next_action": "await_human_decision",
                    "failure_class": failure_class,
                    "reason": "blocked_activity_requires_human_decision",
                }
            )
            return payload
        if failure_class == "needs_implementer_retry":
            payload.update(
                {
                    "next_node": f"{blocked['task_id']}.implement",
                    "next_action": "schedule_implementer_retry",
                    "failure_class": failure_class,
                    "reason": "gate_failure_can_retry_implementer",
                }
            )
            return payload

    task_ids = list(dict.fromkeys(str(activity["task_id"]) for activity in activities if activity.get("task_id")))
    for task_id in task_ids:
        implement = _latest_by_type(activities, task_id, "implement")
        if (
            implement
            and implement.get("status") == "completed"
            and not _has_activity_after(
                activities,
                task_id=task_id,
                activity_type="review",
                after_activity_id=str(implement["activity_id"]),
            )
        ):
            output = implement.get("output_refs") or {}
            payload.update(
                {
                    "next_node": f"{task_id}.review",
                    "next_action": "schedule_review",
                    "candidate_id": output.get("candidate_id"),
                    "reason": "implement_completed_review_not_started",
                    "reuse_completed_activity": True,
                }
            )
            return payload

        review = _latest_by_type(activities, task_id, "review")
        review_output = review.get("output_refs") if review else {}
        if (
            review
            and review.get("status") == "completed"
            and review_output.get("review_status") == "approved"
            and not _has_activity_after(
                activities,
                task_id=task_id,
                activity_type="verification",
                after_activity_id=str(review["activity_id"]),
            )
        ):
            payload.update(
                {
                    "next_node": f"{task_id}.verification",
                    "next_action": "schedule_verification",
                    "candidate_id": review_output.get("candidate_id"),
                    "reason": "review_approved_verification_not_started",
                    "reuse_completed_activity": True,
                }
            )
            return payload

        verification = _latest_by_type(activities, task_id, "verification")
        verification_output = verification.get("output_refs") if verification else {}
        if (
            verification
            and verification.get("status") == "completed"
            and verification_output.get("verification_status") == "passed"
            and not _has_activity_after(
                activities,
                task_id=task_id,
                activity_type="merge",
                after_activity_id=str(verification["activity_id"]),
            )
        ):
            payload.update(
                {
                    "next_node": f"{task_id}.merge",
                    "next_action": "schedule_merge",
                    "candidate_id": verification_output.get("candidate_id"),
                    "reason": "verification_passed_merge_not_started",
                    "reuse_completed_activity": True,
                }
            )
            return payload

        merge = _latest_by_type(activities, task_id, "merge")
        merge_output = merge.get("output_refs") if merge else {}
        if merge and merge.get("status") == "completed":
            payload.update(
                {
                    "next_node": f"{task_id}.checkpoint",
                    "next_action": "verify_checkpoint",
                    "checkpoint_id": merge_output.get("checkpoint_id"),
                    "reason": "merge_completed_checkpoint_should_exist",
                    "reuse_completed_activity": True,
                }
            )
            return payload

    payload.update(
        {
            "next_node": None,
            "next_action": "none",
            "reason": "no_resumable_activity_boundary",
        }
    )
    return payload
