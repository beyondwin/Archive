#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path


SESSION_ID = "12345678-1234-4234-8234-123456789abc"


def _value(argv: list[str], flag: str) -> str:
    return argv[argv.index(flag) + 1]


def _emit(document: object) -> None:
    sys.stdout.write(json.dumps(document, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _launch_number(log_path: Path) -> int:
    if not log_path.exists():
        return 1
    return len(log_path.read_text(encoding="utf-8").splitlines()) + 1


def _record(argv: list[str]) -> None:
    log_path = Path(os.environ["FAKE_CODEX_LOG"])
    selected = {
        key: value
        for key, value in os.environ.items()
        if key.startswith(("OPENAI_", "CODEX_", "GIT_CONFIG_", "KWS_PLAN_RUNNER_"))
        or key in {"GIT_TERMINAL_PROMPT", "SSH_AUTH_SOCK", "GH_TOKEN"}
    }
    record = {
        "argv": argv,
        "cwd": os.getcwd(),
        "env": selected,
        "launch_number": _launch_number(log_path),
        "prompt": sys.stdin.read(),
    }
    with log_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, sort_keys=True) + "\n")


def _write_result(argv: list[str], result: object) -> None:
    Path(_value(argv, "--output-last-message")).write_text(
        json.dumps(result), encoding="utf-8"
    )


def _commit_if_requested() -> None:
    marker = Path("implemented.txt")
    marker.write_text("implemented\n", encoding="utf-8")
    subprocess.run(["git", "add", str(marker)], check=True)
    subprocess.run(
        ["git", "-c", "user.name=Fake Codex", "-c", "user.email=fake@example.test",
         "commit", "-m", "fake implementation"],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def main() -> int:
    argv = sys.argv[1:]
    _record(argv)
    scenario = os.environ.get("FAKE_CODEX_SCENARIO", "initial")
    session_id = argv[-2] if "resume" in argv else SESSION_ID

    if scenario == "malformed-jsonl":
        sys.stdout.write("{not-json}\n")
        sys.stdout.flush()
        return 0
    if scenario == "oversized-jsonl":
        sys.stdout.write(json.dumps({"type": "log", "text": "x" * 70_000}) + "\n")
        sys.stdout.flush()
        return 0

    _emit({"type": "thread.started", "thread_id": session_id})
    _emit({"type": "turn.started", "turn_id": "turn-1"})
    _emit({"type": "item.started", "item": {"id": "tool-1", "type": "command"}})

    if scenario in {"repeated-log", "stall"}:
        deadline = time.monotonic() + (0.15 if scenario == "repeated-log" else 5)
        while time.monotonic() < deadline:
            _emit({"type": "item.delta", "item_id": "message-1", "delta": "token"})
            _emit({"type": "log", "message": "still working"})
            time.sleep(0.02)
        if scenario == "stall":
            time.sleep(5)

    if scenario == "resume-failure":
        _emit({"type": "error", "error": {"code": "session_not_found"}})
        return 2
    if scenario == "transport-failure":
        _emit({"type": "error", "error": {"code": "stream_disconnected"}})
        return 1
    if scenario == "context-overflow":
        _emit({"type": "error", "error": {"code": "context_window_exceeded"}})
        return 1
    if scenario in {"auth-blocked", "auth-then-unknown", "usage-blocked", "unavailable"}:
        codes = {
            "auth-blocked": "authentication_failed",
            "auth-then-unknown": "authentication_failed",
            "usage-blocked": "rate_limit",
            "unavailable": "overloaded",
        }
        _emit({"type": "error", "error": {"code": codes[scenario]}})
        if scenario == "auth-then-unknown":
            _emit({"type": "error", "error": {"code": "unrecognized_later_error"}})
        return 1
    if scenario == "stderr-secret":
        sys.stderr.write("x" * 1_100_000)
        sys.stderr.write("\nOPENAI_API_KEY=super-secret password=hunter2\n")
        sys.stderr.flush()

    _emit({"type": "item.completed", "item": {"id": "tool-1", "type": "command"}})
    _emit(
        {
            "type": "turn.completed",
            "turn_id": "turn-1",
            "usage": {"input_tokens": 12, "output_tokens": 7},
        }
    )
    if scenario == "invalid-output":
        _write_result(argv, ["not", "an", "object"])
        return 0
    if scenario == "implemented":
        _commit_if_requested()
        result = {"status": "implemented", "summary": "done"}
    elif scenario == "blocked":
        result = {"status": "blocked", "reason_code": "external_authority_required"}
    elif scenario == "failed":
        result = {"status": "failed", "reason_code": "verification_failed"}
    else:
        result = {"status": "implemented", "summary": scenario}
    _write_result(argv, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
