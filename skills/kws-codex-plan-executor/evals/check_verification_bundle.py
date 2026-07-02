#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from check_state_schema import base_state


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "validate_state.py"


def run_validator(state: dict) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory(prefix="cpe-bundle-") as temp:
        path = Path(temp) / "state.json"
        path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return subprocess.run([sys.executable, str(SCRIPT), str(path)], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def bundle() -> dict:
    return {
        "class": "verification_bundle",
        "name": "cpe_skill_change",
        "commands": ["./evals/run.sh", "python3 -m py_compile scripts/*.py evals/*.py", "bash -n evals/run.sh"],
        "status": "passed",
        "required": False,
    }


def main() -> int:
    failures: list[str] = []
    checks: dict[str, bool] = {}

    valid = base_state()
    valid["completion_audit"]["verification_evidence"].append(bundle())
    result = run_validator(valid)
    checks["valid_bundle_passes"] = result.returncode == 0
    if not checks["valid_bundle_passes"]:
        failures.append("valid verification bundle should pass: " + (result.stderr or result.stdout))

    missing_name = base_state()
    bad = bundle()
    del bad["name"]
    missing_name["completion_audit"]["verification_evidence"].append(bad)
    result = run_validator(missing_name)
    checks["bundle_missing_name_fails"] = result.returncode != 0 and "verification_bundle.name" in (
        result.stderr + result.stdout
    )
    if not checks["bundle_missing_name_fails"]:
        failures.append("verification bundle missing name should fail")

    empty_commands = base_state()
    bad = bundle()
    bad["commands"] = []
    empty_commands["completion_audit"]["verification_evidence"].append(bad)
    result = run_validator(empty_commands)
    checks["bundle_empty_commands_fails"] = result.returncode != 0 and "verification_bundle.commands" in (
        result.stderr + result.stdout
    )
    if not checks["bundle_empty_commands_fails"]:
        failures.append("verification bundle with empty commands should fail")

    advisory_risk = base_state()
    advisory_risk["completion_audit"]["residual_risk"] = [
        {
            "owner": "operator",
            "class": "test_scope_gap",
            "summary": "No API-key LLM judge was run; deterministic parser and policy checks passed.",
            "blocks_release": False,
        }
    ]
    result = run_validator(advisory_risk)
    checks["new_advisory_risk_class_passes"] = result.returncode == 0
    if not checks["new_advisory_risk_class_passes"]:
        failures.append("new advisory residual risk class should pass: " + (result.stderr or result.stdout))

    print(json.dumps({"passed": not failures, "checks": checks, "failures": failures}, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
