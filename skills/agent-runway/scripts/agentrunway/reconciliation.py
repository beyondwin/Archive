from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .db import AgentRunwayDb
from .events import build_event_payload
from .quality_policy import conflict_decision
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


def _load_run_json(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "run.json"
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _git_metadata_dir(worktree: Path) -> Path:
    dotgit = worktree / ".git"
    if dotgit.is_dir():
        return dotgit
    if dotgit.is_file():
        raw = dotgit.read_text(encoding="utf-8", errors="ignore").strip()
        prefix = "gitdir:"
        if raw.startswith(prefix):
            path = Path(raw.removeprefix(prefix).strip())
            return path if path.is_absolute() else (worktree / path).resolve()
    return dotgit


def _has_interrupted_cherry_pick(worktree: Path) -> bool:
    return (_git_metadata_dir(worktree) / "CHERRY_PICK_HEAD").exists()


def _conflict_redispatch_count(db: AgentRunwayDb, task_id: str) -> int:
    count = 0
    for event in db.list_events():
        if event["event_type"] != "agentrunway.conflict_redispatch_planned":
            continue
        payload = event.get("payload", {})
        if payload.get("task_id") == task_id:
            count += 1
    return count


def _action_exists(actions: list[dict[str, Any]], target: str, action: str) -> bool:
    return any(item.get("target") == target and item.get("action") == action for item in actions)


def plan_reconciliation(*, run_id: str, run_dir: Path, db: AgentRunwayDb) -> dict[str, Any]:
    actions: list[dict[str, Any]] = []
    run_json = _load_run_json(run_dir)
    main_worktree_raw = run_json.get("main_worktree")
    if isinstance(main_worktree_raw, str) and main_worktree_raw.strip():
        main_worktree = Path(main_worktree_raw)
        if _has_interrupted_cherry_pick(main_worktree):
            actions.append(
                {
                    "target": str(main_worktree),
                    "action": "abort_cherry_pick",
                    "reason": "interrupted_cherry_pick",
                    "writes": True,
                }
            )
    for candidate in db.list_merge_candidates():
        if candidate["status"] != "merge_conflict":
            continue
        task_id = str(candidate["task_id"])
        decision = conflict_decision(
            task_id=task_id,
            previous_conflicts=_conflict_redispatch_count(db, task_id),
        )
        action = "conflict_redispatch" if decision.action == "redispatch" else "manual_action"
        if not _action_exists(actions, task_id, action):
            actions.append(
                {
                    "target": task_id,
                    "action": action,
                    "reason": decision.reason,
                    "writes": action == "conflict_redispatch",
                }
            )
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
            if db.count_worker_attempts(task_id=str(worker["task_id"]), role=str(worker["role"])) >= 2:
                target = str(worker["task_id"])
                if not any(item.get("target") == target and item.get("action") == "block" for item in actions):
                    actions.append(
                        {
                            "target": target,
                            "action": "block",
                            "reason": "retry_budget_exhausted",
                            "writes": True,
                        }
                    )
                continue
            actions.append(
                {
                    "target": worker["worker_id"],
                    "action": "retry",
                    "reason": "dead_process_missing_result",
                    "writes": True,
                }
            )
    return {"run_id": run_id, "run_dir": str(run_dir), "actions": actions}


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
        elif action["action"] == "abort_cherry_pick":
            _record_resume_action(
                db,
                str(plan["run_id"]),
                target,
                "abort_cherry_pick",
                "partial",
                "operator must abort interrupted cherry-pick",
            )
        elif action["action"] == "block":
            task = db.get_task(target)
            if task["status"] != "blocked":
                db.set_task_status(target, "blocked")
                _record_resume_action(
                    db,
                    str(plan["run_id"]),
                    target,
                    "block",
                    "failed",
                    "retry budget exhausted",
                )
        elif action["action"] == "conflict_redispatch":
            if not _resume_action_exists(db, target, "conflict_redispatch"):
                _record_resume_action(
                    db,
                    str(plan["run_id"]),
                    target,
                    "conflict_redispatch",
                    "partial",
                    "conflict redispatch required",
                )
                candidate_id = next(
                    (
                        int(candidate["id"])
                        for candidate in db.list_merge_candidates()
                        if str(candidate["task_id"]) == target and candidate["status"] == "merge_conflict"
                    ),
                    0,
                )
                from .decision_events import record_conflict_redispatch_planned
                from .events import EventJournal

                record_conflict_redispatch_planned(
                    EventJournal(db=db, run_dir=Path(str(plan.get("run_dir") or "."))),
                    run_id=str(plan["run_id"]),
                    task_id=target,
                    candidate_id=candidate_id,
                    reason=str(action.get("reason") or "merge_conflict"),
                )
        elif action["action"] == "manual_action":
            _record_resume_action(
                db,
                str(plan["run_id"]),
                target,
                "manual_action",
                "failed",
                "manual action required",
            )
