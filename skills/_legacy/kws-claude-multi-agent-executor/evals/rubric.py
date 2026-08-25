#!/usr/bin/env python3
"""Programmatic rubric runner — deterministic correctness measurement.

Reads a fixture's `expected.rubric` block, runs each `check:` shell command
inside the workdir, and emits a JSON report of pass/fail counts.

Replaces the LLM judge's stochastic guess at "did this implementation match
spec" for the mechanical part of evaluation. The LLM judge is still used for
the subjective code_quality dimension.

Usage:
    python3 rubric.py --fixture path/to/08-*.yaml --workdir path/to/repo
        → emits JSON to stdout

Fixture rubric format (in fixture YAML):
    expected:
      rubric:
        valid_inputs:
          - check: 'python -c "..."'
        error_cases:
          - check: 'python -c "..."'
            desc: 'description for failure reporting'
        code_quality_dimensions:  # for judge, not run here
          - 'subjective criterion 1'

Output format (JSON):
    {
      "valid_inputs":   {"passed": 10, "total": 10, "failures": []},
      "error_cases":    {"passed":  8, "total": 10, "failures": [{"desc": "...", "stderr": "..."}]},
      "summary":        {"total_passed": 18, "total_checks": 20, "pass_rate": 0.9}
    }
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml


def _run_check(cmd: str, workdir: Path, timeout: int = 30) -> tuple[bool, str]:
    """Return (passed, stderr_tail). A check passes iff exit code is 0."""
    try:
        result = subprocess.run(
            ["bash", "-c", cmd],
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    passed = result.returncode == 0
    stderr = (result.stderr or result.stdout or "").strip()
    return passed, stderr[-400:]


def _run_section(items: list[dict[str, Any]], workdir: Path) -> dict[str, Any]:
    passed = 0
    failures: list[dict[str, str]] = []
    for item in items:
        cmd = item.get("check", "")
        if not cmd:
            continue
        ok, err = _run_check(cmd, workdir)
        if ok:
            passed += 1
        else:
            failures.append({
                "desc": item.get("desc", "") or cmd[:80],
                "stderr": err,
            })
    return {"passed": passed, "total": len(items), "failures": failures}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--fixture", required=True, help="path to fixture YAML")
    p.add_argument("--workdir", required=True, help="path to repo with the implementation")
    p.add_argument("--output", default="-", help="output path (default: stdout)")
    args = p.parse_args()

    fixture_path = Path(args.fixture).resolve()
    workdir = Path(args.workdir).resolve()
    if not workdir.is_dir():
        print(f"FATAL: workdir not a directory: {workdir}", file=sys.stderr)
        return 2

    with open(fixture_path) as fh:
        fixture = yaml.safe_load(fh)
    rubric = (fixture.get("expected") or {}).get("rubric") or {}
    if not rubric:
        print("FATAL: fixture has no expected.rubric block", file=sys.stderr)
        return 2

    report = {
        "fixture": fixture.get("name", fixture_path.stem),
        "workdir": str(workdir),
        "valid_inputs": _run_section(rubric.get("valid_inputs") or [], workdir),
        "error_cases": _run_section(rubric.get("error_cases") or [], workdir),
    }
    total_passed = report["valid_inputs"]["passed"] + report["error_cases"]["passed"]
    total_checks = report["valid_inputs"]["total"] + report["error_cases"]["total"]
    report["summary"] = {
        "total_passed": total_passed,
        "total_checks": total_checks,
        "pass_rate": (total_passed / total_checks) if total_checks else 0.0,
    }

    payload = json.dumps(report, indent=2)
    if args.output == "-":
        print(payload)
    else:
        Path(args.output).write_text(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
