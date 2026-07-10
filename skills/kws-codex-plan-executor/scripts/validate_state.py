#!/usr/bin/env python3
"""Validate a kws-codex-plan-executor state file."""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import run_quality_debt
except Exception:
    run_quality_debt = None

from cpe_state_validation import validate as validate_state_domains


REQUIRED_TOP_LEVEL = {
    "schema_version",
    "run_id",
    "mode",
    "workspace",
    "plan",
    "branch",
    "worktree",
    "run_dir",
    "state_path",
    "current_task",
    "current_phase",
    "tasks",
    "timestamps",
}
VALID_MODES = {"interactive", "headless", "prompt", "handoff"}
EXECUTION_MODES = {"interactive", "headless"}
VALID_LIFECYCLE_OUTCOMES = {"finished", "blocked", "failed", "userinterlude", "askuserQuestion"}
NON_SUCCESS_OUTCOMES = {"blocked", "failed", "userinterlude", "askuserQuestion"}
VALID_CONTEXT_HEALTH_STATUSES = {"green", "yellow", "red"}
REQUIRED_CONTEXT_HEALTH_FIELDS = {
    "status",
    "last_checked_at",
    "context_snapshot_present",
    "context_basis_hash_recorded",
    "active_task_contract_present",
    "next_action",
    "open_questions",
    "known_assumptions",
    "handoff_ready",
}
REQUIRED_TASK_FIELDS = {"status", "risk", "files_declared", "contract", "review_retries", "verifier_retries"}
REQUIRED_CONTRACT_FIELDS = {
    "scope",
    "files_to_inspect",
    "allowed_edits",
    "forbidden_edits",
    "acceptance_command_or_honest_substitute",
}
CONTRACT_LIST_FIELDS = {"files_to_inspect", "allowed_edits", "forbidden_edits"}
CONTRACT_STRING_FIELDS = {"scope", "acceptance_command_or_honest_substitute"}
VALID_UNIT_TYPES = {"research", "plan", "execute-task", "reactive-execute", "validate", "complete", "docs", "review", "handoff"}
VALID_CONTEXT_MODES = {"minimal", "focused", "expanded", "full"}
VALID_TOOL_POLICIES = {"read-only", "planning", "implementation", "docs", "verification"}
VALID_ARTIFACT_POLICIES = {"inline", "inline-summary", "excerpt", "on-demand"}
REQUIRED_UNIT_MANIFEST_FIELDS = {
    "unit_type",
    "context_mode",
    "required_skills",
    "tool_policy",
    "allowed_write_globs",
    "forbidden_write_globs",
    "artifact_policy",
    "max_context_chars",
}
VALID_SUBAGENT_STATUSES = {"queued", "running", "completed", "failed", "cancelled"}
VALID_SUBAGENT_REVIEW_STATUSES = {"unreviewed", "accepted", "rejected", "changes_requested"}
REQUIRED_SUBAGENT_FIELDS = {"id", "owner_task", "mode", "write_scope", "status", "result_summary"}
COMPLETED_SUBAGENT_FIELDS = {"changed_files", "review_status"}
REQUIRED_BOUNDARY_ATTESTATION_FIELDS = {
    "schema_version",
    "execution_worktree",
    "worker_cwd",
    "worker_git_root",
    "worker_head_before",
    "worker_head_after",
    "source_workspace",
    "source_workspace_head_before",
    "source_workspace_head_after",
    "execution_worktree_match",
    "source_workspace_unchanged",
    "dirty_scope_after",
}
HEX_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
VALID_SUBAGENT_STRATEGY_MODES = {"delegated", "local_fallback"}
VALID_ADAPTIVE_LOCAL_FAST_PATH_REASONS = {
    "adaptive_policy_local_fast_path_small_scope",
    "adaptive_policy_local_fast_path_docs_only",
    "adaptive_policy_local_fast_path_linear_task",
    "adaptive_policy_local_fast_path_low_parallel_value",
    "spawn_policy_requires_explicit_user_request",
}
VALID_DELEGATION_POLICY_KINDS = {"legacy", "adaptive"}
VALID_DELEGATION_SAFETY_GATES = {"pending", "passed", "failed"}
VALID_DELEGATION_VALUE_GATES = {"pending", "delegate", "local_fast_path", "block", "skipped", "skipped_by_spawn_policy"}
VALID_WOULD_HAVE_DECISIONS = {"delegate", "local_fallback", "block"}
VALID_WOULD_HAVE_VALUE_GATES = {"delegate", "local_fast_path", "block"}
VALID_COMMAND_OBSERVATION_CATEGORIES = {
    "source_failure",
    "missing_local_env",
    "dependency_bootstrap",
    "resource_oom",
    "timeout_or_hang",
    "flaky_test",
    "permission_or_sandbox",
    "tooling_bug",
    "unknown",
}
REQUIRED_COMMAND_OBSERVATION_FIELDS = {"command", "status", "category", "evidence", "next_action"}
VALID_BLOCKER_CATEGORIES = {
    "operator_input_required",
    "workspace_precondition",
    "plan_contract_gap",
    "diff_scope_gap",
    "execution_source_failure",
    "transient_tooling_or_resource",
    "state_integrity_drift",
    "subagent_coordination",
    "observability_degraded",
}
VALID_NEXT_ACTION_KINDS = {"continue", "retry", "bootstrap", "local_fallback", "operator_decision", "block", "fail"}
VALID_CACHE_STRATEGY_MODES = {"interactive-default", "headless-explicit", "prompt-export", "handoff-export"}
VALID_PROVIDER_CACHE_CONTROL = {"unavailable", "available-unused", "available-enabled", "unknown"}
TOKEN_FIELDS = {"input_tokens", "cached_read_tokens", "cached_write_tokens", "output_tokens"}
V220_TOP_LEVEL_FIELDS = {
    "spec_manifest_path",
    "task_packet_dir",
    "current_task_packet_path",
    "decisions_register",
    "preflight_warnings",
    "last_completed_task",
    "last_completed_at",
    "compaction",
}
REQUIRED_DECISION_FIELDS = {
    "id",
    "task",
    "decision",
    "files",
    "made_at",
    "supersedes",
    "superseded_by",
    "reason",
}
VALID_PREFLIGHT_WARNING_KINDS = {"missing_local_config", "dependencies_likely_stale"}
VALID_DELEGATION_REQUESTED_SOURCES = {"default", "explicit", "natural_language", "resume_state"}
VALID_SPAWN_POLICIES = {"available", "unavailable", "explicit-request-required", "unknown"}
VALID_DELEGATION_EFFECTIVE_MODES = {"delegate", "local_fallback", "off", "blocked"}
VALID_AGENTLENS_STATUSES = {
    "agentlens_unavailable",
    "agentlens_emit_failed",
    "agentlens_not_applicable",
    "agentlens_recorded",
}
VALID_RUN_QUALITY_VALIDATION_STATUSES = {"passed", "failed", "unreadable", "not_checked"}
VALID_RESIDUAL_RISK_OWNERS = {"executor", "operator", "product", "environment"}
VALID_RESIDUAL_RISK_CLASSES = {
    "external_credentials",
    "environment_gap",
    "deployment",
    "monitoring",
    "executor_evidence",
    "environment_unavailable",
    "known_executor_debt",
    "manual_review_needed",
    "product_followup",
    "test_scope_gap",
    "third_party_drift",
}
FORBIDDEN_DURABLE_OUTPUT_PATTERNS = {
    "sk-": "sk-",
    "absolute_home_path": "/Users/",
    "full_prompt": "BEGIN FULL PROMPT",
}


def _has_substantive_value(value: object) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return len(value) > 0
    return value is True


def _forbidden_durable_patterns(value: str) -> list[str]:
    return [
        name
        for name, needle in FORBIDDEN_DURABLE_OUTPUT_PATTERNS.items()
        if needle in value
    ]


def _validate_one_line_summary(field: str, value: object, errors: list[str]) -> None:
    if value is None:
        return
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{field} must be a non-empty string when present")
        return
    if "\n" in value or "\r" in value:
        errors.append(f"{field} must be one line")
    markers = _forbidden_durable_patterns(value)
    if markers:
        errors.append(f"{field} contains forbidden durable-output pattern(s): {', '.join(markers)}")


def _parse_ts(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _path_parts(value: object) -> list[str]:
    if not isinstance(value, str) or not value.strip():
        return []
    return [part for part in Path(value).parts if part not in ("", "/")]


def _has_codex_suffix(value: object, parent: str, run_id: str) -> bool:
    parts = _path_parts(value)
    return len(parts) >= 3 and parts[-3:] == [".codex", parent, run_id]


def _join_state_path(run_dir: object, name: str) -> str | None:
    if not isinstance(run_dir, str) or not run_dir.strip():
        return None
    return str(Path(run_dir) / name)


def _validate_paths(data: dict, errors: list[str]) -> None:
    run_id = data.get("run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        return
    if not _has_codex_suffix(data.get("run_dir"), "orchestrator", run_id):
        errors.append("run_dir must end with .codex/orchestrator/<run_id>")
    if not _has_codex_suffix(data.get("worktree"), "worktrees", run_id):
        errors.append("worktree must end with .codex/worktrees/<run_id>")
    expected_state = _join_state_path(data.get("run_dir"), "state.json")
    if expected_state and data.get("state_path") != expected_state:
        errors.append("state_path must equal run_dir/state.json")
    context_path = data.get("context_snapshot_path")
    if context_path is not None:
        expected_context = _join_state_path(data.get("run_dir"), "context.json")
        if expected_context and context_path != expected_context:
            errors.append("context_snapshot_path must equal run_dir/context.json")
        if not isinstance(data.get("context_basis_hash"), str) or not data["context_basis_hash"].strip():
            errors.append("context_basis_hash must be a non-empty string when context_snapshot_path is present")
    removed_path_key = "event_" + "journal_path"
    removed_seq_key = "last_" + "event_seq"
    if removed_path_key in data or removed_seq_key in data:
        errors.append("legacy event journal metadata is not supported; use agentlens_orchestration_run")


def _validate_context_health(data: dict, errors: list[str]) -> None:
    mode = data.get("mode")
    phase = data.get("current_phase")
    outcome = data.get("lifecycle_outcome")
    health = data.get("context_health")
    required = mode in EXECUTION_MODES and phase != "preflight"
    if required and health is None:
        errors.append("context_health must be present after execution preflight")
        return
    if health is None:
        return
    if not isinstance(health, dict):
        errors.append("context_health must be an object")
        return
    for key in sorted(REQUIRED_CONTEXT_HEALTH_FIELDS):
        if key not in health:
            errors.append(f"context_health missing field {key}")
    if health.get("status") not in VALID_CONTEXT_HEALTH_STATUSES:
        errors.append(f"context_health.status must be one of {sorted(VALID_CONTEXT_HEALTH_STATUSES)}")
    for key in ("context_snapshot_present", "context_basis_hash_recorded", "active_task_contract_present", "handoff_ready"):
        if key in health and not isinstance(health[key], bool):
            errors.append(f"context_health.{key} must be a boolean")
    for key in ("open_questions", "known_assumptions"):
        if key in health and not isinstance(health[key], list):
            errors.append(f"context_health.{key} must be a list")
    hot_tail = health.get("hot_tail_summaries")
    if hot_tail is not None:
        if not isinstance(hot_tail, list):
            errors.append("context_health.hot_tail_summaries must be a list when present")
        else:
            tasks = data.get("tasks") if isinstance(data.get("tasks"), dict) else {}
            for index, item in enumerate(hot_tail):
                prefix = f"context_health.hot_tail_summaries[{index}]"
                if not isinstance(item, dict):
                    errors.append(f"{prefix} must be an object")
                    continue
                task_id = item.get("task_id")
                if task_id not in tasks:
                    errors.append(f"{prefix}.task_id must reference a known task")
                _validate_one_line_summary(f"{prefix}.summary", item.get("summary"), errors)
    if data.get("context_snapshot_path") is not None and health.get("context_snapshot_present") is not True:
        errors.append("context_health.context_snapshot_present must be true when context_snapshot_path is present")
    if data.get("context_basis_hash") is not None and health.get("context_basis_hash_recorded") is not True:
        errors.append("context_health.context_basis_hash_recorded must be true when context_basis_hash is present")
    if outcome == "finished":
        if health.get("handoff_ready") is not True:
            errors.append("context_health.handoff_ready must be true when lifecycle_outcome is finished")
        if health.get("status") == "red":
            errors.append("context_health.status must not be red when lifecycle_outcome is finished")
        checked_at = _parse_ts(health.get("last_checked_at"))
        if checked_at is None:
            errors.append("context_health.last_checked_at must be present when lifecycle_outcome is finished")
        timestamps = data.get("timestamps") if isinstance(data.get("timestamps"), dict) else {}
        updated_at = _parse_ts(timestamps.get("updated_at"))
        if updated_at and checked_at and checked_at < updated_at:
            errors.append("context_health.last_checked_at must not be older than timestamps.updated_at when lifecycle_outcome is finished")


def _validate_completion_audit(data: dict, errors: list[str]) -> None:
    outcome = data.get("lifecycle_outcome")
    audit = data.get("completion_audit")
    if outcome is not None and outcome not in VALID_LIFECYCLE_OUTCOMES:
        errors.append(f"lifecycle_outcome must be one of {sorted(VALID_LIFECYCLE_OUTCOMES)}")
        return
    if outcome == "finished":
        if not isinstance(audit, dict):
            errors.append("completion_audit must be present when lifecycle_outcome is finished")
            return
        if audit.get("passed") is not True:
            errors.append("completion_audit.passed must be true when lifecycle_outcome is finished")
        checklist = audit.get("prompt_to_artifact_checklist")
        if not isinstance(checklist, list) or not checklist:
            errors.append("completion_audit.prompt_to_artifact_checklist must be a non-empty list")
        evidence = audit.get("verification_evidence")
        if not isinstance(evidence, list) or not evidence:
            errors.append("completion_audit.verification_evidence must be a non-empty list")
        else:
            _validate_verification_evidence_items(evidence, errors)
        residual = audit.get("residual_risk")
        if not isinstance(residual, list):
            errors.append("completion_audit.residual_risk must be a list")
        else:
            _validate_residual_risk_items(data, residual, errors)
    elif outcome in NON_SUCCESS_OUTCOMES and not _has_substantive_value(data.get("handoff_reason")):
        errors.append("handoff_reason must be non-empty for non-success lifecycle_outcome")


def _validate_residual_risk_items(data: dict, residual: list[object], errors: list[str]) -> None:
    audit = data.get("completion_audit") if isinstance(data.get("completion_audit"), dict) else {}
    for index, item in enumerate(residual):
        prefix = f"completion_audit.residual_risk[{index}]"
        if isinstance(item, str):
            if not item.strip():
                errors.append(f"{prefix} string must be non-empty")
            continue
        if not isinstance(item, dict):
            errors.append(f"{prefix} must be a string or object")
            continue
        for key in ("owner", "class", "summary", "blocks_release"):
            if key not in item:
                errors.append(f"{prefix}.{key} is required")
        if item.get("owner") not in VALID_RESIDUAL_RISK_OWNERS:
            errors.append(f"{prefix}.owner invalid")
        if item.get("class") not in VALID_RESIDUAL_RISK_CLASSES:
            errors.append(f"{prefix}.class invalid")
        if not _has_substantive_value(item.get("summary")):
            errors.append(f"{prefix}.summary must be non-empty")
        if not isinstance(item.get("blocks_release"), bool):
            errors.append(f"{prefix}.blocks_release must be a boolean")
        if (
            item.get("blocks_release") is True
            and data.get("lifecycle_outcome") == "finished"
            and audit.get("passed") is True
        ):
            errors.append("completion_audit.residual_risk blocks_release=true cannot coexist with finished passed completion")


def _validate_verification_evidence_items(evidence: list[object], errors: list[str]) -> None:
    for index, item in enumerate(evidence):
        prefix = f"completion_audit.verification_evidence[{index}]"
        if isinstance(item, str):
            if not item.strip():
                errors.append(f"{prefix} string must be non-empty")
            continue
        if not isinstance(item, dict):
            errors.append(f"{prefix} must be a string or object")
            continue
        evidence_class = item.get("class")
        if evidence_class is not None and not isinstance(evidence_class, str):
            errors.append(f"{prefix}.class must be a string when present")
        status = item.get("status")
        if status is not None and status not in {"passed", "failed", "skipped", "blocked"}:
            errors.append(f"{prefix}.status invalid")
        if evidence_class == "verification_bundle":
            if not _has_substantive_value(item.get("name")):
                errors.append(f"{prefix}.verification_bundle.name is required")
            commands = item.get("commands")
            if not isinstance(commands, list) or not any(isinstance(command, str) and command.strip() for command in commands):
                errors.append(f"{prefix}.verification_bundle.commands must contain at least one command")
            if item.get("status") not in {"passed", "failed", "skipped", "blocked"}:
                errors.append(f"{prefix}.verification_bundle.status is required")
            if "required" in item and not isinstance(item.get("required"), bool):
                errors.append(f"{prefix}.verification_bundle.required must be a boolean when present")


def _validate_timestamps(data: dict, errors: list[str]) -> None:
    timestamps = data.get("timestamps")
    if not isinstance(timestamps, dict):
        errors.append("timestamps must be an object")
        return
    for key in ("started_at", "updated_at"):
        if _parse_ts(timestamps.get(key)) is None:
            errors.append(f"timestamps.{key} must be an ISO timestamp")
    completed_at = timestamps.get("completed_at")
    if data.get("lifecycle_outcome") == "finished":
        if _parse_ts(completed_at) is None:
            errors.append("timestamps.completed_at must be an ISO timestamp when lifecycle_outcome is finished")
    elif completed_at is not None and _parse_ts(completed_at) is None:
        errors.append("timestamps.completed_at must be an ISO timestamp or null")


def _validate_contract(task_id: str, contract: object, errors: list[str]) -> None:
    if not isinstance(contract, dict):
        errors.append(f"{task_id}: contract must be an object")
        return
    for key in sorted(REQUIRED_CONTRACT_FIELDS):
        if key not in contract:
            errors.append(f"{task_id}: contract missing field {key}")
    for key in sorted(CONTRACT_LIST_FIELDS):
        if key in contract and not isinstance(contract[key], list):
            errors.append(f"{task_id}: contract.{key} must be a list")
    for key in sorted(CONTRACT_STRING_FIELDS):
        if key in contract and not _has_substantive_value(contract[key]):
            errors.append(f"{task_id}: contract.{key} must be non-empty")


def _validate_unit_manifest(task_id: str, task: dict, outcome: object, errors: list[str]) -> None:
    manifest = task.get("unit_manifest")
    completed = str(task.get("status", "")).lower() in {"complete", "completed", "done", "verified", "pass", "passed"}
    if outcome == "finished" and completed and not isinstance(manifest, dict):
        errors.append(f"{task_id}: completed task missing unit_manifest")
        return
    if manifest is None:
        return
    if not isinstance(manifest, dict):
        errors.append(f"{task_id}: unit_manifest must be an object")
        return
    for key in sorted(REQUIRED_UNIT_MANIFEST_FIELDS):
        if key not in manifest:
            errors.append(f"{task_id}: unit_manifest missing field {key}")
    if manifest.get("unit_type") not in VALID_UNIT_TYPES:
        errors.append(f"{task_id}: unit_manifest.unit_type invalid")
    if manifest.get("context_mode") not in VALID_CONTEXT_MODES:
        errors.append(f"{task_id}: unit_manifest.context_mode invalid")
    if manifest.get("tool_policy") not in VALID_TOOL_POLICIES:
        errors.append(f"{task_id}: unit_manifest.tool_policy invalid")
    if manifest.get("artifact_policy") not in VALID_ARTIFACT_POLICIES:
        errors.append(f"{task_id}: unit_manifest.artifact_policy invalid")
    for key in ("required_skills", "allowed_write_globs", "forbidden_write_globs"):
        if key in manifest and not isinstance(manifest[key], list):
            errors.append(f"{task_id}: unit_manifest.{key} must be a list")
    if manifest.get("tool_policy") in {"implementation", "docs"}:
        allowed = manifest.get("allowed_write_globs")
        if not isinstance(allowed, list) or not any(isinstance(item, str) and item.strip() for item in allowed):
            errors.append(f"{task_id}: unit_manifest.allowed_write_globs must be non-empty for write-capable units")
    if not isinstance(manifest.get("max_context_chars"), int) or manifest.get("max_context_chars", 0) <= 0:
        errors.append(f"{task_id}: unit_manifest.max_context_chars must be a positive integer")


def _validate_tasks(data: dict, errors: list[str]) -> None:
    tasks = data.get("tasks")
    if not isinstance(tasks, dict):
        errors.append("tasks must be an object")
        return
    current_task = data.get("current_task")
    if tasks and current_task not in tasks:
        errors.append("current_task must reference a task in state when tasks are present")
    outcome = data.get("lifecycle_outcome")
    for task_id, task in tasks.items():
        if not isinstance(task, dict):
            errors.append(f"{task_id}: task must be an object")
            continue
        for key in sorted(REQUIRED_TASK_FIELDS):
            if key not in task:
                errors.append(f"{task_id}: task missing field {key}")
        if "files_declared" in task and not isinstance(task["files_declared"], list):
            errors.append(f"{task_id}: files_declared must be a list")
        _validate_one_line_summary(f"{task_id}: next_task_summary", task.get("next_task_summary"), errors)
        view_path = task.get("task_packet_view_path")
        if view_path is not None:
            if not isinstance(view_path, str) or not view_path.strip():
                errors.append(f"{task_id}: task_packet_view_path must be a non-empty string when present")
            elif "/.codex/orchestrator/" not in view_path:
                errors.append(f"{task_id}: task_packet_view_path must live under .codex/orchestrator")
        view_hash = task.get("task_packet_view_sha256")
        if view_hash is not None:
            if not isinstance(view_hash, str) or len(view_hash) != 64:
                errors.append(f"{task_id}: task_packet_view_sha256 must be a 64-character sha256 string")
        _validate_contract(task_id, task.get("contract"), errors)
        _validate_unit_manifest(task_id, task, outcome, errors)
        carried = task.get("carried_acceptance")
        if outcome == "finished" and isinstance(carried, dict) and carried.get("status") == "open":
            errors.append(f"{task_id}: open carried_acceptance is not allowed for lifecycle_outcome=finished")


def _matches_any(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def _glob_prefix(pattern: str) -> str:
    wildcard_positions = [position for position in (pattern.find("*"), pattern.find("?"), pattern.find("[")) if position != -1]
    if not wildcard_positions:
        return pattern
    return pattern[: min(wildcard_positions)]


def _globs_overlap(left: list[str], right: list[str]) -> bool:
    for left_pattern in left:
        if not isinstance(left_pattern, str) or not left_pattern.strip():
            continue
        for right_pattern in right:
            if not isinstance(right_pattern, str) or not right_pattern.strip():
                continue
            if fnmatch.fnmatch(left_pattern, right_pattern) or fnmatch.fnmatch(right_pattern, left_pattern):
                return True
            left_prefix = _glob_prefix(left_pattern)
            right_prefix = _glob_prefix(right_pattern)
            if left_prefix and right_prefix and (left_prefix.startswith(right_prefix) or right_prefix.startswith(left_prefix)):
                return True
    return False


def _reviewed_completed_subagent_run_ids(data: dict, task_id: str) -> set[str]:
    runs = data.get("subagent_runs", [])
    if not isinstance(runs, list):
        return set()
    ids: set[str] = set()
    for run in runs:
        if not isinstance(run, dict):
            continue
        if (
            run.get("owner_task") == task_id
            and run.get("status") == "completed"
            and run.get("review_status") == "accepted"
            and _has_substantive_value(run.get("id"))
        ):
            ids.add(str(run["id"]))
    return ids


def _latest_dispatch_by_task(data: dict) -> dict[str, dict]:
    decisions = data.get("dispatch_decisions", [])
    latest: dict[str, dict] = {}
    if not isinstance(decisions, list):
        return latest
    for item in decisions:
        if isinstance(item, dict) and isinstance(item.get("task_id"), str):
            latest[item["task_id"]] = item
    return latest


def _expected_strategy_from_dispatch(decision: dict) -> tuple[str | None, str | None]:
    raw_decision = decision.get("decision")
    if raw_decision == "delegate":
        return "delegated", decision.get("reason")
    if raw_decision == "local_fallback":
        return "local_fallback", decision.get("reason")
    return None, None


def _validate_strategy_override(task_id: str, task: dict, errors: list[str]) -> None:
    override = task.get("subagent_strategy_override")
    if not isinstance(override, dict):
        errors.append(f"{task_id}: subagent_strategy_override required when dispatch decision and final strategy differ")
        return
    for key in ("from_reason", "to_reason", "changed_at", "evidence", "operator_decision"):
        if not _has_substantive_value(override.get(key)):
            errors.append(f"{task_id}: subagent_strategy_override.{key} must be non-empty")
    if _parse_ts(override.get("changed_at")) is None:
        errors.append(f"{task_id}: subagent_strategy_override.changed_at must be an ISO timestamp")


def _normalize_path_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value.rstrip("/")


def _validate_boundary_attestation(data: dict, run: dict, prefix: str, errors: list[str]) -> None:
    strict = data.get("subagent_boundary_schema_version") == "1"
    if not strict:
        return
    if run.get("status") != "completed" or run.get("review_status") != "accepted":
        return
    attestation = run.get("boundary_attestation")
    if not isinstance(attestation, dict):
        errors.append(f"{prefix}.boundary_attestation required for accepted delegated run")
        return
    for key in sorted(REQUIRED_BOUNDARY_ATTESTATION_FIELDS):
        if key not in attestation:
            errors.append(f"{prefix}.boundary_attestation missing field {key}")
    if attestation.get("schema_version") != "1":
        errors.append(f"{prefix}.boundary_attestation.schema_version must be 1")
    execution_worktree = _normalize_path_text(data.get("execution_worktree") or data.get("worktree"))
    worker_git_root = _normalize_path_text(attestation.get("worker_git_root"))
    if execution_worktree and worker_git_root != execution_worktree:
        errors.append(f"{prefix}.boundary_attestation.worker_git_root must match execution_worktree")
    worker_cwd = _normalize_path_text(attestation.get("worker_cwd"))
    if execution_worktree and worker_cwd and not worker_cwd.startswith(execution_worktree):
        errors.append(f"{prefix}.boundary_attestation.worker_cwd must be inside execution_worktree")
    if attestation.get("execution_worktree_match") is not True:
        errors.append(f"{prefix}.boundary_attestation.execution_worktree_match must be true")
    if attestation.get("source_workspace_unchanged") is not True and not isinstance(
        run.get("operator_boundary_override"), dict
    ):
        errors.append(f"{prefix}.boundary_attestation.source_workspace_unchanged requires operator_boundary_override")
    dirty_scope_after = attestation.get("dirty_scope_after")
    if not isinstance(dirty_scope_after, list):
        errors.append(f"{prefix}.boundary_attestation.dirty_scope_after must be a list")
    for sha_key in (
        "worker_head_before",
        "worker_head_after",
        "source_workspace_head_before",
        "source_workspace_head_after",
    ):
        sha = attestation.get(sha_key)
        if not isinstance(sha, str) or HEX_SHA_RE.match(sha) is None:
            errors.append(f"{prefix}.boundary_attestation.{sha_key} must be a 40-character lowercase hex git sha")


def _attempt_group_for(run: dict) -> str:
    value = run.get("attempt_group")
    if isinstance(value, str) and value.strip():
        return value
    owner = str(run.get("owner_task") or "")
    scope = ",".join(item for item in run.get("write_scope", []) if isinstance(item, str))
    return f"{owner}:{scope}"


def _validate_attempt_lineage(runs: list[dict], errors: list[str]) -> None:
    final_by_group: dict[str, list[str]] = {}
    ids = {str(run.get("id")) for run in runs if isinstance(run, dict) and _has_substantive_value(run.get("id"))}
    for index, run in enumerate(runs):
        if not isinstance(run, dict):
            continue
        prefix = f"subagent_runs[{index}]"
        accepted_as_final = run.get("accepted_as_final")
        if accepted_as_final is not None and not isinstance(accepted_as_final, bool):
            errors.append(f"{prefix}.accepted_as_final must be a boolean")
        attempt_index = run.get("attempt_index")
        if attempt_index is not None and (not isinstance(attempt_index, int) or attempt_index < 1):
            errors.append(f"{prefix}.attempt_index must be a positive integer")
        superseded_by = run.get("superseded_by")
        if superseded_by is not None and str(superseded_by) not in ids:
            errors.append(f"{prefix}.superseded_by must reference another subagent run id")
        if run.get("review_status") == "accepted" and accepted_as_final is not False:
            final_by_group.setdefault(_attempt_group_for(run), []).append(str(run.get("id")))
    for group, run_ids in final_by_group.items():
        if len(run_ids) > 1:
            errors.append(f"multiple final accepted subagent attempts for {group}: {', '.join(run_ids)}")


def _validate_subagents(data: dict, errors: list[str]) -> None:
    requested = data.get("subagents_requested")
    runs = data.get("subagent_runs", [])
    if requested is None:
        errors.append("subagents_requested must be recorded; default is true because subagents=on is the default")
    elif not isinstance(requested, bool):
        errors.append("subagents_requested must be a boolean")
    if runs is None:
        runs = []
    if not isinstance(runs, list):
        errors.append("subagent_runs must be a list")
        return
    if runs and requested is not True:
        errors.append("subagent_runs requires subagents_requested=true")
    outcome = data.get("lifecycle_outcome")
    current_task = data.get("current_task")
    tasks = data.get("tasks")
    task_ids = set(tasks.keys()) if isinstance(tasks, dict) else set()
    current_files: list[str] = []
    if isinstance(tasks, dict) and isinstance(tasks.get(current_task), dict):
        current_files = tasks[current_task].get("files_declared") or []
    active_scopes: list[tuple[int, list[str], object]] = []
    for index, run in enumerate(runs):
        prefix = f"subagent_runs[{index}]"
        if not isinstance(run, dict):
            errors.append(f"{prefix} must be an object")
            continue
        for key in sorted(REQUIRED_SUBAGENT_FIELDS):
            if key not in run:
                errors.append(f"{prefix} missing field {key}")
        owner_task = run.get("owner_task")
        if owner_task not in task_ids:
            errors.append(f"{prefix}.owner_task must reference a task in state")
        if run.get("status") not in VALID_SUBAGENT_STATUSES:
            errors.append(f"{prefix}.status invalid")
        write_scope = run.get("write_scope")
        if not isinstance(write_scope, list) or not any(isinstance(item, str) and item.strip() for item in write_scope):
            errors.append(f"{prefix}.write_scope must be a non-empty list")
            write_scope = []
        else:
            write_scope = [item for item in write_scope if isinstance(item, str) and item.strip()]
        if run.get("status") == "completed":
            for key in sorted(COMPLETED_SUBAGENT_FIELDS):
                if key not in run:
                    errors.append(f"{prefix} missing completed field {key}")
            if run.get("review_status") not in VALID_SUBAGENT_REVIEW_STATUSES:
                errors.append(f"{prefix}.review_status invalid")
            changed = run.get("changed_files")
            if not isinstance(changed, list):
                errors.append(f"{prefix}.changed_files must be a list")
                changed = []
            for changed_file in changed:
                if isinstance(changed_file, str) and changed_file.strip() and not _matches_any(changed_file, write_scope):
                    errors.append(f"{prefix}.changed_files must match write_scope: {changed_file}")
            _validate_boundary_attestation(data, run, prefix, errors)
        if outcome == "finished" and run.get("status") in {"queued", "running"}:
            errors.append(f"{prefix}: running subagent cannot remain in finished state")
        if outcome == "finished" and run.get("review_status") == "unreviewed":
            errors.append(f"{prefix}: review_status=unreviewed cannot remain in finished state")
        changed = run.get("changed_files") if isinstance(run.get("changed_files"), list) else []
        overlaps = [path for path in changed + write_scope if isinstance(path, str) and _matches_any(path, current_files)]
        if overlaps and not _has_substantive_value(run.get("overlap_rationale")):
            errors.append(f"{prefix}: overlap_rationale required for current task write overlap")
        if run.get("status") in {"queued", "running"} and write_scope:
            active_scopes.append((index, write_scope, run.get("overlap_rationale")))
    for left_index, (index, scope, rationale) in enumerate(active_scopes):
        for other_index, other_scope, other_rationale in active_scopes[left_index + 1 :]:
            if _globs_overlap(scope, other_scope) and not (
                _has_substantive_value(rationale) and _has_substantive_value(other_rationale)
            ):
                errors.append(
                    f"subagent_runs[{index}] and subagent_runs[{other_index}]: active subagent write_scope overlap requires overlap_rationale"
                )
    _validate_attempt_lineage([run for run in runs if isinstance(run, dict)], errors)


def _validate_command_observations(data: dict, errors: list[str]) -> None:
    observations = data.get("command_observations", [])
    if observations is None:
        return
    if not isinstance(observations, list):
        errors.append("command_observations must be a list")
        return
    unknown_commands: list[str] = []
    for index, observation in enumerate(observations):
        prefix = f"command_observations[{index}]"
        if not isinstance(observation, dict):
            errors.append(f"{prefix} must be an object")
            continue
        for key in sorted(REQUIRED_COMMAND_OBSERVATION_FIELDS):
            if key not in observation:
                errors.append(f"{prefix} missing field {key}")
        if observation.get("category") not in VALID_COMMAND_OBSERVATION_CATEGORIES:
            errors.append(f"{prefix}.category invalid")
        if observation.get("category") == "unknown":
            unknown_commands.append(str(observation.get("command", "")))
    if data.get("lifecycle_outcome") == "finished" and unknown_commands:
        audit = data.get("completion_audit") if isinstance(data.get("completion_audit"), dict) else {}
        risk_text = json.dumps(audit.get("residual_risk", []), ensure_ascii=False)
        for command in unknown_commands:
            if command and command not in risk_text:
                errors.append(f"unknown command observation must be mentioned in completion_audit.residual_risk: {command}")


def _validate_cache_fields(data: dict, errors: list[str]) -> None:
    strategy = data.get("cache_strategy")
    if strategy is not None:
        if not isinstance(strategy, dict):
            errors.append("cache_strategy must be an object")
        else:
            if strategy.get("mode") not in VALID_CACHE_STRATEGY_MODES:
                errors.append(f"cache_strategy.mode must be one of {sorted(VALID_CACHE_STRATEGY_MODES)}")
            if strategy.get("provider_cache_control") not in VALID_PROVIDER_CACHE_CONTROL:
                errors.append(
                    f"cache_strategy.provider_cache_control must be one of {sorted(VALID_PROVIDER_CACHE_CONTROL)}"
                )
            for key in ("stable_prefix_policy", "prompt_audit_version"):
                if key in strategy and not isinstance(strategy[key], str):
                    errors.append(f"cache_strategy.{key} must be a string")

    observations = data.get("cache_observations", [])
    if observations is None:
        observations = []
    if not isinstance(observations, list):
        errors.append("cache_observations must be a list")
    else:
        for index, observation in enumerate(observations):
            prefix = f"cache_observations[{index}]"
            if not isinstance(observation, dict):
                errors.append(f"{prefix} must be an object")
                continue
            for key in ("observed_at", "source", "unit", "mode", "model"):
                if key not in observation or not isinstance(observation.get(key), str):
                    errors.append(f"{prefix}.{key} must be a string")
            if _parse_ts(observation.get("observed_at")) is None:
                errors.append(f"{prefix}.observed_at must be an ISO timestamp")
            for key in sorted(TOKEN_FIELDS):
                value = observation.get(key)
                if value is not None and (not isinstance(value, int) or value < 0):
                    errors.append(f"{prefix}.{key} must be a non-negative integer or null")

    audit = data.get("prompt_audit")
    if audit is not None:
        if not isinstance(audit, dict):
            errors.append("prompt_audit must be an object")
        else:
            if "last_checked_at" in audit and _parse_ts(audit.get("last_checked_at")) is None:
                errors.append("prompt_audit.last_checked_at must be an ISO timestamp")
            for key in ("stable_prefix_hashes", "stable_prefix_bytes"):
                if key in audit and not isinstance(audit.get(key), dict):
                    errors.append(f"prompt_audit.{key} must be an object")
            bytes_map = audit.get("stable_prefix_bytes")
            if isinstance(bytes_map, dict):
                for name, value in bytes_map.items():
                    if not isinstance(name, str) or not isinstance(value, int) or value < 0:
                        errors.append("prompt_audit.stable_prefix_bytes values must be non-negative integers")
                        break
            hash_map = audit.get("stable_prefix_hashes")
            if isinstance(hash_map, dict):
                for name, value in hash_map.items():
                    if not isinstance(name, str) or not isinstance(value, str) or not value.strip():
                        errors.append("prompt_audit.stable_prefix_hashes values must be non-empty strings")
                        break
            violations = audit.get("dynamic_marker_violations", [])
            if not isinstance(violations, list):
                errors.append("prompt_audit.dynamic_marker_violations must be a list")
            elif data.get("lifecycle_outcome") == "finished" and violations:
                errors.append("prompt_audit.dynamic_marker_violations must be empty when lifecycle_outcome is finished")


def _validate_graphify_audit(data: dict, errors: list[str]) -> None:
    audit = data.get("graphify_audit")
    if audit is None:
        return
    if not isinstance(audit, dict):
        errors.append("graphify_audit must be an object")
        return
    if audit.get("schema_version") != "1":
        errors.append("graphify_audit.schema_version must be 1")
    for key in ("graphify_present", "update_required"):
        if key in audit and not isinstance(audit[key], bool):
            errors.append(f"graphify_audit.{key} must be a boolean")
    if audit.get("fresh") is not None and not isinstance(audit.get("fresh"), bool):
        errors.append("graphify_audit.fresh must be a boolean or null")
    for key in ("warnings", "errors"):
        if key in audit and not isinstance(audit[key], list):
            errors.append(f"graphify_audit.{key} must be a list")
    if data.get("lifecycle_outcome") == "finished" and audit.get("errors"):
        errors.append("graphify_audit.errors must be empty when lifecycle_outcome is finished")
    if data.get("lifecycle_outcome") == "finished":
        completion = data.get("completion_audit") if isinstance(data.get("completion_audit"), dict) else {}
        evidence_text = json.dumps(completion.get("verification_evidence", []), ensure_ascii=False).lower()
        if "graphify" not in evidence_text:
            errors.append("graphify_audit must be referenced in completion_audit.verification_evidence")


def _validate_plan_executability_audit(data: dict, errors: list[str]) -> None:
    audit = data.get("plan_executability_audit")
    if audit is None:
        return
    if not isinstance(audit, dict):
        errors.append("plan_executability_audit must be an object")
        return
    if not _has_substantive_value(audit.get("path")):
        errors.append("plan_executability_audit.path must be non-empty")
    elif isinstance(data.get("run_dir"), str) and not _path_is_under(audit["path"], data["run_dir"]):
        errors.append("plan_executability_audit.path must live under run_dir")
    if audit.get("grade") not in {"green", "yellow", "red"}:
        errors.append("plan_executability_audit.grade must be green, yellow, or red")
    if "raw_grade" in audit and audit.get("raw_grade") not in {"green", "yellow", "red"}:
        errors.append("plan_executability_audit.raw_grade must be green, yellow, or red")
    for key in ("blocking_issue_count", "fixable_issue_count"):
        value = audit.get(key)
        if not isinstance(value, int) or value < 0:
            errors.append(f"plan_executability_audit.{key} must be a non-negative integer")
    for key in ("raw_blocking_issue_count", "raw_fixable_issue_count"):
        if key in audit:
            value = audit.get(key)
            if not isinstance(value, int) or value < 0:
                errors.append(f"plan_executability_audit.{key} must be a non-negative integer")
    raw_blocking = audit.get("raw_blocking_issue_count")
    effective_blocking = audit.get("blocking_issue_count")
    if isinstance(raw_blocking, int) and isinstance(effective_blocking, int) and effective_blocking < raw_blocking:
        if not audit.get("operator_reviewed_blocking_issues") or not audit.get("operator_decision"):
            errors.append("plan_executability_audit reduced blocking count requires operator review evidence")
    quality = data.get("run_quality") if isinstance(data.get("run_quality"), dict) else {}
    readiness = quality.get("readiness") if isinstance(quality.get("readiness"), dict) else {}
    expected = audit.get("fixable_issue_count")
    observed = readiness.get("plan_executability_fixable_issue_count")
    if expected is not None and observed is not None and expected != observed:
        errors.append("plan_executability_audit fixable count must match run_quality readiness")
    if isinstance(audit.get("path"), str) and Path(audit["path"]).is_file():
        try:
            artifact = json.loads(Path(audit["path"]).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            if data.get("lifecycle_outcome") == "finished":
                errors.append(f"plan_executability_audit artifact is not readable JSON: {exc}")
            artifact = {}
        summary = artifact.get("summary") if isinstance(artifact.get("summary"), dict) else artifact
        if isinstance(summary, dict):
            artifact_blocking = summary.get("blocking_issue_count")
            artifact_fixable = summary.get("fixable_issue_count")
            if isinstance(audit.get("raw_blocking_issue_count"), int) and artifact_blocking != audit.get("raw_blocking_issue_count"):
                errors.append("plan_executability_audit raw blocking count must match artifact")
            if isinstance(audit.get("raw_fixable_issue_count"), int) and artifact_fixable != audit.get("raw_fixable_issue_count"):
                errors.append("plan_executability_audit raw fixable count must match artifact")
    if data.get("lifecycle_outcome") == "finished" and audit.get("grade") == "red":
        errors.append("finished state cannot retain red plan_executability_audit")


def _validate_dispatch_decisions(data: dict, errors: list[str]) -> None:
    decisions = data.get("dispatch_decisions", [])
    if decisions is None:
        return
    if not isinstance(decisions, list):
        errors.append("dispatch_decisions must be a list")
        return
    for index, item in enumerate(decisions):
        prefix = f"dispatch_decisions[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix} must be an object")
            continue
        if item.get("decision") not in {"delegate", "local_fallback", "block"}:
            errors.append(f"{prefix}.decision must be delegate, local_fallback, or block")
        if not _has_substantive_value(item.get("reason")):
            errors.append(f"{prefix}.reason must be non-empty")
        if not isinstance(item.get("failed_prerequisites", []), list):
            errors.append(f"{prefix}.failed_prerequisites must be a list")
        if data.get("lifecycle_outcome") == "finished" and item.get("decision") == "block":
            errors.append(f"{prefix}: block decision cannot remain in finished state")


def _validate_failure_state(data: dict, errors: list[str]) -> None:
    blocker = data.get("current_blocker")
    outcome = data.get("lifecycle_outcome")
    if blocker is not None:
        if not isinstance(blocker, dict):
            errors.append("current_blocker must be an object")
        else:
            if blocker.get("category") not in VALID_BLOCKER_CATEGORIES:
                errors.append(f"current_blocker.category must be one of {sorted(VALID_BLOCKER_CATEGORIES)}")
            if not _has_substantive_value(blocker.get("summary")):
                errors.append("current_blocker.summary must be non-empty")
            if not isinstance(blocker.get("recoverable"), bool):
                errors.append("current_blocker.recoverable must be a boolean")
            if blocker.get("next_action_kind") not in VALID_NEXT_ACTION_KINDS:
                errors.append(f"current_blocker.next_action_kind must be one of {sorted(VALID_NEXT_ACTION_KINDS)}")
    if outcome == "finished" and blocker is not None:
        errors.append("current_blocker must be cleared before lifecycle_outcome=finished")
    if outcome == "blocked":
        if not isinstance(blocker, dict):
            errors.append("blocked outcome requires current_blocker")
        elif blocker.get("recoverable") is not True:
            errors.append("blocked outcome requires a recoverable current_blocker")

    failure = data.get("failure_decision")
    if failure is not None:
        if not isinstance(failure, dict):
            errors.append("failure_decision must be an object")
        else:
            if failure.get("decision") not in {"failed", "block", "fail"}:
                errors.append("failure_decision.decision must be failed, block, or fail")
            if not _has_substantive_value(failure.get("reason")):
                errors.append("failure_decision.reason must be non-empty")
    if outcome == "failed" and not isinstance(failure, dict):
        nonrecoverable = isinstance(blocker, dict) and blocker.get("recoverable") is False
        if not nonrecoverable:
            errors.append("failed outcome requires failure_decision or non-recoverable current_blocker")

    attempts = data.get("recovery_attempts", [])
    if attempts is None:
        return
    if not isinstance(attempts, list):
        errors.append("recovery_attempts must be a list")
        return
    for index, attempt in enumerate(attempts):
        prefix = f"recovery_attempts[{index}]"
        if not isinstance(attempt, dict):
            errors.append(f"{prefix} must be an object")
            continue
        if not _has_substantive_value(attempt.get("root_signature")):
            errors.append(f"{prefix}.root_signature must be non-empty")
        if attempt.get("status") not in {"open", "closed", "abandoned"}:
            errors.append(f"{prefix}.status must be open, closed, or abandoned")
        if outcome == "finished" and attempt.get("status") == "open":
            errors.append(f"{prefix}: open recovery attempt cannot remain in finished state")


def _validate_progress_and_trajectory(data: dict, errors: list[str]) -> None:
    ledger = data.get("progress_ledger", {})
    if ledger is not None:
        if not isinstance(ledger, dict):
            errors.append("progress_ledger must be an object")
        else:
            for task_id, entry in ledger.items():
                if not isinstance(entry, dict):
                    errors.append(f"progress_ledger[{task_id}] must be an object")
                    continue
                for key in ("goal_satisfied", "progress_made", "needs_operator"):
                    if key in entry and not isinstance(entry[key], bool):
                        errors.append(f"progress_ledger[{task_id}].{key} must be a boolean")
                if "stall_count" in entry and (not isinstance(entry["stall_count"], int) or entry["stall_count"] < 0):
                    errors.append(f"progress_ledger[{task_id}].stall_count must be a non-negative integer")
    trajectory_path = data.get("trajectory_path")
    if trajectory_path is not None:
        if not isinstance(trajectory_path, str) or not trajectory_path.strip():
            errors.append("trajectory_path must be a non-empty string")
        elif isinstance(data.get("run_dir"), str) and not _path_is_under(trajectory_path, data["run_dir"]):
            errors.append("trajectory_path must live under run_dir")


def _validate_operational_run_quality(data: dict, errors: list[str]) -> None:
    boundary_schema = data.get("subagent_boundary_schema_version")
    if boundary_schema is not None and boundary_schema != "1":
        errors.append("subagent_boundary_schema_version must be 1 when present")

    run_id = data.get("run_id")
    source_workspace = data.get("source_workspace")
    if source_workspace is not None and not isinstance(source_workspace, str):
        errors.append("source_workspace must be a string")

    execution_worktree = data.get("execution_worktree")
    if execution_worktree is not None:
        if not isinstance(execution_worktree, str) or not execution_worktree.strip():
            errors.append("execution_worktree must be a non-empty string")
        elif isinstance(run_id, str) and not _has_codex_suffix(execution_worktree, "worktrees", run_id):
            errors.append("execution_worktree must end with .codex/worktrees/<run_id>")
        if isinstance(data.get("worktree"), str) and execution_worktree != data.get("worktree"):
            errors.append("execution_worktree must equal worktree when both are present")

    evidence = data.get("command_cwd_evidence", [])
    if evidence is not None:
        if not isinstance(evidence, list):
            errors.append("command_cwd_evidence must be a list")
        else:
            for index, item in enumerate(evidence):
                prefix = f"command_cwd_evidence[{index}]"
                if not isinstance(item, dict):
                    errors.append(f"{prefix} must be an object")
                    continue
                for key in ("command", "cwd", "phase", "status"):
                    if not _has_substantive_value(item.get(key)):
                        errors.append(f"{prefix}.{key} must be non-empty")

    policy = data.get("delegation_policy")
    if policy is not None:
        if not isinstance(policy, dict):
            errors.append("delegation_policy must be an object")
        else:
            if policy.get("requested_mode") not in {"on", "auto", "off"}:
                errors.append("delegation_policy.requested_mode must be on, auto, or off")
            if policy.get("requested_source") not in VALID_DELEGATION_REQUESTED_SOURCES:
                errors.append("delegation_policy.requested_source invalid")
            if not isinstance(policy.get("explicit_user_delegation_request"), bool):
                errors.append("delegation_policy.explicit_user_delegation_request must be a boolean")
            if policy.get("spawn_policy") not in VALID_SPAWN_POLICIES:
                errors.append("delegation_policy.spawn_policy invalid")
            if policy.get("effective_mode") not in VALID_DELEGATION_EFFECTIVE_MODES:
                errors.append("delegation_policy.effective_mode invalid")
            if policy.get("effective_mode") in {"local_fallback", "blocked"} and not _has_substantive_value(
                policy.get("reason")
            ):
                errors.append("delegation_policy.reason must explain local_fallback or blocked mode")
            policy_kind = policy.get("policy_kind")
            if policy_kind is not None and policy_kind not in VALID_DELEGATION_POLICY_KINDS:
                errors.append("delegation_policy.policy_kind must be legacy or adaptive")
            safety_gate = policy.get("safety_gate")
            if safety_gate is not None and safety_gate not in VALID_DELEGATION_SAFETY_GATES:
                errors.append("delegation_policy.safety_gate invalid")
            value_gate = policy.get("value_gate")
            if value_gate is not None and value_gate not in VALID_DELEGATION_VALUE_GATES:
                errors.append("delegation_policy.value_gate invalid")
            signals = policy.get("signals")
            if signals is not None and not isinstance(signals, dict):
                errors.append("delegation_policy.signals must be an object")
            would_have_decision = policy.get("would_have_decision")
            if "would_have_decision" in policy and would_have_decision not in VALID_WOULD_HAVE_DECISIONS:
                errors.append("delegation_policy.would_have_decision invalid")
            would_have_value_gate = policy.get("would_have_value_gate")
            if "would_have_value_gate" in policy and would_have_value_gate not in VALID_WOULD_HAVE_VALUE_GATES:
                errors.append("delegation_policy.would_have_value_gate invalid")
            if any(
                key in policy
                for key in ("would_have_decision", "would_have_reason", "would_have_value_gate")
            ) and not _has_substantive_value(policy.get("would_have_reason")):
                errors.append("delegation_policy.would_have_reason must be non-empty")
            if (
                policy.get("effective_mode") == "local_fallback"
                and policy.get("value_gate") == "local_fast_path"
                and policy.get("reason") not in VALID_ADAPTIVE_LOCAL_FAST_PATH_REASONS
            ):
                errors.append("delegation_policy.reason must be a known adaptive local fast path reason")

    capability = data.get("delegation_capability")
    if capability is not None:
        if not isinstance(capability, dict):
            errors.append("delegation_capability must be an object")
        else:
            if capability.get("schema_version") != "1":
                errors.append("delegation_capability.schema_version must be 1")
            if capability.get("spawn_policy") not in VALID_SPAWN_POLICIES:
                errors.append("delegation_capability.spawn_policy invalid")
            if not isinstance(capability.get("explicit_user_delegation_request"), bool):
                errors.append("delegation_capability.explicit_user_delegation_request must be a boolean")
            if capability.get("run_level_effective_mode") not in VALID_DELEGATION_EFFECTIVE_MODES:
                errors.append("delegation_capability.run_level_effective_mode invalid")
            if not _has_substantive_value(capability.get("reason")):
                errors.append("delegation_capability.reason must be non-empty")

    agentlens_status = data.get("agentlens_status")
    if agentlens_status is not None:
        if not isinstance(agentlens_status, dict):
            errors.append("agentlens_status must be an object")
        else:
            if agentlens_status.get("schema_version") != "1":
                errors.append("agentlens_status.schema_version must be 1")
            if agentlens_status.get("status") not in VALID_AGENTLENS_STATUSES:
                errors.append("agentlens_status.status invalid")
            if not isinstance(agentlens_status.get("blocking"), bool):
                errors.append("agentlens_status.blocking must be a boolean")

    bootstrap = data.get("preflight_bootstrap")
    if bootstrap is not None:
        if not isinstance(bootstrap, dict):
            errors.append("preflight_bootstrap must be an object")
        else:
            if bootstrap.get("schema_version") != "1":
                errors.append("preflight_bootstrap.schema_version must be 1")
            for key in ("warnings", "bootstrap_plan"):
                if not isinstance(bootstrap.get(key, []), list):
                    errors.append(f"preflight_bootstrap.{key} must be a list")
            if not isinstance(bootstrap.get("environment_capabilities", {}), dict):
                errors.append("preflight_bootstrap.environment_capabilities must be an object")

    quality = data.get("run_quality")
    v222_operational = any(
        key in data
        for key in (
            "source_workspace",
            "execution_worktree",
            "command_cwd_evidence",
            "delegation_policy",
            "preflight_bootstrap",
            "run_quality",
        )
    )
    if data.get("lifecycle_outcome") == "finished" and v222_operational and quality is None:
        errors.append("run_quality must be present for finished operational-quality state")
        return
    if quality is not None:
        if not isinstance(quality, dict):
            errors.append("run_quality must be an object")
        else:
            if quality.get("schema_version") != "1":
                errors.append("run_quality.schema_version must be 1")
            if quality.get("validation_status") not in VALID_RUN_QUALITY_VALIDATION_STATUSES:
                errors.append("run_quality.validation_status invalid")
            for key in ("stale", "workspace_matches_execution_worktree"):
                if key in quality and not isinstance(quality[key], bool):
                    errors.append(f"run_quality.{key} must be a boolean")
            for key in ("schema_drift", "open_followups"):
                if key in quality and not isinstance(quality[key], list):
                    errors.append(f"run_quality.{key} must be a list")
            followups = quality.get("open_followups")
            if isinstance(followups, list):
                if quality.get("grade") == "green" and followups:
                    errors.append("run_quality.grade must be yellow or red when open_followups is non-empty")
                if quality.get("grade") == "yellow" and not followups:
                    errors.append("run_quality.grade yellow requires at least one open_followup")

                if run_quality_debt is not None and data.get("lifecycle_outcome") == "finished" and v222_operational:
                    required_followups = run_quality_debt.stable_followups(data, missing_execution_worktree=False)
                    for item in required_followups:
                        if item not in followups:
                            errors.append(f"run_quality.open_followups missing required followup: {item}")
            score = quality.get("score")
            if score is not None and (not isinstance(score, int) or score < 0 or score > 100):
                errors.append("run_quality.score must be an integer from 0 to 100")
            grade = quality.get("grade")
            if grade is not None and grade not in {"green", "yellow", "red"}:
                errors.append("run_quality.grade must be green, yellow, or red")
            for key in ("readiness", "dispatch_consistency", "context_quality", "verification_quality"):
                if data.get("lifecycle_outcome") == "finished" and v222_operational and key not in quality:
                    errors.append(f"run_quality.{key} must be present for finished operational-quality state")
                elif key in quality and not isinstance(quality[key], dict):
                    errors.append(f"run_quality.{key} must be an object")
            if "recommendations" in quality and not isinstance(quality["recommendations"], list):
                errors.append("run_quality.recommendations must be a list")
            if "operational_debt" in quality:
                debt = quality.get("operational_debt")
                if not isinstance(debt, dict):
                    errors.append("run_quality.operational_debt must be an object")
                else:
                    if debt.get("schema_version") != "1":
                        errors.append("run_quality.operational_debt.schema_version must be 1")
                    debt_followups = debt.get("followups")
                    if not isinstance(debt_followups, list):
                        errors.append("run_quality.operational_debt.followups must be a list")
                    count = debt.get("count")
                    if not isinstance(count, int) or count < 0:
                        errors.append("run_quality.operational_debt.count must be a non-negative integer")
                    if not isinstance(debt.get("blocking"), bool):
                        errors.append("run_quality.operational_debt.blocking must be a boolean")


def _is_v220_state(data: dict) -> bool:
    if any(key in data for key in V220_TOP_LEVEL_FIELDS):
        return True
    tasks = data.get("tasks")
    if isinstance(tasks, dict):
        for task in tasks.values():
            if isinstance(task, dict) and any(
                key in task
                for key in (
                    "task_packet_path",
                    "task_packet_sha256",
                    "spec_section_ids",
                    "fallback_spec_used",
                    "timing",
                )
            ):
                return True
    return False


def _path_is_under(child: str, parent: str) -> bool:
    try:
        Path(child).resolve(strict=False).relative_to(Path(parent).resolve(strict=False))
    except (ValueError, TypeError):
        return False
    return True


def _validate_decisions_register(value: object, errors: list[str]) -> None:
    if not isinstance(value, list):
        errors.append("decisions_register must be a list")
        return
    for index, decision in enumerate(value):
        prefix = f"decisions_register[{index}]"
        if not isinstance(decision, dict):
            errors.append(f"{prefix} must be an object")
            continue
        for key in sorted(REQUIRED_DECISION_FIELDS):
            if key not in decision:
                errors.append(f"{prefix} missing field {key}")
        for key in ("id", "task", "decision", "made_at"):
            if key in decision and not isinstance(decision[key], str):
                errors.append(f"{prefix}.{key} must be a string")
        if "made_at" in decision and _parse_ts(decision.get("made_at")) is None:
            errors.append(f"{prefix}.made_at must be an ISO timestamp")
        if "files" in decision and not isinstance(decision["files"], list):
            errors.append(f"{prefix}.files must be a list")
        for key in ("supersedes", "superseded_by", "reason"):
            if key in decision and decision[key] is not None and not isinstance(decision[key], str):
                errors.append(f"{prefix}.{key} must be null or a string")


def _validate_preflight_warnings(value: object, errors: list[str]) -> None:
    if not isinstance(value, list):
        errors.append("preflight_warnings must be a list")
        return
    for index, warning in enumerate(value):
        prefix = f"preflight_warnings[{index}]"
        if not isinstance(warning, dict):
            errors.append(f"{prefix} must be an object")
            continue
        if warning.get("kind") not in VALID_PREFLIGHT_WARNING_KINDS:
            errors.append(f"{prefix}.kind must be one of {sorted(VALID_PREFLIGHT_WARNING_KINDS)}")
        if _parse_ts(warning.get("detected_at")) is None:
            errors.append(f"{prefix}.detected_at must be an ISO timestamp")


def _validate_compaction(value: object, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append("compaction must be an object")
        return
    if not isinstance(value.get("points"), list):
        errors.append("compaction.points must be a list")
    if value.get("last_compaction_after_task") is not None and not isinstance(value.get("last_compaction_after_task"), str):
        errors.append("compaction.last_compaction_after_task must be null or a string")
    if not isinstance(value.get("context_drop_count"), int) or value.get("context_drop_count", -1) < 0:
        errors.append("compaction.context_drop_count must be a non-negative integer")


def _validate_subagent_strategy(task_id: str, task: dict, data: dict, errors: list[str]) -> None:
    if data.get("lifecycle_outcome") != "finished" or data.get("subagents_requested") is not True:
        return
    completed = str(task.get("status", "")).lower() in {"complete", "completed", "done", "verified", "pass", "passed"}
    if not completed:
        return
    manifest = task.get("unit_manifest")
    if not isinstance(manifest, dict):
        return
    allowed = manifest.get("allowed_write_globs")
    tool_policy = manifest.get("tool_policy")
    write_capable = (
        tool_policy in {"implementation", "docs"}
        and isinstance(allowed, list)
        and any(isinstance(item, str) and item.strip() for item in allowed)
    )
    if not write_capable:
        return

    strategy = task.get("subagent_strategy")
    if not isinstance(strategy, dict):
        errors.append(f"{task_id}: completed v2.20 subagents=on write task missing subagent_strategy")
        return
    mode = strategy.get("mode")
    if mode not in VALID_SUBAGENT_STRATEGY_MODES:
        errors.append(f"{task_id}: subagent_strategy.mode must be one of {sorted(VALID_SUBAGENT_STRATEGY_MODES)}")
    if not _has_substantive_value(strategy.get("reason")):
        errors.append(f"{task_id}: subagent_strategy.reason must explain the delegation or local fallback")
    reason = strategy.get("reason")
    if (
        mode == "local_fallback"
        and isinstance(reason, str)
        and reason.startswith("adaptive_policy_")
        and reason not in VALID_ADAPTIVE_LOCAL_FAST_PATH_REASONS
    ):
        errors.append(f"{task_id}: subagent_strategy.reason must be a known adaptive local fast path reason")
    run_ids = strategy.get("run_ids")
    if run_ids is None:
        run_ids = []
    if not isinstance(run_ids, list) or not all(isinstance(item, str) and item.strip() for item in run_ids):
        errors.append(f"{task_id}: subagent_strategy.run_ids must be a list of strings")
        run_ids = []
    if mode == "delegated":
        reviewed = _reviewed_completed_subagent_run_ids(data, task_id)
        missing = [run_id for run_id in run_ids if run_id not in reviewed]
        if not run_ids or missing:
            errors.append(f"{task_id}: delegated subagent_strategy requires a reviewed completed subagent_run")
    elif mode == "local_fallback" and run_ids:
        errors.append(f"{task_id}: local_fallback subagent_strategy must not list delegated run_ids")

    latest_dispatch = _latest_dispatch_by_task(data).get(task_id)
    if isinstance(latest_dispatch, dict) and latest_dispatch.get("decision") != "block":
        expected_mode, expected_reason = _expected_strategy_from_dispatch(latest_dispatch)
        if expected_mode and (mode != expected_mode or reason != expected_reason):
            _validate_strategy_override(task_id, task, errors)


def _validate_v220_task(task_id: str, task: dict, data: dict, errors: list[str]) -> None:
    run_dir = data.get("run_dir")
    packet_dir = data.get("task_packet_dir")
    packet_path = task.get("task_packet_path")
    if packet_path is not None:
        if not isinstance(packet_path, str) or not packet_path.strip():
            errors.append(f"{task_id}: task_packet_path must be a non-empty string")
        elif isinstance(packet_dir, str) and not _path_is_under(packet_path, packet_dir):
            errors.append(f"{task_id}: task_packet_path must live under task_packet_dir")
    if "task_packet_sha256" in task and not _has_substantive_value(task.get("task_packet_sha256")):
        errors.append(f"{task_id}: task_packet_sha256 must be non-empty")
    if "spec_section_ids" in task and not isinstance(task.get("spec_section_ids"), list):
        errors.append(f"{task_id}: spec_section_ids must be a list")
    if "fallback_spec_used" in task and not isinstance(task.get("fallback_spec_used"), bool):
        errors.append(f"{task_id}: fallback_spec_used must be a boolean")
    timing = task.get("timing")
    completed = str(task.get("status", "")).lower() in {"complete", "completed", "done", "verified", "pass", "passed"}
    if completed and data.get("lifecycle_outcome") == "finished":
        if not isinstance(timing, dict):
            errors.append(f"{task_id}: completed v2.20 task missing timing")
            return
        for key in ("started", "completed"):
            if _parse_ts(timing.get(key)) is None:
                errors.append(f"{task_id}: timing.{key} must be an ISO timestamp")
    elif timing is not None and not isinstance(timing, dict):
        errors.append(f"{task_id}: timing must be an object")
    if isinstance(run_dir, str) and isinstance(packet_path, str) and not packet_path.startswith(run_dir):
        errors.append(f"{task_id}: task_packet_path must be under run_dir")
    _validate_subagent_strategy(task_id, task, data, errors)


def _validate_v220(data: dict, errors: list[str]) -> None:
    if not _is_v220_state(data):
        return
    run_dir = data.get("run_dir")
    if not isinstance(run_dir, str) or not run_dir.strip():
        return
    expected_manifest = str(Path(run_dir) / "spec_manifest.json")
    if data.get("spec_manifest_path") is not None and data.get("spec_manifest_path") != expected_manifest:
        errors.append("spec_manifest_path must equal run_dir/spec_manifest.json")
    expected_packet_dir = str(Path(run_dir) / "task_packets")
    if data.get("task_packet_dir") is not None and data.get("task_packet_dir") != expected_packet_dir:
        errors.append("task_packet_dir must equal run_dir/task_packets")
    current_packet = data.get("current_task_packet_path")
    packet_dir = data.get("task_packet_dir")
    if current_packet is not None:
        if not isinstance(current_packet, str) or not current_packet.strip():
            errors.append("current_task_packet_path must be a non-empty string")
        elif isinstance(packet_dir, str) and not _path_is_under(current_packet, packet_dir):
            errors.append("current_task_packet_path must live under task_packet_dir")
    _validate_decisions_register(data.get("decisions_register", []), errors)
    _validate_preflight_warnings(data.get("preflight_warnings", []), errors)
    if "compaction" in data:
        _validate_compaction(data.get("compaction"), errors)
    tasks = data.get("tasks") if isinstance(data.get("tasks"), dict) else {}
    last_completed_task = data.get("last_completed_task")
    if last_completed_task is not None and last_completed_task not in tasks:
        errors.append("last_completed_task must be null or reference a task in state")
    if data.get("last_completed_at") is not None and _parse_ts(data.get("last_completed_at")) is None:
        errors.append("last_completed_at must be an ISO timestamp or null")
    for task_id, task in tasks.items():
        if isinstance(task, dict):
            _validate_v220_task(task_id, task, data, errors)


def _validate_legacy(data: dict) -> list[str]:
    errors: list[str] = []
    for key in sorted(REQUIRED_TOP_LEVEL):
        if key not in data:
            errors.append(f"missing top-level field {key}")
    if data.get("mode") not in VALID_MODES:
        errors.append(f"mode must be one of {sorted(VALID_MODES)}")
    _validate_paths(data, errors)
    if data.get("mode") in EXECUTION_MODES and data.get("current_phase") != "preflight":
        if not _has_substantive_value(data.get("context_snapshot_path")):
            errors.append("context_snapshot_path must be present after execution preflight")
    _validate_context_health(data, errors)
    _validate_completion_audit(data, errors)
    _validate_timestamps(data, errors)
    _validate_tasks(data, errors)
    _validate_subagents(data, errors)
    _validate_command_observations(data, errors)
    _validate_cache_fields(data, errors)
    _validate_graphify_audit(data, errors)
    _validate_plan_executability_audit(data, errors)
    _validate_dispatch_decisions(data, errors)
    _validate_failure_state(data, errors)
    _validate_progress_and_trajectory(data, errors)
    _validate_operational_run_quality(data, errors)
    _validate_v220(data, errors)
    return errors


def validate(data: dict) -> list[str]:
    return validate_state_domains(data, legacy_validate=_validate_legacy)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("state")
    args = parser.parse_args()
    from cpe_runtime.validation import validate_run
    path = Path(args.state).expanduser().resolve()
    report = validate_run(path if path.is_dir() else path.parent)
    print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    if report.classification == "unsupported_schema": return 2
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
