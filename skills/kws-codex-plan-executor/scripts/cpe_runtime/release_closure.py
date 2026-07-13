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
ReviewDisposition = Literal["return_to_design", "repair", "no_action"]


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
_DISPOSITION_RANK = {
    disposition: rank
    for rank, disposition in enumerate(("return_to_design", "repair", "no_action"))
}
_INVARIANT_ID = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)+$")


@dataclass(frozen=True)
class ReviewFinding:
    invariant_id: str
    severity: ReviewSeverity
    affected_revision: str
    evidence: tuple[str, ...]
    recommended_disposition: ReviewDisposition
    source_lanes: tuple[ReviewLane, ...] = ()
    dispositions: tuple[ReviewDisposition, ...] = ()


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

        payload = _review_dict(self)
        validate_serialized_review_artifact(payload)
        return payload

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
            strongest_dispositions = {
                finding.recommended_disposition
                for _, finding in entries
                if finding.severity == severity
            }
            dispositions = tuple(
                sorted(
                    {finding.recommended_disposition for _, finding in entries},
                    key=lambda item: _DISPOSITION_RANK[item],
                )
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
                    recommended_disposition=min(
                        strongest_dispositions,
                        key=lambda item: _DISPOSITION_RANK[item],
                    ),
                    source_lanes=lanes,
                    dispositions=dispositions,
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


def _review_dict(review: ConsolidatedReview) -> dict[str, object]:
    return {
        "schema_version": "cpe.integration-review.vnext",
        "contract_scope": "review_consolidation_only",
        "checkpoint_sha256": review.checkpoint_sha256,
        "repair_wave": review.repair_wave,
        "repair_waves_allowed": review.repair_waves_allowed,
        "verdict": review.verdict,
        "passed": review.verdict == "passed",
        "lanes": [_lane_report_dict(report) for report in review.lanes],
        "findings": [
            _finding_dict(finding, include_reducer_fields=True)
            for finding in review.findings
        ],
    }


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
        _canonical_lane_report(
            next(report for report in materialized if report.lane == lane)
        )
        for lane in REVIEW_LANES
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


def validate_serialized_review_artifact(payload: object) -> None:
    """Validate and replay a serialized, potentially untrusted review artifact.

    JSON Schema remains the structural gate.  This mandatory semantic gate
    replays the raw lane inputs through the reducer and rejects any duplicated
    top-level value or reducer-owned field that does not match canonical output.
    """

    if not isinstance(payload, dict):
        raise TypeError("review_artifact_object_required")
    _require_exact_keys(
        payload,
        {
            "schema_version",
            "contract_scope",
            "checkpoint_sha256",
            "repair_wave",
            "repair_waves_allowed",
            "verdict",
            "passed",
            "lanes",
            "findings",
        },
        "review_artifact_shape_invalid",
    )
    if payload["schema_version"] != "cpe.integration-review.vnext":
        raise ValueError("review_artifact_schema_version_invalid")
    if payload["contract_scope"] != "review_consolidation_only":
        raise ValueError("review_artifact_scope_invalid")
    checkpoint = payload["checkpoint_sha256"]
    _require_sha256(checkpoint, "review_artifact_checkpoint_invalid")
    repair_wave = payload["repair_wave"]
    if type(repair_wave) is not int or not 0 <= repair_wave <= REPAIR_WAVES_ALLOWED:
        raise ValueError("review_artifact_repair_wave_invalid")
    if type(payload["repair_waves_allowed"]) is not int or (
        payload["repair_waves_allowed"] != REPAIR_WAVES_ALLOWED
    ):
        raise ValueError("review_artifact_repair_wave_limit_invalid")
    if payload["verdict"] not in {
        "passed",
        "changes_requested",
        "blocked",
        "inconclusive",
    }:
        raise ValueError("review_artifact_verdict_invalid")
    if type(payload["passed"]) is not bool:
        raise TypeError("review_artifact_passed_invalid")

    raw_lanes = payload["lanes"]
    if not isinstance(raw_lanes, list) or len(raw_lanes) != len(REVIEW_LANES):
        raise ValueError("review_artifact_lanes_invalid")
    reports: list[ReviewLaneReport] = []
    for index, raw_report in enumerate(raw_lanes):
        if not isinstance(raw_report, dict):
            raise TypeError("review_artifact_lane_object_required")
        _require_exact_keys(
            raw_report,
            {
                "lane",
                "checkpoint_sha256",
                "repair_wave",
                "verdict",
                "findings",
                "missing_evidence",
            },
            "review_artifact_lane_shape_invalid",
        )
        if raw_report["lane"] != REVIEW_LANES[index]:
            raise ValueError("review_artifact_lane_order_invalid")
        if raw_report["checkpoint_sha256"] != checkpoint:
            raise ValueError("review_artifact_lane_checkpoint_mismatch")
        if raw_report["repair_wave"] != repair_wave:
            raise ValueError("review_artifact_lane_repair_wave_mismatch")

        raw_findings = raw_report["findings"]
        if not isinstance(raw_findings, list):
            raise TypeError("review_artifact_findings_array_required")
        findings: list[ReviewFinding] = []
        for raw_finding in raw_findings:
            if not isinstance(raw_finding, dict):
                raise TypeError("review_artifact_finding_object_required")
            if "source_lanes" in raw_finding:
                raise ValueError("review_artifact_raw_finding_sources_forbidden")
            if "dispositions" in raw_finding:
                raise ValueError("review_artifact_raw_finding_dispositions_forbidden")
            _require_exact_keys(
                raw_finding,
                {
                    "invariant_id",
                    "severity",
                    "affected_revision",
                    "evidence",
                    "recommended_disposition",
                },
                "review_artifact_finding_shape_invalid",
            )
            raw_evidence = raw_finding["evidence"]
            if not isinstance(raw_evidence, list):
                raise TypeError("review_artifact_evidence_array_required")
            findings.append(
                ReviewFinding(
                    invariant_id=raw_finding["invariant_id"],
                    severity=raw_finding["severity"],
                    affected_revision=raw_finding["affected_revision"],
                    evidence=tuple(raw_evidence),
                    recommended_disposition=raw_finding["recommended_disposition"],
                )
            )

        raw_missing = raw_report["missing_evidence"]
        if not isinstance(raw_missing, list):
            raise TypeError("review_artifact_missing_evidence_array_required")
        reports.append(
            ReviewLaneReport(
                lane=raw_report["lane"],
                checkpoint_sha256=raw_report["checkpoint_sha256"],
                repair_wave=raw_report["repair_wave"],
                verdict=raw_report["verdict"],
                findings=tuple(findings),
                missing_evidence=tuple(raw_missing),
            )
        )

    recomputed = consolidate_review_lanes(reports, checkpoint_sha256=checkpoint)
    if payload["verdict"] != recomputed.verdict:
        raise ValueError("review_artifact_verdict_mismatch")
    if payload["passed"] != (recomputed.verdict == "passed"):
        raise ValueError("review_artifact_passed_mismatch")
    if payload != _review_dict(recomputed):
        raise ValueError("review_artifact_not_canonical")


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
    if finding.recommended_disposition not in _DISPOSITION_RANK:
        raise ValueError("review_disposition_invalid")
    if finding.source_lanes:
        raise ValueError("review_finding_sources_are_reducer_owned")
    if finding.dispositions:
        raise ValueError("review_finding_dispositions_are_reducer_owned")


def _canonical_lane_report(report: ReviewLaneReport) -> ReviewLaneReport:
    findings = tuple(
        sorted(
            {
                ReviewFinding(
                    invariant_id=finding.invariant_id,
                    severity=finding.severity,
                    affected_revision=finding.affected_revision,
                    evidence=tuple(sorted(finding.evidence)),
                    recommended_disposition=finding.recommended_disposition,
                )
                for finding in report.findings
            },
            key=_finding_sort_key,
        )
    )
    return ReviewLaneReport(
        lane=report.lane,
        checkpoint_sha256=report.checkpoint_sha256,
        repair_wave=report.repair_wave,
        verdict=report.verdict,
        findings=findings,
        missing_evidence=tuple(sorted(report.missing_evidence)),
    )


def _finding_sort_key(finding: ReviewFinding) -> tuple[object, ...]:
    return (
        finding.invariant_id,
        _SEVERITY_RANK[finding.severity],
        finding.affected_revision,
        _DISPOSITION_RANK[finding.recommended_disposition],
        finding.evidence,
    )


def _finding_dict(
    finding: ReviewFinding, *, include_reducer_fields: bool
) -> dict[str, object]:
    payload: dict[str, object] = {
        "invariant_id": finding.invariant_id,
        "severity": finding.severity,
        "affected_revision": finding.affected_revision,
        "evidence": list(finding.evidence),
        "recommended_disposition": finding.recommended_disposition,
    }
    if include_reducer_fields:
        payload["source_lanes"] = list(finding.source_lanes)
        payload["dispositions"] = list(finding.dispositions)
    return payload


def _lane_report_dict(report: ReviewLaneReport) -> dict[str, object]:
    return {
        "lane": report.lane,
        "checkpoint_sha256": report.checkpoint_sha256,
        "repair_wave": report.repair_wave,
        "verdict": report.verdict,
        "findings": [
            _finding_dict(finding, include_reducer_fields=False)
            for finding in report.findings
        ],
        "missing_evidence": list(report.missing_evidence),
    }


def _require_exact_keys(value: dict[object, object], expected: set[str], code: str) -> None:
    if set(value) != expected:
        raise ValueError(code)


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
