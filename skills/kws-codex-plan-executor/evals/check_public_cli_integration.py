#!/usr/bin/env python3
"""Compare public CLI result artifacts with outcome-only oracles."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


EVAL_DIR = Path(__file__).resolve().parent
RUNNER = EVAL_DIR / "public_cli_fixture_runner.py"
ORACLES = EVAL_DIR / "public-cli-oracles.json"
CPE = EVAL_DIR.parent / "scripts" / "cpe.py"


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="cpe-public-results-") as raw:
        result = subprocess.run(
            [sys.executable, str(RUNNER), "--output-dir", raw],
            cwd=EVAL_DIR.parent,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if result.returncode:
            print(json.dumps({"passed": False, "checks": {}, "failures": [result.stderr or result.stdout]}, indent=2))
            return 1
        actual_payload = json.loads((Path(raw) / "results.json").read_text(encoding="utf-8"))
    expected_payload = json.loads(ORACLES.read_text(encoding="utf-8"))
    actual = {item["id"]: item for item in actual_payload["results"]}
    expected = expected_payload["oracles"]
    failures: list[str] = []
    checks: dict[str, bool] = {}
    checks["case_oracle_ids_match"] = set(actual) == set(expected)
    if not checks["case_oracle_ids_match"]:
        failures.append("case and oracle ids differ")
    for case_id, oracle in expected.items():
        item = actual.get(case_id, {})
        for field in ("exit_code", "status", "changed_files"):
            name = f"{case_id}:{field}"
            checks[name] = item.get(field) == oracle.get(field)
            if not checks[name]:
                failures.append(f"{name}: expected={oracle.get(field)!r} actual={item.get(field)!r}")
        name = f"{case_id}:public_cpe_invoked"
        checks[name] = item.get("public_cpe_invoked") is True and item.get("argv", [None, None])[1] == str(CPE)
        if not checks[name]:
            failures.append(name)
    mutation_ids = [name for name in expected if "mutation" in name or "invalid" in name or "interruption" in name]
    checks["mutation_cases_fail_closed"] = bool(mutation_ids) and all(actual.get(name, {}).get("exit_code") != 0 for name in mutation_ids)
    if not checks["mutation_cases_fail_closed"]:
        failures.append("mutation cases did not all fail closed")
    print(json.dumps({"passed": not failures, "checks": checks, "failures": failures}, indent=2, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
