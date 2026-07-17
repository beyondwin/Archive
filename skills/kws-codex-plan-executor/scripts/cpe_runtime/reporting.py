"""Bounded trust-labelled optimization reports derived from run evidence."""

from __future__ import annotations

import json
import re
from pathlib import Path
from pathlib import PurePosixPath

from .state import TRUST_LEVELS, atomic_private_write


MAX_REPORT_BYTES = 1024 * 1024
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SIGNAL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_FINDING_REQUIRED = {"signal", "source", "evidence_refs"}
_FINDING_OPTIONAL = {
    "impact", "action", "outcome", "recurrence", "recommendation",
}


def derive_recovery_metrics(
    events: list[dict[str, object]],
) -> dict[str, object]:
    """Derive bounded recovery counters from the authoritative event stream."""
    launches_avoided = 0
    envelope_repairs = 0
    productive_timeouts = 0
    no_progress_slices = 0
    budget_stops = 0
    reasons: dict[str, int] = {}
    for event in events:
        action = event.get("action")
        reason = event.get("reason")
        if action == "resume.stopped_unchanged_blocker":
            launches_avoided += 1
        if action == "result.envelope_repaired":
            envelope_repairs += 1
            launches_avoided += 1
        if (
            action == "plan.pre_spawn_stopped"
            and reason in {
                "checkpoint_budget_exhausted",
                "launch_budget_exhausted",
                "wall_budget_exhausted",
            }
        ):
            budget_stops += 1
        if action != "plan.checkpoint_decided" or not isinstance(reason, str):
            continue
        if event.get("decision") == "continue":
            reasons[reason] = reasons.get(reason, 0) + 1
        if reason == "productive_timeout":
            productive_timeouts += 1
        if reason in {"first_no_progress_slice", "second_no_progress_slice"}:
            no_progress_slices += 1
        if reason in {
            "checkpoint_budget_exhausted",
            "launch_budget_exhausted",
            "wall_budget_exhausted",
        }:
            budget_stops += 1
    return {
        "launches_avoided": launches_avoided,
        "envelope_repairs": envelope_repairs,
        "productive_timeouts": productive_timeouts,
        "no_progress_slices": no_progress_slices,
        "budget_stops": budget_stops,
        "continuation_reason_counts": dict(sorted(reasons.items())),
    }


class OptimizationMarkdownError(RuntimeError):
    """The authoritative JSON report succeeded but its derivative did not."""


def _validate_evidence_reference(reference: object) -> None:
    if (
        not isinstance(reference, str)
        or not reference
        or len(reference) > 500
        or "\\" in reference
    ):
        raise ValueError("optimization finding evidence reference is invalid")
    path = PurePosixPath(reference)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("optimization finding evidence reference is unsafe")


def _validate_finding(finding: object) -> None:
    if not isinstance(finding, dict):
        raise ValueError("optimization finding must be an object")
    fields = set(finding)
    if finding.get("source") not in TRUST_LEVELS:
        raise ValueError("optimization finding trust source is invalid")
    if not _FINDING_REQUIRED.issubset(fields) or fields - _FINDING_REQUIRED - _FINDING_OPTIONAL:
        raise ValueError("optimization finding fields are invalid")
    signal = finding["signal"]
    if not isinstance(signal, str) or not _SIGNAL.fullmatch(signal):
        raise ValueError("optimization finding signal is invalid")
    references = finding["evidence_refs"]
    if not isinstance(references, list) or not references or len(references) > 128:
        raise ValueError("optimization finding evidence references are invalid")
    for reference in references:
        _validate_evidence_reference(reference)
    for name in _FINDING_OPTIONAL & fields:
        value = finding[name]
        if not isinstance(value, str) or not value or len(value) > 2000:
            raise ValueError(f"optimization finding {name} is invalid")


def validate_optimization_report(report: object) -> dict[str, object]:
    if not isinstance(report, dict) or set(report) != {
        "format_version", "run_id", "usage", "duration_ms", "recovery_metrics",
        "findings",
    }:
        raise ValueError("optimization report fields are invalid")
    if report["format_version"] != 2:
        raise ValueError("optimization report format version is invalid")
    run_id = report["run_id"]
    if not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id):
        raise ValueError("optimization report run identity is invalid")
    duration = report["duration_ms"]
    if not isinstance(duration, int) or isinstance(duration, bool) or duration < 0:
        raise ValueError("optimization report duration is invalid")
    usage = report["usage"]
    if not isinstance(usage, dict) or set(usage) != {
        "observed_input_tokens", "unknown_attempt_count", "total_kind",
    }:
        raise ValueError("optimization report usage is invalid")
    for name in ("observed_input_tokens", "unknown_attempt_count"):
        value = usage[name]
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError("optimization report usage is invalid")
    expected_kind = "exact" if usage["unknown_attempt_count"] == 0 else "lower_bound"
    if usage["total_kind"] != expected_kind:
        raise ValueError("optimization report usage kind is invalid")
    metrics = report["recovery_metrics"]
    metric_fields = {
        "launches_avoided", "envelope_repairs", "productive_timeouts",
        "no_progress_slices", "budget_stops", "continuation_reason_counts",
    }
    if not isinstance(metrics, dict) or set(metrics) != metric_fields:
        raise ValueError("optimization report recovery metrics are invalid")
    for name in metric_fields - {"continuation_reason_counts"}:
        value = metrics[name]
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError("optimization report recovery metrics are invalid")
    reasons = metrics["continuation_reason_counts"]
    if (
        not isinstance(reasons, dict)
        or len(reasons) > 128
        or any(
            not isinstance(name, str) or not _SIGNAL.fullmatch(name)
            or not isinstance(value, int) or isinstance(value, bool) or value < 0
            for name, value in reasons.items()
        )
    ):
        raise ValueError("optimization report recovery metrics are invalid")
    findings = report["findings"]
    if not isinstance(findings, list) or len(findings) > 1024:
        raise ValueError("optimization report findings are invalid")
    for finding in findings:
        _validate_finding(finding)
    return report


def build_optimization_report(
    *,
    run_id: str,
    events: list[dict[str, object]],
    findings: list[dict[str, object]],
) -> dict[str, object]:
    observed = 0
    unknown = 0
    duration = 0
    for event in events:
        if event.get("action") != "plan.attempt_finished":
            continue
        duration += int(event.get("duration_ms") or 0)
        tokens = event.get("input_tokens")
        if isinstance(tokens, int) and not isinstance(tokens, bool):
            observed += tokens
        else:
            unknown += 1
    report: dict[str, object] = {
        "format_version": 2,
        "run_id": run_id,
        "usage": {
            "observed_input_tokens": observed,
            "unknown_attempt_count": unknown,
            "total_kind": "exact" if unknown == 0 else "lower_bound",
        },
        "duration_ms": duration,
        "recovery_metrics": derive_recovery_metrics(events),
        "findings": findings,
    }
    return validate_optimization_report(report)


def render_optimization_markdown(report: dict[str, object]) -> str:
    usage = report["usage"]
    assert isinstance(usage, dict)
    metrics = report["recovery_metrics"]
    assert isinstance(metrics, dict)
    reasons = metrics["continuation_reason_counts"]
    assert isinstance(reasons, dict)
    lines = [
        "# Optimization Report",
        "",
        f"Run: `{report['run_id']}`",
        f"Usage ({usage['total_kind']}): {usage['observed_input_tokens']} observed input tokens; "
        f"{usage['unknown_attempt_count']} attempts unknown.",
        f"Observed attempt duration: {report['duration_ms']} ms.",
        "",
        "## Recovery Metrics",
        "",
        f"- Launches avoided: {metrics['launches_avoided']}",
        f"- Local envelope repairs: {metrics['envelope_repairs']}",
        f"- Productive timeouts: {metrics['productive_timeouts']}",
        f"- No-progress slices: {metrics['no_progress_slices']}",
        f"- Budget stops: {metrics['budget_stops']}",
        (
            "- Continuation reasons: " + ", ".join(
                f"{name}={count}" for name, count in reasons.items()
            )
            if reasons else "- Continuation reasons: none"
        ),
        "",
        "## Findings",
        "",
    ]
    findings = report.get("findings", [])
    if not findings:
        lines.append("No optimization findings were derived.")
    else:
        for finding in findings:
            assert isinstance(finding, dict)
            lines.extend([
                f"### {finding.get('signal', finding.get('symptom', 'signal'))}",
                "",
                f"- Source trust: {finding.get('source', 'derived')}",
                f"- Impact: {finding.get('impact', 'unavailable')}",
                f"- Action: {finding.get('action', 'unavailable')}",
                f"- Outcome: {finding.get('outcome', 'unavailable')}",
                f"- Recurrence: {finding.get('recurrence', 'unavailable')}",
                f"- Recommendation: {finding.get('recommendation', 'unavailable')}",
                "- Evidence references: " + ", ".join(
                    str(item) for item in finding.get("evidence_refs", [])
                ),
                "",
            ])
    return "\n".join(lines).rstrip() + "\n"


def write_optimization_reports(
    *,
    reports_root: Path,
    report: dict[str, object],
) -> tuple[Path, Path]:
    validate_optimization_report(report)
    encoded = json.dumps(
        report, ensure_ascii=False, sort_keys=True, indent=2
    ).encode("utf-8")
    if len(encoded) > MAX_REPORT_BYTES:
        raise ValueError("optimization report exceeds size limit")
    json_path = reports_root / "optimization-report.json"
    md_path = reports_root / "optimization-report.md"
    atomic_private_write(json_path, encoded)
    try:
        markdown = render_optimization_markdown(report).encode("utf-8")
        if len(markdown) > MAX_REPORT_BYTES:
            raise ValueError("optimization markdown exceeds size limit")
        atomic_private_write(md_path, markdown)
    except (OSError, TypeError, ValueError, AssertionError) as exc:
        raise OptimizationMarkdownError(str(exc)) from exc
    return json_path, md_path
