from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from .db import AgentRunwayDb
from .models import FileClaim, TaskSpec
from .scheduler import ready_tasks_after_checkpoints, schedule_safe_wave
from .task_classifier import classify_task


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
    withheld_tasks: list[dict[str, Any]]
    stale_activities: list[dict[str, Any]]
    task_classes: list[dict[str, Any]]
    projection_status: str
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


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _stale_activities(activities: list[dict[str, Any]], *, stale_after_seconds: int) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)
    stale: list[dict[str, Any]] = []
    for activity in activities:
        if activity.get("status") != "started":
            continue
        started = _parse_timestamp(activity.get("created_at"))
        if started is None:
            continue
        age = max((now - started).total_seconds(), 0)
        if age >= stale_after_seconds:
            payload = _compact_activity(activity)
            payload["age_seconds"] = int(age)
            stale.append(payload)
    return stale


def _blocked_dependency_map(task_rows: list[dict[str, Any]], tasks: list[TaskSpec]) -> dict[str, set[str]]:
    blocked_ids = {
        str(row["task_id"])
        for row in task_rows
        if str(row.get("status") or "") in {"blocked", "failed"}
    }
    return {
        task.task_id: set(task.dependencies) & blocked_ids
        for task in tasks
        if set(task.dependencies) & blocked_ids
    }


def _decode_decision_packet(packet: dict[str, Any]) -> dict[str, Any]:
    payload = dict(packet)
    raw = payload.get("payload_json")
    if isinstance(raw, str):
        payload["payload"] = json.loads(raw)
    return payload


def _decision_for_activity(db: AgentRunwayDb, run_id: str, activity: dict[str, Any]) -> dict[str, Any] | None:
    activity_id = str(activity.get("activity_id"))
    task_id = str(activity.get("task_id") or "")
    failure_class = str(activity.get("failure_class") or "")
    packets = [_decode_decision_packet(packet) for packet in db.list_decision_packets(run_id)]
    for packet in packets:
        if str(packet.get("decision_id")).startswith(activity_id):
            return packet
    for packet in reversed(packets):
        if task_id and packet.get("task_id") == task_id and packet.get("failure_class") == failure_class:
            return packet
    for packet in reversed(packets):
        if task_id and packet.get("task_id") == task_id:
            return packet
    if packets:
        return packets[-1]
    return None


def _unresolved_blocked_activities(
    activities: list[dict[str, Any]],
    *,
    task_rows: list[dict[str, Any]],
    completed_checkpoint_tasks: list[str],
) -> list[dict[str, Any]]:
    task_statuses = {str(row["task_id"]): str(row.get("status") or "") for row in task_rows}
    resolved_tasks = {
        task_id
        for task_id, status in task_statuses.items()
        if status == "merged" or task_id in set(completed_checkpoint_tasks)
    }
    return [
        activity
        for activity in activities
        if activity.get("status") in {"failed", "blocked"}
        and str(activity.get("task_id") or "") not in resolved_tasks
    ]


def _required_human_decision(failure_class: str | None, decision_packet: dict[str, Any] | None) -> str | None:
    if failure_class and failure_class in _HUMAN_DECISION_BY_FAILURE_CLASS:
        return _HUMAN_DECISION_BY_FAILURE_CLASS[failure_class]
    if decision_packet is not None:
        return "inspect decision packet"
    return None


def read_durable_projection(*, run_id: str, db: AgentRunwayDb, stale_after_seconds: int = 3600) -> DurableProjection:
    checkpoints = db.list_checkpoints(run_id)
    latest = db.latest_checkpoint(run_id)
    completed_checkpoint_tasks = _completed_checkpoint_tasks(checkpoints)
    task_rows = _task_rows(db)
    checkpoint_repair_tasks = _checkpoint_repair_tasks(task_rows, completed_checkpoint_tasks)
    tasks = _task_specs(db)
    blocked_dependencies = _blocked_dependency_map(task_rows, tasks)
    completed_tasks = {
        str(row["task_id"])
        for row in task_rows
        if str(row.get("status") or "") in _TERMINAL_TASK_STATUSES
    }
    ready = [
        task
        for task in ready_tasks_after_checkpoints(
            tasks,
            completed_checkpoints=set(completed_checkpoint_tasks),
            completed_tasks=completed_tasks,
        )
        if task.task_id not in blocked_dependencies
    ]
    safe_wave = schedule_safe_wave(ready)
    activities = db.list_activities(run_id)
    stale = _stale_activities(activities, stale_after_seconds=stale_after_seconds)
    task_classes = [
        classify_task(task, blocked_dependencies=blocked_dependencies.get(task.task_id, set())).to_dict()
        for task in tasks
    ]
    withheld_tasks = [
        {
            "task_id": task_id,
            "reason": "blocked_dependency",
            "blocked_dependencies": sorted(blocked),
        }
        for task_id, blocked in sorted(blocked_dependencies.items())
    ]
    running = [activity for activity in activities if activity.get("status") == "started"]
    unresolved_blocked = _unresolved_blocked_activities(
        activities,
        task_rows=task_rows,
        completed_checkpoint_tasks=completed_checkpoint_tasks,
    )
    blocked = next(
        (activity for activity in reversed(unresolved_blocked)),
        None,
    )
    failure_class = str(blocked.get("failure_class")) if blocked and blocked.get("failure_class") else None
    decision_packet = _decision_for_activity(db, run_id, blocked) if blocked else None
    human_decision = _required_human_decision(failure_class, decision_packet)
    blocked_task_exists = any(str(row.get("status") or "") in {"blocked", "failed"} for row in task_rows)
    automatic_action = None if human_decision else (
        "verify_checkpoint"
        if checkpoint_repair_tasks
        else ("classify_stale_activity" if stale else ("resume" if blocked else None))
    )
    if human_decision or stale or blocked_task_exists or withheld_tasks:
        projection_status = "blocked"
    elif running:
        projection_status = "running"
    elif task_rows and all(str(row.get("status") or "") == "merged" for row in task_rows) and not checkpoint_repair_tasks:
        projection_status = "finished"
    elif ready:
        projection_status = "running"
    else:
        projection_status = "blocked"
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
        safe_wave=[] if human_decision or stale else [_compact_task(task) for task in safe_wave],
        running_activities=[_compact_activity(activity) for activity in running],
        blocked_node=str(blocked["activity_id"]) if blocked else None,
        failure_class=failure_class,
        next_automatic_action=automatic_action,
        required_human_decision=human_decision,
        decision_packet=decision_packet,
        withheld_tasks=withheld_tasks,
        stale_activities=stale,
        task_classes=task_classes,
        projection_status=projection_status,
        graph={
            "complete": sum(1 for activity in activities if activity.get("status") == "completed"),
            "ready": len(ready),
            "running": len(running),
            "blocked": sum(1 for activity in activities if activity.get("status") in {"failed", "blocked"}),
        },
    )
