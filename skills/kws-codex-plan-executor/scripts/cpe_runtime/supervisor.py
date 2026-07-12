from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from .autonomy import AutonomyDecision


_TASK_STATUSES = frozenset(
    {
        "pending",
        "ready",
        "scouting",
        "implementing",
        "reviewing",
        "verifying",
        "repairing",
        "waiting_user",
        "waiting_external",
        "completed",
        "blocked",
        "failed",
    }
)
_RUN_LIFECYCLES = frozenset(
    {
        "created",
        "ready",
        "running",
        "waiting_user",
        "waiting_external",
        "blocked",
        "failed",
        "completed",
    }
)


@dataclass(frozen=True)
class SupervisionAction:
    kind: str
    run_id: str
    task_id: str
    attempt_id: str | None = None
    preserve_attempt: bool = False


@dataclass(frozen=True)
class NotificationRequest:
    decision_id: str
    dedupe_key: str
    kind: str
    affected_tasks: tuple[str, ...]


@dataclass(frozen=True)
class SupervisionResult:
    run_id: str
    actions: tuple[SupervisionAction, ...]
    decisions: tuple[AutonomyDecision, ...]
    notifications: tuple[NotificationRequest, ...]


def _task_attempt_id(state: Mapping[str, object], task_id: str) -> str:
    attempts = state.get("attempts")
    if not isinstance(attempts, list):
        raise ValueError("invalid_attempt_state")
    active = [
        item
        for item in attempts
        if isinstance(item, dict)
        and item.get("task_id") == task_id
        and item.get("status") == "started"
        and isinstance(item.get("attempt_id"), str)
        and item["attempt_id"]
    ]
    if len(active) != 1:
        raise ValueError("external_wait_attempt_ambiguous")
    return str(active[0]["attempt_id"])


def _known_ids(items: object, *fields: str) -> set[str]:
    if not isinstance(items, list):
        raise ValueError("invalid_supervisor_state")
    known: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("invalid_supervisor_state")
        for field in fields:
            value = item.get(field)
            if isinstance(value, str) and value:
                known.add(value)
    return known


def supervise(
    state: Mapping[str, object],
    *,
    recovered_external_waits: tuple[tuple[str, str], ...] = (),
    decisions: Iterable[AutonomyDecision] = (),
) -> SupervisionResult:
    if not isinstance(state, Mapping) or state.get("schema_version") != "4":
        raise ValueError("unsupported_run_schema")
    run_id = state.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("run_id_required")
    tasks = state.get("tasks")
    if not isinstance(tasks, dict):
        raise ValueError("invalid_task_state")
    if state.get("lifecycle") not in _RUN_LIFECYCLES:
        raise ValueError("invalid_run_lifecycle")
    if state["lifecycle"] in {"completed", "failed"}:
        return SupervisionResult(run_id, (), (), ())
    if any(not isinstance(task_id, str) or not task_id for task_id in tasks):
        raise ValueError("invalid_task_state")
    if not isinstance(recovered_external_waits, tuple) or any(
        not isinstance(item, tuple)
        or len(item) != 2
        or not isinstance(item[0], str)
        or not item[0]
        or not isinstance(item[1], str)
        or not item[1]
        for item in recovered_external_waits
    ):
        raise ValueError("invalid_external_recovery_reason")
    if len({task_id for task_id, _reason in recovered_external_waits}) != len(
        recovered_external_waits
    ):
        raise ValueError("duplicate_external_recovery_task")
    recovered = dict(recovered_external_waits)
    if any(
        reason not in {"provider_transient", "quota_transient"}
        for reason in recovered.values()
    ):
        raise ValueError("invalid_external_recovery_reason")
    if any(
        task_id not in tasks
        or not isinstance(tasks[task_id], dict)
        or tasks[task_id].get("status") != "waiting_external"
        for task_id in recovered
    ):
        raise ValueError("invalid_external_recovery_task")

    completed = {
        task_id
        for task_id, task in tasks.items()
        if isinstance(task, dict) and task.get("status") == "completed"
    }
    actions: list[SupervisionAction] = []
    for task_id in sorted(tasks):
        task = tasks[task_id]
        if not isinstance(task_id, str) or not task_id or not isinstance(task, dict):
            raise ValueError("invalid_task_state")
        status = task.get("status")
        if status not in _TASK_STATUSES:
            raise ValueError("invalid_task_status")
        dependencies = task.get("dependencies", [])
        if not isinstance(dependencies, list) or any(
            not isinstance(dependency, str) or dependency not in tasks
            for dependency in dependencies
        ):
            raise ValueError("invalid_task_dependencies")
        dependencies_complete = all(dependency in completed for dependency in dependencies)
        if status in {"pending", "ready"} and dependencies_complete:
            actions.append(SupervisionAction("schedule_task", run_id, task_id))
        elif status == "waiting_external" and task_id in recovered:
            actions.append(
                SupervisionAction(
                    "resume_external",
                    run_id,
                    task_id,
                    attempt_id=_task_attempt_id(state, task_id),
                    preserve_attempt=True,
                )
            )

    existing_decision_ids = _known_ids(state.get("decisions", []), "decision_id")
    existing_notification_ids = _known_ids(
        state.get("notifications", []), "decision_id", "dedupe_key"
    )
    new_decisions: list[AutonomyDecision] = []
    notifications: list[NotificationRequest] = []
    seen: set[str] = set()
    for decision in decisions:
        if not isinstance(decision, AutonomyDecision):
            raise TypeError("autonomy_decision_required")
        if decision.decision_id in seen:
            continue
        seen.add(decision.decision_id)
        if decision.decision_id not in existing_decision_ids:
            new_decisions.append(decision)
        if decision.decision_id not in existing_notification_ids:
            notifications.append(
                NotificationRequest(
                    decision_id=decision.decision_id,
                    dedupe_key=decision.decision_id,
                    kind=(
                        "user_decision_required"
                        if decision.user_input_required
                        else "autonomy_decision"
                    ),
                    affected_tasks=decision.affected_tasks,
                )
            )
    return SupervisionResult(
        run_id=run_id,
        actions=tuple(actions),
        decisions=tuple(new_decisions),
        notifications=tuple(notifications),
    )
