"""Closed vNext release phases and deterministic integration-review contracts.

This module defines and reduces review evidence.  It does not execute the R3
review program, authorize live proof, or issue a final release verdict.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Literal


ClosurePhase = Literal[
    "trust_repair",
    "integration_review",
    "frozen",
    "cost_free_passed",
    "live_proved",
    "closed",
]
ReviewLane = Literal[
    "state_crash",
    "trust_privacy",
    "cli_dataflow",
    "release_lineage",
]
ReviewSeverity = Literal["P0", "P1", "P2", "P3"]
ReviewVerdict = Literal["passed", "changes_requested", "blocked", "inconclusive"]


CLOSURE_PHASES: tuple[ClosurePhase, ...] = (
    "trust_repair",
    "integration_review",
    "frozen",
    "cost_free_passed",
    "live_proved",
    "closed",
)
REVIEW_LANES: tuple[ReviewLane, ...] = (
    "state_crash",
    "trust_privacy",
    "cli_dataflow",
    "release_lineage",
)
REPAIR_WAVES_ALLOWED = 1


_PHASE_TRANSITIONS: dict[tuple[str, str], ClosurePhase] = {
    ("trust_repair", "trust_repaired"): "integration_review",
    ("integration_review", "review_passed"): "frozen",
    ("frozen", "cost_free_passed"): "cost_free_passed",
    ("cost_free_passed", "live_proved"): "live_proved",
    ("live_proved", "metadata_verified"): "closed",
}
_SEVERITY_RANK = {severity: rank for rank, severity in enumerate(("P0", "P1", "P2", "P3"))}
_INVARIANT_ID = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)+$")


@dataclass(frozen=True)
class ReviewFinding:
    invariant_id: str
    severity: ReviewSeverity
    affected_revision: str
    evidence: tuple[str, ...]
    recommended_disposition: str
    source_lanes: tuple[ReviewLane, ...] = ()


@dataclass(frozen=True)
class ReviewLaneReport:
    lane: ReviewLane
    checkpoint_sha256: str
    repair_wave: int
    verdict: ReviewVerdict
    findings: tuple[ReviewFinding, ...] = ()
    missing_evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class ConsolidatedReview:
    checkpoint_sha256: str
    repair_wave: int
    verdict: ReviewVerdict
    lanes: tuple[ReviewLaneReport, ...]
    findings: tuple[ReviewFinding, ...]
    repair_waves_allowed: int = REPAIR_WAVES_ALLOWED

    def to_dict(self) -> dict[str, object]:
        """Return the canonical JSON-compatible review-contract payload."""

        return {
            "schema_version": "cpe.integration-review.vnext",
            "contract_scope": "review_consolidation_only",
            "checkpoint_sha256": self.checkpoint_sha256,
            "repair_wave": self.repair_wave,
            "repair_waves_allowed": self.repair_waves_allowed,
            "verdict": self.verdict,
            "lanes": [_lane_report_dict(report) for report in self.lanes],
            "findings": [_finding_dict(finding, include_sources=True) for finding in self.findings],
        }

    @classmethod
    def from_invariant_groups(
        cls,
        reports: tuple[ReviewLaneReport, ...],
        checkpoint_sha256: str,
        *,
        repair_waves_allowed: int,
    ) -> "ConsolidatedReview":
        """Reduce validated lane reports by stable invariant identity."""

        groups: dict[str, list[tuple[ReviewLane, ReviewFinding]]] = {}
        for report in reports:
            for finding in report.findings:
                groups.setdefault(finding.invariant_id, []).append((report.lane, finding))

        consolidated: list[ReviewFinding] = []
        for invariant_id in sorted(groups):
            entries = groups[invariant_id]
            revisions = {finding.affected_revision for _, finding in entries}
            if len(revisions) != 1:
                raise ValueError("review_invariant_revision_conflict")
            severity = min(
                (finding.severity for _, finding in entries),
                key=lambda item: _SEVERITY_RANK[item],
            )
            strongest_dispositions = sorted(
                {
                    finding.recommended_disposition
                    for _, finding in entries
                    if finding.severity == severity
                }
            )
            evidence = tuple(
                sorted({reference for _, finding in entries for reference in finding.evidence})
            )
            lanes = tuple(
                lane
                for lane in REVIEW_LANES
                if any(source_lane == lane for source_lane, _ in entries)
            )
            consolidated.append(
                ReviewFinding(
                    invariant_id=invariant_id,
                    severity=severity,
                    affected_revision=next(iter(revisions)),
                    evidence=evidence,
                    recommended_disposition=strongest_dispositions[0],
                    source_lanes=lanes,
                )
            )

        verdicts = {report.verdict for report in reports}
        if "blocked" in verdicts:
            verdict: ReviewVerdict = "blocked"
        elif "inconclusive" in verdicts or any(report.missing_evidence for report in reports):
            verdict = "inconclusive"
        elif consolidated or "changes_requested" in verdicts:
            verdict = "changes_requested"
        else:
            verdict = "passed"

        return cls(
            checkpoint_sha256=checkpoint_sha256,
            repair_wave=reports[0].repair_wave,
            verdict=verdict,
            lanes=reports,
            findings=tuple(consolidated),
            repair_waves_allowed=repair_waves_allowed,
        )


def next_closure_phase(current: str, event: str) -> ClosurePhase:
    """Return the one legal successor for a phase/event pair."""

    try:
        return _PHASE_TRANSITIONS[(current, event)]
    except (KeyError, TypeError) as exc:
        raise ValueError("illegal_closure_transition") from exc


def consolidate_review_lanes(
    reports: Iterable[ReviewLaneReport], *, checkpoint_sha256: str
) -> ConsolidatedReview:
    """Validate and deterministically consolidate exactly four review lanes."""

    materialized = tuple(reports)
    _require_exact_lanes(materialized)
    _require_sha256(checkpoint_sha256, "review_checkpoint_invalid")

    waves: set[int] = set()
    for report in materialized:
        if not isinstance(report, ReviewLaneReport):
            raise TypeError("review_lane_report_required")
        if report.checkpoint_sha256 != checkpoint_sha256:
            raise ValueError("review_checkpoint_mismatch")
        if type(report.repair_wave) is not int or report.repair_wave < 0:
            raise ValueError("review_repair_wave_invalid")
        if report.repair_wave > REPAIR_WAVES_ALLOWED:
            raise ValueError("review_repair_wave_limit_exceeded")
        waves.add(report.repair_wave)
        if report.verdict not in {"passed", "changes_requested", "blocked", "inconclusive"}:
            raise ValueError("review_lane_verdict_invalid")
        _require_string_tuple(report.missing_evidence, "review_missing_evidence_invalid")
        if report.verdict in {"changes_requested", "blocked", "inconclusive"} and not (
            report.findings or report.missing_evidence
        ):
            raise ValueError("review_lane_verdict_unsupported")
        if not isinstance(report.findings, tuple):
            raise TypeError("review_findings_tuple_required")
        for finding in report.findings:
            _validate_finding(finding)
    if len(waves) != 1:
        raise ValueError("review_repair_wave_mismatch")

    ordered = tuple(
        next(report for report in materialized if report.lane == lane) for lane in REVIEW_LANES
    )
    return ConsolidatedReview.from_invariant_groups(
        ordered,
        checkpoint_sha256,
        repair_waves_allowed=REPAIR_WAVES_ALLOWED,
    )


def _require_exact_lanes(reports: tuple[ReviewLaneReport, ...]) -> None:
    lanes = [getattr(report, "lane", None) for report in reports]
    approved = set(REVIEW_LANES)
    if any(lane not in approved for lane in lanes) or len(lanes) > len(REVIEW_LANES):
        raise ValueError("review_lanes_extra")
    if len(lanes) != len(set(lanes)):
        raise ValueError("review_lanes_duplicate")
    if set(lanes) != approved:
        raise ValueError("review_lanes_missing")


def _validate_finding(finding: ReviewFinding) -> None:
    if not isinstance(finding, ReviewFinding):
        raise TypeError("review_finding_required")
    if not isinstance(finding.invariant_id, str) or not _INVARIANT_ID.fullmatch(
        finding.invariant_id
    ):
        raise ValueError("review_invariant_id_invalid")
    if finding.severity not in _SEVERITY_RANK:
        raise ValueError("review_severity_invalid")
    if not _is_lower_hex(finding.affected_revision, 40):
        raise ValueError("review_affected_revision_invalid")
    _require_string_tuple(finding.evidence, "review_evidence_invalid", require_nonempty=True)
    if not isinstance(finding.recommended_disposition, str) or not finding.recommended_disposition:
        raise ValueError("review_disposition_invalid")
    if finding.source_lanes:
        raise ValueError("review_finding_sources_are_reducer_owned")


def _finding_dict(finding: ReviewFinding, *, include_sources: bool) -> dict[str, object]:
    payload: dict[str, object] = {
        "invariant_id": finding.invariant_id,
        "severity": finding.severity,
        "affected_revision": finding.affected_revision,
        "evidence": list(finding.evidence),
        "recommended_disposition": finding.recommended_disposition,
    }
    if include_sources:
        payload["source_lanes"] = list(finding.source_lanes)
    return payload


def _lane_report_dict(report: ReviewLaneReport) -> dict[str, object]:
    return {
        "lane": report.lane,
        "checkpoint_sha256": report.checkpoint_sha256,
        "repair_wave": report.repair_wave,
        "verdict": report.verdict,
        "findings": [_finding_dict(finding, include_sources=False) for finding in report.findings],
        "missing_evidence": list(report.missing_evidence),
    }


def _require_sha256(value: object, code: str) -> None:
    if not _is_lower_hex(value, 64):
        raise ValueError(code)


def _is_lower_hex(value: object, length: int) -> bool:
    return (
        isinstance(value, str)
        and len(value) == length
        and all(character in "0123456789abcdef" for character in value)
    )


def _require_string_tuple(
    value: object, code: str, *, require_nonempty: bool = False
) -> None:
    if not isinstance(value, tuple) or (require_nonempty and not value):
        raise TypeError(code)
    if any(not isinstance(item, str) or not item for item in value) or len(value) != len(
        set(value)
    ):
        raise ValueError(code)
