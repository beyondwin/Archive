"""Bounded trust-labelled optimization reports derived from run evidence."""

from __future__ import annotations

import json
from pathlib import Path

from .state import atomic_private_write


MAX_REPORT_BYTES = 1024 * 1024


class OptimizationMarkdownError(RuntimeError):
    """The authoritative JSON report succeeded but its derivative did not."""


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
    return {
        "format_version": 2,
        "run_id": run_id,
        "usage": {
            "observed_input_tokens": observed,
            "unknown_attempt_count": unknown,
            "total_kind": "exact" if unknown == 0 else "lower_bound",
        },
        "duration_ms": duration,
        "findings": findings,
    }


def render_optimization_markdown(report: dict[str, object]) -> str:
    usage = report["usage"]
    assert isinstance(usage, dict)
    lines = [
        "# Optimization Report",
        "",
        f"Run: `{report['run_id']}`",
        f"Usage ({usage['total_kind']}): {usage['observed_input_tokens']} observed input tokens; "
        f"{usage['unknown_attempt_count']} attempts unknown.",
        f"Observed attempt duration: {report['duration_ms']} ms.",
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
