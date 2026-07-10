#!/usr/bin/env python3
"""Deterministic parse_plan fixture checks."""

from __future__ import annotations

import argparse
import json
import re
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
    skill_root = fixture_path.parents[2]
    repo_root = skill_root.parents[1]
    script = skill_root / "scripts" / "parse_plan.py"
    mode = fixture.get("mode", "interactive")
    failures: list[str] = []
    checks: dict[str, bool] = {}

    source_plan = fixture.get("plan_path")
    if source_plan:
        plan = (repo_root / str(source_plan)).resolve()
        result = run(
            [sys.executable, str(script), "--plan", str(plan), "--repo-root", str(repo_root), "--mode", mode]
        )
        checks["source_plan_loaded"] = plan.is_file()
        if not checks["source_plan_loaded"]:
            failures.append(f"source plan does not exist: {plan}")
    else:
        with tempfile.TemporaryDirectory(prefix="codex-parse-plan-") as temp:
            repo = Path(temp) / "repo"
            repo.mkdir()
            plan = repo / "plan.md"
            plan.write_text(fixture.get("plan", ""), encoding="utf-8")
            result = run(
                [sys.executable, str(script), "--plan", str(plan), "--repo-root", str(repo), "--mode", mode]
            )

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

    expected_task_lines = expected.get("task_lines") or {}
    if expected_task_lines:
        actual_task_lines = {task.get("id"): task.get("line") for task in parsed.get("tasks", [])}
        checks["task_lines_match"] = expected_task_lines == actual_task_lines
        if not checks["task_lines_match"]:
            failures.append(f"expected task lines {expected_task_lines}, got {actual_task_lines}")

    expected_acceptance_commands = expected.get("acceptance_commands") or {}
    if expected_acceptance_commands:
        actual_acceptance_commands = {
            task.get("id"): task.get("acceptance_command")
            for task in parsed.get("tasks", [])
        }
        checks["acceptance_commands_match"] = expected_acceptance_commands == actual_acceptance_commands
        if not checks["acceptance_commands_match"]:
            failures.append(
                f"expected acceptance commands {expected_acceptance_commands}, got {actual_acceptance_commands}"
            )

    expected_file_line_numbers = expected.get("file_line_numbers") or {}
    if expected_file_line_numbers:
        actual_file_line_numbers = {}
        for task in parsed.get("tasks", []):
            actual_file_line_numbers.update(task.get("file_line_numbers", {}))
        checks["file_line_numbers_match"] = expected_file_line_numbers == actual_file_line_numbers
        if not checks["file_line_numbers_match"]:
            failures.append(f"expected file line numbers {expected_file_line_numbers}, got {actual_file_line_numbers}")

    expected_tasks = expected.get("tasks") or []
    if expected_tasks:
        actual_tasks = {task.get("id"): task for task in parsed.get("tasks", [])}
        task_failures = []
        for expected_task in expected_tasks:
            task_id = expected_task.get("id")
            actual_task = actual_tasks.get(task_id)
            if not actual_task:
                task_failures.append(f"missing task {task_id}")
                continue
            for key, expected_value in expected_task.items():
                if key == "id":
                    continue
                if actual_task.get(key) != expected_value:
                    task_failures.append(f"{task_id}.{key}: expected {expected_value!r}, got {actual_task.get(key)!r}")
        checks["tasks_match"] = not task_failures
        failures.extend(task_failures)

    parsed_tasks = parsed.get("tasks", [])
    expected_task_ids = expected.get("task_ids") or []
    if expected_task_ids:
        actual_task_ids = [task.get("id") for task in parsed_tasks]
        checks["task_ids_match"] = expected_task_ids == actual_task_ids
        if not checks["task_ids_match"]:
            failures.append(f"expected task ids {expected_task_ids}, got {actual_task_ids}")

    expected_task_count = expected.get("task_count")
    if expected_task_count is not None:
        checks["task_count_matches"] = len(parsed_tasks) == expected_task_count
        if not checks["task_count_matches"]:
            failures.append(f"expected {expected_task_count} tasks, got {len(parsed_tasks)}")

    if expected.get("require_explicit_files"):
        missing = [task.get("id") for task in parsed_tasks if not task.get("files")]
        checks["explicit_files_present"] = not missing
        if missing:
            failures.append(f"tasks without explicit files: {missing}")

    if expected.get("require_numeric_dependencies"):
        ids = {task.get("id") for task in parsed_tasks}
        invalid = [
            f"{task.get('id')}:{dependency}"
            for task in parsed_tasks
            for dependency in task.get("depends_on", [])
            if dependency not in ids or not re.fullmatch(r"task_\d+(?:_\d+)*", str(dependency))
        ]
        checks["numeric_dependencies"] = not invalid
        if invalid:
            failures.append(f"invalid numeric dependencies: {invalid}")

    if expected.get("require_acceptance_commands"):
        missing = [task.get("id") for task in parsed_tasks if not str(task.get("acceptance_command") or "").strip()]
        checks["acceptance_commands_present"] = not missing
        if missing:
            failures.append(f"tasks without acceptance commands: {missing}")

    if expected.get("require_task_local_yaml"):
        missing = [task.get("id") for task in parsed_tasks if not task.get("yaml_task_id")]
        checks["task_local_yaml_present"] = not missing
        if missing:
            failures.append(f"tasks without task-local yaml metadata: {missing}")

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
