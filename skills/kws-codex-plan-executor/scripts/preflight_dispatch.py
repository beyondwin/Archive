#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fnmatch
import json
import subprocess
from pathlib import Path

from cpe_audit_common import (
    ADAPTIVE_LOCAL_FAST_PATH_DOCS_ONLY,
    ADAPTIVE_LOCAL_FAST_PATH_LINEAR_TASK,
    ADAPTIVE_LOCAL_FAST_PATH_LOW_PARALLEL_VALUE,
    ADAPTIVE_LOCAL_FAST_PATH_SMALL_SCOPE,
    RISK_MARKER_REQUIRES_OPERATOR_REVIEW,
    dependency_list,
    docs_only,
    list_strings,
    malformed_scope,
    path_risk_markers,
    write_scope_too_broad,
)


def git_changed(repo: Path) -> set[str]:
    files: set[str] = set()
    for args in (["diff", "--name-only", "HEAD"], ["ls-files", "--others", "--exclude-standard"]):
        result = subprocess.run(["git", *args], cwd=repo, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        files.update(line.strip() for line in result.stdout.splitlines() if line.strip())
    return files


def matches_any(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def decision_payload(
    task_id: str,
    decision: str,
    reason: str,
    write_scope: list[str],
    failed: list[str],
    delegation_policy: dict,
    delegation_capability: dict,
) -> dict:
    mode = "delegated" if decision == "delegate" else "local_fallback"
    return {
        "schema_version": "1",
        "task_id": task_id,
        "decision": decision,
        "reason": reason,
        "write_scope": write_scope,
        "failed_prerequisites": failed,
        "delegation_policy": delegation_policy,
        "state_updates": {
            "delegation_policy": delegation_policy,
            "delegation_capability": delegation_capability,
            "subagent_strategy": {
                "mode": mode,
                "reason": reason,
                "run_ids": [],
            }
        },
    }


def delegation_capability_payload(args: argparse.Namespace, reason: str, decision: str) -> dict:
    effective = "delegate" if decision == "delegate" else decision
    return {
        "schema_version": "1",
        "spawn_policy": args.spawn_policy,
        "explicit_user_delegation_request": args.explicit_delegation_requested == "true",
        "run_level_effective_mode": effective,
        "reason": reason,
    }


def write_scope_format_invalid(pattern: str) -> bool:
    return malformed_scope(pattern)


def packet_context_status(packet: dict) -> str:
    budget = packet.get("context_budget") if isinstance(packet, dict) else {}
    if not isinstance(budget, dict):
        return "unknown"
    status = budget.get("status")
    return status if isinstance(status, str) and status.strip() else "unknown"


def packet_estimated_chars(packet: dict) -> int:
    budget = packet.get("context_budget") if isinstance(packet, dict) else {}
    if not isinstance(budget, dict):
        return 0
    value = budget.get("estimated_chars", 0)
    return value if isinstance(value, int) and value >= 0 else 0


def adaptive_value_decision(packet: dict, write_scope: list[str], explicit_requested: bool) -> tuple[str, str, dict]:
    files = list_strings(packet.get("files"))
    dependencies = dependency_list(packet)
    explicit_risks = list_strings(packet.get("risk_markers"))
    allowed = []
    policy = packet.get("write_policy") if isinstance(packet, dict) else {}
    if isinstance(policy, dict):
        allowed = list_strings(policy.get("allowed_write_globs"))
    context_status = packet_context_status(packet)
    estimated_chars = packet_estimated_chars(packet)
    risk_markers = path_risk_markers(files + write_scope, explicit_risks)
    docs_only_value = docs_only(files)
    small_file_count = 0 < len(files) <= 3
    narrow_scope = 0 < len(allowed) <= 3 and 0 < len(write_scope) <= 3
    low_parallel_value = small_file_count and narrow_scope and len(dependencies) <= 1 and estimated_chars <= 12000
    signals = {
        "declared_file_count": len(files),
        "allowed_write_glob_count": len(allowed),
        "write_scope_count": len(write_scope),
        "dependency_count": len(dependencies),
        "packet_budget_status": context_status,
        "estimated_chars": estimated_chars,
        "explicit_user_delegation_request": explicit_requested,
        "risk_markers": risk_markers,
        "docs_only": docs_only_value,
        "low_parallel_value": low_parallel_value,
    }
    if risk_markers:
        return "block", RISK_MARKER_REQUIRES_OPERATOR_REVIEW, signals
    if docs_only_value and context_status in {"green", "yellow"} and narrow_scope:
        return "local_fast_path", ADAPTIVE_LOCAL_FAST_PATH_DOCS_ONLY, signals
    if low_parallel_value and context_status in {"green", "yellow"}:
        if len(dependencies) == 1:
            return "local_fast_path", ADAPTIVE_LOCAL_FAST_PATH_LINEAR_TASK, signals
        return "local_fast_path", ADAPTIVE_LOCAL_FAST_PATH_SMALL_SCOPE, signals
    if not explicit_requested and len(files) <= 1 and estimated_chars <= 20000 and narrow_scope:
        return "local_fast_path", ADAPTIVE_LOCAL_FAST_PATH_LOW_PARALLEL_VALUE, signals
    return "delegate", "all pre-dispatch prerequisites passed", signals


def advisory_value_decision(packet: dict, write_scope: list[str], explicit_requested: bool) -> tuple[str, str, dict]:
    value_gate, value_reason, signals = adaptive_value_decision(packet, write_scope, explicit_requested)
    if value_gate == "local_fast_path":
        return "local_fallback", value_reason, signals
    if value_gate == "block":
        return "block", value_reason, signals
    return "delegate", value_reason, signals


def main() -> int:
    parser = argparse.ArgumentParser(description="Decide CPE subagent pre-dispatch readiness.")
    parser.add_argument("--state", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--task-packet", required=True)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--write-scope", action="append", required=True)
    parser.add_argument("--output")
    parser.add_argument(
        "--spawn-policy",
        choices=["available", "unavailable", "explicit-request-required", "unknown"],
        default="unknown",
    )
    parser.add_argument("--explicit-delegation-requested", choices=["true", "false"], default="false")
    parser.add_argument("--requested-subagents", choices=["on", "auto", "off"], default="on")
    parser.add_argument(
        "--requested-source",
        choices=["default", "explicit", "natural_language", "resume_state"],
        default="default",
    )
    args = parser.parse_args()

    repo = Path(args.repo_root).resolve()
    state_path = Path(args.state)
    failed: list[str] = []
    decision = "delegate"
    reason = "all pre-dispatch prerequisites passed"
    write_scope = args.write_scope
    explicit_requested = args.explicit_delegation_requested == "true"
    delegation_policy = {
        "requested_mode": args.requested_subagents,
        "requested_source": args.requested_source,
        "explicit_user_delegation_request": explicit_requested,
        "spawn_policy": args.spawn_policy,
        "effective_mode": "delegate",
        "reason": "Delegation prerequisites are still being evaluated.",
        "policy_kind": "adaptive",
        "safety_gate": "pending",
        "value_gate": "pending",
        "signals": {},
    }
    if args.requested_subagents == "off":
        failed.append("subagents_off")
        decision = "local_fallback"
        reason = "subagents=off requests local-only execution"
    elif args.spawn_policy == "unavailable":
        failed.append("spawn_policy_unavailable")
        decision = "local_fallback"
        reason = "spawn_agent tool is unavailable in this session"
    elif args.spawn_policy == "explicit-request-required" and not explicit_requested:
        failed.append("spawn_policy_requires_explicit_user_request")
        decision = "local_fallback"
        reason = "spawn_agent tool policy requires explicit user delegation intent"

    packet_path = Path(args.task_packet)
    packet = {}
    if not packet_path.is_file():
        failed.append("task_packet_missing")
    else:
        packet = json.loads(packet_path.read_text(encoding="utf-8"))

    if not state_path.is_file():
        failed.append("state_missing")
        state = {}
    else:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state.get("subagents_requested") is not True:
            failed.append("subagents_not_requested")
        tasks = state.get("tasks") if isinstance(state.get("tasks"), dict) else {}
        task_state = tasks.get(args.task_id) if isinstance(tasks.get(args.task_id), dict) else {}
        expected_hash = task_state.get("task_packet_sha256")
        actual_hash = packet.get("sha256") if isinstance(packet, dict) else None
        if expected_hash and actual_hash and expected_hash != actual_hash:
            failed.append("task_packet_hash_mismatch")
            decision = "block"
            reason = "task packet hash does not match state"

    policy = packet.get("write_policy") if isinstance(packet, dict) else {}
    allowed = policy.get("allowed_write_globs") if isinstance(policy, dict) else []
    forbidden = policy.get("forbidden_write_globs") if isinstance(policy, dict) else []
    if not allowed:
        failed.append("allowed_write_globs_empty")
    if any(write_scope_too_broad(str(scope)) for scope in allowed):
        failed.append("write_scope_too_broad")
        decision = "block"
        reason = "write scope is too broad for delegated execution"
    for scope in write_scope:
        if write_scope_format_invalid(scope):
            failed.append("write_scope_format_invalid")
            continue
        if allowed and not matches_any(scope, allowed):
            failed.append("write_scope_outside_allowed")
        if forbidden and matches_any(scope, forbidden):
            failed.append("write_scope_matches_forbidden")

    budget = packet.get("context_budget") if isinstance(packet, dict) else {}
    if isinstance(budget, dict) and budget.get("status") == "red":
        failed.append("packet_context_budget_red")

    spec = packet.get("spec") if isinstance(packet, dict) else {}
    if isinstance(spec, dict) and spec.get("fallback_used") is True:
        failed.append("explicit_spec_mapping_required")

    acceptance = packet.get("acceptance") if isinstance(packet, dict) else {}
    if isinstance(acceptance, dict) and not acceptance.get("command"):
        failed.append("acceptance_command_missing")

    dirty = git_changed(repo)
    dirty_overlap = sorted(path for path in dirty if matches_any(path, write_scope))
    if dirty_overlap:
        failed.append("dirty_overlap:" + ",".join(dirty_overlap))
        decision = "block"
        reason = "dirty files overlap delegated write scope"

    spawn_policy_failed_only = failed == ["spawn_policy_requires_explicit_user_request"]
    if spawn_policy_failed_only and decision == "local_fallback":
        would_decision, would_reason, signals = advisory_value_decision(packet, write_scope, explicit_requested)
        delegation_policy["signals"] = signals
        delegation_policy["value_gate"] = "skipped_by_spawn_policy"
        delegation_policy["would_have_decision"] = would_decision
        delegation_policy["would_have_reason"] = would_reason
        delegation_policy["would_have_value_gate"] = (
            "delegate" if would_decision == "delegate" else ("block" if would_decision == "block" else "local_fast_path")
        )
    elif not failed and decision == "delegate":
        value_gate, value_reason, signals = adaptive_value_decision(packet, write_scope, explicit_requested)
        delegation_policy["signals"] = signals
        delegation_policy["value_gate"] = value_gate
        if value_gate == "local_fast_path":
            decision = "local_fallback"
            reason = value_reason
        elif value_gate == "block":
            failed.append(value_reason)
            decision = "block"
            reason = value_reason
        else:
            reason = value_reason
    else:
        delegation_policy["signals"] = {}
        delegation_policy["value_gate"] = "skipped"

    delegation_policy["safety_gate"] = "failed" if failed else "passed"

    if failed and decision == "delegate":
        decision = "local_fallback"
        reason = failed[0]

    delegation_policy["effective_mode"] = "delegate" if decision == "delegate" else decision
    delegation_policy["reason"] = reason

    capability = delegation_capability_payload(args, reason, decision)
    payload = decision_payload(args.task_id, decision, reason, write_scope, failed, delegation_policy, capability)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if decision in {"delegate", "local_fallback"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
