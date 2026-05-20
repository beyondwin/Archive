from __future__ import annotations

from pathlib import Path

from agentrunway.db import AgentRunwayDb
from agentrunway.decision_events import record_candidate_ranked, record_quality_decision
from agentrunway.events import EventJournal


def test_record_quality_decision_writes_bounded_event(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    db = AgentRunwayDb.open(run_dir / "state.sqlite")
    journal = EventJournal(db=db, run_dir=run_dir)

    event = record_quality_decision(
        journal,
        run_id="run_001",
        task_id="task_001",
        decision="retry",
        reason="verification_failed",
        outcome="partial",
        diagnosis_status="needs_resume",
    )

    assert event.event_type == "agentrunway.quality_decision"
    assert event.payload["decision"] == "retry"
    assert event.payload["reason"] == "verification_failed"
    assert event.payload["diagnosis_status"] == "needs_resume"


def test_record_candidate_ranked_writes_scores(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    db = AgentRunwayDb.open(run_dir / "state.sqlite")
    journal = EventJournal(db=db, run_dir=run_dir)

    event = record_candidate_ranked(
        journal,
        run_id="run_001",
        task_id="task_001",
        selected_candidate_id=7,
        scores=[{"candidate_id": 7, "rank": 1, "score": 96, "reasons": ["verifier_passed"]}],
    )

    assert event.event_type == "agentrunway.candidate_ranked"
    assert event.payload["selected_candidate_id"] == 7
    assert event.payload["scores"][0]["reasons"] == ["verifier_passed"]
