from __future__ import annotations

import pytest

from kao.file_claims import ClaimConflictError, validate_claims_compatible
from kao.models import FileClaim, TaskSpec
from kao.resource_locks import resource_conflicts
from kao.scheduler import schedule_waves


def task(
    task_id: str,
    *,
    deps: tuple[str, ...] = (),
    claims: tuple[FileClaim, ...] = (),
    resources: tuple[str, ...] = (),
    risk: str = "low",
    serial: bool = False,
) -> TaskSpec:
    return TaskSpec(
        task_id=task_id,
        title=task_id,
        risk=risk,  # type: ignore[arg-type]
        phase="implementation",
        dependencies=deps,
        spec_refs=(),
        file_claims=claims,
        acceptance_commands=("pytest",),
        resource_keys=resources,
        serial=serial,
    )


def test_owned_claims_conflict_but_read_only_does_not() -> None:
    first = task("task_001", claims=(FileClaim("src/a.py", "owned"),))
    second = task("task_002", claims=(FileClaim("src/a.py", "read_only"),))
    validate_claims_compatible([first, second])
    conflicting = task("task_003", claims=(FileClaim("src/a.py", "owned"),))
    with pytest.raises(ClaimConflictError):
        validate_claims_compatible([first, conflicting])


def test_shared_append_requires_same_base_reference() -> None:
    left = FileClaim("CHANGELOG.md", "shared_append")
    right = FileClaim("CHANGELOG.md", "shared_append")
    validate_claims_compatible([task("a", claims=(left,)), task("b", claims=(right,))])


def test_resource_locks_conflict_by_key() -> None:
    conflicts = resource_conflicts([task("a", resources=("db:migration",)), task("b", resources=("db:migration",))])
    assert conflicts == {"db:migration": ["a", "b"]}


def test_scheduler_groups_independent_tasks_and_orders_dependencies_by_risk() -> None:
    waves = schedule_waves(
        [
            task("task_001", risk="low"),
            task("task_002", risk="high"),
            task("task_003", deps=("task_001",)),
        ]
    )
    assert waves[0] == ("task_002", "task_001")
    assert waves[1] == ("task_003",)


def test_scheduler_rejects_cycles() -> None:
    with pytest.raises(ValueError, match="cycle"):
        schedule_waves([task("a", deps=("b",)), task("b", deps=("a",))])
