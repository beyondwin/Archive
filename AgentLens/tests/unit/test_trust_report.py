from __future__ import annotations

from agentlens.evaluator.agentrunway_v2 import project_events
from agentlens.evaluator.trust import build_trust_report


def _event(event_type: str, payload: dict, **overrides: object) -> dict:
    event = {
        "schema": "agentlens.event.v2",
        "event_id": "evt_000001",
        "run_id": "run_20260521_000000_agent",
        "event_type": event_type,
        "producer": {"name": "agentrunway", "version": "0.1.0"},
        "occurred_at": "2026-05-21T00:00:00Z",
        "sequence": 1,
        "phase": "run",
        "outcome": "success",
        "severity": "info",
        "trust_impact": "supports_success",
        "summary": event_type,
        "payload": payload,
    }
    event.update(overrides)
    return event


def test_trust_report_trusts_success_with_verification_and_artifacts() -> None:
    projection = project_events(
        [
            _event("agentrunway.run_started", {"run_id": "ar-001"}),
            _event(
                "agentrunway.artifacts_ready",
                {
                    "run_id": "ar-001",
                    "contract_path": "contract.json",
                    "artifact_graph_path": "artifact_graph.json",
                    "coverage_path": "coverage.json",
                },
            ),
            _event(
                "agentrunway.verification_result",
                {"run_id": "ar-001", "task_id": "task_001", "status": "passed"},
                phase="verification",
            ),
            _event(
                "agentrunway.run_finished",
                {"run_id": "ar-001", "status": "finished"},
                phase="finish",
            ),
        ]
    )

    report = build_trust_report(projection, claimed_outcome="success")

    assert report["trust_verdict"] == "trusted"
    assert report["evidence_strength"] == "strong"
    assert report["missing_evidence"] == []


def test_trust_report_flags_false_success_without_verification() -> None:
    projection = project_events(
        [
            _event("agentrunway.run_started", {"run_id": "ar-002"}),
            _event(
                "agentrunway.run_finished",
                {"run_id": "ar-002", "status": "finished"},
                phase="finish",
            ),
        ]
    )

    report = build_trust_report(projection, claimed_outcome="success")

    assert report["trust_verdict"] == "untrusted"
    assert report["evidence_strength"] == "insufficient"
    assert any(item["code"] == "missing_verification_pass" for item in report["missing_evidence"])
