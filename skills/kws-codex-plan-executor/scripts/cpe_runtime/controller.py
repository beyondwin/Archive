from __future__ import annotations
import json, os, selectors, signal, subprocess, sys, threading, time, uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from .state import SANDBOXES, SHA40, GitIdentity, validate_resume_capsule
MAX_JSONL_LINE_BYTES = 1_048_576
MAX_TERMINAL_ENVELOPE_BYTES = 65_536
MAX_LIVE_OUTPUT_BYTES = 65_536
TERMINAL_CLAIMS = frozenset({"completed", "interrupted", "blocked"})
PROVIDER_CODES = frozenset({
    "auth", "quota", "provider_unavailable", "session_unavailable",
    "transport", "unknown",
})
_SECRETS = {"OPENAI_API_KEY", "ANTHROPIC_API_KEY", "AWS_SECRET_ACCESS_KEY",
            "AWS_SESSION_TOKEN", "GITHUB_TOKEN"}
_GIT_ROUTING = {"GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
                "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES"}
_BLOCKER_LIMITS = {
    "class": 64, "code": 128, "resource": 256, "operation": 128,
    "retry_condition": 512,
}
_PROVIDER_PATTERNS = {
    "auth": ("invalid-api-key", "api-key-invalid", "authentication", "authorization",
             "unauthorized", "credential", "auth-"),
    "quota": ("quota", "rate-limit", "usage-limit", "billing-limit", "429"),
    "provider_unavailable": ("provider-overloaded", "provider-unavailable", "overloaded",
                             "capacity", "service-unavailable", "503"),
    "transport": ("transport", "network", "connection", "disconnected", "stream-", "timeout"),
}
@dataclass(frozen=True)
class ResumeCapsule:
    head_commit: str; worktree_status_digest: str; note: str; evidence_refs: tuple[str, ...]
@dataclass(frozen=True)
class TerminalEnvelope:
    claim: str; head_commit: str; resume_capsule: ResumeCapsule | None; blocker: Mapping[str, object] | None
@dataclass(frozen=True)
class ControllerRequest:
    mode: str; worktree: Path; git_common_dir: Path; sandbox: str; prompt: str
    schema_path: Path; session_id: str | None; generation: int
    git_identity: GitIdentity; lock_fd: int
@dataclass(frozen=True)
class ControllerOutcome:
    session_id: str | None; exit_code: int; process_class: str
    terminal: TerminalEnvelope | None; provider_code: str | None
def _canonical_uuid(value: object) -> str:
    if not isinstance(value, str): raise ValueError("controller session ID is invalid")
    try:
        parsed = uuid.UUID(value)
    except (AttributeError, ValueError) as exc:
        raise ValueError("controller session ID is invalid") from exc
    if str(parsed) != value: raise ValueError("controller session ID is invalid")
    return value
def _bounded(value: object, maximum: int, name: str) -> str:
    if not isinstance(value, str): raise ValueError(f"{name} is invalid")
    try:
        size = len(value.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise ValueError(f"{name} is invalid") from exc
    if not 1 <= size <= maximum: raise ValueError(f"{name} is invalid")
    return value
def _provider_code(event: Mapping[str, object]) -> str:
    nested = event.get("error")
    code = nested.get("code") if isinstance(nested, Mapping) else event.get("code")
    if not isinstance(code, str): return "unknown"
    code = code.casefold().replace("_", "-")
    if (any(token in code for token in ("session", "thread"))
            and any(token in code for token in ("not-found", "unavailable", "expired", "missing"))):
        return "session_unavailable"
    for classification, patterns in _PROVIDER_PATTERNS.items():
        if any(pattern in code for pattern in patterns):
            return classification
    return "unknown"
def _capsule(value: object) -> ResumeCapsule | None:
    if value is None: return None
    normalized = validate_resume_capsule(value)
    refs = normalized["evidence_refs"]
    assert isinstance(refs, list)
    return ResumeCapsule(
        str(normalized["head_commit"]), str(normalized["worktree_status_digest"]),
        str(normalized["note"]), tuple(str(ref) for ref in refs),
    )
def _blocker(value: object) -> dict[str, object] | None:
    if value is None: return None
    required, allowed = set(_BLOCKER_LIMITS), set(_BLOCKER_LIMITS) | {"provider_code"}
    if not isinstance(value, Mapping) or not required <= set(value) or not set(value) <= allowed:
        raise ValueError("terminal blocker is invalid")
    normalized: dict[str, object] = {key: _bounded(value[key], limit, "terminal blocker")
                                    for key, limit in _BLOCKER_LIMITS.items()}
    if "provider_code" in value:
        provider = value["provider_code"]
        normalized["provider_code"] = None if provider is None else _bounded(provider, 128, "terminal blocker")
    return normalized
def _envelope(text: str) -> TerminalEnvelope:
    _bounded(text, MAX_TERMINAL_ENVELOPE_BYTES, "terminal envelope")
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("terminal envelope is invalid") from exc
    allowed = {"claim", "head_commit", "resume_capsule", "blocker"}
    if (not isinstance(payload, dict) or not {"claim", "head_commit"} <= set(payload)
            or not set(payload) <= allowed):
        raise ValueError("terminal envelope is invalid")
    claim = _bounded(payload["claim"], 64, "terminal claim")
    head = payload["head_commit"]
    if claim not in TERMINAL_CLAIMS or not isinstance(head, str) or not SHA40.fullmatch(head):
        raise ValueError("terminal envelope is invalid")
    if any(key in payload and payload[key] is None for key in ("resume_capsule", "blocker")):
        raise ValueError("terminal envelope is invalid")
    capsule, blocker = _capsule(payload.get("resume_capsule")), _blocker(payload.get("blocker"))
    invalid_combo = ((claim == "completed" and (capsule is not None or blocker is not None))
                     or (claim == "interrupted" and (capsule is None or blocker is not None))
                     or (claim == "blocked" and blocker is None))
    if invalid_combo: raise ValueError("terminal envelope is invalid")
    return TerminalEnvelope(claim, head, capsule, blocker)
class _JsonlParser:
    def __init__(self, session_id: str | None, on_session_id: Callable[[str], None]) -> None:
        self.session_id, self.on_session_id = session_id, on_session_id
        self.terminal_text: str | None = None; self.provider_code: str | None = None
        self.invalid = False; self.buffer = bytearray(); self.discarding = False
    def feed(self, chunk: bytes) -> None:
        parts = chunk.split(b"\n")
        for index, part in enumerate(parts):
            terminated = index < len(parts) - 1
            if self.discarding:
                if terminated: self.discarding = False
                continue
            if len(self.buffer) + len(part) > MAX_JSONL_LINE_BYTES:
                self.invalid, self.buffer = True, bytearray()
                self.discarding = not terminated
                continue
            self.buffer.extend(part)
            if terminated:
                self._line(bytes(self.buffer))
                self.buffer.clear()

    def finish(self) -> None:
        if self.discarding:
            self.invalid = True
        elif self.buffer:
            self._line(bytes(self.buffer))
        self.buffer.clear()
    def _line(self, line: bytes) -> None:
        line = line[:-1] if line.endswith(b"\r") else line
        if not line.strip(): return
        try:
            event = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
            self.invalid = True
            return
        if not isinstance(event, dict): self.invalid = True; return
        kind = event.get("type")
        if kind == "thread.started":
            try:
                observed = _canonical_uuid(event.get("thread_id"))
            except ValueError:
                self.invalid = True
                return
            if self.session_id is None:
                self.session_id = observed
                self.on_session_id(observed)
            elif self.session_id != observed: self.invalid = True
        elif kind == "item.completed":
            item = event.get("item")
            if isinstance(item, Mapping) and item.get("type") == "agent_message":
                try:
                    self.terminal_text = _bounded(
                        item.get("text"), MAX_TERMINAL_ENVELOPE_BYTES,
                        "terminal envelope",
                    )
                except ValueError:
                    self.terminal_text, self.invalid = None, True
        elif kind in {"error", "turn.failed"} or "error" in event:
            if self.provider_code is None: self.provider_code = _provider_code(event)
class CodexController:
    """Launch one Codex process and return bounded transport facts."""

    def __init__(self, *, executable: str = "codex", termination_grace_seconds: float = 1.0) -> None:
        if not isinstance(executable, str) or not executable or "\x00" in executable:
            raise ValueError("controller executable is invalid")
        if (
            isinstance(termination_grace_seconds, bool)
            or not isinstance(termination_grace_seconds, (int, float))
            or not 0 <= termination_grace_seconds <= 10
        ):
            raise ValueError("termination grace is invalid")
        self.executable = executable
        self.termination_grace_seconds = float(termination_grace_seconds)

    @staticmethod
    def _validate(request: ControllerRequest) -> None:
        if not isinstance(request, ControllerRequest):
            raise ValueError("controller request is invalid")
        if request.session_id is not None:
            _canonical_uuid(request.session_id)
        if request.sandbox not in SANDBOXES or not isinstance(request.mode, str) or not request.mode:
            raise ValueError("controller request is invalid")
        if (
            not isinstance(request.generation, int) or isinstance(request.generation, bool)
            or request.generation < 0
        ):
            raise ValueError("controller generation is invalid")
        if not isinstance(request.git_identity, GitIdentity):
            raise ValueError("controller Git identity is invalid")
        if not isinstance(request.lock_fd, int) or isinstance(request.lock_fd, bool) or request.lock_fd < 0:
            raise ValueError("controller lock descriptor is invalid")
        if not isinstance(request.prompt, str):
            raise ValueError("controller prompt is invalid")
        try:
            request.prompt.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ValueError("controller prompt is invalid") from exc
        if any(
            not isinstance(path, Path) or not path.is_absolute()
            for path in (request.worktree, request.git_common_dir, request.schema_path)
        ):
            raise ValueError("controller path is invalid")

    def build_argv(self, request: ControllerRequest) -> list[str]:
        self._validate(request)
        argv = [
            self.executable, "exec", "--ignore-user-config", "--ignore-rules",
            "--strict-config", "-c", 'approval_policy="never"', "--json",
            "--output-schema", str(request.schema_path), "--cd", str(request.worktree),
            "--sandbox", request.sandbox, "--add-dir", str(request.git_common_dir),
        ]
        argv.extend(["-"] if request.session_id is None else ["resume", request.session_id, "-"])
        return argv

    @staticmethod
    def build_environment(request: ControllerRequest) -> dict[str, str]:
        if not isinstance(request, ControllerRequest):
            raise ValueError("controller request is invalid")
        identity, environment = request.git_identity.to_payload(), os.environ.copy()
        for key in tuple(environment):
            if (
                key in _SECRETS or key in _GIT_ROUTING or key == "GIT_CONFIG"
                or key.startswith("GIT_CONFIG_")
            ):
                environment.pop(key)
        environment.update({
            "GIT_AUTHOR_NAME": identity["author_name"],
            "GIT_AUTHOR_EMAIL": identity["author_email"],
            "GIT_COMMITTER_NAME": identity["committer_name"],
            "GIT_COMMITTER_EMAIL": identity["committer_email"],
        })
        return environment

    def launch(
        self,
        request: ControllerRequest,
        on_session_id: Callable[[str], None],
        on_process_started: Callable[[int, int], None],
    ) -> ControllerOutcome:
        argv, environment = self.build_argv(request), self.build_environment(request)
        main_thread = threading.current_thread() is threading.main_thread()
        previous_sigterm = signal.getsignal(signal.SIGTERM) if main_thread else None
        if main_thread:
            def interrupt(_signum: int, _frame: object) -> None:
                raise KeyboardInterrupt
            signal.signal(signal.SIGTERM, interrupt)
        try:
            process = subprocess.Popen(
                argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, cwd=request.worktree, env=environment,
                start_new_session=True, pass_fds=(request.lock_fd,),
            )
            try:
                on_process_started(process.pid, process.pid)
                parser = self._drain(process, request.prompt, request.session_id, on_session_id)
                exit_code = process.wait()
            except BaseException:
                self._close(process.stdin)
                self._terminate(process)
                self._close(process.stdout, process.stderr)
                raise
            self._close(process.stdout, process.stderr)
            return self._outcome(parser, exit_code)
        finally:
            if main_thread and previous_sigterm is not None:
                signal.signal(signal.SIGTERM, previous_sigterm)

    def _drain(
        self,
        process: subprocess.Popen[bytes],
        prompt: str,
        expected_session_id: str | None,
        on_session_id: Callable[[str], None],
    ) -> _JsonlParser:
        if process.stdin is None or process.stdout is None or process.stderr is None:
            raise RuntimeError("controller process streams are unavailable")
        selector, parser = selectors.DefaultSelector(), _JsonlParser(
            expected_session_id, on_session_id,
        )
        selector.register(process.stdout, selectors.EVENT_READ, "stdout")
        selector.register(process.stderr, selectors.EVENT_READ, "stderr")
        prompt_bytes, prompt_offset = prompt.encode("utf-8"), 0
        for stream in (process.stdin, process.stdout, process.stderr):
            os.set_blocking(stream.fileno(), False)
        if prompt_bytes:
            selector.register(process.stdin, selectors.EVENT_WRITE, "stdin")
        else:
            process.stdin.close()
        forwarded, final_deadline = {"stdout": 0, "stderr": 0}, None
        try:
            while selector.get_map():
                timeout = 0.1 if final_deadline is None else min(
                    0.1, max(0.0, final_deadline - time.monotonic()),
                )
                for key, _events in selector.select(timeout):
                    stream, label = key.fileobj, key.data
                    if label == "stdin":
                        try:
                            sent = os.write(
                                stream.fileno(),
                                prompt_bytes[prompt_offset:prompt_offset + 65_536],
                            )
                            prompt_offset += sent
                        except BrokenPipeError:
                            prompt_offset = len(prompt_bytes)
                        if prompt_offset >= len(prompt_bytes):
                            selector.unregister(stream)
                            stream.close()
                        continue
                    try:
                        chunk = os.read(stream.fileno(), 65_536)
                    except BlockingIOError:
                        continue
                    if not chunk:
                        selector.unregister(stream)
                        stream.close()
                        continue
                    self._forward(label, chunk, forwarded)
                    if label == "stdout":
                        parser.feed(chunk)
                if (final_deadline is None and os.waitid(
                    os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT,
                ) is not None):
                    self._unregister_close(selector, process.stdin)
                    self._terminate(process)
                    final_deadline = time.monotonic() + 0.25
                if final_deadline is not None and time.monotonic() >= final_deadline:
                    break
        finally:
            selector.close()
        parser.finish()
        return parser

    @staticmethod
    def _forward(label: str, chunk: bytes, forwarded: dict[str, int]) -> None:
        payload = chunk[:max(0, MAX_LIVE_OUTPUT_BYTES - forwarded[label])]
        if not payload:
            return
        forwarded[label] += len(payload)
        stream = sys.stdout if label == "stdout" else sys.stderr
        binary = getattr(stream, "buffer", None)
        try:
            (binary.write(payload) if binary is not None else stream.write(
                payload.decode("utf-8", errors="replace")
            ))
            (binary if binary is not None else stream).flush()
        except (BrokenPipeError, OSError):
            forwarded[label] = MAX_LIVE_OUTPUT_BYTES

    def _terminate(self, process: subprocess.Popen[bytes]) -> None:
        group = process.pid
        exited = process.returncode is not None or os.waitid(
            os.P_PID, group, os.WEXITED | os.WNOHANG | os.WNOWAIT,
        ) is not None
        try:
            if not self._group_exists(group):
                return
            try:
                os.killpg(group, signal.SIGTERM)
            except ProcessLookupError:
                return
            except PermissionError:
                pass
            deadline = time.monotonic() + (0 if exited else self.termination_grace_seconds)
            while self._group_exists(group) and time.monotonic() < deadline:
                time.sleep(0.01)
            if self._group_exists(group):
                try:
                    os.killpg(group, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
        finally:
            process.wait()

    @staticmethod
    def _group_exists(group: int) -> bool:
        try:
            os.killpg(group, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    @staticmethod
    def _unregister_close(selector: selectors.BaseSelector, stream: object) -> None:
        try:
            selector.unregister(stream)
        except (KeyError, ValueError):
            pass
        CodexController._close(stream)

    @staticmethod
    def _close(*streams: object) -> None:
        for stream in streams:
            if stream is not None and not stream.closed:
                stream.close()

    @staticmethod
    def _outcome(parser: _JsonlParser, exit_code: int) -> ControllerOutcome:
        terminal, invalid = None, parser.invalid
        if not invalid and parser.terminal_text is not None:
            try:
                terminal = _envelope(parser.terminal_text)
            except ValueError:
                invalid = True
        elif not invalid and exit_code == 0:
            invalid = True
        if terminal is not None and parser.session_id is None:
            terminal, invalid = None, True
        provider = parser.provider_code
        if provider is None and exit_code != 0 and terminal is None and not invalid:
            provider = "unknown"
        if invalid:
            process_class, terminal = "invalid_envelope", None
        elif terminal is not None:
            process_class = (
                "failed" if terminal.claim == "completed" and exit_code != 0
                else terminal.claim
            )
        elif provider in {"auth", "quota", "provider_unavailable"}:
            process_class = "blocked"
        elif exit_code in {130, 143, -signal.SIGINT, -signal.SIGTERM}:
            process_class = "interrupted"
        else:
            process_class = "failed"
        return ControllerOutcome(
            parser.session_id, exit_code, process_class, terminal, provider,
        )
