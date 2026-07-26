#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import fcntl
import hashlib
import subprocess
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


def packet_from_prompt(prompt: str) -> dict[str, object]:
    marker = "\nEXECUTION_PACKET="
    if marker not in prompt:
        raise ValueError("execution packet is missing")
    packet = json.loads(prompt.split(marker, 1)[1])
    if not isinstance(packet, dict):
        raise ValueError("execution packet is invalid")
    return packet


def consume_action(path: Path) -> tuple[int, str]:
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


def nested_git_init_probe(action_index: int) -> dict[str, object] | None:
    probe_root = os.environ.get("PLAN_RUNNER_FAKE_NESTED_GIT_INIT_ROOT")
    if probe_root is None:
        return None

    repository = Path(probe_root) / f"action-{action_index}"
    init_argv = ["git", "init", str(repository)]
    initialized = subprocess.run(
        init_argv,
        text=True,
        capture_output=True,
        check=False,
    )
    add_returncode: int | None = None
    commit_returncode: int | None = None
    if initialized.returncode == 0:
        probe_file = repository / "provider-child-probe.txt"
        probe_file.write_text("provider child nested git init\n", encoding="utf-8")
        added = subprocess.run(
            ["git", "-C", str(repository), "add", probe_file.name],
            text=True,
            capture_output=True,
            check=False,
        )
        add_returncode = added.returncode
        if added.returncode == 0:
            committed = subprocess.run(
                [
                    "git",
                    "-C",
                    str(repository),
                    "commit",
                    "-m",
                    "provider child probe",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            commit_returncode = committed.returncode

    git_dir = repository / ".git"
    hook_marker = os.environ.get("PARITY_HOSTILE_HOOK_MARKER")
    identity = None
    if commit_returncode == 0:
        raw_identity = subprocess.run(
            [
                "git",
                "-C",
                str(repository),
                "log",
                "-1",
                "--format=%an%x00%ae%x00%cn%x00%ce",
            ],
            text=True,
            capture_output=True,
            check=True,
        ).stdout.rstrip("\n").split("\0")
        identity = {
            "author_name": raw_identity[0],
            "author_email": raw_identity[1],
            "committer_name": raw_identity[2],
            "committer_email": raw_identity[3],
        }
    return {
        "add_returncode": add_returncode,
        "commit_returncode": commit_returncode,
        "git_template_dir": os.environ.get("GIT_TEMPLATE_DIR"),
        "identity": identity,
        "hostile_hook_copied": (git_dir / "hooks" / "pre-commit").exists(),
        "hostile_hook_executed": (
            hook_marker is not None and Path(hook_marker).exists()
        ),
        "hostile_template_marker_copied": (
            git_dir / "parity-hostile-template-marker"
        ).exists(),
        "init_argv": init_argv,
        "init_returncode": initialized.returncode,
    }


def helper_call(packet: dict[str, object], operation: str, payload: object) -> dict:
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


def generic_result(packet: dict[str, object], action: str) -> dict[str, object]:
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
            "verification_set_digest": None,
            "blocker": {
                "kind": "external_authority_required",
                "detail": "provider-neutral parity blocker",
            },
        }
    command = {
        "command_id": f"handoff-{packet['current_plan']['index']}",
        "command_role": "handoff",
        "argv": ["/usr/bin/true"],
        "cwd": ".",
        "input_digest": "a" * 64,
        "deadline_seconds": 10,
    }
    declaration = helper_call(
        packet,
        "declare_verification",
        {
            "candidate_head": head,
            "plan_index": packet["current_plan"]["index"],
            "verification": {
                "kind": "commands",
                "candidate_head": head,
                "commands": [command],
            },
            "prior_set_digests": packet["prior_verification_sets"],
            "is_final_plan": packet["is_final_plan"],
        },
    )
    digest = declaration["artifact"]["digest"]
    helper_call(
        packet,
        "run_verification",
        {
            "candidate_head": head,
            "set_digest": digest,
            "command_index": 0,
            "deadline_seconds": 10,
        },
    )
    return {
        "status": "implemented",
        "head_commit": head,
        "summary": "provider-neutral implementation",
        "verification_set_digest": digest,
        "blocker": None,
    }


def generic_emit_result(session_id: str, structured: object) -> None:
    emit(
        {
            "type": "result",
            "subtype": "success",
            "session_id": session_id,
            "usage": {"input_tokens": 1, "output_tokens": 1},
            "structured_output": structured,
        }
    )


def generic_main(sequence_path: Path) -> int:
    action_index, action = consume_action(sequence_path)
    prompt = flag_value("-p")
    if prompt is None:
        raise ValueError("Claude prompt is missing")
    packet = packet_from_prompt(prompt)
    session_id = flag_value("--resume") or flag_value("--session-id")
    if session_id is None:
        raise ValueError("Claude session is missing")
    log_path = Path(os.environ["PLAN_RUNNER_FAKE_LOG"])
    record = {
        "action": action,
        "action_index": action_index,
        "argv": sys.argv[1:],
        "cwd": os.getcwd(),
        "pid": os.getpid(),
        "mode": packet["mode"],
        "packet_digest": hashlib.sha256(
            json.dumps(
                packet,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
        "required_strategy_change": packet.get("required_strategy_change"),
        "session_action": "resume" if "--resume" in sys.argv else "fresh",
        "session_id": session_id,
    }
    nested_git_init = nested_git_init_probe(action_index)
    if nested_git_init is not None:
        record["nested_git_init"] = nested_git_init
    with log_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, sort_keys=True) + "\n")
    emit({"type": "system", "subtype": "init", "session_id": session_id})
    if action in {"stalled", "dirty-stalled", "canary-interrupt"}:
        if action == "dirty-stalled":
            Path("partial-provider-edit.txt").write_text(
                "partial implementation\n", encoding="utf-8"
            )
        if action == "canary-interrupt":
            Path("resume-marker.txt").write_text(
                "first plan handoff complete\n", encoding="utf-8"
            )
            subprocess.run(["git", "add", "resume-marker.txt"], check=True)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=Plan Runner Parity",
                    "-c",
                    "user.email=parity@example.test",
                    "commit",
                    "-m",
                    "canary interruption boundary",
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            Path("dirty-checkpoint.txt").write_text(
                "resume this exact checkpoint\n", encoding="utf-8"
            )
            time.sleep(300)
        time.sleep(2)
        return 7
    if action in {"interrupted", "clean-interrupted", "same-failure"}:
        return 7
    if action in {"implemented", "resume-dirty-implemented"}:
        index = packet["current_plan"]["index"]
        marker = Path(f"plan-{index}.txt")
        marker.write_text("implemented\n", encoding="utf-8")
        paths = [marker.name]
        partial = (
            Path("partial-provider-edit.txt")
            if Path("partial-provider-edit.txt").exists()
            else Path("dirty-checkpoint.txt")
        )
        if action == "resume-dirty-implemented":
            if not partial.is_file():
                raise ValueError("sealed partial implementation is missing")
            paths.append(partial.name)
        subprocess.run(["git", "add", *paths], check=True)
        commit_environment = dict(os.environ)
        commit_environment.update(
            {
                "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+00:00",
                "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+00:00",
            }
        )
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
            env=commit_environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        structured = generic_result(packet, "implemented")
    elif action == "blocked":
        structured = generic_result(packet, action)
    else:
        raise ValueError(f"unknown provider-neutral action: {action}")
    generic_emit_result(session_id, structured)
    return 0


generic_sequence = os.environ.get("PLAN_RUNNER_FAKE_SEQUENCE")
if generic_sequence is not None:
    raise SystemExit(generic_main(Path(generic_sequence)))


scenario = os.environ.get("FAKE_CLAUDE_SCENARIO", "success")
session_id = flag_value("--resume") or flag_value("--session-id") or DEFAULT_SESSION
log_path = Path(os.environ["FAKE_CLAUDE_LOG"])
launch_count = 1
if log_path.exists():
    launch_count += len(log_path.read_text(encoding="utf-8").splitlines())
record = {
    "argv": sys.argv[1:],
    "cwd": os.getcwd(),
    "pid": os.getpid(),
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
            "GITHUB_PAT",
            "BITBUCKET_APP_PASSWORD",
            "SSH_AUTH_SOCK",
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
            "AWS_SHARED_CREDENTIALS_FILE",
            "AWS_PROFILE",
            "GOOGLE_APPLICATION_CREDENTIALS",
            "CLOUDSDK_CONFIG",
            "AZURE_CONFIG_DIR",
            "DOCKER_CONFIG",
            "KUBECONFIG",
            "NETRC",
        )
        if key in os.environ
    },
    "git_terminal_prompt": os.environ.get("GIT_TERMINAL_PROMPT"),
    "git_config_count": os.environ.get("GIT_CONFIG_COUNT"),
    "git_pushurl": next(
        (
            os.environ.get(f"GIT_CONFIG_VALUE_{index}")
            for index in range(
                int(os.environ.get("GIT_CONFIG_COUNT", "0"))
            )
            if os.environ.get(f"GIT_CONFIG_KEY_{index}")
            == "remote.origin.pushurl"
        ),
        None,
    ),
    "git_identity": {
        "author_name": os.environ.get("GIT_AUTHOR_NAME"),
        "author_email": os.environ.get("GIT_AUTHOR_EMAIL"),
        "committer_name": os.environ.get("GIT_COMMITTER_NAME"),
        "committer_email": os.environ.get("GIT_COMMITTER_EMAIL"),
    },
    "helper_socket": os.environ.get("KWS_PLAN_RUNNER_HELPER_SOCKET"),
}
nested_git_init = nested_git_init_probe(launch_count - 1)
if nested_git_init is not None:
    record["nested_git_init"] = nested_git_init
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
elif scenario == "abnormal-compaction":
    result(subtype="error", api_error_status="abnormal_compaction")
    raise SystemExit(1)
elif scenario == "session-damaged":
    result(subtype="error", api_error_status="session_damage")
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
    sys.stderr.write("x" * 1_100_000 + "\n")
    sys.stderr.write("ANTHROPIC_API_KEY=super-secret password=hunter2\n")
    sys.stderr.flush()
    result(structured={"status": "implemented"})
elif scenario in {"stderr-boundary-key", "stderr-boundary-equals"}:
    assignment = (
        b"password=middle-secret\n"
        if scenario == "stderr-boundary-key"
        else b"password=equals-secret\n"
    )
    cut = 4 if scenario == "stderr-boundary-key" else len(b"password")
    suffix = b"x" * (1_048_576 - (len(assignment) - cut))
    sys.stderr.buffer.write(b"padding\n" + assignment + suffix)
    sys.stderr.buffer.flush()
    result(structured={"status": "implemented"})
else:
    raise SystemExit(f"unknown fake scenario: {scenario}")
