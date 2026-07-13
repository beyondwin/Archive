from __future__ import annotations

from copy import deepcopy
from typing import Callable

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
    "scouting": {"implementing", "blocked", "failed", "waiting_user", "waiting_external"},
    "implementing": {"reviewing", "repairing", "blocked", "failed", "waiting_user", "waiting_external"},
    "reviewing": {"verifying", "repairing", "blocked", "failed", "waiting_user", "waiting_external"},
    "verifying": {"completed", "repairing", "blocked", "failed", "waiting_user", "waiting_external"},
    "repairing": {"reviewing", "verifying", "blocked", "failed", "waiting_user", "waiting_external"},
    "waiting_user": {"ready", "implementing", "reviewing", "repairing", "verifying", "blocked", "failed"},
    "waiting_external": {"ready", "implementing", "reviewing", "repairing", "verifying", "blocked", "failed"},
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


_KERNEL_PHASES = {
    "implementation": "implemented",
    "acceptance": "accepted",
    "review": "reviewed",
    "verify": "verified",
    "repair": "repairing",
    "structural_redesign": "blocked",
    "block": "blocked",
    "wait_user": "waiting_user",
    "wait_external": "waiting_external",
    "global_integration": "integration_complete",
}


def project_kernel_event(
    state: dict,
    event: dict,
    *,
    crash_hook: Callable[[str], None] | None = None,
) -> dict:
    """Project one vNext kernel event without mutating its input.

    Durable append remains a kernel responsibility.  This projector only
    validates state-changing command payloads and returns a replacement value.
    """

    if not isinstance(state, dict) or not isinstance(event, dict):
        raise ValueError("kernel_projection_invalid")
    command = event.get("command")
    outcome = event.get("outcome")
    if not isinstance(command, str) or not isinstance(outcome, str):
        raise ValueError("kernel_projection_invalid")
    hook = crash_hook or (lambda _point: None)
    projected = deepcopy(state)
    hook("before_projection_replacement")
    if command == "plan_checkpoint":
        identity = event.get("checkpoint_identity")
        if not isinstance(identity, str) or len(identity) != 64:
            raise ValueError("plan_checkpoint_identity_invalid")
        checkpoints = projected.setdefault("plan_checkpoints", [])
        if identity in checkpoints:
            raise ValueError("plan_checkpoint_already_published")
        hook("before_plan_checkpoint_publication")
        checkpoints.append(identity)
        projected["phase"] = "plan_complete"
        hook("after_plan_checkpoint_publication")
    elif command == "register_external_call":
        call_id = event.get("external_call_id")
        if not isinstance(call_id, str) or not call_id:
            raise ValueError("external_call_id_invalid")
        calls = projected.setdefault("external_calls", [])
        if call_id in calls:
            raise ValueError("external_call_already_registered")
        hook("before_external_call_registration")
        calls.append(call_id)
        hook("after_external_call_registration")
    elif command == "complete_program":
        if projected.get("completed") is True:
            raise ValueError("global_completion_already_recorded")
        required = event.get("required_plan_checkpoints")
        published = projected.get("plan_checkpoints")
        if (
            not isinstance(required, list)
            or not set(required).issubset(set(published or []))
            or event.get("integration_gate_passed") is not True
            or projected.get("integration_gate_passed") is not True
        ):
            raise ValueError("global_completion_prerequisites_missing")
        hook("before_global_completion")
        projected["completed"] = True
        projected["phase"] = "completed"
        hook("after_global_completion")
    elif command in _KERNEL_PHASES:
        projected["phase"] = _KERNEL_PHASES[command]
    else:
        raise ValueError(f"kernel_command_unknown:{command}")
    hook("after_projection_replacement")
    return projected


def validate_task_status_change(
    state: dict,
    task_id: str | None,
    payload: dict,
    attempt_id: str | None,
) -> None:
    tasks = state.get("tasks")
    if not isinstance(tasks, dict) or task_id not in tasks:
        raise ValueError("unknown task")
    task = tasks[task_id]
    current = task.get("status")
    target = payload.get("to")
    if payload.get("from") != current:
        raise ValueError("task transition from mismatch")
    if target not in TASK_TRANSITIONS.get(str(current), set()):
        raise ValueError("invalid task transition")
    waiting = target in {"waiting_external", "waiting_user"}
    if target == "blocked":
        if not isinstance(payload.get("wait_reason"), str) or not payload["wait_reason"]:
            raise ValueError("invalid task blocked payload")
        if any(key in payload for key in ("resume_phase", "active_attempt_id")):
            raise ValueError("invalid task blocked payload")
        return
    if waiting:
        reason = payload.get("wait_reason")
        phase = payload.get("resume_phase")
        active = payload.get("active_attempt_id")
        if (
            not isinstance(reason, str)
            or not reason
            or phase not in RETRY_PHASE_STATES
            or (active is not None and (not isinstance(active, str) or not active))
            or active != attempt_id
        ):
            raise ValueError("invalid task wait payload")
        expected = RETRY_PHASE_STATES[str(phase)]
        if active is not None and current != expected:
            raise ValueError("invalid task wait payload")
        return
    if current in {"waiting_external", "waiting_user"}:
        if target == "failed":
            if any(
                key in payload
                for key in ("wait_reason", "resume_phase", "active_attempt_id")
            ):
                raise ValueError("invalid task transition payload")
            return
        phase = task.get("resume_phase")
        persisted_active = task.get("active_attempt_id")
        active = payload.get("active_attempt_id")
        if (
            phase not in RETRY_PHASE_STATES
            or payload.get("resume_phase") != phase
            or attempt_id != active
            or (
                persisted_active is not None
                and active != persisted_active
            )
        ):
            raise ValueError("task resume phase mismatch")
        expected = RETRY_PHASE_STATES[str(phase)]
        allowed_targets = {expected, "ready"} if active is None else {expected}
        if target not in allowed_targets:
            raise ValueError("task resume phase mismatch")
        return
    if any(key in payload for key in ("wait_reason", "resume_phase", "active_attempt_id")):
        raise ValueError("invalid task transition payload")


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


def _valid_hex(value: object, length: int) -> bool:
    return (
        isinstance(value, str)
        and len(value) == length
        and all(character in "0123456789abcdef" for character in value)
    )


def valid_verified_checkpoint_payload(payload: object) -> bool:
    return (
        isinstance(payload, dict)
        and all(_valid_hex(payload.get(field), 40) for field in ("predecessor", "commit", "tree"))
        and all(
            _valid_hex(payload.get(field), 64)
            for field in ("contract_sha256", "acceptance_sha256", "review_sha256")
        )
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
    packet_sha256_by_task = {
        str(entry["task_id"]): str(entry["sha256"])
        for entry in manifest.get("task_packets", [])
        if isinstance(entry, dict)
        and isinstance(entry.get("task_id"), str)
        and isinstance(entry.get("sha256"), str)
    }
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
            "task_packet_sha256": packet_sha256_by_task.get(str(task["id"])),
            "wait_reason": None,
            "resume_phase": None,
            "active_attempt_id": None,
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
        "source_head": (manifest.get("source_git") or {}).get("head"),
        "tasks": tasks,
        "attempts": [],
        "verdicts": [],
        "active_blockers": [],
        "blocker_history": [],
        "candidate_checkpoints": [],
        "verified_checkpoints": [],
        "checkpoint_head": None,
        "decisions": [],
        "notifications": [],
        "backlog": [],
        "repair_roots": {},
        "selected_repairs": {},
        "wait_reason": None,
        "attempt_budget": {"limit": int(manifest.get("attempt_budget_limit", 40)), "used": 0},
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
        validate_task_status_change(
            state, task_id, payload, event.get("attempt_id")
        )
        task = state["tasks"][task_id]
        task["status"] = payload["to"]
        if payload["to"] in {"waiting_external", "waiting_user"}:
            task["wait_reason"] = payload["wait_reason"]
            task["resume_phase"] = payload["resume_phase"]
            task["active_attempt_id"] = payload.get("active_attempt_id")
        elif payload["to"] == "blocked":
            task["wait_reason"] = payload["wait_reason"]
            task["resume_phase"] = None
            task["active_attempt_id"] = None
        elif payload["from"] in {"waiting_external", "waiting_user"}:
            task["wait_reason"] = None
            task["resume_phase"] = None
            task["active_attempt_id"] = None
        state["current_task"] = (
            None
            if payload["to"] in {"completed", "blocked", "failed", "waiting_user", "waiting_external"}
            else task_id
        )
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
        task_id = event.get("task_id")
        if task_id in state["tasks"]:
            state["tasks"][task_id]["active_attempt_id"] = event.get("attempt_id")
    elif typ == "attempt.completed":
        attempt_id = event.get("attempt_id")
        if not valid_attempt_completion(state, event.get("task_id"), attempt_id, payload):
            raise ValueError("invalid attempt payload")
        matching = [item for item in state["attempts"] if item.get("attempt_id") == attempt_id]
        matching[0].update(payload)
        task_id = event.get("task_id")
        if (
            task_id in state["tasks"]
            and state["tasks"][task_id].get("active_attempt_id") == attempt_id
        ):
            state["tasks"][task_id]["active_attempt_id"] = None
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
        if not valid_verified_checkpoint_payload(payload):
            raise ValueError("invalid checkpoint payload")
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
        if payload.get("decision_kind") == "repair_root_updated":
            root = payload.get("root_cause_key")
            count = payload.get("repair_count")
            if (
                not isinstance(root, str)
                or not root
                or type(count) is not int
                or count not in {1, 2}
                or count < int(state["repair_roots"].get(root, 0))
            ):
                raise ValueError("invalid repair root decision")
            state["repair_roots"][root] = count
        elif payload.get("decision_kind") == "backlog_added":
            item = payload.get("backlog_item")
            if not isinstance(item, dict):
                raise ValueError("invalid backlog decision")
            if item not in state["backlog"]:
                state["backlog"].append(item)
        elif payload.get("decision_kind") == "selected_repair_recorded":
            task_id = payload.get("task_id")
            ref = payload.get("selected_repair_ref")
            if (
                task_id != event.get("task_id")
                or task_id not in state["tasks"]
                or not isinstance(ref, dict)
                or payload.get("repair_slot") != payload.get("repair_count")
            ):
                raise ValueError("invalid selected repair decision")
            state["selected_repairs"][task_id] = deepcopy(payload)
        elif payload.get("decision_kind") == "selected_repair_resolved":
            task_id = payload.get("task_id")
            selected = state["selected_repairs"].get(str(task_id))
            if (
                task_id != event.get("task_id")
                or selected is None
                or selected.get("selected_repair_ref")
                != payload.get("selected_repair_ref")
            ):
                raise ValueError("invalid selected repair resolution")
            state["selected_repairs"].pop(str(task_id), None)
    elif typ == "notification.requested":
        state["notifications"].append(payload)
    elif typ == "runtime.upgraded":
        target = validate_runtime_upgrade(
            RuntimeIdentity.from_mapping(state["runtime"]),
            payload,
            checkpoint_head=state["checkpoint_head"],
            verified_checkpoints=state["verified_checkpoints"],
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
