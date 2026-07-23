from __future__ import annotations

import json
import math
import os
import re
import selectors
import subprocess
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .git_ops import sanitized_child_env
from .helper import HelperDescriptor
from .process import (
    _anchored_group,
    _bounded_direct_cleanup,
    _finish_group,
    open_executable,
)
from .recovery import ActivityLease


MAX_JSONL_LINE_BYTES = 65_536
MAX_RETAINED_BYTES = 1_048_576
_MAX_USAGE_FIELDS = 32
_MAX_USAGE_VALUE = 2**63 - 1
_SECRET = re.compile(
    r"(?i)\b((?:[A-Z][A-Z0-9_]*(?:TOKEN|SECRET|API_KEY)|password)\s*=)\s*[^\s]+"
)
_AUTH_CODES = frozenset(
    {
        "authentication_failed",
        "billing_error",
        "invalid_api_key",
        "oauth_org_not_allowed",
        "unauthorized",
    }
)
_USAGE_CODES = frozenset(
    {
        "credits_exhausted",
        "insufficient_quota",
        "quota_exceeded",
        "rate_limit",
        "usage_limit",
    }
)
_UNAVAILABLE_CODES = frozenset(
    {"overloaded", "provider_unavailable", "service_unavailable", "unavailable"}
)
_RESUME_CODES = frozenset(
    {"invalid_session", "session_not_found", "thread_not_found"}
)
_CONTEXT_CODES = frozenset(
    {"context_overflow", "context_window_exceeded", "max_context_length_exceeded"}
)
_TRANSPORT_CODES = frozenset(
    {"connection_error", "stream_disconnected", "transport_error"}
)
_RECOGNIZED_ERROR_CODES = (
    _AUTH_CODES
    | _USAGE_CODES
    | _UNAVAILABLE_CODES
    | _RESUME_CODES
    | _CONTEXT_CODES
    | _TRANSPORT_CODES
)
_RESULT_STATUSES = frozenset({"implemented", "blocked", "failed"})


@dataclass(frozen=True)
class ProviderRequest:
    worktree: Path
    git_common_dir: Path
    prompt: str
    output_schema: Path
    output_path: Path
    sandbox: str
    model: str | None = None
    session_id: str | None = None

    def __post_init__(self) -> None:
        for field in ("worktree", "git_common_dir", "output_schema", "output_path"):
            value = Path(getattr(self, field))
            if not value.is_absolute():
                raise ValueError(f"{field} must be an absolute path")
            object.__setattr__(self, field, value)
        for field in ("prompt", "sandbox"):
            value = getattr(self, field)
            if not isinstance(value, str) or not value or "\0" in value:
                raise ValueError(f"{field} must be a non-empty NUL-free string")
        if self.model is not None and (
            not isinstance(self.model, str) or not self.model or "\0" in self.model
        ):
            raise ValueError("model must be a non-empty NUL-free string")
        if self.session_id is not None and not isinstance(self.session_id, str):
            raise ValueError("session_id must be a string")


@dataclass(frozen=True)
class ProviderOutcome:
    kind: str
    return_code: int | None
    session_id: str | None
    result: Mapping[str, Any] | None
    provider_code: str | None
    usage: Mapping[str, int | float]
    activity_keys: tuple[str, ...]
    stderr_tail: str


class CodexAdapter:
    def __init__(
        self,
        *,
        source_env: Mapping[str, str] | None = None,
        provider_auth_prefixes: Sequence[str] = ("OPENAI_", "CODEX_"),
        remotes: Sequence[str] = (),
        run_id: str = "codex-plan-runner",
        helper: HelperDescriptor | None = None,
        poll_seconds: float = 0.05,
    ) -> None:
        if (
            not isinstance(poll_seconds, (int, float))
            or isinstance(poll_seconds, bool)
            or not math.isfinite(poll_seconds)
            or poll_seconds <= 0
        ):
            raise ValueError("poll_seconds must be finite and positive")
        self._source_env = dict(os.environ if source_env is None else source_env)
        self._provider_auth_prefixes = tuple(provider_auth_prefixes)
        self._remotes = tuple(remotes)
        self._run_id = run_id
        self._helper = helper
        self._poll_seconds = float(poll_seconds)

    def build_argv(self, request: ProviderRequest) -> list[str]:
        if request.session_id is not None:
            _require_uuid(request.session_id)
        argv = [
            "codex",
            "exec",
            "--ignore-user-config",
            "--json",
            "--output-schema",
            str(request.output_schema),
            "--output-last-message",
            str(request.output_path),
            "--cd",
            str(request.worktree),
            "--sandbox",
            request.sandbox,
            "--add-dir",
            str(request.git_common_dir),
        ]
        if request.model is not None:
            argv.extend(["--model", request.model])
        if request.session_id is None:
            argv.append("-")
        else:
            argv.extend(["resume", request.session_id, "-"])
        return argv

    def launch(
        self, request: ProviderRequest, lease: ActivityLease
    ) -> ProviderOutcome:
        argv = self.build_argv(request)
        self._validate_launch_paths(request)
        env = sanitized_child_env(
            self._source_env,
            provider_auth_prefixes=self._provider_auth_prefixes,
            remotes=self._remotes,
            run_id=self._run_id,
        )
        self._add_helper_env(env)
        request.output_path.unlink(missing_ok=True)

        activity_keys: list[str] = []
        usage: dict[str, int | float] = {}
        session_id: str | None = None
        provider_code: str | None = None
        malformed = False
        stalled = False
        stderr_tail = bytearray()
        stdout_buffer = bytearray()
        return_code: int | None = None

        try:
            with open_executable("codex", cwd=request.worktree, env=env) as opened:
                opened.revalidate()
                process = subprocess.Popen(
                    argv,
                    executable=str(opened.path),
                    cwd=str(request.worktree),
                    env=env,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    shell=False,
                    start_new_session=True,
                )
                pgid = process.pid
                try:
                    opened.revalidate()
                    try:
                        if os.getpgid(process.pid) != pgid:
                            raise RuntimeError(
                                "provider did not create an isolated process group"
                            )
                    except ProcessLookupError:
                        pass
                    assert (
                        process.stdin is not None
                        and process.stdout is not None
                        and process.stderr is not None
                    )
                    try:
                        process.stdin.write(request.prompt.encode("utf-8"))
                        process.stdin.close()
                    except BrokenPipeError:
                        process.stdin.close()

                    selector = selectors.DefaultSelector()
                    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
                    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
                    leader_finished = False
                    try:
                        while True:
                            if (
                                not leader_finished
                                and not malformed
                                and lease.expired(time.monotonic())
                            ):
                                stalled = True
                                return_code, _forced = _finish_group(
                                    process, pgid, terminate_leader=True
                                )
                                leader_finished = True

                            if selector.get_map():
                                ready = selector.select(self._poll_seconds)
                                for key, _events in ready:
                                    stream = key.fileobj
                                    chunk = os.read(stream.fileno(), 65_536)
                                    if not chunk:
                                        selector.unregister(stream)
                                        continue
                                    if key.data == "stderr":
                                        _append_tail(
                                            stderr_tail, chunk, MAX_RETAINED_BYTES
                                        )
                                        continue
                                    stdout_buffer.extend(chunk)
                                    (
                                        malformed,
                                        session_id,
                                        provider_code,
                                    ) = self._consume_stdout(
                                        stdout_buffer,
                                        malformed=malformed,
                                        session_id=session_id,
                                        provider_code=provider_code,
                                        usage=usage,
                                        activity_keys=activity_keys,
                                        lease=lease,
                                    )
                            elif not leader_finished:
                                time.sleep(self._poll_seconds)

                            if malformed and not leader_finished:
                                return_code, _forced = _finish_group(
                                    process, pgid, terminate_leader=True
                                )
                                leader_finished = True
                            if not leader_finished:
                                leader_exited, _descendants = _anchored_group(
                                    process,
                                    pgid,
                                    observation_timeout=max(
                                        0.1, min(0.25, self._poll_seconds)
                                    ),
                                )
                                if leader_exited:
                                    return_code, _forced = _finish_group(
                                        process, pgid, terminate_leader=False
                                    )
                                    leader_finished = True
                            if leader_finished and not selector.get_map():
                                break
                    finally:
                        selector.close()
                finally:
                    if process.returncode is None:
                        _bounded_direct_cleanup(process, pgid)
                    if process.stdin is not None and not process.stdin.closed:
                        process.stdin.close()
                    if process.stdout is not None:
                        process.stdout.close()
                    if process.stderr is not None:
                        process.stderr.close()
        except (OSError, RuntimeError, ValueError):
            return ProviderOutcome(
                kind="transport_failed",
                return_code=None,
                session_id=session_id or request.session_id,
                result=None,
                provider_code="controller_transport_failed",
                usage=dict(usage),
                activity_keys=tuple(activity_keys),
                stderr_tail=_scrub(stderr_tail),
            )

        if stdout_buffer:
            malformed = True
        stderr = _scrub(stderr_tail)
        if stalled:
            return ProviderOutcome(
                "stalled",
                None,
                session_id or request.session_id,
                None,
                "stall_expired",
                dict(usage),
                tuple(activity_keys),
                stderr,
            )
        if malformed:
            return ProviderOutcome(
                "failed",
                return_code,
                session_id or request.session_id,
                None,
                "controller_transport_failed",
                dict(usage),
                tuple(activity_keys),
                stderr,
            )

        classified = _classified_provider_outcome(provider_code, request.session_id)
        if classified is not None:
            kind, normalized_code = classified
            return ProviderOutcome(
                kind,
                return_code,
                session_id or request.session_id,
                None,
                normalized_code,
                dict(usage),
                tuple(activity_keys),
                stderr,
            )
        if return_code != 0:
            return ProviderOutcome(
                "transport_failed",
                return_code,
                session_id or request.session_id,
                None,
                "controller_transport_failed",
                dict(usage),
                tuple(activity_keys),
                stderr,
            )
        if session_id is None or (
            request.session_id is not None and session_id != request.session_id
        ):
            return ProviderOutcome(
                "failed",
                return_code,
                session_id,
                None,
                "controller_transport_failed",
                dict(usage),
                tuple(activity_keys),
                stderr,
            )
        result = self._read_result(request.output_path)
        if result is None:
            return ProviderOutcome(
                "failed",
                return_code,
                session_id,
                None,
                "controller_transport_failed",
                dict(usage),
                tuple(activity_keys),
                stderr,
            )
        return ProviderOutcome(
            str(result["status"]),
            return_code,
            session_id,
            result,
            None,
            dict(usage),
            tuple(activity_keys),
            stderr,
        )

    def _validate_launch_paths(self, request: ProviderRequest) -> None:
        if not request.worktree.is_dir() or not request.git_common_dir.is_dir():
            raise ValueError("provider directories must exist")
        if (
            not request.output_schema.is_file()
            or request.output_schema.is_symlink()
            or request.output_path.is_symlink()
            or not request.output_path.parent.is_dir()
        ):
            raise ValueError("provider output paths are unsafe")

    def _add_helper_env(self, env: dict[str, str]) -> None:
        if self._helper is None:
            return
        descriptor = self._helper
        env["KWS_PLAN_RUNNER_HELPER_PROTOCOL_VERSION"] = str(
            descriptor.protocol_version
        )
        env["KWS_PLAN_RUNNER_HELPER_SOCKET"] = str(descriptor.socket_path)
        env["KWS_PLAN_RUNNER_HELPER_NONCE"] = descriptor.nonce
        env["KWS_PLAN_RUNNER_HELPER_CLIENT_ARGV"] = json.dumps(
            descriptor.client_argv, separators=(",", ":")
        )

    def _consume_stdout(
        self,
        buffer: bytearray,
        *,
        malformed: bool,
        session_id: str | None,
        provider_code: str | None,
        usage: dict[str, int | float],
        activity_keys: list[str],
        lease: ActivityLease,
    ) -> tuple[bool, str | None, str | None]:
        while b"\n" in buffer:
            raw, remainder = buffer.split(b"\n", 1)
            buffer[:] = remainder
            if len(raw) > MAX_JSONL_LINE_BYTES or not raw:
                return True, session_id, provider_code
            try:
                event = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError):
                return True, session_id, provider_code
            if not isinstance(event, Mapping) or not isinstance(
                event.get("type"), str
            ):
                return True, session_id, provider_code
            event_type = event["type"]
            if event_type == "thread.started":
                candidate = event.get("thread_id")
                try:
                    candidate = _require_uuid(candidate)
                except ValueError:
                    return True, session_id, provider_code
                if session_id is not None and session_id != candidate:
                    return True, session_id, provider_code
                session_id = candidate
            elif event_type in {"turn.started", "turn.completed"}:
                turn_id = event.get("turn_id")
                if not isinstance(turn_id, str) or not turn_id:
                    return True, session_id, provider_code
                key = f"{event_type}:{turn_id}"
                if lease.observe_provider_event(
                    "lifecycle_advanced", key, time.monotonic()
                ):
                    activity_keys.append(f"lifecycle_advanced:{key}")
                if event_type == "turn.completed":
                    _merge_usage(usage, event.get("usage"))
            elif event_type in {"item.started", "item.completed"}:
                item = event.get("item")
                item_id = item.get("id") if isinstance(item, Mapping) else None
                if not isinstance(item_id, str) or not item_id:
                    return True, session_id, provider_code
                kind = (
                    "tool_started"
                    if event_type == "item.started"
                    else "tool_finished"
                )
                if lease.observe_provider_event(kind, item_id, time.monotonic()):
                    activity_keys.append(f"{kind}:{item_id}")
            elif event_type == "error":
                error = event.get("error")
                code = error.get("code") if isinstance(error, Mapping) else None
                if isinstance(code, str) and code:
                    if (
                        provider_code is None
                        or provider_code not in _RECOGNIZED_ERROR_CODES
                    ):
                        provider_code = code
        if len(buffer) > MAX_JSONL_LINE_BYTES:
            malformed = True
        return malformed, session_id, provider_code

    @staticmethod
    def _read_result(output_path: Path) -> dict[str, Any] | None:
        try:
            metadata = output_path.lstat()
            if (
                output_path.is_symlink()
                or not output_path.is_file()
                or metadata.st_size > MAX_RETAINED_BYTES
            ):
                return None
            value = json.loads(output_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        if (
            not isinstance(value, dict)
            or value.get("status") not in _RESULT_STATUSES
        ):
            return None
        return value


def _require_uuid(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("session ID must be a UUID")
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError) as error:
        raise ValueError("session ID must be a UUID") from error
    canonical = str(parsed)
    if canonical != value:
        raise ValueError("session ID must be a canonical UUID")
    return canonical


def _append_tail(target: bytearray, chunk: bytes, limit: int) -> None:
    target.extend(chunk)
    if len(target) > limit:
        del target[: len(target) - limit]


def _scrub(value: bytearray) -> str:
    decoded = bytes(value).decode("utf-8", "replace")
    scrubbed = _SECRET.sub(r"\1[REDACTED]", decoded).encode("utf-8")
    return scrubbed[-MAX_RETAINED_BYTES:].decode("utf-8", "replace")


def _merge_usage(target: dict[str, int | float], value: object) -> None:
    if not isinstance(value, Mapping):
        return
    for key in sorted(value):
        if len(target) >= _MAX_USAGE_FIELDS:
            break
        counter = value[key]
        if (
            not isinstance(key, str)
            or not key
            or len(key) > 64
            or not isinstance(counter, (int, float))
            or isinstance(counter, bool)
            or not math.isfinite(counter)
            or counter < 0
        ):
            continue
        target[key] = min(counter, _MAX_USAGE_VALUE)


def _classified_provider_outcome(
    code: str | None, requested_session_id: str | None
) -> tuple[str, str] | None:
    if code in _AUTH_CODES:
        return "blocked", "provider_auth_blocked"
    if code in _USAGE_CODES:
        return "blocked", "provider_usage_blocked"
    if code in _UNAVAILABLE_CODES:
        return "blocked", "provider_unavailable"
    if code in _RESUME_CODES and requested_session_id is not None:
        return "resume_failed", "session_resume_failed"
    if code in _CONTEXT_CODES:
        return "context_overflow", "session_invalid"
    if code in _TRANSPORT_CODES:
        return "transport_failed", "controller_transport_failed"
    return None
