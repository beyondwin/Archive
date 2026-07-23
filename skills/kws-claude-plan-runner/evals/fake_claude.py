#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


DEFAULT_SESSION = "00000000-0000-4000-8000-000000000001"


def emit(event: object) -> None:
    print(json.dumps(event, ensure_ascii=False, separators=(",", ":")), flush=True)


def flag_value(name: str) -> str | None:
    try:
        return sys.argv[sys.argv.index(name) + 1]
    except (ValueError, IndexError):
        return None


scenario = os.environ.get("FAKE_CLAUDE_SCENARIO", "success")
session_id = flag_value("--resume") or flag_value("--session-id") or DEFAULT_SESSION
log_path = Path(os.environ["FAKE_CLAUDE_LOG"])
launch_count = 1
if log_path.exists():
    launch_count += len(log_path.read_text(encoding="utf-8").splitlines())
record = {
    "argv": sys.argv[1:],
    "cwd": os.getcwd(),
    "launch_count": launch_count,
    "resume": "--resume" in sys.argv,
    "nesting_markers": {
        key: key in os.environ
        for key in (
            "CLAUDECODE",
            "CLAUDE_CODE_CHILD_SESSION",
            "CLAUDE_CODE_ENTRYPOINT",
        )
    },
    "credentials": {
        key: os.environ.get(key)
        for key in (
            "ANTHROPIC_API_KEY",
            "GH_TOKEN",
            "SSH_AUTH_SOCK",
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
            "GOOGLE_APPLICATION_CREDENTIALS",
        )
        if key in os.environ
    },
    "git_terminal_prompt": os.environ.get("GIT_TERMINAL_PROMPT"),
    "git_config_count": os.environ.get("GIT_CONFIG_COUNT"),
    "git_pushurl": os.environ.get("GIT_CONFIG_VALUE_0"),
    "helper_socket": os.environ.get("KWS_PLAN_RUNNER_HELPER_SOCKET"),
}
with log_path.open("a", encoding="utf-8") as stream:
    stream.write(json.dumps(record, sort_keys=True) + "\n")


def init() -> None:
    emit(
        {
            "type": "system",
            "subtype": "init",
            "session_id": session_id,
        }
    )


def assistant() -> None:
    emit(
        {
            "type": "assistant",
            "message": {
                "id": "message-1",
                "content": [{"type": "tool_use", "id": "tool-1", "name": "Bash"}],
            },
        }
    )


def tool_result() -> None:
    emit(
        {
            "type": "user",
            "message": {
                "id": "message-2",
                "content": [{"type": "tool_result", "tool_use_id": "tool-1"}],
            },
        }
    )


def result(
    *,
    subtype: str = "success",
    structured: object = ...,
    api_error_status: str | None = None,
) -> None:
    event = {
        "type": "result",
        "subtype": subtype,
        "session_id": session_id,
        "usage": {"input_tokens": 17, "output_tokens": 9},
    }
    if structured is not ...:
        event["structured_output"] = structured
    if api_error_status is not None:
        event["api_error_status"] = api_error_status
    emit(event)


if scenario != "session-missing":
    init()

if scenario == "success":
    assistant()
    tool_result()
    result(structured={"status": "implemented", "summary": "done"})
elif scenario == "explicit-resume":
    assistant()
    result(structured={"status": "implemented", "summary": "resumed"})
elif scenario in {"callback-then-invalid", "success-no-structured"}:
    result()
elif scenario == "rate-limit":
    emit(
        {
            "type": "rate_limit_event",
            "rate_limit_info": {"status": "rejected", "overageStatus": "allowed"},
        }
    )
    result(subtype="error", api_error_status="overloaded")
    raise SystemExit(1)
elif scenario == "allowed-rate-limit":
    emit(
        {
            "type": "rate_limit_event",
            "rate_limit_info": {"status": "allowed", "overageStatus": "rejected"},
        }
    )
    result(structured={"status": "implemented"})
elif scenario == "api-error":
    result(subtype="error", api_error_status="Overloaded")
    raise SystemExit(1)
elif scenario == "auth-error":
    result(subtype="error", api_error_status="authentication_failed")
    raise SystemExit(1)
elif scenario == "resume-failed":
    result(subtype="error", api_error_status="session_not_found")
    raise SystemExit(1)
elif scenario == "context-damaged":
    result(subtype="error", api_error_status="context_window_exceeded")
    raise SystemExit(1)
elif scenario == "interrupted":
    assistant()
    raise SystemExit(7)
elif scenario == "session-missing":
    result(structured={"status": "implemented"})
elif scenario == "repeated":
    assistant()
    assistant()
    tool_result()
    tool_result()
    result(structured={"status": "implemented"})
elif scenario == "stall":
    assistant()
    for _ in range(20):
        assistant()
        emit({"type": "stream_event", "event": {"type": "content_block_delta"}})
        time.sleep(0.03)
    result(structured={"status": "implemented"})
elif scenario == "malformed":
    print("{this is not json", flush=True)
elif scenario == "oversized":
    print("{" + '"value":"' + "x" * 70_000 + '"}', flush=True)
elif scenario == "stderr-secret":
    sys.stderr.write("x" * 1_100_000)
    sys.stderr.write("ANTHROPIC_API_KEY=super-secret password=hunter2\n")
    sys.stderr.flush()
    result(structured={"status": "implemented"})
else:
    raise SystemExit(f"unknown fake scenario: {scenario}")
