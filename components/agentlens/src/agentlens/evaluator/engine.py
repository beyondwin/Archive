"""Evaluator engine (spec §5.15, §6.3).

Loads the four canonical run-tree JSON documents, dispatches the 12
:data:`agentlens.evaluator.checks.REQUIRED_CHECKS` in alphabetical order
by ``__name__``, aggregates per-check ``CheckResult``/``Failure`` entries,
and writes a v1-conformant ``eval.json``.

Status resolution (spec §6.3):

* evaluator internal raise         → ``"error"`` (engine top-level catch)
* ``final.json`` missing           → ``"incomplete"``
* any required check ``failed``    → ``"failed"``
* otherwise                        → ``"passed"``

``needs_eval`` is owned by the query layer (when ``eval.json`` is absent).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from agentlens.constants import SCHEMA_EVAL_V1
from agentlens.store.trust_artifacts import write_projection, write_trust_report
from agentlens.store.writer import atomic_write_json
from agentlens.time import utc_now_iso

from .agentrunway_v2 import project_events
from .agentrunway_events import build_evidence_coverage
from .checks import (
    REQUIRED_CHECKS,
    CheckFn,
    CheckResult,
    EvalContext,
)
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
    "normalize_for_diff",
    "resolve_status",
]


# ---------------------------------------------------------------------------
# Determinism helper (spec §9.5)
# ---------------------------------------------------------------------------

# Spec-pinned placeholder for masked timestamps. Note this is distinct from
# the ``agentlens.time.normalize_for_diff`` *string* helper, which uses a
# microsecond-precision placeholder. The evaluator determinism contract in
# spec §9.5 fixes the second-precision form ``0000-00-00T00:00:00Z``.
_DIFF_PLACEHOLDER = "0000-00-00T00:00:00Z"
_ISO_UTC_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$"
)


def normalize_for_diff(doc: Any) -> Any:
    """Return a deep copy of *doc* with every ``*_at`` timestamp masked.

    Used by the determinism regression test (spec §9.5) so two back-to-back
    ``evaluate(run_dir)`` calls can be compared byte-for-byte. Keys ending
    in ``_at`` whose value is an ISO8601-UTC string are replaced with the
    fixed placeholder ``"0000-00-00T00:00:00Z"``. The walk recurses into
    nested dicts and lists. The original input is **not** mutated.
    """
    if isinstance(doc, dict):
        out: dict[str, Any] = {}
        for k, v in doc.items():
            if (
                isinstance(k, str)
                and k.endswith("_at")
                and isinstance(v, str)
                and _ISO_UTC_RE.match(v)
            ):
                out[k] = _DIFF_PLACEHOLDER
            else:
                out[k] = normalize_for_diff(v)
        return out
    if isinstance(doc, list):
        return [normalize_for_diff(item) for item in doc]
    return doc


# ---------------------------------------------------------------------------
# Context loading
# ---------------------------------------------------------------------------


def _load_optional_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def load_context(run_dir: Path) -> EvalContext:
    """Load the four canonical documents from *run_dir*.

    ``run.json`` is required; the others may be absent (the corresponding
    checks then return ``skipped`` or ``failed`` per their own rules).
    Malformed event lines are kept as raw strings so
    :func:`check_schema_valid` / :func:`check_events_well_formed` can flag
    them per-line.
    """
    run_path = run_dir / "run.json"
    if not run_path.is_file():
        raise FileNotFoundError(f"run.json not found under {run_dir}")
    run = json.loads(run_path.read_text(encoding="utf-8"))

    events_lines: list[str] = []
    events: list[dict[str, Any]] = []
    events_path = run_dir / "events.jsonl"
    if events_path.is_file():
        text = events_path.read_text(encoding="utf-8")
        for line in text.splitlines():
            if not line.strip():
                continue
            events_lines.append(line)
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                events.append(parsed)

    final = _load_optional_json(run_dir / "final.json")
    manifest = _load_optional_json(run_dir / "manifest.json")

    return EvalContext(
        run=run,
        events=events,
        events_lines=events_lines,
        final=final,
        manifest=manifest,
        run_dir=run_dir,
    )


# ---------------------------------------------------------------------------
# Status resolution (spec §6.3)
# ---------------------------------------------------------------------------


def resolve_status(ctx: EvalContext, results: list[CheckResult]) -> str:
    if ctx.final is None:
        return "incomplete"
    if any(r.status == "failed" for r in results):
        return "failed"
    return "passed"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _short_name(fn: CheckFn) -> str:
    return getattr(fn, "__name__", "unknown").removeprefix("check_")


def _evaluator_error(summary: str, evidence: tuple[str, ...] = ()) -> Failure:
    return Failure(
        category=FailureCategory.EVALUATOR_ERROR,
        severity="critical",
        source="evaluator",
        blame_scope="unknown",
        recoverability="non_recoverable",
        confidence=1.0,
        summary=summary,
        evidence=evidence,
    )


def _minimal_error_eval(run_dir: Path, message: str) -> dict[str, Any]:
    return {
        "schema": SCHEMA_EVAL_V1,
        "run_id": run_dir.name,
        "evaluated_at": utc_now_iso(),
        "status": "error",
        "agent_outcome": "unknown",
        "checks": [],
        "failures": [
            _evaluator_error(
                f"evaluator failed to load context: {message}"
            ).to_dict()
        ],
    }


def _is_agentrunway_context(ctx: EvalContext, coverage: dict[str, Any]) -> bool:
    if int(coverage.get("event_count") or 0) > 0:
        return True
    run = ctx.run
    agent = run.get("agent") if isinstance(run, dict) else {}
    if isinstance(agent, dict):
        values = [agent.get("name"), agent.get("label"), agent.get("mode")]
        if any(isinstance(value, str) and "agentrunway" in value.lower() for value in values):
            return True
    return str(run.get("run_kind") or "").lower() == "agentrunway"


def _write_trust_artifacts(ctx: EvalContext, doc: dict[str, Any], coverage: dict[str, Any]) -> None:
    if not _is_agentrunway_context(ctx, coverage):
        return
    from .trust import build_trust_report

    projection = project_events(ctx.events)
    if not projection.get("run_id"):
        projection["run_id"] = str(ctx.run.get("run_id") or ctx.run_dir.name)
    final = ctx.final or {}
    claimed_outcome = str(final.get("agent_outcome") or final.get("claimed_outcome") or "unknown")
    trust_report = build_trust_report(
        projection,
        claimed_outcome=claimed_outcome,
        residual_risks=final.get("residual_risks") if isinstance(final.get("residual_risks"), list) else [],
    )
    write_projection(ctx.run_dir, projection)
    write_trust_report(ctx.run_dir, trust_report)
    doc["projection_ref"] = "artifacts/agentrunway_projection.json"
    doc["trust_report_ref"] = "artifacts/trust_report.json"
    doc["trust_report"] = trust_report


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def evaluate(run_dir: Path) -> dict[str, Any]:
    """Run all 12 required checks against *run_dir* and write ``eval.json``."""
    run_dir = Path(run_dir)

    try:
        ctx = load_context(run_dir)
    except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
        doc = _minimal_error_eval(run_dir, str(exc))
        atomic_write_json(run_dir / "eval.json", doc, redact=False)
        return doc

    results: list[CheckResult] = []
    failures: list[Failure] = []
    internal_error = False

    # Per spec §5.15 the engine dispatches in alphabetical order. This is
    # deterministic across platforms and independent of REQUIRED_CHECKS'
    # declared ordering.
    for fn in sorted(REQUIRED_CHECKS, key=lambda f: f.__name__):
        short = _short_name(fn)
        try:
            res = fn(ctx)
        except Exception as exc:  # noqa: BLE001 — surface as EVALUATOR_ERROR
            internal_error = True
            results.append(
                CheckResult(
                    name=short,
                    status="failed",
                    message=f"evaluator internal error: {exc!r}",
                )
            )
            failures.append(
                Failure(
                    category=FailureCategory.EVALUATOR_ERROR,
                    severity="high",
                    source="evaluator",
                    blame_scope="unknown",
                    recoverability="rerun_or_fix",
                    confidence=1.0,
                    summary=f"Evaluator check {fn.__name__} raised",
                    evidence=(repr(exc),),
                )
            )
            continue
        # Normalise the check name to the spec-canonical short form even if
        # a check returns an empty/unset name.
        if not res.name:
            res = CheckResult(
                name=short,
                status=res.status,
                message=res.message,
                evidence=res.evidence,
                failures=res.failures,
            )
        results.append(res)
        failures.extend(res.failures)

    status = "error" if internal_error else resolve_status(ctx, results)
    agent_outcome = (ctx.final or {}).get("agent_outcome", "unknown")

    sorted_results = sorted(results, key=lambda r: r.name)
    sorted_failures = sorted(failures, key=lambda f: (f.category.value, f.summary))

    doc: dict[str, Any] = {
        "schema": SCHEMA_EVAL_V1,
        "run_id": ctx.run.get("run_id", run_dir.name),
        "evaluated_at": utc_now_iso(),
        "status": status,
        "agent_outcome": agent_outcome,
        "checks": [r.to_dict() for r in sorted_results],
        "failures": [f.to_dict() for f in sorted_failures],
    }
    doc["evidence_coverage"] = build_evidence_coverage(ctx.events, run=ctx.run)
    _write_trust_artifacts(ctx, doc, doc["evidence_coverage"])
    atomic_write_json(run_dir / "eval.json", doc, redact=False)
    return doc
