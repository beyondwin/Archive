#!/usr/bin/env python3
"""Validate a kws-codex-plan-executor state file."""

from __future__ import annotations

import argparse
import json
import sys
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
REQUIRED_CONTRACT_FIELDS = {
    "scope",
    "files_to_inspect",
    "allowed_edits",
    "forbidden_edits",
    "acceptance_command_or_honest_substitute",
}
CONTRACT_LIST_FIELDS = {"files_to_inspect", "allowed_edits", "forbidden_edits"}
CONTRACT_STRING_FIELDS = {"scope", "acceptance_command_or_honest_substitute"}


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
    _validate_completion_audit(data, errors)

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
