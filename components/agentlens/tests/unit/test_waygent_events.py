"""Waygent-native event projection and coverage tests."""
from __future__ import annotations

from agentlens.evaluator.waygent_events import build_evidence_coverage
from agentlens.evaluator.waygent_projection import project_events


def test_waygent_events_project_to_waygent_projection() -> None:
    projection = project_events(
        [
            {
                "event_type": "platform.run_started",
                "payload": {"run_id": "run_waygent"},
                "producer": {"name": "waygent"},
            },
            {
                "event_type": "runway.verification_result",
                "payload": {"task_id": "task_verify", "status": "passed"},
                "producer": {"name": "waygent"},
            },
            {
                "event_type": "lens.trust_report_updated",
                "payload": {"trust_status": "trusted"},
                "producer": {"name": "waygent"},
            },
        ]
    )

    assert projection["schema"] == "agentlens.waygent_projection.v1"
    assert projection["run_id"] == "run_waygent"
    assert projection["waygent_run_id"] == "run_waygent"
    assert projection["producer"] == "waygent"
    assert projection["status"] == "observed"
    assert projection["event_count"] == 3
    assert [item["type"] for item in projection["timeline"]] == [
        "platform.run_started",
        "runway.verification_result",
        "lens.trust_report_updated",
    ]
    assert projection["tasks"] == [
        {"task_id": "task_verify", "events": ["runway.verification_result"]}
    ]


def test_waygent_empty_projection_has_stable_shape() -> None:
    projection = project_events([])

    assert projection["schema"] == "agentlens.waygent_projection.v1"
    assert projection["run_id"] is None
    assert projection["waygent_run_id"] is None
    assert projection["producer"] == "waygent"
    assert projection["status"] == "empty"
    assert projection["event_count"] == 0
    assert projection["timeline"] == []
    assert projection["tasks"] == []


def test_waygent_evidence_coverage_counts_active_event_families() -> None:
    coverage = build_evidence_coverage(
        [
            {"event_type": "platform.run_started", "payload": {}},
            {"event_type": "runway.verification_result", "payload": {}},
            {"event_type": "kernel.execution_result", "payload": {}},
            {"event_type": "lens.trust_report_updated", "payload": {}},
        ],
        run={"agent": {"name": "waygent"}},
    )

    assert coverage["producer"] == "waygent"
    assert coverage["event_count"] == 4
    assert coverage["coverage"]["platform"] == 1
    assert coverage["coverage"]["runway"] == 1
    assert coverage["coverage"]["kernel"] == 1
    assert coverage["coverage"]["lens"] == 1
    assert coverage["run_agent"] == {"name": "waygent"}
