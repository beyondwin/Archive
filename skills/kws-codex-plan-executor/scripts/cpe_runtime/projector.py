from __future__ import annotations

from copy import deepcopy

from .events import READ_COMPAT_EVENT_TYPES


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
    "blocked": {"failed"},
    "failed": set(),
}
RETRY_PHASE_STATES = {
    "implementation": "implementing",
    "repair": "repairing",
    "acceptance": "verifying",
    "task_review": "reviewing",
    "verification": "verifying",
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
        "worktree_revision": 0,
        "worktree_patch_sha256": None,
        "tasks": tasks,
        "attempts": [],
        "verdicts": [],
        "active_blockers": [],
        "blocker_history": [],
        "retry_queue": [],
        # Deprecated projection alias retained until all v3 consumers use
        # active_blockers directly.
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
    if event.get("type") not in READ_COMPAT_EVENT_TYPES:
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
    elif typ == "task.retry_scheduled":
        task_id = event.get("task_id")
        state["retry_queue"].append({"task_id": task_id, **payload})
        if task_id in state["tasks"] and state["tasks"][task_id]["status"] == "blocked":
            state["tasks"][task_id]["status"] = RETRY_PHASE_STATES[payload["phase"]]
            state["current_task"] = task_id
    elif typ in {"attempt.recorded", "attempt.started"}:
        record = {"task_id": event.get("task_id"), "attempt_id": event.get("attempt_id"), **payload}
        if typ == "attempt.started":
            record.setdefault("status", "started")
        state["attempts"].append(record)
        if typ == "attempt.recorded":
            for key in state["usage_totals"]:
                state["usage_totals"][key] += int((payload.get("usage") or {}).get(key, 0) or 0)
    elif typ == "attempt.completed":
        attempt_id = event.get("attempt_id")
        matching = [item for item in state["attempts"] if item.get("attempt_id") == attempt_id]
        if len(matching) != 1:
            raise ValueError("unknown attempt")
        matching[0].update(payload)
        for key in state["usage_totals"]:
            state["usage_totals"][key] += int((payload.get("usage") or {}).get(key, 0) or 0)
    elif typ == "verdict.recorded":
        state["verdicts"].append(
            {"task_id": event.get("task_id"), "attempt_id": event.get("attempt_id"), **payload}
        )
    elif typ == "worktree.revision_recorded":
        state["worktree_revision"] = payload["to"]
        state["worktree_patch_sha256"] = payload["patch_sha256"]
    elif typ == "blocker.opened":
        blocker_id = payload["blocker_id"]
        if any(item.get("blocker_id") == blocker_id for item in state["blocker_history"]):
            raise ValueError("duplicate blocker")
        blocker = {"task_id": event.get("task_id"), **payload, "status": "open"}
        state["active_blockers"].append(blocker)
        state["blocker_history"].append(deepcopy(blocker))
        state["blockers"] = deepcopy(state["active_blockers"])
    elif typ == "blocker.updated":
        blocker_id = payload["blocker_id"]
        active = {item.get("blocker_id"): item for item in state["active_blockers"]}
        if blocker_id not in active:
            raise ValueError("unknown blocker")
        active[blocker_id].update(payload)
        history = [item for item in state["blocker_history"] if item.get("blocker_id") == blocker_id]
        if len(history) != 1:
            raise ValueError("unknown blocker")
        history[0].update(payload)
        state["blockers"] = deepcopy(state["active_blockers"])
    elif typ == "blocker.resolved":
        blocker_id = payload["blocker_id"]
        active = {item.get("blocker_id"): item for item in state["active_blockers"]}
        if blocker_id not in active:
            raise ValueError("unknown blocker")
        state["active_blockers"] = [
            item for item in state["active_blockers"] if item.get("blocker_id") != blocker_id
        ]
        history = [item for item in state["blocker_history"] if item.get("blocker_id") == blocker_id]
        if len(history) != 1:
            raise ValueError("unknown blocker")
        history[0].update(payload)
        history[0]["status"] = "resolved"
        state["blockers"] = deepcopy(state["active_blockers"])
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
