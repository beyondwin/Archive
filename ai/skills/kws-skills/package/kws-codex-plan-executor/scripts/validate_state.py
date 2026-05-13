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
    expected_run_dir = f".codex-orchestrator/runs/{run_id}" if isinstance(run_id, str) else None
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
