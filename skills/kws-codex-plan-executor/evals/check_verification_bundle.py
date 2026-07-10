#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
from copy import deepcopy
from pathlib import Path

from check_validation_consumer_parity import make_v3_run

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from cpe_runtime.validation import validate_completion
from cpe_runtime.evidence import put_json


def main() -> int:
    checks: dict[str, bool] = {}
    with tempfile.TemporaryDirectory(prefix="cpe-v3-verification-bundle-") as raw:
        run_dir, healthy = make_v3_run(Path(raw), false_completion=False, terminal=False)
        checks["current_v3_bundle_passes"] = validate_completion(
            run_dir, candidate_state=healthy
        ).passed

        stale_history = deepcopy(healthy)
        task_id = "T1"
        packet_sha = next(
            item["packet_sha256"]
            for item in stale_history["verdicts"]
            if item.get("task_id") == task_id
        )
        stale_ref = put_json(
            run_dir,
            "acceptance",
            {
                "task_id": task_id,
                "passed": True,
                "worktree_revision": 0,
                "worktree_patch_sha256": None,
                "packet_sha256": packet_sha,
            },
        ).as_dict()
        stale_history["artifact_index"].insert(
            0,
            {"task_id": task_id, "attempt_id": "T1.acceptance.old", "kind": "acceptance", "ref": stale_ref},
        )
        stale_history_report = validate_completion(run_dir, candidate_state=stale_history)
        checks["audit_excludes_stale_history"] = (
            stale_history_report.passed
            and "stale_revision_evidence" in stale_history_report.warnings
            and stale_ref not in stale_history["completion_audit"]["verification_evidence"]
        )

        missing_repository = deepcopy(healthy)
        missing_repository["completion_audit"]["verification_evidence"] = [
            ref
            for ref in missing_repository["completion_audit"]["verification_evidence"]
            if ref.get("kind") != "repository_check"
        ]
        checks["audit_must_index_repository_bundle"] = (
            validate_completion(run_dir, candidate_state=missing_repository).errors
            == ["completion_evidence_incomplete"]
        )

        stale = deepcopy(healthy)
        stale["worktree_revision"] += 1
        stale["worktree_patch_sha256"] = "c" * 64
        report = validate_completion(run_dir, candidate_state=stale)
        checks["stale_bundle_fails_closed"] = (
            "current_revision_acceptance_not_passed" in report.errors
            and "current_revision_task_review_not_passed" in report.errors
            and "current_revision_verification_not_passed" in report.errors
            and "current_revision_repository_check_missing" in report.errors
            and "stale_completion_evidence" in report.errors
        )

        tampered_ref = healthy["completion_audit"]["verification_evidence"][0]
        (run_dir / tampered_ref["path"]).write_text("{}\n", encoding="utf-8")
        report = validate_completion(run_dir, candidate_state=healthy)
        checks["tampered_bundle_fails_digest_check"] = (
            "evidence_digest_mismatch" in report.errors
            and "completion_evidence_invalid" in report.errors
        )

    failures = [name for name, passed in checks.items() if not passed]
    print(json.dumps({"passed": not failures, "checks": checks, "failures": failures}, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
