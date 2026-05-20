from __future__ import annotations

from pathlib import Path

import pytest

from agentrunway.db import AgentRunwayDb
from agentrunway.models import FileClaim, TaskSpec
from agentrunway.packetizer import materialize_role_prompt
from agentrunway.result_validation import ResultValidationError
from agentrunway.supervisor import gate_review_result, gate_verification_result, next_worker_id


def _task() -> TaskSpec:
    return TaskSpec(
        task_id="task_001",
        title="Example",
        risk="low",
        phase="implementation",
        dependencies=(),
        spec_refs=("S1",),
        file_claims=(FileClaim(path="src/example.py", mode="owned"),),
        acceptance_commands=("python -m pytest",),
    )


def test_next_worker_id_counts_existing_role_attempts(tmp_path: Path) -> None:
    db = AgentRunwayDb.open(tmp_path / "state.sqlite")
    db.create_worker_attempt(
        worker_id="task_001-reviewer-001",
        task_id="task_001",
        role="reviewer",
        runtime="codex",
        model="gpt-5.5",
        reasoning_effort="high",
        attempt=1,
        worktree_path=str(tmp_path / "w1"),
        branch="b1",
        state="running",
        handle_json={},
    )

    assert next_worker_id(db=db, task_id="task_001", role="reviewer") == ("task_001-reviewer-002", 2)


def test_review_gate_rejects_approved_findings() -> None:
    with pytest.raises(ResultValidationError, match="approved review cannot include findings"):
        gate_review_result(
            {
                "schema": "agentrunway.review_result.v1",
                "worker_id": "task_001-reviewer-001",
                "task_id": "task_001",
                "reviewed_worker_id": "task_001-implementer-001",
                "status": "approved",
                "checks": [],
                "findings": [{"severity": "major", "body": "bug"}],
                "method_audit": {},
            }
        )


def test_verification_gate_accepts_passed_status() -> None:
    status = gate_verification_result(
        {
            "schema": "agentrunway.verification_result.v1",
            "worker_id": "task_001-verifier-001",
            "task_id": "task_001",
            "status": "passed",
            "checks": [{"command": "python -m pytest", "status": "passed"}],
            "method_audit": {},
        }
    )
    assert status == "passed"


def test_materialize_role_prompt_names_output_schema(tmp_path: Path) -> None:
    output_path = tmp_path / "review_result.json"
    prompt_path = materialize_role_prompt(
        role="reviewer",
        task=_task(),
        worker_id="task_001-reviewer-001",
        packet_path=tmp_path / "task_001.json",
        output_path=output_path,
        prompt_dir=tmp_path,
        context={
            "reviewed_worker_id": "task_001-implementer-001",
            "diff": "diff --git a/src/example.py b/src/example.py",
        },
    )

    text = prompt_path.read_text(encoding="utf-8")
    assert "agentrunway.review_result.v1" in text
    assert str(output_path) in text
    assert "task_001-implementer-001" in text
