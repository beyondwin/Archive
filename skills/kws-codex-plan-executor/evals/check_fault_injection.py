#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from cpe_runtime.attempt_controller import validate_verdict
from cpe_runtime.worker import WorkerError


def rejected(message: str, fn) -> bool:
    try:
        fn()
    except WorkerError as exc:
        return str(exc) == message
    return False


def verdict_cases() -> dict[str, bool]:
    base = {
        "findings": [],
        "missing_evidence": [],
        "worktree_revision": 7,
    }
    return {
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
