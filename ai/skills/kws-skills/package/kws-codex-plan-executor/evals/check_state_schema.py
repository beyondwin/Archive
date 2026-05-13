#!/usr/bin/env python3
"""Deterministic checks for validate_state.py contract enforcement."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


REQUIRED_CONTRACT = {
    "scope": "Create one docs note.",
    "files_to_inspect": ["docs/example.md"],
    "allowed_edits": ["docs/example.md", ".codex-orchestrator/state.json"],
    "forbidden_edits": ["docs/unrelated.md"],
    "acceptance_command_or_honest_substitute": "test -f docs/example.md",
}


def base_state() -> dict:
    return {
        "schema_version": "1",
        "mode": "interactive",
        "workspace": "/tmp/repo",
        "plan": "/tmp/repo/plan.md",
        "branch": "codex/example",
        "worktree": "/tmp/repo",
        "current_task": "task_0",
        "current_phase": "task_loop",
        "tasks": {
            "task_0": {
                "status": "pending",
                "risk": "low",
                "files_declared": ["docs/example.md"],
                "contract": dict(REQUIRED_CONTRACT),
                "review_retries": 0,
                "verifier_retries": 0,
            }
        },
        "timestamps": {"started_at": None, "updated_at": None, "completed_at": None},
    }


def run_validator(script: Path, payload: dict) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory(prefix="codex-state-schema-") as temp:
        state_path = Path(temp) / "state.json"
        state_path.write_text(json.dumps(payload), encoding="utf-8")
        return subprocess.run(
            [sys.executable, str(script), str(state_path)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )


def main() -> int:
    script = Path(__file__).resolve().parents[1] / "scripts" / "validate_state.py"
    checks: dict[str, bool] = {}
    failures: list[str] = []

    valid = run_validator(script, base_state())
    checks["valid_contract_passes"] = valid.returncode == 0
    if not checks["valid_contract_passes"]:
        failures.append("valid state with task contract should pass")

    missing_contract = base_state()
    del missing_contract["tasks"]["task_0"]["contract"]
    missing = run_validator(script, missing_contract)
    checks["missing_contract_fails"] = missing.returncode != 0 and "contract" in (missing.stderr + missing.stdout)
    if not checks["missing_contract_fails"]:
        failures.append("state without task contract should fail")

    incomplete_contract = base_state()
    del incomplete_contract["tasks"]["task_0"]["contract"]["forbidden_edits"]
    incomplete = run_validator(script, incomplete_contract)
    checks["incomplete_contract_fails"] = incomplete.returncode != 0 and "forbidden_edits" in (
        incomplete.stderr + incomplete.stdout
    )
    if not checks["incomplete_contract_fails"]:
        failures.append("state with incomplete task contract should fail")

    payload = {"passed": not failures, "checks": checks, "failures": failures}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
