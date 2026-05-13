#!/usr/bin/env python3
"""Deterministic checks for interactive/headless execution fixtures."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import yaml


def run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def changed_files(workdir: Path) -> set[str]:
    files: set[str] = set()
    diff = run(["git", "diff", "--name-only", "HEAD"], cwd=workdir)
    files.update(line.strip() for line in diff.stdout.splitlines() if line.strip())
    untracked = run(["git", "ls-files", "--others", "--exclude-standard"], cwd=workdir)
    files.update(line.strip() for line in untracked.stdout.splitlines() if line.strip())
    return files


def task_statuses_complete(state: dict, allow_blocked: bool) -> bool:
    tasks = state.get("tasks") or {}
    if not tasks:
        return False
    complete_values = {"complete", "completed", "done", "pass", "passed"}
    blocked_values = {"blocked", "skipped"}
    for task in tasks.values():
        value = str(task.get("status", "")).lower()
        if value in complete_values:
            continue
        if allow_blocked and value in blocked_values:
            continue
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", required=True, help="Fixture YAML path")
    parser.add_argument("--workdir", required=True, help="Repository/worktree to inspect")
    args = parser.parse_args()

    fixture_path = Path(args.fixture)
    workdir = Path(args.workdir).resolve()
    with fixture_path.open(encoding="utf-8") as fh:
        fixture = yaml.safe_load(fh) or {}
    expected = fixture.get("expected") or {}

    failures: list[str] = []
    checks: dict[str, bool] = {}

    state_path = workdir / ".codex-orchestrator" / "state.json"
    checks["state_exists"] = state_path.is_file()
    if not checks["state_exists"]:
        failures.append("missing .codex-orchestrator/state.json")
        state = {}
    else:
        validator = Path(__file__).resolve().parents[1] / "scripts" / "validate_state.py"
        result = run([sys.executable, str(validator), str(state_path)])
        checks["state_valid"] = result.returncode == 0
        if not checks["state_valid"]:
            failures.append("state validation failed: " + (result.stderr.strip() or result.stdout.strip()))
        state = json.loads(state_path.read_text(encoding="utf-8"))

    expected_files = set(expected.get("files_changed") or [])
    actual_files = changed_files(workdir)
    checks["expected_files_changed"] = expected_files.issubset(actual_files)
    if not checks["expected_files_changed"]:
        failures.append(f"missing expected changed files: {sorted(expected_files - actual_files)}")

    allowed_extra = set(expected.get("allowed_extra_files") or [])
    allowed_extra.add(".codex-orchestrator/state.json")
    out_of_scope = actual_files - expected_files - allowed_extra
    checks["no_out_of_scope_files"] = not out_of_scope
    if out_of_scope:
        failures.append(f"out-of-scope files changed: {sorted(out_of_scope)}")

    checks["tasks_finished"] = task_statuses_complete(state, bool(expected.get("allow_blocked")))
    if not checks["tasks_finished"]:
        failures.append("final state does not mark tasks complete or expected blocked")

    test_after = expected.get("test_after")
    if test_after:
        result = subprocess.run(test_after, cwd=workdir, shell=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        checks["test_after"] = result.returncode == 0
        if result.returncode != 0:
            failures.append("test_after failed: " + (result.stderr.strip() or result.stdout.strip()))
    else:
        checks["test_after"] = True

    payload = {
        "fixture": fixture.get("name") or fixture_path.stem,
        "passed": not failures,
        "checks": checks,
        "failures": failures,
        "actual_changed_files": sorted(actual_files),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
