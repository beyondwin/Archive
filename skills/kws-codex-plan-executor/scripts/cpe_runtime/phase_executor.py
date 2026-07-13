"""One-command execution boundary for the vNext runtime."""

from __future__ import annotations

from types import MappingProxyType
from typing import Callable, Mapping

from .transition_kernel import KernelCommand, TypedOutcome


PhaseHandler = Callable[[KernelCommand], TypedOutcome]


class PhaseExecutor:
    """Dispatch exactly one command and return exactly one typed outcome."""

    def __init__(self, handlers: Mapping[str, PhaseHandler]):
        self.handlers = MappingProxyType(dict(handlers))

    def execute(self, command: KernelCommand) -> TypedOutcome:
        if not isinstance(command, KernelCommand):
            raise TypeError("phase_command_must_be_typed")
        handler = self.handlers.get(command.kind)
        if handler is None:
            raise ValueError(f"phase_handler_missing:{command.kind}")
        outcome = handler(command)
        if not isinstance(outcome, TypedOutcome):
            raise TypeError("phase_handler_must_return_typed_outcome")
        if command.task_id != outcome.task_id:
            raise ValueError("phase_handler_outcome_task_mismatch")
        return outcome
