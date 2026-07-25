from __future__ import annotations

import hashlib
import json
import math
import os
import secrets
import socket
import stat
import tempfile
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from .contracts import canonical_json, require_digest, require_full_sha
from .evidence import EvidenceStore, ExactCommand
from .storage import StateStore

PROTOCOL_VERSION = 1
MAX_MESSAGE_BYTES = 262_144
_IO_TIMEOUT = 15.0
_DETAIL_LIMIT = 512
_ENVELOPE = {"protocol_version", "run_id", "nonce", "operation", "payload"}
_COMMAND = {
    "command_id", "command_role", "argv", "cwd", "input_digest", "deadline_seconds"
}


@dataclass(frozen=True)
class HelperDescriptor:
    protocol_version: int
    socket_path: Path
    nonce: str
    client_argv: tuple[str, ...]


@dataclass(frozen=True)
class _ProtocolError(Exception):
    code: str
    detail: str


def _safe_detail(value: object) -> str:
    flattened = str(value).replace("\n", " ").replace("\r", " ").replace("\0", " ")
    return flattened[:_DETAIL_LIMIT] or "request rejected"


def _failure(code: str, detail: object) -> dict[str, object]:
    return {"ok": False, "error_code": code, "detail": _safe_detail(detail)}


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _exact_command(value: object, role: str | None = None) -> ExactCommand:
    document = _mapping(value, "command")
    if set(document) != _COMMAND or not isinstance(document["argv"], list):
        raise ValueError("command shape is invalid")
    command = ExactCommand(
        document["command_id"],
        document["command_role"],
        tuple(document["argv"]),
        document["cwd"],
        document["input_digest"],
        document["deadline_seconds"],
    )
    if role is not None and command.command_role != role:
        raise ValueError(f"command role must be {role}")
    return command


def _head(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("candidate head is invalid")
    return require_full_sha(value)


def _read_one_line(
    connection: socket.socket,
    *,
    deadline: float,
    clock: Callable[[], float] = time.monotonic,
) -> bytes:
    accumulated = bytearray()
    while True:
        remaining = deadline - clock()
        if remaining <= 0:
            raise _ProtocolError("request_timeout", "request timed out")
        connection.settimeout(remaining)
        try:
            block = connection.recv(min(8192, MAX_MESSAGE_BYTES + 1 - len(accumulated)))
        except TimeoutError as error:
            raise _ProtocolError("request_timeout", "request timed out") from error
        if not block:
            raise _ProtocolError(
                "invalid_request", "request must contain one newline-terminated JSON value"
            )
        accumulated.extend(block)
        if len(accumulated) > MAX_MESSAGE_BYTES:
            raise _ProtocolError("request_too_large", "request exceeds byte limit")
        if b"\n" not in block:
            continue
        newline = accumulated.find(b"\n")
        if newline != len(accumulated) - 1:
            raise _ProtocolError("invalid_request", "request must contain exactly one JSON line")
        remaining = deadline - clock()
        if remaining <= 0:
            raise _ProtocolError("request_timeout", "request timed out")
        connection.settimeout(remaining)
        try:
            trailing = connection.recv(1)
        except TimeoutError as error:
            raise _ProtocolError("request_timeout", "request timed out") from error
        if trailing:
            raise _ProtocolError("invalid_request", "request must contain exactly one JSON line")
        return bytes(accumulated[:-1])


def _wire(value: Mapping[str, object]) -> bytes:
    encoded = canonical_json(dict(value)) + b"\n"
    if len(encoded) > MAX_MESSAGE_BYTES:
        return (
            b'{"detail":"response exceeds byte limit","error_code":'
            b'"response_too_large","ok":false}\n'
        )
    return encoded


class HelperServer:
    def __init__(
        self,
        *,
        run_id: str,
        worktree: Path,
        evidence_store: EvidenceStore,
        client_argv: tuple[str, ...],
        state_store: StateStore | None = None,
        on_command_started: Callable[[float], None] | None = None,
        on_command_finished: Callable[[float], None] | None = None,
        io_timeout_seconds: float = _IO_TIMEOUT,
        shutdown_timeout_seconds: float = _IO_TIMEOUT,
    ) -> None:
        if not isinstance(run_id, str) or not run_id:
            raise ValueError("run ID is invalid")
        worktree = Path(worktree).absolute()
        if not worktree.is_dir() or worktree.is_symlink():
            raise ValueError("worktree must be a real directory")
        if (
            not isinstance(client_argv, tuple)
            or not client_argv
            or any(not isinstance(item, str) or not item or "\0" in item for item in client_argv)
            or any(not Path(item).is_absolute() for item in client_argv[:2])
        ):
            raise ValueError("helper executable and script must be literal absolute paths")
        if state_store is not None and state_store.snapshot().get("run_id") != run_id:
            raise ValueError("state store run ID does not match helper run ID")
        for value, label in (
            (io_timeout_seconds, "helper I/O timeout"),
            (shutdown_timeout_seconds, "helper shutdown timeout"),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{label} must be finite and positive")
        direct = worktree / ".kws-plan-runner.sock"
        direct_usable = len(os.fsencode(direct)) < 100
        socket_path = (
            direct
            if direct_usable
            else Path(tempfile.gettempdir())
            / f"kpr-{hashlib.sha256(str(worktree).encode()).hexdigest()[:24]}.sock"
        )
        self._run_id = run_id
        self._worktree = worktree
        self._evidence = evidence_store
        self._state = state_store
        self._direct = direct_usable
        self._descriptor = HelperDescriptor(
            PROTOCOL_VERSION, socket_path, secrets.token_hex(32), client_argv
        )
        self._listener: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._running = threading.Event()
        self._operation_lock = threading.Lock()
        self._active_lock = threading.Lock()
        self._active_deadline: float | None = None
        self._verification_digest: str | None = None
        self._verification_head: str | None = None
        self._on_started = on_command_started
        self._on_finished = on_command_finished
        self._io_timeout = float(io_timeout_seconds)
        self._shutdown_timeout = float(shutdown_timeout_seconds)

    @property
    def descriptor(self) -> HelperDescriptor:
        return self._descriptor

    @property
    def active_command_deadline(self) -> float | None:
        with self._active_lock:
            return self._active_deadline

    @property
    def server_thread(self) -> threading.Thread:
        if self._thread is None:
            raise RuntimeError("helper server is not running")
        return self._thread

    def __enter__(self) -> "HelperServer":
        if self._listener is not None:
            raise RuntimeError("helper server is already running")
        metadata = self._worktree.lstat()
        if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
            raise ValueError("worktree must be a real directory")
        path = self._descriptor.socket_path
        if self._direct and path.parent != self._worktree:
            raise ValueError("socket path must be a direct child of worktree")
        if path.exists() or path.is_symlink():
            raise ValueError("helper socket path already exists")
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            listener.bind(str(path))
            os.chmod(path, 0o600)
            listener.listen(8)
        except BaseException:
            listener.close()
            path.unlink(missing_ok=True)
            raise
        self._listener = listener
        self._running.set()
        self._thread = threading.Thread(
            target=self._serve, name="claude-plan-runner-helper", daemon=False
        )
        self._thread.start()
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> bool:
        self._running.clear()
        listener, self._listener = self._listener, None
        if listener:
            listener.close()
        thread = self._thread
        if thread:
            deadline = self.active_command_deadline
            remaining = max(0.0, deadline - time.monotonic()) + 1 if deadline else 0
            thread.join(max(self._shutdown_timeout, remaining))
        self._descriptor.socket_path.unlink(missing_ok=True)
        if thread and thread.is_alive():
            raise RuntimeError("helper server shutdown timed out")
        return False

    def _serve(self) -> None:
        while self._running.is_set():
            listener = self._listener
            if listener is None:
                return
            try:
                connection, _ = listener.accept()
            except OSError:
                return
            with connection:
                response = self._handle(connection)
                try:
                    connection.sendall(_wire(response))
                except OSError:
                    pass

    def _handle(self, connection: socket.socket) -> dict[str, object]:
        try:
            deadline = time.monotonic() + self._io_timeout
            raw = _read_one_line(connection, deadline=deadline)
            request = json.loads(raw.decode("utf-8"))
            if raw != canonical_json(request):
                return _failure("invalid_request", "request must use canonical JSON")
            if time.monotonic() >= deadline:
                return _failure("request_timeout", "request timed out")
            return self._dispatch(request)
        except _ProtocolError as error:
            return _failure(error.code, error.detail)
        except (UnicodeError, json.JSONDecodeError, ValueError, TypeError):
            return _failure("invalid_request", "request validation failed")
        except Exception:
            return _failure("internal_error", "parent verification helper failed")

    def _dispatch(self, value: object) -> dict[str, object]:
        request = _mapping(value, "request")
        if set(request) != _ENVELOPE:
            raise _ProtocolError("invalid_request", "request envelope is invalid")
        if request["protocol_version"] != PROTOCOL_VERSION:
            raise _ProtocolError("unsupported_protocol", "protocol version is unsupported")
        if request["run_id"] != self._run_id or request["nonce"] != self._descriptor.nonce:
            raise _ProtocolError("forbidden", "run ID or nonce is invalid")
        payload = _mapping(request["payload"], "payload")
        operation = request["operation"]
        if operation == "declare_verification":
            return self._declare_verification(payload)
        if operation == "run_verification":
            return self._run_verification(payload)
        if operation == "record_liveness":
            return self._liveness(payload)
        raise _ProtocolError("unknown_operation", "operation is not supported")

    def _execute(self, command: ExactCommand, candidate_head: str, operation: str) -> dict[str, object]:
        with self._operation_lock:
            command_deadline = time.monotonic() + command.deadline_seconds
            with self._active_lock:
                self._active_deadline = command_deadline
            if self._on_started:
                self._on_started(command_deadline)
            try:
                receipt = self._evidence.execute(command, candidate_head=candidate_head)
            finally:
                with self._active_lock:
                    self._active_deadline = None
                if self._on_finished:
                    self._on_finished(time.monotonic())
        return {
            "ok": True,
            "operation": operation,
            "artifact": {"digest": receipt.artifact.digest},
        }

    def _declare_verification(
        self,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        required = {
            "candidate_head",
            "plan_index",
            "verification",
            "prior_set_digests",
            "is_final_plan",
        }
        if set(payload) != required:
            raise ValueError("verification declaration payload is invalid")
        candidate = _head(payload["candidate_head"])
        plan_index = payload["plan_index"]
        prior = payload["prior_set_digests"]
        is_final = payload["is_final_plan"]
        if (
            isinstance(plan_index, bool)
            or not isinstance(plan_index, int)
            or plan_index < 0
            or not isinstance(prior, list)
            or any(not isinstance(item, str) for item in prior)
            or not isinstance(is_final, bool)
        ):
            raise ValueError("verification declaration identity is invalid")
        for digest in prior:
            require_digest(digest)
        verification = _mapping(
            payload["verification"],
            "verification",
        )
        with self._operation_lock:
            if self._verification_digest is not None:
                raise _ProtocolError(
                    "verification_set_sealed",
                    "a verification set is already sealed",
                )
            artifact = self._evidence.declare_verification(
                verification,
                candidate,
                plan_index=plan_index,
                prior_set_digests=prior,
                is_final_plan=is_final,
            )
            self._verification_digest = artifact.digest
            self._verification_head = candidate
        return {
            "ok": True,
            "operation": "declare_verification",
            "artifact": {"digest": artifact.digest},
        }

    def _run_verification(
        self,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        required = {"candidate_head", "set_digest", "command_index", "deadline_seconds"}
        if set(payload) != required:
            raise ValueError("verification execution payload is invalid")
        candidate = _head(payload["candidate_head"])
        digest = require_digest(payload["set_digest"])
        index = payload["command_index"]
        if isinstance(index, bool) or not isinstance(index, int) or index < 0:
            raise ValueError("verification command index is invalid")
        with self._operation_lock:
            if digest != self._verification_digest:
                raise _ProtocolError(
                    "verification_set_unavailable",
                    "verification set is not sealed by this helper",
                )
            if candidate != self._verification_head:
                raise _ProtocolError("candidate_head_mismatch", "candidate head does not match sealed set")
            command = self._evidence.load_verification_command(digest, index)
            supplied = payload["deadline_seconds"]
            if isinstance(supplied, bool) or not isinstance(supplied, (int, float)) or float(supplied) != float(command.deadline_seconds):
                raise ValueError("verification command deadline does not match sealed command")
        return self._execute(command, candidate, "run_verification")

    def _liveness(self, payload: Mapping[str, object]) -> dict[str, object]:
        if set(payload) != {"sample"} or not isinstance(payload["sample"], Mapping):
            raise ValueError("liveness payload is invalid")
        with self._operation_lock:
            self._evidence.record_liveness(dict(payload["sample"]))
        return {"ok": True, "operation": "record_liveness", "artifact": {}}


def _response_timeout(request: Mapping[str, object]) -> float:
    payload = request.get("payload")
    deadline = None
    if isinstance(payload, Mapping):
        if request.get("operation") == "run_verification":
            deadline = payload.get("deadline_seconds")
    if isinstance(deadline, (int, float)) and not isinstance(deadline, bool) and math.isfinite(deadline) and deadline > 0:
        return float(deadline) + _IO_TIMEOUT
    return _IO_TIMEOUT


def helper_client(
    socket_path: Path,
    nonce: str,
    request: Mapping[str, object],
) -> dict[str, object]:
    path = Path(socket_path)
    if not path.is_absolute() or not isinstance(nonce, str) or len(nonce) != 64:
        raise RuntimeError("helper client arguments are invalid")
    if not isinstance(request, Mapping) or request.get("nonce") != nonce:
        raise RuntimeError("helper request nonce is invalid")
    encoded = canonical_json(dict(request)) + b"\n"
    if len(encoded) > MAX_MESSAGE_BYTES:
        raise RuntimeError("helper request exceeds byte limit")
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(_IO_TIMEOUT)
            client.connect(str(path))
            client.sendall(encoded)
            client.shutdown(socket.SHUT_WR)
            raw = _read_one_line(
                client, deadline=time.monotonic() + _response_timeout(request)
            )
    except (OSError, _ProtocolError) as error:
        raise RuntimeError(_safe_detail(error)) from None
    try:
        response = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError("helper response is invalid") from error
    if not isinstance(response, dict) or not isinstance(response.get("ok"), bool):
        raise RuntimeError("helper response is invalid")
    if not response["ok"]:
        raise RuntimeError(_safe_detail(response.get("error_code", "helper request failed")))
    return response
