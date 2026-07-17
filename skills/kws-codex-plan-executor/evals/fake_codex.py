#!/usr/bin/env python3
"""Small deterministic Codex stand-in for the sequential runner evals."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path


SCENARIOS = {
    "completed",
    "interrupted",
    "blocked",
    "failed",
    "wrong_commit",
    "dirty_handoff",
    "resume_completed",
    "blocking_completed",
    "timeout_grandchild",
    "timeout_after_commit",
    "completed_with_grandchild",
    "large_log",
    "oversized_usage",
    "mutate_prior_nonzero_completed",
    "retryable_then_completed",
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


def invocation_number(
    plan_id: str,
    worktree: Path,
    recovery_capsule: str | None,
) -> int:
    declared = os.environ.get("CPE_FAKE_INVOCATION_LOG")
    if not declared:
        return 1
    path = Path(declared)
    entries = []
    if path.exists():
        entries = [json.loads(line) for line in path.read_text().splitlines()]
    count = sum(entry["plan_id"] == plan_id for entry in entries) + 1
    entries.append(
        {
            "plan_id": plan_id,
            "worktree": str(worktree),
            "number": count,
            "recovery_capsule": recovery_capsule,
        }
    )
    path.write_text("".join(json.dumps(entry) + "\n" for entry in entries))
    return count


def commit_plan(worktree: Path, plan_id: str, suffix: str = "") -> str:
    number = str(int(plan_id.rsplit("-", 1)[-1]))
    target = worktree / f"plan-{number}{suffix}.txt"
    target.write_text(f"{plan_id}{suffix}\n", encoding="utf-8")
    git(worktree, "add", "--", target.name)
    git(worktree, "commit", "-q", "-m", f"fake {plan_id}{suffix}")
    return git(worktree, "rev-parse", "HEAD")


def workflow_receipt(worktree: Path, head: str) -> dict[str, object]:
    evidence = worktree / ".superpowers" / "sdd"
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / ".gitignore").write_text("*\n", encoding="utf-8")
    (evidence / "progress.md").write_text(
        "Task 1: complete\n",
        encoding="utf-8",
    )
    (evidence / "final-review.md").write_text(
        "Verdict: approved\nFindings: none\n",
        encoding="utf-8",
    )
    return {
        "ledger_path": ".superpowers/sdd/progress.md",
        "final_review_path": ".superpowers/sdd/final-review.md",
        "final_review_head": head,
        "open_finding_ids": [],
        "open_obligation_ids": [],
    }


def write_progress(worktree: Path) -> None:
    evidence = worktree / ".superpowers" / "sdd"
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / ".gitignore").write_text("*\n", encoding="utf-8")
    (evidence / "progress.md").write_text(
        "Task 1: complete (commit 1111111)\n"
        "Task 2: complete (commit 2222222)\n",
        encoding="utf-8",
    )


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
    recovery_match = re.search(
        r"^RECOVERY_CAPSULE: (.+)$",
        prompt,
        re.MULTILINE,
    )
    recovery_capsule = (
        recovery_match.group(1).strip()
        if recovery_match
        else None
    )
    attempt = invocation_number(
        plan_id,
        worktree,
        recovery_capsule,
    )
    head = marker(prompt, "CURRENT_COMMIT")
    status = scenario

    if scenario in {"completed", "oversized_usage"}:
        head = commit_plan(worktree, plan_id)
        status = "completed"
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
    elif scenario == "blocking_completed":
        ready = Path(os.environ["CPE_FAKE_READY"])
        release = Path(os.environ["CPE_FAKE_RELEASE"])
        ready.write_text(str(os.getpid()), encoding="utf-8")
        deadline = time.monotonic() + 5
        while not release.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        if not release.exists():
            raise SystemExit("blocking fixture was not released")
        if attempt == 1:
            head = commit_plan(worktree, plan_id)
        else:
            head = git(worktree, "rev-parse", "HEAD")
        status = "completed"
    elif scenario == "timeout_grandchild":
        pid_path = Path(os.environ["CPE_FAKE_GRANDCHILD_PID"])
        grandchild = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        with pid_path.open("a", encoding="utf-8") as stream:
            stream.write(f"{os.getpid()}\n{grandchild.pid}\n")
            stream.flush()
        while True:
            print("waiting for timeout", flush=True)
            time.sleep(0.05)
    elif scenario == "timeout_after_commit":
        commit_plan(worktree, plan_id)
        while True:
            print("waiting for timeout after commit", flush=True)
            time.sleep(0.05)
    elif scenario == "completed_with_grandchild":
        pid_path = Path(os.environ["CPE_FAKE_GRANDCHILD_PID"])
        grandchild = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        pid_path.write_text(str(grandchild.pid), encoding="utf-8")
        head = commit_plan(worktree, plan_id)
        status = "completed"
    elif scenario == "large_log":
        sys.stderr.buffer.write(b"x" * 2_200_000)
        sys.stderr.buffer.write(b"CPE_FINAL_LOG_MARKER\n")
        sys.stderr.flush()
        head = commit_plan(worktree, plan_id)
        status = "completed"
    elif scenario == "mutate_prior_nonzero_completed":
        prior = next(result_path.parent.glob("plan-01-attempt-*.json"))
        try:
            prior.write_text("tampered\n", encoding="utf-8")
        except PermissionError:
            pass
        head = commit_plan(worktree, plan_id)
        status = "completed"
    elif scenario == "retryable_then_completed":
        if attempt == 1:
            write_progress(worktree)
            status = "failed"
        else:
            head = commit_plan(worktree, plan_id)
            status = "completed"
    elif scenario == "interrupted":
        write_progress(worktree)
        status = "checkpointed"

    payload = {
        "plan_id": plan_id,
        "status": status,
        "head_commit": head,
        "summary": f"fake {scenario} attempt {attempt}",
        "verification": (
            [
                {
                    "command_id": "fake-final",
                    "argv_digest": "f" * 64,
                    "phase": "branch_final",
                    "evidence_key": "0" * 64,
                    "exit_code": 0,
                    "receipt_path": None,
                }
            ]
            if status == "completed"
            else []
        ),
        "checkpoint": None,
        "blocker": None,
        "workflow_receipt": None,
    }
    if status == "checkpointed":
        payload["checkpoint"] = {
            "reason": "coordinator_interrupt",
            "progress_fingerprint": "1" * 64,
            "completed_task_ids": ["Task 1", "Task 2"],
            "current_task_id": None,
        }
    if status == "blocked":
        payload["blocker"] = {
            "kind": "operator_owned",
            "code": "fake_blocked",
            "resource": plan_id,
            "operation": "execute_plan",
            "errno": None,
            "retry_condition": "operator resolves the fake blocker",
            "fingerprint": "2" * 64,
        }
    if status == "completed":
        payload["workflow_receipt"] = workflow_receipt(worktree, head)
    print(
        json.dumps(
            {
                "type": "item.completed",
                "item": {"text": "RAW_EVENT_SENTINEL"},
            }
        ),
        flush=True,
    )
    if scenario != "blocking_completed":
        usage_total = (
            10**4_199
            if scenario == "oversized_usage"
            else None
        )
        print(
            json.dumps(
                {
                    "type": "turn.completed",
                    "usage": {
                        "input_tokens": usage_total or 41,
                        "cached_input_tokens": usage_total or 31,
                        "output_tokens": usage_total or 7,
                        "reasoning_output_tokens": usage_total or 5,
                    },
                }
            ),
            flush=True,
        )
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(payload), encoding="utf-8")
    print(json.dumps({"type": "result", "status": status}))
    if scenario == "mutate_prior_nonzero_completed":
        return 1
    return 0 if status == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
