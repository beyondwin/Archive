#!/usr/bin/env python3
"""Static checks for eval harness failure and isolation behavior."""

from __future__ import annotations

import json
from pathlib import Path


def main() -> int:
    skill_dir = Path(__file__).resolve().parents[1]
    run_sh = (skill_dir / "evals" / "run.sh").read_text(encoding="utf-8")
    check_execution = (skill_dir / "evals" / "check_execution.py").read_text(encoding="utf-8")
    checks: dict[str, bool] = {}
    failures: list[str] = []

    checks["aggregates_fixture_failures"] = "overall_status=0" in run_sh and "overall_status=1" in run_sh
    if not checks["aggregates_fixture_failures"]:
        failures.append("run.sh should aggregate fixture failures into a non-zero final status")

    checks["exits_with_aggregate_status"] = 'exit "$overall_status"' in run_sh
    if not checks["exits_with_aggregate_status"]:
        failures.append("run.sh should exit with the aggregate fixture status")

    checks["isolates_state_home"] = "CODEX_EVAL_HOME" in run_sh and "Path.home()" not in run_sh
    if not checks["isolates_state_home"]:
        failures.append("run.sh should use an eval-specific home for state fixtures, not the real home")

    checks["execution_checker_uses_eval_home"] = "CODEX_EVAL_HOME" in check_execution and "Path.home()" not in check_execution
    if not checks["execution_checker_uses_eval_home"]:
        failures.append("check_execution.py should locate state under CODEX_EVAL_HOME when present")

    checks["maps_headless_sandbox"] = "headless_sandbox" in run_sh and "HEADLESS_SANDBOX" in run_sh
    if not checks["maps_headless_sandbox"]:
        failures.append("run.sh should map headless_sandbox to HEADLESS_SANDBOX for the target process")

    checks["prompt_export_fast_path"] = "For mode=prompt or mode=handoff, do not load implementation-only skills" in run_sh
    if not checks["prompt_export_fast_path"]:
        failures.append("run.sh should keep prompt/handoff evals on an export-only fast path")

    payload = {"passed": not failures, "checks": checks, "failures": failures}
    print(json.dumps(payload, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
