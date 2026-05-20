from __future__ import annotations

from typing import Any

from .events import EventJournal, EventRecord, build_event_payload


def record_quality_decision(
    journal: EventJournal,
    *,
    run_id: str,
    task_id: str,
    decision: str,
    reason: str,
    outcome: str,
    diagnosis_status: str | None = None,
    **extra: Any,
) -> EventRecord:
    return journal.record(
        "agentrunway.quality_decision",
        build_event_payload(
            run_id,
            "quality",
            outcome,
            "quality decision",
            task_id=task_id,
            decision=decision,
            reason=reason,
            diagnosis_status=diagnosis_status,
            **extra,
        ),
    )


def record_candidate_ranked(
    journal: EventJournal,
    *,
    run_id: str,
    task_id: str,
    selected_candidate_id: int | None,
    scores: list[dict[str, Any]],
) -> EventRecord:
    return journal.record(
        "agentrunway.candidate_ranked",
        build_event_payload(
            run_id,
            "quality",
            "success" if selected_candidate_id is not None else "failed",
            "candidate ranked",
            task_id=task_id,
            decision="select_candidate",
            selected_candidate_id=selected_candidate_id,
            scores=scores,
        ),
    )


def record_conflict_redispatch_planned(
    journal: EventJournal,
    *,
    run_id: str,
    task_id: str,
    candidate_id: int,
    reason: str,
) -> EventRecord:
    return journal.record(
        "agentrunway.conflict_redispatch_planned",
        build_event_payload(
            run_id,
            "resume",
            "partial",
            "conflict redispatch planned",
            task_id=task_id,
            candidate_id=candidate_id,
            reason=reason,
            decision="conflict_redispatch",
        ),
    )
