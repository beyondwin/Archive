from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from typing import Any

from .db import AgentRunwayDb


@dataclass(frozen=True)
class RunDiagnosis:
    run_id: str
    status: str
    reason: str
    next_action: str
    safe_actions: list[str] = field(default_factory=list)
    manual_actions: list[str] = field(default_factory=list)
    blocked_tasks: list[str] = field(default_factory=list)
    conflict: dict[str, Any] | None = None
    agentlens_health: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _process_alive(handle_json: dict[str, Any]) -> bool:
    pid = handle_json.get("pid")
    if pid is None and isinstance(handle_json.get("process"), dict):
        pid = handle_json["process"].get("pid")
    if pid is None:
        return False
    try:
        os.kill(int(pid), 0)
    except (OSError, ValueError):
        return False
    return True


def _agentlens_health(db: AgentRunwayDb) -> dict[str, Any]:
    summary = db.agentlens_summary()
    return {
        "status": summary.get("run_status") or summary.get("last_status") or "unknown",
        "last_status": summary.get("last_status"),
        "failed": summary.get("failed", 0),
        "last_error": summary.get("last_error"),
    }


def diagnose_run(*, run_json: dict[str, Any], db: AgentRunwayDb) -> RunDiagnosis:
    run_id = str(run_json.get("run_id") or "unknown")
    run_status = str(run_json.get("status") or "unknown")
    agentlens = _agentlens_health(db)

    for candidate in db.list_merge_candidates():
        if candidate["status"] == "merge_conflict":
            return RunDiagnosis(
                run_id=run_id,
                status="needs_conflict_redispatch",
                reason="merge_conflict",
                next_action=f"agentrunway resume --run {run_id} --dry-run",
                safe_actions=["resume", "inspect"],
                conflict={"task_id": candidate["task_id"], "candidate_id": int(candidate["id"])},
                agentlens_health=agentlens,
            )

    blocked_tasks = [
        str(task["task_id"])
        for task in db.list_tasks()
        if str(task.get("status")) == "blocked"
    ]
    if blocked_tasks:
        return RunDiagnosis(
            run_id=run_id,
            status="blocked_by_gate",
            reason="gate_budget_exhausted",
            next_action=f"agentrunway inspect --run {run_id}",
            safe_actions=["inspect", "resume"],
            blocked_tasks=blocked_tasks,
            agentlens_health=agentlens,
        )

    for worker in db.list_workers():
        if worker["state"] == "running" and not _process_alive(worker.get("handle_json", {})):
            return RunDiagnosis(
                run_id=run_id,
                status="needs_resume",
                reason="dead_worker_missing_result",
                next_action=f"agentrunway resume --run {run_id}",
                safe_actions=["resume", "inspect"],
                agentlens_health=agentlens,
            )

    if run_status == "finished":
        return RunDiagnosis(
            run_id=run_id,
            status="finished",
            reason="none",
            next_action="apply or inspect artifacts",
            safe_actions=["apply", "inspect"],
            agentlens_health=agentlens,
        )
    if run_status in {"created", "running"}:
        return RunDiagnosis(
            run_id=run_id,
            status="running",
            reason="none",
            next_action="continue monitoring",
            safe_actions=["status", "inspect"],
            agentlens_health=agentlens,
        )
    if run_status in {"blocked", "failed"}:
        return RunDiagnosis(
            run_id=run_id,
            status="needs_manual_action",
            reason="blocked",
            next_action=f"agentrunway inspect --run {run_id}",
            safe_actions=["inspect"],
            manual_actions=["inspect blocked run"],
            agentlens_health=agentlens,
        )
    if run_status == "cancelled":
        return RunDiagnosis(
            run_id=run_id,
            status="needs_manual_action",
            reason="cancelled",
            next_action="inspect events before restarting",
            safe_actions=["inspect"],
            manual_actions=["inspect cancelled run"],
            agentlens_health=agentlens,
        )
    return RunDiagnosis(
        run_id=run_id,
        status="missing" if run_status == "missing" else "needs_manual_action",
        reason="unknown",
        next_action="inspect run state",
        safe_actions=["inspect"],
        manual_actions=["inspect run state"],
        agentlens_health=agentlens,
    )
