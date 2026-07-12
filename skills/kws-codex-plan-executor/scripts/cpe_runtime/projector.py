from __future__ import annotations

from copy import deepcopy

from .events import EVENT_TYPES
from .runtime_upgrade import RuntimeIdentity, validate_runtime_upgrade


RUN_SCHEMA_VERSION = "4"
RUN_TRANSITIONS = {
    "created": {"ready", "blocked", "failed"},
    "ready": {"running", "blocked", "failed"},
    "running": {"completed", "blocked", "failed", "waiting_user", "waiting_external"},
    "waiting_user": {"running", "blocked", "failed"},
    "waiting_external": {"running", "blocked", "failed"},
    "blocked": {"ready", "failed"},
    "failed": set(),
    "completed": set(),
}
TASK_TRANSITIONS = {
    "pending": {"ready", "blocked", "failed", "waiting_user", "waiting_external"},
    "ready": {"scouting", "implementing", "blocked", "failed", "waiting_user", "waiting_external"},
    "scouting": {"implementing", "blocked", "failed"},
    "implementing": {"reviewing", "repairing", "blocked", "failed"},
    "reviewing": {"verifying", "repairing", "blocked", "failed"},
    "verifying": {"completed", "repairing", "blocked", "failed"},
    "repairing": {"reviewing", "verifying", "blocked", "failed"},
    "waiting_user": {"ready", "blocked", "failed"},
    "waiting_external": {"ready", "blocked", "failed"},
    "completed": set(),
    "blocked": {"failed"},
    "failed": set(),
}

# Kept as scheduler vocabulary while v4 scheduler work lands; no legacy event
# type is accepted or projected from this mapping.
RETRY_PHASE_STATES = {
    "implementation": "implementing",
    "repair": "repairing",
    "acceptance": "verifying",
    "task_review": "reviewing",
    "verification": "verifying",
}


def _require_v4_schema(value: object) -> dict:
    if not isinstance(value, dict) or value.get("schema_version") != RUN_SCHEMA_VERSION:
        raise ValueError("unsupported_run_schema")
    return value


def valid_evidence_refs(value: object) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(ref, dict) and bool(ref) for ref in value)
    )


def valid_attempt_completion(
    state: dict,
    task_id: str | None,
    attempt_id: str | None,
    payload: dict,
) -> bool:
    matches = [item for item in state.get("attempts", []) if item.get("attempt_id") == attempt_id]
    usage = payload.get("usage")
    latency = payload.get("latency_ms")
    status = payload.get("status")
    return (
        isinstance(attempt_id, str)
        and bool(attempt_id)
        and len(matches) == 1
        and matches[0].get("task_id") == task_id
        and matches[0].get("status") == "started"
        and status in {"completed", "failed", "interrupted"}
        and isinstance(payload.get("attestation"), dict)
        and isinstance(usage, dict)
        and all(
            isinstance(key, str)
            and isinstance(value, int)
            and not isinstance(value, bool)
            and value >= 0
            for key, value in usage.items()
        )
        and isinstance(latency, int)
        and not isinstance(latency, bool)
        and latency >= 0
        and (status == "completed" or valid_evidence_refs(payload.get("evidence_refs")))
    )


def valid_verdict(
    state: dict,
    task_id: str | None,
    attempt_id: str | None,
    payload: dict,
) -> bool:
    matches = [item for item in state.get("attempts", []) if item.get("attempt_id") == attempt_id]
    return (
        isinstance(attempt_id, str)
        and bool(attempt_id)
        and len(matches) == 1
        and matches[0].get("task_id") == task_id
        and payload.get("status") in {"passed", "changes_requested", "blocked", "inconclusive"}
        and isinstance(payload.get("findings"), list)
        and isinstance(payload.get("missing_evidence"), list)
    )


def owned_active_blocker(state: dict, task_id: str | None, blocker_id: object) -> dict | None:
    matches = [
        item
        for item in state.get("active_blockers", [])
        if item.get("blocker_id") == blocker_id and item.get("task_id") == task_id
    ]
    return matches[0] if len(matches) == 1 else None


def initial_state(manifest: dict) -> dict:
    manifest = _require_v4_schema(manifest)
    tasks = {
        str(task["id"]): {
            "id": str(task["id"]),
            "title": str(task.get("title", task["id"])),
            "status": "pending",
            "dependencies": list(task.get("dependencies") or []),
            "file_claims": list(task.get("file_claims") or []),
            "spec_refs": list(task.get("spec_refs") or []),
            "acceptance_command": task.get("acceptance_command"),
            "task_contract_sha256": task.get("task_contract_sha256"),
        }
        for task in manifest.get("task_graph", [])
    }
    runtime = RuntimeIdentity.from_mapping(manifest.get("runtime"))
    return {
        "schema_version": RUN_SCHEMA_VERSION,
        "run_id": manifest.get("run_id"),
        "lifecycle": "created",
        "current_task": None,
        "runtime": runtime.as_dict(),
        "tasks": tasks,
        "attempts": [],
        "verdicts": [],
        "active_blockers": [],
        "blocker_history": [],
        "candidate_checkpoints": [],
        "verified_checkpoints": [],
        "checkpoint_head": (manifest.get("source_git") or {}).get("head"),
        "decisions": [],
        "notifications": [],
        "backlog": [],
        "repair_roots": {},
        "wait_reason": None,
        "attempt_budget": {"limit": 40, "used": 0},
        "completion_audit": None,
        "usage_totals": {
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "output_tokens": 0,
            "reasoning_output_tokens": 0,
        },
        "artifact_index": [],
        "last_event": {"seq": 0, "hash": None},
    }


def apply_event(state: dict, event: dict) -> dict:
    _require_v4_schema(state)
    if not isinstance(event, dict) or event.get("type") not in EVENT_TYPES:
        raise ValueError("unknown event type")
    state = deepcopy(state)
    state["last_event"] = {"seq": event["seq"], "hash": event["hash"]}
    payload = deepcopy(event.get("payload", {}))
    if not isinstance(payload, dict):
        raise ValueError("invalid event payload")
    typ = event["type"]
    if typ == "run.status_changed":
        state["lifecycle"] = payload["to"]
        state["wait_reason"] = payload.get("wait_reason")
    elif typ == "task.status_changed":
        task_id = event.get("task_id")
        if task_id not in state["tasks"]:
            raise ValueError("unknown task")
        state["tasks"][task_id]["status"] = payload["to"]
        state["current_task"] = (
            None
            if payload["to"] in {"completed", "blocked", "failed", "waiting_user", "waiting_external"}
            else task_id
        )
        state["wait_reason"] = payload.get("wait_reason")
    elif typ == "attempt.started":
        if state["attempt_budget"]["used"] >= state["attempt_budget"]["limit"]:
            raise ValueError("attempt_budget_exhausted")
        state["attempt_budget"]["used"] += 1
        state["attempts"].append(
            {
                "task_id": event.get("task_id"),
                "attempt_id": event.get("attempt_id"),
                "status": "started",
                **payload,
            }
        )
    elif typ == "attempt.completed":
        attempt_id = event.get("attempt_id")
        if not valid_attempt_completion(state, event.get("task_id"), attempt_id, payload):
            raise ValueError("invalid attempt payload")
        matching = [item for item in state["attempts"] if item.get("attempt_id") == attempt_id]
        matching[0].update(payload)
        for key in state["usage_totals"]:
            state["usage_totals"][key] += int((payload.get("usage") or {}).get(key, 0) or 0)
    elif typ == "verdict.recorded":
        if not valid_verdict(state, event.get("task_id"), event.get("attempt_id"), payload):
            raise ValueError("invalid verdict payload")
        state["verdicts"].append(
            {"task_id": event.get("task_id"), "attempt_id": event.get("attempt_id"), **payload}
        )
    elif typ == "evidence.attached":
        state["artifact_index"].append(
            {"task_id": event.get("task_id"), "attempt_id": event.get("attempt_id"), **payload}
        )
    elif typ == "candidate.checkpoint_recorded":
        state["candidate_checkpoints"].append({"task_id": event.get("task_id"), **payload})
    elif typ == "task.checkpoint_verified":
        state["verified_checkpoints"].append({"task_id": event.get("task_id"), **payload})
        state["checkpoint_head"] = payload["commit"]
    elif typ == "blocker.opened":
        blocker_id = payload["blocker_id"]
        if any(item.get("blocker_id") == blocker_id for item in state["blocker_history"]):
            raise ValueError("duplicate blocker")
        blocker = {"task_id": event.get("task_id"), **payload, "status": "open"}
        state["active_blockers"].append(blocker)
        state["blocker_history"].append(deepcopy(blocker))
    elif typ == "blocker.resolved":
        blocker_id = payload["blocker_id"]
        blocker = owned_active_blocker(state, event.get("task_id"), blocker_id)
        if blocker is None or not valid_evidence_refs(payload.get("evidence_refs")):
            raise ValueError("invalid blocker resolution payload")
        state["active_blockers"] = [
            item for item in state["active_blockers"] if item.get("blocker_id") != blocker_id
        ]
        history = [item for item in state["blocker_history"] if item.get("blocker_id") == blocker_id]
        history[0].update(payload)
        history[0]["status"] = "resolved"
    elif typ == "decision.recorded":
        state["decisions"].append(payload)
    elif typ == "notification.requested":
        state["notifications"].append(payload)
    elif typ == "runtime.upgraded":
        target = validate_runtime_upgrade(
            RuntimeIdentity.from_mapping(state["runtime"]),
            payload,
            checkpoint_head=state["checkpoint_head"],
        )
        state["runtime"] = target.as_dict()
    elif typ == "completion.recorded":
        state["completion_audit"] = payload
    return state


def project(manifest: dict, events: list[dict]) -> dict:
    state = initial_state(manifest)
    for event in events:
        state = apply_event(state, event)
    return state
