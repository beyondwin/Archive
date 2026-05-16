#!/usr/bin/env python3
"""Check changed files against the active task contract and unit manifest."""

from __future__ import annotations

import argparse
import fnmatch
import json
import subprocess
import sys
from pathlib import Path


def git_lines(repo_root: Path, args: list[str]) -> list[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git command failed")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def changed_files(repo_root: Path) -> list[str]:
    changed: set[str] = set()
    changed.update(git_lines(repo_root, ["diff", "--name-only"]))
    changed.update(git_lines(repo_root, ["diff", "--cached", "--name-only"]))
    changed.update(git_lines(repo_root, ["ls-files", "--others", "--exclude-standard"]))
    return sorted(changed)


def as_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]


def matches_any(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def classify(path: str, allowed: list[str], forbidden: list[str]) -> str | None:
    if matches_any(path, forbidden):
        return "forbidden by contract or unit_manifest"
    if matches_any(path, allowed):
        return None
    return "not allowed by contract.allowed_edits or unit_manifest.allowed_write_globs"


def check(repo_root: Path, state_path: Path, task_id: str) -> tuple[dict, int]:
    state = json.loads(state_path.read_text(encoding="utf-8"))
    tasks = state.get("tasks")
    if not isinstance(tasks, dict) or task_id not in tasks:
        return {
            "passed": False,
            "task_id": task_id,
            "changed_files": [],
            "violations": [{"path": "", "reason": "task not found in state"}],
        }, 2

    task = tasks[task_id]
    if not isinstance(task, dict):
        return {
            "passed": False,
            "task_id": task_id,
            "changed_files": [],
            "violations": [{"path": "", "reason": "task state must be an object"}],
        }, 2

    contract = task.get("contract") if isinstance(task.get("contract"), dict) else {}
    manifest = task.get("unit_manifest") if isinstance(task.get("unit_manifest"), dict) else {}

    allowed = as_string_list(contract.get("allowed_edits")) + as_string_list(manifest.get("allowed_write_globs"))
    forbidden = as_string_list(contract.get("forbidden_edits")) + as_string_list(
        manifest.get("forbidden_write_globs")
    )

    changed = changed_files(repo_root)
    violations = []
    for path in changed:
        reason = classify(path, allowed, forbidden)
        if reason:
            violations.append({"path": path, "reason": reason})

    payload = {
        "passed": not violations,
        "task_id": task_id,
        "changed_files": changed,
        "violations": violations,
    }
    return payload, 0 if not violations else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--state", required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--json", action="store_true", help="Emit JSON output")
    args = parser.parse_args()

    try:
        payload, status = check(Path(args.repo_root).resolve(), Path(args.state).resolve(), args.task)
    except Exception as exc:
        payload = {
            "passed": False,
            "task_id": args.task,
            "changed_files": [],
            "violations": [{"path": "", "reason": str(exc)}],
        }
        status = 2

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        if payload["passed"]:
            print(f"diff policy passed for {args.task}")
        else:
            for violation in payload["violations"]:
                path = violation.get("path") or "<state>"
                print(f"{path}: {violation.get('reason')}", file=sys.stderr)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
