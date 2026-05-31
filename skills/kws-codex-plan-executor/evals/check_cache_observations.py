#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import check_state_schema


ROOT = Path(__file__).resolve().parents[1]
RECORDER = ROOT / "scripts" / "record_cache_observation.py"
VALIDATOR = ROOT / "scripts" / "validate_state.py"


def run_validator(payload: dict) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory(prefix="cpe-cache-state-") as temp:
        path = Path(temp) / "state.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return subprocess.run(
            [sys.executable, str(VALIDATOR), str(path)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )


def main() -> int:
    checks: dict[str, bool] = {}
    failures: list[str] = []

    with tempfile.TemporaryDirectory(prefix="cpe-cache-state-") as temp:
        state_path = Path(temp) / "state.json"
        state = check_state_schema.v220_state()
        state_path.write_text(json.dumps(state), encoding="utf-8")
        result = subprocess.run(
            [
                sys.executable,
                str(RECORDER),
                "--state",
                str(state_path),
                "--unit",
                "task_0",
                "--mode",
                "interactive",
                "--model",
                "gpt-5",
                "--input-tokens",
                "1000",
                "--output-tokens",
                "200",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        data = json.loads(state_path.read_text(encoding="utf-8"))
        observation = data.get("cache_observations", [{}])[-1]
        checks["recorder_appends_null_cache_counters"] = (
            result.returncode == 0
            and observation.get("cached_read_tokens") is None
            and observation.get("cached_write_tokens") is None
        )
        if not checks["recorder_appends_null_cache_counters"]:
            failures.append("missing cache counters should be stored as null")

    valid = check_state_schema.v220_state()
    valid["cache_strategy"] = {
        "mode": "interactive-default",
        "stable_prefix_policy": "static-first-hot-tail",
        "provider_cache_control": "unavailable",
        "prompt_audit_version": "1",
    }
    valid["cache_observations"] = []
    valid["prompt_audit"] = {
        "last_checked_at": "2026-05-31T00:00:00Z",
        "stable_prefix_hashes": {"templates/fresh-session-prompt.txt": "a" * 64},
        "stable_prefix_bytes": {"templates/fresh-session-prompt.txt": 100},
        "dynamic_marker_violations": [],
    }
    result = run_validator(valid)
    checks["valid_cache_fields_pass"] = result.returncode == 0
    if not checks["valid_cache_fields_pass"]:
        failures.append("valid optional cache fields should pass: " + (result.stderr or result.stdout))

    invalid = dict(valid)
    invalid["prompt_audit"] = dict(valid["prompt_audit"])
    invalid["prompt_audit"]["dynamic_marker_violations"] = [{"file": "templates/fresh-session-prompt.txt"}]
    result = run_validator(invalid)
    checks["finished_prompt_audit_violations_fail"] = (
        result.returncode != 0 and "prompt_audit.dynamic_marker_violations" in (result.stderr + result.stdout)
    )
    if not checks["finished_prompt_audit_violations_fail"]:
        failures.append("finished state with prompt audit violations should fail")

    payload = {"passed": not failures, "checks": checks, "failures": failures}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
