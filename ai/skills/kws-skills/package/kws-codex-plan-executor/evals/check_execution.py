#!/usr/bin/env python3
"""Deterministic checks for interactive/headless execution fixtures."""

from __future__ import annotations

import argparse
import json
import re
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


def select_state_path(workdir: Path) -> Path:
    run_states = sorted((workdir / ".codex-orchestrator" / "runs").glob("*/state.json"))
    if run_states:
        return run_states[-1]
    return workdir / ".codex-orchestrator" / "state.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", required=True, help="Fixture YAML path")
    parser.add_argument("--workdir", required=True, help="Repository/worktree to inspect")
    parser.add_argument("--final-output", help="Final assistant message to inspect")
    parser.add_argument("--run-log", help="JSONL/stdout log to inspect")
    args = parser.parse_args()

    fixture_path = Path(args.fixture)
    workdir = Path(args.workdir).resolve()
    with fixture_path.open(encoding="utf-8") as fh:
        fixture = yaml.safe_load(fh) or {}
    expected = fixture.get("expected") or {}

    failures: list[str] = []
    checks: dict[str, bool] = {}

    state_path = select_state_path(workdir)
    checks["state_exists"] = state_path.is_file()
    allow_no_state = bool(expected.get("allow_no_state"))
    if not checks["state_exists"] and not allow_no_state:
        failures.append("missing .codex-orchestrator/state.json")
        state = {}
    elif not checks["state_exists"]:
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
    allowed_extra.update(
        {
            ".codex-orchestrator/headless-final.json",
            ".codex-orchestrator/headless-final.md",
            ".codex-orchestrator/headless.jsonl",
            ".codex-orchestrator/blocker-event.json",
            ".codex-orchestrator/learning-event.json",
            ".codex-orchestrator/parsed-plan.json",
            ".codex-orchestrator/final.schema.json",
            ".harness/fixture.json",
            ".harness/final.md",
            ".harness/run.jsonl",
        }
    )
    allowed_prefixes = (
        ".codex-orchestrator/runs/",
        ".codex-orchestrator/raw/",
        ".codex-orchestrator/learning",
        ".codex-orchestrator/events",
    )
    allowed_name_fragments = ("learning-event",)
    out_of_scope = {
        path
        for path in actual_files - expected_files - allowed_extra
        if not path.startswith(allowed_prefixes)
        and not any(fragment in path for fragment in allowed_name_fragments)
    }
    checks["no_out_of_scope_files"] = not out_of_scope
    if out_of_scope:
        failures.append(f"out-of-scope files changed: {sorted(out_of_scope)}")

    must_not_change = set(expected.get("must_not_change") or [])
    changed_forbidden = actual_files.intersection(must_not_change)
    checks["must_not_change"] = not changed_forbidden
    if changed_forbidden:
        failures.append(f"forbidden files changed: {sorted(changed_forbidden)}")

    checks["tasks_finished"] = allow_no_state or task_statuses_complete(state, bool(expected.get("allow_blocked")))
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

    final_text = ""
    final_required = any(key in expected for key in ("must_include", "must_include_final", "must_not_include_final", "must_block"))
    if args.final_output:
        final_path = Path(args.final_output)
        if final_path.is_file():
            final_text = final_path.read_text(encoding="utf-8")
        elif final_required:
            failures.append(f"final output not found: {final_path}")
    elif final_required:
        failures.append("final output path is required for final-message expectations")

    must_include = list(expected.get("must_include") or []) + list(expected.get("must_include_final") or [])
    missing_final = [item for item in must_include if item not in final_text]
    checks["must_include_final"] = not missing_final
    failures.extend(f"missing final text: {item}" for item in missing_final)

    present_forbidden_final = [item for item in expected.get("must_not_include_final") or [] if item in final_text]
    checks["must_not_include_final"] = not present_forbidden_final
    failures.extend(f"forbidden final text present: {item}" for item in present_forbidden_final)

    if expected.get("must_block"):
        blocked_values = {"blocked", "skipped"}
        tasks = state.get("tasks") if isinstance(state, dict) else {}
        state_blocked = any(str(task.get("status", "")).lower() in blocked_values for task in (tasks or {}).values())
        final_blocked = bool(
            re.search(
                r"\bblocked\b|\bstopp?ed\b|\bstopping\b|\bhalt(?:ed)?\b|"
                r"cannot proceed|dirty worktree|related dirty|차단|중단|정지|멈춤|더티",
                final_text,
                re.I,
            )
        )
        checks["must_block"] = state_blocked or final_blocked
        if not checks["must_block"]:
            failures.append("expected blocked outcome was not observed")
    else:
        checks["must_block"] = True

    state_text = json.dumps(state, ensure_ascii=False, sort_keys=True)
    missing_state = [item for item in expected.get("state_must_include") or [] if item not in state_text]
    checks["state_must_include"] = not missing_state
    failures.extend(f"missing state text: {item}" for item in missing_state)

    if expected.get("contract_required"):
        required_contract = {"scope", "files_to_inspect", "allowed_edits", "forbidden_edits", "acceptance_command_or_honest_substitute"}
        tasks = state.get("tasks") if isinstance(state, dict) else {}
        missing_contracts = []
        for task_id, task in (tasks or {}).items():
            contract = task.get("contract") if isinstance(task, dict) else None
            if not isinstance(contract, dict) or not required_contract.issubset(contract):
                missing_contracts.append(task_id)
        checks["contract_required"] = not missing_contracts and bool(tasks)
        if not checks["contract_required"]:
            failures.append(f"missing task contracts: {missing_contracts or ['<no tasks>']}")
    else:
        checks["contract_required"] = True

    log_text = ""
    patterns = expected.get("forbidden_log_patterns") or []
    if args.run_log:
        log_path = Path(args.run_log)
        if log_path.is_file():
            log_text = log_path.read_text(encoding="utf-8", errors="replace")
        elif patterns:
            failures.append(f"run log not found: {log_path}")
    elif patterns:
        failures.append("run log path is required for log-pattern expectations")
    present_patterns = [pattern for pattern in patterns if re.search(pattern, log_text)]
    checks["forbidden_log_patterns"] = not present_patterns
    failures.extend(f"forbidden log pattern present: {pattern}" for pattern in present_patterns)

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
