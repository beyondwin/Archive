#!/usr/bin/env python3
"""Manual checks for the headless final result schema."""

from __future__ import annotations

import json
from pathlib import Path


REQUIRED = [
    "status",
    "run_id",
    "state_path",
    "summary",
    "changed_files",
    "verification",
    "open_gaps",
    "residual_risk",
    "next_action",
]
STATUSES = {"success", "blocked", "failed", "cancelled"}
VERIFICATION_STATUSES = {"passed", "failed", "skipped"}


def validate_sample(payload: dict) -> list[str]:
    errors: list[str] = []
    for key in REQUIRED:
        if key not in payload:
            errors.append(f"missing {key}")
    if payload.get("status") not in STATUSES:
        errors.append("invalid status")
    for key in ("run_id", "state_path", "summary", "next_action"):
        if key in payload and (not isinstance(payload[key], str) or not payload[key].strip()):
            errors.append(f"{key} must be a non-empty string")
    for key in ("changed_files", "verification", "open_gaps", "residual_risk"):
        if key in payload and not isinstance(payload[key], list):
            errors.append(f"{key} must be a list")
    for index, item in enumerate(payload.get("verification", [])):
        if not isinstance(item, dict):
            errors.append(f"verification[{index}] must be an object")
            continue
        if not isinstance(item.get("command"), str) or not item.get("command", "").strip():
            errors.append(f"verification[{index}].command must be non-empty")
        if item.get("status") not in VERIFICATION_STATUSES:
            errors.append(f"verification[{index}].status invalid")
    return errors


def valid_payload() -> dict:
    return {
        "status": "success",
        "run_id": "headless-plan-20260519-143022",
        "state_path": "~/.codex/orchestrator/headless-plan-20260519-143022/state.json",
        "summary": "Implemented task 2 and verified state schema checks.",
        "changed_files": ["scripts/validate_state.py", "evals/check_state_schema.py"],
        "verification": [{"command": "python3 evals/check_state_schema.py", "status": "passed"}],
        "open_gaps": [],
        "residual_risk": [],
        "next_action": "Review diff and commit.",
    }


def main() -> int:
    skill_dir = Path(__file__).resolve().parents[1]
    schema_path = skill_dir / "templates" / "headless-output-schema.json"
    checks: dict[str, bool] = {}
    failures: list[str] = []

    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except Exception as exc:
        schema = {}
        failures.append(f"schema should parse as JSON: {exc}")
    checks["schema_json_parses"] = bool(schema)

    checks["schema_required_fields_match"] = schema.get("required") == REQUIRED
    if not checks["schema_required_fields_match"]:
        failures.append("schema required fields should match final result contract")

    status_enum = set(schema.get("properties", {}).get("status", {}).get("enum", []))
    checks["schema_status_enum_matches"] = status_enum == STATUSES
    if not checks["schema_status_enum_matches"]:
        failures.append("schema status enum should match manual validator")

    good = valid_payload()
    checks["valid_payload_passes"] = not validate_sample(good)
    if not checks["valid_payload_passes"]:
        failures.append("valid payload should pass manual validation")

    bad_status = valid_payload()
    bad_status["status"] = "done"
    checks["invalid_status_fails"] = "invalid status" in validate_sample(bad_status)
    if not checks["invalid_status_fails"]:
        failures.append("invalid status should fail")

    missing = valid_payload()
    del missing["state_path"]
    checks["missing_required_fails"] = "missing state_path" in validate_sample(missing)
    if not checks["missing_required_fails"]:
        failures.append("missing required field should fail")

    bad_verification = valid_payload()
    bad_verification["verification"] = [{"command": "pytest", "status": "unknown"}]
    checks["invalid_verification_status_fails"] = "verification[0].status invalid" in validate_sample(
        bad_verification
    )
    if not checks["invalid_verification_status_fails"]:
        failures.append("invalid verification status should fail")

    payload = {"passed": not failures, "checks": checks, "failures": failures}
    print(json.dumps(payload, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
