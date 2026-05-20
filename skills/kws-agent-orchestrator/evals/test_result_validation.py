from __future__ import annotations

import pytest

from kao.method_audit import MethodAuditError, verify_method_audit
from kao.result_validation import ResultValidationError, validate_worker_result


def test_worker_result_requires_schema_and_method_audit() -> None:
    with pytest.raises(ResultValidationError):
        validate_worker_result({"schema": "wrong"})


def test_valid_worker_result_round_trips() -> None:
    result = validate_worker_result(
        {
            "schema": "kws.kao.worker_result.v1",
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
