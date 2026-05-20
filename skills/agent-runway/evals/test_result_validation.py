from __future__ import annotations

import pytest

from agentrunway.method_audit import MethodAuditError, verify_method_audit
from agentrunway.result_validation import (
    ResultValidationError,
    validate_review_result,
    validate_verification_result,
    validate_worker_result,
)


def test_worker_result_requires_schema_and_method_audit() -> None:
    with pytest.raises(ResultValidationError):
        validate_worker_result({"schema": "wrong"})


def test_valid_worker_result_round_trips() -> None:
    result = validate_worker_result(
        {
            "schema": "agentrunway.worker_result.v1",
            "worker_id": "w1",
            "task_id": "task_001",
            "role": "implementer",
            "status": "success",
            "changed_files": ["src/a.py"],
            "summary": "done",
            "method_audit": {"superpowers_used": True, "tdd_red": "failed", "tdd_green": "passed"},
        }
    )
    assert result["task_id"] == "task_001"


def test_method_audit_requires_superpowers_and_tdd_for_code_changes() -> None:
    with pytest.raises(MethodAuditError):
        verify_method_audit({"superpowers_used": True}, code_change=True)
    verify_method_audit({"superpowers_used": True, "tdd_red": "failed", "tdd_green": "passed"}, code_change=True)


def test_review_result_rejects_approved_with_findings() -> None:
    payload = {
        "schema": "agentrunway.review_result.v1",
        "worker_id": "reviewer-1",
        "task_id": "task_001",
        "reviewed_worker_id": "implementer-1",
        "status": "approved",
        "checks": [],
        "findings": [{"severity": "medium", "body": "issue"}],
        "method_audit": {"superpowers_used": True},
    }
    with pytest.raises(ResultValidationError, match="approved review cannot include findings"):
        validate_review_result(payload)


def test_verification_result_requires_passed_failed_or_blocked() -> None:
    payload = {
        "schema": "agentrunway.verification_result.v1",
        "worker_id": "verifier-1",
        "task_id": "task_001",
        "status": "passed",
        "checks": [{"command": "pytest", "status": "passed"}],
        "method_audit": {"superpowers_used": True},
    }
    assert validate_verification_result(payload)["status"] == "passed"
