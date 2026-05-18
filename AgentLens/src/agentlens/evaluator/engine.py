"""Evaluator engine — v0 stub (spec §S1.6.16, §S1.7.3).

Implements two required checks:

* ``schema_valid`` — re-validates ``run.json``, every line of
  ``events.jsonl``, and ``final.json`` (if present) against the v1 schemas.
* ``final_present`` — asserts that ``final.json`` exists.

The result is written to ``run_dir/eval.json`` and matches
``agentlens.eval.v1``. Status resolution follows the spec table:

* evaluator internal raise        -> ``"error"``
* ``final.json`` missing          -> ``"incomplete"``
* ``schema_valid`` failed         -> ``"failed"``
* any required check failed       -> ``"failed"``
* all required checks passed      -> ``"passed"``

The full failure taxonomy lands with task_6; this module emits only the
minimal failure entries needed for ``eval.schema.json`` to validate.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from agentlens.constants import SCHEMA_EVAL_V1
from agentlens.schema.validate import (
    EventLineError,
    SchemaError,
    validate_doc,
    validate_event_line,
)
from agentlens.store.writer import atomic_write_json
from agentlens.time import utc_now_iso


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Failure:
    """Minimal failure entry conforming to ``eval.schema.json``.

    The full FailureCategory taxonomy lands with task_6; v0 stub uses a
    small subset of the enum that's sufficient for schema_valid /
    final_present.
    """

    category: str
    severity: str
    source: str
    blame_scope: str
    recoverability: str
    confidence: float
    summary: str
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "severity": self.severity,
            "source": self.source,
            "blame_scope": self.blame_scope,
            "recoverability": self.recoverability,
            "confidence": self.confidence,
            "summary": self.summary,
            "evidence": list(self.evidence),
        }


@dataclass
class CheckResult:
    name: str
    status: str  # "passed" | "failed" | "skipped"
    message: str | None = None
    failures: list[Failure] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"name": self.name, "status": self.status}
        if self.message is not None:
            out["message"] = self.message
        return out


@dataclass
class EvalContext:
    run_dir: Path
    run: dict[str, Any]
    events_lines: list[str]
    final: dict[str, Any] | None


# ---------------------------------------------------------------------------
# Context loading
# ---------------------------------------------------------------------------


def _load_context(run_dir: Path) -> EvalContext:
    run_path = run_dir / "run.json"
    if not run_path.is_file():
        raise FileNotFoundError(f"run.json not found under {run_dir}")
    run = json.loads(run_path.read_text(encoding="utf-8"))

    events_path = run_dir / "events.jsonl"
    if events_path.is_file():
        events_lines = events_path.read_text(encoding="utf-8").splitlines()
    else:
        events_lines = []

    final_path = run_dir / "final.json"
    final: dict[str, Any] | None
    if final_path.is_file():
        try:
            final = json.loads(final_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            final = None
    else:
        final = None

    return EvalContext(
        run_dir=run_dir,
        run=run,
        events_lines=events_lines,
        final=final,
    )


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def _failure(
    *,
    category: str,
    summary: str,
    evidence: list[str] | None = None,
    severity: str = "medium",
    recoverability: str = "rerun_or_fix",
) -> Failure:
    return Failure(
        category=category,
        severity=severity,
        source="evaluator",
        blame_scope="agent",
        recoverability=recoverability,
        confidence=1.0,
        summary=summary,
        evidence=list(evidence or []),
    )


def check_schema_valid(ctx: EvalContext) -> CheckResult:
    """Re-validate run.json, every event line, and final.json (if present)."""
    failures: list[Failure] = []
    messages: list[str] = []

    try:
        validate_doc(ctx.run, schema_name="run")
    except SchemaError as exc:
        failures.append(
            _failure(
                category="INVALID_RUN_SCHEMA",
                summary=f"run.json failed schema validation: {exc}",
                evidence=list(exc.errors)[:5],
                severity="high",
            )
        )
        messages.append(f"run.json: {exc}")

    for idx, line in enumerate(ctx.events_lines, start=1):
        if not line.strip():
            continue
        try:
            validate_event_line(line)
        except EventLineError as exc:
            failures.append(
                _failure(
                    category="INVALID_EVENT_SCHEMA",
                    summary=f"events.jsonl line {idx} failed: {exc}",
                    evidence=list(exc.errors)[:5],
                    severity="high",
                )
            )
            messages.append(f"events.jsonl[{idx}]: {exc}")

    if ctx.final is not None:
        try:
            validate_doc(ctx.final, schema_name="final")
        except SchemaError as exc:
            failures.append(
                _failure(
                    category="INVALID_FINAL_SCHEMA",
                    summary=f"final.json failed schema validation: {exc}",
                    evidence=list(exc.errors)[:5],
                    severity="high",
                )
            )
            messages.append(f"final.json: {exc}")

    status = "failed" if failures else "passed"
    return CheckResult(
        name="schema_valid",
        status=status,
        message="; ".join(messages) if messages else None,
        failures=failures,
    )


def check_final_present(ctx: EvalContext) -> CheckResult:
    if ctx.final is None:
        return CheckResult(
            name="final_present",
            status="failed",
            message="final.json not found",
            failures=[
                _failure(
                    category="MISSING_FINAL",
                    summary="final.json was not written before evaluation",
                    severity="high",
                    recoverability="rerun_or_fix",
                )
            ],
        )
    return CheckResult(name="final_present", status="passed")


REQUIRED_CHECKS: tuple[Callable[[EvalContext], CheckResult], ...] = (
    check_schema_valid,
    check_final_present,
)


# ---------------------------------------------------------------------------
# Status resolution
# ---------------------------------------------------------------------------


def resolve_status(ctx: EvalContext, results: list[CheckResult]) -> str:
    if ctx.final is None:
        return "incomplete"
    if any(r.status == "failed" for r in results):
        return "failed"
    return "passed"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _minimal_error_eval(run_dir: Path, message: str) -> dict[str, Any]:
    run_id = run_dir.name
    doc = {
        "schema": SCHEMA_EVAL_V1,
        "run_id": run_id,
        "evaluated_at": utc_now_iso(),
        "status": "error",
        "agent_outcome": "unknown",
        "checks": [],
        "failures": [
            _failure(
                category="EVALUATOR_ERROR",
                summary=f"evaluator failed to load context: {message}",
                severity="critical",
                recoverability="non_recoverable",
            ).to_dict()
        ],
    }
    return doc


def evaluate(run_dir: Path) -> dict[str, Any]:
    """Run the v0 evaluator stub against *run_dir* and write ``eval.json``."""
    run_dir = Path(run_dir)

    try:
        ctx = _load_context(run_dir)
    except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
        doc = _minimal_error_eval(run_dir, str(exc))
        atomic_write_json(run_dir / "eval.json", doc, redact=False)
        return doc

    results: list[CheckResult] = []
    failures: list[Failure] = []
    internal_error = False

    for fn in REQUIRED_CHECKS:
        try:
            res = fn(ctx)
        except Exception as exc:  # noqa: BLE001
            internal_error = True
            results.append(
                CheckResult(
                    name=getattr(fn, "__name__", "unknown").removeprefix("check_"),
                    status="failed",
                    message=f"evaluator internal error: {exc}",
                )
            )
            failures.append(
                _failure(
                    category="EVALUATOR_ERROR",
                    summary=f"evaluator check raised: {exc}",
                    severity="critical",
                    recoverability="non_recoverable",
                )
            )
            continue
        # Normalise check name: drop the "check_" prefix.
        res.name = res.name or getattr(fn, "__name__", "").removeprefix("check_")
        results.append(res)
        failures.extend(res.failures)

    status = "error" if internal_error else resolve_status(ctx, results)
    agent_outcome = (ctx.final or {}).get("agent_outcome", "unknown")

    sorted_results = sorted(results, key=lambda r: r.name)
    sorted_failures = sorted(failures, key=lambda f: (f.category, f.summary))

    doc: dict[str, Any] = {
        "schema": SCHEMA_EVAL_V1,
        "run_id": ctx.run.get("run_id", run_dir.name),
        "evaluated_at": utc_now_iso(),
        "status": status,
        "agent_outcome": agent_outcome,
        "checks": [r.to_dict() for r in sorted_results],
        "failures": [f.to_dict() for f in sorted_failures],
    }
    atomic_write_json(run_dir / "eval.json", doc, redact=False)
    return doc


__all__ = [
    "CheckResult",
    "EvalContext",
    "Failure",
    "REQUIRED_CHECKS",
    "check_final_present",
    "check_schema_valid",
    "evaluate",
    "resolve_status",
]
