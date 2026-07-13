#!/usr/bin/env python3
"""Deterministic contract checks for vNext release closure and review reduction."""

from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from typing import Callable, get_args


SKILL_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = SKILL_ROOT.parents[1]
SCRIPT_ROOT = SKILL_ROOT / "scripts"
SCHEMA_PATH = SKILL_ROOT / "templates" / "integration-review-vnext.schema.json"
sys.path.insert(0, str(SCRIPT_ROOT))

from cpe_runtime.release_closure import (  # noqa: E402
    ClosurePhase,
    ConsolidatedReview,
    ReviewFinding,
    ReviewLaneReport,
    consolidate_review_lanes,
    next_closure_phase,
)


CHECKPOINT = "a" * 64
REVISION = "b" * 40
LANES = ("state_crash", "trust_privacy", "cli_dataflow", "release_lineage")


def _finding(
    *,
    invariant_id: str = "trust.git_object_binding",
    severity: str = "P1",
    evidence: tuple[str, ...] = ("evidence/trust.json",),
    disposition: str = "repair_before_freeze",
) -> ReviewFinding:
    return ReviewFinding(
        invariant_id=invariant_id,
        severity=severity,
        affected_revision=REVISION,
        evidence=evidence,
        recommended_disposition=disposition,
    )


def _reports(
    *,
    repair_wave: int = 0,
    lane_verdicts: dict[str, str] | None = None,
    lane_findings: dict[str, tuple[ReviewFinding, ...]] | None = None,
    lane_missing_evidence: dict[str, tuple[str, ...]] | None = None,
) -> tuple[ReviewLaneReport, ...]:
    verdicts = lane_verdicts or {}
    findings = lane_findings or {}
    missing = lane_missing_evidence or {}
    return tuple(
        ReviewLaneReport(
            lane=lane,
            checkpoint_sha256=CHECKPOINT,
            repair_wave=repair_wave,
            verdict=verdicts.get(lane, "passed"),
            findings=findings.get(lane, ()),
            missing_evidence=missing.get(lane, ()),
        )
        for lane in LANES
    )


def _expect_error(code: str, operation: Callable[[], object]) -> None:
    try:
        operation()
    except (TypeError, ValueError) as exc:
        assert str(exc) == code, (str(exc), code)
    else:
        raise AssertionError(f"expected {code}")


def _schema_results(payloads: list[tuple[bool, dict[str, object]]]) -> list[bool]:
    bun = shutil.which("bun")
    assert bun is not None, "bun is required to validate the JSON Schema with Ajv"
    program = r"""
import { readFileSync } from "node:fs";
import Ajv2020 from "ajv/dist/2020";

const schema = JSON.parse(readFileSync(process.env.CPE_REVIEW_SCHEMA, "utf8"));
const cases = JSON.parse(readFileSync(0, "utf8"));
const ajv = new Ajv2020({allErrors: true, strict: true});
if (!ajv.validateSchema(schema)) {
  throw new Error(ajv.errorsText(ajv.errors));
}
const validate = ajv.compile(schema);
const actual = cases.map((item) => Boolean(validate(item.payload)));
process.stdout.write(JSON.stringify(actual));
"""
    completed = subprocess.run(
        [bun, "-e", program],
        cwd=REPOSITORY_ROOT,
        env={**os.environ, "CPE_REVIEW_SCHEMA": str(SCHEMA_PATH)},
        input=json.dumps(
            [{"expected": expected, "payload": payload} for expected, payload in payloads]
        ),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def main() -> None:
    checks: dict[str, bool] = {}

    expected_phases = (
        "trust_repair",
        "integration_review",
        "frozen",
        "cost_free_passed",
        "live_proved",
        "closed",
    )
    checks["six_canonical_phases"] = get_args(ClosurePhase) == expected_phases

    legal = (
        ("trust_repair", "trust_repaired", "integration_review"),
        ("integration_review", "review_passed", "frozen"),
        ("frozen", "cost_free_passed", "cost_free_passed"),
        ("cost_free_passed", "live_proved", "live_proved"),
        ("live_proved", "metadata_verified", "closed"),
    )
    checks["legal_closure_transitions"] = all(
        next_closure_phase(current, event) == expected
        for current, event, expected in legal
    )
    for current, event in (
        ("trust_repair", "review_passed"),
        ("integration_review", "trust_repaired"),
        ("frozen", "live_proved"),
        ("closed", "metadata_verified"),
        ("unknown", "trust_repaired"),
    ):
        _expect_error(
            "illegal_closure_transition",
            lambda current=current, event=event: next_closure_phase(current, event),
        )
    checks["illegal_closure_transitions_rejected"] = True

    duplicate_reports = _reports(
        lane_findings={
            "trust_privacy": (_finding(severity="P1", evidence=("evidence/trust.json",)),),
            "release_lineage": (
                _finding(severity="P0", evidence=("evidence/lineage.json",)),
            ),
        }
    )
    review = consolidate_review_lanes(duplicate_reports, checkpoint_sha256=CHECKPOINT)
    assert isinstance(review, ConsolidatedReview)
    checks["duplicate_invariant_reduced_once"] = [
        finding.invariant_id for finding in review.findings
    ] == ["trust.git_object_binding"]
    finding = review.findings[0]
    checks["highest_severity_and_all_evidence_preserved"] = (
        finding.severity == "P0"
        and finding.evidence == ("evidence/lineage.json", "evidence/trust.json")
        and finding.source_lanes == ("trust_privacy", "release_lineage")
    )
    checks["finding_overrides_conflicting_pass_verdicts"] = review.verdict == "changes_requested"
    checks["one_repair_wave_contract"] = (
        review.repair_wave == 0 and review.repair_waves_allowed == 1
    )

    blocked = consolidate_review_lanes(
        _reports(
            lane_verdicts={"state_crash": "blocked"},
            lane_missing_evidence={"state_crash": ("evidence/crash-replay.json",)},
        ),
        checkpoint_sha256=CHECKPOINT,
    )
    checks["blocked_verdict_has_conservative_precedence"] = blocked.verdict == "blocked"

    _expect_error(
        "review_checkpoint_mismatch",
        lambda: consolidate_review_lanes(
            (replace(duplicate_reports[0], checkpoint_sha256="c" * 64),)
            + duplicate_reports[1:],
            checkpoint_sha256=CHECKPOINT,
        ),
    )
    checks["checkpoint_mismatch_rejected"] = True

    for code, reports in (
        ("review_lanes_missing", duplicate_reports[:-1]),
        (
            "review_lanes_extra",
            duplicate_reports
            + (replace(duplicate_reports[-1], lane="unapproved_lane"),),
        ),
        (
            "review_lanes_duplicate",
            duplicate_reports[:-1]
            + (replace(duplicate_reports[-1], lane="trust_privacy"),),
        ),
    ):
        _expect_error(
            code,
            lambda reports=reports: consolidate_review_lanes(
                reports, checkpoint_sha256=CHECKPOINT
            ),
        )
    checks["exact_four_lane_set_enforced"] = True

    _expect_error(
        "review_repair_wave_limit_exceeded",
        lambda: consolidate_review_lanes(
            _reports(repair_wave=2), checkpoint_sha256=CHECKPOINT
        ),
    )
    checks["second_repair_wave_rejected"] = True

    payload = review.to_dict()
    checks["contract_does_not_claim_release_or_live_proof"] = (
        payload["contract_scope"] == "review_consolidation_only"
        and "final_release_verdict" not in payload
        and "live_proof" not in payload
    )
    missing_lane = copy.deepcopy(payload)
    missing_lane["lanes"].pop()
    extra_lane = copy.deepcopy(payload)
    extra_lane["lanes"].append(copy.deepcopy(payload["lanes"][-1]))
    duplicate_lane = copy.deepcopy(payload)
    duplicate_lane["lanes"][-1]["lane"] = "trust_privacy"
    expected_schema_results = [True, False, False, False]
    actual_schema_results = _schema_results(
        [
            (True, payload),
            (False, missing_lane),
            (False, extra_lane),
            (False, duplicate_lane),
        ]
    )
    checks["draft_2020_12_schema_compiles_and_enforces_lanes"] = (
        actual_schema_results == expected_schema_results
    )

    failures = [name for name, passed in checks.items() if not passed]
    print(json.dumps({**checks, "failures": failures}, indent=2, sort_keys=True))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
