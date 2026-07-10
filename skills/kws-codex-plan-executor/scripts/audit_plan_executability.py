#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from cpe_audit_common import (
    ADAPTIVE_LOCAL_FAST_PATH_DOCS_ONLY,
    ADAPTIVE_LOCAL_FAST_PATH_LINEAR_TASK,
    ADAPTIVE_LOCAL_FAST_PATH_SMALL_SCOPE,
    RISK_MARKER_REQUIRES_OPERATOR_REVIEW,
    dependency_list,
    docs_only,
    list_strings,
    malformed_scope,
    normalized_scopes,
    path_risk_markers,
    write_scope_too_broad,
)


CURRENT_SUPERPOWERS_PLAN_MARKERS = (
    "REQUIRED SUB-SKILL",
    "subagent-driven-development",
    "executing-plans",
)

CURRENT_SUPERPOWERS_COMPATIBLE = "current_superpowers_compatible"
CPE_FIXABLE_METADATA = "cpe_fixable_metadata"
OPERATOR_REVIEW_REQUIRED = "operator_review_required"
BLOCKED_UNSUPPORTED_PLAN_SHAPE = "blocked_unsupported_plan_shape"

BLOCKING_REASON_PRIORITY = (
    BLOCKED_UNSUPPORTED_PLAN_SHAPE,
    "acceptance_command_missing",
    "files_missing",
    "allowed_write_globs_empty",
    "write_scope_too_broad",
    RISK_MARKER_REQUIRES_OPERATOR_REVIEW,
)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_plan_text(plan: dict[str, Any], plan_json: Path) -> str:
    raw_plan_path = plan.get("plan")
    if not isinstance(raw_plan_path, str) or not raw_plan_path.strip():
        return ""
    plan_path = Path(raw_plan_path).expanduser()
    if not plan_path.is_absolute():
        plan_path = (plan_json.parent / plan_path).resolve(strict=False)
    try:
        return plan_path.read_text(encoding="utf-8")
    except OSError:
        return ""


def current_superpowers_header_present(plan_text: str) -> bool:
    return all(marker in plan_text for marker in CURRENT_SUPERPOWERS_PLAN_MARKERS)


def primary_blocking_reason(blocking: list[str]) -> str:
    unique = list(dict.fromkeys(blocking))
    for reason in BLOCKING_REASON_PRIORITY:
        if reason in unique:
            return reason
    return unique[0] if unique else "all pre-dispatch prerequisites passed"


def support_classification(blocking: list[str], fixable: list[str], risks: list[str]) -> str:
    if BLOCKED_UNSUPPORTED_PLAN_SHAPE in blocking:
        return BLOCKED_UNSUPPORTED_PLAN_SHAPE
    if risks or RISK_MARKER_REQUIRES_OPERATOR_REVIEW in blocking:
        return OPERATOR_REVIEW_REQUIRED
    if fixable:
        return CPE_FIXABLE_METADATA
    return CURRENT_SUPERPOWERS_COMPATIBLE


def strongest_plan_support(tasks: list[dict[str, Any]], global_blocking: list[str]) -> str:
    if global_blocking:
        return BLOCKED_UNSUPPORTED_PLAN_SHAPE
    supports = [item.get("plan_support") for item in tasks]
    for candidate in (BLOCKED_UNSUPPORTED_PLAN_SHAPE, OPERATOR_REVIEW_REQUIRED, CPE_FIXABLE_METADATA):
        if candidate in supports:
            return candidate
    return CURRENT_SUPERPOWERS_COMPATIBLE


def files_exist_or_are_declared(files: list[str], repo_root: Path) -> bool:
    if not files:
        return False
    for item in files:
        candidate = (repo_root / item).resolve(strict=False)
        try:
            candidate.relative_to(repo_root)
        except ValueError:
            return False
    return True


def load_packets(packet_dir: Path | None) -> dict[str, dict[str, Any]]:
    if packet_dir is None or not packet_dir.is_dir():
        return {}
    packets: dict[str, dict[str, Any]] = {}
    for packet_path in sorted(packet_dir.glob("*.json")):
        payload = load_json(packet_path)
        if isinstance(payload, dict):
            task_id = payload.get("task_id")
            if isinstance(task_id, str) and task_id.strip():
                packets[task_id] = payload
    return packets


def subagent_fit(files: list[str], depends_on: list[str], acceptance_missing: bool, risks: list[str]) -> tuple[str, str]:
    if risks:
        return "block", RISK_MARKER_REQUIRES_OPERATOR_REVIEW
    if acceptance_missing and not docs_only(files):
        return "block", "acceptance_command_missing"
    if docs_only(files):
        return "local_fast_path", ADAPTIVE_LOCAL_FAST_PATH_DOCS_ONLY
    if 0 < len(files) <= 2 and len(depends_on) <= 1:
        reason = ADAPTIVE_LOCAL_FAST_PATH_SMALL_SCOPE if not depends_on else ADAPTIVE_LOCAL_FAST_PATH_LINEAR_TASK
        return "local_fast_path", reason
    return "delegate", "all pre-dispatch prerequisites passed"


def audit_task(
    task: dict[str, Any],
    packet: dict[str, Any] | None,
    repo_root: Path,
    plan_shape_blocking: list[str],
) -> dict[str, Any]:
    task_id = str(task.get("id") or task.get("task_id") or "unknown_task")
    files = list_strings(task.get("files"))
    depends_on = dependency_list(task)
    packet_policy = packet.get("write_policy") if isinstance(packet, dict) and isinstance(packet.get("write_policy"), dict) else {}
    allowed = list_strings(packet_policy.get("allowed_write_globs")) if packet_policy else files
    packet_acceptance = packet.get("acceptance") if isinstance(packet, dict) and isinstance(packet.get("acceptance"), dict) else {}
    acceptance_command = task.get("acceptance_command") or packet_acceptance.get("command")
    acceptance_missing = not isinstance(acceptance_command, str) or not acceptance_command.strip()
    risks = path_risk_markers(files + allowed, list_strings(task.get("risk_markers")))

    fixable: list[str] = []
    blocking: list[str] = list(plan_shape_blocking)
    suggested = normalized_scopes(allowed or files)

    if not files_exist_or_are_declared(files, repo_root):
        blocking.append("files_missing")
        blocking.append(BLOCKED_UNSUPPORTED_PLAN_SHAPE)
    if not allowed:
        blocking.append("allowed_write_globs_empty")
    if any(write_scope_too_broad(scope) for scope in allowed):
        blocking.append("write_scope_too_broad")
    if any(malformed_scope(scope) for scope in allowed + files):
        fixable.append("write_scope_format_invalid")
    if acceptance_missing:
        if docs_only(files):
            fixable.append("acceptance_command_missing")
        else:
            blocking.append("acceptance_command_missing")
    if packet and isinstance(packet.get("spec"), dict) and (
        not isinstance(packet["spec"].get("section_ids"), list) or not packet["spec"].get("section_ids")
    ):
        blocking.append("missing_explicit_spec_mapping")
    if risks:
        blocking.append(RISK_MARKER_REQUIRES_OPERATOR_REVIEW)

    fit, reason = subagent_fit(files, depends_on, acceptance_missing, risks)
    if blocking:
        fit = "block"
        reason = primary_blocking_reason(blocking)
    plan_support = support_classification(blocking, fixable, risks)

    return {
        "task_id": task_id,
        "files_status": "green" if files and "files_missing" not in blocking else "red",
        "acceptance_status": "yellow"
        if "acceptance_command_missing" in fixable
        else ("red" if "acceptance_command_missing" in blocking else "green"),
        "write_policy_status": "red"
        if any(item in blocking for item in ("allowed_write_globs_empty", "write_scope_too_broad"))
        else ("yellow" if "write_scope_format_invalid" in fixable else "green"),
        "spec_mapping_status": "red" if "missing_explicit_spec_mapping" in blocking else "green",
        "plan_support": plan_support,
        "subagent_fit": fit,
        "subagent_reason": reason,
        "risk_markers": risks,
        "fixable_issues": sorted(dict.fromkeys(fixable)),
        "blocking_issues": sorted(dict.fromkeys(blocking)),
        "suggested_write_scopes": suggested,
    }


def build_payload(plan_json: Path, repo_root: Path, packet_dir: Path | None) -> dict[str, Any]:
    plan = load_json(plan_json)
    if not isinstance(plan, dict):
        raise ValueError("plan JSON must be an object")
    plan_text = read_plan_text(plan, plan_json)
    plan_shape_blocking = [] if current_superpowers_header_present(plan_text) else [BLOCKED_UNSUPPORTED_PLAN_SHAPE]
    packets = load_packets(packet_dir)
    tasks = []
    for task in plan.get("tasks", []):
        if not isinstance(task, dict):
            continue
        task_id = str(task.get("id") or task.get("task_id") or "")
        tasks.append(audit_task(task, packets.get(task_id), repo_root, plan_shape_blocking))

    global_blocking = []
    if not tasks:
        global_blocking.append(BLOCKED_UNSUPPORTED_PLAN_SHAPE)
    blocking_count = len(global_blocking) + sum(len(item["blocking_issues"]) for item in tasks)
    fixable_count = sum(len(item["fixable_issues"]) for item in tasks)
    grade = "red" if blocking_count else ("yellow" if fixable_count else "green")
    plan_support = strongest_plan_support(tasks, global_blocking)
    support_counts = {
        CURRENT_SUPERPOWERS_COMPATIBLE: sum(
            1 for item in tasks if item.get("plan_support") == CURRENT_SUPERPOWERS_COMPATIBLE
        ),
        CPE_FIXABLE_METADATA: sum(1 for item in tasks if item.get("plan_support") == CPE_FIXABLE_METADATA),
        OPERATOR_REVIEW_REQUIRED: sum(1 for item in tasks if item.get("plan_support") == OPERATOR_REVIEW_REQUIRED),
        BLOCKED_UNSUPPORTED_PLAN_SHAPE: sum(
            1 for item in tasks if item.get("plan_support") == BLOCKED_UNSUPPORTED_PLAN_SHAPE
        )
        + len(global_blocking),
    }
    summary = {
        "route": "thin_stateful_bridge",
        "plan_support": plan_support,
        "plan_support_counts": support_counts,
        "task_count": len(tasks),
        "delegate_ready_count": sum(1 for item in tasks if item["subagent_fit"] == "delegate"),
        "local_fast_path_count": sum(1 for item in tasks if item["subagent_fit"] == "local_fast_path"),
        "fixable_issue_count": fixable_count,
        "blocking_issue_count": blocking_count,
    }
    return {
        "schema_version": "1",
        "passed": blocking_count == 0,
        "grade": grade,
        "plan_support": plan_support,
        "summary": summary,
        "tasks": tasks,
        "global_followups": sorted(dict.fromkeys(global_blocking)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit Superpowers plan executability before CPE task execution.")
    parser.add_argument("--plan-json", required=True)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--task-packet-dir")
    parser.add_argument("--output")
    args = parser.parse_args()

    payload = build_payload(
        Path(args.plan_json).expanduser(),
        Path(args.repo_root).expanduser().resolve(),
        Path(args.task_packet_dir).expanduser() if args.task_packet_dir else None,
    )
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
