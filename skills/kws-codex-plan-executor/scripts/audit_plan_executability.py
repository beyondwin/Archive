#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ADAPTIVE_LOCAL_FAST_PATH_DOCS_ONLY = "adaptive_policy_local_fast_path_docs_only"
ADAPTIVE_LOCAL_FAST_PATH_SMALL_SCOPE = "adaptive_policy_local_fast_path_small_scope"
ADAPTIVE_LOCAL_FAST_PATH_LINEAR_TASK = "adaptive_policy_local_fast_path_linear_task"
ADAPTIVE_LOCAL_FAST_PATH_LOW_PARALLEL_VALUE = "adaptive_policy_local_fast_path_low_parallel_value"
RISK_MARKER_REQUIRES_OPERATOR_REVIEW = "risk_marker_requires_operator_review"

RISKY_PATH_FRAGMENTS = ("migration", "migrations", "auth", "security", "infra", "terraform", "pulumi")
RISKY_EXACT_FILES = {"bun.lock", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "Cargo.lock"}
BROAD_SCOPES = {"", ".", "*", "**", "**/*", "./", "./*", "./**", "./**/*"}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def list_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]


def write_scope_too_broad(pattern: str) -> bool:
    return pattern.strip().rstrip("/") in BROAD_SCOPES


def malformed_scope(pattern: str) -> bool:
    stripped = pattern.strip()
    return "," in stripped and not any(char in stripped for char in "[]{}")


def normalized_scopes(patterns: list[str]) -> list[str]:
    result: list[str] = []
    for pattern in patterns:
        parts = [item.strip() for item in pattern.split(",")] if malformed_scope(pattern) else [pattern.strip()]
        for part in parts:
            if part and part not in result:
                result.append(part)
    return result


def path_risk_markers(paths: list[str], explicit: list[str] | None = None) -> list[str]:
    markers = {item for item in (explicit or []) if item}
    for path in paths:
        normalized = path.strip().lstrip("./")
        if normalized in RISKY_EXACT_FILES:
            markers.add("lockfile")
        lowered = normalized.lower()
        for fragment in RISKY_PATH_FRAGMENTS:
            if fragment in lowered:
                markers.add(fragment)
    return sorted(markers)


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
    docs_only = bool(files) and all(path.startswith("docs/") and path.endswith(".md") for path in files)
    if risks:
        return "block", RISK_MARKER_REQUIRES_OPERATOR_REVIEW
    if docs_only:
        return "local_fast_path", ADAPTIVE_LOCAL_FAST_PATH_DOCS_ONLY
    if 0 < len(files) <= 2 and len(depends_on) <= 1:
        reason = ADAPTIVE_LOCAL_FAST_PATH_SMALL_SCOPE if not depends_on else ADAPTIVE_LOCAL_FAST_PATH_LINEAR_TASK
        return "local_fast_path", reason
    if acceptance_missing:
        return "local_only", "acceptance_command_missing"
    return "delegate", "all pre-dispatch prerequisites passed"


def audit_task(task: dict[str, Any], packet: dict[str, Any] | None, repo_root: Path) -> dict[str, Any]:
    task_id = str(task.get("id") or task.get("task_id") or "unknown_task")
    files = list_strings(task.get("files"))
    depends_on = list_strings(task.get("depends_on"))
    packet_policy = packet.get("write_policy") if isinstance(packet, dict) and isinstance(packet.get("write_policy"), dict) else {}
    allowed = list_strings(packet_policy.get("allowed_write_globs")) if packet_policy else files
    packet_acceptance = packet.get("acceptance") if isinstance(packet, dict) and isinstance(packet.get("acceptance"), dict) else {}
    acceptance_command = task.get("acceptance_command") or packet_acceptance.get("command")
    acceptance_missing = not isinstance(acceptance_command, str) or not acceptance_command.strip()
    risks = path_risk_markers(files + allowed, list_strings(task.get("risk_markers")))

    fixable: list[str] = []
    blocking: list[str] = []
    suggested = normalized_scopes(allowed or files)

    if not files_exist_or_are_declared(files, repo_root):
        blocking.append("files_missing")
    if not allowed:
        blocking.append("allowed_write_globs_empty")
    if any(write_scope_too_broad(scope) for scope in allowed):
        blocking.append("write_scope_too_broad")
    if any(malformed_scope(scope) for scope in allowed + files):
        fixable.append("write_scope_format_invalid")
    if acceptance_missing:
        docs_only = bool(files) and all(path.startswith("docs/") and path.endswith(".md") for path in files)
        if docs_only:
            fixable.append("acceptance_command_missing")
        else:
            blocking.append("acceptance_command_missing")
    if packet and isinstance(packet.get("spec"), dict) and packet["spec"].get("fallback_used") is True:
        fixable.append("full_spec_fallback")
    if risks:
        blocking.append(RISK_MARKER_REQUIRES_OPERATOR_REVIEW)

    fit, reason = subagent_fit(files, depends_on, acceptance_missing, risks)
    if blocking:
        fit = "block"

    return {
        "task_id": task_id,
        "files_status": "green" if files and "files_missing" not in blocking else "red",
        "acceptance_status": "yellow"
        if "acceptance_command_missing" in fixable
        else ("red" if "acceptance_command_missing" in blocking else "green"),
        "write_policy_status": "red"
        if any(item in blocking for item in ("allowed_write_globs_empty", "write_scope_too_broad"))
        else ("yellow" if "write_scope_format_invalid" in fixable else "green"),
        "spec_mapping_status": "yellow" if "full_spec_fallback" in fixable else "green",
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
    packets = load_packets(packet_dir)
    tasks = []
    for task in plan.get("tasks", []):
        if not isinstance(task, dict):
            continue
        task_id = str(task.get("id") or task.get("task_id") or "")
        tasks.append(audit_task(task, packets.get(task_id), repo_root))

    blocking_count = sum(len(item["blocking_issues"]) for item in tasks)
    fixable_count = sum(len(item["fixable_issues"]) for item in tasks)
    grade = "red" if blocking_count else ("yellow" if fixable_count else "green")
    summary = {
        "route": "thin_stateful_bridge",
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
        "summary": summary,
        "tasks": tasks,
        "global_followups": [],
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
