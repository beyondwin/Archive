from __future__ import annotations

from agentrunway.models import FileClaim, TaskSpec
from agentrunway.task_classifier import TaskExecutionClass, classify_task


def _task(
    task_id: str = "task_001",
    *,
    risk: str = "low",
    claims: tuple[FileClaim, ...] = (FileClaim("src/a.py", "owned"),),
    resources: tuple[str, ...] = (),
    serial: bool = False,
) -> TaskSpec:
    return TaskSpec(
        task_id=task_id,
        title=task_id,
        risk=risk,  # type: ignore[arg-type]
        phase="implementation",
        dependencies=(),
        spec_refs=("S1",),
        file_claims=claims,
        acceptance_commands=("python -m pytest",),
        resource_keys=resources,
        serial=serial,
    )


def test_independent_owned_low_risk_task() -> None:
    result = classify_task(_task())

    assert isinstance(result, TaskExecutionClass)
    assert result.execution_class == "independent"
    assert result.review_mode == "diff"
    assert result.serial_required is False
    assert result.reasons == ("owned_files", "low_or_medium_risk")


def test_shared_core_runner_task_is_serial_full_tree() -> None:
    result = classify_task(
        _task(claims=(FileClaim("skills/agent-runway/scripts/agentrunway/runner.py", "owned"),))
    )

    assert result.execution_class == "shared_core"
    assert result.review_mode == "full_tree"
    assert result.serial_required is True
    assert "shared_core_path" in result.reasons


def test_adapter_control_flow_is_shared_core() -> None:
    result = classify_task(
        _task(claims=(FileClaim("skills/agent-runway/scripts/agentrunway/adapters/codex.py", "owned"),))
    )

    assert result.execution_class == "shared_core"
    assert result.review_mode == "full_tree"
    assert result.serial_required is True
    assert "shared_core_path" in result.reasons


def test_broad_claim_is_barrier() -> None:
    result = classify_task(_task(claims=(FileClaim("skills/agent-runway/scripts/agentrunway/**", "owned"),)))

    assert result.execution_class == "barrier"
    assert result.serial_required is True
    assert "broad_claim" in result.reasons


def test_schema_and_generated_surfaces_are_barriers() -> None:
    schema = classify_task(_task(claims=(FileClaim("migrations/001_add_table.sql", "owned"),)))
    generated = classify_task(_task(claims=(FileClaim("src/generated/client.py", "owned"),)))

    assert schema.execution_class == "barrier"
    assert schema.review_mode == "full_tree"
    assert "schema_or_generated_surface" in schema.reasons
    assert generated.execution_class == "barrier"
    assert generated.review_mode == "full_tree"
    assert "schema_or_generated_surface" in generated.reasons


def test_shared_append_is_soft_overlap() -> None:
    result = classify_task(_task(claims=(FileClaim("skills/agent-runway/README.md", "shared_append"),)))

    assert result.execution_class == "soft_overlap"
    assert result.review_mode == "diff"
    assert result.serial_required is False


def test_blocked_dependency_overrides_other_classes() -> None:
    result = classify_task(_task(), blocked_dependencies={"task_000"})

    assert result.execution_class == "blocked_dependent"
    assert result.serial_required is True
    assert result.blocked_dependencies == ("task_000",)
