#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fnmatch
import json
import subprocess
from pathlib import Path


def git_changed(repo: Path) -> set[str]:
    files: set[str] = set()
    for args in (["diff", "--name-only", "HEAD"], ["ls-files", "--others", "--exclude-standard"]):
        result = subprocess.run(["git", *args], cwd=repo, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        files.update(line.strip() for line in result.stdout.splitlines() if line.strip())
    return files


def matches_any(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def decision_payload(task_id: str, decision: str, reason: str, write_scope: list[str], failed: list[str]) -> dict:
    mode = "delegated" if decision == "delegate" else "local_fallback"
    return {
        "schema_version": "1",
        "task_id": task_id,
        "decision": decision,
        "reason": reason,
        "write_scope": write_scope,
        "failed_prerequisites": failed,
        "state_updates": {
            "subagent_strategy": {
                "mode": mode,
                "reason": reason,
                "run_ids": [],
            }
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Decide CPE subagent pre-dispatch readiness.")
    parser.add_argument("--state", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--task-packet", required=True)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--write-scope", action="append", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()

    repo = Path(args.repo_root).resolve()
    state_path = Path(args.state)
    failed: list[str] = []
    decision = "delegate"
    reason = "all pre-dispatch prerequisites passed"
    write_scope = args.write_scope

    packet_path = Path(args.task_packet)
    packet = {}
    if not packet_path.is_file():
        failed.append("task_packet_missing")
    else:
        packet = json.loads(packet_path.read_text(encoding="utf-8"))

    if not state_path.is_file():
        failed.append("state_missing")
    else:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state.get("subagents_requested") is not True:
            failed.append("subagents_not_requested")

    policy = packet.get("write_policy") if isinstance(packet, dict) else {}
    allowed = policy.get("allowed_write_globs") if isinstance(policy, dict) else []
    forbidden = policy.get("forbidden_write_globs") if isinstance(policy, dict) else []
    if not allowed:
        failed.append("allowed_write_globs_empty")
    for scope in write_scope:
        if allowed and not matches_any(scope, allowed):
            failed.append("write_scope_outside_allowed")
        if forbidden and matches_any(scope, forbidden):
            failed.append("write_scope_matches_forbidden")

    dirty = git_changed(repo)
    dirty_overlap = sorted(path for path in dirty if matches_any(path, write_scope))
    if dirty_overlap:
        failed.append("dirty_overlap:" + ",".join(dirty_overlap))
        decision = "block"
        reason = "dirty files overlap delegated write scope"

    if failed and decision != "block":
        decision = "local_fallback"
        reason = failed[0]

    payload = decision_payload(args.task_id, decision, reason, write_scope, failed)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if decision in {"delegate", "local_fallback"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
