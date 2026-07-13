#!/usr/bin/env python3
"""Deterministic, network-free Codex boundary for lean schema-4 CPE evals."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path


WRITE_ROLES = frozenset({"task_agent", "fix_agent", "integration_fix_agent"})
VERDICT_ROLES = frozenset(
    {"reviewer", "document_auditor", "program_final_integrator"}
)
SCENARIOS = frozenset(
    {
        "success",
        "review_changes_requested",
        "ordinary_failure",
        "authority",
        "timeout",
        "timeout_leader_exits_descendant_survives",
        "dirty_handoff",
        "wrong_commit",
        "tampered_artifact_path",
    }
)


def _value(argv: list[str], flag: str) -> str:
    try:
        return argv[argv.index(flag) + 1]
    except (ValueError, IndexError) as exc:
        raise SystemExit(f"fake codex missing launcher argument: {flag}") from exc


def _prompt_value(prompt: str, name: str) -> str:
    match = re.search(rf"^{re.escape(name)}:\s*(.+)$", prompt, flags=re.MULTILINE)
    if match is None:
        raise SystemExit(f"fake codex missing prompt marker: {name}")
    return match.group(1).strip()


def _git(worktree: Path, *arguments: str) -> str:
    declared = os.environ.get("CPE_FAKE_GIT_BIN")
    git_bin = declared or ("/usr/bin/git" if Path("/usr/bin/git").is_file() else "git")
    completed = subprocess.run(
        [git_bin, "-C", str(worktree), *arguments],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return completed.stdout.strip()


def _write_report(outbox: Path, report_path: str) -> None:
    target = outbox / report_path
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    target.write_bytes(b"deterministic child report\n")
    target.chmod(0o600)


def _log_invocation(argv: list[str], prompt: str) -> None:
    declared = os.environ.get("CPE_FAKE_INVOCATION_LOG")
    if not declared:
        return
    names = {
        "PATH",
        "CODEX_HOME",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "GITHUB_TOKEN",
    }
    payload = {
        "argv": argv,
        "env": {key: value for key, value in os.environ.items() if key in names},
        "prompt": prompt,
    }
    with Path(declared).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def _commit_change(worktree: Path, item_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]", "-", item_id)
    relative = f"cpe-{safe}.txt"
    (worktree / relative).write_text("deterministic write role change\n", encoding="utf-8")
    _git(worktree, "add", "--", relative)
    _git(worktree, "commit", "-q", "-m", f"fake cpe {safe}")
    return _git(worktree, "rev-parse", "HEAD")


def main() -> int:
    argv = sys.argv[1:]
    if argv[:3] != ["exec", "--ignore-user-config", "--json"] or argv[-1:] != ["-"]:
        raise SystemExit("fake codex rejected launcher shape")
    prompt = sys.stdin.read()
    _log_invocation(argv, prompt)

    role = _prompt_value(prompt, "CPE_ROLE")
    item_id = _prompt_value(prompt, "ITEM")
    report_path = _prompt_value(prompt, "OUTBOX_REPORT_PATH")
    scenario = os.environ.get("CPE_FAKE_SCENARIO", "success")
    if scenario not in SCENARIOS:
        raise SystemExit(f"unknown fake scenario: {scenario}")
    worktree = Path(_value(argv, "-C")).resolve(strict=True)
    outbox = Path(_value(argv, "--add-dir")).resolve(strict=True)
    schema = Path(_value(argv, "--output-schema"))
    last_message = Path(_value(argv, "--output-last-message"))
    sandbox = _value(argv, "--sandbox")
    expected_sandbox = "workspace-write" if role in WRITE_ROLES else "read-only"
    if sandbox != expected_sandbox or not schema.is_file():
        raise SystemExit("fake codex rejected sandbox or result schema")
    if any(flag in argv for flag in ("--model", "--profile", "--config")):
        raise SystemExit("fake codex rejected forbidden policy argument")

    if scenario in {"timeout", "timeout_leader_exits_descendant_survives"}:
        child_code = "import time; time.sleep(60)"
        if scenario == "timeout_leader_exits_descendant_survives":
            child_code = (
                "import signal, time; "
                "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                "time.sleep(60)"
            )
        descendant = subprocess.Popen(
            [sys.executable, "-c", child_code],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        declared_pid = os.environ.get("CPE_FAKE_DESCENDANT_PID")
        if declared_pid:
            Path(declared_pid).write_text(str(descendant.pid), encoding="utf-8")
        time.sleep(60)
        return 99

    _write_report(outbox, report_path)
    status = "completed"
    verdict = "pass" if role in VERDICT_ROLES else None
    commit = None
    failure_code = None
    authority_id = None
    artifact_paths = [report_path]

    if scenario == "success" and role in WRITE_ROLES:
        commit = _commit_change(worktree, item_id)
    elif scenario == "review_changes_requested":
        status = "changes_requested"
        verdict = "changes_requested" if role in VERDICT_ROLES else None
    elif scenario == "ordinary_failure":
        status = "failed"
        verdict = None
        failure_code = "test_failure"
    elif scenario == "authority":
        status = "waiting_authority"
        verdict = "blocked" if role in VERDICT_ROLES else None
        authority_id = "credential_required"
    elif scenario == "dirty_handoff":
        (worktree / "fake-dirty-handoff.txt").write_text("dirty\n", encoding="utf-8")
    elif scenario == "wrong_commit":
        if role not in WRITE_ROLES:
            raise SystemExit("wrong_commit requires a write role")
        _commit_change(worktree, item_id)
        commit = _git(worktree, "rev-parse", "HEAD^")
    elif scenario == "tampered_artifact_path":
        artifact_paths = ["../escaped.md"]

    result = {
        "role": role,
        "status": status,
        "item_id": item_id,
        "commit": commit,
        "verdict": verdict,
        "failure_code": failure_code,
        "authority_id": authority_id,
        "strategy_key": "initial",
        "affected_document_ids": [],
        "artifact_paths": artifact_paths,
        "summary": f"deterministic {scenario} result",
    }
    last_message.write_text(json.dumps(result, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"type": "thread.started"}, sort_keys=True), flush=True)
    print(json.dumps({"type": "turn.completed"}, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
