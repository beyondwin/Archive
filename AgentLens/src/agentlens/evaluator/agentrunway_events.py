"""Projection helpers for AgentRunway ``agentrunway.*`` events."""
from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any

AGENTRUNWAY_PREFIX = "agentrunway."
INTERNAL_EVENT_TYPES = frozenset({"agentrunway.resume_action"})
MAX_PAYLOAD_BYTES = 4096

_COVERAGE_KEYS = ("covered", "partial", "blocked", "unreferenced")


def _payload(event: Mapping[str, Any]) -> dict[str, Any]:
    payload = event.get("payload")
    return payload if isinstance(payload, dict) else {}


def _event_type(event: Mapping[str, Any]) -> str:
    type_ = event.get("type")
    return type_ if isinstance(type_, str) else ""


def _is_agentrunway_event(event: Mapping[str, Any]) -> bool:
    return _event_type(event).startswith(AGENTRUNWAY_PREFIX)


def _payload_size(event: Mapping[str, Any]) -> int:
    try:
        return len(json.dumps(_payload(event), sort_keys=True).encode("utf-8"))
    except (TypeError, ValueError):
        return MAX_PAYLOAD_BYTES + 1


def _append_unique(target: list[str], values: Any) -> None:
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        return
    for value in values:
        if isinstance(value, str) and value not in target:
            target.append(value)


def _task_record(tasks: dict[str, dict[str, Any]], task_id: str) -> dict[str, Any]:
    if task_id not in tasks:
        tasks[task_id] = {
            "status": "unknown",
            "implementer_attempts": 0,
            "review_attempts": 0,
            "verification_attempts": 0,
            "last_reason": None,
        }
    return tasks[task_id]


def _timeline_entry(
    event: Mapping[str, Any], payload: Mapping[str, Any]
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "ts": event.get("ts"),
        "type": _event_type(event),
    }
    for key in ("task_id", "status", "outcome", "reason", "summary"):
        value = payload.get(key)
        if value is not None:
            entry[key] = value
    return entry


def _empty_projection() -> dict[str, Any]:
    return {
        "producer": "agentrunway",
        "run_id": None,
        "status": "not_started",
        "event_count": 0,
        "timeline": [],
        "tasks": {},
        "gate_retries": [],
        "blocked_tasks": [],
        "merge": {"ready": False, "conflicts": []},
        "artifacts": {
            "contract": "missing",
            "artifact_graph": "missing",
            "coverage": "missing",
        },
        "coverage": {key: [] for key in _COVERAGE_KEYS},
        "agentlens_emit_health": {"last_status": "unknown", "statuses": {}},
        "payload_safety": "ok",
        "internal_actions": 0,
    }


def _update_artifacts(projection: dict[str, Any], payload: Mapping[str, Any]) -> None:
    artifacts = projection["artifacts"]
    if any(payload.get(key) for key in ("contract_path", "contract_ref", "contract")):
        artifacts["contract"] = "present"
    if any(
        payload.get(key)
        for key in ("artifact_graph_path", "artifact_graph_ref", "artifact_graph")
    ):
        artifacts["artifact_graph"] = "present"
    if payload.get("coverage_path") or isinstance(payload.get("coverage"), dict):
        artifacts["coverage"] = "present"


def _update_coverage(projection: dict[str, Any], payload: Mapping[str, Any]) -> None:
    coverage = payload.get("coverage")
    if isinstance(coverage, dict):
        for key in _COVERAGE_KEYS:
            _append_unique(projection["coverage"][key], coverage.get(key))
    for key in _COVERAGE_KEYS:
        _append_unique(projection["coverage"][key], payload.get(f"{key}_spec_refs"))


def _update_agentlens_health(
    projection: dict[str, Any], payload: Mapping[str, Any]
) -> None:
    status = payload.get("agentlens_status")
    if not isinstance(status, str):
        return
    health = projection["agentlens_emit_health"]
    health["last_status"] = status
    statuses = health["statuses"]
    statuses[status] = statuses.get(status, 0) + 1


def _mark_task_event(
    projection: dict[str, Any],
    event_name: str,
    payload: Mapping[str, Any],
) -> None:
    task_id = payload.get("task_id")
    if not isinstance(task_id, str) or not task_id:
        return

    task = _task_record(projection["tasks"], task_id)
    status = payload.get("status")
    reason = payload.get("reason")
    if isinstance(status, str):
        task["status"] = status
    if isinstance(reason, str):
        task["last_reason"] = reason

    if event_name == "worker_result":
        task["implementer_attempts"] += 1
    elif event_name == "review_result":
        task["review_attempts"] += 1
    elif event_name == "verification_result":
        task["verification_attempts"] += 1
    elif event_name == "run_blocked":
        task["status"] = "blocked"


def project_agentrunway_events(events: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Project AgentRunway events into a user-facing timeline summary.

    ``agentrunway.resume_action`` is internal recovery bookkeeping: it is
    counted under ``internal_actions`` but intentionally omitted from the
    user-facing timeline.
    """
    projection = _empty_projection()
    agentrunway_events = [
        event
        for event in events
        if isinstance(event, Mapping) and _is_agentrunway_event(event)
    ]
    projection["event_count"] = len(agentrunway_events)

    for event in sorted(
        agentrunway_events,
        key=lambda item: (
            str(item.get("ts", "")),
            str(item.get("run_id", "")),
            str(item.get("event_id", "")),
        ),
    ):
        type_ = _event_type(event)
        payload = _payload(event)
        event_name = type_.removeprefix(AGENTRUNWAY_PREFIX)

        run_id = payload.get("run_id") or payload.get("agentrunway_run_id")
        if isinstance(run_id, str) and run_id and projection["run_id"] is None:
            projection["run_id"] = run_id

        if _payload_size(event) > MAX_PAYLOAD_BYTES:
            projection["payload_safety"] = "oversized"

        _update_artifacts(projection, payload)
        _update_coverage(projection, payload)
        _update_agentlens_health(projection, payload)

        if type_ in INTERNAL_EVENT_TYPES:
            projection["internal_actions"] += 1
            continue

        projection["timeline"].append(_timeline_entry(event, payload))
        _mark_task_event(projection, event_name, payload)

        if event_name == "run_started":
            projection["status"] = "running"
        elif event_name == "run_finished":
            projection["status"] = str(payload.get("status") or "finished")
        elif event_name == "run_blocked":
            projection["status"] = "blocked"
            task_id = payload.get("task_id")
            projection["blocked_tasks"].append(
                {
                    "task_id": task_id if isinstance(task_id, str) else None,
                    "reason": str(payload.get("reason") or "blocked"),
                }
            )
        elif event_name == "gate_retry":
            projection["gate_retries"].append(
                {
                    "task_id": payload.get("task_id"),
                    "attempt": payload.get("attempt"),
                    "reason": str(payload.get("reason") or "retry"),
                }
            )
        elif event_name == "merge_ready":
            projection["merge"]["ready"] = True
        elif event_name == "merge_conflict":
            projection["merge"]["ready"] = False
            projection["merge"]["conflicts"].append(
                {
                    "task_id": payload.get("task_id"),
                    "reason": str(payload.get("reason") or "merge conflict"),
                }
            )

    return projection


def _run_looks_agentrunway(run: Mapping[str, Any] | None) -> bool:
    if not isinstance(run, Mapping):
        return False
    agent = run.get("agent")
    if not isinstance(agent, Mapping):
        return False
    values = [
        agent.get("name"),
        agent.get("mode"),
        agent.get("label"),
        run.get("run_kind"),
    ]
    return any(
        isinstance(value, str) and "agentrunway" in value.lower()
        for value in values
    )


def _coverage_strength(projection: Mapping[str, Any]) -> str:
    if projection.get("event_count") == 0:
        return "none"
    if projection.get("payload_safety") == "oversized":
        return "partial"
    artifacts = projection.get("artifacts")
    contract_present = (
        isinstance(artifacts, Mapping) and artifacts.get("contract") == "present"
    )
    has_terminal = projection.get("status") in {"finished", "blocked"}
    has_gate = any(
        item.get("type")
        in {"agentrunway.review_result", "agentrunway.verification_result"}
        for item in projection.get("timeline", [])
        if isinstance(item, Mapping)
    )
    if contract_present and has_terminal and has_gate:
        return "strong"
    if has_terminal or has_gate:
        return "partial"
    return "weak"


def build_evidence_coverage(
    events: Iterable[Mapping[str, Any]],
    *,
    run: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the additive ``eval.json.evidence_coverage`` block."""
    projection = project_agentrunway_events(events)
    event_count = int(projection["event_count"])
    if event_count:
        observability = "present"
    elif _run_looks_agentrunway(run):
        observability = "missing"
    else:
        observability = "not_applicable"

    return {
        "producer": "agentrunway",
        "observability": observability,
        "event_count": event_count,
        "timeline_event_count": len(projection["timeline"]),
        "internal_actions": projection["internal_actions"],
        "payload_safety": projection["payload_safety"],
        "strength": _coverage_strength(projection),
        "artifacts": projection["artifacts"],
        "coverage": projection["coverage"],
        "gates": {
            "retry_count": len(projection["gate_retries"]),
            "review_results": sum(
                1
                for item in projection["timeline"]
                if item.get("type") == "agentrunway.review_result"
            ),
            "verification_results": sum(
                1
                for item in projection["timeline"]
                if item.get("type") == "agentrunway.verification_result"
            ),
        },
        "projection": projection,
    }


__all__ = [
    "AGENTRUNWAY_PREFIX",
    "INTERNAL_EVENT_TYPES",
    "MAX_PAYLOAD_BYTES",
    "build_evidence_coverage",
    "project_agentrunway_events",
]
