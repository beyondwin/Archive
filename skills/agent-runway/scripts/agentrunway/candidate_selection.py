from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class CandidateScore:
    candidate_id: int
    rank: int
    score: int
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "reasons": list(self.reasons)}


@dataclass(frozen=True)
class CandidateSelection:
    selected_candidate_id: int | None
    scores: tuple[CandidateScore, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected_candidate_id": self.selected_candidate_id,
            "scores": [score.to_dict() for score in self.scores],
        }


@dataclass(frozen=True)
class _CandidateEvaluation:
    candidate_id: int
    verifier_passed: int
    reviewer_approved: int
    file_claims_clean: int
    required_artifacts_present: int
    acceptance_evidence_present: int
    scope_match: int
    unexpected_changed_files: int
    reasons: tuple[str, ...]

    @property
    def rank_key(self) -> tuple[int, int, int, int, int, int, int]:
        return (
            self.verifier_passed,
            self.reviewer_approved,
            self.file_claims_clean,
            self.required_artifacts_present,
            self.acceptance_evidence_present,
            self.scope_match,
            -self.unexpected_changed_files,
        )


def _bool(candidate: dict[str, Any], key: str, default: bool = False) -> bool:
    value = candidate.get(key, default)
    return bool(value)


def _candidate_id(candidate: dict[str, Any]) -> int:
    return int(candidate["id"])


def _unexpected_changed_files(candidate: dict[str, Any]) -> int:
    return max(0, int(candidate.get("unexpected_changed_files", 0) or 0))


def _evaluate(candidate: dict[str, Any]) -> _CandidateEvaluation:
    reasons: list[str] = []
    verifier_passed = int(
        candidate.get("verification_status") == "passed"
        or candidate.get("status") in {"merge_ready", "merged"}
    )
    if verifier_passed:
        reasons.append("verifier_passed")

    reviewer_approved = int(candidate.get("review_status") == "approved")
    if reviewer_approved:
        reasons.append("reviewer_approved")

    file_claims_clean = int(not _bool(candidate, "file_claim_violation"))
    if file_claims_clean:
        reasons.append("file_claims_clean")

    required_artifacts_present = int(_bool(candidate, "required_artifacts_present", True))
    if required_artifacts_present:
        reasons.append("required_artifacts_present")

    acceptance_evidence_present = int(_bool(candidate, "acceptance_evidence_present"))
    if acceptance_evidence_present:
        reasons.append("acceptance_evidence_present")

    scope_match = int(_bool(candidate, "scope_match", True))
    if scope_match:
        reasons.append("scope_match")

    unexpected = _unexpected_changed_files(candidate)
    if unexpected:
        reasons.append("unexpected_changed_files")

    return _CandidateEvaluation(
        candidate_id=_candidate_id(candidate),
        verifier_passed=verifier_passed,
        reviewer_approved=reviewer_approved,
        file_claims_clean=file_claims_clean,
        required_artifacts_present=required_artifacts_present,
        acceptance_evidence_present=acceptance_evidence_present,
        scope_match=scope_match,
        unexpected_changed_files=unexpected,
        reasons=tuple(reasons),
    )


def _display_score(evaluation: _CandidateEvaluation, max_unexpected: int) -> int:
    score = 0
    for signal in (
        evaluation.verifier_passed,
        evaluation.reviewer_approved,
        evaluation.file_claims_clean,
        evaluation.required_artifacts_present,
        evaluation.acceptance_evidence_present,
        evaluation.scope_match,
    ):
        score = (score * 2) + signal
    return (score * (max_unexpected + 1)) + (max_unexpected - evaluation.unexpected_changed_files)


def rank_candidates(candidates: list[dict[str, Any]]) -> list[CandidateScore]:
    evaluations = [_evaluate(candidate) for candidate in candidates]
    max_unexpected = max(
        (evaluation.unexpected_changed_files for evaluation in evaluations),
        default=0,
    )
    ordered = sorted(
        evaluations,
        key=lambda evaluation: (evaluation.rank_key, -evaluation.candidate_id),
        reverse=True,
    )
    return [
        CandidateScore(
            candidate_id=evaluation.candidate_id,
            rank=index + 1,
            score=_display_score(evaluation, max_unexpected),
            reasons=evaluation.reasons,
        )
        for index, evaluation in enumerate(ordered)
    ]


def select_candidate(candidates: list[dict[str, Any]]) -> CandidateSelection:
    scores = tuple(rank_candidates(candidates))
    selected = scores[0].candidate_id if scores else None
    return CandidateSelection(selected_candidate_id=selected, scores=scores)
