"""AgentLens evaluator package (spec §S1.6.16, §S1.7.3).

Public surface:

* :func:`evaluate` — run all 12 deterministic checks and write ``eval.json``.
* :class:`Failure`, :class:`FailureCategory` — failure taxonomy (spec §5.13).
* :class:`EvalContext`, :class:`CheckResult`, :data:`REQUIRED_CHECKS` —
  the check primitives (spec §5.14).
"""
from .checks import REQUIRED_CHECKS, CheckFn, CheckResult, EvalContext
from .engine import evaluate, load_context, resolve_status
from .failures import Failure, FailureCategory

__all__ = [
    "CheckFn",
    "CheckResult",
    "EvalContext",
    "Failure",
    "FailureCategory",
    "REQUIRED_CHECKS",
    "evaluate",
    "load_context",
    "resolve_status",
]
