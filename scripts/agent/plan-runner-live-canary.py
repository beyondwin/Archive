#!/usr/bin/env python
"""Disposable live canaries for the two provider-specific plan runners.

Only bounded, normalized probe results are written to stdout. Provider prompts,
native streams, credentials, and stderr are deliberately never returned.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import platform
import re
import shutil
import signal
import stat
import subprocess
import sys
import sysconfig
import tempfile
import time
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
RESULT_LIMIT = 2_048
STREAM_LIMIT = 1_048_576
VERSION_LIMIT = 160
COMMAND_DEADLINE_SECONDS = 600.0
INTERRUPTION_BOUNDARY_DEADLINE_SECONDS = 1_800.0
RUNNER_DEADLINE_SECONDS = 7_200.0
TERM_GRACE_SECONDS = 1.0
GIT_ENV = {
    "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+00:00",
    "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+00:00",
}
AUTH_CODES = frozenset(
    {
        "authentication_error",
        "auth_error",
        "invalid_api_key",
        "login_required",
        "not_authenticated",
        "unauthorized",
    }
)
BLOCKED_REASON_CODES = frozenset(
    {
        "provider_auth_blocked",
        "provider_unavailable",
        "provider_usage_blocked",
        "runtime_incompatible",
        "runtime_missing",
        *AUTH_CODES,
    }
)
SAFE_RUNNER_FAILURE_CODES = BLOCKED_REASON_CODES | frozenset(
    {
        "controller_spawn_failed",
        "controller_transport_failed",
        "destructive_authorization_required",
        "external_authority_required",
        "input_changed_requires_new_run",
        "irreconcilable_requirements",
        "provider_command_failed",
        "recovery_exhausted",
        "review_failed",
        "session_invalid",
        "session_resume_failed",
        "stall_expired",
        "state_integrity_failed",
        "unknown_provider_stage_failure",
        "verification_failed",
        "verification_timed_out",
    }
)
AUTH_TEXT = re.compile(
    r"(?:not[ -]?logged[ -]?in|authentication|authenticate|unauthorized|"
    r"invalid[ _-]?(?:api[ _-]?)?key|login required|credential)",
    re.IGNORECASE,
)
FULL_HEAD = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
CANARY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "nonce": {
            "type": "string",
            "minLength": 32,
            "maxLength": 64,
            "pattern": "^[a-f0-9]+$",
        }
    },
    "required": ["nonce"],
}


class CanaryError(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


class InvocationError(ValueError):
    pass


class _SignalInterrupt(BaseException):
    def __init__(self, signum: int) -> None:
        super().__init__(signum)
        self.signum = signum


class ContractArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise InvocationError(message)


@dataclasses.dataclass(frozen=True)
class RuntimeIdentity:
    executable: str
    version: str
    architecture: str
    uv_version: str


@dataclasses.dataclass(frozen=True)
class CommandResult:
    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool


@dataclasses.dataclass(frozen=True)
class ParsedStream:
    status: str
    reason_code: str | None
    session_id: str | None
    structured: Mapping[str, Any] | None
    normalized: Mapping[str, Any]


@dataclasses.dataclass(frozen=True)
class SessionEvidence:
    initial_session_id: str | None
    resumed_session_id: str | None
    initial_nonce: str | None
    resumed_nonce: str | None
    head_before: str
    head_after: str
    porcelain: str


def _bounded_text(value: object, limit: int) -> str:
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    return text[:limit]


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def require_runtime() -> RuntimeIdentity:
    if sys.implementation.name != "cpython" or not (
        (3, 13) <= sys.version_info[:2] < (3, 14)
    ):
        raise CanaryError("runtime_incompatible")
    if bool(sysconfig.get_config_var("Py_GIL_DISABLED")):
        raise CanaryError("runtime_incompatible")
    is_gil_enabled = getattr(sys, "_is_gil_enabled", None)
    if callable(is_gil_enabled) and not is_gil_enabled():
        raise CanaryError("runtime_incompatible")
    executable = Path(sys.executable)
    try:
        resolved = executable.resolve(strict=True)
    except OSError as error:
        raise CanaryError("runtime_missing") from error
    if not resolved.is_file():
        raise CanaryError("runtime_missing")
    try:
        uv = subprocess.run(
            ["uv", "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise CanaryError("runtime_missing") from error
    if uv.returncode != 0 or not uv.stdout.strip():
        raise CanaryError("runtime_missing")
    return RuntimeIdentity(
        executable=str(resolved),
        version=platform.python_version(),
        architecture=platform.machine(),
        uv_version=_bounded_text(uv.stdout, VERSION_LIMIT),
    )


def codex_session_argv(
    *,
    root: Path,
    schema_path: Path,
    output_path: Path,
    session_id: str | None,
) -> list[str]:
    argv = [
        "codex",
        "exec",
        "--ignore-user-config",
        "--json",
        "--output-schema",
        str(schema_path),
        "--output-last-message",
        str(output_path),
        "--cd",
        str(root),
        "--sandbox",
        "read-only",
    ]
    if session_id is None:
        argv.append("-")
    else:
        uuid.UUID(session_id)
        argv.extend(("resume", session_id, "-"))
    return argv


def codex_probe_paths(root: Path) -> tuple[Path, Path]:
    return root.parent / "nonce.schema.json", root.parent / "nonce-result.json"


def claude_session_argv(
    *, prompt: str, session_id: str, resume: bool
) -> list[str]:
    canonical = str(uuid.UUID(session_id))
    argv = [
        "claude",
        "-p",
        prompt,
        "--output-format",
        "stream-json",
        "--verbose",
        "--json-schema",
        json.dumps(CANARY_SCHEMA, sort_keys=True, separators=(",", ":")),
        "--permission-mode",
        "plan",
        "--disallowedTools",
        "Bash",
        "Edit",
        "Write",
        "NotebookEdit",
    ]
    if resume:
        argv.extend(("--resume", canonical))
    else:
        argv.extend(("--session-id", canonical))
    return argv


def run_bounded(
    argv: Sequence[str],
    *,
    cwd: Path,
    timeout: float,
    input_text: str | None = None,
    env: Mapping[str, str] | None = None,
) -> CommandResult:
    saved_handlers = {
        signum: signal.getsignal(signum)
        for signum in (signal.SIGINT, signal.SIGTERM)
    }

    def interrupt(signum: int, _frame: object) -> None:
        raise _SignalInterrupt(signum)

    for signum in saved_handlers:
        signal.signal(signum, interrupt)
    process: subprocess.Popen[str] | None = None
    try:
        process = subprocess.Popen(
            list(argv),
            cwd=str(cwd),
            env=None if env is None else dict(env),
            stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=False,
            start_new_session=True,
        )
        try:
            stdout, stderr = process.communicate(input=input_text, timeout=timeout)
            timed_out = False
        except subprocess.TimeoutExpired:
            timed_out = True
            stdout, stderr = _terminate_and_reap(process)
        except BaseException:
            _terminate_and_reap(process)
            raise
    finally:
        for signum, handler in saved_handlers.items():
            signal.signal(signum, handler)
    assert process is not None
    return CommandResult(
        process.returncode,
        (stdout or "")[-STREAM_LIMIT:],
        (stderr or "")[-STREAM_LIMIT:],
        timed_out,
    )


def _terminate_and_reap(
    process: subprocess.Popen[str],
) -> tuple[str, str]:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        return process.communicate(timeout=TERM_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        return process.communicate()


def _json_lines(raw: str) -> tuple[list[Mapping[str, Any]], bool]:
    if len(raw.encode("utf-8", errors="replace")) > STREAM_LIMIT:
        return [], False
    events: list[Mapping[str, Any]] = []
    try:
        for line in raw.splitlines():
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, Mapping):
                return [], False
            events.append(value)
    except (UnicodeError, json.JSONDecodeError):
        return [], False
    return events, bool(events)


def _event_error_code(event: Mapping[str, Any]) -> str | None:
    candidates: list[object] = [
        event.get("code"),
        event.get("error_code"),
        event.get("api_error_status"),
    ]
    error = event.get("error")
    if isinstance(error, Mapping):
        candidates.extend((error.get("code"), error.get("type")))
    for candidate in candidates:
        if isinstance(candidate, str) and candidate:
            return re.sub(r"[^a-z0-9]+", "_", candidate.lower()).strip("_")[:80]
    return None


def parse_codex_stream(raw: str) -> ParsedStream:
    events, valid = _json_lines(raw)
    if not valid:
        return ParsedStream(
            "failed",
            "stream_malformed",
            None,
            None,
            {"status": "failed", "reason_code": "stream_malformed"},
        )
    session_id: str | None = None
    error_codes: list[str] = []
    malformed = False
    for event in events:
        candidate = None
        if event.get("type") in {"thread.started", "session.started"}:
            candidate = event.get("thread_id") or event.get("session_id")
        if candidate is not None:
            try:
                normalized = str(uuid.UUID(str(candidate)))
            except ValueError:
                malformed = True
                continue
            if session_id is not None and session_id != normalized:
                malformed = True
            session_id = normalized
        code = _event_error_code(event)
        if code:
            error_codes.append(code)
    if malformed:
        return ParsedStream(
            "failed",
            "session_discontinuous",
            session_id,
            None,
            {"status": "failed", "reason_code": "session_discontinuous"},
        )
    blocked = next(
        (code for code in error_codes if code in BLOCKED_REASON_CODES), None
    )
    if blocked is not None:
        reason = (
            "provider_auth_blocked"
            if blocked in AUTH_CODES or blocked == "provider_auth_blocked"
            else blocked
        )
        return ParsedStream(
            "blocked",
            reason,
            session_id,
            None,
            {"status": "blocked", "reason_code": reason},
        )
    return ParsedStream(
        "ok",
        None,
        session_id,
        None,
        {"status": "ok", "session_captured": session_id is not None},
    )


def parse_claude_stream(raw: str, *, expected_session_id: str) -> ParsedStream:
    try:
        expected = str(uuid.UUID(expected_session_id))
    except ValueError:
        expected = ""
    events, valid = _json_lines(raw)
    if not valid:
        return ParsedStream(
            "failed",
            "stream_malformed",
            None,
            None,
            {"status": "failed", "reason_code": "stream_malformed"},
        )
    session_id: str | None = None
    structured: Mapping[str, Any] | None = None
    error_codes: list[str] = []
    malformed = False
    for event in events:
        if event.get("type") == "system" and event.get("subtype") == "init":
            candidate = event.get("session_id")
            try:
                normalized = str(uuid.UUID(str(candidate)))
            except ValueError:
                malformed = True
                continue
            if normalized != expected or (
                session_id is not None and session_id != normalized
            ):
                malformed = True
            session_id = normalized
        if event.get("type") == "result":
            candidate = event.get("session_id")
            if candidate is not None:
                try:
                    if str(uuid.UUID(str(candidate))) != expected:
                        malformed = True
                except ValueError:
                    malformed = True
            value = event.get("structured_output")
            if isinstance(value, Mapping):
                structured = dict(value)
        code = _event_error_code(event)
        if code:
            error_codes.append(code)
    if malformed:
        return ParsedStream(
            "failed",
            "session_discontinuous",
            session_id,
            None,
            {"status": "failed", "reason_code": "session_discontinuous"},
        )
    blocked = next(
        (code for code in error_codes if code in BLOCKED_REASON_CODES), None
    )
    if blocked is not None:
        reason = (
            "provider_auth_blocked"
            if blocked in AUTH_CODES or blocked == "provider_auth_blocked"
            else blocked
        )
        return ParsedStream(
            "blocked",
            reason,
            session_id,
            None,
            {"status": "blocked", "reason_code": reason},
        )
    return ParsedStream(
        "ok",
        None,
        session_id,
        structured,
        {
            "status": "ok",
            "session_captured": session_id is not None,
            "structured_result": structured is not None,
        },
    )


def classify_provider_result(
    command: CommandResult, parsed: ParsedStream
) -> tuple[str, str | None]:
    if command.timed_out:
        return "failed", "provider_deadline"
    if parsed.status == "blocked":
        return "blocked", parsed.reason_code
    if parsed.status == "failed":
        return "failed", parsed.reason_code
    if command.returncode != 0:
        if AUTH_TEXT.search(command.stderr):
            return "blocked", "provider_auth_blocked"
        return "failed", "provider_command_failed"
    if parsed.session_id is None:
        return "failed", "session_missing"
    return "passed", None


def classify_runner_summary(
    returncode: int | None,
    summary: Mapping[str, Any] | None,
    stderr: str,
) -> tuple[str, str | None]:
    if isinstance(summary, Mapping):
        status = summary.get("status")
        reason = summary.get("reason_code")
        if status == "blocked" and isinstance(reason, str):
            normalized = re.sub(r"[^a-z0-9]+", "_", reason.lower()).strip("_")
            if normalized in BLOCKED_REASON_CODES:
                return (
                    "blocked",
                    "provider_auth_blocked"
                    if normalized in AUTH_CODES
                    else normalized,
                )
        if status == "blocked" and reason is None and isinstance(
            summary.get("run_id"), str
        ):
            return "blocked", "provider_unavailable"
        if (
            returncode == 0
            and status == "ready_for_integration"
            and isinstance(summary.get("run_id"), str)
        ):
            return "passed", None
        if status == "failed":
            normalized = (
                re.sub(r"[^a-z0-9]+", "_", reason.lower()).strip("_")
                if isinstance(reason, str)
                else ""
            )
            return (
                "failed",
                (
                    normalized
                    if normalized in SAFE_RUNNER_FAILURE_CODES
                    else "unknown_provider_stage_failure"
                ),
            )
    if AUTH_TEXT.search(stderr):
        return "blocked", "provider_auth_blocked"
    return "failed", "runner_not_ready"


def blocked_runner_reason(home: Path, provider: str, run_id: str) -> str | None:
    if (
        provider not in {"codex", "claude"}
        or re.fullmatch(r"[a-z0-9][a-z0-9-]{0,126}", run_id) is None
    ):
        return None
    path = home / f".{provider}" / "plan-runner" / run_id / "state.json"
    try:
        if path.stat().st_size > STREAM_LIMIT:
            return None
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(state, Mapping) or state.get("status") != "blocked":
        return None
    failure = state.get("failure")
    reason = failure.get("reason_code") if isinstance(failure, Mapping) else None
    if not isinstance(reason, str):
        return None
    normalized = re.sub(r"[^a-z0-9]+", "_", reason.lower()).strip("_")
    if normalized not in BLOCKED_REASON_CODES:
        return None
    return "provider_auth_blocked" if normalized in AUTH_CODES else normalized


def runner_failure_evidence(
    home: Path, provider: str, run_id: str
) -> dict[str, object] | None:
    if (
        provider not in {"codex", "claude"}
        or re.fullmatch(r"[a-z0-9][a-z0-9-]{0,126}", run_id) is None
    ):
        return None
    path = home / f".{provider}" / "plan-runner" / run_id / "state.json"
    descriptor = -1
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
        )
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) & 0o022
            or metadata.st_size > STREAM_LIMIT
        ):
            return None
        chunks: list[bytes] = []
        total = 0
        while total <= STREAM_LIMIT:
            chunk = os.read(
                descriptor,
                min(65_536, STREAM_LIMIT + 1 - total),
            )
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        raw = b"".join(chunks)
        if len(raw) != metadata.st_size:
            return None
        opened_after = os.fstat(descriptor)
        path_after = path.lstat()
        identity_before = (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_mode,
            metadata.st_uid,
            metadata.st_size,
            metadata.st_mtime_ns,
        )
        identity_opened_after = (
            opened_after.st_dev,
            opened_after.st_ino,
            opened_after.st_mode,
            opened_after.st_uid,
            opened_after.st_size,
            opened_after.st_mtime_ns,
        )
        identity_path_after = (
            path_after.st_dev,
            path_after.st_ino,
            path_after.st_mode,
            path_after.st_uid,
            path_after.st_size,
            path_after.st_mtime_ns,
        )
        if (
            identity_opened_after != identity_before
            or identity_path_after != identity_before
        ):
            return None
        state = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if not isinstance(state, Mapping):
        return None
    status = state.get("status")
    if status not in {
        "running",
        "recovering",
        "resumable",
        "blocked",
        "failed",
        "ready_for_integration",
    }:
        return None
    failure = state.get("failure")
    raw_reason = (
        failure.get("reason_code") if isinstance(failure, Mapping) else None
    )
    normalized_reason = (
        re.sub(r"[^a-z0-9]+", "_", raw_reason.lower()).strip("_")
        if isinstance(raw_reason, str)
        else ""
    )
    reason = (
        normalized_reason
        if normalized_reason in SAFE_RUNNER_FAILURE_CODES
        else "unknown_provider_stage_failure"
    )
    plans = state.get("plans")
    sessions = state.get("sessions")
    artifacts = state.get("artifact_refs")
    plan_items = plans if isinstance(plans, list) else []
    session_items = sessions if isinstance(sessions, list) else []
    artifact_items = artifacts if isinstance(artifacts, list) else []
    revision = state.get("revision")
    bounded_revision = (
        min(revision, 1_000_000)
        if isinstance(revision, int)
        and not isinstance(revision, bool)
        and revision >= 0
        else 0
    )
    return {
        "artifact_count": min(len(artifact_items), 1_000_000),
        "implemented_plan_count": min(
            sum(
                1
                for plan in plan_items
                if isinstance(plan, Mapping) and plan.get("status") == "implemented"
            ),
            1_000_000,
        ),
        "plan_count": min(len(plan_items), 1_000_000),
        "reason_code": reason,
        "receipt_count": min(
            sum(
                1
                for artifact in artifact_items
                if isinstance(artifact, Mapping)
                and isinstance(artifact.get("kind"), str)
                and (
                    artifact["kind"] == "receipt"
                    or artifact["kind"].endswith("_receipt")
                )
            ),
            1_000_000,
        ),
        "revision": bounded_revision,
        "runner_status": status,
        "session_count": min(len(session_items), 1_000_000),
        "state_sha256": hashlib.sha256(raw).hexdigest(),
    }


def validate_session_evidence(
    evidence: SessionEvidence,
) -> tuple[bool, str | None]:
    if (
        evidence.initial_session_id is None
        or evidence.resumed_session_id is None
        or evidence.initial_session_id != evidence.resumed_session_id
    ):
        return False, "session_discontinuous"
    if (
        evidence.initial_nonce is None
        or evidence.resumed_nonce is None
        or evidence.initial_nonce != evidence.resumed_nonce
    ):
        return False, "nonce_discontinuous"
    if evidence.head_before != evidence.head_after:
        return False, "repository_head_changed"
    if evidence.porcelain:
        return False, "repository_dirty"
    return True, None


def normalized_result(
    *,
    provider: str,
    mode: str,
    status: str,
    provider_version: str | None,
    session_action: str,
    final_head: str | None,
    elapsed: float,
    reason_code: str | None = None,
    failure_evidence: Mapping[str, object] | None = None,
) -> dict[str, object]:
    result: dict[str, object] = {
        "provider": provider,
        "mode": mode,
        "status": status,
        "provider_version": (
            _bounded_text(provider_version, VERSION_LIMIT)
            if provider_version
            else None
        ),
        "session_action": _bounded_text(session_action, 80),
        "final_head": final_head if final_head and FULL_HEAD.fullmatch(final_head) else None,
        "elapsed_seconds": round(max(0.0, elapsed), 3),
    }
    if reason_code is not None:
        result["reason_code"] = _bounded_text(reason_code, 80)
    if failure_evidence is not None:
        result["failure_evidence"] = dict(failure_evidence)
    if len(json.dumps(result, sort_keys=True)) > RESULT_LIMIT:
        raise CanaryError("normalized_result_too_large")
    return result


def _git(root: Path, *arguments: str, env: Mapping[str, str] | None = None) -> str:
    merged = dict(os.environ if env is None else env)
    merged.update(GIT_ENV)
    result = subprocess.run(
        ["git", *arguments],
        cwd=root,
        env=merged,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise CanaryError("git_command_failed")
    return result.stdout.strip()


def _create_repository(root: Path) -> str:
    root.mkdir(parents=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.name", "Plan Runner Canary")
    _git(root, "config", "user.email", "plan-runner-canary@example.invalid")
    (root / "seed.txt").write_text("plan runner live canary\n", encoding="utf-8")
    _git(root, "add", "seed.txt")
    _git(root, "commit", "-q", "-m", "test: seed canary repository")
    return _git(root, "rev-parse", "HEAD")


def _provider_version(
    provider: str, root: Path, env: Mapping[str, str]
) -> tuple[str | None, str | None]:
    executable = shutil.which(provider, path=env.get("PATH"))
    if executable is None:
        return None, "provider_unavailable"
    command = run_bounded(
        [executable, "--version"], cwd=root, timeout=20, env=env
    )
    if command.timed_out or command.returncode != 0:
        return None, "provider_unavailable"
    version = (command.stdout or command.stderr).strip()
    if not version:
        return None, "provider_unavailable"
    return _bounded_text(version, VERSION_LIMIT), None


def _read_nonce(path: Path) -> str | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    nonce = value.get("nonce") if isinstance(value, Mapping) else None
    return nonce if isinstance(nonce, str) else None


def _without_agentlens_shims(path: str) -> str:
    retained: list[str] = []
    for entry in path.split(os.pathsep):
        if not entry:
            continue
        parts = Path(entry).parts
        if len(parts) >= 2 and parts[-2:] == (".agentlens", "shims"):
            continue
        retained.append(entry)
    return os.pathsep.join(retained)


def isolated_provider_environment(
    provider: str,
    isolated_home: Path,
    *,
    operator_home: Path | None = None,
    source_env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    if provider not in {"codex", "claude"}:
        raise ValueError("unknown provider")
    operator = Path.home() if operator_home is None else operator_home
    env = dict(os.environ if source_env is None else source_env)
    effective_codex_home = env.get("CODEX_HOME")
    isolated_home.mkdir(mode=0o700, parents=True, exist_ok=True)
    isolated_home.chmod(0o700)
    env["HOME"] = str(isolated_home)
    for key in (
        "CODEX_HOME",
        "CLAUDE_CONFIG_DIR",
        "CLAUDECODE",
        "CLAUDE_CODE_ENTRYPOINT",
        "CLAUDE_CODE_SESSION_ACCESS_TOKEN",
    ):
        env.pop(key, None)
    if provider == "codex":
        if effective_codex_home in (None, ""):
            config = operator / ".codex"
        elif (
            not isinstance(effective_codex_home, str)
            or "\0" in effective_codex_home
        ):
            raise CanaryError("provider_auth_blocked")
        else:
            config = Path(effective_codex_home)
            if not config.is_absolute():
                raise CanaryError("provider_auth_blocked")
        env["CODEX_HOME"] = str(config)
    else:
        env["PATH"] = _without_agentlens_shims(env.get("PATH", ""))
        config = isolated_home / ".claude"
        config.mkdir(mode=0o700)
        env["CLAUDE_CONFIG_DIR"] = str(config)
    return env


def claude_explicit_auth_present(env: Mapping[str, str]) -> bool:
    return any(
        isinstance(env.get(key), str) and bool(env[key].strip())
        for key in (
            "ANTHROPIC_API_KEY",
            "ANTHROPIC_AUTH_TOKEN",
            "CLAUDE_CODE_OAUTH_TOKEN",
        )
    )


def _probe_codex_session(
    root: Path, env: Mapping[str, str]
) -> tuple[str, str | None, str]:
    schema, output = codex_probe_paths(root)
    schema.write_bytes(_canonical_json(CANARY_SCHEMA))
    head_before = _git(root, "rev-parse", "HEAD")
    nonce = uuid.uuid4().hex
    prompt = (
        "Return only the requested structured object with nonce "
        f"{nonce}. Remember it for the next turn. Do not modify files or Git."
    )
    first = run_bounded(
        codex_session_argv(
            root=root,
            schema_path=schema,
            output_path=output,
            session_id=None,
        ),
        cwd=root,
        timeout=COMMAND_DEADLINE_SECONDS,
        input_text=prompt,
        env=env,
    )
    parsed_first = parse_codex_stream(first.stdout)
    status, reason = classify_provider_result(first, parsed_first)
    if status != "passed":
        return status, reason, "fresh_session"
    first_nonce = _read_nonce(output)
    session_id = parsed_first.session_id
    if session_id is None:
        return "failed", "session_missing", "fresh_session"
    output.unlink(missing_ok=True)
    second_prompt = (
        "Return only the requested structured object containing exactly the "
        "nonce remembered from the previous turn. Do not modify files or Git."
    )
    second = run_bounded(
        codex_session_argv(
            root=root,
            schema_path=schema,
            output_path=output,
            session_id=session_id,
        ),
        cwd=root,
        timeout=COMMAND_DEADLINE_SECONDS,
        input_text=second_prompt,
        env=env,
    )
    parsed_second = parse_codex_stream(second.stdout)
    second_status, second_reason = classify_provider_result(second, parsed_second)
    if second_status != "passed":
        return second_status, second_reason, "resume_explicit"
    evidence = SessionEvidence(
        session_id,
        parsed_second.session_id,
        first_nonce,
        _read_nonce(output),
        head_before,
        _git(root, "rev-parse", "HEAD"),
        _git(root, "status", "--porcelain=v1"),
    )
    valid, reason = validate_session_evidence(evidence)
    return ("passed", None, "fresh_then_resume") if valid else (
        "failed",
        reason,
        "fresh_then_resume",
    )


def _probe_claude_session(
    root: Path, env: Mapping[str, str]
) -> tuple[str, str | None, str]:
    head_before = _git(root, "rev-parse", "HEAD")
    nonce = uuid.uuid4().hex
    session_id = str(uuid.uuid4())
    prompt = (
        "Return only the requested structured object with nonce "
        f"{nonce}. Remember it for the next turn. Do not modify files or Git."
    )
    first = run_bounded(
        claude_session_argv(
            prompt=prompt, session_id=session_id, resume=False
        ),
        cwd=root,
        timeout=COMMAND_DEADLINE_SECONDS,
        env=env,
    )
    parsed_first = parse_claude_stream(
        first.stdout, expected_session_id=session_id
    )
    status, reason = classify_provider_result(first, parsed_first)
    if status != "passed":
        return status, reason, "fresh_session"
    first_nonce = (
        parsed_first.structured.get("nonce")
        if isinstance(parsed_first.structured, Mapping)
        else None
    )
    second_prompt = (
        "Return only the requested structured object containing exactly the "
        "nonce remembered from the previous turn. Do not modify files or Git."
    )
    second = run_bounded(
        claude_session_argv(
            prompt=second_prompt, session_id=session_id, resume=True
        ),
        cwd=root,
        timeout=COMMAND_DEADLINE_SECONDS,
        env=env,
    )
    parsed_second = parse_claude_stream(
        second.stdout, expected_session_id=session_id
    )
    second_status, second_reason = classify_provider_result(second, parsed_second)
    if second_status != "passed":
        return second_status, second_reason, "resume_explicit"
    resumed_nonce = (
        parsed_second.structured.get("nonce")
        if isinstance(parsed_second.structured, Mapping)
        else None
    )
    evidence = SessionEvidence(
        parsed_first.session_id,
        parsed_second.session_id,
        first_nonce if isinstance(first_nonce, str) else None,
        resumed_nonce if isinstance(resumed_nonce, str) else None,
        head_before,
        _git(root, "rev-parse", "HEAD"),
        _git(root, "status", "--porcelain=v1"),
    )
    valid, reason = validate_session_evidence(evidence)
    return ("passed", None, "fresh_then_resume") if valid else (
        "failed",
        reason,
        "fresh_then_resume",
    )


def probe_session(provider: str) -> dict[str, object]:
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix=f"{provider}-session-canary-") as raw:
        root = Path(raw) / "repository"
        try:
            provider_env = isolated_provider_environment(
                provider, Path(raw) / "provider-home"
            )
            version, unavailable = _provider_version(
                provider, Path(raw), provider_env
            )
        except (CanaryError, OSError, ValueError) as error:
            reason = (
                error.reason_code
                if isinstance(error, CanaryError)
                else "provider_auth_blocked"
            )
            return normalized_result(
                provider=provider,
                mode="session",
                status="blocked",
                provider_version=None,
                session_action="not_started",
                final_head=None,
                elapsed=time.monotonic() - started,
                reason_code=reason,
            )
        if unavailable:
            return normalized_result(
                provider=provider,
                mode="session",
                status="blocked",
                provider_version=None,
                session_action="not_started",
                final_head=None,
                elapsed=time.monotonic() - started,
                reason_code=unavailable,
            )
        if provider == "claude" and not claude_explicit_auth_present(provider_env):
            return normalized_result(
                provider=provider,
                mode="session",
                status="blocked",
                provider_version=version,
                session_action="not_started",
                final_head=None,
                elapsed=time.monotonic() - started,
                reason_code="provider_auth_blocked",
            )
        try:
            _create_repository(root)
            if provider == "codex":
                status, reason, action = _probe_codex_session(root, provider_env)
            else:
                status, reason, action = _probe_claude_session(root, provider_env)
        except (CanaryError, OSError, ValueError) as error:
            status = "failed"
            reason = (
                error.reason_code
                if isinstance(error, CanaryError)
                else "session_probe_failed"
            )
            action = "not_completed"
        return normalized_result(
            provider=provider,
            mode="session",
            status=status,
            provider_version=version,
            session_action=action,
            final_head=None,
            elapsed=time.monotonic() - started,
            reason_code=reason,
        )


def _write_runner_documents(root: Path) -> tuple[list[Path], list[Path]]:
    docs = root / "immutable-inputs"
    docs.mkdir()
    specs = [docs / "01-product.md", docs / "02-verification.md"]
    plans = [docs / "01-alpha.md", docs / "02-beta.md"]
    specs[0].write_text(
        "# Canary product spec\n\n"
        "The repository exposes `alpha()` returning `alpha` and `beta()` "
        "returning `beta`. Preserve both behaviors once implemented.\n",
        encoding="utf-8",
    )
    specs[1].write_text(
        "# Canary verification spec\n\n"
        "Use only the Python standard library. The final required command is "
        f"`{Path(sys.executable).resolve()} -m unittest -v`. Commit every plan. "
        "Never merge, push, deploy, or modify source repository refs.\n",
        encoding="utf-8",
    )
    plans[0].write_text(
        "# Plan 1: alpha\n\n"
        "## Task 1\n\n"
        "Create `behaviors.py` with `alpha()` returning `alpha` and deterministic "
        "unittest coverage.\n\n"
        "## Task 2\n\n"
        "Run the focused test, commit the implementation, and report every task "
        "done through the runner protocol. Do not implement beta yet.\n",
        encoding="utf-8",
    )
    plans[1].write_text(
        "# Plan 2: beta\n\n"
        "## Task 1\n\n"
        "After preserving alpha, add `beta()` returning `beta` and deterministic "
        "unittest coverage.\n\n"
        "## Task 2\n\n"
        "Run all unittests, commit the implementation, and report every task "
        "done. For finalization declare "
        f"`{Path(sys.executable).resolve()} -m unittest -v` as the complete "
        "required verification set and perform the whole-branch review.\n",
        encoding="utf-8",
    )
    for path in (*specs, *plans):
        path.chmod(0o400)
    return specs, plans


def _artifact_from_ref(
    run_root: Path, ref: Mapping[str, Any]
) -> Mapping[str, Any]:
    if set(ref) != {"kind", "digest", "relative_path"}:
        raise CanaryError("artifact_reference_invalid")
    kind = ref.get("kind")
    relative = ref.get("relative_path")
    digest = ref.get("digest")
    if (
        not isinstance(kind, str)
        or not kind
        or not isinstance(relative, str)
        or not isinstance(digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", digest) is None
    ):
        raise CanaryError("artifact_reference_invalid")
    relative_path = Path(relative)
    expected = Path("artifacts") / kind / f"{digest}.json"
    if (
        relative_path != expected
        or relative_path.is_absolute()
        or ".." in relative_path.parts
    ):
        raise CanaryError("artifact_reference_invalid")
    path = run_root / relative_path
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise CanaryError("artifact_missing") from error
    if hashlib.sha256(raw).hexdigest() != digest:
        raise CanaryError("artifact_digest_mismatch")
    value = json.loads(raw)
    if not isinstance(value, Mapping) or _canonical_json(value) != raw:
        raise CanaryError("artifact_invalid")
    return value


def _references(state: Mapping[str, Any], kind: str) -> list[Mapping[str, Any]]:
    refs = state.get("artifact_refs")
    if not isinstance(refs, list):
        raise CanaryError("artifact_reference_invalid")
    return [
        ref
        for ref in refs
        if isinstance(ref, Mapping) and ref.get("kind") == kind
    ]


def _one_artifact(
    run_root: Path, state: Mapping[str, Any], kind: str
) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    refs = _references(state, kind)
    if len(refs) != 1:
        raise CanaryError(f"{kind}_missing")
    return refs[0], _artifact_from_ref(run_root, refs[0])


def _contains_workflow_state(value: object) -> bool:
    forbidden = {
        "task",
        "task_id",
        "task_ledger",
        "task_status",
        "finding",
        "findings",
        "open_findings",
        "finalization",
        "final_review_fix",
        "obligation",
        "obligations",
    }
    if isinstance(value, Mapping):
        return any(
            key in forbidden or _contains_workflow_state(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_workflow_state(item) for item in value)
    return False


def _scenario_command_identity(value: object) -> bytes | None:
    if not isinstance(value, Mapping):
        return None
    required = {"argv", "cwd", "input_digest", "deadline_seconds"}
    if not required.issubset(value) or not set(value).issubset(
        required | {"command_id", "command_role"}
    ):
        return None
    argv = value.get("argv")
    if (
        not isinstance(argv, list)
        or not argv
        or any(not isinstance(item, str) or not item for item in argv)
        or not isinstance(value.get("cwd"), str)
        or not isinstance(value.get("input_digest"), str)
        or re.fullmatch(r"[0-9a-f]{64}", value["input_digest"]) is None
        or not isinstance(value.get("deadline_seconds"), (int, float))
        or isinstance(value.get("deadline_seconds"), bool)
        or value["deadline_seconds"] <= 0
    ):
        return None
    return _canonical_json({key: value[key] for key in sorted(required)})


def validate_multi_plan_ownership_scenario(
    evidence: Mapping[str, Any],
) -> tuple[bool, str | None, str | None]:
    labels = evidence.get("plan_labels")
    if labels != [["Task 1", "Task 2"], ["Task 1", "Task 2"]]:
        return False, "plan_labels_not_reused", None
    source_head = evidence.get("source_head")
    observed_head = evidence.get("observed_head")
    if (
        not isinstance(source_head, str)
        or FULL_HEAD.fullmatch(source_head) is None
        or not isinstance(observed_head, str)
        or FULL_HEAD.fullmatch(observed_head) is None
    ):
        return False, "repository_head_invalid", None
    if evidence.get("porcelain") != "":
        return False, "runner_worktree_dirty", None
    if evidence.get("prior_handoff_is_ancestor") is not True:
        return False, "prior_handoff_not_ancestor", None

    state = evidence.get("state")
    if not isinstance(state, Mapping) or _contains_workflow_state(state):
        return False, "runner_owns_workflow_state", None
    if (
        state.get("format_version") != 2
        or state.get("contract_version") != 2
        or state.get("status") != "ready_for_integration"
        or state.get("integration") != "not_observed"
    ):
        return False, "run_not_ready", None
    plans = state.get("plans")
    if not isinstance(plans, list) or len(plans) != 2 or any(
        not isinstance(plan, Mapping) or plan.get("status") != "implemented"
        for plan in plans
    ):
        return False, "plans_not_implemented", None
    sessions = state.get("sessions")
    if not isinstance(sessions, list) or len(sessions) != 2:
        return False, "fresh_plan_sessions_missing", None
    session_ids: list[str] = []
    for index, session in enumerate(sessions):
        if (
            not isinstance(session, Mapping)
            or session.get("mode") != "implementation"
            or session.get("plan_index") != index
            or session.get("health") != "healthy"
            or not isinstance(session.get("session_id"), str)
            or not session["session_id"]
        ):
            return False, "fresh_plan_sessions_missing", None
        session_ids.append(session["session_id"])
    if len(set(session_ids)) != 2:
        return False, "plan_session_not_distinct", None

    handoffs = evidence.get("plan_handoffs")
    plan_sets = evidence.get("plan_verification_sets")
    run_set = evidence.get("run_verification_set")
    if (
        not isinstance(handoffs, list)
        or len(handoffs) != 2
        or not isinstance(plan_sets, list)
        or len(plan_sets) != 2
        or not isinstance(run_set, Mapping)
    ):
        return False, "handoff_evidence_missing", None
    heads: list[str] = []
    plan_set_digests: list[str] = []
    union: list[Mapping[str, Any]] = []
    seen: set[bytes] = set()
    for index, (plan, handoff, plan_set) in enumerate(
        zip(plans, handoffs, plan_sets, strict=True)
    ):
        if (
            not isinstance(handoff, Mapping)
            or not isinstance(plan_set, Mapping)
            or handoff.get("plan_index") != index
            or plan.get("handoff_digest") != handoff.get("digest")
            or not isinstance(handoff.get("head_commit"), str)
            or FULL_HEAD.fullmatch(handoff["head_commit"]) is None
            or not isinstance(plan_set.get("digest"), str)
            or re.fullmatch(r"[0-9a-f]{64}", plan_set["digest"]) is None
            or plan_set.get("candidate_head") != handoff["head_commit"]
        ):
            return False, "handoff_invalid", None
        heads.append(handoff["head_commit"])
        plan_set_digests.append(plan_set["digest"])
        commands = plan_set.get("commands")
        if not isinstance(commands, list) or not commands:
            return False, "verification_set_invalid", None
        for command in commands:
            identity = _scenario_command_identity(command)
            if identity is None:
                return False, "verification_set_invalid", None
            if identity not in seen:
                seen.add(identity)
                union.append(command)
    if (
        source_head in heads
        or len(set(heads)) != 2
        or heads[-1] != observed_head
    ):
        return False, "plan_commits_not_distinct", None
    if (
        handoffs[0].get("verification_set_digest") != plan_set_digests[0]
        or handoffs[-1].get("verification_set_digest") != run_set.get("digest")
        or run_set.get("candidate_head") != observed_head
        or run_set.get("plan_set_digests") != plan_set_digests
        or run_set.get("commands") != union
    ):
        return False, "final_run_union_invalid", None
    receipts = evidence.get("verification_receipts")
    observation = evidence.get("worktree_observation")
    if not isinstance(receipts, list) or len(receipts) != len(union):
        return False, "final_handoff_not_receipt_bound", None
    if (
        not isinstance(observation, Mapping)
        or observation.get("head") != observed_head
        or observation.get("clean") is not True
        or not isinstance(observation.get("tree_digest"), str)
    ):
        return False, "final_handoff_not_receipt_bound", None
    unmatched = list(union)
    for receipt in receipts:
        command = receipt.get("command") if isinstance(receipt, Mapping) else None
        document = receipt.get("receipt") if isinstance(receipt, Mapping) else None
        identity = (
            _validated_receipt_identity(
                document,
                observed_head,
                command_role=str(command.get("command_role")),
                worktree_digest=str(observation["tree_digest"]),
            )
            if isinstance(command, Mapping)
            else None
        )
        if (
            not isinstance(receipt, Mapping)
            or identity is None
            or command not in unmatched
            or identity.get("argv") != command.get("argv")
            or identity.get("input_digest") != command.get("input_digest")
        ):
            return False, "final_handoff_not_receipt_bound", None
        unmatched.remove(command)
    if unmatched:
        return False, "final_handoff_not_receipt_bound", None
    return True, None, observed_head


def validate_interruption_resume_scenario(
    evidence: Mapping[str, Any],
) -> tuple[bool, str | None, str | None]:
    if evidence.get("sigint_sent") is not True:
        return False, "sigint_not_observed", None
    if evidence.get("provider_process_group_quiescent") is not True:
        return False, "provider_process_group_not_quiescent", None
    if evidence.get("interrupted_status") != "resumable":
        return False, "interrupted_run_not_resumable", None
    interrupted = evidence.get("interrupted_checkpoint")
    resumed = evidence.get("resume_checkpoint")
    if (
        not isinstance(interrupted, Mapping)
        or interrupted.get("clean") is not False
        or resumed != interrupted
    ):
        return False, "dirty_checkpoint_changed", None
    recorded = evidence.get("recorded_session")
    if (
        not isinstance(recorded, Mapping)
        or recorded.get("health") != "healthy"
        or recorded.get("plan_index") != 1
        or not isinstance(recorded.get("session_id"), str)
        or evidence.get("resume_session_id") != recorded.get("session_id")
    ):
        return False, "recorded_healthy_session_not_resumed", None
    if (
        evidence.get("completed_first_handoff_before")
        != evidence.get("completed_first_handoff_after")
        or evidence.get("first_plan_session_count_before") != 1
        or evidence.get("first_plan_session_count_after") != 1
    ):
        return False, "completed_first_task_replayed", None
    final = evidence.get("final_ownership")
    if not isinstance(final, Mapping):
        return False, "final_handoff_missing", None
    valid, reason, head = validate_multi_plan_ownership_scenario(final)
    if not valid:
        return False, reason or "final_handoff_invalid", None
    if (
        evidence.get("drift_rejected") is not True
        or evidence.get("drift_reason_code") != "dirty_checkpoint_drift"
        or evidence.get("provider_launch_count_before_drift")
        != evidence.get("provider_launch_count_after_drift")
    ):
        return False, "dirty_drift_launched_provider", None
    return True, None, head


def validate_runner_state(
    state: Mapping[str, Any], *, observed_head: str, porcelain: str
) -> tuple[bool, str | None, str | None]:
    if state.get("status") != "ready_for_integration":
        return False, "run_not_ready", None
    if state.get("integration") != "not_observed":
        return False, "integration_observed", None
    plans = state.get("plans")
    if not isinstance(plans, list) or len(plans) != 2 or any(
        not isinstance(plan, Mapping) or plan.get("status") != "implemented"
        for plan in plans
    ):
        return False, "plans_not_implemented", None
    sessions = state.get("sessions")
    if not isinstance(sessions, list):
        return False, "sessions_missing", None
    implementation: dict[int, str] = {}
    final_sessions: list[str] = []
    for session in sessions:
        if not isinstance(session, Mapping):
            continue
        identifier = session.get("session_id")
        if not isinstance(identifier, str) or not identifier:
            continue
        if session.get("mode") == "implementation" and session.get(
            "plan_index"
        ) in (0, 1):
            implementation[int(session["plan_index"])] = identifier
        if session.get("mode") == "finalization":
            final_sessions.append(identifier)
    if set(implementation) != {0, 1}:
        return False, "plan_sessions_missing", None
    if len(set(implementation.values())) != 2:
        return False, "plan_session_not_distinct", None
    if not final_sessions or final_sessions[-1] in set(implementation.values()):
        return False, "final_session_not_separate", None
    finalization = state.get("finalization")
    if not isinstance(finalization, Mapping):
        return False, "finalization_missing", None
    candidate = finalization.get("candidate_head")
    if (
        not isinstance(candidate, str)
        or FULL_HEAD.fullmatch(candidate) is None
        or candidate != observed_head
    ):
        return False, "final_head_mismatch", None
    review_head = finalization.get("review_head", candidate)
    if review_head != candidate:
        return False, "review_head_mismatch", None
    commands = finalization.get("verification_commands")
    if commands is not None:
        if not isinstance(commands, list) or not commands or any(
            not isinstance(item, Mapping)
            or item.get("status") != "passed"
            or item.get("candidate_head") != candidate
            for item in commands
        ):
            return False, "verification_not_passed", None
    review = finalization.get("review")
    if review is not None and (
        not isinstance(review, Mapping)
        or review.get("status") not in {"approved", "reviewed"}
        or review.get("candidate_head") != candidate
    ):
        return False, "review_not_approved", None
    if porcelain:
        return False, "runner_worktree_dirty", None
    return True, None, candidate


def _validated_executable_identity(value: object) -> bool:
    if not isinstance(value, Mapping) or set(value) != {
        "path",
        "sha256",
        "mode",
        "size",
    }:
        return False
    path_value = value.get("path")
    digest = value.get("sha256")
    mode = value.get("mode")
    size = value.get("size")
    if (
        not isinstance(path_value, str)
        or not Path(path_value).is_absolute()
        or not isinstance(digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        or not isinstance(mode, int)
        or isinstance(mode, bool)
        or not stat.S_ISREG(mode)
        or not isinstance(size, int)
        or isinstance(size, bool)
        or size < 0
    ):
        return False
    try:
        executable = Path(path_value)
        metadata = executable.stat()
        actual_digest = hashlib.sha256(executable.read_bytes()).hexdigest()
    except OSError:
        return False
    return (
        metadata.st_mode == mode
        and metadata.st_size == size
        and actual_digest == digest
        and os.access(executable, os.X_OK)
    )


def _validated_receipt_identity(
    receipt: object,
    candidate: str,
    *,
    command_role: str = "final",
    worktree_digest: str | None = None,
) -> Mapping[str, Any] | None:
    if (
        not isinstance(receipt, Mapping)
        or set(receipt)
        != {
            "schema_version",
            "identity",
            "identity_digest",
            "outcome",
            "exit_code",
            "stdout_tail",
            "stderr_tail",
            "process",
        }
        or receipt.get("schema_version") != 1
        or receipt.get("outcome") != "success"
        or receipt.get("exit_code") != 0
    ):
        return None
    identity = receipt.get("identity")
    if not isinstance(identity, Mapping) or set(identity) != {
        "argv",
        "candidate_head",
        "command_role",
        "cwd",
        "environment_fingerprint",
        "executable_identity",
        "input_digest",
        "worktree_digest",
    }:
        return None
    argv = identity.get("argv")
    cwd = identity.get("cwd")
    digests = (
        identity.get("environment_fingerprint"),
        identity.get("input_digest"),
        identity.get("worktree_digest"),
        receipt.get("identity_digest"),
    )
    if (
        identity.get("candidate_head") != candidate
        or identity.get("command_role") != command_role
        or not isinstance(argv, list)
        or not argv
        or any(not isinstance(item, str) or not item for item in argv)
        or not isinstance(cwd, str)
        or not Path(cwd).is_absolute()
        or any(
            not isinstance(value, str)
            or re.fullmatch(r"[0-9a-f]{64}", value) is None
            for value in digests
        )
        or hashlib.sha256(_canonical_json(identity)).hexdigest()
        != receipt["identity_digest"]
        or not _validated_executable_identity(identity.get("executable_identity"))
        or (
            worktree_digest is not None
            and identity.get("worktree_digest") != worktree_digest
        )
    ):
        return None
    return identity


def _production_worktree_observation(
    provider: str,
    state: Mapping[str, Any],
) -> dict[str, object]:
    repository = state.get("repository")
    if provider not in {"codex", "claude"} or not isinstance(
        repository, Mapping
    ):
        raise CanaryError("dirty_checkpoint_changed")
    required = {
        "source_repository": repository.get("source_repository"),
        "worktree": repository.get("worktree"),
        "branch": repository.get("branch"),
    }
    if any(not isinstance(value, str) for value in required.values()):
        raise CanaryError("dirty_checkpoint_changed")
    scripts = (
        REPO_ROOT
        / f"skills/kws-{provider}-plan-runner/scripts"
    ).resolve(strict=True)
    source = """
import dataclasses, json, sys
sys.path.insert(0, sys.argv[1])
from plan_runner.git_ops import GitWorkspace
workspace = GitWorkspace.open(
    __import__("pathlib").Path(sys.argv[2]),
    __import__("pathlib").Path(sys.argv[3]),
    sys.argv[4],
)
print(json.dumps(dataclasses.asdict(workspace.observe()), sort_keys=True))
"""
    result = subprocess.run(
        [
            str(Path(sys.executable).resolve()),
            "-c",
            source,
            str(scripts),
            required["source_repository"],
            required["worktree"],
            required["branch"],
        ],
        cwd=REPO_ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        timeout=30,
    )
    try:
        observed = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise CanaryError("dirty_checkpoint_changed") from error
    if (
        result.returncode != 0
        or not isinstance(observed, dict)
        or set(observed)
        != {
            "head",
            "branch",
            "porcelain_digest",
            "tree_digest",
            "clean",
        }
    ):
        raise CanaryError("dirty_checkpoint_changed")
    return observed


def validate_runner_artifacts(
    state: Mapping[str, Any],
    run_root: Path,
    worktree: Path,
    candidate: str,
) -> tuple[bool, str | None]:
    try:
        set_ref, final_set = _one_artifact(
            run_root, state, "final_verification_set"
        )
        review_ref, review = _one_artifact(
            run_root, state, "final_review_receipt"
        )
        _handoff_ref, handoff = _one_artifact(run_root, state, "branch_handoff")
        all_receipt_refs = _references(state, "verification_receipt")
        all_ref_keys = [
            (ref.get("kind"), ref.get("digest"), ref.get("relative_path"))
            for ref in all_receipt_refs
        ]
        if len(all_ref_keys) != len(set(all_ref_keys)):
            return False, "verification_receipt_duplicate"
        for reference in all_receipt_refs:
            _artifact_from_ref(run_root, reference)
        refs = handoff.get("verification_receipts")
        if not isinstance(refs, list) or any(
            not isinstance(ref, Mapping) for ref in refs
        ):
            return False, "handoff_invalid"
        ref_keys = [
            (ref.get("kind"), ref.get("digest"), ref.get("relative_path"))
            for ref in refs
        ]
        if (
            len(ref_keys) != len(set(ref_keys))
            or any(ref not in all_receipt_refs for ref in refs)
        ):
            return False, "verification_receipt_duplicate"
        commands = final_set.get("commands")
        finalization = state.get("finalization")
        if (
            final_set.get("kind") != "commands"
            or final_set.get("candidate_head") != candidate
            or not isinstance(commands, list)
            or not commands
            or len(refs) != len(commands)
            or not isinstance(finalization, Mapping)
            or finalization.get("candidate_head") != candidate
            or finalization.get("review_head") != candidate
            or finalization.get("verification_set_digest") != set_ref.get("digest")
        ):
            return False, "verification_set_invalid"
        command_ids: set[str] = set()
        identities: list[Mapping[str, Any]] = []
        identity_digests: set[str] = set()
        for ref in refs:
            receipt = _artifact_from_ref(run_root, ref)
            identity = _validated_receipt_identity(receipt, candidate)
            if identity is None:
                return False, "verification_receipt_invalid"
            identity_digest = receipt.get("identity_digest")
            if identity_digest in identity_digests:
                return False, "verification_receipt_duplicate"
            assert isinstance(identity_digest, str)
            identity_digests.add(identity_digest)
            identities.append(identity)
        unmatched = list(identities)
        for command in commands:
            if not isinstance(command, Mapping) or set(command) != {
                "command_id",
                "command_role",
                "argv",
                "cwd",
                "input_digest",
                "deadline_seconds",
            }:
                return False, "verification_set_invalid"
            command_id = command.get("command_id")
            if (
                not isinstance(command_id, str)
                or not command_id
                or command_id in command_ids
                or command.get("command_role") != "final"
                or not isinstance(command.get("argv"), list)
                or not command["argv"]
                or not Path(command["argv"][0]).is_absolute()
                or not isinstance(command.get("cwd"), str)
                or Path(command["cwd"]).is_absolute()
                or ".." in Path(command["cwd"]).parts
                or not isinstance(command.get("input_digest"), str)
                or re.fullmatch(r"[0-9a-f]{64}", command["input_digest"]) is None
                or not isinstance(command.get("deadline_seconds"), (int, float))
                or isinstance(command.get("deadline_seconds"), bool)
                or command["deadline_seconds"] <= 0
            ):
                return False, "verification_set_invalid"
            command_ids.add(command_id)
            expected_cwd = str((worktree / command["cwd"]).resolve())
            try:
                Path(expected_cwd).relative_to(worktree.resolve())
            except ValueError:
                return False, "verification_set_invalid"
            match = next(
                (
                    identity
                    for identity in unmatched
                    if identity.get("argv") == command.get("argv")
                    and identity.get("cwd") == expected_cwd
                    and identity.get("input_digest") == command.get("input_digest")
                    and identity.get("candidate_head") == candidate
                    and identity.get("command_role") == "final"
                    and identity.get("executable_identity", {}).get("path")
                    == str(Path(command["argv"][0]).resolve(strict=True))
                ),
                None,
            )
            if match is None:
                return False, "verification_receipt_identity_mismatch"
            unmatched.remove(match)
        if unmatched:
            return False, "verification_receipt_identity_mismatch"
        findings = review.get("open_findings")
        review_approved = (
            isinstance(findings, list)
            and all(
                isinstance(item, Mapping)
                and item.get("severity") not in {"Critical", "Important"}
                for item in findings
            )
        )
        if (
            review.get("status") != "reviewed"
            or review.get("candidate_head") != candidate
            or review.get("review_head") != candidate
            or review.get("verification_set_digest") != set_ref.get("digest")
            or not review_approved
            or review.get("open_obligation_ids") != []
        ):
            return False, "review_not_approved"
        if (
            handoff.get("status") != "ready_for_integration"
            or handoff.get("candidate_head") != candidate
            or handoff.get("review_head") != candidate
            or handoff.get("verification_set_digest") != set_ref.get("digest")
            or handoff.get("review_receipt") != review_ref
            or handoff.get("verification_receipts") != refs
            or handoff.get("integration") != "not_observed"
        ):
            return False, "handoff_invalid"
    except (CanaryError, OSError, ValueError, json.JSONDecodeError) as error:
        return False, (
            error.reason_code
            if isinstance(error, CanaryError)
            else "final_evidence_invalid"
        )
    return True, None


def _runner_environment(provider: str, home: Path) -> dict[str, str]:
    env = isolated_provider_environment(provider, home)
    env.pop("KWS_PLAN_RUNNER_HELPER_SOCKET", None)
    env.pop("KWS_PLAN_RUNNER_HELPER_NONCE", None)
    return env


def _artifact_with_digest(
    run_root: Path,
    state: Mapping[str, Any],
    kind: str,
    digest: str,
) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    matches = [
        ref
        for ref in _references(state, kind)
        if ref.get("digest") == digest
    ]
    if len(matches) != 1:
        raise CanaryError(f"{kind}_missing")
    return matches[0], _artifact_from_ref(run_root, matches[0])


def _ownership_evidence_from_run(
    *,
    state: Mapping[str, Any],
    run_root: Path,
    worktree: Path,
    plans: Sequence[Path],
    project_resumed_sessions: bool = False,
) -> dict[str, object]:
    plan_records = state.get("plans")
    repository = state.get("repository")
    if (
        not isinstance(plan_records, list)
        or len(plan_records) != 2
        or not isinstance(repository, Mapping)
    ):
        raise CanaryError("plans_not_implemented")
    labels = [
        re.findall(r"^## (Task [12])$", path.read_text(encoding="utf-8"), re.MULTILINE)
        for path in plans
    ]
    handoffs: list[dict[str, object]] = []
    plan_sets_by_index: dict[int, dict[str, object]] = {}
    for index, plan in enumerate(plan_records):
        if not isinstance(plan, Mapping) or not isinstance(
            plan.get("handoff_digest"), str
        ):
            raise CanaryError("handoff_evidence_missing")
        handoff_ref, handoff_value = _artifact_with_digest(
            run_root,
            state,
            "plan_handoff",
            plan["handoff_digest"],
        )
        handoffs.append({"digest": handoff_ref["digest"], **dict(handoff_value)})
        plan_set_digest = (
            handoff_value.get("verification_set_digest")
            if index == 0
            else None
        )
        if isinstance(plan_set_digest, str):
            plan_ref, plan_value = _artifact_with_digest(
                run_root, state, "plan_verification_set", plan_set_digest
            )
            plan_sets_by_index[index] = {
                "digest": plan_ref["digest"],
                **dict(plan_value),
            }
    for reference in _references(state, "plan_verification_set"):
        value = _artifact_from_ref(run_root, reference)
        index = value.get("plan_index")
        if index in (0, 1):
            plan_sets_by_index[int(index)] = {
                "digest": reference["digest"],
                **dict(value),
            }
    if set(plan_sets_by_index) != {0, 1}:
        raise CanaryError("verification_set_invalid")
    final_digest = handoffs[-1].get("verification_set_digest")
    if not isinstance(final_digest, str):
        raise CanaryError("verification_set_invalid")
    run_ref, run_value = _artifact_with_digest(
        run_root, state, "run_verification_set", final_digest
    )
    run_set = {"digest": run_ref["digest"], **dict(run_value)}
    observed_head = _git(worktree, "rev-parse", "HEAD")
    observed_tree = _production_worktree_observation(
        str(state.get("provider")), state
    )
    final_commands = run_set.get("commands")
    if not isinstance(final_commands, list):
        raise CanaryError("verification_set_invalid")
    receipts: list[dict[str, object]] = []
    for reference in _references(state, "verification_receipt"):
        receipt = _artifact_from_ref(run_root, reference)
        matching = next(
            (
                command
                for command in final_commands
                if isinstance(command, Mapping)
                and (
                    identity := _validated_receipt_identity(
                        receipt,
                        observed_head,
                        command_role=str(command.get("command_role")),
                        worktree_digest=str(observed_tree["tree_digest"]),
                    )
                )
                is not None
                and command.get("argv") == identity.get("argv")
                and command.get("input_digest") == identity.get("input_digest")
                and isinstance(command.get("cwd"), str)
                and identity.get("cwd")
                == str((worktree / command["cwd"]).resolve())
            ),
            None,
        )
        if matching is not None:
            receipts.append(
                {
                    "artifact_ref": dict(reference),
                    "receipt": dict(receipt),
                    "command": matching,
                }
            )
    first_head = handoffs[0].get("head_commit")
    ancestry = False
    if isinstance(first_head, str):
        check = subprocess.run(
            ["git", "merge-base", "--is-ancestor", first_head, observed_head],
            cwd=worktree,
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
        ancestry = check.returncode == 0
    projected_state = dict(state)
    if project_resumed_sessions:
        sessions = state.get("sessions")
        selected: list[Mapping[str, Any]] = []
        if isinstance(sessions, list):
            for index in (0, 1):
                matching = [
                    session
                    for session in sessions
                    if isinstance(session, Mapping)
                    and session.get("mode") == "implementation"
                    and session.get("plan_index") == index
                    and session.get("health") == "healthy"
                ]
                if matching:
                    selected.append(dict(matching[0]))
        projected_state["sessions"] = selected
    return {
        "plan_labels": labels,
        "source_head": repository.get("source_commit"),
        "observed_head": observed_head,
        "porcelain": _git(worktree, "status", "--porcelain=v1"),
        "worktree_observation": observed_tree,
        "prior_handoff_is_ancestor": ancestry,
        "state": projected_state,
        "plan_handoffs": handoffs,
        "plan_verification_sets": [
            plan_sets_by_index[0],
            plan_sets_by_index[1],
        ],
        "run_verification_set": run_set,
        "verification_receipts": receipts,
    }


def probe_runner(
    provider: str, *, scenario_mode: str = "runner"
) -> dict[str, object]:
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix=f"{provider}-runner-canary-") as raw:
        root = Path(raw).resolve(strict=True)
        home = root / "operator-home"
        home.mkdir(mode=0o700)
        try:
            runner_env = _runner_environment(provider, home)
            version, unavailable = _provider_version(provider, root, runner_env)
        except (CanaryError, OSError, ValueError) as error:
            reason = (
                error.reason_code
                if isinstance(error, CanaryError)
                else "provider_auth_blocked"
            )
            return normalized_result(
                provider=provider,
                mode=scenario_mode,
                status="blocked",
                provider_version=None,
                session_action="not_started",
                final_head=None,
                elapsed=time.monotonic() - started,
                reason_code=reason,
            )
        if unavailable:
            return normalized_result(
                provider=provider,
                mode=scenario_mode,
                status="blocked",
                provider_version=None,
                session_action="not_started",
                final_head=None,
                elapsed=time.monotonic() - started,
                reason_code=unavailable,
            )
        if provider == "claude" and not claude_explicit_auth_present(runner_env):
            return normalized_result(
                provider=provider,
                mode=scenario_mode,
                status="blocked",
                provider_version=version,
                session_action="not_started",
                final_head=None,
                elapsed=time.monotonic() - started,
                reason_code="provider_auth_blocked",
            )
        workspace = root / "source"
        try:
            _create_repository(workspace)
            specs, plans = _write_runner_documents(root)
            runner = (
                REPO_ROOT
                / f"skills/kws-{provider}-plan-runner/scripts/runner"
            )
            argv = _runner_argv(
                provider,
                runner,
                "run",
                workspace=workspace,
                specs=specs,
                plans=plans,
            )
            command = run_bounded(
                argv,
                cwd=root,
                timeout=RUNNER_DEADLINE_SECONDS,
                env=runner_env,
            )
            if command.timed_out:
                raise CanaryError("runner_deadline")
            summaries = [
                value
                for line in command.stdout.splitlines()
                if line.strip()
                for value in [json.loads(line)]
                if isinstance(value, Mapping)
            ]
            summary = summaries[-1] if summaries else None
            classification, classified_reason = classify_runner_summary(
                command.returncode,
                summary if isinstance(summary, Mapping) else None,
                command.stderr,
            )
            if classification == "blocked":
                run_id_value = (
                    summary.get("run_id")
                    if isinstance(summary, Mapping)
                    else None
                )
                durable_reason = (
                    blocked_runner_reason(home, provider, run_id_value)
                    if isinstance(run_id_value, str)
                    else None
                )
                return normalized_result(
                    provider=provider,
                    mode=scenario_mode,
                    status="blocked",
                    provider_version=version,
                    session_action="not_completed",
                    final_head=None,
                    elapsed=time.monotonic() - started,
                    reason_code=durable_reason or classified_reason,
                )
            if classification != "passed" or not isinstance(summary, Mapping):
                run_id_value = (
                    summary.get("run_id")
                    if isinstance(summary, Mapping)
                    else None
                )
                evidence = (
                    runner_failure_evidence(home, provider, run_id_value)
                    if isinstance(run_id_value, str)
                    else None
                )
                reason = (
                    evidence.get("reason_code")
                    if isinstance(evidence, Mapping)
                    and isinstance(evidence.get("reason_code"), str)
                    else classified_reason or "unknown_provider_stage_failure"
                )
                return normalized_result(
                    provider=provider,
                    mode=scenario_mode,
                    status="failed",
                    provider_version=version,
                    session_action="not_completed",
                    final_head=None,
                    elapsed=time.monotonic() - started,
                    reason_code=reason,
                    failure_evidence=evidence,
                )
            run_id = summary["run_id"]
            state_root = home / f".{provider}" / "plan-runner" / run_id
            state = json.loads((state_root / "state.json").read_text(encoding="utf-8"))
            worktree = Path(state["repository"]["worktree"])
            observed = _git(worktree, "rev-parse", "HEAD")
            porcelain = _git(worktree, "status", "--porcelain=v1")
            if scenario_mode == "ownership":
                evidence = _ownership_evidence_from_run(
                    state=state,
                    run_root=state_root,
                    worktree=worktree,
                    plans=plans,
                )
                valid, reason, candidate = (
                    validate_multi_plan_ownership_scenario(evidence)
                )
                if not valid or candidate is None:
                    raise CanaryError(reason or "ownership_evidence_invalid")
            else:
                valid, reason, candidate = validate_runner_state(
                    state, observed_head=observed, porcelain=porcelain
                )
                if not valid or candidate is None:
                    raise CanaryError(reason or "runner_state_invalid")
                valid, reason = validate_runner_artifacts(
                    state, state_root, worktree, candidate
                )
                if not valid:
                    raise CanaryError(reason or "final_evidence_invalid")
            before = hashlib.sha256((state_root / "state.json").read_bytes()).hexdigest()
            inspect = run_bounded(
                [str(runner), "inspect", "--run-id", run_id],
                cwd=root,
                timeout=60,
                env=runner_env,
            )
            after = hashlib.sha256((state_root / "state.json").read_bytes()).hexdigest()
            if inspect.returncode != 0 or before != after:
                raise CanaryError("inspect_mutated_state")
            inspect_lines = [
                json.loads(line)
                for line in inspect.stdout.splitlines()
                if line.strip()
            ]
            if (
                not inspect_lines
                or inspect_lines[-1].get("status") != "ready_for_integration"
                or inspect_lines[-1].get("integration") != "not_observed"
            ):
                raise CanaryError("inspect_facts_mismatch")
            return normalized_result(
                provider=provider,
                mode=scenario_mode,
                status="passed",
                provider_version=version,
                session_action=(
                    "two_fresh_plan_sessions"
                    if scenario_mode == "ownership"
                    else "distinct_plan_and_final_sessions"
                ),
                final_head=candidate,
                elapsed=time.monotonic() - started,
            )
        except (CanaryError, OSError, ValueError, KeyError, json.JSONDecodeError) as error:
            reason = (
                error.reason_code
                if isinstance(error, CanaryError)
                else "runner_probe_failed"
            )
            return normalized_result(
                provider=provider,
                mode=scenario_mode,
                status="failed",
                provider_version=version,
                session_action="not_completed",
                final_head=None,
                elapsed=time.monotonic() - started,
                reason_code=reason,
            )


def _write_interruption_documents(
    root: Path,
) -> tuple[list[Path], list[Path]]:
    docs = root / "immutable-inputs"
    docs.mkdir()
    specs = [docs / "01-product.md", docs / "02-verification.md"]
    plans = [docs / "01-alpha.md", docs / "02-interruption.md"]
    specs[0].write_text(
        "# Interruption canary product spec\n\n"
        "The repository must finish with committed `alpha()` and `beta()` "
        "functions returning their names and deterministic unittest coverage.\n",
        encoding="utf-8",
    )
    specs[1].write_text(
        "# Interruption canary verification spec\n\n"
        "Use only the Python standard library. Preserve an existing dirty "
        "checkpoint exactly across controller interruption. The final required "
        f"command is `{Path(sys.executable).resolve()} -m unittest -v`. "
        "Never merge, push, deploy, or modify source repository refs.\n",
        encoding="utf-8",
    )
    plans[0].write_text(
        "# Plan 1: alpha\n\n"
        "## Task 1\n\n"
        "Create `behaviors.py` with `alpha()` returning `alpha` and add its "
        "deterministic unittest.\n\n"
        "## Task 2\n\n"
        "Run the focused test and commit the complete plan.\n",
        encoding="utf-8",
    )
    plans[1].write_text(
        "# Plan 2: interrupted beta\n\n"
        "## Task 1\n\n"
        "Create `resume-marker.txt` containing exactly `task 1 complete`, add "
        "and commit it by itself. Do not start Task 2 before that commit.\n\n"
        "## Task 2\n\n"
        "Create untracked `dirty-checkpoint.txt` containing exactly "
        "`resume this exact checkpoint`. Before staging or committing that file, "
        "run `/bin/sleep 300` in the foreground. If the controller interrupts "
        "the command and later resumes this same session, do not recreate, "
        "rewrite, stage, clean, or restore the existing dirty file. Continue "
        "from it: add `beta()` returning `beta`, add deterministic unittest "
        "coverage, include the unchanged checkpoint file in the final commit, "
        "run all unittests, and complete the plan. Declare "
        f"`{Path(sys.executable).resolve()} -m unittest -v` as the complete "
        "final verification set and perform the whole-branch review.\n",
        encoding="utf-8",
    )
    for path in (*specs, *plans):
        path.chmod(0o400)
    return specs, plans


def _runner_argv(
    provider: str,
    runner: Path,
    command: str,
    *,
    workspace: Path | None = None,
    specs: Sequence[Path] = (),
    plans: Sequence[Path] = (),
    run_id: str | None = None,
) -> list[str]:
    if provider not in {"codex", "claude"}:
        raise CanaryError("interruption_scenario_invalid")
    argv = [str(runner), command]
    if command == "run":
        for spec in specs:
            argv.extend(("--spec", str(spec)))
        for plan in plans:
            argv.extend(("--plan", str(plan)))
        if workspace is None:
            raise CanaryError("interruption_scenario_invalid")
        argv.extend(("--workspace", str(workspace)))
        if provider == "codex":
            argv.extend(("--sandbox", "danger-full-access"))
    elif command == "resume":
        if not isinstance(run_id, str):
            raise CanaryError("interruption_scenario_invalid")
        argv.extend(("--run-id", run_id))
    else:
        raise CanaryError("interruption_scenario_invalid")
    return argv


def _process_table() -> list[tuple[int, int, int, str]]:
    result = subprocess.run(
        ["ps", "-axo", "pid=,ppid=,pgid=,stat="],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise CanaryError("process_observation_failed")
    rows: list[tuple[int, int, int, str]] = []
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) < 4:
            continue
        try:
            rows.append(
                (int(fields[0]), int(fields[1]), int(fields[2]), fields[3])
            )
        except ValueError:
            continue
    return rows


def _descendant_groups(controller_pid: int) -> set[int]:
    rows = _process_table()
    children: dict[int, list[int]] = {}
    pgids: dict[int, int] = {}
    for pid, parent, pgid, _status in rows:
        children.setdefault(parent, []).append(pid)
        pgids[pid] = pgid
    pending = list(children.get(controller_pid, []))
    descendants: set[int] = set()
    while pending:
        pid = pending.pop()
        if pid in descendants:
            continue
        descendants.add(pid)
        pending.extend(children.get(pid, []))
    return {
        pgids[pid]
        for pid in descendants
        if pgids.get(pid, 0) > 0 and pgids[pid] != controller_pid
    }


def _process_group_quiescent(pgid: int) -> bool:
    return not any(
        row_pgid == pgid and not status.startswith("Z")
        for _pid, _parent, row_pgid, status in _process_table()
    )


def _cleanup_process_groups(pgids: set[int]) -> None:
    for pgid in sorted(pgids):
        if _process_group_quiescent(pgid):
            continue
        try:
            os.killpg(pgid, signal.SIGTERM)
        except ProcessLookupError:
            continue
    deadline = time.monotonic() + TERM_GRACE_SECONDS
    while time.monotonic() < deadline and any(
        not _process_group_quiescent(pgid) for pgid in pgids
    ):
        time.sleep(0.05)
    for pgid in sorted(pgids):
        if _process_group_quiescent(pgid):
            continue
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def _load_latest_run(
    home: Path, provider: str
) -> tuple[Path, dict[str, Any]] | None:
    state_home = home / f".{provider}" / "plan-runner"
    candidates = sorted(
        state_home.glob("*/state.json"),
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    )
    for path in candidates:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            return path.parent, value
    return None


def _interruption_boundary(
    home: Path,
    provider: str,
    controller: subprocess.Popen[str],
    observed_groups: set[int],
) -> tuple[Path, dict[str, Any], Path, int]:
    deadline = time.monotonic() + INTERRUPTION_BOUNDARY_DEADLINE_SECONDS
    while time.monotonic() < deadline:
        if controller.poll() is not None:
            raise CanaryError("interruption_boundary_not_reached")
        loaded = _load_latest_run(home, provider)
        if loaded is None:
            time.sleep(0.1)
            continue
        run_root, state = loaded
        repository = state.get("repository")
        plans = state.get("plans")
        sessions = state.get("sessions")
        attempts = state.get("attempts")
        if (
            not isinstance(repository, Mapping)
            or not isinstance(plans, list)
            or len(plans) != 2
            or not isinstance(sessions, list)
            or not isinstance(attempts, list)
            or state.get("current_plan_index") != 1
            or not isinstance(plans[0], Mapping)
            or plans[0].get("status") != "implemented"
        ):
            time.sleep(0.1)
            continue
        worktree_value = repository.get("worktree")
        if not isinstance(worktree_value, str):
            time.sleep(0.1)
            continue
        worktree = Path(worktree_value)
        if not worktree.is_dir():
            time.sleep(0.1)
            continue
        healthy = [
            session
            for session in sessions
            if isinstance(session, Mapping)
            and session.get("mode") == "implementation"
            and session.get("plan_index") == 1
            and session.get("health") == "healthy"
            and isinstance(session.get("session_id"), str)
        ]
        current_attempts = [
            attempt
            for attempt in attempts
            if isinstance(attempt, Mapping)
            and attempt.get("mode") == "implementation"
            and attempt.get("plan_index") == 1
            and attempt.get("completed") is False
        ]
        current_pgid = (
            current_attempts[0].get("provider_pgid")
            if len(current_attempts) == 1
            else None
        )
        if not isinstance(current_pgid, int) or current_pgid <= 0:
            time.sleep(0.1)
            continue
        marker_committed = (
            subprocess.run(
                ["git", "cat-file", "-e", "HEAD:resume-marker.txt"],
                cwd=worktree,
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
            ).returncode
            == 0
        )
        dirty = _git(worktree, "status", "--porcelain=v1")
        if (
            healthy
            and not _process_group_quiescent(current_pgid)
            and marker_committed
            and "dirty-checkpoint.txt" in dirty
        ):
            observed_groups.clear()
            observed_groups.add(current_pgid)
            return run_root, state, worktree, current_pgid
        time.sleep(0.1)
    raise CanaryError("interruption_boundary_deadline")


def _interrupt_controller(
    controller: subprocess.Popen[str], provider_groups: set[int]
) -> CommandResult:
    os.kill(controller.pid, signal.SIGINT)
    try:
        stdout, stderr = controller.communicate(timeout=60)
        timed_out = False
    except subprocess.TimeoutExpired:
        timed_out = True
        stdout, stderr = _terminate_and_reap(controller)
    quiescent = all(_process_group_quiescent(pgid) for pgid in provider_groups)
    if not quiescent:
        _cleanup_process_groups(provider_groups)
    result = CommandResult(
        controller.returncode,
        (stdout or "")[-STREAM_LIMIT:],
        (stderr or "")[-STREAM_LIMIT:],
        timed_out,
    )
    if not quiescent:
        raise CanaryError("provider_process_group_not_quiescent")
    return result


def _run_interrupted_once(
    *,
    provider: str,
    root: Path,
    runner: Path,
    environment: Mapping[str, str],
    drift: bool,
) -> dict[str, object]:
    workspace = root / "source"
    _create_repository(workspace)
    specs, plans = _write_interruption_documents(root)
    controller = subprocess.Popen(
        _runner_argv(
            provider,
            runner,
            "run",
            workspace=workspace,
            specs=specs,
            plans=plans,
        ),
        cwd=str(root),
        env=dict(environment),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        shell=False,
        start_new_session=True,
    )
    provider_groups: set[int] = set()
    try:
        run_root, _state_before, worktree, current_provider_pgid = (
            _interruption_boundary(
                Path(environment["HOME"]),
                provider,
                controller,
                provider_groups,
            )
        )
        if _process_group_quiescent(current_provider_pgid):
            raise CanaryError("provider_process_group_not_live")
        interruption = _interrupt_controller(controller, provider_groups)
    except BaseException:
        if controller.poll() is None:
            _terminate_and_reap(controller)
        _cleanup_process_groups(provider_groups)
        raise
    loaded = _load_latest_run(Path(environment["HOME"]), provider)
    if loaded is None or loaded[0] != run_root:
        raise CanaryError("interrupted_state_missing")
    _run_root, interrupted_state = loaded
    failure = interrupted_state.get("failure")
    checkpoint = (
        failure.get("partial_worktree")
        if isinstance(failure, Mapping)
        else None
    )
    if (
        interruption.timed_out
        or interruption.returncode != 2
        or interrupted_state.get("status") != "resumable"
        or not isinstance(checkpoint, Mapping)
        or checkpoint.get("clean") is not False
    ):
        raise CanaryError("interrupted_run_not_resumable")
    sessions_before = interrupted_state.get("sessions")
    plans_before = interrupted_state.get("plans")
    attempts_before = interrupted_state.get("attempts")
    if (
        not isinstance(sessions_before, list)
        or not isinstance(plans_before, list)
        or not isinstance(attempts_before, list)
        or len(plans_before) != 2
        or not isinstance(plans_before[0], Mapping)
    ):
        raise CanaryError("interrupted_state_invalid")
    recorded = [
        session
        for session in sessions_before
        if isinstance(session, Mapping)
        and session.get("mode") == "implementation"
        and session.get("plan_index") == 1
        and session.get("health") == "healthy"
        and isinstance(session.get("session_id"), str)
    ]
    if not recorded:
        raise CanaryError("recorded_healthy_session_missing")
    first_handoff = plans_before[0].get("handoff_digest")
    first_sessions_before = sum(
        1
        for session in sessions_before
        if isinstance(session, Mapping)
        and session.get("mode") == "implementation"
        and session.get("plan_index") == 0
    )
    observed_before = _production_worktree_observation(
        provider, interrupted_state
    )
    expected_checkpoint = {
        **observed_before,
    }
    if provider == "claude":
        expected_checkpoint = {
            "version": 1,
            "plan_index": interrupted_state.get("current_plan_index"),
            **expected_checkpoint,
        }
    if checkpoint != expected_checkpoint:
        raise CanaryError("dirty_checkpoint_changed")
    if drift:
        (worktree / "drift.txt").write_text(
            "drift after sealed checkpoint\n", encoding="utf-8"
        )
    observed_at_resume = _production_worktree_observation(
        provider, interrupted_state
    )
    resume = run_bounded(
        _runner_argv(
            provider,
            runner,
            "resume",
            run_id=interrupted_state["run_id"],
        ),
        cwd=root,
        timeout=RUNNER_DEADLINE_SECONDS,
        env=environment,
    )
    loaded_after = _load_latest_run(Path(environment["HOME"]), provider)
    if loaded_after is None or loaded_after[0] != run_root:
        raise CanaryError("resumed_state_missing")
    _run_root, final_state = loaded_after
    attempts_after = final_state.get("attempts")
    sessions_after = final_state.get("sessions")
    if not isinstance(attempts_after, list) or not isinstance(sessions_after, list):
        raise CanaryError("resumed_state_invalid")
    if drift:
        return {
            "drift_rejected": (
                resume.returncode in {65, 70}
                and observed_at_resume != observed_before
                and len(attempts_before) == len(attempts_after)
            ),
            "drift_reason_code": "dirty_checkpoint_drift",
            "provider_launch_count_before_drift": len(attempts_before),
            "provider_launch_count_after_drift": len(attempts_after),
        }
    if resume.returncode != 0 or final_state.get("status") != "ready_for_integration":
        raise CanaryError("interruption_resume_failed")
    final_recorded = [
        session
        for session in sessions_after
        if isinstance(session, Mapping)
        and session.get("mode") == "implementation"
        and session.get("plan_index") == 1
        and session.get("health") == "healthy"
        and session.get("session_id") == recorded[-1]["session_id"]
    ]
    resumed_attempts = attempts_after[len(attempts_before) :]
    resumed_recorded_session = (
        bool(resumed_attempts)
        and isinstance(resumed_attempts[0], Mapping)
        and resumed_attempts[0].get("session_action") == "resume_root"
    )
    ownership = _ownership_evidence_from_run(
        state=final_state,
        run_root=run_root,
        worktree=worktree,
        plans=plans,
        project_resumed_sessions=True,
    )
    return {
        "sigint_sent": True,
        "provider_process_group_quiescent": True,
        "interrupted_status": interrupted_state["status"],
        "interrupted_checkpoint": dict(checkpoint),
        "resume_checkpoint": (
            dict(checkpoint)
            if observed_at_resume == observed_before
            and observed_before.get("clean") is False
            else None
        ),
        "recorded_session": dict(recorded[-1]),
        "resume_session_id": (
            final_recorded[-1]["session_id"]
            if final_recorded and resumed_recorded_session
            else None
        ),
        "completed_first_handoff_before": first_handoff,
        "completed_first_handoff_after": (
            final_state["plans"][0].get("handoff_digest")
            if isinstance(final_state.get("plans"), list)
            and isinstance(final_state["plans"][0], Mapping)
            else None
        ),
        "first_plan_session_count_before": first_sessions_before,
        "first_plan_session_count_after": sum(
            1
            for session in sessions_after
            if isinstance(session, Mapping)
            and session.get("mode") == "implementation"
            and session.get("plan_index") == 0
        ),
        "final_ownership": ownership,
    }


def _probe_interruption_live(provider: str) -> dict[str, object]:
    started = time.monotonic()
    with tempfile.TemporaryDirectory(
        prefix=f"{provider}-interruption-canary-"
    ) as raw:
        root = Path(raw).resolve(strict=True)
        primary = root / "resume"
        drift = root / "drift"
        primary.mkdir()
        drift.mkdir()
        primary_home = primary / "operator-home"
        drift_home = drift / "operator-home"
        primary_home.mkdir(mode=0o700)
        drift_home.mkdir(mode=0o700)
        version: str | None = None
        try:
            primary_env = _runner_environment(provider, primary_home)
            drift_env = _runner_environment(provider, drift_home)
            version, unavailable = _provider_version(
                provider, primary, primary_env
            )
            if unavailable:
                raise CanaryError(unavailable)
            if (
                provider == "claude"
                and not claude_explicit_auth_present(primary_env)
            ):
                raise CanaryError("provider_auth_blocked")
            runner = (
                REPO_ROOT
                / f"skills/kws-{provider}-plan-runner/scripts/runner"
            )
            evidence = _run_interrupted_once(
                provider=provider,
                root=primary,
                runner=runner,
                environment=primary_env,
                drift=False,
            )
            evidence.update(
                _run_interrupted_once(
                    provider=provider,
                    root=drift,
                    runner=runner,
                    environment=drift_env,
                    drift=True,
                )
            )
            valid, reason, head = validate_interruption_resume_scenario(
                evidence
            )
            if not valid or head is None:
                raise CanaryError(reason or "interruption_evidence_invalid")
            return normalized_result(
                provider=provider,
                mode="interruption",
                status="passed",
                provider_version=version,
                session_action="sigint_then_recorded_resume",
                final_head=head,
                elapsed=time.monotonic() - started,
            )
        except (CanaryError, OSError, ValueError, KeyError, json.JSONDecodeError) as error:
            reason = (
                error.reason_code
                if isinstance(error, CanaryError)
                else "interruption_probe_failed"
            )
            status = "blocked" if reason in BLOCKED_REASON_CODES else "failed"
            return normalized_result(
                provider=provider,
                mode="interruption",
                status=status,
                provider_version=version,
                session_action="not_completed",
                final_head=None,
                elapsed=time.monotonic() - started,
                reason_code=reason,
            )


def probe_ownership(provider: str) -> dict[str, object]:
    return probe_runner(provider, scenario_mode="ownership")


def probe_interruption(provider: str) -> dict[str, object]:
    return _probe_interruption_live(provider)


def _parser() -> argparse.ArgumentParser:
    parser = ContractArgumentParser(prog="plan-runner-live-canary")
    parser.add_argument(
        "--provider", choices=("codex", "claude", "all"), required=True
    )
    parser.add_argument(
        "--mode",
        choices=("session", "runner", "ownership", "interruption", "all"),
        required=True,
    )
    return parser


def _requested(value: str, choices: tuple[str, str]) -> tuple[str, ...]:
    return choices if value == "all" else (value,)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        arguments = _parser().parse_args(argv)
    except InvocationError:
        print(
            json.dumps(
                normalized_result(
                    provider="invalid",
                    mode="invalid",
                    status="failed",
                    provider_version=None,
                    session_action="not_started",
                    final_head=None,
                    elapsed=0,
                    reason_code="invalid_invocation",
                ),
                sort_keys=True,
            )
        )
        return 64
    try:
        require_runtime()
    except CanaryError as error:
        for provider in _requested(arguments.provider, ("codex", "claude")):
            for mode in _requested(arguments.mode, ("session", "runner")):
                print(
                    json.dumps(
                        normalized_result(
                            provider=provider,
                            mode=mode,
                            status="blocked",
                            provider_version=None,
                            session_action="not_started",
                            final_head=None,
                            elapsed=0,
                            reason_code=error.reason_code,
                        ),
                        sort_keys=True,
                    )
                )
        return 3
    results: list[Mapping[str, object]] = []
    probes = {
        "session": probe_session,
        "runner": probe_runner,
        "ownership": probe_ownership,
        "interruption": probe_interruption,
    }
    try:
        for provider in _requested(arguments.provider, ("codex", "claude")):
            for mode in _requested(arguments.mode, ("session", "runner")):
                result = probes[mode](provider)
                results.append(result)
                print(json.dumps(result, sort_keys=True))
    except _SignalInterrupt as error:
        return 128 + error.signum
    if any(result["status"] == "failed" for result in results):
        return 4
    if any(result["status"] == "blocked" for result in results):
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
