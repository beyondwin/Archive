#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
from copy import deepcopy
from pathlib import Path

from check_validation_consumer_parity import make_v3_run, record_revision

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from cpe_runtime.validation import validate_completion
from cpe_runtime.events import append_event
from cpe_runtime.kernel import rebuild_snapshot


def main() -> int:
    checks: dict[str, bool] = {}
    with tempfile.TemporaryDirectory(prefix="cpe-v3-verification-bundle-") as raw:
        root = Path(raw)
        prospective_run, prospective = make_v3_run(
            root / "prospective",
            false_completion=False,
            terminal=False,
            record_audit=False,
        )
        prospective_refs = [item["ref"] for item in prospective["artifact_index"]]
        prospective_checklist = [
            {
                "kind": item["kind"],
                "task_id": item.get("task_id"),
                "ref": item["ref"],
            }
            for item in prospective["artifact_index"]
        ]
        duplicate_audit = deepcopy(prospective)
        duplicate_audit["completion_audit"] = {
            "passed": True,
            "prompt_to_artifact_checklist": prospective_checklist,
            "verification_evidence": prospective_refs + [prospective_refs[0]],
            "residual_risk": [],
        }
        checks["audit_rejects_duplicate_refs"] = (
            "completion_evidence_duplicate" in validate_completion(
                prospective_run, candidate_state=duplicate_audit
            ).errors
        )
        checklist_gap = deepcopy(prospective)
        checklist_gap["completion_audit"] = {
            "passed": True,
            "prompt_to_artifact_checklist": prospective_checklist[:-1],
            "verification_evidence": prospective_refs,
            "residual_risk": [],
        }
        checks["audit_rejects_structured_checklist_gap"] = (
            "completion_checklist_incomplete" in validate_completion(
                prospective_run, candidate_state=checklist_gap
            ).errors
        )
        forged = deepcopy(prospective)
        forged["tasks"]["T1"]["status"] = "pending"
        checks["candidate_rejects_forged_projection"] = (
            validate_completion(prospective_run, candidate_state=forged).errors[0]
            == "candidate_state_invalid"
        )
        blocked_run, pre_blocker = make_v3_run(
            root / "pre-blocker",
            false_completion=False,
            terminal=False,
            record_audit=False,
        )
        append_event(
            blocked_run / "events.jsonl",
            {
                "type": "blocker.opened",
                "task_id": "T1",
                "payload": {
                    "blocker_id": "B-late",
                    "category": "state_integrity",
                    "owner": "cpe",
                    "resume_condition": "repair current evidence",
                },
            },
        )
        rebuild_snapshot(blocked_run)
        checks["candidate_cannot_replace_post_blocker_projection"] = (
            validate_completion(blocked_run, candidate_state=pre_blocker).errors[0]
            == "candidate_state_invalid"
        )

        run_dir, healthy = make_v3_run(root / "healthy", false_completion=False, terminal=False)
        checks["current_v3_bundle_passes"] = validate_completion(
            run_dir, candidate_state=healthy
        ).passed

        stale_history_run, stale_history = make_v3_run(
            root / "stale-history",
            false_completion=False,
            terminal=False,
            include_stale_history=True,
        )
        stale_history_report = validate_completion(stale_history_run)
        checks["audit_excludes_stale_history"] = (
            stale_history_report.passed
            and "stale_revision_evidence" in stale_history_report.warnings
            and len(stale_history["artifact_index"])
            == len(stale_history["completion_audit"]["verification_evidence"]) + 1
        )

        negative_history_run, _ = make_v3_run(
            root / "negative-history",
            false_completion=False,
            terminal=False,
            include_current_negative_history=True,
        )
        checks["latest_pass_is_not_poisoned_by_earlier_negative_history"] = (
            validate_completion(negative_history_run).passed
        )

        missing_repository = deepcopy(prospective)
        missing_repository_refs = [
            ref
            for ref in prospective_refs
            if ref.get("kind") != "repository_check"
        ]
        missing_repository_checklist = [
            item
            for item in prospective_checklist
            if item["kind"] != "repository_check"
        ]
        missing_repository["completion_audit"] = {
            "passed": True,
            "prompt_to_artifact_checklist": missing_repository_checklist,
            "verification_evidence": missing_repository_refs,
            "residual_risk": [],
        }
        checks["audit_must_index_repository_bundle"] = (
            "completion_evidence_incomplete" in validate_completion(
                prospective_run, candidate_state=missing_repository
            ).errors
        )

        stale_run, _ = make_v3_run(
            root / "stale-revision", false_completion=False, terminal=False
        )
        record_revision(stale_run, "T1", b"revision two\n")
        report = validate_completion(stale_run)
        checks["stale_bundle_fails_closed"] = (
            "current_revision_acceptance_not_passed" in report.errors
            and "current_revision_task_review_not_passed" in report.errors
            and "current_revision_verification_not_passed" in report.errors
            and "current_revision_repository_check_missing" in report.errors
            and "stale_completion_evidence" in report.errors
        )

        tampered_run, tampered = make_v3_run(
            root / "tampered", false_completion=False, terminal=False
        )
        tampered_ref = tampered["completion_audit"]["verification_evidence"][0]
        (tampered_run / tampered_ref["path"]).write_text("{}\n", encoding="utf-8")
        report = validate_completion(tampered_run)
        checks["tampered_bundle_fails_digest_check"] = (
            "evidence_digest_mismatch" in report.errors
            and "completion_evidence_invalid" in report.errors
        )

    failures = [name for name, passed in checks.items() if not passed]
    print(json.dumps({"passed": not failures, "checks": checks, "failures": failures}, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
