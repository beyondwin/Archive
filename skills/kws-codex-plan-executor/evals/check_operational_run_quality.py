#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from cpe_runtime.scheduler import next_phase, route_verdict


def _rejects(fn) -> bool:
    try:
        fn()
    except ValueError:
        return True
    return False


def main() -> int:
    runtime = subprocess.run(
        [sys.executable, str(ROOT / "evals" / "check_execution_runtime.py")],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        runtime_payload = json.loads(runtime.stdout)
    except json.JSONDecodeError:
        runtime_payload = {}
    checks = {
        "execution_runtime_is_real_and_green": runtime.returncode == 0
        and runtime_payload.get("passed") is True,
        "phase_dispatch_is_explicit": next_phase(
            {"tasks": {"T": {"status": "reviewing"}}}, "T"
        )
        == "acceptance",
        "unknown_phase_fails_closed": _rejects(
            lambda: next_phase({"tasks": {"T": {"status": "mystery"}}}, "T")
        ),
        "typed_verdict_routing_is_explicit": [
            route_verdict({"status": status})
            for status in ("passed", "changes_requested", "blocked", "inconclusive")
        ]
        == ["continue", "repair", "blocked", "inconclusive"],
        "unknown_verdict_fails_closed": _rejects(
            lambda: route_verdict({"status": "mystery"})
        ),
    }
    failures = [name for name, passed in checks.items() if not passed]
    print(json.dumps({"passed": not failures, "checks": checks, "failures": failures}, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
