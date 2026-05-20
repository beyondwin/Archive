from __future__ import annotations

from agentrunway.candidate_selection import rank_candidates, select_candidate


def _candidate(candidate_id: int, **overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "id": candidate_id,
        "task_id": "task_001",
        "worker_id": f"task_001-implementer-{candidate_id:03d}",
        "status": "validated",
        "verification_status": "passed",
        "review_status": "approved",
        "file_claim_violation": False,
        "required_artifacts_present": True,
        "acceptance_evidence_present": True,
        "scope_match": True,
        "unexpected_changed_files": 0,
    }
    data.update(overrides)
    return data


def test_verifier_passed_candidate_wins() -> None:
    ranked = rank_candidates(
        [
            _candidate(2, verification_status="failed"),
            _candidate(1, verification_status="passed"),
        ]
    )

    assert ranked[0].candidate_id == 1
    assert ranked[0].rank == 1
    assert "verifier_passed" in ranked[0].reasons


def test_verifier_passed_dominates_lower_priority_signals() -> None:
    selected = select_candidate(
        [
            _candidate(
                1,
                verification_status="passed",
                review_status="changes_requested",
                file_claim_violation=True,
                required_artifacts_present=False,
                acceptance_evidence_present=False,
                scope_match=False,
                unexpected_changed_files=3,
            ),
            _candidate(2, verification_status="failed"),
        ]
    )

    assert selected.selected_candidate_id == 1
    assert selected.scores[0].candidate_id == 1


def test_reviewer_approved_dominates_lower_priority_signals() -> None:
    selected = select_candidate(
        [
            _candidate(
                1,
                review_status="approved",
                file_claim_violation=True,
                required_artifacts_present=False,
                acceptance_evidence_present=False,
                scope_match=False,
                unexpected_changed_files=3,
            ),
            _candidate(2, review_status="changes_requested"),
        ]
    )

    assert selected.selected_candidate_id == 1
    assert selected.scores[0].candidate_id == 1


def test_file_claim_violation_loses_even_with_lower_candidate_id() -> None:
    selected = select_candidate(
        [
            _candidate(1, file_claim_violation=True),
            _candidate(2),
        ]
    )

    assert selected.selected_candidate_id == 2
    assert selected.scores[0].candidate_id == 2


def test_missing_artifact_and_acceptance_evidence_lower_score() -> None:
    selected = select_candidate(
        [
            _candidate(1, required_artifacts_present=False, acceptance_evidence_present=False),
            _candidate(2, unexpected_changed_files=1),
        ]
    )

    assert selected.selected_candidate_id == 2
    assert selected.scores[0].score > selected.scores[1].score


def test_tie_breaks_by_candidate_id() -> None:
    selected = select_candidate([_candidate(8), _candidate(7)])

    assert selected.selected_candidate_id == 7
    assert [score.candidate_id for score in selected.scores] == [7, 8]
