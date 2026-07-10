from __future__ import annotations

from copy import deepcopy

from .events import EVENT_TYPES


RUN_TRANSITIONS = {
    "created": {"ready", "blocked", "failed"},
    "ready": {"running", "blocked", "failed"},
    "running": {"completed", "blocked", "failed"},
    "blocked": {"ready", "failed"},
    "failed": set(),
    "completed": set(),
}
TASK_TRANSITIONS = {
    "pending": {"ready", "blocked", "failed"},
    "ready": {"scouting", "implementing", "blocked", "failed"},
    "scouting": {"implementing", "blocked", "failed"},
    "implementing": {"reviewing", "repairing", "blocked", "failed"},
    "reviewing": {"verifying", "repairing", "blocked", "failed"},
    "verifying": {"completed", "repairing", "blocked", "failed"},
    "repairing": {"reviewing", "verifying", "blocked", "failed"},
    "completed": set(),
    "blocked": {"ready", "failed"},
    "failed": set(),
}


def initial_state(manifest: dict) -> dict:
    tasks = {
        str(task["id"]): {
            "id": str(task["id"]),
            "title": str(task.get("title", task["id"])),
            "status": "pending",
            "dependencies": list(task.get("dependencies") or []),
            "file_claims": list(task.get("file_claims") or []),
            "spec_refs": list(task.get("spec_refs") or []),
            "acceptance_command": task.get("acceptance_command"),
        }
        for task in manifest.get("task_graph", [])
    }
    return {
        "schema_version": "3",
        "run_id": manifest.get("run_id"),
        "lifecycle": "created",
        "current_task": None,
        "tasks": tasks,
        "attempts": [],
        "blockers": [],
        "context_health": None,
        "completion_audit": None,
        "usage_totals": {
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "output_tokens": 0,
            "reasoning_output_tokens": 0,
        },
        "artifact_index": [],
        "repairs": [],
        "last_event": {"seq": 0, "hash": None},
    }


def apply_event(state: dict, event: dict) -> dict:
    if event.get("type") not in EVENT_TYPES:
        raise ValueError("unknown event type")
    state = deepcopy(state)
    state["last_event"] = {"seq": event["seq"], "hash": event["hash"]}
    payload = deepcopy(event.get("payload", {}))
    typ = event["type"]
    if typ == "run.status_changed":
        state["lifecycle"] = payload["to"]
    elif typ == "task.status_changed":
        task_id = event.get("task_id")
        if task_id not in state["tasks"]:
            raise ValueError("unknown task")
        state["tasks"][task_id]["status"] = payload["to"]
        state["current_task"] = None if payload["to"] in {"completed", "blocked", "failed"} else task_id
        if payload["to"] == "blocked":
            state["blockers"].append({"task_id": task_id, **payload})
    elif typ == "attempt.recorded":
        record = {"task_id": event.get("task_id"), "attempt_id": event.get("attempt_id"), **payload}
        state["attempts"].append(record)
        for key in state["usage_totals"]:
            state["usage_totals"][key] += int((payload.get("usage") or {}).get(key, 0) or 0)
    elif typ == "evidence.attached":
        state["artifact_index"].append({"task_id": event.get("task_id"), "attempt_id": event.get("attempt_id"), **payload})
    elif typ == "context.updated":
        state["context_health"] = payload
    elif typ == "completion.recorded":
        state["completion_audit"] = payload
    elif typ == "repair.applied":
        state["repairs"].append(payload)
    return state


def project(manifest: dict, events: list[dict]) -> dict:
    state = initial_state(manifest)
    for event in events:
        state = apply_event(state, event)
    return state
