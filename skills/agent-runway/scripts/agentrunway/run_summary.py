from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from .db import AgentRunwayDb
from .diagnostics import diagnose_run


AGENTLENS_DISABLED_NOTICE = "AgentLens disabled; local SQLite and artifacts are authoritative."


def _duration_seconds(started_at: str | None, ended_at: str | None) -> float | None:
    if not started_at or not ended_at:
        return None
    try:
        started = datetime.fromisoformat(started_at)
        ended = datetime.fromisoformat(ended_at)
    except ValueError:
        return None
    return max((ended - started).total_seconds(), 0.0)


def _safe_events_tail(run_dir: Path, limit: int) -> list[dict[str, Any]]:
    path = run_dir / "events.jsonl"
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines()[-limit:]:
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            rows.append({"event_type": "malformed_event"})
    return rows


def _workflow_summary(db: AgentRunwayDb, run_id: str) -> dict[str, Any]:
    if not run_id:
        return {}
    from .durable_projection import durable_operator_next_action, read_durable_projection

    projection = read_durable_projection(run_id=run_id, db=db)
    payload = projection.to_dict()
    latest = payload.get("latest_checkpoint")
    return {
        "latest_checkpoint": {
            "id": latest.get("checkpoint_id"),
            "commit": latest.get("commit_sha"),
            "reason": latest.get("reason"),
        }
        if isinstance(latest, dict)
        else None,
        "graph": payload["graph"],
        "blocked_node": payload["blocked_node"],
        "failure_class": payload["failure_class"],
        "next_automatic_action": payload["next_automatic_action"],
        "required_human_decision": payload["required_human_decision"],
        "ready_queue": payload["ready_queue"],
        "safe_wave": payload["safe_wave"],
        "decision_packet": payload["decision_packet"],
        "durable": payload,
        "next_action": durable_operator_next_action(payload),
    }


def reconstruct_run_json(*, run_id: str, run_dir: Path) -> dict[str, Any]:
    state_db = run_dir / "state.sqlite"
    reconstructed_from = ["run.json"]
    if not state_db.exists():
        return {
            "run_id": run_id,
            "status": "missing",
            "run_dir": str(run_dir),
            "state_db": None,
            "tasks": [],
            "reconstructed_from": reconstructed_from,
            "recovery": "no_state_sqlite",
        }
    db = AgentRunwayDb.open(state_db)
    run = db.get_run(run_id)
    reconstructed_from.append("state.sqlite")
    return {
        "run_id": run_id,
        "status": run.get("status", "unknown"),
        "run_dir": str(run_dir),
        "state_db": str(state_db),
        "tasks": db.list_tasks(),
        "main_worktree": "",
        "repo_root": run.get("repo_root"),
        "plan_path": run.get("plan_path"),
        "spec_path": run.get("spec_path"),
        "contract_path": run.get("contract_path"),
        "plan_hash": run.get("plan_hash"),
        "spec_hash": run.get("spec_hash"),
        "base_commit_sha": run.get("base_commit_sha"),
        "model_profile": run.get("model_profile"),
        "allowed_dirty": bool(run.get("allowed_dirty")),
        "apply_to_source": bool(run.get("apply_to_source")),
        "reconstructed_from": reconstructed_from,
    }


def build_run_summary(*, run_json: dict[str, Any], db: AgentRunwayDb, event_tail: int = 20) -> dict[str, Any]:
    run_dir = Path(str(run_json["run_dir"]))
    state_db = run_json.get("state_db")
    tasks = db.list_tasks() if state_db and Path(str(state_db)).exists() else list(run_json.get("tasks") or [])
    task_counts = Counter(str(task.get("status", "unknown")) for task in tasks)
    diagnosis = diagnose_run(run_json=run_json, db=db).to_dict()
    agentlens = db.agentlens_summary()
    blocked_tasks = [
        {"task_id": task.get("task_id"), "status": task.get("status"), "reason": diagnosis.get("reason")}
        for task in tasks
        if str(task.get("status")) == "blocked"
    ]
    ranked_events = [
        event.get("payload", {})
        for event in db.list_events()
        if event.get("event_type") == "agentrunway.candidate_ranked"
    ]
    selected_ids = {
        int(payload.get("selected_candidate_id"))
        for payload in ranked_events
        if payload.get("selected_candidate_id") is not None
    }
    workers = db.list_workers()
    summary = {
        "run_id": run_json.get("run_id"),
        "status": run_json.get("status"),
        "base_commit": run_json.get("base_commit_sha") or run_json.get("base_commit"),
        "task_counts": dict(sorted(task_counts.items())),
        "current_task": blocked_tasks[0]["task_id"] if blocked_tasks else None,
        "next_action": diagnosis["next_action"],
        "selected_candidates": [
            candidate
            for candidate in db.list_merge_candidates()
            if int(candidate.get("id", -1)) in selected_ids or candidate.get("status") == "merged"
        ],
        "worker_durations": [
            {
                "worker_id": worker.get("worker_id"),
                "task_id": worker.get("task_id"),
                "role": worker.get("role"),
                "state": worker.get("state"),
                "started_at": worker.get("started_at"),
                "ended_at": worker.get("ended_at"),
                "duration_seconds": _duration_seconds(worker.get("started_at"), worker.get("ended_at")),
            }
            for worker in workers
        ],
        "blocked_tasks": blocked_tasks,
        "quality_decisions": [
            event.get("payload", {})
            for event in db.list_events()
            if event.get("event_type") == "agentrunway.quality_decision"
        ],
        "residual_risks": [],
        "agentlens": agentlens,
        "agentlens_notice": AGENTLENS_DISABLED_NOTICE if agentlens.get("run_status") == "disabled" else "",
        "event_tail": _safe_events_tail(run_dir, event_tail),
        "artifact_refs": {
            "events": str(run_dir / "events.jsonl"),
            "state": str(run_dir / "state.sqlite"),
            "run": str(run_dir / "run.json"),
        },
    }
    if "reconstructed_from" in run_json:
        summary["reconstructed_from"] = run_json["reconstructed_from"]
    if "recovery" in run_json:
        summary["recovery"] = run_json["recovery"]
    workflow = _workflow_summary(db, str(run_json.get("run_id")))
    fallback_next_action = summary["next_action"]
    summary.update(workflow)
    if workflow:
        from .durable_projection import durable_operator_next_action

        summary["next_action"] = durable_operator_next_action(workflow["durable"], fallback_next_action)
    return summary
