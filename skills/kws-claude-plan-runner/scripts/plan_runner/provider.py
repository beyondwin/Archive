from __future__ import annotations

import json
import math
import os
import re
import selectors
import subprocess
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from .git_ops import sanitized_child_env
from .helper import HelperDescriptor
from .process import (
    _anchored_members,
    _bounded_direct_cleanup,
    _finish_anchored_group,
    open_executable,
)
from .recovery import ActivityLease


MAX_JSONL_LINE_BYTES = 65_536
MAX_RETAINED_BYTES = 1_048_576
MAX_RESULT_STRING_BYTES = 4_096
MAX_RAW_STDERR_LINE_BYTES = 65_536
_MAX_USAGE_FIELDS = 32
_MAX_USAGE_VALUE = 2**63 - 1
_RESULT_STATUSES = frozenset(("implemented", "blocked", "failed", "reviewed"))
_AUTH_CODES = frozenset(
    (
        "authentication_failed",
        "billing_error",
        "forbidden",
        "invalid_api_key",
        "oauth_org_not_allowed",
        "unauthorized",
    )
)
_USAGE_CODES = frozenset(
    (
        "credits_exhausted",
        "insufficient_quota",
        "quota_exceeded",
        "rate_limit",
        "rate_limited",
        "usage_limit",
    )
)
_SESSION_CODES = frozenset(
    (
        "conversation_not_found",
        "invalid_session",
        "resume_failed",
        "session_not_found",
    )
)
_CONTEXT_CODES = frozenset(
    (
        "context_overflow",
        "context_window_exceeded",
        "max_context_length_exceeded",
        "prompt_too_long",
    )
)
_COMPACTION_CODES = frozenset(
    ("abnormal_compaction", "compaction_corrupt", "compaction_failed")
)
_SESSION_DAMAGE_CODES = frozenset(
    ("conversation_corrupt", "session_corrupt", "session_damage", "session_damaged")
)
_NESTING_MARKERS = frozenset(
    ("CLAUDECODE", "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_ENTRYPOINT")
)
_UNRELATED_CREDENTIALS = frozenset(
    (
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AZURE_CLIENT_ID",
        "AZURE_CLIENT_SECRET",
        "AZURE_TENANT_ID",
        "CLOUDSDK_AUTH_ACCESS_TOKEN",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "GOOGLE_OAUTH_ACCESS_TOKEN",
    )
)
_CREDENTIAL_PATHS = frozenset(
    (
        "AWS_CONFIG_FILE",
        "AWS_SHARED_CREDENTIALS_FILE",
        "AWS_WEB_IDENTITY_TOKEN_FILE",
        "AZURE_CONFIG_DIR",
        "CLOUDSDK_CONFIG",
        "DOCKER_CONFIG",
        "GCLOUD_CONFIG",
        "GH_CONFIG_DIR",
        "GITHUB_CONFIG_DIR",
        "KUBECONFIG",
        "NETRC",
        "NPM_CONFIG_USERCONFIG",
        "OCI_CONFIG_FILE",
        "PIP_CONFIG_FILE",
        "TF_CLI_CONFIG_FILE",
    )
)
_CREDENTIAL_FAMILIES = (
    "AWS_",
    "AZURE_",
    "BITBUCKET_",
    "CLOUDSDK_",
    "GCLOUD_",
    "GCP_",
    "GITHUB_",
    "GITLAB_",
    "GOOGLE_",
    "OCI_",
)
_CREDENTIAL_HINTS = (
    "ACCESS",
    "ACCOUNT",
    "AUTH",
    "CLIENT",
    "CONFIG",
    "CREDENTIAL",
    "IDENTITY",
    "KEY",
    "PASSWORD",
    "PAT",
    "PROFILE",
    "SECRET",
    "SUBSCRIPTION",
    "TENANT",
    "TOKEN",
)
_SECRET = re.compile(
    r"(?i)\b((?:[A-Z][A-Z0-9_]*(?:TOKEN|SECRET|API_KEY)|password)\s*=)\s*[^\s]+"
)
_NON_CODE = re.compile(r"[^a-z0-9]+")

DENY_TOOLS = (
    "AskUserQuestion",
    "EnterPlanMode",
    "ExitPlanMode",
    "Bash(git push*)",
    "Bash(git merge*)",
    "Bash(gh pr create*)",
    "Bash(glab mr create*)",
    "Bash(rm -rf /*)",
    "Bash(git reset --hard origin*)",
)


def _canonical_uuid(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("session_id must be a canonical UUID")
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError) as error:
        raise ValueError("session_id must be a canonical UUID") from error
    if str(parsed) != value:
        raise ValueError("session_id must be a canonical UUID")
    return value


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        frozen: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("JSON object keys must be strings")
            frozen[key] = _freeze_json(item)
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    if value is None or isinstance(value, (str, bool, int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("JSON numbers must be finite")
        return value
    raise ValueError("value must contain only JSON types")


def _plain_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _plain_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_json(item) for item in value]
    return value


def _inline_schema(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(
            _plain_json(value),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as error:
        raise ValueError("output_schema must be a JSON object") from error


@dataclass(frozen=True)
class ProviderRequest:
    worktree: Path
    prompt: str
    output_schema: Mapping[str, Any]
    session_id: str
    resume: bool = False
    model: str | None = None

    def __post_init__(self) -> None:
        worktree = Path(self.worktree)
        if not worktree.is_absolute():
            raise ValueError("worktree must be an absolute path")
        object.__setattr__(self, "worktree", worktree)
        if (
            not isinstance(self.prompt, str)
            or not self.prompt
            or "\0" in self.prompt
        ):
            raise ValueError("prompt must be a non-empty NUL-free string")
        if not isinstance(self.output_schema, Mapping):
            raise ValueError("output_schema must be a JSON object")
        _inline_schema(self.output_schema)
        object.__setattr__(self, "output_schema", _freeze_json(self.output_schema))
        if self.model is not None and (
            not isinstance(self.model, str)
            or not self.model
            or "\0" in self.model
        ):
            raise ValueError("model must be a non-empty NUL-free string")
        _canonical_uuid(self.session_id)
        if not isinstance(self.resume, bool):
            raise ValueError("resume must be a boolean")


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

    def __post_init__(self) -> None:
        if self.result is not None:
            if not isinstance(self.result, Mapping):
                raise ValueError("provider result must be a mapping")
            object.__setattr__(self, "result", _freeze_json(self.result))
        if not isinstance(self.usage, Mapping):
            raise ValueError("provider usage must be a mapping")
        object.__setattr__(self, "usage", _freeze_json(self.usage))
        object.__setattr__(self, "activity_keys", tuple(self.activity_keys))


class _StreamState:
    def __init__(self) -> None:
        self.session_id: str | None = None
        self.result: Mapping[str, Any] | None = None
        self.provider_codes: list[str] = []
        self.rate_limited = False
        self.usage: dict[str, int | float] = {}
        self.activity_keys: list[str] = []
        self.seen_activity: set[tuple[str, str]] = set()


class ClaudeAdapter:
    def __init__(
        self,
        *,
        source_env: Mapping[str, str] | None = None,
        remotes: Sequence[str] = (),
        run_id: str = "claude-plan-runner",
        helper: HelperDescriptor | None = None,
        poll_seconds: float = 0.05,
    ) -> None:
        if (
            isinstance(poll_seconds, bool)
            or not isinstance(poll_seconds, (int, float))
            or not math.isfinite(poll_seconds)
            or poll_seconds <= 0
        ):
            raise ValueError("poll_seconds must be finite and positive")
        self._source_env = dict(os.environ if source_env is None else source_env)
        self._remotes = tuple(remotes)
        self._run_id = run_id
        self._helper = helper
        self._poll_seconds = float(poll_seconds)

    def build_argv(self, request: ProviderRequest) -> list[str]:
        session_id = _canonical_uuid(request.session_id)
        argv = [
            "claude",
            "-p",
            request.prompt,
            "--output-format",
            "stream-json",
            "--verbose",
            "--json-schema",
            _inline_schema(request.output_schema),
            "--permission-mode",
            "bypassPermissions",
            "--disallowedTools",
            *DENY_TOOLS,
        ]
        if request.resume:
            argv.extend(("--resume", session_id))
        else:
            argv.extend(("--session-id", session_id))
        if request.model is not None:
            argv.extend(("--model", request.model))
        return argv

    def launch(
        self,
        request: ProviderRequest,
        lease: ActivityLease,
        on_session_id: Callable[[str], None] | None = None,
    ) -> ProviderOutcome:
        argv = self.build_argv(request)
        if not request.worktree.is_dir() or request.worktree.is_symlink():
            raise ValueError("provider worktree must be a real directory")
        env = self._child_env()
        state = _StreamState()
        stdout_buffer = bytearray()
        stderr_tail = _RedactedStderrTail()
        malformed = False
        stalled = False
        return_code: int | None = None

        try:
            with open_executable("claude", cwd=request.worktree, env=env) as opened:
                opened.revalidate()
                process = subprocess.Popen(
                    argv,
                    executable=str(opened.path),
                    cwd=str(request.worktree),
                    env=env,
                    stdin=subprocess.DEVNULL,
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
                    assert process.stdout is not None and process.stderr is not None
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
                                return_code, _forced = _finish_anchored_group(
                                    process, pgid, terminate_leader=True
                                )
                                leader_finished = True

                            if selector.get_map():
                                for key, _events in selector.select(self._poll_seconds):
                                    stream = key.fileobj
                                    chunk = os.read(stream.fileno(), 65_536)
                                    if not chunk:
                                        selector.unregister(stream)
                                    elif key.data == "stderr":
                                        stderr_tail.feed(chunk)
                                    else:
                                        stdout_buffer.extend(chunk)
                                        malformed = not self._consume_stdout(
                                            stdout_buffer,
                                            state,
                                            request=request,
                                            lease=lease,
                                            on_session_id=on_session_id,
                                        )
                            elif not leader_finished:
                                time.sleep(self._poll_seconds)

                            if malformed and not leader_finished:
                                try:
                                    return_code, _forced = _finish_anchored_group(
                                        process, pgid, terminate_leader=True
                                    )
                                except RuntimeError:
                                    # A short-lived malformed producer can exit
                                    # between parsing and the anchored signal.
                                    # Preserve the stronger malformed-stream
                                    # classification after a bounded direct reap.
                                    _bounded_direct_cleanup(process, pgid)
                                    return_code = process.poll()
                                leader_finished = True
                            if not leader_finished:
                                leader_exited, _descendants = _anchored_members(
                                    process,
                                    pgid,
                                    timeout=0.25,
                                )
                                if leader_exited:
                                    return_code, _forced = _finish_anchored_group(
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
                    if process.stdout is not None:
                        process.stdout.close()
                    if process.stderr is not None:
                        process.stderr.close()
        except (OSError, RuntimeError, ValueError):
            return self._outcome(
                "transport_failed",
                None,
                state,
                request,
                stderr_tail,
                provider_code="controller_transport_failed",
            )

        if stdout_buffer:
            malformed = True
        if stalled:
            return self._outcome(
                "stalled",
                None,
                state,
                request,
                stderr_tail,
                provider_code="stall_expired",
            )
        if malformed:
            return self._outcome(
                "failed",
                return_code,
                state,
                request,
                stderr_tail,
                provider_code="controller_transport_failed",
            )

        classified = _classify_provider(state, request.resume)
        if classified is not None:
            kind, code = classified
            return self._outcome(
                kind,
                return_code,
                state,
                request,
                stderr_tail,
                provider_code=code,
            )
        if state.session_id is None:
            return self._outcome(
                "session_missing",
                return_code,
                state,
                request,
                stderr_tail,
                provider_code="session_invalid",
            )
        if return_code != 0:
            return self._outcome(
                "interrupted",
                return_code,
                state,
                request,
                stderr_tail,
                provider_code="controller_transport_failed",
            )
        result = state.result
        structured = result.get("structured_output") if result is not None else None
        if (
            result is None
            or result.get("subtype") != "success"
            or not isinstance(structured, Mapping)
            or structured.get("status") not in _RESULT_STATUSES
        ):
            return self._outcome(
                "failed",
                return_code,
                state,
                request,
                stderr_tail,
                provider_code="controller_transport_failed",
            )
        return ProviderOutcome(
            str(structured["status"]),
            return_code,
            state.session_id,
            dict(structured),
            None,
            dict(state.usage),
            tuple(state.activity_keys),
            _scrub(stderr_tail),
        )

    def _child_env(self) -> dict[str, str]:
        env = sanitized_child_env(
            self._source_env,
            provider_auth_prefixes=("ANTHROPIC_",),
            remotes=self._remotes,
            run_id=self._run_id,
        )
        for key in _NESTING_MARKERS | _UNRELATED_CREDENTIALS:
            env.pop(key, None)
        for key in tuple(env):
            if _is_unrelated_credential(key):
                env.pop(key, None)
        if self._helper is not None:
            descriptor = self._helper
            env["KWS_PLAN_RUNNER_HELPER_PROTOCOL_VERSION"] = str(
                descriptor.protocol_version
            )
            env["KWS_PLAN_RUNNER_HELPER_SOCKET"] = str(descriptor.socket_path)
            env["KWS_PLAN_RUNNER_HELPER_NONCE"] = descriptor.nonce
            env["KWS_PLAN_RUNNER_HELPER_CLIENT_ARGV"] = json.dumps(
                descriptor.client_argv, separators=(",", ":")
            )
        return env

    def _consume_stdout(
        self,
        buffer: bytearray,
        state: _StreamState,
        *,
        request: ProviderRequest,
        lease: ActivityLease,
        on_session_id: Callable[[str], None] | None,
    ) -> bool:
        while b"\n" in buffer:
            raw, remainder = buffer.split(b"\n", 1)
            buffer[:] = remainder
            if not raw or len(raw) > MAX_JSONL_LINE_BYTES:
                return False
            try:
                event = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError):
                return False
            if not isinstance(event, Mapping) or not isinstance(
                event.get("type"), str
            ):
                return False
            if not self._consume_event(
                event,
                state,
                request=request,
                lease=lease,
                on_session_id=on_session_id,
            ):
                return False
        return len(buffer) <= MAX_JSONL_LINE_BYTES

    def _consume_event(
        self,
        event: Mapping[str, Any],
        state: _StreamState,
        *,
        request: ProviderRequest,
        lease: ActivityLease,
        on_session_id: Callable[[str], None] | None,
    ) -> bool:
        event_type = event["type"]
        if event_type == "system" and event.get("subtype") == "init":
            try:
                candidate = _canonical_uuid(event.get("session_id"))
            except ValueError:
                return False
            if candidate != request.session_id or (
                state.session_id is not None and state.session_id != candidate
            ):
                return False
            if state.session_id is None:
                if on_session_id is not None:
                    on_session_id(candidate)
                state.session_id = candidate
            self._activity(
                state,
                lease,
                "lifecycle_advanced",
                f"system.init:{candidate}",
            )
        elif event_type == "assistant":
            message = event.get("message")
            if not isinstance(message, Mapping):
                return False
            message_id = message.get("id")
            if not isinstance(message_id, str) or not message_id:
                return False
            self._activity(
                state, lease, "lifecycle_advanced", f"assistant:{message_id}"
            )
            if not self._consume_content(message.get("content"), state, lease):
                return False
        elif event_type == "user":
            message = event.get("message")
            if not isinstance(message, Mapping):
                return False
            if not self._consume_content(message.get("content"), state, lease):
                return False
        elif event_type == "rate_limit_event":
            info = event.get("rate_limit_info")
            if not isinstance(info, Mapping) or not isinstance(
                info.get("status"), str
            ):
                return False
            state.rate_limited |= info["status"] != "allowed"
        elif event_type == "result":
            if state.result is not None:
                return False
            event_session = event.get("session_id")
            if event_session is not None:
                try:
                    if _canonical_uuid(event_session) != request.session_id:
                        return False
                except ValueError:
                    return False
            try:
                state.result = _bounded_mapping(event)
            except ValueError:
                return False
            _merge_usage(state.usage, event.get("usage"))
            api_status = event.get("api_error_status")
            if isinstance(api_status, str) and api_status:
                state.provider_codes.append(_normalize_code(api_status))
        _harvest_explicit_error(event, state.provider_codes)
        return True

    @staticmethod
    def _consume_content(
        content: object,
        state: _StreamState,
        lease: ActivityLease,
    ) -> bool:
        if content is None:
            return True
        if not isinstance(content, list):
            return False
        for block in content:
            if not isinstance(block, Mapping):
                return False
            if block.get("type") == "tool_use":
                tool_id = block.get("id")
                if not isinstance(tool_id, str) or not tool_id:
                    return False
                ClaudeAdapter._activity(state, lease, "tool_started", tool_id)
            elif block.get("type") == "tool_result":
                tool_id = block.get("tool_use_id")
                if not isinstance(tool_id, str) or not tool_id:
                    return False
                ClaudeAdapter._activity(state, lease, "tool_finished", tool_id)
        return True

    @staticmethod
    def _activity(
        state: _StreamState,
        lease: ActivityLease,
        kind: str,
        key: str,
    ) -> None:
        marker = (kind, key)
        if marker in state.seen_activity:
            return
        state.seen_activity.add(marker)
        if lease.observe_provider_event(kind, key, time.monotonic()):
            state.activity_keys.append(f"{kind}:{key}")

    @staticmethod
    def _outcome(
        kind: str,
        return_code: int | None,
        state: _StreamState,
        request: ProviderRequest,
        stderr_tail: _RedactedStderrTail,
        *,
        provider_code: str,
    ) -> ProviderOutcome:
        return ProviderOutcome(
            kind,
            return_code,
            state.session_id or request.session_id,
            None,
            provider_code,
            dict(state.usage),
            tuple(state.activity_keys),
            _scrub(stderr_tail),
        )


def _append_tail(target: bytearray, chunk: bytes, limit: int) -> None:
    target.extend(chunk)
    if len(target) > limit:
        del target[: len(target) - limit]


def _scrub(raw: _RedactedStderrTail) -> str:
    return raw.text()


class _RedactedStderrTail:
    """Bound raw stderr by line, redact complete lines, then bound retained text."""

    def __init__(self) -> None:
        self._pending = bytearray()
        self._tail = bytearray()
        self._discard_line = False
        self._finished = False

    def feed(self, chunk: bytes) -> None:
        if self._finished:
            raise RuntimeError("stderr capture is already finished")
        offset = 0
        while offset < len(chunk):
            newline = chunk.find(b"\n", offset)
            end = len(chunk) if newline < 0 else newline
            segment = chunk[offset:end]
            if not self._discard_line:
                if len(self._pending) + len(segment) > MAX_RAW_STDERR_LINE_BYTES:
                    self._pending.clear()
                    self._discard_line = True
                else:
                    self._pending.extend(segment)
            if newline < 0:
                break
            self._finish_line(newline=True)
            offset = newline + 1

    def text(self) -> str:
        if not self._finished:
            self._finish_line(newline=False)
            self._finished = True
        return bytes(self._tail).decode("utf-8", "ignore")

    def _finish_line(self, *, newline: bool) -> None:
        if self._discard_line:
            sanitized = b"[REDACTED_OVERSIZE_STDERR_LINE]"
        else:
            text = bytes(self._pending).decode("utf-8", "replace")
            sanitized = _SECRET.sub(
                lambda match: match.group(1) + "[REDACTED]", text
            ).encode("utf-8")
        if newline:
            sanitized += b"\n"
        _append_tail(self._tail, sanitized, MAX_RETAINED_BYTES)
        self._pending.clear()
        self._discard_line = False


def _is_unrelated_credential(key: str) -> bool:
    if key.startswith("ANTHROPIC_"):
        return False
    if key in _CREDENTIAL_PATHS:
        return True
    return key.startswith(_CREDENTIAL_FAMILIES) and any(
        hint in key for hint in _CREDENTIAL_HINTS
    )


def _normalize_code(value: str) -> str:
    return _NON_CODE.sub("_", value.strip().lower()).strip("_")[:128]


def _harvest_explicit_error(
    event: Mapping[str, Any], provider_codes: list[str]
) -> None:
    direct = event.get("error_code")
    if isinstance(direct, str) and direct:
        provider_codes.append(_normalize_code(direct))
    error = event.get("error")
    if isinstance(error, Mapping):
        code = error.get("code")
        if isinstance(code, str) and code:
            provider_codes.append(_normalize_code(code))


def _classify_provider(
    state: _StreamState, resume: bool
) -> tuple[str, str] | None:
    codes = set(state.provider_codes)
    if codes & _AUTH_CODES:
        return "blocked", "provider_auth_blocked"
    if state.rate_limited or codes & _USAGE_CODES:
        return "blocked", "provider_usage_blocked"
    if codes & _CONTEXT_CODES:
        return "context_overflow", "session_invalid"
    if codes & _COMPACTION_CODES:
        return "abnormal_compaction", "session_invalid"
    if codes & _SESSION_DAMAGE_CODES:
        return "session_damage", "session_invalid"
    if codes & _SESSION_CODES:
        return (
            ("resume_failed", "session_resume_failed")
            if resume
            else ("session_missing", "session_invalid")
        )
    if codes:
        return "transport_failed", "provider_unavailable"
    return None


def _merge_usage(target: dict[str, int | float], value: object) -> None:
    if not isinstance(value, Mapping):
        return
    for key, amount in value.items():
        if len(target) >= _MAX_USAGE_FIELDS:
            break
        if (
            isinstance(key, str)
            and key
            and isinstance(amount, (int, float))
            and not isinstance(amount, bool)
            and math.isfinite(amount)
            and 0 <= amount <= _MAX_USAGE_VALUE
        ):
            target[key[:128]] = amount


def _bounded_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    bounded = _bounded_json(value, depth=0)
    if not isinstance(bounded, dict):
        raise ValueError("result must be an object")
    return bounded


def _bounded_json(value: Any, *, depth: int) -> Any:
    if depth > 12:
        raise ValueError("result nesting exceeds limit")
    if value is None or isinstance(value, (bool, int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("result number must be finite")
        return value
    if isinstance(value, str):
        encoded = value.encode("utf-8")
        return encoded[:MAX_RESULT_STRING_BYTES].decode("utf-8", "ignore")
    if isinstance(value, Mapping):
        if len(value) > 128:
            raise ValueError("result object exceeds field limit")
        bounded: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("result object keys must be strings")
            bounded[key[:256]] = _bounded_json(item, depth=depth + 1)
        return bounded
    if isinstance(value, list):
        if len(value) > 256:
            raise ValueError("result array exceeds item limit")
        return [_bounded_json(item, depth=depth + 1) for item in value]
    raise ValueError("result contains a non-JSON value")
