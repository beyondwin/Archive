"""Legacy AgentRunway v2 projection artifacts."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from agentlens.constants import SCHEMA_AGENTRUNWAY_PROJECTION_V1

from .agentrunway_events import project_agentrunway_events


def _event_key(event: Mapping[str, Any]) -> tuple[str, str]:
    return (str(event.get("event_type") or event.get("type") or ""), str(event.get("sequence") or ""))


def _projection_issues(events: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for event in events:
        key = _event_key(event)
        if key[0].startswith("kws-cpe.") or key[0].startswith("kws-cme.") or key[0].startswith("kws.orchestrator."):
            issues.append({"code": "legacy_namespace_rejected", "event_type": key[0]})
        if key[1] and key in seen:
            issues.append({"code": "duplicate_event_sequence", "event_type": key[0], "sequence": key[1]})
        seen.add(key)
    return issues


def project_events(events: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    event_list = [event for event in events if isinstance(event, Mapping)]
    base = project_agentrunway_events(event_list)
    run_id = None
    for event in event_list:
        if isinstance(event.get("run_id"), str):
            run_id = str(event["run_id"])
            break
        if isinstance(event.get("orchestrator_run_id"), str):
            run_id = str(event["orchestrator_run_id"])
            break
    return {
        "schema": SCHEMA_AGENTRUNWAY_PROJECTION_V1,
        "run_id": run_id or "",
        "agentrunway_run_id": base.get("run_id"),
        "status": base.get("status", "not_started"),
        "event_count": int(base.get("event_count") or 0),
        "timeline": base.get("timeline") or [],
        "tasks": base.get("tasks") or {},
        "artifacts": base.get("artifacts") or {
            "contract": "missing",
            "artifact_graph": "missing",
            "coverage": "missing",
        },
        "coverage": base.get("coverage") or {
            "covered": [],
            "partial": [],
            "blocked": [],
            "unreferenced": [],
        },
        "projection_issues": _projection_issues(event_list),
        "agentlens_emit_health": base.get("agentlens_emit_health") or {
            "last_status": "unknown",
            "statuses": {},
        },
        "payload_safety": base.get("payload_safety") or "ok",
    }


__all__ = ["project_events"]
