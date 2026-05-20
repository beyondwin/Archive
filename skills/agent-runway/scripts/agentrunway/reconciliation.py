from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .db import AgentRunwayDb
from .events import build_event_payload
from .result_validation import ResultValidationError, validate_worker_result


def _result_path(run_dir: Path, worker: dict[str, Any]) -> Path:
    role = str(worker["role"])
    filename = "worker_result.json"
    if role == "reviewer":
        filename = "review_result.json"
    if role == "verifier":
        filename = "verification_result.json"
    return run_dir / "artifacts" / str(worker["task_id"]) / str(worker["worker_id"]) / filename


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


def _valid_worker_result(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        validate_worker_result(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, ResultValidationError):
        return False
    return True


def plan_reconciliation(*, run_id: str, run_dir: Path, db: AgentRunwayDb) -> dict[str, Any]:
    actions: list[dict[str, Any]] = []
    for worker in db.list_workers():
        state = str(worker["state"])
        if state in {"merged", "blocked", "cancelled", "validated", "result_collected"}:
            continue
        result_path = _result_path(run_dir, worker)
        if _valid_worker_result(result_path):
            actions.append(
                {
                    "target": worker["worker_id"],
                    "action": "reconcile_forward",
                    "reason": "valid_result_artifact_exists",
                    "writes": True,
                }
            )
            continue
        if state == "running" and not _process_alive(worker.get("handle_json", {})):
            actions.append(
                {
                    "target": worker["worker_id"],
                    "action": "retry",
                    "reason": "dead_process_missing_result",
                    "writes": True,
                }
            )
    return {"run_id": run_id, "actions": actions}


def _resume_action_exists(db: AgentRunwayDb, target: str, action: str) -> bool:
    for event in db.list_events():
        if event["event_type"] != "agentrunway.resume_action":
            continue
        payload = event.get("payload", {})
        if payload.get("target") == target and payload.get("action") == action:
            return True
    return False


def _record_resume_action(db: AgentRunwayDb, run_id: str, target: str, action: str, outcome: str, summary: str) -> None:
    if _resume_action_exists(db, target, action):
        return
    db.insert_event(
        event_type="agentrunway.resume_action",
        payload=build_event_payload(run_id, "resume", outcome, summary, target=target, action=action),
        status="agentlens_disabled",
    )


def apply_reconciliation_plan(*, db: AgentRunwayDb, plan: dict[str, Any]) -> None:
    for action in plan.get("actions", []):
        target = str(action["target"])
        if action["action"] == "reconcile_forward":
            worker = db.get_worker(target)
            if worker["state"] != "result_collected":
                db.set_worker_state(target, "result_collected")
                _record_resume_action(
                    db,
                    str(plan["run_id"]),
                    target,
                    "reconcile_forward",
                    "success",
                    "reconciled forward",
                )
        elif action["action"] == "retry":
            worker = db.get_worker(target)
            if worker["state"] == "running":
                db.set_worker_state(target, "stalled")
                _record_resume_action(
                    db,
                    str(plan["run_id"]),
                    target,
                    "retry",
                    "partial",
                    "retry required",
                )
