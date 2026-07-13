"""Pure vNext lifecycle decisions.

This module deliberately contains no filesystem, subprocess, provider, or event
append logic.  It turns an immutable state/outcome pair into one immutable
command for :class:`PhaseExecutor`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Callable, Mapping


class IllegalTransition(ValueError):
    """The state/outcome pair is not present in the transition table."""


def _frozen_mapping(value: Mapping[str, object] | None) -> Mapping[str, object]:
    return MappingProxyType(dict(value or {}))


def _frozen_refs(
    refs: tuple[Mapping[str, str], ...] | list[Mapping[str, str]] | None,
) -> tuple[Mapping[str, str], ...]:
    return tuple(MappingProxyType(dict(ref)) for ref in (refs or ()))


@dataclass(frozen=True)
class RunState:
    phase: str
    task_id: str | None = None
    resume_command: str | None = None
    details: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "details", _frozen_mapping(self.details))


@dataclass(frozen=True)
class TypedOutcome:
    kind: str
    task_id: str | None = None
    evidence_refs: tuple[Mapping[str, str], ...] = ()
    details: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_refs", _frozen_refs(self.evidence_refs))
        object.__setattr__(self, "details", _frozen_mapping(self.details))


@dataclass(frozen=True)
class KernelCommand:
    kind: str
    task_id: str | None = None
    details: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "details", _frozen_mapping(self.details))


CommandFactory = Callable[[RunState, TypedOutcome], KernelCommand]


def _command(kind: str) -> CommandFactory:
    def factory(state: RunState, outcome: TypedOutcome) -> KernelCommand:
        if (
            state.task_id is not None
            and outcome.task_id is not None
            and state.task_id != outcome.task_id
        ):
            raise IllegalTransition("outcome_task_mismatch")
        return KernelCommand(kind, state.task_id or outcome.task_id, outcome.details)

    return factory


TRANSITIONS: Mapping[tuple[str, str], CommandFactory] = MappingProxyType(
    {
        ("ready", "start"): _command("implementation"),
        ("implemented", "pass"): _command("acceptance"),
        ("accepted", "pass"): _command("review"),
        ("reviewed", "pass"): _command("verify"),
        ("verified", "pass"): _command("plan_checkpoint"),
        ("plan_complete", "pass"): _command("global_integration"),
        ("integration_complete", "pass"): _command("complete_program"),
        ("repairing", "pass"): _command("review"),
        ("ready", "dispatch"): _command("implementation"),
        ("implemented", "dispatch"): _command("acceptance"),
        ("reviewed", "dispatch"): _command("verify"),
        ("repairing", "dispatch"): _command("repair"),
        ("completed", "dispatch"): _command("repository_checks"),
        ("verdict", "passed"): _command("continue"),
        ("verdict", "changes_requested"): _command("repair"),
        ("verdict", "blocked"): _command("block"),
        ("verdict", "inconclusive"): _command("wait"),
    }
)


_REPAIRABLE_PHASES = frozenset(
    {"implemented", "accepted", "reviewed", "verified", "repairing"}
)
_WAITABLE_PHASES = frozenset(
    {"ready", "implemented", "accepted", "reviewed", "verified", "repairing"}
)
_RESUME_COMMANDS = frozenset(
    {"implementation", "acceptance", "review", "verify", "repair"}
)


def decide(state: RunState, outcome: TypedOutcome) -> KernelCommand:
    """Return exactly one command or fail closed for an unlisted transition."""

    if not isinstance(state, RunState) or not isinstance(outcome, TypedOutcome):
        raise TypeError("transition_inputs_must_be_typed")
    if (
        state.task_id is not None
        and outcome.task_id is not None
        and state.task_id != outcome.task_id
    ):
        raise IllegalTransition("outcome_task_mismatch")
    if state.phase in {"waiting_user", "waiting_external"} and outcome.kind == "resume":
        command = state.resume_command or "implementation"
        if command not in _RESUME_COMMANDS:
            raise IllegalTransition("resume_command_invalid")
        return KernelCommand(command, state.task_id, outcome.details)
    if outcome.kind == "structural_redesign" and state.phase not in {
        "completed",
        "blocked",
    }:
        return KernelCommand("structural_redesign", state.task_id, outcome.details)
    if outcome.kind in {"changes_requested", "fail"} and state.phase in _REPAIRABLE_PHASES:
        return KernelCommand("repair", state.task_id, outcome.details)
    if outcome.kind == "blocked" and state.phase not in {"completed", "blocked"}:
        return KernelCommand("block", state.task_id, outcome.details)
    if outcome.kind in {"wait_user", "wait_external"} and state.phase in _WAITABLE_PHASES:
        return KernelCommand(outcome.kind, state.task_id, outcome.details)
    if outcome.kind == "external_call_required" and state.phase not in {
        "completed",
        "blocked",
    }:
        return KernelCommand("register_external_call", state.task_id, outcome.details)
    factory = TRANSITIONS.get((state.phase, outcome.kind))
    if factory is None:
        raise IllegalTransition(f"illegal_transition:{state.phase}:{outcome.kind}")
    return factory(state, outcome)
