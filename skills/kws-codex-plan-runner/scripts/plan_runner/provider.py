from __future__ import annotations

import json
import math
import os
import re
import selectors
import stat
import subprocess
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .git_ops import GitIdentity, sanitized_child_env
from .helper import HelperDescriptor
from .process import (
    _anchored_group,
    _bounded_direct_cleanup,
    _finish_group,
    OpenedExecutable,
    ProcessResult,
    open_executable,
    run_exact,
)
from .recovery import ActivityLease
from .storage import resolve_effective_codex_home


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
_SANDBOX_PERMISSION_CODES = frozenset(
    {
        "helper_denied",
        "sandbox_capability_denied",
        "sandbox_denied",
    }
)
_HOST_PERMISSION_CODES = frozenset(
    {
        "host_permission_denied",
        "keychain_denied",
        "protected_gui_resource_denied",
        "tcc_denied",
    }
)
_HOST_PERMISSION_SYSTEMS = frozenset({"keychain", "protected_gui", "tcc"})
_SANDBOX_CAPABILITIES = frozenset(
    {"helper", "helper_socket", "unix_socket", "workspace_write"}
)
_PERMISSION_ERRNOS = frozenset({"EACCES", "EPERM"})
_CLI_PROBE_DEADLINE_SECONDS = 5
_CLI_PROBE_OUTPUT_LIMIT = 65_536
_CLI_CAPABILITY_CACHE: set[tuple[object, ...]] = set()
_CLI_PARSE_REJECTION_MARKERS = (
    "invalid value",
    "unexpected argument",
    "unknown argument",
    "unknown flag",
    "unknown option",
    "unrecognized argument",
    "unrecognized option",
    "unsupported flag",
    "unsupported option",
)
_REQUIRED_POLICY_ARGUMENTS = frozenset(
    {
        "--add-dir",
        "--ignore-rules",
        "--ignore-user-config",
        "--sandbox",
        "--strict-config",
        "-c",
        'approval_policy="never"',
    }
)
_RECOGNIZED_ERROR_CODES = (
    _AUTH_CODES
    | _USAGE_CODES
    | _UNAVAILABLE_CODES
    | _RESUME_CODES
    | _CONTEXT_CODES
    | _TRANSPORT_CODES
    | frozenset({"host_permission_blocked", "sandbox_capability_blocked"})
)
_RESULT_STATUSES = frozenset({"implemented", "blocked", "failed", "reviewed"})
_SUPPORTED_ENV_AUTH_NAMES = frozenset({"OPENAI_API_KEY"})
_MAX_AUTH_FILE_BYTES = 1_048_576
_MAX_ERROR_MESSAGE_CHARS = 4_096
_AUTH_MESSAGE = re.compile(
    r"(?i)(?:"
    r"\b401\b|"
    r"\bunauthorized\b|"
    r"\bauthentication failed\b|"
    r"\binvalid(?:[ _-]+)api(?:[ _-]+)key\b|"
    r"\btoken expired\b|"
    r"\bnot logged in\b|"
    r"\blogin required\b"
    r")"
)
_REQUIRED_SDD_PATHS = (
    Path("skills/subagent-driven-development/SKILL.md"),
    Path("skills/subagent-driven-development/scripts/sdd-workspace"),
    Path("skills/subagent-driven-development/scripts/task-brief"),
    Path("skills/subagent-driven-development/scripts/review-package"),
    Path("skills/subagent-driven-development/implementer-prompt.md"),
    Path("skills/subagent-driven-development/task-reviewer-prompt.md"),
    Path("skills/subagent-driven-development/re-review-prompt.md"),
    Path("skills/requesting-code-review/code-reviewer.md"),
)


@dataclass(frozen=True)
class ProviderRequest:
    worktree: Path
    git_common_dir: Path
    git_identity: GitIdentity
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


@dataclass(frozen=True)
class StreamSummary:
    session_id: str | None = None
    provider_code: str | None = None
    root_turn_completed: bool = False
    stream_error: str | None = None


class CodexAdapter:
    def __init__(
        self,
        *,
        source_env: Mapping[str, str] | None = None,
        provider_auth_prefixes: Sequence[str] = ("OPENAI_", "CODEX_"),
        remotes: Sequence[str] = (),
        run_id: str = "codex-plan-runner",
        helper: HelperDescriptor | None = None,
        executable: str = "codex",
        poll_seconds: float = 0.05,
        stop_requested: Callable[[], bool] | None = None,
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
        if (
            not isinstance(executable, str)
            or not executable
            or "\0" in executable
        ):
            raise ValueError("executable must be a non-empty NUL-free string")
        self.executable = executable
        self._poll_seconds = float(poll_seconds)
        if stop_requested is not None and not callable(stop_requested):
            raise ValueError("stop_requested must be callable")
        self._stop_requested = stop_requested or (lambda: False)

    def build_argv(self, request: ProviderRequest) -> list[str]:
        if request.session_id is not None:
            _require_uuid(request.session_id)
        argv = self._exec_prefix() + [
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

    def _exec_prefix(self) -> list[str]:
        return [
            self.executable,
            "exec",
            "--ignore-user-config",
            "--ignore-rules",
            "--strict-config",
            "-c",
            'approval_policy="never"',
            "--json",
        ]

    def launch(
        self,
        request: ProviderRequest,
        lease: ActivityLease,
        on_session_id: Callable[[str], None] | None = None,
    ) -> ProviderOutcome:
        argv = self.build_argv(request)
        self._validate_launch_paths(request)
        try:
            codex_home = resolve_effective_codex_home(self._source_env)
        except ValueError:
            code = (
                "provider_capability_blocked"
                if _has_environment_auth(
                    self._source_env, self._provider_auth_prefixes
                )
                else "provider_auth_blocked"
            )
            return _blocked_preflight(code)
        env = sanitized_child_env(
            self._source_env,
            provider_auth_prefixes=self._provider_auth_prefixes,
            remotes=self._remotes,
            run_id=self._run_id,
            git_identity=request.git_identity,
        )
        preflight_code = _capability_preflight(
            codex_home,
            env,
            provider_auth_prefixes=self._provider_auth_prefixes,
        )
        if preflight_code is not None:
            return _blocked_preflight(preflight_code)
        env["CODEX_HOME"] = str(codex_home)
        cli_preflight = self._cli_preflight(request, env)
        if cli_preflight is not None:
            return cli_preflight
        isolated_home = request.output_path.parent / ".codex-child-home"
        isolated_config = isolated_home / ".config"
        _ensure_private_directory(isolated_home)
        _ensure_private_directory(isolated_config)
        env["HOME"] = str(isolated_home)
        env["XDG_CONFIG_HOME"] = str(isolated_config)
        self._add_helper_env(env)
        request.output_path.unlink(missing_ok=True)

        activity_keys: list[str] = []
        usage: dict[str, int | float] = {}
        summary = StreamSummary()
        stalled = False
        controller_stopped = False
        stderr_tail = bytearray()
        stdout_buffer = bytearray()
        return_code: int | None = None

        try:
            with open_executable(
                self.executable, cwd=request.worktree, env=env
            ) as opened:
                cli_failure = _required_cli_capability_failure(
                    opened,
                    cwd=request.worktree,
                    env=env,
                    probe_argv=[
                        *self._exec_prefix(),
                        "--sandbox",
                        request.sandbox,
                        "--add-dir",
                        str(request.git_common_dir),
                        "--help",
                    ],
                )
                if cli_failure is not None:
                    return _cli_preflight_failure(cli_failure)
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
                            if not leader_finished and self._stop_requested():
                                controller_stopped = True
                                return_code, _forced = _finish_group(
                                    process, pgid, terminate_leader=True
                                )
                                leader_finished = True
                            if (
                                not leader_finished
                                and summary.stream_error is None
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
                                    summary = self._consume_stdout(
                                        stdout_buffer,
                                        summary=summary,
                                        usage=usage,
                                        activity_keys=activity_keys,
                                        lease=lease,
                                        on_session_id=on_session_id,
                                    )
                            elif not leader_finished:
                                time.sleep(self._poll_seconds)

                            if (
                                summary.stream_error is not None
                                and not leader_finished
                            ):
                                return_code, _forced = _finish_group(
                                    process, pgid, terminate_leader=True
                                )
                                leader_finished = True
                            if not leader_finished:
                                leader_exited, _descendants = _anchored_group(
                                    process,
                                    pgid,
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
                session_id=summary.session_id or request.session_id,
                result=None,
                provider_code="controller_transport_failed",
                usage=dict(usage),
                activity_keys=tuple(activity_keys),
                stderr_tail=_scrub(stderr_tail),
            )

        if stdout_buffer and summary.stream_error is None:
            summary = StreamSummary(
                session_id=summary.session_id,
                provider_code=summary.provider_code,
                root_turn_completed=summary.root_turn_completed,
                stream_error="provider_stream_malformed",
            )
        stderr = _scrub(stderr_tail)
        if controller_stopped:
            return ProviderOutcome(
                "controller_stopped",
                return_code,
                summary.session_id or request.session_id,
                None,
                "controller_transport_failed",
                dict(usage),
                tuple(activity_keys),
                stderr,
            )
        if summary.stream_error is not None:
            return ProviderOutcome(
                "failed",
                return_code,
                summary.session_id or request.session_id,
                None,
                summary.stream_error,
                dict(usage),
                tuple(activity_keys),
                stderr,
            )
        if stalled:
            return ProviderOutcome(
                "stalled",
                None,
                summary.session_id or request.session_id,
                None,
                "stall_expired",
                dict(usage),
                tuple(activity_keys),
                stderr,
            )

        classified = _classified_provider_outcome(
            summary.provider_code, request.session_id
        )
        if classified is not None:
            kind, normalized_code = classified
            return ProviderOutcome(
                kind,
                return_code,
                summary.session_id or request.session_id,
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
                summary.session_id or request.session_id,
                None,
                "controller_transport_failed",
                dict(usage),
                tuple(activity_keys),
                stderr,
            )
        if summary.session_id is None or (
            request.session_id is not None
            and summary.session_id != request.session_id
        ):
            return ProviderOutcome(
                "failed",
                return_code,
                summary.session_id,
                None,
                "provider_stream_malformed",
                dict(usage),
                tuple(activity_keys),
                stderr,
            )
        if not summary.root_turn_completed:
            return ProviderOutcome(
                "transport_failed",
                return_code,
                summary.session_id,
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
                summary.session_id,
                None,
                "provider_result_invalid",
                dict(usage),
                tuple(activity_keys),
                stderr,
            )
        return ProviderOutcome(
            str(result["status"]),
            return_code,
            summary.session_id,
            result,
            None,
            dict(usage),
            tuple(activity_keys),
            stderr,
        )

    def _cli_preflight(
        self,
        request: ProviderRequest,
        env: Mapping[str, str],
    ) -> ProviderOutcome | None:
        try:
            opened = open_executable(
                self.executable, cwd=request.worktree, env=env
            )
        except (OSError, ValueError):
            return _transport_preflight("provider_unavailable")
        try:
            with opened:
                failure = _required_cli_capability_failure(
                    opened,
                    cwd=request.worktree,
                    env=env,
                    probe_argv=[
                        *self._exec_prefix(),
                        "--sandbox",
                        request.sandbox,
                        "--add-dir",
                        str(request.git_common_dir),
                        "--help",
                    ],
                )
        except (OSError, RuntimeError, ValueError):
            return _transport_preflight("controller_transport_failed")
        return None if failure is None else _cli_preflight_failure(failure)

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
        summary: StreamSummary,
        usage: dict[str, int | float],
        activity_keys: list[str],
        lease: ActivityLease,
        on_session_id: Callable[[str], None] | None = None,
    ) -> StreamSummary:
        if summary.stream_error is not None:
            return summary
        session_id = summary.session_id
        provider_code = summary.provider_code
        root_turn_completed = summary.root_turn_completed
        while b"\n" in buffer:
            raw, remainder = buffer.split(b"\n", 1)
            buffer[:] = remainder
            if len(raw) > MAX_JSONL_LINE_BYTES:
                return StreamSummary(
                    session_id,
                    provider_code,
                    root_turn_completed,
                    "provider_stream_oversized",
                )
            if not raw:
                return StreamSummary(
                    session_id,
                    provider_code,
                    root_turn_completed,
                    "provider_stream_malformed",
                )
            try:
                event = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError):
                return StreamSummary(
                    session_id,
                    provider_code,
                    root_turn_completed,
                    "provider_stream_malformed",
                )
            if not isinstance(event, Mapping) or not isinstance(
                event.get("type"), str
            ):
                return StreamSummary(
                    session_id,
                    provider_code,
                    root_turn_completed,
                    "provider_stream_malformed",
                )
            event_type = event["type"]
            if event_type == "thread.started":
                candidate = event.get("thread_id")
                try:
                    candidate = _require_uuid(candidate)
                except ValueError:
                    return StreamSummary(
                        session_id,
                        provider_code,
                        root_turn_completed,
                        "provider_stream_malformed",
                    )
                if session_id is not None and session_id != candidate:
                    return StreamSummary(
                        session_id,
                        provider_code,
                        root_turn_completed,
                        "provider_stream_malformed",
                    )
                if session_id is None and on_session_id is not None:
                    on_session_id(candidate)
                session_id = candidate
            elif event_type in {"turn.started", "turn.completed"}:
                turn_id = event.get("turn_id")
                if turn_id is not None and (
                    not isinstance(turn_id, str) or not turn_id
                ):
                    return StreamSummary(
                        session_id,
                        provider_code,
                        root_turn_completed,
                        "provider_stream_malformed",
                    )
                key = (
                    f"{event_type}:{turn_id}"
                    if isinstance(turn_id, str)
                    else event_type
                )
                if lease.observe_provider_event(
                    "lifecycle_advanced", key, time.monotonic()
                ):
                    activity_keys.append(f"lifecycle_advanced:{key}")
                if event_type == "turn.completed":
                    root_turn_completed = True
                    _merge_usage(usage, event.get("usage"))
            elif event_type == "turn.failed":
                turn_id = event.get("turn_id")
                if turn_id is not None and (
                    not isinstance(turn_id, str) or not turn_id
                ):
                    return StreamSummary(
                        session_id,
                        provider_code,
                        root_turn_completed,
                        "provider_stream_malformed",
                    )
                key = (
                    f"{event_type}:{turn_id}"
                    if isinstance(turn_id, str)
                    else event_type
                )
                if lease.observe_provider_event(
                    "lifecycle_advanced", key, time.monotonic()
                ):
                    activity_keys.append(f"lifecycle_advanced:{key}")
                code = _event_provider_code(event)
                if code is not None and (
                    provider_code is None
                    or provider_code not in _RECOGNIZED_ERROR_CODES
                ):
                    provider_code = code
            elif event_type in {"item.started", "item.completed"}:
                item = event.get("item")
                item_id = item.get("id") if isinstance(item, Mapping) else None
                if not isinstance(item_id, str) or not item_id:
                    return StreamSummary(
                        session_id,
                        provider_code,
                        root_turn_completed,
                        "provider_stream_malformed",
                    )
                kind = (
                    "tool_started"
                    if event_type == "item.started"
                    else "tool_finished"
                )
                if lease.observe_provider_event(kind, item_id, time.monotonic()):
                    activity_keys.append(f"{kind}:{item_id}")
            elif event_type == "error":
                code = _event_provider_code(event)
                if code is not None and (
                    provider_code is None
                    or provider_code not in _RECOGNIZED_ERROR_CODES
                ):
                    provider_code = code
        stream_error = (
            "provider_stream_oversized"
            if len(buffer) > MAX_JSONL_LINE_BYTES
            else None
        )
        return StreamSummary(
            session_id,
            provider_code,
            root_turn_completed,
            stream_error,
        )

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


def _ensure_private_directory(path: Path) -> None:
    try:
        path.mkdir(mode=0o700, exist_ok=True)
        metadata = path.lstat()
    except OSError as error:
        raise ValueError("isolated provider home is unavailable") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("isolated provider home must be a directory")
    try:
        path.chmod(0o700)
    except OSError as error:
        raise ValueError("isolated provider home permissions are unavailable") from error


def _has_environment_auth(
    environment: Mapping[str, str], prefixes: Sequence[str]
) -> bool:
    allowed_names = {
        name
        for name in _SUPPORTED_ENV_AUTH_NAMES
        if name.startswith(tuple(prefixes))
    }
    return any(
        key in allowed_names
        and isinstance(value, str)
        and bool(value.strip())
        for key, value in environment.items()
    )


def _readable_nonempty_regular(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        return False
    return (
        stat.S_ISREG(metadata.st_mode)
        and not stat.S_ISLNK(metadata.st_mode)
        and metadata.st_size > 0
        and os.access(path, os.R_OK)
    )


def _file_auth_available(path: Path) -> bool:
    try:
        metadata = path.lstat()
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_size <= 0
            or metadata.st_size > _MAX_AUTH_FILE_BYTES
            or not os.access(path, os.R_OK)
        ):
            return False
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    if not isinstance(value, Mapping):
        return False
    api_key = value.get("OPENAI_API_KEY")
    if isinstance(api_key, str) and bool(api_key.strip()):
        return True
    tokens = value.get("tokens")
    if not isinstance(tokens, Mapping):
        return False
    access_token = tokens.get("access_token")
    return isinstance(access_token, str) and bool(access_token.strip())


def _capability_preflight(
    codex_home: Path,
    environment: Mapping[str, str],
    *,
    provider_auth_prefixes: Sequence[str],
) -> str | None:
    environment_auth = _has_environment_auth(
        environment, provider_auth_prefixes
    )
    file_auth = _file_auth_available(codex_home / "auth.json")
    if not environment_auth and not file_auth:
        return "provider_auth_blocked"
    try:
        home_available = codex_home.is_dir()
    except OSError:
        home_available = False
    if not home_available or any(
        not _readable_nonempty_regular(codex_home / relative)
        for relative in _REQUIRED_SDD_PATHS
    ):
        return "provider_capability_blocked"
    return None


def _event_provider_code(event: Mapping[str, Any]) -> str | None:
    error = event.get("error")
    permission_code = _structured_permission_code(error)
    if permission_code is not None:
        return permission_code
    code = error.get("code") if isinstance(error, Mapping) else None
    if isinstance(code, str) and code:
        return code
    message = event.get("message")
    if not isinstance(message, str) and isinstance(error, Mapping):
        message = error.get("message")
    if not isinstance(message, str):
        return None
    bounded = message[:_MAX_ERROR_MESSAGE_CHARS]
    return "authentication_failed" if _AUTH_MESSAGE.search(bounded) else None


def _structured_permission_code(error: object) -> str | None:
    if not isinstance(error, Mapping):
        return None
    code = error.get("code")
    errno = error.get("errno")
    capability = error.get("capability")
    permission_system = error.get("permission_system")
    normalized_code = code.lower() if isinstance(code, str) else None
    normalized_errno = errno.upper() if isinstance(errno, str) else None
    normalized_capability = (
        capability.lower() if isinstance(capability, str) else None
    )
    normalized_system = (
        permission_system.lower()
        if isinstance(permission_system, str)
        else None
    )
    if (
        normalized_code in _HOST_PERMISSION_CODES
        or normalized_system in _HOST_PERMISSION_SYSTEMS
    ):
        return "host_permission_blocked"
    if (
        normalized_code in _SANDBOX_PERMISSION_CODES
        and normalized_errno in _PERMISSION_ERRNOS
    ) or (
        normalized_capability in _SANDBOX_CAPABILITIES
        and (
            normalized_errno in _PERMISSION_ERRNOS
            or normalized_code in _SANDBOX_PERMISSION_CODES
        )
    ):
        return "sandbox_capability_blocked"
    return None


def _required_cli_capability_failure(
    opened: OpenedExecutable,
    *,
    cwd: Path,
    env: Mapping[str, str],
    probe_argv: Sequence[str],
) -> str | None:
    version = run_exact(
        [probe_argv[0], "--version"],
        cwd=cwd,
        env=env,
        deadline_seconds=_CLI_PROBE_DEADLINE_SECONDS,
        output_limit=_CLI_PROBE_OUTPUT_LIMIT,
        opened_executable=opened,
    )
    if version.kind != "success" or not version.stdout_tail.strip():
        return "provider_unavailable"
    identity = opened.identity()
    cache_key = (
        str(identity["path"]),
        str(identity["sha256"]),
        int(identity["mode"]),
        int(identity["size"]),
        version.stdout_tail.decode("utf-8", "replace").strip(),
        tuple(probe_argv[1:]),
    )
    if cache_key in _CLI_CAPABILITY_CACHE:
        return None
    probe = run_exact(
        probe_argv,
        cwd=cwd,
        env=env,
        deadline_seconds=_CLI_PROBE_DEADLINE_SECONDS,
        output_limit=_CLI_PROBE_OUTPUT_LIMIT,
        opened_executable=opened,
    )
    if probe.kind != "success":
        return (
            "sandbox_capability_blocked"
            if _is_required_policy_parse_rejection(probe, probe_argv)
            else "controller_transport_failed"
        )
    opened.revalidate()
    _CLI_CAPABILITY_CACHE.add(cache_key)
    return None


def _is_required_policy_parse_rejection(
    result: ProcessResult,
    probe_argv: Sequence[str],
) -> bool:
    message = (
        result.stderr_tail + b"\n" + result.stdout_tail
    ).decode("utf-8", "replace").lower()
    diagnostic = message.split("\nusage:", 1)[0]
    if not any(marker in diagnostic for marker in _CLI_PARSE_REJECTION_MARKERS):
        return False
    for argument in probe_argv:
        if argument not in _REQUIRED_POLICY_ARGUMENTS:
            continue
        if argument == "-c":
            if re.search(r"(?<![a-z0-9])-c(?![a-z0-9])", diagnostic):
                return True
        elif argument.startswith("approval_policy="):
            if "approval_policy" in diagnostic:
                return True
        elif argument.lower() in diagnostic:
            return True
    return False


def _cli_preflight_failure(provider_code: str) -> ProviderOutcome:
    if provider_code == "sandbox_capability_blocked":
        return _blocked_preflight(provider_code)
    return _transport_preflight(provider_code)


def _transport_preflight(provider_code: str) -> ProviderOutcome:
    return ProviderOutcome(
        kind="transport_failed",
        return_code=None,
        session_id=None,
        result=None,
        provider_code=provider_code,
        usage={},
        activity_keys=(),
        stderr_tail="",
    )


def _blocked_preflight(provider_code: str) -> ProviderOutcome:
    return ProviderOutcome(
        kind="blocked",
        return_code=None,
        session_id=None,
        result=None,
        provider_code=provider_code,
        usage={},
        activity_keys=(),
        stderr_tail="",
    )


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
        return "transport_failed", "provider_unavailable"
    if code in _RESUME_CODES and requested_session_id is not None:
        return "resume_failed", "session_resume_failed"
    if code in _CONTEXT_CODES:
        return "context_overflow", "session_invalid"
    if code in _TRANSPORT_CODES:
        return "transport_failed", "controller_transport_failed"
    if code in {"host_permission_blocked", "sandbox_capability_blocked"}:
        return "blocked", code
    return None
