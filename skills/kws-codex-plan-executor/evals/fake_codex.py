#!/usr/bin/env python3
"""Small deterministic Codex stand-in for the sequential runner evals."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path


SCENARIOS = {
    "completed",
    "interrupted",
    "blocked",
    "failed",
    "wrong_commit",
    "dirty_handoff",
    "resume_completed",
}


def value(arguments: list[str], flag: str) -> str:
    try:
        return arguments[arguments.index(flag) + 1]
    except (ValueError, IndexError) as exc:
        raise SystemExit(f"missing {flag}") from exc


def marker(prompt: str, name: str) -> str:
    match = re.search(rf"^{re.escape(name)}: (.+)$", prompt, re.MULTILINE)
    if match is None:
        raise SystemExit(f"missing prompt marker {name}")
    return match.group(1).strip()


def git(worktree: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(worktree), *arguments],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout.strip()


def invocation_number(plan_id: str, worktree: Path) -> int:
    declared = os.environ.get("CPE_FAKE_INVOCATION_LOG")
    if not declared:
        return 1
    path = Path(declared)
    entries = []
    if path.exists():
        entries = [json.loads(line) for line in path.read_text().splitlines()]
    count = sum(entry["plan_id"] == plan_id for entry in entries) + 1
    entries.append({"plan_id": plan_id, "worktree": str(worktree), "number": count})
    path.write_text("".join(json.dumps(entry) + "\n" for entry in entries))
    return count


def commit_plan(worktree: Path, plan_id: str, suffix: str = "") -> str:
    number = str(int(plan_id.rsplit("-", 1)[-1]))
    target = worktree / f"plan-{number}{suffix}.txt"
    target.write_text(f"{plan_id}{suffix}\n", encoding="utf-8")
    git(worktree, "add", "--", target.name)
    git(worktree, "commit", "-q", "-m", f"fake {plan_id}{suffix}")
    return git(worktree, "rev-parse", "HEAD")


def main() -> int:
    arguments = sys.argv[1:]
    prompt = sys.stdin.read()
    worktree = Path(value(arguments, "-C"))
    result_path = Path(value(arguments, "--output-last-message"))
    plan_id = marker(prompt, "PLAN_ID")
    plan_path = Path(marker(prompt, "CURRENT_PLAN"))
    scenario = plan_path.read_text(encoding="utf-8").splitlines()[0].split(":", 1)[1]
    if scenario not in SCENARIOS:
        raise SystemExit(f"unsupported scenario {scenario}")
    attempt = invocation_number(plan_id, worktree)
    head = git(worktree, "rev-parse", "HEAD")
    status = scenario

    if scenario == "completed":
        head = commit_plan(worktree, plan_id)
    elif scenario == "resume_completed":
        if attempt == 1:
            head = commit_plan(worktree, plan_id, "-progress")
            status = "blocked"
        else:
            head = commit_plan(worktree, plan_id)
            status = "completed"
    elif scenario == "wrong_commit":
        old_head = head
        commit_plan(worktree, plan_id)
        head = old_head
        status = "completed"
    elif scenario == "dirty_handoff":
        head = commit_plan(worktree, plan_id)
        (worktree / "left-untracked.txt").write_text("dirty\n", encoding="utf-8")
        status = "completed"

    payload = {
        "plan_id": plan_id,
        "status": status,
        "head_commit": head,
        "verification": ([{"command": "fake verify", "exit_code": 0}] if status == "completed" else []),
        "summary": f"fake {scenario} attempt {attempt}",
    }
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(payload), encoding="utf-8")
    print(json.dumps({"type": "result", "status": status}))
    return 0 if status == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
