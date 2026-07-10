from __future__ import annotations

RUN_TRANSITIONS = {"created": {"ready", "blocked", "failed"}, "ready": {"running", "blocked", "failed"}, "running": {"completed", "blocked", "failed"}, "blocked": {"ready", "failed"}, "failed": set(), "completed": set()}


def initial_state(manifest: dict) -> dict:
    return {"schema_version": "3", "run_id": manifest.get("run_id"), "lifecycle": "created", "current_task": None, "tasks": {}, "attempts": [], "blockers": [], "last_event": {"seq": 0, "hash": None}}


def apply_event(state: dict, event: dict) -> dict:
    state = {**state, "last_event": {"seq": event["seq"], "hash": event["hash"]}}
    payload = event.get("payload", {}); typ = event.get("type")
    if typ == "run.status_changed": state["lifecycle"] = payload["to"]
    elif typ == "task.status_changed": state.setdefault("tasks", {}).setdefault(event.get("task_id"), {})["status"] = payload["to"]
    elif typ == "attempt.recorded": state.setdefault("attempts", []).append(payload)
    elif typ == "evidence.attached": state.setdefault("artifact_index", []).append(payload)
    elif typ == "context.updated": state["context_health"] = payload
    elif typ == "completion.recorded": state["completion_audit"] = payload
    elif typ == "repair.applied": state.setdefault("repairs", []).append(payload)
    return state


def project(manifest: dict, events: list[dict]) -> dict:
    state = initial_state(manifest)
    for event in events: state = apply_event(state, event)
    return state
