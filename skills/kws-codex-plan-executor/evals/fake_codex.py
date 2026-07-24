#!/usr/bin/env python3
"""Small deterministic Codex stand-in for the sequential runner evals."""

from __future__ import annotations

import hashlib
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
    "blocked_after_commit",
    "failed",
    "wrong_commit",
    "dirty_handoff",
    "resume_completed",
    "blocking_completed",
    "timeout_grandchild",
    "timeout_after_commit",
    "timeout_with_progress",
    "timeout_without_progress",
    "timeout_with_completed_result",
    "timeout_with_malformed_ledger",
    "malformed_ledger_then_completed",
    "timeout_with_ledger_deletion",
    "timeout_with_ledger_rewrite",
    "completed_with_grandchild",
    "large_log",
    "oversized_usage",
    "mutate_prior_nonzero_completed",
    "retryable_then_completed",
    "zero_empty_result",
    "nonzero_empty_result",
    "invalid_present_result",
    "provider_usage_blocked",
    "provider_auth_blocked",
    "provider_unavailable",
    "state_db_warnings",
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


def workflow_receipt(worktree: Path, head: str, plan_id: str) -> dict[str, object]:
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
    receipts = evidence / "receipts"
    receipts.mkdir(exist_ok=True)
    references = {
        "task": "receipts/task.txt",
        "review": "receipts/review.txt",
        "verification": "receipts/verification.txt",
    }
    for category, reference in references.items():
        (evidence / reference).write_text(f"{category}: pass\n", encoding="utf-8")
    digest = "a" * 64
    events = [
        {
            "schema_version": 1, "event_id": "task-1", "source": "child_attested",
            "plan_id": plan_id,
            "category": "task", "action": "completed", "result": "pass",
            "evidence_refs": [references["task"]], "task_id": "task-01", "duration_ms": 1,
        },
        {
            "schema_version": 1, "event_id": "review-1", "source": "child_attested",
            "plan_id": plan_id,
            "category": "review", "action": "approved", "result": "pass",
            "evidence_refs": [references["review"]], "review_id": "review-01", "artifact_digest": digest, "duration_ms": 1,
        },
        {
            "schema_version": 1, "event_id": "verification-1", "source": "child_attested",
            "plan_id": plan_id,
            "category": "verification", "action": "verified", "result": "pass",
            "evidence_refs": [references["verification"]], "command_id": "fake-final",
            "argv_digest": digest, "evidence_key": "b" * 64, "duration_ms": 1,
            "requested_phase": "branch_final",
            "executed_phase": "branch_final",
            "avoided_executions": 0,
        },
    ]
    ledger = evidence / "execution-ledger.jsonl"
    preserved = ""
    existing_ids: set[str] = set()
    if ledger.exists():
        candidate = ledger.read_text(encoding="utf-8")
        try:
            previous_events = [
                json.loads(line) for line in candidate.splitlines() if line.strip()
            ]
        except json.JSONDecodeError:
            previous_events = []
        if previous_events and all(
            isinstance(event, dict) and event.get("plan_id") == plan_id
            for event in previous_events
        ):
            preserved = candidate
            existing_ids = {
                str(event["event_id"])
                for event in previous_events
                if isinstance(event.get("event_id"), str)
            }
    ledger.write_text(
        preserved
        + "".join(
            json.dumps(event, sort_keys=True) + "\n"
            for event in events
            if event["event_id"] not in existing_ids
        ),
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


def write_checkpoint_ledger(worktree: Path, plan_id: str) -> None:
    evidence = worktree / ".superpowers" / "sdd"
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / ".gitignore").write_text("*\n", encoding="utf-8")
    receipt = evidence / "receipts" / "checkpoint-task.txt"
    receipt.parent.mkdir(exist_ok=True)
    receipt.write_text("task: pass\n", encoding="utf-8")
    event = {
        "schema_version": 1,
        "event_id": "checkpoint-task-1",
        "source": "child_attested",
        "plan_id": plan_id,
        "category": "task",
        "action": "completed",
        "result": "pass",
        "evidence_refs": ["receipts/checkpoint-task.txt"],
        "task_id": "task-01",
        "duration_ms": 1,
    }
    (evidence / "execution-ledger.jsonl").write_text(
        json.dumps(event, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def checkpoint_payload(plan_id: str, head: str, scenario: str, attempt: int) -> dict[str, object]:
    return {
        "plan_id": plan_id,
        "status": "checkpointed",
        "head_commit": head,
        "summary": f"fake {scenario} attempt {attempt}",
        "verification": [],
        "checkpoint": {
            "reason": "timeout_progress",
            "progress_fingerprint": "1" * 64,
            "completed_task_ids": ["task-01"] if scenario == "timeout_with_progress" else [],
            "current_task_id": None,
        },
        "blocker": None,
        "workflow_receipt": None,
    }


def wait_for_launcher_timeout(result_path: Path, payload: dict[str, object]) -> None:
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(payload), encoding="utf-8")
    print(json.dumps({"type": "result", "status": "checkpointed"}), flush=True)
    while True:
        time.sleep(0.05)


def main() -> int:
    arguments = sys.argv[1:]
    prompt = sys.stdin.read()
    worktree = Path(value(arguments, "-C"))
    result_path = Path(value(arguments, "--output-last-message"))
    plan_id = marker(prompt, "PLAN_ID")
    plan_path = Path(marker(prompt, "CURRENT_PLAN"))
    plan_lines = plan_path.read_text(encoding="utf-8").splitlines()
    scenario = plan_lines[0].split(":", 1)[1]
    blocker_resource = next(
        (
            line.split(":", 1)[1].strip()
            for line in plan_lines[1:]
            if line.startswith("blocker-resource:")
        ),
        plan_id,
    )
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

    provider_codes = {
        "provider_usage_blocked": "rate-limit-exceeded",
        "provider_auth_blocked": "invalid-api-key",
        "provider_unavailable": "provider-overloaded",
    }
    if scenario in provider_codes:
        print(
            json.dumps(
                {
                    "type": "error",
                    "error": {
                        "code": provider_codes[scenario],
                        "message": "RAW_PROVIDER_MESSAGE",
                    },
                    "message": "RAW_PROVIDER_MESSAGE",
                }
            ),
            flush=True,
        )
        return 1
    if scenario == "zero_empty_result":
        return 0
    if scenario == "nonzero_empty_result":
        return 1
    if scenario == "invalid_present_result":
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(
            json.dumps({"unexpected": "present but schema invalid"}),
            encoding="utf-8",
        )
        return 0

    if scenario in {"completed", "oversized_usage", "state_db_warnings"}:
        head = commit_plan(worktree, plan_id)
        status = "completed"
    elif scenario == "resume_completed":
        if attempt == 1:
            head = commit_plan(worktree, plan_id, "-progress")
            write_checkpoint_ledger(worktree, plan_id)
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
        if attempt == 1:
            commit_plan(worktree, plan_id)
        while True:
            print("waiting for timeout after commit", flush=True)
            time.sleep(0.05)
    elif scenario == "timeout_with_progress":
        if attempt == 1:
            head = commit_plan(worktree, plan_id, "-progress")
            write_checkpoint_ledger(worktree, plan_id)
            wait_for_launcher_timeout(
                result_path,
                checkpoint_payload(plan_id, head, scenario, attempt),
            )
        head = commit_plan(worktree, plan_id)
        status = "completed"
    elif scenario == "timeout_without_progress":
        wait_for_launcher_timeout(
            result_path,
            checkpoint_payload(plan_id, head, scenario, attempt),
        )
    elif scenario == "timeout_with_completed_result":
        head = commit_plan(worktree, plan_id)
        payload = {
            "plan_id": plan_id,
            "status": "completed",
            "head_commit": head,
            "summary": "completed payload before launcher timeout",
            "verification": [{
                "command_id": "fake-final",
                "argv_digest": "f" * 64,
                "phase": "branch_final",
                "evidence_key": "0" * 64,
                "exit_code": 0,
                "receipt_path": None,
            }],
            "checkpoint": None,
            "blocker": None,
            "workflow_receipt": workflow_receipt(worktree, head, plan_id),
        }
        wait_for_launcher_timeout(result_path, payload)
    elif scenario in {
        "timeout_with_malformed_ledger",
        "malformed_ledger_then_completed",
    } and attempt == 1:
        evidence = worktree / ".superpowers" / "sdd"
        evidence.mkdir(parents=True, exist_ok=True)
        (evidence / ".gitignore").write_text("*\n", encoding="utf-8")
        (evidence / "execution-ledger.jsonl").write_text(
            "{not-json}\n", encoding="utf-8"
        )
        wait_for_launcher_timeout(
            result_path,
            checkpoint_payload(plan_id, head, scenario, attempt),
        )
    elif scenario == "malformed_ledger_then_completed":
        schema_path = Path(marker(prompt, "EXECUTION_LEDGER_SCHEMA"))
        if not schema_path.is_file():
            raise SystemExit("execution ledger schema was not supplied")
        if marker(prompt, "RUN_AUTHORITY_PROFILE") != (
            "local-implementation-with-evidence-approvals"
        ):
            raise SystemExit("implementation authority profile was not supplied")
        head = commit_plan(worktree, plan_id)
        status = "completed"
    elif scenario == "timeout_with_ledger_deletion":
        if attempt == 1:
            head = commit_plan(worktree, plan_id, "-progress")
            write_checkpoint_ledger(worktree, plan_id)
        else:
            ledger = worktree / ".superpowers" / "sdd" / "execution-ledger.jsonl"
            ledger.unlink()
        wait_for_launcher_timeout(
            result_path,
            checkpoint_payload(plan_id, head, scenario, attempt),
        )
    elif scenario == "timeout_with_ledger_rewrite":
        if attempt == 1:
            head = commit_plan(worktree, plan_id, "-progress")
            write_checkpoint_ledger(worktree, plan_id)
        else:
            ledger = worktree / ".superpowers" / "sdd" / "execution-ledger.jsonl"
            event = json.loads(ledger.read_text(encoding="utf-8"))
            event["task_id"] = "task-rewritten"
            ledger.write_text(
                json.dumps(event, sort_keys=True) + "\n", encoding="utf-8",
            )
        wait_for_launcher_timeout(
            result_path,
            checkpoint_payload(plan_id, head, scenario, attempt),
        )
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
    elif scenario == "blocked_after_commit":
        head = commit_plan(worktree, plan_id, "-blocked")
        status = "blocked"

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
            "resource": blocker_resource,
            "operation": "execute_plan",
            "errno": None,
            "retry_condition": "operator resolves the fake blocker",
            "fingerprint": "2" * 64,
        }
    if status == "completed":
        payload["workflow_receipt"] = workflow_receipt(worktree, head, plan_id)
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
    if scenario == "state_db_warnings":
        for _ in range(4):
            print(
                "Warning: failed to update state db: database is locked",
                file=sys.stderr,
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
