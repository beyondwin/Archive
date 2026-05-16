#!/usr/bin/env python3
"""Validate a kws-codex-plan-executor state file."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


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
VALID_LIFECYCLE_OUTCOMES = {
    "finished",
    "blocked",
    "failed",
    "userinterlude",
    "askuserQuestion",
}
NON_SUCCESS_OUTCOMES = {"blocked", "failed", "userinterlude", "askuserQuestion"}
VALID_CONTEXT_HEALTH_STATUSES = {"green", "yellow", "red"}
VALID_CONTEXT_BUDGET_STATUSES = {"green", "yellow", "red"}
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
REQUIRED_TASK_FIELDS = {
    "status",
    "risk",
    "files_declared",
    "contract",
    "review_retries",
    "verifier_retries",
}
VALID_CARRIED_ACCEPTANCE_STATUSES = {"open", "resolved", "accepted_with_rationale"}
REQUIRED_CARRIED_ACCEPTANCE_FIELDS = {
    "status",
    "metric",
    "current_value",
    "baseline_value",
    "reason",
    "depends_on_task",
    "next_action",
}
REQUIRED_METHOD_AUDIT_FIELDS = {"required", "applied", "missing", "waived"}
REQUIRED_CONTRACT_FIELDS = {
    "scope",
    "files_to_inspect",
    "allowed_edits",
    "forbidden_edits",
    "acceptance_command_or_honest_substitute",
}
CONTRACT_LIST_FIELDS = {"files_to_inspect", "allowed_edits", "forbidden_edits"}
CONTRACT_STRING_FIELDS = {"scope", "acceptance_command_or_honest_substitute"}
VALID_UNIT_TYPES = {
    "research",
    "plan",
    "execute-task",
    "reactive-execute",
    "validate",
    "complete",
    "docs",
    "review",
    "handoff",
}
VALID_CONTEXT_MODES = {"minimal", "focused", "expanded", "full"}
VALID_TOOL_POLICIES = {"read-only", "planning", "implementation", "docs", "verification"}
VALID_ARTIFACT_POLICIES = {"inline", "inline-summary", "excerpt", "on-demand"}
VALID_EVENT_TYPES = {
    "run_started",
    "context_snapshot_created",
    "pre_dispatch_checked",
    "dispatch_gate_failed",
    "task_contract_recorded",
    "task_started",
    "task_completed",
    "verification_started",
    "verification_passed",
    "verification_failed",
    "drift_detected",
    "drift_repaired",
    "blocked",
    "failed",
    "finished",
}
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


def _required_project_path(run_id: str, name: str) -> str:
    return f".codex-orchestrator/runs/{run_id}/{name}"


def _required_run_dir(run_id: str) -> str:
    return f".codex-orchestrator/runs/{run_id}"


def _has_substantive_value(value: object) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return len(value) > 0
    if isinstance(value, dict):
        return len(value) > 0
    return value is True


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


def _validate_context_snapshot(data: dict, errors: list[str]) -> None:
    run_id = data.get("run_id")
    mode = data.get("mode")
    phase = data.get("current_phase")
    context_path = data.get("context_snapshot_path")
    basis_hash = data.get("context_basis_hash")

    if not isinstance(run_id, str) or not run_id.strip():
        return

    context_required = mode in EXECUTION_MODES and phase != "preflight"
    if context_required and not _has_substantive_value(context_path):
        errors.append("context_snapshot_path must be present after execution preflight")
        return

    if context_path is None:
        return
    if not isinstance(context_path, str) or not context_path.strip():
        errors.append("context_snapshot_path must be a non-empty string when present")
        return

    expected_context_path = _required_project_path(run_id, "context.json")
    if context_path != expected_context_path:
        errors.append(f"context_snapshot_path must be {expected_context_path}")
    if not isinstance(basis_hash, str) or not basis_hash.strip():
        errors.append("context_basis_hash must be a non-empty string when context_snapshot_path is present")


def _validate_context_health(data: dict, errors: list[str]) -> None:
    mode = data.get("mode")
    phase = data.get("current_phase")
    outcome = data.get("lifecycle_outcome")
    health = data.get("context_health")

    health_required = mode in EXECUTION_MODES and phase != "preflight"
    if health_required and health is None:
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

    status = health.get("status")
    if status not in VALID_CONTEXT_HEALTH_STATUSES:
        errors.append(f"context_health.status must be one of {sorted(VALID_CONTEXT_HEALTH_STATUSES)}")

    for key in ("context_snapshot_present", "context_basis_hash_recorded", "active_task_contract_present", "handoff_ready"):
        if key in health and not isinstance(health[key], bool):
            errors.append(f"context_health.{key} must be a boolean")

    if "next_action" in health and (not isinstance(health["next_action"], str) or not health["next_action"].strip()):
        errors.append("context_health.next_action must be a non-empty string")

    for key in ("open_questions", "known_assumptions"):
        if key in health and not isinstance(health[key], list):
            errors.append(f"context_health.{key} must be a list")

    if data.get("context_snapshot_path") is not None and health.get("context_snapshot_present") is not True:
        errors.append("context_health.context_snapshot_present must be true when context_snapshot_path is present")
    if data.get("context_basis_hash") is not None and health.get("context_basis_hash_recorded") is not True:
        errors.append("context_health.context_basis_hash_recorded must be true when context_basis_hash is present")

    if status == "green" and _has_substantive_value(health.get("open_questions")):
        errors.append("context_health.open_questions must be empty when status is green")
    if status == "red" and health.get("handoff_ready") is True:
        errors.append("context_health.handoff_ready must be false when status is red")

    if outcome == "finished":
        if health.get("handoff_ready") is not True:
            errors.append("context_health.handoff_ready must be true when lifecycle_outcome is finished")
        if status == "red":
            errors.append("context_health.status must not be red when lifecycle_outcome is finished")
        checked_at = _parse_ts(health.get("last_checked_at"))
        if checked_at is None:
            errors.append("context_health.last_checked_at must be present when lifecycle_outcome is finished")
        timestamps = data.get("timestamps") if isinstance(data.get("timestamps"), dict) else {}
        updated_at = _parse_ts(timestamps.get("updated_at"))
        if updated_at is not None and checked_at is not None and checked_at < updated_at:
            errors.append(
                "context_health.last_checked_at must not be older than timestamps.updated_at when lifecycle_outcome is finished"
            )


def _validate_context_budget(data: dict, errors: list[str]) -> None:
    budget = data.get("context_budget")
    if budget is None:
        return
    if not isinstance(budget, dict):
        errors.append("context_budget must be an object")
        return
    if budget.get("status") not in VALID_CONTEXT_BUDGET_STATUSES:
        errors.append(f"context_budget.status must be one of {sorted(VALID_CONTEXT_BUDGET_STATUSES)}")
    for key in ("max_chars", "estimated_chars"):
        if key in budget and (not isinstance(budget[key], int) or budget[key] < 0):
            errors.append(f"context_budget.{key} must be a non-negative integer")
    if isinstance(budget.get("max_chars"), int) and budget["max_chars"] <= 0:
        errors.append("context_budget.max_chars must be a positive integer")
    for key in ("included_sections", "omitted_sections"):
        if key in budget and not isinstance(budget[key], list):
            errors.append(f"context_budget.{key} must be a list")


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
        evidence = audit.get("verification_evidence")
        if not _has_substantive_value(checklist):
            errors.append("completion_audit.prompt_to_artifact_checklist must be non-empty")
        if not _has_substantive_value(evidence):
            errors.append("completion_audit.verification_evidence must be non-empty")
        return

    if outcome in NON_SUCCESS_OUTCOMES and not _has_substantive_value(data.get("handoff_reason")):
        errors.append("handoff_reason must be non-empty for non-success lifecycle_outcome")


def _validate_carried_acceptance(data: dict, errors: list[str]) -> None:
    outcome = data.get("lifecycle_outcome")
    audit = data.get("completion_audit") if isinstance(data.get("completion_audit"), dict) else {}
    evidence_text = json.dumps(audit.get("verification_evidence", []), sort_keys=True)
    tasks = data.get("tasks")
    if not isinstance(tasks, dict):
        return

    for task_id, task in tasks.items():
        if not isinstance(task, dict) or "carried_acceptance" not in task:
            continue
        carried = task["carried_acceptance"]
        if not isinstance(carried, dict):
            errors.append(f"{task_id}: carried_acceptance must be an object")
            continue

        for key in sorted(REQUIRED_CARRIED_ACCEPTANCE_FIELDS):
            if key not in carried:
                errors.append(f"{task_id}: carried_acceptance missing field {key}")

        status = carried.get("status")
        if status not in VALID_CARRIED_ACCEPTANCE_STATUSES:
            errors.append(
                f"{task_id}: carried_acceptance.status must be one of {sorted(VALID_CARRIED_ACCEPTANCE_STATUSES)}"
            )

        for key in sorted(REQUIRED_CARRIED_ACCEPTANCE_FIELDS - {"status"}):
            if key in carried and not _has_substantive_value(carried[key]):
                errors.append(f"{task_id}: carried_acceptance.{key} must be non-empty")

        if outcome == "finished" and status == "open":
            errors.append(f"{task_id}: open carried_acceptance is not allowed for lifecycle_outcome=finished")

        if outcome == "finished" and status in {"resolved", "accepted_with_rationale"}:
            metric = carried.get("metric")
            if isinstance(metric, str) and metric and metric not in evidence_text:
                errors.append(
                    f"{task_id}: carried_acceptance metric must be referenced by completion_audit.verification_evidence"
                )


def _validate_unit_manifest(data: dict, errors: list[str]) -> None:
    outcome = data.get("lifecycle_outcome")
    tasks = data.get("tasks")
    if not isinstance(tasks, dict):
        return

    for task_id, task in tasks.items():
        if not isinstance(task, dict):
            continue
        manifest = task.get("unit_manifest")
        completed = task.get("status") in {"completed", "verified", "done"}
        if outcome == "finished" and completed and manifest is None:
            errors.append(
                f"{task_id}: unit_manifest is required for completed tasks when lifecycle_outcome is finished"
            )
            continue
        if manifest is None:
            continue
        if not isinstance(manifest, dict):
            errors.append(f"{task_id}: unit_manifest must be an object")
            continue

        for key in sorted(REQUIRED_UNIT_MANIFEST_FIELDS):
            if key not in manifest:
                errors.append(f"{task_id}: unit_manifest missing field {key}")

        if manifest.get("unit_type") not in VALID_UNIT_TYPES:
            errors.append(f"{task_id}: unit_manifest.unit_type must be one of {sorted(VALID_UNIT_TYPES)}")
        if manifest.get("context_mode") not in VALID_CONTEXT_MODES:
            errors.append(f"{task_id}: unit_manifest.context_mode must be one of {sorted(VALID_CONTEXT_MODES)}")
        if manifest.get("tool_policy") not in VALID_TOOL_POLICIES:
            errors.append(f"{task_id}: unit_manifest.tool_policy must be one of {sorted(VALID_TOOL_POLICIES)}")
        if manifest.get("artifact_policy") not in VALID_ARTIFACT_POLICIES:
            errors.append(f"{task_id}: unit_manifest.artifact_policy must be one of {sorted(VALID_ARTIFACT_POLICIES)}")

        for key in ("required_skills", "allowed_write_globs", "forbidden_write_globs"):
            if key in manifest and not isinstance(manifest[key], list):
                errors.append(f"{task_id}: unit_manifest.{key} must be a list")

        max_chars = manifest.get("max_context_chars")
        if not isinstance(max_chars, int) or max_chars <= 0:
            errors.append(f"{task_id}: unit_manifest.max_context_chars must be a positive integer")

        policy = manifest.get("tool_policy")
        allowed = manifest.get("allowed_write_globs")
        if policy == "implementation" and not _has_substantive_value(allowed):
            errors.append(f"{task_id}: implementation unit_manifest requires allowed_write_globs")
        if policy == "read-only" and isinstance(allowed, list) and allowed:
            errors.append(f"{task_id}: read-only unit_manifest must not allow write globs")


def _validate_event_journal(data: dict, errors: list[str]) -> None:
    if data.get("lifecycle_outcome") != "finished":
        return

    run_id = data.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        return

    expected_path = _required_project_path(run_id, "events.jsonl")
    journal_path = data.get("event_journal_path")
    if not isinstance(journal_path, str) or not journal_path.strip():
        errors.append("event_journal_path must be a non-empty string when lifecycle_outcome is finished")
    elif journal_path != expected_path:
        errors.append(f"event_journal_path must be {expected_path}")

    last_seq = data.get("last_event_seq")
    if not isinstance(last_seq, int) or last_seq <= 0:
        errors.append("last_event_seq must be a positive integer when lifecycle_outcome is finished")


def _validate_drift(data: dict, errors: list[str]) -> None:
    if data.get("lifecycle_outcome") != "finished":
        return
    drift = data.get("drift")
    if drift is None:
        return
    if not isinstance(drift, dict):
        errors.append("drift must be an object")
        return
    blockers = drift.get("unrepaired_blockers", [])
    if blockers:
        errors.append("drift.unrepaired_blockers must be empty when lifecycle_outcome is finished")
    records = drift.get("records", [])
    if isinstance(records, list):
        for index, record_item in enumerate(records):
            if isinstance(record_item, dict) and record_item.get("severity") == "blocking":
                errors.append(
                    f"drift.records[{index}] blocking drift is not allowed when lifecycle_outcome is finished"
                )


def _method_skill(entry: object) -> str | None:
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict) and isinstance(entry.get("skill"), str):
        return entry["skill"]
    return None


def _evidence_refs(entry: dict) -> list[str]:
    refs = entry.get("evidence_refs")
    if not isinstance(refs, list):
        return []
    return [item for item in refs if isinstance(item, str)]


def _validate_method_audit(data: dict, errors: list[str]) -> None:
    audit = data.get("method_audit")
    if audit is None:
        return
    if not isinstance(audit, dict):
        errors.append("method_audit must be an object")
        return

    for key in sorted(REQUIRED_METHOD_AUDIT_FIELDS):
        if key not in audit:
            errors.append(f"method_audit missing field {key}")

    required = audit.get("required", [])
    applied = audit.get("applied", [])
    missing = audit.get("missing", [])
    waived = audit.get("waived", [])
    for key, value in (("required", required), ("applied", applied), ("missing", missing), ("waived", waived)):
        if not isinstance(value, list):
            errors.append(f"method_audit.{key} must be a list")
            return

    required_skills = [_method_skill(item) for item in required]
    required_skills = [skill for skill in required_skills if skill]
    applied_by_skill: dict[str, list[dict]] = {}
    missing_by_skill: dict[str, list[object]] = {}
    waived_by_skill: dict[str, list[dict]] = {}

    for entry in applied:
        if not isinstance(entry, dict):
            errors.append("method_audit.applied entries must be objects")
            continue
        skill = _method_skill(entry)
        if not skill:
            errors.append("method_audit.applied entry missing skill")
            continue
        applied_by_skill.setdefault(skill, []).append(entry)
        if entry.get("status") != "applied":
            errors.append(f"{skill}: applied method status must be applied")
        if not _evidence_refs(entry):
            errors.append(f"{skill}: applied method evidence_refs must be non-empty")

    for entry in missing:
        skill = _method_skill(entry)
        if not skill:
            errors.append("method_audit.missing entry missing skill")
            continue
        missing_by_skill.setdefault(skill, []).append(entry)

    for entry in waived:
        if not isinstance(entry, dict):
            errors.append("method_audit.waived entries must be objects")
            continue
        skill = _method_skill(entry)
        if not skill:
            errors.append("method_audit.waived entry missing skill")
            continue
        waived_by_skill.setdefault(skill, []).append(entry)
        if not _has_substantive_value(entry.get("reason")):
            errors.append(f"{skill}: waived method requires a reason")

    for skill in required_skills:
        count = len(applied_by_skill.get(skill, [])) + len(missing_by_skill.get(skill, [])) + len(waived_by_skill.get(skill, []))
        if count == 0:
            errors.append(f"required method {skill} has no applied or waived evidence")
        elif count > 1:
            errors.append(f"required method {skill} must appear in exactly one method_audit bucket")

    if data.get("lifecycle_outcome") == "finished":
        for skill in missing_by_skill:
            errors.append(f"required method {skill} is missing for lifecycle_outcome=finished")

    for entry in applied_by_skill.get("test-driven-development", []):
        refs = [ref.lower() for ref in _evidence_refs(entry)]
        if not any("red" in ref for ref in refs) or not any("green" in ref for ref in refs):
            errors.append("test-driven-development requires RED and GREEN evidence references")

    for entry in applied_by_skill.get("review", []):
        refs = [ref.lower().replace("-", "_") for ref in _evidence_refs(entry)]
        if not any("findings" in ref or "residual_risk" in ref or "no_findings" in ref for ref in refs):
            errors.append("review method requires findings or residual-risk evidence")

    for entry in applied_by_skill.get("verification-before-completion", []):
        refs = _evidence_refs(entry)
        if "completion_audit.verification_evidence" not in refs:
            errors.append("verification-before-completion requires completion_audit.verification_evidence")

    for entry in applied_by_skill.get("using-superpowers", []):
        refs = [ref.lower() for ref in _evidence_refs(entry)]
        if not any("contract" in ref or "pre_task" in ref or "pre-implementation" in ref for ref in refs):
            errors.append("using-superpowers requires task contract or pre-implementation evidence")


def validate(data: object) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["state root must be a JSON object"]

    for key in sorted(REQUIRED_TOP_LEVEL):
        if key not in data:
            errors.append(f"missing top-level field: {key}")

    mode = data.get("mode")
    if mode not in VALID_MODES:
        errors.append(f"mode must be one of {sorted(VALID_MODES)}")

    run_id = data.get("run_id")
    expected_run_dir = _required_run_dir(run_id) if isinstance(run_id, str) else None
    expected_state_path = f"{expected_run_dir}/state.json" if expected_run_dir else None
    if not isinstance(run_id, str) or not run_id.strip():
        errors.append("run_id must be a non-empty string")
    if expected_run_dir and data.get("run_dir") != expected_run_dir:
        errors.append(f"run_dir must be {expected_run_dir}")
    if expected_state_path and data.get("state_path") != expected_state_path:
        errors.append(f"state_path must be {expected_state_path}")

    if not isinstance(data.get("tasks"), dict):
        errors.append("tasks must be an object keyed by task id")
    else:
        for task_id, task in data["tasks"].items():
            if not isinstance(task, dict):
                errors.append(f"{task_id}: task must be an object")
                continue
            for key in sorted(REQUIRED_TASK_FIELDS):
                if key not in task:
                    errors.append(f"{task_id}: missing field {key}")
            if "files_declared" in task and not isinstance(task["files_declared"], list):
                errors.append(f"{task_id}: files_declared must be a list")
            contract = task.get("contract")
            if "contract" in task:
                if not isinstance(contract, dict):
                    errors.append(f"{task_id}: contract must be an object")
                else:
                    for key in sorted(REQUIRED_CONTRACT_FIELDS):
                        if key not in contract:
                            errors.append(f"{task_id}: contract missing field {key}")
                    for key in sorted(CONTRACT_LIST_FIELDS):
                        if key in contract and not isinstance(contract[key], list):
                            errors.append(f"{task_id}: contract.{key} must be a list")
                    for key in sorted(CONTRACT_STRING_FIELDS):
                        if key in contract and not isinstance(contract[key], str):
                            errors.append(f"{task_id}: contract.{key} must be a string")
            for retry_key in ("review_retries", "verifier_retries"):
                if retry_key in task and not isinstance(task[retry_key], int):
                    errors.append(f"{task_id}: {retry_key} must be an integer")

    if "timestamps" in data and not isinstance(data["timestamps"], dict):
        errors.append("timestamps must be an object")

    _validate_context_snapshot(data, errors)
    _validate_context_health(data, errors)
    _validate_context_budget(data, errors)
    _validate_unit_manifest(data, errors)
    _validate_event_journal(data, errors)
    _validate_drift(data, errors)
    _validate_completion_audit(data, errors)
    _validate_carried_acceptance(data, errors)
    _validate_method_audit(data, errors)

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("state_json", help="Path to .codex-orchestrator/runs/<run_id>/state.json")
    args = parser.parse_args()

    path = Path(args.state_json)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"error: state file not found: {path}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print(f"error: invalid JSON: {exc}", file=sys.stderr)
        return 1

    errors = validate(data)
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1

    print("state is valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
