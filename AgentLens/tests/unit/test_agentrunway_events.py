"""AgentRunway event projection and eval coverage tests."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agentlens.evaluator.agentrunway_events import (
    build_evidence_coverage,
    project_agentrunway_events,
)
from agentlens.evaluator.engine import evaluate
from agentlens.schema.validate import validate_doc


def _event(
    type_: str,
    payload: dict[str, Any] | None = None,
    *,
    ts: str = "2026-05-20T00:00:00Z",
) -> dict[str, Any]:
    return {
        "schema": "agentlens.event.v1",
        "event_id": "evt_" + "a" * 12,
        "run_id": "run_20260520_000000_agent",
        "ts": ts,
        "type": type_,
        "payload": payload or {},
    }


def test_projection_tracks_gate_retry_blocked_status_and_internal_resume_action() -> None:
    projection = project_agentrunway_events(
        [
            _event("run.started"),
            _event(
                "agentrunway.run_started",
                {
                    "run_id": "ar-001",
                    "agentlens_status": "active",
                    "coverage": {"covered": ["S1"], "blocked": ["S2"]},
                },
                ts="2026-05-20T00:00:00Z",
            ),
            _event(
                "agentrunway.contract_created",
                {"contract_path": "contract.json"},
                ts="2026-05-20T00:00:01Z",
            ),
            _event(
                "agentrunway.worker_result",
                {
                    "task_id": "task_1",
                    "attempt": 1,
                    "status": "completed",
                    "artifact_graph_path": "artifact_graph.json",
                },
                ts="2026-05-20T00:00:02Z",
            ),
            _event(
                "agentrunway.review_result",
                {
                    "task_id": "task_1",
                    "attempt": 1,
                    "status": "changes_requested",
                    "reason": "tighten tests",
                },
                ts="2026-05-20T00:00:03Z",
            ),
            _event(
                "agentrunway.gate_retry",
                {
                    "task_id": "task_1",
                    "attempt": 2,
                    "reason": "review requested changes",
                },
                ts="2026-05-20T00:00:04Z",
            ),
            _event(
                "agentrunway.verification_result",
                {
                    "task_id": "task_1",
                    "attempt": 2,
                    "status": "failed",
                    "reason": "pytest failed",
                },
                ts="2026-05-20T00:00:05Z",
            ),
            _event(
                "agentrunway.resume_action",
                {"task_id": "task_1", "action": "retry"},
                ts="2026-05-20T00:00:06Z",
            ),
            _event(
                "agentrunway.run_blocked",
                {
                    "task_id": "task_1",
                    "reason": "verification failed after retry budget",
                },
                ts="2026-05-20T00:00:07Z",
            ),
        ]
    )

    assert projection["producer"] == "agentrunway"
    assert projection["run_id"] == "ar-001"
    assert projection["status"] == "blocked"
    assert projection["internal_actions"] == 1
    assert "agentrunway.resume_action" not in {
        item["type"] for item in projection["timeline"]
    }
    assert projection["tasks"]["task_1"]["implementer_attempts"] == 1
    assert projection["tasks"]["task_1"]["review_attempts"] == 1
    assert projection["tasks"]["task_1"]["verification_attempts"] == 1
    assert projection["gate_retries"] == [
        {
            "task_id": "task_1",
            "attempt": 2,
            "reason": "review requested changes",
        }
    ]
    assert projection["blocked_tasks"] == [
        {
            "task_id": "task_1",
            "reason": "verification failed after retry budget",
        }
    ]
    assert projection["artifacts"]["contract"] == "present"
    assert projection["artifacts"]["artifact_graph"] == "present"
    assert projection["coverage"]["covered"] == ["S1"]
    assert projection["coverage"]["blocked"] == ["S2"]


def test_evidence_coverage_is_not_applicable_for_non_agentrunway_runs() -> None:
    coverage = build_evidence_coverage(
        [_event("example.task_finished"), _event("codex.tool_use")],
        run={"agent": {"name": "generic", "label": "example-orchestrator"}},
    )

    assert coverage["producer"] == "agentrunway"
    assert coverage["observability"] == "not_applicable"
    assert coverage["event_count"] == 0
    assert coverage["strength"] == "none"


def test_projection_tracks_quality_decisions_and_candidate_ranking() -> None:
    projection = project_agentrunway_events(
        [
            _event(
                "agentrunway.quality_decision",
                {
                    "run_id": "ar-001",
                    "task_id": "task_001",
                    "decision": "retry",
                    "reason": "verification_failed",
                    "diagnosis_status": "needs_resume",
                },
            ),
            _event(
                "agentrunway.candidate_ranked",
                {
                    "run_id": "ar-001",
                    "task_id": "task_001",
                    "selected_candidate_id": 7,
                    "scores": [{"candidate_id": 7, "rank": 1, "score": 96, "reasons": ["verifier_passed"]}],
                },
                ts="2026-05-20T00:00:01Z",
            ),
            _event(
                "agentrunway.conflict_redispatch_planned",
                {
                    "run_id": "ar-001",
                    "task_id": "task_001",
                    "candidate_id": 7,
                    "reason": "merge_conflict",
                },
                ts="2026-05-20T00:00:02Z",
            ),
        ]
    )

    assert projection["quality_decisions"] == [
        {
            "task_id": "task_001",
            "decision": "retry",
            "reason": "verification_failed",
            "diagnosis_status": "needs_resume",
        }
    ]
    assert projection["candidate_rankings"][0]["selected_candidate_id"] == 7
    assert projection["conflict_redispatch_plans"] == [
        {"task_id": "task_001", "candidate_id": 7, "reason": "merge_conflict"}
    ]


def test_evaluator_adds_agentrunway_evidence_coverage_and_keeps_schema_valid(
    tmp_path: Path,
) -> None:
    run_id = "run_20260520_000000_agent"
    run = {
        "schema": "agentlens.run.v1",
        "run_id": run_id,
        "workspace_id": "ws_0123456789abcdef",
        "started_at": "2026-05-20T00:00:00Z",
        "agent": {"name": "generic", "mode": "unknown", "label": "agentrunway"},
        "workspace": {
            "root_label": "<workspace>",
            "root_hash": "sha256:" + "1" * 64,
            "id_basis": "git",
        },
        "recording": {
            "mode": "minimal",
            "adapter": "agentlens_container",
            "has_transcript": False,
            "transcript_source": "none",
        },
    }
    final = {
        "schema": "agentlens.final.v1",
        "run_id": run_id,
        "ended_at": "2026-05-20T00:01:00Z",
        "agent_outcome": "success",
        "summary": "AgentRunway run completed.",
        "changed_files": [
            {"path_label": "AgentLens/src/x.py", "path_hash": "sha256:" + "2" * 64}
        ],
        "verification": [
            {
                "kind": "command",
                "command_hash": "sha256:" + "3" * 64,
                "status": "passed",
                "excerpt": "pytest passed",
            }
        ],
        "residual_risks": [],
    }
    events = [
        _event("run.started", ts="2026-05-20T00:00:00Z"),
        _event(
            "agentrunway.run_started",
            {"run_id": "ar-001", "coverage_path": "coverage.json"},
            ts="2026-05-20T00:00:01Z",
        ),
        _event(
            "agentrunway.contract_created",
            {"contract_path": "contract.json"},
            ts="2026-05-20T00:00:02Z",
        ),
        _event(
            "agentrunway.verification_result",
            {"task_id": "task_1", "status": "passed", "attempt": 1},
            ts="2026-05-20T00:00:03Z",
        ),
        _event(
            "agentrunway.merge_ready",
            {"task_id": "task_1"},
            ts="2026-05-20T00:00:04Z",
        ),
        _event(
            "agentrunway.run_finished",
            {"run_id": "ar-001", "status": "finished"},
            ts="2026-05-20T00:00:05Z",
        ),
    ]

    (tmp_path / "run.json").write_text(json.dumps(run), encoding="utf-8")
    (tmp_path / "final.json").write_text(json.dumps(final), encoding="utf-8")
    (tmp_path / "events.jsonl").write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )

    doc = evaluate(tmp_path)

    assert doc["evidence_coverage"]["observability"] == "present"
    assert doc["evidence_coverage"]["projection"]["run_id"] == "ar-001"
    assert doc["evidence_coverage"]["projection"]["status"] == "finished"
    validate_doc(doc, schema_name="eval")
