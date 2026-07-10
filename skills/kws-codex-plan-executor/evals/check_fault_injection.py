#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from cpe_runtime.attempt_controller import validate_verdict
from cpe_runtime.worker import Worker, WorkerError, WorkerRequest


def rejected(message: str, fn) -> bool:
    try:
        fn()
    except WorkerError as exc:
        return str(exc) == message
    return False


def worker_rejects_result(message: str, payload: dict[str, object]) -> bool:
    request = WorkerRequest(
        attempt_id="T1.task_review.fault",
        attempt_kind="task_review",
        prompt="{}",
        worktree=Path("/tmp/cpe-verdict-fault-worktree"),
        read_only=True,
        verdict_capable=True,
        task_id="T1",
        packet_path="artifacts/task-packets/T1.json",
        packet_sha256="a" * 64,
        worktree_revision=7,
    )
    provider_payload = {
        **payload,
        "_provider_metadata": {
            "model": "gpt-5.6-sol",
            "reasoning": "high",
            "trusted_source": "fault-fixture",
        },
    }
    return rejected(message, lambda: Worker(provider=lambda _request, _argv: provider_payload).run(request))


def verdict_cases() -> dict[str, bool]:
    base = {
        "findings": [],
        "missing_evidence": [],
        "worktree_revision": 7,
    }
    passed_worker_result = {
        "status": "completed",
        "summary": "contradictory review",
        "changed_files": [],
        "findings": [],
        "evidence_refs": [],
        "missing_evidence": [],
        "verification": [],
        "verdict": {**base, "status": "passed"},
    }
    return {
        "worker_top_level_critical_mismatch_rejected": worker_rejects_result(
            "worker result findings do not match verdict",
            {
                **passed_worker_result,
                "findings": [{"severity": "critical", "summary": "hidden contradiction"}],
            },
        ),
        "worker_top_level_missing_evidence_mismatch_rejected": worker_rejects_result(
            "worker result missing_evidence does not match verdict",
            {**passed_worker_result, "missing_evidence": ["required acceptance output"]},
        ),
        "critical_passed_rejected": rejected(
            "passed verdict conflicts with critical findings",
            lambda: validate_verdict(
                {
                    **base,
                    "status": "passed",
                    "findings": [{"severity": "critical", "summary": "completion is false"}],
                },
                "task_review",
                7,
            ),
        ),
        "missing_evidence_passed_rejected": rejected(
            "passed verdict conflicts with missing evidence",
            lambda: validate_verdict(
                {**base, "status": "passed", "missing_evidence": ["acceptance log"]},
                "verification",
                7,
            ),
        ),
        "empty_changes_requested_rejected": rejected(
            "changes_requested verdict requires an actionable finding",
            lambda: validate_verdict(
                {**base, "status": "changes_requested"}, "final_review", 7
            ),
        ),
        "ownerless_blocked_rejected": rejected(
            "blocked verdict requires owner and resume_condition",
            lambda: validate_verdict({**base, "status": "blocked"}, "task_review", 7),
        ),
        "unbounded_inconclusive_rejected": rejected(
            "inconclusive verdict requires next_evidence_action",
            lambda: validate_verdict(
                {**base, "status": "inconclusive"}, "verification", 7
            ),
        ),
        "stale_revision_rejected": rejected(
            "verdict revision is stale",
            lambda: validate_verdict({**base, "status": "passed"}, "task_review", 8),
        ),
        "write_role_verdict_rejected": rejected(
            "role implementation cannot issue a verdict",
            lambda: validate_verdict({**base, "status": "passed"}, "implementation", 7),
        ),
        "valid_passed_accepted": validate_verdict(
            {**base, "status": "passed"}, "task_review", 7
        )["status"]
        == "passed",
        "valid_changes_requested_accepted": validate_verdict(
            {
                **base,
                "status": "changes_requested",
                "findings": [{"severity": "major", "action": "add the missing assertion"}],
            },
            "final_review",
            7,
        )["status"]
        == "changes_requested",
        "valid_blocked_accepted": validate_verdict(
            {
                **base,
                "status": "blocked",
                "owner": "operator",
                "resume_condition": "provide the signed report",
            },
            "verification",
            7,
        )["status"]
        == "blocked",
        "valid_inconclusive_accepted": validate_verdict(
            {
                **base,
                "status": "inconclusive",
                "next_evidence_action": "run the bounded acceptance command",
            },
            "verification",
            7,
        )["status"]
        == "inconclusive",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", choices=("verdicts", "scope", "completion"))
    args = parser.parse_args()

    if args.case == "verdicts":
        checks = verdict_cases()
    elif args.case == "scope":
        checks = {"scope_fault_cases_pending_task_6": False}
    elif args.case == "completion":
        checks = {"completion_fault_cases_pending_task_7": False}
    else:
        checks = {
            **verdict_cases(),
            "scope_fault_cases_pending_task_6": False,
            "completion_fault_cases_pending_task_7": False,
        }
    failures = [name for name, passed in checks.items() if not passed]
    print(json.dumps({"passed": not failures, "checks": checks, "failures": failures}, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
