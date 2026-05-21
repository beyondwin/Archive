"""Waygent event read compatibility tests."""
from __future__ import annotations

from agentlens.evaluator.agentrunway_v2 import project_events


def test_waygent_verification_event_namespace_is_accepted() -> None:
    projection = project_events(
        [
            {
                "schema": "agentlens.event.v3",
                "event_id": "event_run_waygent_1",
                "agentlens_run_id": "lens_run_waygent",
                "orchestrator_run_id": "run_waygent",
                "producer": {
                    "name": "waygent",
                    "kind": "orchestrator",
                    "version": "0.1.0",
                },
                "event_type": "runway.verification_result",
                "occurred_at": "2026-05-21T00:00:00Z",
                "sequence": 1,
                "phase": "verify",
                "outcome": "success",
                "severity": "info",
                "trust_impact": "supports_success",
                "summary": "Verification passed with kernel evidence.",
                "payload": {"checkpoint_ref": "checkpoint_task_a"},
            }
        ]
    )

    assert projection["run_id"] == "run_waygent"
    assert projection["projection_issues"] == []
