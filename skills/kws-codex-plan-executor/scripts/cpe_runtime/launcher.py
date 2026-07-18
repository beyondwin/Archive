"""Bounded fresh-process launcher for one sequential CPE plan."""

from __future__ import annotations

import json
import os
import re
import selectors
import signal
import stat
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence


_SECRETS = {
    "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN", "GITHUB_TOKEN",
}
_RETAINED_LOG_BYTES = 1_048_576
_COMPACT_AT_BYTES = 2_097_152
_JSON_EVENT_LINE_BYTES = 65_536
_USAGE_FIELDS = (
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
)
_MAX_USAGE_COUNTER = (1 << 63) - 1
CONTROLLER_OUTCOME_CODES = {
    "provider_usage_blocked",
    "provider_auth_blocked",
    "provider_unavailable",
    "controller_spawn_failed",
    "controller_transport_failed",
    "controller_result_missing",
    "controller_result_invalid",
    "controller_timed_out",
}
_PROVIDER_CODE = re.compile(r"^[a-z0-9_]{1,128}$")
_PROVIDER_USAGE_CODES = {
    "insufficient_quota",
    "quota_exceeded",
    "rate_limit",
    "rate_limit_exceeded",
    "usage_limit",
    "usage_limit_reached",
}
_PROVIDER_AUTH_CODES = {
    "auth_error",
    "authentication_error",
    "invalid_api_key",
    "permission_denied",
    "unauthorized",
}
_PROVIDER_UNAVAILABLE_CODES = {
    "overloaded",
    "provider_overloaded",
    "provider_unavailable",
    "server_overloaded",
    "service_unavailable",
}


def _git_common_directory(worktree: Path) -> Path:
    dot_git = worktree / ".git"
    if dot_git.is_dir() and not dot_git.is_symlink():
        resolved = dot_git.resolve(strict=True)
    elif dot_git.is_file() and not dot_git.is_symlink():
        declaration = dot_git.read_text(encoding="utf-8").strip()
        if not declaration.startswith("gitdir: "):
            raise ValueError("linked-worktree Git directory is invalid")
        declared_git = Path(declaration.removeprefix("gitdir: "))
        git_directory = (
            declared_git
            if declared_git.is_absolute()
            else dot_git.parent / declared_git
        ).resolve(strict=True)
        common_file = git_directory / "commondir"
        if common_file.is_file() and not common_file.is_symlink():
            declared_common = Path(
                common_file.read_text(encoding="utf-8").strip()
            )
            resolved = (
                declared_common
                if declared_common.is_absolute()
                else git_directory / declared_common
            ).resolve(strict=True)
        else:
            resolved = git_directory
    else:
        raise ValueError("worktree Git metadata is unavailable")
    if not resolved.is_dir():
        raise ValueError("Git common directory is not a directory")
    return resolved


def _provider_outcome(code: object) -> str | None:
    if not isinstance(code, str) or not code or len(code) > 128:
        return None
    normalized = re.sub(r"[-.\s]+", "_", code.strip().lower())
    if not _PROVIDER_CODE.fullmatch(normalized):
        return None
    if normalized in _PROVIDER_USAGE_CODES:
        return "provider_usage_blocked"
    if normalized in _PROVIDER_AUTH_CODES:
        return "provider_auth_blocked"
    if normalized in _PROVIDER_UNAVAILABLE_CODES:
        return "provider_unavailable"
    return None


def _controller_outcome(
    *,
    spawn_failed: bool,
    timed_out: bool,
    provider_outcome: str | None,
    result_present: bool,
    returncode: int | None,
) -> str | None:
    if spawn_failed:
        return "controller_spawn_failed"
    if timed_out:
        return "controller_timed_out"
    if provider_outcome in {
        "provider_usage_blocked",
        "provider_auth_blocked",
        "provider_unavailable",
    }:
        return provider_outcome
    if not result_present and returncode == 0:
        return "controller_result_missing"
    if not result_present:
        return "controller_transport_failed"
    return None


class _JsonEventFilter:
    def __init__(self) -> None:
        self._buffer = bytearray()
        self._dropping = False
        self.usage: dict[str, int | None] = {
            name: None for name in _USAGE_FIELDS
        }
        self.provider_outcome: str | None = None

    def feed(self, chunk: bytes) -> None:
        for segment in chunk.splitlines(keepends=True):
            complete = segment.endswith((b"\n", b"\r"))
            if self._dropping:
                if complete:
                    self._dropping = False
                continue
            self._buffer.extend(segment)
            if len(self._buffer) > _JSON_EVENT_LINE_BYTES:
                self._buffer.clear()
                self._dropping = not complete
                continue
            if complete:
                self._consume(bytes(self._buffer).rstrip(b"\r\n"))
                self._buffer.clear()

    def finish(self) -> None:
        if self._buffer and not self._dropping:
            self._consume(bytes(self._buffer))
        self._buffer.clear()
        self._dropping = False

    def _consume(self, line: bytes) -> None:
        try:
            event = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return
        if not isinstance(event, dict):
            return
        error = event.get("error")
        if self.provider_outcome is None and isinstance(error, dict):
            self.provider_outcome = _provider_outcome(error.get("code"))
        if event.get("type") != "turn.completed":
            return
        usage = event.get("usage")
        if not isinstance(usage, dict):
            return
        self.usage = {
            name: (
                value
                if isinstance((value := usage.get(name)), int)
                and not isinstance(value, bool)
                and 0 <= value <= _MAX_USAGE_COUNTER
                else None
            )
            for name in _USAGE_FIELDS
        }


class _StateDbWarningCounter:
    def __init__(self, sink: Callable[[bytes], None]) -> None:
        self._sink = sink
        self._buffer = bytearray()
        self._dropping = False
        self.count = 0

    def feed(self, chunk: bytes) -> None:
        self._sink(chunk)
        for segment in chunk.splitlines(keepends=True):
            complete = segment.endswith((b"\n", b"\r"))
            if self._dropping:
                if complete:
                    self._dropping = False
                continue
            self._buffer.extend(segment)
            if len(self._buffer) > _JSON_EVENT_LINE_BYTES:
                self._buffer.clear()
                self._dropping = not complete
                continue
            if complete:
                self._consume(bytes(self._buffer).rstrip(b"\r\n"))
                self._buffer.clear()

    def finish(self) -> None:
        if self._buffer and not self._dropping:
            self._consume(bytes(self._buffer))
        self._buffer.clear()
        self._dropping = False

    def _consume(self, line: bytes) -> None:
        lowered = line.lower()
        known = (
            b"failed to update state db" in lowered
            or b"failed to update state database" in lowered
            or (
                (b"state db" in lowered or b"state database" in lowered)
                and (
                    b"database is locked" in lowered
                    or b"database is busy" in lowered
                )
            )
            or (
                b"failed to record rollout" in lowered
                and b"database" in lowered
            )
        )
        if known and self.count < _MAX_USAGE_COUNTER:
            self.count += 1


class _BoundedLog:
    def __init__(self, path: Path) -> None:
        self.path = path
        descriptor = os.open(
            path,
            os.O_RDWR
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        self.stream = os.fdopen(descriptor, "w+b", buffering=0)
        self.total_bytes = 0
        self.discarded_bytes = 0

    def write(self, chunk: bytes) -> None:
        remaining = memoryview(chunk)
        while remaining:
            end = self.stream.seek(0, os.SEEK_END)
            capacity = _COMPACT_AT_BYTES - end
            if capacity <= 0:
                self._compact()
                continue
            portion = remaining[:capacity]
            self.stream.write(portion)
            self.total_bytes += len(portion)
            remaining = remaining[len(portion) :]
            if self.stream.tell() >= _COMPACT_AT_BYTES:
                self._compact()

    def _compact(self) -> None:
        end = self.stream.seek(0, os.SEEK_END)
        marker_budget = 96
        tail_size = max(0, _RETAINED_LOG_BYTES - marker_budget)
        self.stream.seek(max(0, end - tail_size))
        tail = self.stream.read(tail_size)
        self.discarded_bytes = max(0, self.total_bytes - len(tail))
        marker = (
            f"[cpe log truncated; discarded_bytes={self.discarded_bytes}]\n"
        ).encode("ascii")
        self.stream.seek(0)
        self.stream.truncate()
        self.stream.write(
            marker + tail[-(_RETAINED_LOG_BYTES - len(marker)) :]
        )

    def close(self) -> None:
        if self.stream.closed:
            return
        if self.stream.seek(0, os.SEEK_END) > _RETAINED_LOG_BYTES:
            self._compact()
        os.fsync(self.stream.fileno())
        self.stream.close()
        self.path.chmod(0o600)


def _group_exists(process_group: int) -> bool:
    try:
        os.killpg(process_group, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # macOS may transiently report EPERM after TERM and before the group
        # leader has been reaped. The group still exists during that window.
        return True


def _terminate_group(
    process: subprocess.Popen[bytes],
    grace_seconds: float,
) -> bool:
    process_group = process.pid
    forced = False
    if _group_exists(process_group):
        try:
            os.killpg(process_group, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
        deadline = time.monotonic() + grace_seconds
        while _group_exists(process_group) and time.monotonic() < deadline:
            process.poll()
            time.sleep(0.02)
        if _group_exists(process_group):
            forced = True
            try:
                os.killpg(process_group, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            deadline = time.monotonic() + max(1.0, grace_seconds)
            while _group_exists(process_group) and time.monotonic() < deadline:
                process.poll()
                time.sleep(0.02)
    direct_child_alive = False
    try:
        process.wait(timeout=max(1.0, grace_seconds))
    except subprocess.TimeoutExpired:
        direct_child_alive = True
    group_alive = _group_exists(process_group)
    if direct_child_alive or group_alive:
        raise RuntimeError("child process group did not terminate")
    return forced


def _drain_pipe(
    pipe: object,
    consume: Callable[[bytes], None],
) -> None:
    descriptor = pipe.fileno()  # type: ignore[attr-defined]
    while True:
        chunk = os.read(descriptor, 65_536)
        if not chunk:
            return
        consume(chunk)


def _drain_registered(selector: selectors.BaseSelector) -> None:
    for key in list(selector.get_map().values()):
        _drain_pipe(key.fileobj, key.data)
        selector.unregister(key.fileobj)


def _seal_regular_output(path: Path) -> os.stat_result | None:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return None
    if stat.S_ISREG(metadata.st_mode) and not path.is_symlink():
        path.chmod(0o400)
    return metadata


@dataclass(frozen=True)
class LaunchResult:
    payload: dict[str, object] | None
    returncode: int | None
    timed_out: bool
    forced_cleanup: bool
    discarded_log_bytes: int
    result_path: Path
    log_path: Path
    duration_ms: int
    input_tokens: int | None
    cached_input_tokens: int | None
    output_tokens: int | None
    reasoning_output_tokens: int | None
    launcher_prompt_bytes: int
    outcome_code: str | None = None
    state_db_warning_count: int = 0


@dataclass(frozen=True)
class StructuredLaunchRequest:
    command: list[str]
    cwd: Path
    prompt: str
    result_path: Path
    log_path: Path
    timeout_seconds: float


class CodexLauncher:
    def __init__(
        self,
        *,
        schema_path: Path,
        codex_bin: str = "codex",
        timeout_seconds: float = 3600,
        environ: Mapping[str, str] | None = None,
        termination_grace_seconds: float = 0.1,
    ) -> None:
        try:
            self.schema_path = schema_path.resolve(strict=True)
            schema = json.loads(self.schema_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("plan result schema is unavailable or invalid") from exc
        if not self.schema_path.is_file() or self.schema_path.is_symlink() or schema.get("additionalProperties") is not False:
            raise ValueError("plan result schema must be a strict regular file")
        if (
            not codex_bin
            or timeout_seconds <= 0
            or termination_grace_seconds <= 0
        ):
            raise ValueError("launcher configuration is invalid")
        self.codex_bin = codex_bin
        self.timeout_seconds = float(timeout_seconds)
        self.termination_grace_seconds = float(termination_grace_seconds)
        self.environ = dict(os.environ if environ is None else environ)

    @staticmethod
    def attempt_paths(
        results_directory: Path,
        logs_directory: Path,
        plan_id: str,
        attempt: int,
    ) -> tuple[Path, Path]:
        return (
            results_directory / f"{plan_id}-attempt-{attempt}.json",
            logs_directory / f"{plan_id}-attempt-{attempt}.log",
        )

    def _command(
        self, worktree: Path, result_path: Path, sandbox_mode: str,
    ) -> list[str]:
        return [
            self.codex_bin,
            "exec",
            "--ignore-user-config",
            "--ephemeral",
            "--json",
            "--sandbox",
            sandbox_mode,
            "--add-dir",
            str(_git_common_directory(worktree)),
            "-C",
            str(worktree),
            "--output-schema",
            str(self.schema_path),
            "--output-last-message",
            str(result_path),
            "-",
        ]

    @staticmethod
    def _prompt(
        *,
        worktree: Path,
        plan_id: str,
        plan_path: Path,
        spec_paths: Sequence[Path],
        starting_commit: str,
        current_commit: str,
        recovery_path: Path | None,
        execution_ledger: Path | None = None,
        verification_helper_descriptor: Path | None = None,
    ) -> str:
        lines = [
            "The worktree is already isolated for this run.",
            f"WORKTREE: {worktree}",
            f"PLAN_ID: {plan_id}",
            f"CURRENT_PLAN: {plan_path}",
            f"STARTING_COMMIT: {starting_commit}",
            f"CURRENT_COMMIT: {current_commit}",
            f"EXECUTION_LEDGER: {execution_ledger or 'unavailable'}",
            f"VERIFICATION_HELPER_DESCRIPTOR: {verification_helper_descriptor or 'unavailable'}",
            "SPECIFICATIONS:",
        ]
        lines.extend(f"- {path}" for path in spec_paths)
        if recovery_path is not None:
            lines.append(f"RECOVERY_CAPSULE: {recovery_path}")
        lines.extend(
            [
                "",
                "Follow repository AGENTS.md from root through the edited subtree.",
                "Use Superpowers. Ordinary agents reuse this worktree; create another only when the approved plan explicitly requires cross-revision comparison.",
                "Return only the fixed schema object as the final response. Do not merge, push, deploy, or modify files outside the worktree.",
            ]
        )
        return "\n".join(lines) + "\n"

    def launch(
        self,
        *,
        worktree: Path,
        plan_id: str,
        plan_path: Path,
        spec_paths: Sequence[Path],
        starting_commit: str,
        current_commit: str,
        result_path: Path,
        log_path: Path,
        lock_fd: int,
        recovery_path: Path | None = None,
        sandbox_mode: str,
        execution_ledger: Path | None = None,
        verification_helper_descriptor: Path | None = None,
    ) -> LaunchResult:
        """Launch one attempt using caller-owned paths and the held run lock."""
        request = StructuredLaunchRequest(
            command=self._command(worktree, result_path, sandbox_mode),
            cwd=worktree,
            prompt=self._prompt(
                worktree=worktree, plan_id=plan_id, plan_path=plan_path,
                spec_paths=spec_paths, starting_commit=starting_commit,
                current_commit=current_commit,
                recovery_path=recovery_path,
                execution_ledger=execution_ledger,
                verification_helper_descriptor=verification_helper_descriptor,
            ),
            result_path=result_path,
            log_path=log_path,
            timeout_seconds=self.timeout_seconds,
        )
        return self._launch_structured(request, lock_fd)

    def _launch_structured(
        self,
        request: StructuredLaunchRequest,
        lock_fd: int,
    ) -> LaunchResult:
        command = request.command
        prompt = request.prompt
        result_path = request.result_path
        log_path = request.log_path
        environment = {key: value for key, value in self.environ.items() if key not in _SECRETS}
        returncode: int | None = None
        timed_out = False
        forced_cleanup = False
        log = _BoundedLog(log_path)
        process: subprocess.Popen[bytes] | None = None
        selector = selectors.DefaultSelector()
        previous_sigterm: object | None = None
        manages_sigterm = threading.current_thread() is threading.main_thread()
        if manages_sigterm:
            previous_sigterm = signal.getsignal(signal.SIGTERM)

            def interrupt_on_sigterm(_signum: int, _frame: object) -> None:
                raise KeyboardInterrupt

            signal.signal(signal.SIGTERM, interrupt_on_sigterm)
        spawn_error: OSError | None = None
        prompt_bytes = prompt.encode("utf-8")
        started = time.monotonic()
        event_filter = _JsonEventFilter()
        diagnostics = _StateDbWarningCounter(log.write)
        try:
            try:
                process = subprocess.Popen(
                    command,
                    cwd=request.cwd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    start_new_session=True,
                    env=environment,
                    pass_fds=(lock_fd,),
                )
            except OSError as exc:
                spawn_error = exc
                log.write(
                    f"[cpe spawn failed: {(str(exc).strip() or type(exc).__name__)[:2000]}]\n".encode(
                        "utf-8", errors="replace"
                    )
                )
            if process is not None:
                assert (
                    process.stdin is not None
                    and process.stdout is not None
                    and process.stderr is not None
                )
                try:
                    process.stdin.write(prompt_bytes)
                    process.stdin.close()
                except BrokenPipeError:
                    process.stdin.close()
                selector.register(
                    process.stdout,
                    selectors.EVENT_READ,
                    event_filter.feed,
                )
                selector.register(
                    process.stderr,
                    selectors.EVENT_READ,
                    diagnostics.feed,
                )
                deadline = time.monotonic() + request.timeout_seconds
                while True:
                    remaining = deadline - time.monotonic()
                    if process.poll() is None and remaining <= 0:
                        timed_out = True
                        _terminate_group(process, self.termination_grace_seconds)
                        returncode = process.returncode
                        _drain_registered(selector)
                        break
                    events = selector.select(
                        min(0.02, max(0.0, remaining))
                        if process.poll() is None
                        else 0
                    )
                    for key, _ in events:
                        sink = key.data
                        chunk = os.read(key.fd, 65_536)
                        if chunk:
                            sink(chunk)
                        else:
                            selector.unregister(key.fileobj)
                    observed = process.poll()
                    if observed is not None:
                        returncode = observed
                        if _group_exists(process.pid):
                            forced_cleanup = True
                            _terminate_group(
                                process,
                                self.termination_grace_seconds,
                            )
                        _drain_registered(selector)
                        break
        except BaseException:
            if process is not None:
                _terminate_group(process, self.termination_grace_seconds)
                _drain_registered(selector)
            raise
        finally:
            selector.close()
            if process is not None and process.stdout is not None:
                process.stdout.close()
            if process is not None and process.stderr is not None:
                process.stderr.close()
            diagnostics.finish()
            log.close()
            if manages_sigterm and previous_sigterm is not None:
                signal.signal(signal.SIGTERM, previous_sigterm)

        event_filter.finish()
        payload = None
        if (
            result_path.is_file()
            and not result_path.is_symlink()
            and result_path.stat().st_size <= 1_048_576
        ):
            try:
                candidate = json.loads(result_path.read_text(encoding="utf-8"))
                if isinstance(candidate, dict):
                    payload = candidate
                result_path.chmod(0o600)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                payload = None
        if spawn_error is not None:
            returncode = None
        outcome_code = _controller_outcome(
            spawn_failed=spawn_error is not None,
            timed_out=timed_out,
            provider_outcome=event_filter.provider_outcome,
            result_present=payload is not None,
            returncode=returncode,
        )
        duration_ms = max(0, round((time.monotonic() - started) * 1000))
        return LaunchResult(
            payload=payload,
            returncode=returncode,
            timed_out=timed_out,
            forced_cleanup=forced_cleanup,
            discarded_log_bytes=log.discarded_bytes,
            result_path=result_path,
            log_path=log_path,
            duration_ms=duration_ms,
            input_tokens=event_filter.usage["input_tokens"],
            cached_input_tokens=event_filter.usage["cached_input_tokens"],
            output_tokens=event_filter.usage["output_tokens"],
            reasoning_output_tokens=event_filter.usage[
                "reasoning_output_tokens"
            ],
            launcher_prompt_bytes=len(prompt_bytes),
            outcome_code=outcome_code,
            state_db_warning_count=diagnostics.count,
        )
