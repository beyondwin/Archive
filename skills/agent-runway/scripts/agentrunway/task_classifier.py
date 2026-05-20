from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

from .models import TaskSpec


TaskClassName = Literal["independent", "soft_overlap", "shared_core", "barrier", "blocked_dependent"]
ReviewMode = Literal["diff", "full_tree"]

_SHARED_CORE_PATHS = (
    "skills/agent-runway/scripts/agentrunway/runner.py",
    "skills/agent-runway/scripts/agentrunway/scheduler.py",
    "skills/agent-runway/scripts/agentrunway/checkpoint_scheduler.py",
    "skills/agent-runway/scripts/agentrunway/durable_projection.py",
    "skills/agent-runway/scripts/agentrunway/resume_executor.py",
    "skills/agent-runway/scripts/agentrunway/resume_planner.py",
    "skills/agent-runway/scripts/agentrunway/gate_runner.py",
    "skills/agent-runway/scripts/agentrunway/db.py",
    "skills/agent-runway/scripts/agentrunway/workflow_store.py",
)
_SHARED_CORE_PREFIXES = (
    "skills/agent-runway/scripts/agentrunway/adapters/",
)
_FULL_TREE_PATH_MARKERS = (
    "migration",
    "migrations/",
    "schema",
    "generated/",
    ".generated",
)


@dataclass(frozen=True)
class TaskExecutionClass:
    task_id: str
    execution_class: TaskClassName
    review_mode: ReviewMode
    serial_required: bool
    reasons: tuple[str, ...]
    blocked_dependencies: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _has_broad_claim(task: TaskSpec) -> bool:
    return any(any(char in claim.path for char in "*?[") or claim.path.endswith("/**") for claim in task.file_claims)


def _touches_shared_core(task: TaskSpec) -> bool:
    return any(
        claim.path in _SHARED_CORE_PATHS or any(claim.path.startswith(prefix) for prefix in _SHARED_CORE_PREFIXES)
        for claim in task.file_claims
    )


def _touches_schema_or_generated_surface(task: TaskSpec) -> bool:
    for claim in task.file_claims:
        normalized = claim.path.replace("\\", "/").lower()
        if any(marker in normalized for marker in _FULL_TREE_PATH_MARKERS):
            return True
    return False


def _has_shared_append_only(task: TaskSpec) -> bool:
    return bool(task.file_claims) and all(claim.mode in {"shared_append", "read_only"} for claim in task.file_claims)


def classify_task(task: TaskSpec, *, blocked_dependencies: set[str] | None = None) -> TaskExecutionClass:
    blocked = tuple(sorted(blocked_dependencies or set()))
    if blocked:
        return TaskExecutionClass(
            task_id=task.task_id,
            execution_class="blocked_dependent",
            review_mode="full_tree",
            serial_required=True,
            reasons=("blocked_dependency",),
            blocked_dependencies=blocked,
        )
    if task.serial or task.risk == "high" or _has_broad_claim(task) or _touches_schema_or_generated_surface(task):
        reasons = []
        if task.serial:
            reasons.append("task_serial")
        if task.risk == "high":
            reasons.append("high_risk")
        if _has_broad_claim(task):
            reasons.append("broad_claim")
        if _touches_schema_or_generated_surface(task):
            reasons.append("schema_or_generated_surface")
        return TaskExecutionClass(
            task_id=task.task_id,
            execution_class="barrier",
            review_mode="full_tree",
            serial_required=True,
            reasons=tuple(reasons),
        )
    if _touches_shared_core(task):
        return TaskExecutionClass(
            task_id=task.task_id,
            execution_class="shared_core",
            review_mode="full_tree",
            serial_required=True,
            reasons=("shared_core_path",),
        )
    if _has_shared_append_only(task):
        return TaskExecutionClass(
            task_id=task.task_id,
            execution_class="soft_overlap",
            review_mode="diff",
            serial_required=False,
            reasons=("shared_append_or_read_only",),
        )
    return TaskExecutionClass(
        task_id=task.task_id,
        execution_class="independent",
        review_mode="diff",
        serial_required=False,
        reasons=("owned_files", "low_or_medium_risk"),
    )
