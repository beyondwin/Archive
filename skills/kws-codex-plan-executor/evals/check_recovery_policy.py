#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "classify_recovery.py"


def run_case(root: Path, state: dict, observation: dict) -> dict:
    state_path = root / "state.json"
    observation_path = root / "observation.json"
    output = root / "recovery.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    observation_path.write_text(json.dumps(observation), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--state",
            str(state_path),
            "--task-id",
            "task_0",
            "--observation",
            str(observation_path),
            "--output",
            str(output),
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    payload = json.loads(output.read_text(encoding="utf-8")) if output.is_file() else {}
    payload["_returncode"] = result.returncode
    payload["_stderr"] = result.stderr
    return payload


def main() -> int:
    checks: dict[str, bool] = {}
    failures: list[str] = []

    with tempfile.TemporaryDirectory(prefix="cpe-recovery-") as temp:
        root = Path(temp)
        state = {"schema_version": "1", "recovery_attempts": []}
        bootstrap = {"command": "bun test", "category": "dependency_bootstrap", "evidence": "node_modules missing"}
        data = run_case(root, state, bootstrap)
        checks["dependency_bootstrap_once"] = data.get("decision") == "bootstrap" and data.get("retry_budget") == 1
        if not checks["dependency_bootstrap_once"]:
            failures.append("dependency bootstrap should choose a one-time bootstrap")

        state = {"schema_version": "1", "recovery_attempts": [{"root_signature": data["root_signature"], "status": "closed"}]}
        data = run_case(root, state, bootstrap)
        checks["dependency_bootstrap_not_repeated"] = data.get("decision") == "block"
        if not checks["dependency_bootstrap_not_repeated"]:
            failures.append("dependency bootstrap should not repeat after the same root signature")

        flaky = {"command": "bun test foo", "category": "flaky_test", "evidence": "timeout"}
        state = {"schema_version": "1", "recovery_attempts": []}
        data = run_case(root, state, flaky)
        checks["flaky_retries"] = data.get("decision") == "retry" and data.get("retry_budget") == 2
        if not checks["flaky_retries"]:
            failures.append("flaky tests should use bounded retry")

        state = {
            "schema_version": "1",
            "recovery_attempts": [
                {"root_signature": data["root_signature"], "status": "closed"},
                {"root_signature": data["root_signature"], "status": "closed"},
            ],
        }
        data = run_case(root, state, flaky)
        checks["flaky_budget_exhaustion_fails"] = data.get("decision") == "failed"
        if not checks["flaky_budget_exhaustion_fails"]:
            failures.append("same flaky root should fail after retry budget")

        permission = {"command": "git worktree add", "category": "permission_or_sandbox", "evidence": "permission denied"}
        data = run_case(root, {"schema_version": "1"}, permission)
        checks["permission_blocks"] = data.get("decision") == "block" and data.get("category") == "workspace_precondition"
        if not checks["permission_blocks"]:
            failures.append("permission/sandbox failure should block")

    payload = {"passed": not failures, "checks": checks, "failures": failures}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
