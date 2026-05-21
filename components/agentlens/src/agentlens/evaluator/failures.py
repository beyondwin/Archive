"""Failure taxonomy for the AgentLens evaluator (spec §4.5, §5.13).

Defines the 19-entry :class:`FailureCategory` enum and the structured
:class:`Failure` record emitted by every check. The full categorisation
is shared with ``eval.schema.json`` — adding a new category requires a
schema bump.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal


class FailureCategory(str, Enum):
    """Closed enumeration of evaluator failure codes (spec §4.5)."""

    MISSING_FINAL = "MISSING_FINAL"
    INVALID_RUN_SCHEMA = "INVALID_RUN_SCHEMA"
    INVALID_EVENT_SCHEMA = "INVALID_EVENT_SCHEMA"
    INVALID_FINAL_SCHEMA = "INVALID_FINAL_SCHEMA"
    INVALID_MANIFEST_SCHEMA = "INVALID_MANIFEST_SCHEMA"
    MISSING_VERIFICATION_EVIDENCE = "MISSING_VERIFICATION_EVIDENCE"
    UNACKNOWLEDGED_FAILED_COMMAND = "UNACKNOWLEDGED_FAILED_COMMAND"
    SUCCESS_WITH_RESIDUAL_RISK = "SUCCESS_WITH_RESIDUAL_RISK"
    ARTIFACT_HASH_MISMATCH = "ARTIFACT_HASH_MISMATCH"
    MANIFEST_NOT_SEALED = "MANIFEST_NOT_SEALED"
    RECORDING_INCOMPLETE = "RECORDING_INCOMPLETE"
    EVALUATOR_ERROR = "EVALUATOR_ERROR"
    COMMAND_TIMEOUT = "COMMAND_TIMEOUT"
    ENVIRONMENT_BLOCKER = "ENVIRONMENT_BLOCKER"
    DIFF_SCOPE_UNKNOWN = "DIFF_SCOPE_UNKNOWN"
    CHANGED_FILES_MISSING = "CHANGED_FILES_MISSING"
    AGENT_REPORTED_GAP = "AGENT_REPORTED_GAP"
    USER_CORRECTION = "USER_CORRECTION"
    UNKNOWN = "UNKNOWN"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


Severity = Literal["low", "medium", "high", "critical"]
Source = Literal["agent_reported", "evaluator", "user_reported", "imported"]
BlameScope = Literal["agent", "project", "environment", "user", "unknown"]
Recoverability = Literal[
    "informational", "retry", "rerun_or_fix", "needs_user", "non_recoverable"
]


@dataclass(frozen=True)
class Failure:
    """Structured failure entry conforming to ``eval.schema.json``.

    All Literal fields mirror the enum constraints in the schema.
    ``confidence`` is auto-rounded to two decimal places in ``__post_init__``.
    """

    category: FailureCategory
    severity: Severity
    source: Source
    blame_scope: BlameScope
    recoverability: Recoverability
    confidence: float  # [0, 1], rounded to 2 dp
    summary: str
    evidence: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        # Clamp + round confidence to 2 dp. Frozen dataclass requires
        # object.__setattr__.
        raw = float(self.confidence)
        if raw < 0.0:
            raw = 0.0
        elif raw > 1.0:
            raw = 1.0
        object.__setattr__(self, "confidence", round(raw, 2))
        # Normalise evidence to a tuple of str for hashability + schema fit.
        if not isinstance(self.evidence, tuple):
            object.__setattr__(self, "evidence", tuple(self.evidence))

    def to_dict(self) -> dict[str, Any]:
        """Serialise to the schema-shaped dict consumed by eval.json."""
        cat = self.category
        cat_value = cat.value if isinstance(cat, FailureCategory) else str(cat)
        return {
            "category": cat_value,
            "severity": self.severity,
            "source": self.source,
            "blame_scope": self.blame_scope,
            "recoverability": self.recoverability,
            "confidence": self.confidence,
            "summary": self.summary,
            "evidence": list(self.evidence),
        }


__all__ = [
    "BlameScope",
    "Failure",
    "FailureCategory",
    "Recoverability",
    "Severity",
    "Source",
]
