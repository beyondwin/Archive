#!/usr/bin/env python3
"""Small deterministic JSONL provider fixture for controller evals."""

from __future__ import annotations

import json
import os
import signal
import sys
import time
from pathlib import Path


SESSION_ID = "11111111-1111-4111-8111-111111111111"
SECOND_SESSION_ID = "22222222-2222-4222-8222-222222222222"
HEAD_COMMIT = "a" * 40
STATUS_DIGEST = "b" * 64
SCENARIOS = {
    "completed",
    "interrupted",
    "blocked_auth",
    "blocked_quota",
    "provider_unavailable",
    "session_unavailable",
    "transport",
    "invalid_envelope",
    "duplicate_session",
    "ignore_term",
}


def emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, separators=(",", ":")), flush=True)


def emit_session(session_id: str = SESSION_ID) -> None:
    emit({"type": "thread.started", "thread_id": session_id})


def emit_terminal(payload: dict[str, object]) -> None:
    emit(
        {
            "type": "item.completed",
            "item": {
                "type": "agent_message",
                "text": json.dumps(payload, separators=(",", ":")),
            },
        }
    )


def provider_error(code: str, scenario: str) -> int:
    print(f"RAW_PROVIDER_STDERR:{scenario}", file=sys.stderr, flush=True)
    emit(
        {
            "type": "error",
            "error": {
                "code": code,
                "message": f"RAW_PROVIDER_MESSAGE:{scenario}",
            },
        }
    )
    return 1


def expected_lock_is_inherited() -> bool:
    declared = os.environ.get("CPE_FAKE_EXPECT_LOCK_FD")
    if declared is None:
        return True
    try:
        os.fstat(int(declared))
    except (OSError, TypeError, ValueError):
        return False
    return True


def ignore_term_forever() -> int:
    marker = os.environ.get("CPE_FAKE_TERM_MARKER")

    def observe_term(_signal_number: int, _frame: object) -> None:
        if marker is not None:
            Path(marker).write_text("SIGTERM\n", encoding="utf-8")

    signal.signal(signal.SIGTERM, observe_term)
    emit_session()
    while True:
        time.sleep(0.05)


def main() -> int:
    scenario = os.environ.get("CPE_FAKE_SCENARIO", "completed")
    if scenario not in SCENARIOS:
        raise SystemExit(f"unsupported scenario: {scenario}")
    sys.stdin.read()

    if not expected_lock_is_inherited():
        return provider_error("transport-error", "missing-lock-fd")
    if scenario == "ignore_term":
        return ignore_term_forever()

    provider_codes = {
        "blocked_auth": "invalid-api-key",
        "blocked_quota": "rate-limit-exceeded",
        "provider_unavailable": "provider-overloaded",
        "session_unavailable": "session-not-found",
        "transport": "stream-disconnected",
    }
    if scenario in provider_codes:
        return provider_error(provider_codes[scenario], scenario)

    emit_session()
    if scenario == "duplicate_session":
        emit_session(SECOND_SESSION_ID)
    if scenario == "invalid_envelope":
        emit(
            {
                "type": "item.completed",
                "item": {
                    "type": "agent_message",
                    "text": "{not-json",
                },
            }
        )
    elif scenario == "interrupted":
        emit_terminal(
            {
                "claim": "interrupted",
                "head_commit": HEAD_COMMIT,
                "resume_capsule": {
                    "head_commit": HEAD_COMMIT,
                    "worktree_status_digest": STATUS_DIGEST,
                    "note": "provider process interrupted",
                    "evidence_refs": [],
                },
            }
        )
    else:
        emit_terminal(
            {
                "claim": "completed",
                "head_commit": HEAD_COMMIT,
            }
        )
    emit({"type": "turn.completed"})
    return 130 if scenario == "interrupted" else 0


if __name__ == "__main__":
    raise SystemExit(main())
