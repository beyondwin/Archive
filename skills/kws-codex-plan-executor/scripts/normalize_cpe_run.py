#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def list_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]


def residual_risk_classes(audit: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for item in audit.get("residual_risk", []):
        risk_class: str | None = None
        if isinstance(item, dict) and isinstance(item.get("class"), str):
            risk_class = item["class"]
        elif isinstance(item, str) and "credential" in item.lower():
            risk_class = "external_credentials"
        if risk_class and risk_class not in result:
            result.append(risk_class)
    return result


def forbidden_patterns(texts: list[str]) -> list[str]:
    markers: list[str] = []
    joined = "\n".join(texts)
    for marker, needle in (
        ("sk-", "sk-"),
        ("absolute_home_path", "/Users/"),
        ("full_prompt", "BEGIN FULL PROMPT"),
    ):
        if needle in joined and marker not in markers:
            markers.append(marker)
    return markers


def count_dispatch_reasons(state: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    decisions = state.get("dispatch_decisions")
    if not isinstance(decisions, list):
        return counts
    for item in decisions:
        if not isinstance(item, dict):
            continue
        reason = item.get("reason")
        if isinstance(reason, str) and reason.strip():
            counts[reason] = counts.get(reason, 0) + 1
    return dict(sorted(counts.items()))


def full_spec_fallback_count(state: dict[str, Any]) -> int:
    quality = state.get("run_quality") if isinstance(state.get("run_quality"), dict) else {}
    context = quality.get("context_quality") if isinstance(quality.get("context_quality"), dict) else {}
    value = context.get("full_spec_fallback_count")
    if isinstance(value, int):
        return value
    tasks = state.get("tasks")
    if not isinstance(tasks, dict):
        return 0
    return sum(1 for task in tasks.values() if isinstance(task, dict) and task.get("fallback_spec_used") is True)


def plan_executability_summary(state: dict[str, Any]) -> dict[str, Any]:
    audit = state.get("plan_executability_audit")
    if not isinstance(audit, dict):
        return {}
    return {
        "grade": audit.get("grade"),
        "raw_grade": audit.get("raw_grade", audit.get("grade")),
        "blocking_issue_count": audit.get("blocking_issue_count", 0),
        "raw_blocking_issue_count": audit.get("raw_blocking_issue_count", audit.get("blocking_issue_count", 0)),
        "fixable_issue_count": audit.get("fixable_issue_count", 0),
        "raw_fixable_issue_count": audit.get("raw_fixable_issue_count", audit.get("fixable_issue_count", 0)),
    }


def read_optional_text(path: str | None) -> str:
    if not path:
        return ""
    candidate = Path(path).expanduser()
    if not candidate.is_file():
        return ""
    return candidate.read_text(encoding="utf-8", errors="replace")


def normalize(state: dict[str, Any], *, context_text: str = "", final_output_text: str = "") -> dict[str, Any]:
    completion = state.get("completion_audit") if isinstance(state.get("completion_audit"), dict) else {}
    quality = state.get("run_quality") if isinstance(state.get("run_quality"), dict) else {}
    prompt_audit = state.get("prompt_audit") if isinstance(state.get("prompt_audit"), dict) else {}
    graphify = state.get("graphify_audit") if isinstance(state.get("graphify_audit"), dict) else {}
    tasks = state.get("tasks") if isinstance(state.get("tasks"), dict) else {}
    return {
        "schema_version": "1",
        "run_id": state.get("run_id"),
        "terminal_state": state.get("lifecycle_outcome"),
        "completion_passed": completion.get("passed") is True,
        "run_quality_grade": quality.get("grade"),
        "open_followups": list_strings(quality.get("open_followups")),
        "task_count": len(tasks),
        "full_spec_fallback_count": full_spec_fallback_count(state),
        "dispatch_decision_reasons": count_dispatch_reasons(state),
        "plan_executability": plan_executability_summary(state),
        "prompt_audit_passed": prompt_audit.get("passed") is True or prompt_audit.get("dynamic_marker_violations") == [],
        "graphify_fresh": graphify.get("fresh") is True,
        "residual_risk_classes": residual_risk_classes(completion),
        "forbidden_patterns_found": forbidden_patterns([context_text, final_output_text]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize CPE run state into deterministic replay JSON.")
    parser.add_argument("--state", required=True)
    parser.add_argument("--run-dir")
    parser.add_argument("--context")
    parser.add_argument("--final-output")
    parser.add_argument("--output")
    args = parser.parse_args()

    state_path = Path(args.state).expanduser()
    state = load_json(state_path)
    context_text = read_optional_text(args.context)
    final_output_text = read_optional_text(args.final_output)
    payload = normalize(state, context_text=context_text, final_output_text=final_output_text)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).expanduser().write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
