#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from cpe_runtime.scheduler import route_verdict


def _run(script: str) -> tuple[int, dict]:
    result = subprocess.run(
        [sys.executable, str(ROOT / "evals" / script)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        payload = {}
    return result.returncode, payload


def main() -> int:
    before = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=ROOT,
        text=True,
        check=True,
        stdout=subprocess.PIPE,
    ).stdout
    operational_code, operational = _run("check_operational_run_quality.py")
    parity_code, parity = _run("check_validation_consumer_parity.py")
    after = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=ROOT,
        text=True,
        check=True,
        stdout=subprocess.PIPE,
    ).stdout
    checks = {
        "operational_scheduler_rubric_passes": operational_code == 0
        and operational.get("passed") is True,
        "canonical_validator_parity_passes": parity_code == 0
        and parity.get("passed") is True,
        "rubric_executes_multiple_behavior_checks": len(operational.get("checks") or {}) >= 5
        and len(parity.get("checks") or {}) >= 5,
        "rubric_is_read_only": before == after,
        "rubric_uses_current_verdict_contract": route_verdict({"status": "passed"}) == "continue",
    }
    failures = [name for name, passed in checks.items() if not passed]
    print(json.dumps({"passed": not failures, "checks": checks, "failures": failures}, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
