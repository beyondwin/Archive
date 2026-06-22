#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def issue(task_id: str, severity: str, kind: str, message: str, **extra: object) -> dict:
    payload = {
        "task_id": task_id,
        "severity": severity,
        "kind": kind,
        "message": message,
    }
    payload.update(extra)
    return payload


def packet_task_id(packet: dict, fallback: str) -> str:
    value = packet.get("task_id")
    return value if isinstance(value, str) and value.strip() else fallback


def list_strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]


def malformed_scope(pattern: str) -> bool:
    return "," in pattern and not any(char in pattern for char in "[]{}")


def normalized_scopes(patterns: list[str]) -> list[str]:
    normalized: list[str] = []
    for pattern in patterns:
        parts = [item.strip() for item in pattern.split(",")] if malformed_scope(pattern) else [pattern.strip()]
        for part in parts:
            if part and part not in normalized:
                normalized.append(part)
    return normalized


def audit_packet(packet_path: Path) -> tuple[dict, list[dict]]:
    packet = load_json(packet_path)
    if not isinstance(packet, dict):
        return {"task_id": packet_path.stem}, [
            issue(packet_path.stem, "blocking", "packet_not_object", "Task packet must be a JSON object.")
        ]

    task_id = packet_task_id(packet, packet_path.stem)
    issues: list[dict] = []
    files = list_strings(packet.get("files"))
    acceptance = packet.get("acceptance") if isinstance(packet.get("acceptance"), dict) else {}
    if not acceptance.get("command"):
        issues.append(
            issue(task_id, "fixable", "acceptance_command_missing", "Task packet has no acceptance command before dispatch.")
        )

    spec = packet.get("spec") if isinstance(packet.get("spec"), dict) else {}
    if spec.get("fallback_used") is True:
        issues.append(
            issue(
                task_id,
                "fixable",
                "full_spec_fallback",
                "Task packet uses full spec fallback instead of task-specific spec sections.",
            )
        )

    policy = packet.get("write_policy") if isinstance(packet.get("write_policy"), dict) else {}
    allowed = list_strings(policy.get("allowed_write_globs"))
    normalized = normalized_scopes(allowed or files)
    if not allowed:
        issues.append(issue(task_id, "blocking", "allowed_write_globs_empty", "Task packet has no allowed write globs."))
    for pattern in allowed + files:
        if malformed_scope(pattern):
            issues.append(
                issue(
                    task_id,
                    "fixable",
                    "write_scope_format_invalid",
                    "Write scope appears to contain multiple comma-joined paths.",
                    suggested_write_scopes=normalized_scopes([pattern]),
                )
            )
            break

    budget = packet.get("context_budget") if isinstance(packet.get("context_budget"), dict) else {}
    if budget.get("status") == "red":
        issues.append(issue(task_id, "fixable", "packet_context_budget_red", "Task packet context budget is red before execution."))

    has_blocking = any(item["severity"] == "blocking" for item in issues)
    summary = {
        "task_id": task_id,
        "delegate_ready": not has_blocking and not issues,
        "local_fast_path_candidate": len(files) <= 3 and not has_blocking,
        "issue_count": len(issues),
        "normalized_write_globs": normalized,
    }
    return summary, issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit CPE task packet readiness before execution edits.")
    parser.add_argument("--state", required=True)
    parser.add_argument("--task-packet-dir", required=True)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--requested-subagents", choices=["on", "auto", "off"], default="on")
    parser.add_argument("--requested-source", choices=["default", "explicit", "natural_language", "resume_state"], default="default")
    parser.add_argument("--spawn-policy", choices=["available", "unavailable", "explicit-request-required", "unknown"], default="unknown")
    parser.add_argument("--explicit-delegation-requested", choices=["true", "false"], default="false")
    args = parser.parse_args()

    state_path = Path(args.state)
    packet_dir = Path(args.task_packet_dir)
    repo_root = Path(args.repo_root)
    all_issues: list[dict] = []
    task_summaries: list[dict] = []

    if not state_path.is_file():
        all_issues.append(issue("__run__", "blocking", "state_missing", "State file is not readable."))
    if not packet_dir.is_dir():
        all_issues.append(issue("__run__", "blocking", "task_packet_dir_missing", "Task packet directory is not readable."))
    if not repo_root.is_dir():
        all_issues.append(issue("__run__", "blocking", "repo_root_missing", "Repository root is not readable."))

    if not all_issues:
        for packet_path in sorted(packet_dir.glob("*.json")):
            try:
                summary, issues = audit_packet(packet_path)
            except (OSError, json.JSONDecodeError) as exc:
                summary = {"task_id": packet_path.stem, "delegate_ready": False, "local_fast_path_candidate": False, "issue_count": 1}
                issues = [issue(packet_path.stem, "blocking", "packet_unreadable", f"Task packet is not readable JSON: {exc}")]
            task_summaries.append(summary)
            all_issues.extend(issues)

    blocking = sum(1 for item in all_issues if item.get("severity") == "blocking")
    fixable = sum(1 for item in all_issues if item.get("severity") == "fixable")
    payload = {
        "schema_version": "1",
        "passed": blocking == 0 and fixable == 0,
        "requested": {
            "subagents": args.requested_subagents,
            "source": args.requested_source,
            "spawn_policy": args.spawn_policy,
            "explicit_delegation_requested": args.explicit_delegation_requested == "true",
        },
        "summary": {
            "task_count": len(task_summaries),
            "delegate_ready_count": sum(1 for item in task_summaries if item.get("delegate_ready") is True),
            "local_fast_path_count": sum(1 for item in task_summaries if item.get("local_fast_path_candidate") is True),
            "fixable_issue_count": fixable,
            "blocking_issue_count": blocking,
        },
        "tasks": task_summaries,
        "issues": all_issues,
    }
    Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
