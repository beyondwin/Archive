"""Projection helpers for active Waygent events."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

WAYGENT_PREFIXES = ("platform.", "runway.", "kernel.", "lens.")


def _event_type(event: Mapping[str, Any]) -> str:
    event_type = event.get("event_type") or event.get("type")
    return event_type if isinstance(event_type, str) else ""


def is_waygent_event(event: Mapping[str, Any]) -> bool:
    return _event_type(event).startswith(WAYGENT_PREFIXES)


def build_evidence_coverage(
    events: Iterable[Mapping[str, Any]],
    *,
    run: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    event_list = [
        event
        for event in events
        if isinstance(event, Mapping) and is_waygent_event(event)
    ]
    coverage = {"platform": 0, "runway": 0, "kernel": 0, "lens": 0}
    for event in event_list:
        family = _event_type(event).split(".", 1)[0]
        if family in coverage:
            coverage[family] += 1

    run_agent: dict[str, Any] = {}
    if isinstance(run, Mapping):
        agent = run.get("agent")
        if isinstance(agent, Mapping):
            run_agent = dict(agent)
    is_waygent_run = any(
        isinstance(value, str) and "waygent" in value.lower()
        for value in (run_agent.get("name"), run_agent.get("label"), run_agent.get("mode"))
    )

    return {
        "producer": "waygent",
        "observability": "present" if event_list else "missing" if is_waygent_run else "not_applicable",
        "event_count": len(event_list),
        "timeline_event_count": len(event_list),
        "internal_actions": 0,
        "payload_safety": "ok",
        "strength": "strong" if event_list else "none",
        "artifacts": {"contract": "missing", "artifact_graph": "missing", "coverage": "missing"},
        "coverage": coverage,
        "gates": {
            "retry_count": 0,
            "review_results": sum(1 for event in event_list if _event_type(event) == "runway.review_result"),
            "verification_results": sum(1 for event in event_list if _event_type(event) == "runway.verification_result"),
        },
        "run_agent": run_agent,
    }


__all__ = ["WAYGENT_PREFIXES", "build_evidence_coverage", "is_waygent_event"]
