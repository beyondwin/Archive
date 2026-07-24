#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import fcntl
import hashlib
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


def _record(
    argv: list[str],
    prompt: str,
    *,
    action: str | None = None,
    action_index: int | None = None,
    session_id: str | None = None,
) -> None:
    log_value = os.environ.get("PLAN_RUNNER_FAKE_LOG")
    if log_value is None:
        log_value = os.environ["FAKE_CODEX_LOG"]
    log_path = Path(log_value)
    selected = {
        key: value
        for key, value in os.environ.items()
        if key.startswith(("OPENAI_", "CODEX_", "GIT_CONFIG_", "KWS_PLAN_RUNNER_"))
        or key
        in {
            "DATABASE_URL",
            "DOCKER_AUTH_CONFIG",
            "GIT_TERMINAL_PROMPT",
            "HOME",
            "PGPASSWORD",
            "SSH_AUTH_SOCK",
            "STRIPE_SECRET_KEY",
            "XDG_CONFIG_HOME",
            "GH_TOKEN",
        }
    }
    record = {
        "argv": argv,
        "cwd": os.getcwd(),
        "env": selected,
        "launch_number": _launch_number(log_path),
        "pid": os.getpid(),
        "prompt": prompt,
    }
    if action is not None:
        packet = _packet(prompt)
        record.update(
            {
                "action": action,
                "action_index": action_index,
                "mode": packet["mode"],
                "packet_digest": hashlib.sha256(
                    json.dumps(
                        packet,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest(),
                "required_strategy_change": packet.get(
                    "required_strategy_change"
                ),
                "session_action": "resume" if "resume" in argv else "fresh",
                "session_id": session_id,
            }
        )
    with log_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, sort_keys=True) + "\n")


def _write_result(argv: list[str], result: object) -> None:
    Path(_value(argv, "--output-last-message")).write_text(
        json.dumps(result), encoding="utf-8"
    )


def _commit_if_requested(
    marker_name: str = "implemented.txt",
    commit_message: str = "fake implementation",
) -> None:
    marker = Path(marker_name)
    marker.write_text("implemented\n", encoding="utf-8")
    subprocess.run(["git", "add", str(marker)], check=True)
    subprocess.run(
        ["git", "-c", "user.name=Plan Runner Parity",
         "-c", "user.email=parity@example.test",
         "commit", "-m", commit_message],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _packet(prompt: str) -> dict[str, object]:
    marker = "\nEXECUTION_PACKET="
    if marker not in prompt:
        raise ValueError("execution packet is missing")
    packet = json.loads(prompt.split(marker, 1)[1])
    if not isinstance(packet, dict):
        raise ValueError("execution packet is invalid")
    return packet


def _consume_action(path: Path) -> tuple[int, str]:
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.touch(mode=0o600, exist_ok=True)
    with lock_path.open("r+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        document = json.loads(path.read_text(encoding="utf-8"))
        if document.get("protocol_version") != 1:
            raise ValueError("fake sequence protocol is unsupported")
        actions = document.get("actions")
        index = document.get("next_index")
        if (
            not isinstance(actions, list)
            or not isinstance(index, int)
            or isinstance(index, bool)
            or not 0 <= index < len(actions)
            or not isinstance(actions[index], str)
        ):
            raise ValueError("fake sequence is exhausted or invalid")
        document["next_index"] = index + 1
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        temporary.write_text(
            json.dumps(document, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return index, actions[index]


def _helper_call(packet: dict[str, object], operation: str, payload: object) -> dict:
    helper = packet["helper"]
    envelope = {
        "protocol_version": helper["protocol_version"],
        "run_id": packet["run_id"],
        "nonce": helper["nonce"],
        "operation": operation,
        "payload": payload,
    }
    result = subprocess.run(
        helper["client_argv"],
        input=json.dumps(envelope),
        text=True,
        capture_output=True,
        check=True,
    )
    response = json.loads(result.stdout)
    if not isinstance(response, dict):
        raise ValueError("helper response is invalid")
    return response


def _generic_result(packet: dict[str, object], action: str) -> dict[str, object]:
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if action == "blocked":
        return {
            "status": "blocked",
            "head_commit": head,
            "summary": "external authority is required",
            "task_ledger": packet["task_ledger"],
            "open_obligation_ids": [],
            "failure_signature": None,
            "strategy_note": None,
            "blocker": {
                "kind": "external_authority_required",
                "detail": "provider-neutral parity blocker",
            },
        }
    return {
        "status": "implemented",
        "head_commit": head,
        "summary": "provider-neutral implementation",
        "task_ledger": packet["task_ledger"],
        "open_obligation_ids": [],
        "failure_signature": None,
        "strategy_note": None,
        "blocker": None,
    }


def _generic_finalization(packet: dict[str, object]) -> dict[str, object]:
    head = packet["candidate_head"]
    digest = packet.get("sealed_verification_set_digest")
    if digest is None:
        final_set = {
            "kind": "commands",
            "candidate_head": head,
            "commands": [
                {
                    "command_id": "parity-final",
                    "command_role": "final",
                    "argv": ["/usr/bin/true"],
                    "cwd": ".",
                    "input_digest": "a" * 64,
                    "deadline_seconds": 10,
                }
            ],
        }
        declaration = _helper_call(
            packet,
            "declare_final_set",
            {"candidate_head": head, "final_set": final_set},
        )
        digest = declaration["artifact"]["digest"]
        _helper_call(
            packet,
            "verify_final",
            {
                "candidate_head": head,
                "set_digest": digest,
                "command_index": 0,
                "deadline_seconds": 10,
            },
        )
    return {
        "status": "reviewed",
        "review_head": head,
        "verification_set_digest": digest,
        "open_findings": [],
        "open_obligation_ids": [],
        "no_applicable_verification_approved": False,
        "summary": "provider-neutral whole-branch review",
    }


def _generic_main(argv: list[str], prompt: str, sequence_path: Path) -> int:
    action_index, action = _consume_action(sequence_path)
    packet = _packet(prompt)
    session_id = (
        argv[-2]
        if "resume" in argv
        else str(uuid.UUID(int=action_index + 1))
    )
    _record(
        argv,
        prompt,
        action=action,
        action_index=action_index,
        session_id=session_id,
    )
    _emit({"type": "thread.started", "thread_id": session_id})
    if action in {"stalled", "dirty-stalled"}:
        if action == "dirty-stalled":
            Path("partial-provider-edit.txt").write_text(
                "partial implementation\n", encoding="utf-8"
            )
        time.sleep(2)
        return 7
    if action in {
        "interrupted",
        "same-failure",
        "dirty-invalid-result",
        "dirty-malformed-stream",
        "dirty-oversized-stream",
    }:
        Path("partial.txt").write_text("partial implementation\n", encoding="utf-8")
        if action == "dirty-malformed-stream":
            sys.stdout.write("{not-json}\n")
            sys.stdout.flush()
            return 0
        if action == "dirty-oversized-stream":
            sys.stdout.write(
                json.dumps({"type": "log", "text": "x" * 70_000}) + "\n"
            )
            sys.stdout.flush()
            return 0
        if action == "dirty-invalid-result":
            _emit({"type": "turn.started", "turn_id": f"turn-{action_index + 1}"})
            _emit(
                {
                    "type": "turn.completed",
                    "turn_id": f"turn-{action_index + 1}",
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                }
            )
            _write_result(argv, {"status": "implemented"})
            return 0
        return 7
    _emit({"type": "turn.started", "turn_id": f"turn-{action_index + 1}"})
    if action in {"implemented", "resume-dirty-implemented"}:
        index = packet["current_plan"]["index"]
        marker = f"plan-{index}.txt"
        Path(marker).write_text("implemented\n", encoding="utf-8")
        paths = [marker]
        partial = (
            Path("partial-provider-edit.txt")
            if Path("partial-provider-edit.txt").exists()
            else Path("partial.txt")
        )
        if action == "resume-dirty-implemented":
            if not partial.is_file():
                raise ValueError("sealed partial implementation is missing")
            paths.append(partial.name)
        subprocess.run(["git", "add", *paths], check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Plan Runner Parity",
                "-c",
                "user.email=parity@example.test",
                "commit",
                "-m",
                f"implement plan {index}",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        result = _generic_result(packet, "implemented")
    elif action == "blocked":
        result = _generic_result(packet, action)
    elif action == "finalized":
        result = _generic_finalization(packet)
    else:
        raise ValueError(f"unknown provider-neutral action: {action}")
    _emit(
        {
            "type": "turn.completed",
            "turn_id": f"turn-{action_index + 1}",
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }
    )
    _write_result(argv, result)
    return 0


def main() -> int:
    argv = sys.argv[1:]
    prompt = sys.stdin.read()
    sequence = os.environ.get("PLAN_RUNNER_FAKE_SEQUENCE")
    if sequence is not None:
        return _generic_main(argv, prompt, Path(sequence))
    _record(argv, prompt)
    scenario = os.environ.get("FAKE_CODEX_SCENARIO", "initial")
    session_id = argv[-2] if "resume" in argv else SESSION_ID

    if scenario in {"malformed-jsonl", "malformed-jsonl-ready"}:
        sys.stdout.write("{not-json}\n")
        sys.stdout.flush()
        if scenario == "malformed-jsonl-ready":
            Path(os.environ["FAKE_CODEX_LOG"] + ".ready").write_text(
                "ready\n", encoding="utf-8"
            )
            time.sleep(5)
        return 0
    if scenario == "oversized-jsonl":
        sys.stdout.write(json.dumps({"type": "log", "text": "x" * 70_000}) + "\n")
        sys.stdout.flush()
        return 0

    _emit({"type": "thread.started", "thread_id": session_id})
    _emit(
        {"type": "turn.started"}
        if scenario == "current-cli-lifecycle"
        else {"type": "turn.started", "turn_id": "turn-1"}
    )
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
            **(
                {}
                if scenario == "current-cli-lifecycle"
                else {"turn_id": "turn-1"}
            ),
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
