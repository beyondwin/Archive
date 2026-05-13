#!/usr/bin/env python3
"""Deterministic parse_plan fixture checks."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml


def run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", required=True, help="Fixture YAML path")
    args = parser.parse_args()

    fixture_path = Path(args.fixture).resolve()
    fixture = yaml.safe_load(fixture_path.read_text(encoding="utf-8")) or {}
    expected = fixture.get("expected") or {}
    script = fixture_path.parents[2] / "scripts" / "parse_plan.py"
    mode = fixture.get("mode", "interactive")
    failures: list[str] = []
    checks: dict[str, bool] = {}

    with tempfile.TemporaryDirectory(prefix="codex-parse-plan-") as temp:
        repo = Path(temp) / "repo"
        repo.mkdir()
        plan = repo / "plan.md"
        plan.write_text(fixture.get("plan", ""), encoding="utf-8")
        result = run([sys.executable, str(script), "--plan", str(plan), "--repo-root", str(repo), "--mode", mode])

    expected_error = expected.get("error_contains")
    if expected_error:
        checks["expected_error"] = result.returncode != 0 and expected_error in (result.stderr + result.stdout)
        if not checks["expected_error"]:
            failures.append("expected parser error was not observed")
        parsed = {}
    else:
        checks["parser_success"] = result.returncode == 0
        if result.returncode != 0:
            failures.append("parser failed: " + (result.stderr.strip() or result.stdout.strip()))
            parsed = {}
        else:
            parsed = json.loads(result.stdout)

    expected_files = expected.get("files") or []
    if expected_files:
        actual_files = []
        for task in parsed.get("tasks", []):
            actual_files.extend(task.get("files", []))
        checks["files_match"] = sorted(expected_files) == sorted(actual_files)
        if not checks["files_match"]:
            failures.append(f"expected files {expected_files}, got {sorted(actual_files)}")

    expected_depends = expected.get("depends_on") or {}
    if expected_depends:
        actual_depends = {
            task.get("id"): task.get("depends_on", [])
            for task in parsed.get("tasks", [])
        }
        checks["depends_on_match"] = expected_depends == actual_depends
        if not checks["depends_on_match"]:
            failures.append(f"expected dependencies {expected_depends}, got {actual_depends}")

    payload = {
        "fixture": fixture.get("name") or fixture_path.stem,
        "passed": not failures,
        "checks": checks,
        "failures": failures,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
