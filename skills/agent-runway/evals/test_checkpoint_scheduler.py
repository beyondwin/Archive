from __future__ import annotations

from agentrunway.models import FileClaim, TaskSpec
from agentrunway.scheduler import ready_tasks_after_checkpoints, schedule_safe_wave


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


def test_ready_tasks_require_dependency_checkpoints_not_only_completed_tasks() -> None:
    first = task("task_001")
    dependent = task("task_002", deps=("task_001",))

    ready = ready_tasks_after_checkpoints(
        [first, dependent],
        completed_checkpoints=set(),
        completed_tasks={"task_001"},
    )

    assert ready == []


def test_ready_tasks_excludes_already_completed_tasks_and_orders_by_risk() -> None:
    low = task("task_001", risk="low")
    high = task("task_002", risk="high")
    dependent = task("task_003", deps=("task_001",))

    ready = ready_tasks_after_checkpoints(
        [low, high, dependent],
        completed_checkpoints={"task_001"},
        completed_tasks={"task_001"},
    )

    assert [item.task_id for item in ready] == ["task_002", "task_003"]


def test_schedule_safe_wave_allows_disjoint_low_risk_tasks() -> None:
    ready = [
        task("task_002", claims=(FileClaim("src/b.py", "owned"),)),
        task("task_001", claims=(FileClaim("src/a.py", "owned"),)),
    ]

    wave = schedule_safe_wave(ready)

    assert [item.task_id for item in wave] == ["task_001", "task_002"]


def test_schedule_safe_wave_serializes_file_claim_conflicts_and_resource_conflicts() -> None:
    ready = [
        task("task_001", claims=(FileClaim("src/a.py", "owned"),)),
        task("task_002", claims=(FileClaim("src/a.py", "owned"),)),
        task("task_003", resources=("db:migration",)),
        task("task_004", resources=("db:migration",)),
    ]

    wave = schedule_safe_wave(ready)

    assert [item.task_id for item in wave] == ["task_001", "task_003"]


def test_schedule_safe_wave_serializes_conservative_tasks() -> None:
    assert [item.task_id for item in schedule_safe_wave([task("task_001", serial=True), task("task_002")])] == [
        "task_001"
    ]
    assert [item.task_id for item in schedule_safe_wave([task("task_001", risk="high"), task("task_002")])] == [
        "task_001"
    ]
    assert [
        item.task_id
        for item in schedule_safe_wave([task("task_001", claims=(FileClaim("src/**", "owned"),)), task("task_002")])
    ] == ["task_001"]
