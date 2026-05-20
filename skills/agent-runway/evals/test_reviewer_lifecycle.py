from __future__ import annotations

from pathlib import Path

from agentrunway.models import TaskSpec
from agentrunway.packetizer import materialize_role_prompt
from agentrunway.result_validation import validate_review_result


def _task() -> TaskSpec:
    return TaskSpec(
        task_id="task_001",
        title="Task",
        risk="low",
        phase="implementation",
        dependencies=(),
        spec_refs=(),
        file_claims=(),
        acceptance_commands=(),
    )


def test_review_validation_accepts_needs_context_with_review_mode() -> None:
    payload = {
        "schema": "agentrunway.review_result.v1",
        "worker_id": "task_001-reviewer-001",
        "task_id": "task_001",
        "reviewed_worker_id": "task_001-implementer-001",
        "status": "needs_context",
        "review_mode": "diff",
        "checks": [{"name": "diff visibility", "status": "blocked"}],
        "findings": [{"severity": "major", "body": "Need full-tree context."}],
        "method_audit": {"superpowers_used": True},
    }

    assert validate_review_result(payload)["status"] == "needs_context"


def test_reviewer_prompt_declares_review_mode_and_needs_context(tmp_path: Path) -> None:
    path = materialize_role_prompt(
        role="reviewer",
        task=_task(),
        worker_id="task_001-reviewer-001",
        packet_path=tmp_path / "packet.json",
        output_path=tmp_path / "review.json",
        prompt_dir=tmp_path / "prompts",
        context={"review_mode": "diff", "reviewed_worker_id": "task_001-implementer-001"},
    )
    text = path.read_text(encoding="utf-8")

    assert '"review_mode": "diff"' in text
    assert "needs_context" in text
