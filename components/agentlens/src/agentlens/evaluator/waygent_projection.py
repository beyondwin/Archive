"""Waygent projection artifacts."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .waygent_events import is_waygent_event

SCHEMA_WAYGENT_PROJECTION_V1 = "agentlens.waygent_projection.v1"
_COVERAGE_KEYS = ("covered", "partial", "blocked", "unreferenced")
_ACTIVE_PREFIXES = ("platform.", "runway.", "kernel.", "lens.")


def _payload(event: Mapping[str, Any]) -> Mapping[str, Any]:
    payload = event.get("payload")
    return payload if isinstance(payload, Mapping) else {}


def _event_type(event: Mapping[str, Any]) -> str:
    event_type = event.get("event_type") or event.get("type")
    return event_type if isinstance(event_type, str) else ""


def _candidate_run_id(event: Mapping[str, Any], payload: Mapping[str, Any]) -> str | None:
    for value in (
        payload.get("run_id"),
        event.get("run_id"),
        event.get("waygent_run_id"),
        event.get("orchestrator_run_id"),
    ):
        if isinstance(value, str) and value:
            return value
    return None


def _append_unique(target: list[str], values: Any) -> None:
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        return
    for value in values:
        if isinstance(value, str) and value not in target:
            target.append(value)


def _payload_size(event: Mapping[str, Any]) -> int:
    import json

    try:
        return len(json.dumps(_payload(event), sort_keys=True).encode("utf-8"))
    except (TypeError, ValueError):
        return 4097


def _projection_issues(events: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for event in events:
        event_type = _event_type(event)
        sequence = str(event.get("sequence") or "")
        if event_type and not event_type.startswith(_ACTIVE_PREFIXES):
            issues.append({"code": "inactive_namespace_rejected", "event_type": event_type})
        key = (event_type, sequence)
        if sequence and key in seen:
            issues.append({"code": "duplicate_event_sequence", "event_type": event_type, "sequence": sequence})
        seen.add(key)
    return issues


def project_events(events: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    all_events = [event for event in events if isinstance(event, Mapping)]
    event_list = [event for event in all_events if is_waygent_event(event)]
    run_id = None
    timeline: list[dict[str, Any]] = []
    tasks: dict[str, dict[str, Any]] = {}
    artifacts = {"contract": "missing", "artifact_graph": "missing", "coverage": "missing"}
    coverage: dict[str, list[str]] = {key: [] for key in _COVERAGE_KEYS}
    emit_health = {"last_status": "unknown", "statuses": {}}
    payload_safety = "ok"
    status = "observed" if event_list else "empty"

    for index, event in enumerate(event_list, start=1):
        payload = _payload(event)
        if run_id is None:
            run_id = _candidate_run_id(event, payload)

        event_type = _event_type(event)
        entry: dict[str, Any] = {
            "sequence": event.get("sequence", index),
            "type": event_type,
            "summary": event.get("summary", ""),
        }
        for key in ("task_id", "status", "outcome", "reason"):
            value = payload.get(key)
            if value is not None:
                entry[key] = value
        timeline.append(entry)

        task_id = payload.get("task_id")
        if isinstance(task_id, str) and task_id:
            task = tasks.setdefault(task_id, {"task_id": task_id, "events": []})
            task["events"].append(event_type)

        if any(payload.get(key) for key in ("contract_path", "contract_ref", "contract")):
            artifacts["contract"] = "present"
        if any(payload.get(key) for key in ("artifact_graph_path", "artifact_graph_ref", "artifact_graph")):
            artifacts["artifact_graph"] = "present"
        if payload.get("coverage_path") or isinstance(payload.get("coverage"), Mapping):
            artifacts["coverage"] = "present"
        payload_coverage = payload.get("coverage")
        if isinstance(payload_coverage, Mapping):
            for key in _COVERAGE_KEYS:
                _append_unique(coverage[key], payload_coverage.get(key))
        for key in _COVERAGE_KEYS:
            _append_unique(coverage[key], payload.get(f"{key}_spec_refs"))

        agentlens_status = payload.get("agentlens_status")
        if isinstance(agentlens_status, str):
            emit_health["last_status"] = agentlens_status
            statuses = emit_health["statuses"]
            statuses[agentlens_status] = statuses.get(agentlens_status, 0) + 1
        if _payload_size(event) > 4096:
            payload_safety = "oversized"
        if event_type.endswith("run_finished"):
            status = str(payload.get("status") or "finished")
        elif event_type.endswith("run_blocked"):
            status = "blocked"

    return {
        "schema": SCHEMA_WAYGENT_PROJECTION_V1,
        "run_id": run_id,
        "waygent_run_id": run_id,
        "producer": "waygent",
        "status": status,
        "event_count": len(event_list),
        "timeline": timeline,
        "tasks": list(tasks.values()),
        "artifacts": artifacts,
        "coverage": coverage,
        "projection_issues": _projection_issues(all_events),
        "agentlens_emit_health": emit_health,
        "payload_safety": payload_safety,
    }


__all__ = ["SCHEMA_WAYGENT_PROJECTION_V1", "project_events"]
