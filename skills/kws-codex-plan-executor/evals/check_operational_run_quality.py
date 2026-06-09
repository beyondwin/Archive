#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import check_state_schema


def run_validator(payload: dict) -> subprocess.CompletedProcess[str]:
    script = Path(__file__).resolve().parents[1] / "scripts" / "validate_state.py"
    with tempfile.TemporaryDirectory(prefix="cpe-run-quality-") as temp:
        state_path = Path(temp) / "state.json"
        state_path.write_text(json.dumps(payload), encoding="utf-8")
        return subprocess.run(
            [sys.executable, str(script), str(state_path)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )


def v222_state() -> dict:
    state = check_state_schema.v220_state()
    state["source_workspace"] = "/tmp/source"
    state["execution_worktree"] = state["worktree"]
    state["command_cwd_evidence"] = [
        {
            "command": 'python3 scripts/preflight_local_env.py --repo-root "$WORKTREE_ABS"',
            "cwd": state["worktree"],
            "phase": "preflight",
            "status": "passed",
        }
    ]
    state["delegation_policy"] = {
        "requested_mode": "on",
        "requested_source": "default",
        "explicit_user_delegation_request": False,
        "spawn_policy": "explicit-request-required",
        "effective_mode": "local_fallback",
        "reason": "spawn_agent tool policy requires explicit user delegation intent",
    }
    state["preflight_bootstrap"] = {
        "schema_version": "1",
        "warnings": [],
        "bootstrap_plan": [],
        "environment_capabilities": {"node": "present", "agentlens": "absent"},
    }
    state["run_quality"] = {
        "schema_version": "1",
        "validation_status": "passed",
        "terminal_state": "finished",
        "stale": False,
        "workspace_matches_execution_worktree": True,
        "schema_drift": [],
        "open_followups": [],
        "summary": "Run finished with validated state.",
    }
    return state


def main() -> int:
    failures: list[str] = []
    checks: dict[str, bool] = {}

    valid = run_validator(v222_state())
    checks["valid_v222_state_passes"] = valid.returncode == 0
    if not checks["valid_v222_state_passes"]:
        failures.append("valid v2.22 state should pass: " + (valid.stderr or valid.stdout))

    bad_policy = v222_state()
    bad_policy["delegation_policy"]["effective_mode"] = "maybe"
    invalid = run_validator(bad_policy)
    checks["invalid_delegation_policy_fails"] = (
        invalid.returncode != 0 and "delegation_policy.effective_mode" in invalid.stderr
    )
    if not checks["invalid_delegation_policy_fails"]:
        failures.append("invalid delegation_policy.effective_mode should fail")

    bad_worktree = v222_state()
    bad_worktree["execution_worktree"] = "/tmp/not-a-codex-worktree"
    invalid_worktree = run_validator(bad_worktree)
    checks["invalid_execution_worktree_fails"] = (
        invalid_worktree.returncode != 0 and "execution_worktree" in invalid_worktree.stderr
    )
    if not checks["invalid_execution_worktree_fails"]:
        failures.append("execution_worktree outside .codex/worktrees/<run_id> should fail")

    payload = {"passed": not failures, "checks": checks, "failures": failures}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
