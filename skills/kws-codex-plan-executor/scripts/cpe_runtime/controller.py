"""Thin POSIX process and JSONL adapter for one Codex controller session."""

from __future__ import annotations

import json
import os
import selectors
import signal
import subprocess
import sys
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from .state import (
    SANDBOXES,
    SHA40,
    GitIdentity,
    validate_resume_capsule,
)


MAX_JSONL_LINE_BYTES = 1_048_576
MAX_TERMINAL_ENVELOPE_BYTES = 65_536
MAX_LIVE_OUTPUT_BYTES = 65_536
TERMINAL_CLAIMS = frozenset({"completed", "interrupted", "blocked", "failed"})
PROVIDER_CODES = frozenset(
    {
        "auth",
        "quota",
        "provider_unavailable",
        "session_unavailable",
        "transport",
        "unknown",
    }
)


@dataclass(frozen=True)
class ResumeCapsule:
    head_commit: str
    worktree_status_digest: str
    note: str
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True)
class TerminalEnvelope:
    claim: str
    head_commit: str
    resume_capsule: ResumeCapsule | None
    blocker: Mapping[str, object] | None


@dataclass(frozen=True)
class ControllerRequest:
    mode: str
    worktree: Path
    git_common_dir: Path
    sandbox: str
    prompt: str
    schema_path: Path
    session_id: str | None
    generation: int
    git_identity: GitIdentity
    lock_fd: int


@dataclass(frozen=True)
class ControllerOutcome:
    session_id: str | None
    exit_code: int
    process_class: str
    terminal: TerminalEnvelope | None
    provider_code: str | None


@dataclass(frozen=True)
class _DrainResult:
    session_id: str | None
    terminal_text: str | None
    provider_code: str | None
    invalid_stream: bool


def _canonical_uuid(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("controller session ID is invalid")
    try:
        parsed = uuid.UUID(value)
    except (AttributeError, ValueError) as exc:
        raise ValueError("controller session ID is invalid") from exc
    if str(parsed) != value:
        raise ValueError("controller session ID is invalid")
    return value


def _utf8_length(value: object, *, maximum: int, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} is invalid")
    try:
        length = len(value.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise ValueError(f"{name} is invalid") from exc
    if not 1 <= length <= maximum:
        raise ValueError(f"{name} is invalid")
    return value


def _provider_code(event: Mapping[str, object]) -> str:
    nested = event.get("error")
    raw_code: object = None
    if isinstance(nested, Mapping):
        raw_code = nested.get("code")
    if raw_code is None:
        raw_code = event.get("code")
    if not isinstance(raw_code, str):
        return "unknown"
    code = raw_code.casefold().replace("_", "-")
    if any(
        token in code
        for token in (
            "invalid-api-key",
            "api-key-invalid",
            "authentication",
            "authorization",
            "unauthorized",
            "credential",
            "auth-",
        )
    ):
        return "auth"
    if any(
        token in code
        for token in (
            "quota",
            "rate-limit",
            "usage-limit",
            "billing-limit",
            "429",
        )
    ):
        return "quota"
    if (
        any(token in code for token in ("session", "thread"))
        and any(token in code for token in ("not-found", "unavailable", "expired", "missing"))
    ):
        return "session_unavailable"
    if any(
        token in code
        for token in (
            "provider-overloaded",
            "provider-unavailable",
            "overloaded",
            "capacity",
            "service-unavailable",
            "503",
        )
    ):
        return "provider_unavailable"
    if any(
        token in code
        for token in (
            "transport",
            "network",
            "connection",
            "disconnected",
            "stream-",
            "timeout",
        )
    ):
        return "transport"
    return "unknown"


def _resume_capsule(value: object) -> ResumeCapsule | None:
    if value is None:
        return None
    normalized = validate_resume_capsule(value)
    references = normalized["evidence_refs"]
    if not isinstance(references, list):
        raise ValueError("resume capsule is invalid")
    return ResumeCapsule(
        head_commit=str(normalized["head_commit"]),
        worktree_status_digest=str(normalized["worktree_status_digest"]),
        note=str(normalized["note"]),
        evidence_refs=tuple(str(reference) for reference in references),
    )


def _terminal_envelope(value: str) -> TerminalEnvelope:
    _utf8_length(
        value,
        maximum=MAX_TERMINAL_ENVELOPE_BYTES,
        name="terminal envelope",
    )
    try:
        payload = json.loads(value)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("terminal envelope is invalid") from exc
    allowed = {"claim", "head_commit", "resume_capsule", "blocker"}
    if (
        not isinstance(payload, dict)
        or not {"claim", "head_commit"} <= set(payload)
        or not set(payload) <= allowed
    ):
        raise ValueError("terminal envelope is invalid")
    claim = _utf8_length(payload["claim"], maximum=64, name="terminal claim")
    if claim not in TERMINAL_CLAIMS:
        raise ValueError("terminal envelope is invalid")
    head_commit = payload["head_commit"]
    if not isinstance(head_commit, str) or not SHA40.fullmatch(head_commit):
        raise ValueError("terminal envelope is invalid")
    capsule = _resume_capsule(payload.get("resume_capsule"))
    blocker = payload.get("blocker")
    if blocker is not None and not isinstance(blocker, Mapping):
        raise ValueError("terminal envelope is invalid")
    return TerminalEnvelope(
        claim=claim,
        head_commit=head_commit,
        resume_capsule=capsule,
        blocker=None if blocker is None else dict(blocker),
    )


class CodexController:
    """Launch one Codex process and return bounded transport facts."""

    def __init__(
        self,
        *,
        executable: str = "codex",
        termination_grace_seconds: float = 1.0,
    ) -> None:
        if (
            not isinstance(executable, str)
            or not executable
            or "\x00" in executable
        ):
            raise ValueError("controller executable is invalid")
        if (
            isinstance(termination_grace_seconds, bool)
            or not isinstance(termination_grace_seconds, (int, float))
            or not 0 <= termination_grace_seconds <= 10
        ):
            raise ValueError("termination grace is invalid")
        self.executable = executable
        self.termination_grace_seconds = float(termination_grace_seconds)

    def build_argv(self, request: ControllerRequest) -> list[str]:
        self._validate_request(request)
        argv = [
            self.executable,
            "exec",
            "--ignore-user-config",
            "--ignore-rules",
            "--strict-config",
            "-c",
            'approval_policy="never"',
            "--json",
            "--output-schema",
            str(request.schema_path),
            "--cd",
            str(request.worktree),
            "--sandbox",
            request.sandbox,
            "--add-dir",
            str(request.git_common_dir),
        ]
        argv.extend(
            ["-"]
            if request.session_id is None
            else ["resume", request.session_id, "-"]
        )
        return argv

    @staticmethod
    def build_environment(request: ControllerRequest) -> dict[str, str]:
        if not isinstance(request, ControllerRequest):
            raise ValueError("controller request is invalid")
        identity = request.git_identity.to_payload()
        environment = os.environ.copy()
        for name in tuple(environment):
            if name == "GIT_CONFIG" or name.startswith("GIT_CONFIG_"):
                environment.pop(name)
        environment.update(
            {
                "GIT_AUTHOR_NAME": identity["author_name"],
                "GIT_AUTHOR_EMAIL": identity["author_email"],
                "GIT_COMMITTER_NAME": identity["committer_name"],
                "GIT_COMMITTER_EMAIL": identity["committer_email"],
            }
        )
        return environment

    def launch(
        self,
        request: ControllerRequest,
        on_session_id: Callable[[str], None],
        on_process_started: Callable[[int, int], None],
    ) -> ControllerOutcome:
        argv = self.build_argv(request)
        environment = self.build_environment(request)
        process = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=request.worktree,
            env=environment,
            start_new_session=True,
            pass_fds=(request.lock_fd,),
        )
        process_group = process.pid
        try:
            on_process_started(process.pid, process_group)
            self._write_prompt(process, request.prompt)
            drained = self._drain(
                process,
                expected_session_id=request.session_id,
                on_session_id=on_session_id,
            )
            exit_code = process.wait()
        except BaseException:
            self._close_stdin(process)
            self._terminate(process, process_group)
            self._close_outputs(process)
            raise
        self._close_outputs(process)
        return self._outcome(drained, exit_code)

    @staticmethod
    def _validate_request(request: ControllerRequest) -> None:
        if not isinstance(request, ControllerRequest):
            raise ValueError("controller request is invalid")
        if request.session_id is not None:
            _canonical_uuid(request.session_id)
        if request.sandbox not in SANDBOXES:
            raise ValueError("controller sandbox is invalid")
        if not isinstance(request.mode, str) or not request.mode:
            raise ValueError("controller mode is invalid")
        if (
            not isinstance(request.generation, int)
            or isinstance(request.generation, bool)
            or request.generation < 0
        ):
            raise ValueError("controller generation is invalid")
        if not isinstance(request.git_identity, GitIdentity):
            raise ValueError("controller Git identity is invalid")
        if (
            not isinstance(request.lock_fd, int)
            or isinstance(request.lock_fd, bool)
            or request.lock_fd < 0
        ):
            raise ValueError("controller lock descriptor is invalid")
        if not isinstance(request.prompt, str):
            raise ValueError("controller prompt is invalid")
        try:
            request.prompt.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ValueError("controller prompt is invalid") from exc
        for name in ("worktree", "git_common_dir", "schema_path"):
            path = getattr(request, name)
            if not isinstance(path, Path) or not path.is_absolute():
                raise ValueError(f"controller {name} is invalid")

    @staticmethod
    def _write_prompt(
        process: subprocess.Popen[bytes],
        prompt: str,
    ) -> None:
        if process.stdin is None:
            raise RuntimeError("controller stdin is unavailable")
        try:
            process.stdin.write(prompt.encode("utf-8"))
            process.stdin.flush()
        except BrokenPipeError:
            pass
        finally:
            process.stdin.close()

    def _drain(
        self,
        process: subprocess.Popen[bytes],
        *,
        expected_session_id: str | None,
        on_session_id: Callable[[str], None],
    ) -> _DrainResult:
        if process.stdout is None or process.stderr is None:
            raise RuntimeError("controller output streams are unavailable")
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ, "stdout")
        selector.register(process.stderr, selectors.EVENT_READ, "stderr")
        for stream in (process.stdout, process.stderr):
            os.set_blocking(stream.fileno(), False)

        session_id = expected_session_id
        terminal_text: str | None = None
        provider_code: str | None = None
        invalid_stream = False
        stdout_buffer = bytearray()
        discarding_oversized_line = False
        forwarded = {"stdout": 0, "stderr": 0}

        def consume_event(line: bytes) -> None:
            nonlocal session_id, terminal_text, provider_code, invalid_stream
            if line.endswith(b"\r"):
                line = line[:-1]
            if not line.strip():
                return
            try:
                event = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
                invalid_stream = True
                return
            if not isinstance(event, dict):
                invalid_stream = True
                return
            event_type = event.get("type")
            if event_type == "thread.started":
                try:
                    observed = _canonical_uuid(event.get("thread_id"))
                except ValueError:
                    invalid_stream = True
                    return
                if session_id is None:
                    session_id = observed
                    on_session_id(observed)
                elif session_id != observed:
                    invalid_stream = True
                return
            if event_type == "item.completed":
                item = event.get("item")
                if isinstance(item, Mapping) and item.get("type") == "agent_message":
                    text = item.get("text")
                    try:
                        terminal_text = _utf8_length(
                            text,
                            maximum=MAX_TERMINAL_ENVELOPE_BYTES,
                            name="terminal envelope",
                        )
                    except ValueError:
                        terminal_text = None
                        invalid_stream = True
                return
            if event_type in {"error", "turn.failed"} or "error" in event:
                candidate = _provider_code(event)
                if candidate not in PROVIDER_CODES:
                    candidate = "unknown"
                if provider_code is None:
                    provider_code = candidate

        try:
            while selector.get_map():
                ready = selector.select(timeout=0.1)
                for key, _events in ready:
                    stream = key.fileobj
                    label = key.data
                    try:
                        chunk = os.read(stream.fileno(), 65_536)
                    except BlockingIOError:
                        continue
                    if not chunk:
                        selector.unregister(stream)
                        stream.close()
                        if label == "stdout" and stdout_buffer:
                            if discarding_oversized_line:
                                invalid_stream = True
                            else:
                                consume_event(bytes(stdout_buffer))
                            stdout_buffer.clear()
                        continue
                    self._forward_live(label, chunk, forwarded)
                    if label != "stdout":
                        continue
                    parts = chunk.split(b"\n")
                    for index, part in enumerate(parts):
                        terminated = index < len(parts) - 1
                        if discarding_oversized_line:
                            if terminated:
                                discarding_oversized_line = False
                            continue
                        if len(stdout_buffer) + len(part) > MAX_JSONL_LINE_BYTES:
                            invalid_stream = True
                            stdout_buffer.clear()
                            if not terminated:
                                discarding_oversized_line = True
                            continue
                        stdout_buffer.extend(part)
                        if terminated:
                            consume_event(bytes(stdout_buffer))
                            stdout_buffer.clear()
        finally:
            selector.close()
        return _DrainResult(
            session_id=session_id,
            terminal_text=terminal_text,
            provider_code=provider_code,
            invalid_stream=invalid_stream,
        )

    @staticmethod
    def _forward_live(
        label: str,
        chunk: bytes,
        forwarded: dict[str, int],
    ) -> None:
        remaining = MAX_LIVE_OUTPUT_BYTES - forwarded[label]
        if remaining <= 0:
            return
        payload = chunk[:remaining]
        forwarded[label] += len(payload)
        stream = sys.stdout if label == "stdout" else sys.stderr
        binary = getattr(stream, "buffer", None)
        try:
            if binary is not None:
                binary.write(payload)
                binary.flush()
            else:
                stream.write(payload.decode("utf-8", errors="replace"))
                stream.flush()
        except (BrokenPipeError, OSError):
            forwarded[label] = MAX_LIVE_OUTPUT_BYTES

    def _terminate(
        self,
        process: subprocess.Popen[bytes],
        process_group: int,
    ) -> None:
        if process.poll() is not None:
            process.wait()
            return
        try:
            os.killpg(process_group, signal.SIGTERM)
        except ProcessLookupError:
            process.wait()
            return
        try:
            process.wait(timeout=self.termination_grace_seconds)
            return
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(process_group, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=max(1.0, self.termination_grace_seconds))

    @staticmethod
    def _close_stdin(process: subprocess.Popen[bytes]) -> None:
        if process.stdin is not None and not process.stdin.closed:
            process.stdin.close()

    @staticmethod
    def _close_outputs(process: subprocess.Popen[bytes]) -> None:
        for stream in (process.stdout, process.stderr):
            if stream is not None and not stream.closed:
                stream.close()

    @staticmethod
    def _outcome(drained: _DrainResult, exit_code: int) -> ControllerOutcome:
        terminal: TerminalEnvelope | None = None
        invalid = drained.invalid_stream
        if not invalid and drained.terminal_text is not None:
            try:
                terminal = _terminal_envelope(drained.terminal_text)
            except ValueError:
                invalid = True
        elif not invalid and exit_code == 0:
            invalid = True
        if terminal is not None and drained.session_id is None:
            terminal = None
            invalid = True

        provider_code = drained.provider_code
        if provider_code is None and exit_code != 0 and terminal is None and not invalid:
            provider_code = "unknown"
        if invalid:
            process_class = "invalid_envelope"
            terminal = None
        elif terminal is not None:
            process_class = terminal.claim
            if terminal.claim == "completed" and exit_code != 0:
                process_class = "failed"
        elif provider_code in {"auth", "quota", "provider_unavailable"}:
            process_class = "blocked"
        elif exit_code in {130, 143, -signal.SIGINT, -signal.SIGTERM}:
            process_class = "interrupted"
        else:
            process_class = "failed"
        return ControllerOutcome(
            session_id=drained.session_id,
            exit_code=exit_code,
            process_class=process_class,
            terminal=terminal,
            provider_code=provider_code,
        )
