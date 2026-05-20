from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

from .db import AgentRunwayDb
from .models import FileClaim, TaskSpec
from .scheduler import ready_tasks_after_checkpoints, schedule_safe_wave


_HUMAN_DECISION_BY_FAILURE_CLASS = {
    "needs_plan_fix": "fix plan",
    "needs_split": "approve task split",
    "needs_infra_fix": "fix infrastructure",
    "needs_human_decision": "inspect decision packet",
    "terminal_rejected": "inspect terminal rejection",
}

_TERMINAL_TASK_STATUSES = {"blocked", "failed", "merged"}


@dataclass(frozen=True)
class DurableProjection:
    run_id: str
    latest_checkpoint: dict[str, Any] | None
    completed_checkpoint_tasks: list[str]
    checkpoint_repair_tasks: list[str]
    ready_tasks: list[dict[str, Any]]
    safe_wave: list[dict[str, Any]]
    running_activities: list[dict[str, Any]]
    blocked_node: str | None
    failure_class: str | None
    next_automatic_action: str | None
    required_human_decision: str | None
    decision_packet: dict[str, Any] | None
    graph: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["ready_queue"] = [task["task_id"] for task in self.ready_tasks]
        payload["safe_wave"] = [task["task_id"] for task in self.safe_wave]
        return payload


def durable_operator_next_action(projection: dict[str, Any], fallback: str | None = None) -> str | None:
    if projection.get("required_human_decision"):
        return "await_human_decision"
    if projection.get("next_automatic_action"):
        return str(projection["next_automatic_action"])
    return fallback


def _json_list(row: dict[str, Any], key: str) -> tuple[str, ...]:
    raw = row.get(key)
    if isinstance(raw, str):
        value = json.loads(raw)
    else:
        value = raw or []
    return tuple(str(item) for item in value)


def _task_from_row(row: dict[str, Any], claims: list[dict[str, Any]]) -> TaskSpec:
    return TaskSpec(
        task_id=str(row["task_id"]),
        title=str(row["title"]),
        risk=str(row["risk"]),  # type: ignore[arg-type]
        phase=str(row["phase"]),
        dependencies=_json_list(row, "dependencies_json"),
        spec_refs=_json_list(row, "spec_refs_json"),
        file_claims=tuple(FileClaim(str(claim["path"]), str(claim["mode"])) for claim in claims),  # type: ignore[arg-type]
        acceptance_commands=_json_list(row, "acceptance_commands_json"),
        resource_keys=_json_list(row, "resource_keys_json"),
        required_skills=_json_list(row, "required_skills_json"),
        serial=bool(row.get("serial")),
        objective=str(row.get("objective") or ""),
        line=int(row.get("line") or 0),
    )


def _task_rows(db: AgentRunwayDb) -> list[dict[str, Any]]:
    return db.list_tasks()


def _task_specs(db: AgentRunwayDb) -> list[TaskSpec]:
    specs: list[TaskSpec] = []
    for row in _task_rows(db):
        claims = [
            dict(claim)
            for claim in db.conn.execute(
                "SELECT path, mode FROM file_claims WHERE task_id=? ORDER BY path, mode",
                (row["task_id"],),
            ).fetchall()
        ]
        specs.append(_task_from_row(row, claims))
    return specs


def _completed_checkpoint_tasks(checkpoints: list[dict[str, Any]]) -> list[str]:
    completed: list[str] = []
    for checkpoint in checkpoints:
        reason = str(checkpoint.get("reason") or "")
        if not reason.startswith("merged:"):
            continue
        task_id = reason.split(":", 1)[1]
        if task_id and task_id not in completed:
            completed.append(task_id)
    return completed


def _checkpoint_repair_tasks(task_rows: list[dict[str, Any]], completed_checkpoint_tasks: list[str]) -> list[str]:
    completed = set(completed_checkpoint_tasks)
    return [
        str(row["task_id"])
        for row in task_rows
        if str(row.get("status") or "") == "merged" and str(row["task_id"]) not in completed
    ]


def _compact_task(task: TaskSpec) -> dict[str, Any]:
    return {
        "task_id": task.task_id,
        "risk": task.risk,
        "dependencies": list(task.dependencies),
        "file_claims": [{"path": claim.path, "mode": claim.mode} for claim in task.file_claims],
        "resource_keys": list(task.resource_keys),
        "serial": task.serial,
    }


def _compact_activity(activity: dict[str, Any]) -> dict[str, Any]:
    return {
        "activity_id": activity.get("activity_id"),
        "activity_type": activity.get("activity_type"),
        "task_id": activity.get("task_id"),
        "status": activity.get("status"),
        "failure_class": activity.get("failure_class"),
        "output_refs": activity.get("output_refs") or {},
    }


def _decision_for_activity(db: AgentRunwayDb, run_id: str, activity_id: str) -> dict[str, Any] | None:
    packets = db.list_decision_packets(run_id)
    for packet in packets:
        if str(packet.get("decision_id")).startswith(activity_id):
            payload = dict(packet)
            raw = payload.get("payload_json")
            if isinstance(raw, str):
                payload["payload"] = json.loads(raw)
            return payload
    if packets:
        payload = dict(packets[-1])
        raw = payload.get("payload_json")
        if isinstance(raw, str):
            payload["payload"] = json.loads(raw)
        return payload
    return None


def read_durable_projection(*, run_id: str, db: AgentRunwayDb) -> DurableProjection:
    checkpoints = db.list_checkpoints(run_id)
    latest = db.latest_checkpoint(run_id)
    completed_checkpoint_tasks = _completed_checkpoint_tasks(checkpoints)
    task_rows = _task_rows(db)
    checkpoint_repair_tasks = _checkpoint_repair_tasks(task_rows, completed_checkpoint_tasks)
    completed_tasks = {
        str(row["task_id"])
        for row in task_rows
        if str(row.get("status") or "") in _TERMINAL_TASK_STATUSES
    }
    tasks = _task_specs(db)
    ready = ready_tasks_after_checkpoints(
        tasks,
        completed_checkpoints=set(completed_checkpoint_tasks),
        completed_tasks=completed_tasks,
    )
    safe_wave = schedule_safe_wave(ready)
    activities = db.list_activities(run_id)
    running = [activity for activity in activities if activity.get("status") == "started"]
    blocked = next(
        (activity for activity in reversed(activities) if activity.get("status") in {"failed", "blocked"}),
        None,
    )
    failure_class = str(blocked.get("failure_class")) if blocked and blocked.get("failure_class") else None
    human_decision = _HUMAN_DECISION_BY_FAILURE_CLASS.get(failure_class) if failure_class else None
    decision_packet = _decision_for_activity(db, run_id, str(blocked["activity_id"])) if blocked else None
    return DurableProjection(
        run_id=run_id,
        latest_checkpoint={
            "checkpoint_id": latest["checkpoint_id"],
            "commit_sha": latest["commit_sha"],
            "reason": latest["reason"],
        }
        if latest
        else None,
        completed_checkpoint_tasks=completed_checkpoint_tasks,
        checkpoint_repair_tasks=checkpoint_repair_tasks,
        ready_tasks=[_compact_task(task) for task in ready],
        safe_wave=[_compact_task(task) for task in safe_wave],
        running_activities=[_compact_activity(activity) for activity in running],
        blocked_node=str(blocked["activity_id"]) if blocked else None,
        failure_class=failure_class,
        next_automatic_action=None if human_decision else ("verify_checkpoint" if checkpoint_repair_tasks else ("resume" if blocked else None)),
        required_human_decision=human_decision,
        decision_packet=decision_packet,
        graph={
            "complete": sum(1 for activity in activities if activity.get("status") == "completed"),
            "ready": len(ready),
            "running": len(running),
            "blocked": sum(1 for activity in activities if activity.get("status") in {"failed", "blocked"}),
        },
    )
