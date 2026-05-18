"""Twelve deterministic evaluator checks (spec §5.14).

Each check is a pure function ``CheckFn(EvalContext) -> CheckResult``.
The full list is exported as :data:`REQUIRED_CHECKS`; the engine
(`evaluator/engine.py`) iterates them in alphabetical order.

Conventions:

* ``CheckResult.name`` uses the spec-canonical short name (no ``check_``
  prefix) so it appears as ``schema_valid``, ``final_present``, etc. in
  ``eval.json``.
* ``Failure.blame_scope`` is set explicitly per category — never default
  to ``"agent"``. Schema failures blame the agent; ``EVALUATOR_ERROR``
  blames ``"unknown"``; artifact-hash mismatches blame the environment.
* ``check_*`` functions never raise; they return a ``failed`` result with
  appropriate failures. Only an *unexpected* exception is surfaced as
  ``EVALUATOR_ERROR`` by the engine.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from agentlens.schema.validate import (
    EventLineError,
    SchemaError,
    validate_doc,
    validate_event_line,
)

from .failures import Failure, FailureCategory

# ---------------------------------------------------------------------------
# Context + result containers
# ---------------------------------------------------------------------------


@dataclass
class EvalContext:
    """The four JSON documents loaded from a run directory (spec §5.14).

    ``events`` is the parsed list (used by most checks).
    ``events_lines`` is the raw list (used by :func:`check_schema_valid` /
    :func:`check_events_well_formed` to detect malformed lines).
    """

    run: dict[str, Any]
    events: list[dict[str, Any]]
    events_lines: list[str]
    final: dict[str, Any] | None
    manifest: dict[str, Any] | None
    run_dir: Path


@dataclass
class CheckResult:
    name: str  # spec-canonical short name, e.g. "schema_valid"
    status: str  # "passed" | "failed" | "skipped"
    message: str | None = None
    evidence: tuple[str, ...] = ()
    failures: tuple[Failure, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a dict matching ``eval.schema.json.checks[]``."""
        out: dict[str, Any] = {"name": self.name, "status": self.status}
        if self.message is not None:
            out["message"] = self.message
        if self.evidence:
            out["evidence"] = list(self.evidence)
        return out


CheckFn = Callable[[EvalContext], CheckResult]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _agent_outcome(ctx: EvalContext) -> str | None:
    if ctx.final is None:
        return None
    val = ctx.final.get("agent_outcome")
    return val if isinstance(val, str) else None


def _hash_bytes(b: bytes) -> str:
    return "sha256:" + hashlib.sha256(b).hexdigest()


# Severity ordering for residual-risk comparison.
_SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}


# ---------------------------------------------------------------------------
# 1. check_schema_valid
# ---------------------------------------------------------------------------


def check_schema_valid(ctx: EvalContext) -> CheckResult:
    """Re-validate run.json, events.jsonl, final.json, manifest.json."""
    failures: list[Failure] = []
    messages: list[str] = []

    try:
        validate_doc(ctx.run, schema_name="run")
    except SchemaError as exc:
        failures.append(
            Failure(
                category=FailureCategory.INVALID_RUN_SCHEMA,
                severity="high",
                source="evaluator",
                blame_scope="agent",
                recoverability="rerun_or_fix",
                confidence=1.0,
                summary=f"run.json failed schema validation: {exc}",
                evidence=tuple(list(exc.errors)[:5]),
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
                Failure(
                    category=FailureCategory.INVALID_EVENT_SCHEMA,
                    severity="high",
                    source="evaluator",
                    blame_scope="agent",
                    recoverability="rerun_or_fix",
                    confidence=1.0,
                    summary=f"events.jsonl line {idx} failed: {exc}",
                    evidence=tuple(list(exc.errors)[:5]),
                )
            )
            messages.append(f"events.jsonl[{idx}]: {exc}")

    if ctx.final is not None:
        try:
            validate_doc(ctx.final, schema_name="final")
        except SchemaError as exc:
            failures.append(
                Failure(
                    category=FailureCategory.INVALID_FINAL_SCHEMA,
                    severity="high",
                    source="evaluator",
                    blame_scope="agent",
                    recoverability="rerun_or_fix",
                    confidence=1.0,
                    summary=f"final.json failed schema validation: {exc}",
                    evidence=tuple(list(exc.errors)[:5]),
                )
            )
            messages.append(f"final.json: {exc}")

    if ctx.manifest is not None:
        try:
            validate_doc(ctx.manifest, schema_name="manifest")
        except SchemaError as exc:
            failures.append(
                Failure(
                    category=FailureCategory.INVALID_MANIFEST_SCHEMA,
                    severity="high",
                    source="evaluator",
                    blame_scope="agent",
                    recoverability="rerun_or_fix",
                    confidence=1.0,
                    summary=f"manifest.json failed schema validation: {exc}",
                    evidence=tuple(list(exc.errors)[:5]),
                )
            )
            messages.append(f"manifest.json: {exc}")

    status = "failed" if failures else "passed"
    return CheckResult(
        name="schema_valid",
        status=status,
        message="; ".join(messages) if messages else None,
        failures=tuple(failures),
    )


# ---------------------------------------------------------------------------
# 2. check_run_started
# ---------------------------------------------------------------------------


def check_run_started(ctx: EvalContext) -> CheckResult:
    """Verify that the events stream begins with a ``run.started`` event."""
    if not ctx.events:
        return CheckResult(
            name="run_started",
            status="failed",
            message="events.jsonl is empty (no run.started)",
            failures=(
                Failure(
                    category=FailureCategory.RECORDING_INCOMPLETE,
                    severity="high",
                    source="evaluator",
                    blame_scope="agent",
                    recoverability="rerun_or_fix",
                    confidence=1.0,
                    summary="no run.started event recorded",
                    evidence=(),
                ),
            ),
        )
    first = ctx.events[0]
    if first.get("type") == "run.started":
        return CheckResult(name="run_started", status="passed")
    return CheckResult(
        name="run_started",
        status="failed",
        message=f"first event type is {first.get('type')!r}, expected run.started",
        failures=(
            Failure(
                category=FailureCategory.RECORDING_INCOMPLETE,
                severity="high",
                source="evaluator",
                blame_scope="agent",
                recoverability="rerun_or_fix",
                confidence=1.0,
                summary="events.jsonl does not start with run.started",
                evidence=(f"first_type={first.get('type')!r}",),
            ),
        ),
    )


# ---------------------------------------------------------------------------
# 3. check_events_well_formed
# ---------------------------------------------------------------------------


def check_events_well_formed(ctx: EvalContext) -> CheckResult:
    """Each non-empty line in events.jsonl parses + matches event schema."""
    bad: list[str] = []
    for idx, line in enumerate(ctx.events_lines, start=1):
        if not line.strip():
            continue
        try:
            validate_event_line(line)
        except EventLineError as exc:
            bad.append(f"line {idx}: {exc}")
    if not bad:
        return CheckResult(name="events_well_formed", status="passed")
    return CheckResult(
        name="events_well_formed",
        status="failed",
        message="; ".join(bad[:5]),
        failures=(
            Failure(
                category=FailureCategory.INVALID_EVENT_SCHEMA,
                severity="high",
                source="evaluator",
                blame_scope="agent",
                recoverability="rerun_or_fix",
                confidence=1.0,
                summary=f"{len(bad)} malformed event line(s)",
                evidence=tuple(bad[:5]),
            ),
        ),
    )


# ---------------------------------------------------------------------------
# 4. check_final_present
# ---------------------------------------------------------------------------


def check_final_present(ctx: EvalContext) -> CheckResult:
    if ctx.final is None:
        return CheckResult(
            name="final_present",
            status="failed",
            message="final.json not found",
            failures=(
                Failure(
                    category=FailureCategory.MISSING_FINAL,
                    severity="high",
                    source="evaluator",
                    blame_scope="agent",
                    recoverability="rerun_or_fix",
                    confidence=1.0,
                    summary="final.json was not written before evaluation",
                    evidence=(),
                ),
            ),
        )
    return CheckResult(name="final_present", status="passed")


# ---------------------------------------------------------------------------
# 5. check_agent_outcome_valid
# ---------------------------------------------------------------------------

_VALID_OUTCOMES = {"success", "failed", "partial", "cancelled", "unknown"}


def check_agent_outcome_valid(ctx: EvalContext) -> CheckResult:
    if ctx.final is None:
        return CheckResult(
            name="agent_outcome_valid",
            status="skipped",
            message="final.json absent",
        )
    outcome = ctx.final.get("agent_outcome")
    if isinstance(outcome, str) and outcome in _VALID_OUTCOMES:
        return CheckResult(name="agent_outcome_valid", status="passed")
    return CheckResult(
        name="agent_outcome_valid",
        status="failed",
        message=f"agent_outcome={outcome!r} not in {sorted(_VALID_OUTCOMES)}",
        failures=(
            Failure(
                category=FailureCategory.INVALID_FINAL_SCHEMA,
                severity="high",
                source="evaluator",
                blame_scope="agent",
                recoverability="rerun_or_fix",
                confidence=1.0,
                summary=f"agent_outcome {outcome!r} not in allowed set",
                evidence=(f"agent_outcome={outcome!r}",),
            ),
        ),
    )


# ---------------------------------------------------------------------------
# 6. check_verification_present
# ---------------------------------------------------------------------------


def check_verification_present(ctx: EvalContext) -> CheckResult:
    outcome = _agent_outcome(ctx)
    if outcome != "success":
        return CheckResult(
            name="verification_present",
            status="skipped",
            message="check applies only when agent_outcome=success",
        )
    assert ctx.final is not None  # implied by outcome != None
    verification = ctx.final.get("verification") or []
    if verification:
        return CheckResult(name="verification_present", status="passed")
    return CheckResult(
        name="verification_present",
        status="failed",
        message="agent_outcome=success but verification[] is empty",
        failures=(
            Failure(
                category=FailureCategory.MISSING_VERIFICATION_EVIDENCE,
                severity="high",
                source="evaluator",
                blame_scope="agent",
                recoverability="rerun_or_fix",
                confidence=1.0,
                summary="success outcome without verification evidence",
                evidence=(),
            ),
        ),
    )


# ---------------------------------------------------------------------------
# 7. check_commands_resolved
# ---------------------------------------------------------------------------


def check_commands_resolved(ctx: EvalContext) -> CheckResult:
    """Every command.started has a matching command.finished (by command_hash)."""
    started_hashes: list[str] = []
    finished_hashes: list[str] = []
    for ev in ctx.events:
        if not isinstance(ev, dict):
            continue
        payload = ev.get("payload") or {}
        h = payload.get("command_hash") if isinstance(payload, dict) else None
        if ev.get("type") == "command.started" and isinstance(h, str):
            started_hashes.append(h)
        elif ev.get("type") == "command.finished" and isinstance(h, str):
            finished_hashes.append(h)

    if not started_hashes:
        return CheckResult(
            name="commands_resolved",
            status="passed",
            message="no command.started events to resolve",
        )

    # multiset subtraction
    pending = list(started_hashes)
    for fh in finished_hashes:
        if fh in pending:
            pending.remove(fh)

    if not pending:
        return CheckResult(name="commands_resolved", status="passed")

    return CheckResult(
        name="commands_resolved",
        status="failed",
        message=f"{len(pending)} command.started event(s) without matching finished",
        failures=(
            Failure(
                category=FailureCategory.RECORDING_INCOMPLETE,
                severity="medium",
                source="evaluator",
                blame_scope="agent",
                recoverability="rerun_or_fix",
                confidence=0.9,
                summary="command.started without command.finished counterpart",
                evidence=tuple(pending[:5]),
            ),
        ),
    )


# ---------------------------------------------------------------------------
# 8. check_failed_commands_acknowledged
# ---------------------------------------------------------------------------


def check_failed_commands_acknowledged(ctx: EvalContext) -> CheckResult:
    """Each command.finished with status="failed" is acknowledged in final."""
    failed_hashes: list[str] = []
    for ev in ctx.events:
        if not isinstance(ev, dict) or ev.get("type") != "command.finished":
            continue
        payload = ev.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        if payload.get("status") == "failed":
            h = payload.get("command_hash")
            if isinstance(h, str):
                failed_hashes.append(h)

    if not failed_hashes:
        return CheckResult(name="failed_commands_acknowledged", status="passed")

    if ctx.final is None:
        return CheckResult(
            name="failed_commands_acknowledged",
            status="failed",
            message=f"{len(failed_hashes)} failed command(s) but no final.json to ack",
            failures=(
                Failure(
                    category=FailureCategory.UNACKNOWLEDGED_FAILED_COMMAND,
                    severity="high",
                    source="evaluator",
                    blame_scope="agent",
                    recoverability="rerun_or_fix",
                    confidence=1.0,
                    summary="failed command without final.json acknowledgement",
                    evidence=tuple(failed_hashes[:5]),
                ),
            ),
        )

    # Acknowledgement: verification entry references command_hash (failed or not),
    # OR agent_outcome is non-success (the failure is implicitly owned).
    outcome = ctx.final.get("agent_outcome")
    if outcome != "success":
        # Treat as acknowledged: final captures the broader failure mode.
        return CheckResult(
            name="failed_commands_acknowledged",
            status="passed",
            message=f"agent_outcome={outcome!r} acknowledges {len(failed_hashes)} failed command(s)",
        )

    acked = {
        v.get("command_hash")
        for v in (ctx.final.get("verification") or [])
        if isinstance(v, dict)
    }
    unacked = [h for h in failed_hashes if h not in acked]
    if not unacked:
        return CheckResult(name="failed_commands_acknowledged", status="passed")
    return CheckResult(
        name="failed_commands_acknowledged",
        status="failed",
        message=f"{len(unacked)} failed command(s) not acknowledged in verification",
        failures=(
            Failure(
                category=FailureCategory.UNACKNOWLEDGED_FAILED_COMMAND,
                severity="high",
                source="evaluator",
                blame_scope="agent",
                recoverability="rerun_or_fix",
                confidence=1.0,
                summary="success outcome but failed commands not acknowledged",
                evidence=tuple(unacked[:5]),
            ),
        ),
    )


# ---------------------------------------------------------------------------
# 9. check_changed_files_present_when_success
# ---------------------------------------------------------------------------


def check_changed_files_present_when_success(ctx: EvalContext) -> CheckResult:
    if _agent_outcome(ctx) != "success":
        return CheckResult(
            name="changed_files_present_when_success",
            status="skipped",
            message="check applies only when agent_outcome=success",
        )
    assert ctx.final is not None
    changed = ctx.final.get("changed_files") or []
    if changed:
        return CheckResult(
            name="changed_files_present_when_success",
            status="passed",
        )
    reason = ctx.final.get("no_changes_reason")
    if isinstance(reason, str) and reason.strip():
        return CheckResult(
            name="changed_files_present_when_success",
            status="passed",
            message=f"no changes declared: {reason}",
        )
    return CheckResult(
        name="changed_files_present_when_success",
        status="failed",
        message="success outcome with empty changed_files and no no_changes_reason",
        failures=(
            Failure(
                category=FailureCategory.DIFF_SCOPE_UNKNOWN,
                severity="medium",
                source="evaluator",
                blame_scope="agent",
                recoverability="rerun_or_fix",
                confidence=0.9,
                summary="diff scope unknown: success without changed_files or reason",
                evidence=(),
            ),
        ),
    )


# ---------------------------------------------------------------------------
# 10. check_residual_risks_explicit
# ---------------------------------------------------------------------------


def check_residual_risks_explicit(ctx: EvalContext) -> CheckResult:
    if ctx.final is None:
        return CheckResult(
            name="residual_risks_explicit",
            status="skipped",
            message="final.json absent",
        )
    outcome = ctx.final.get("agent_outcome")
    risks = ctx.final.get("residual_risks") or []
    if outcome != "success":
        # Non-success: residual risks already captured by outcome itself.
        return CheckResult(name="residual_risks_explicit", status="passed")

    if not risks:
        return CheckResult(name="residual_risks_explicit", status="passed")

    max_rank = max(
        _SEVERITY_RANK.get(
            (r.get("severity") if isinstance(r, dict) else None) or "low",
            0,
        )
        for r in risks
    )
    if max_rank >= _SEVERITY_RANK["medium"]:
        evidence = tuple(
            f"severity={r.get('severity')}: {r.get('summary')}"
            for r in risks
            if isinstance(r, dict)
        )[:5]
        return CheckResult(
            name="residual_risks_explicit",
            status="failed",
            message=f"success outcome with medium+ residual risk ({len(risks)} entries)",
            failures=(
                Failure(
                    category=FailureCategory.SUCCESS_WITH_RESIDUAL_RISK,
                    severity="high",
                    source="evaluator",
                    blame_scope="agent",
                    recoverability="needs_user",
                    confidence=1.0,
                    summary="agent reported success but left medium+ residual risk",
                    evidence=evidence,
                ),
            ),
        )

    # success + only low-severity residuals.
    verification = ctx.final.get("verification") or []
    if verification:
        return CheckResult(
            name="residual_risks_explicit",
            status="passed",
            message=f"{len(risks)} low-severity residual risk(s) with verification",
        )
    return CheckResult(
        name="residual_risks_explicit",
        status="passed",
        message=f"{len(risks)} low-severity residual risk(s) (no verification)",
    )


# ---------------------------------------------------------------------------
# 11. check_manifest_sealed
# ---------------------------------------------------------------------------


def check_manifest_sealed(ctx: EvalContext) -> CheckResult:
    if ctx.manifest is None:
        return CheckResult(
            name="manifest_sealed",
            status="skipped",
            message="manifest.json absent (pre-seal evaluation)",
        )
    sealed = bool(ctx.manifest.get("sealed"))
    if sealed:
        return CheckResult(name="manifest_sealed", status="passed")
    return CheckResult(
        name="manifest_sealed",
        status="failed",
        message="manifest.sealed is false",
        failures=(
            Failure(
                category=FailureCategory.MANIFEST_NOT_SEALED,
                severity="high",
                source="evaluator",
                blame_scope="environment",
                recoverability="rerun_or_fix",
                confidence=1.0,
                summary="manifest.json exists but sealed=false",
                evidence=(),
            ),
        ),
    )


# ---------------------------------------------------------------------------
# 12. check_artifact_hashes_valid
# ---------------------------------------------------------------------------


def check_artifact_hashes_valid(ctx: EvalContext) -> CheckResult:
    if ctx.manifest is None:
        return CheckResult(
            name="artifact_hashes_valid",
            status="skipped",
            message="manifest.json absent",
        )
    entries = ctx.manifest.get("files") or []
    mismatches: list[str] = []
    missing: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        path = entry.get("path")
        expected = entry.get("sha256")
        if not isinstance(path, str) or not isinstance(expected, str):
            continue
        target = ctx.run_dir / path
        if not target.is_file():
            missing.append(path)
            continue
        try:
            actual = _hash_bytes(target.read_bytes())
        except OSError as exc:
            mismatches.append(f"{path}: read error {exc}")
            continue
        if actual != expected:
            mismatches.append(f"{path}: expected {expected} actual {actual}")

    if not mismatches and not missing:
        return CheckResult(name="artifact_hashes_valid", status="passed")

    evidence = tuple((missing + mismatches)[:5])
    summary = (
        f"{len(mismatches)} hash mismatch(es), {len(missing)} missing file(s)"
    )
    return CheckResult(
        name="artifact_hashes_valid",
        status="failed",
        message=summary,
        failures=(
            Failure(
                category=FailureCategory.ARTIFACT_HASH_MISMATCH,
                severity="critical",
                source="evaluator",
                blame_scope="environment",
                recoverability="non_recoverable",
                confidence=1.0,
                summary=summary,
                evidence=evidence,
            ),
        ),
    )


# ---------------------------------------------------------------------------
# REQUIRED_CHECKS (declaration order is informational; engine sorts by name)
# ---------------------------------------------------------------------------


REQUIRED_CHECKS: tuple[CheckFn, ...] = (
    check_schema_valid,
    check_run_started,
    check_events_well_formed,
    check_final_present,
    check_agent_outcome_valid,
    check_verification_present,
    check_commands_resolved,
    check_failed_commands_acknowledged,
    check_changed_files_present_when_success,
    check_residual_risks_explicit,
    check_manifest_sealed,
    check_artifact_hashes_valid,
)


__all__ = [
    "REQUIRED_CHECKS",
    "CheckFn",
    "CheckResult",
    "EvalContext",
    "check_agent_outcome_valid",
    "check_artifact_hashes_valid",
    "check_changed_files_present_when_success",
    "check_commands_resolved",
    "check_events_well_formed",
    "check_failed_commands_acknowledged",
    "check_final_present",
    "check_manifest_sealed",
    "check_residual_risks_explicit",
    "check_run_started",
    "check_schema_valid",
    "check_verification_present",
]
