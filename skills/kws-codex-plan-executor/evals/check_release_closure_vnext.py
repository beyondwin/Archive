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
    validate_serialized_review_artifact,
)


CHECKPOINT = "a" * 64
REVISION = "b" * 40
LANES = ("state_crash", "trust_privacy", "cli_dataflow", "release_lineage")


def _finding(
    *,
    invariant_id: str = "trust.git_object_binding",
    severity: str = "P1",
    evidence: tuple[str, ...] = ("evidence/trust.json",),
    disposition: str = "repair",
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
            "trust_privacy": (
                _finding(
                    severity="P0",
                    evidence=("evidence/trust.json",),
                    disposition="repair",
                ),
            ),
            "release_lineage": (
                _finding(
                    severity="P0",
                    evidence=("evidence/lineage.json",),
                    disposition="return_to_design",
                ),
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
    checks["equal_severity_disposition_uses_conservative_precedence"] = (
        finding.recommended_disposition == "return_to_design"
        and finding.dispositions == ("return_to_design", "repair")
    )
    _expect_error(
        "review_disposition_invalid",
        lambda: consolidate_review_lanes(
            _reports(
                lane_findings={
                    "state_crash": (_finding(disposition="unranked_action"),)
                }
            ),
            checkpoint_sha256=CHECKPOINT,
        ),
    )
    checks["unranked_disposition_rejected"] = True
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

    permutation_reports = _reports(
        lane_verdicts={
            "state_crash": "changes_requested",
            "trust_privacy": "inconclusive",
        },
        lane_findings={
            "state_crash": (
                _finding(
                    invariant_id="state.zeta",
                    severity="P2",
                    evidence=("evidence/z-2.json", "evidence/z-1.json"),
                    disposition="no_action",
                ),
                _finding(
                    invariant_id="state.alpha",
                    severity="P1",
                    evidence=("evidence/a-2.json", "evidence/a-1.json"),
                    disposition="repair",
                ),
            ),
        },
        lane_missing_evidence={
            "trust_privacy": ("evidence/missing-z.json", "evidence/missing-a.json")
        },
    )
    permuted_reports = tuple(
        replace(
            report,
            findings=tuple(
                replace(finding, evidence=tuple(reversed(finding.evidence)))
                for finding in reversed(report.findings)
            ),
            missing_evidence=tuple(reversed(report.missing_evidence)),
        )
        for report in reversed(permutation_reports)
    )
    canonical_bytes = json.dumps(
        consolidate_review_lanes(
            permutation_reports, checkpoint_sha256=CHECKPOINT
        ).to_dict(),
        separators=(",", ":"),
    ).encode()
    permuted_bytes = json.dumps(
        consolidate_review_lanes(
            permuted_reports, checkpoint_sha256=CHECKPOINT
        ).to_dict(),
        separators=(",", ":"),
    ).encode()
    checks["all_set_like_collections_serialize_canonically"] = (
        canonical_bytes == permuted_bytes
    )
    duplicate_lane_reports = (
        replace(
            permutation_reports[0],
            findings=permutation_reports[0].findings
            + (permutation_reports[0].findings[0],),
        ),
    ) + permutation_reports[1:]
    duplicate_lane_bytes = json.dumps(
        consolidate_review_lanes(
            duplicate_lane_reports, checkpoint_sha256=CHECKPOINT
        ).to_dict(),
        separators=(",", ":"),
    ).encode()
    checks["exact_duplicate_lane_findings_do_not_change_serialization"] = (
        canonical_bytes == duplicate_lane_bytes
    )

    passed_payload = consolidate_review_lanes(
        _reports(), checkpoint_sha256=CHECKPOINT
    ).to_dict()
    validate_serialized_review_artifact(passed_payload)
    checks["serialized_artifact_semantic_validator_accepts_canonical_payload"] = True

    semantic_mutations: tuple[tuple[str, str, Callable[[dict[str, object]], None]], ...] = (
        (
            "lane_checkpoint",
            "review_artifact_lane_checkpoint_mismatch",
            lambda item: item["lanes"][0].__setitem__("checkpoint_sha256", "c" * 64),
        ),
        (
            "lane_wave",
            "review_artifact_lane_repair_wave_mismatch",
            lambda item: item["lanes"][0].__setitem__("repair_wave", 1),
        ),
        (
            "top_level_passed",
            "review_artifact_passed_mismatch",
            lambda item: item.__setitem__("passed", False),
        ),
        (
            "top_level_verdict",
            "review_artifact_verdict_mismatch",
            lambda item: item.__setitem__("verdict", "changes_requested"),
        ),
        (
            "raw_finding",
            "review_artifact_verdict_mismatch",
            lambda item: item["lanes"][0]["findings"].append(
                {
                    "invariant_id": "state.injected",
                    "severity": "P1",
                    "affected_revision": REVISION,
                    "evidence": ["evidence/injected.json"],
                    "recommended_disposition": "repair",
                }
            ),
        ),
        (
            "missing_evidence",
            "review_artifact_verdict_mismatch",
            lambda item: item["lanes"][0]["missing_evidence"].append(
                "evidence/missing.json"
            ),
        ),
        (
            "lane_verdict",
            "review_artifact_verdict_mismatch",
            lambda item: (
                item["lanes"][0].__setitem__("verdict", "blocked"),
                item["lanes"][0]["missing_evidence"].append("evidence/blocked.json"),
            ),
        ),
        (
            "raw_source_lanes",
            "review_artifact_raw_finding_sources_forbidden",
            lambda item: (
                item["lanes"][0]["findings"].append(
                    {
                        "invariant_id": "state.injected",
                        "severity": "P1",
                        "affected_revision": REVISION,
                        "evidence": ["evidence/injected.json"],
                        "recommended_disposition": "repair",
                        "source_lanes": ["state_crash"],
                    }
                )
            ),
        ),
    )
    for name, code, mutate in semantic_mutations:
        mutated = copy.deepcopy(passed_payload)
        mutate(mutated)
        _expect_error(
            code,
            lambda mutated=mutated: validate_serialized_review_artifact(mutated),
        )
        checks[f"semantic_mutation_{name}_rejected"] = True

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
    raw_sources = copy.deepcopy(payload)
    raw_sources["lanes"][1]["findings"][0]["source_lanes"] = ["trust_privacy"]
    raw_dispositions = copy.deepcopy(payload)
    raw_dispositions["lanes"][1]["findings"][0]["dispositions"] = ["repair"]
    missing_consolidated_sources = copy.deepcopy(payload)
    del missing_consolidated_sources["findings"][0]["source_lanes"]
    missing_consolidated_dispositions = copy.deepcopy(payload)
    del missing_consolidated_dispositions["findings"][0]["dispositions"]
    expected_schema_results = [True, False, False, False, False, False, False, False]
    actual_schema_results = _schema_results(
        [
            (True, payload),
            (False, missing_lane),
            (False, extra_lane),
            (False, duplicate_lane),
            (False, raw_sources),
            (False, raw_dispositions),
            (False, missing_consolidated_sources),
            (False, missing_consolidated_dispositions),
        ]
    )
    checks["draft_2020_12_schema_compiles_and_enforces_artifact_roles"] = (
        actual_schema_results == expected_schema_results
    )

    failures = [name for name, passed in checks.items() if not passed]
    print(json.dumps({**checks, "failures": failures}, indent=2, sort_keys=True))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
