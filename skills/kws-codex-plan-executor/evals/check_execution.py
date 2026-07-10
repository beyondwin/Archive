#!/usr/bin/env python3
"""Validate execution fixtures through the real CPE v3 runtime artifacts."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from cpe_runtime.events import read_events, validate_chain
from cpe_runtime.manifest import load_manifest, resolve_ref
from cpe_runtime.projector import project
from cpe_runtime.validation import validate_run


def git_changes(path: Path) -> set[str]:
    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=path,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode:
        return set()
    return {line[3:].split(" -> ")[-1] for line in result.stdout.splitlines() if len(line) >= 4}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--workdir", required=True)
    parser.add_argument("--final-output")
    parser.add_argument("--run-log")
    args = parser.parse_args()
    fixture = yaml.safe_load(Path(args.fixture).read_text(encoding="utf-8")) or {}
    expected = fixture.get("expected") or {}
    workdir = Path(args.workdir).resolve()
    home = Path(os.environ.get("CODEX_EVAL_HOME", Path.home())).expanduser().resolve()
    run_dirs = sorted((home / ".codex" / "orchestrator").glob("*"), key=lambda path: path.stat().st_mtime)
    allow_no_state = bool(expected.get("allow_no_state"))
    failures: list[str] = []
    checks: dict[str, bool] = {}
    if not run_dirs:
        checks["run_exists"] = allow_no_state
        if not allow_no_state:
            failures.append("missing v3 run directory")
        state = {}
        actual = git_changes(workdir)
    else:
        run_dir = run_dirs[-1]
        checks["manifest_exists"] = (run_dir / "run_manifest.json").is_file()
        checks["events_nonempty"] = bool(read_events(run_dir / "events.jsonl"))
        manifest = load_manifest(run_dir / "run_manifest.json")
        events = read_events(run_dir / "events.jsonl")
        checks["event_chain_valid"] = validate_chain(events) == []
        state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
        checks["replay_parity"] = state == project(manifest, events)
        report = validate_run(run_dir)
        checks["state_valid"] = report.passed
        if not report.passed:
            failures.append("state validation failed: " + ",".join(report.errors))
        worktree = resolve_ref(str(manifest["execution_worktree_ref"]))
        checks["isolated_worktree"] = worktree != workdir and worktree.is_dir()
        actual = git_changes(worktree)
        artifacts = state.get("artifact_index") or []
        checks["content_addressed_evidence"] = bool(artifacts) and all(
            str((item.get("ref") or {}).get("path", "")).startswith("artifacts/evidence/") for item in artifacts
        )
        checks["fixed_attestation"] = bool(state.get("attempts")) and all(
            (item.get("attestation") or {}).get("verified") is True for item in state.get("attempts", [])
        )
        allowed_source_changes = {".harness/final.md", ".harness/run.jsonl"} | set(expected.get("allowed_extra_files") or [])
        checks["source_checkout_isolated"] = not (git_changes(workdir) - allowed_source_changes)
        for key, value in checks.items():
            if not value:
                failures.append(f"failed {key}")

    expected_files = set(expected.get("files_changed") or [])
    checks["expected_files_changed"] = expected_files.issubset(actual)
    forbidden = set(expected.get("must_not_change") or []) & actual
    checks["forbidden_files_unchanged"] = not forbidden
    if not checks["expected_files_changed"]:
        failures.append(f"missing expected files: {sorted(expected_files - actual)}")
    if forbidden:
        failures.append(f"forbidden files changed: {sorted(forbidden)}")
    checks["tasks_finished"] = allow_no_state or (
        state.get("lifecycle") == "completed"
        and state.get("tasks")
        and all(item.get("status") == "completed" for item in state["tasks"].values())
    )
    if not checks["tasks_finished"]:
        failures.append("tasks not completed")
    final_text = Path(args.final_output).read_text(encoding="utf-8") if args.final_output and Path(args.final_output).is_file() else ""
    for item in list(expected.get("must_include") or []) + list(expected.get("must_include_final") or []):
        if item not in final_text:
            failures.append(f"missing final text: {item}")
    if expected.get("must_block") and not allow_no_state and state.get("lifecycle") != "blocked":
        failures.append("expected blocked state")
    payload = {
        "fixture": fixture.get("name") or Path(args.fixture).stem,
        "passed": not failures,
        "checks": checks,
        "failures": failures,
        "actual_changed_files": sorted(actual),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
