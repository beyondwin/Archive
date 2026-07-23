from __future__ import annotations

import json
import hashlib
import math
import os
import secrets
import socket
import stat
import tempfile
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .contracts import canonical_json, require_digest, require_full_sha
from .evidence import EvidenceStore, ExactCommand
from .storage import StateStore


PROTOCOL_VERSION = 1
MAX_MESSAGE_BYTES = 262_144
_DETAIL_LIMIT = 512
_SOCKET_NAME = ".kws-plan-runner.sock"
_CLIENT_TIMEOUT_SECONDS = 15.0
_ENVELOPE_KEYS = {"protocol_version", "run_id", "nonce", "operation", "payload"}
_COMMAND_KEYS = {"command_id", "command_role", "argv", "cwd", "input_digest", "deadline_seconds"}


@dataclass(frozen=True)
class HelperDescriptor:
    protocol_version: int
    socket_path: Path
    nonce: str
    client_argv: tuple[str, ...]


def _bounded_detail(value: object) -> str:
    text = str(value).replace("\n", " ").replace("\r", " ").replace("\x00", " ")
    return text[:_DETAIL_LIMIT] or "request rejected"


def _error(code: str, detail: object) -> dict[str, object]:
    return {"ok": False, "error_code": code, "detail": _bounded_detail(detail)}


def _require_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _command(value: object, *, expected_role: str | None = None) -> ExactCommand:
    document = _require_mapping(value, "command")
    if set(document) != _COMMAND_KEYS or not isinstance(document["argv"], list):
        raise ValueError("command shape is invalid")
    command = ExactCommand(
        command_id=document["command_id"],
        command_role=document["command_role"],
        argv=tuple(document["argv"]),
        cwd=document["cwd"],
        input_digest=document["input_digest"],
        deadline_seconds=document["deadline_seconds"],
    )
    if expected_role is not None and command.command_role != expected_role:
        raise ValueError(f"command role must be {expected_role}")
    return command


def _candidate_head(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("candidate head is invalid")
    return require_full_sha(value)


class HelperServer:
    """Parent-owned, one-request Unix socket verification protocol."""

    def __init__(
        self,
        *,
        run_id: str,
        worktree: Path,
        evidence_store: EvidenceStore,
        client_argv: tuple[str, ...],
        state_store: StateStore | None = None,
        sealed_final_set_digest: str | None = None,
        sealed_candidate_head: str | None = None,
        io_timeout_seconds: float = _CLIENT_TIMEOUT_SECONDS,
        shutdown_timeout_seconds: float = _CLIENT_TIMEOUT_SECONDS,
    ) -> None:
        if not isinstance(run_id, str) or not run_id:
            raise ValueError("run ID is invalid")
        resolved = Path(worktree).absolute()
        if not resolved.is_dir() or resolved.is_symlink():
            raise ValueError("worktree must be a real directory")
        if not isinstance(client_argv, tuple) or not client_argv:
            raise ValueError("client argv is invalid")
        if any(
            not isinstance(item, str) or not item or "\x00" in item
            for item in client_argv
        ) or any(not Path(item).is_absolute() for item in client_argv[:2]):
            raise ValueError(
                "helper executable and script must be literal absolute paths"
            )
        if state_store is not None and state_store.snapshot().get("run_id") != run_id:
            raise ValueError("state store run ID does not match helper run ID")
        if (sealed_final_set_digest is None) != (sealed_candidate_head is None):
            raise ValueError("sealed finalization identity is incomplete")
        if sealed_final_set_digest is not None:
            require_digest(sealed_final_set_digest)
            require_full_sha(sealed_candidate_head)
        if not isinstance(io_timeout_seconds, (int, float)) or isinstance(io_timeout_seconds, bool) or not math.isfinite(io_timeout_seconds) or io_timeout_seconds <= 0:
            raise ValueError("helper I/O timeout must be finite and positive")
        if not isinstance(shutdown_timeout_seconds, (int, float)) or isinstance(shutdown_timeout_seconds, bool) or not math.isfinite(shutdown_timeout_seconds) or shutdown_timeout_seconds <= 0:
            raise ValueError("helper shutdown timeout must be finite and positive")
        self._run_id = run_id
        self._worktree = resolved
        self._evidence = evidence_store
        self._state = state_store
        direct_socket = resolved / _SOCKET_NAME
        self._socket_is_direct = len(os.fsencode(direct_socket)) < 100
        self._socket_path = (
            direct_socket
            if self._socket_is_direct
            else Path(tempfile.gettempdir())
            / (
                "kpr-"
                + hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()[:24]
                + ".sock"
            )
        )
        self._descriptor = HelperDescriptor(PROTOCOL_VERSION, self._socket_path, secrets.token_hex(32), client_argv)
        self._listener: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._running = threading.Event()
        self._dispatch_lock = threading.Lock()
        self._active_lock = threading.Lock()
        self._active_command_deadline: float | None = None
        self._final_set_digest = sealed_final_set_digest
        self._final_candidate_head = sealed_candidate_head
        self._io_timeout_seconds = float(io_timeout_seconds)
        self._shutdown_timeout_seconds = float(shutdown_timeout_seconds)

    @property
    def descriptor(self) -> HelperDescriptor:
        return self._descriptor

    @property
    def active_command_deadline(self) -> float | None:
        with self._active_lock:
            return self._active_command_deadline

    @property
    def server_thread(self) -> threading.Thread:
        if self._thread is None:
            raise RuntimeError("helper server is not running")
        return self._thread

    def __enter__(self) -> "HelperServer":
        if self._listener is not None:
            raise RuntimeError("helper server is already running")
        if self._socket_is_direct and self._socket_path.parent != self._worktree:
            raise ValueError("socket path must be a direct child of worktree")
        try:
            metadata = self._worktree.lstat()
        except OSError as error:
            raise ValueError("worktree is unavailable") from error
        if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
            raise ValueError("worktree must be a real directory")
        if self._socket_path.exists() or self._socket_path.is_symlink():
            raise ValueError("helper socket path already exists")
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            listener.bind(str(self._socket_path))
            os.chmod(self._socket_path, 0o600)
            listener.listen(8)
        except BaseException:
            listener.close()
            try:
                self._socket_path.unlink()
            except FileNotFoundError:
                pass
            raise
        self._listener = listener
        self._running.set()
        self._thread = threading.Thread(target=self._serve, name="kws-plan-runner-helper", daemon=False)
        self._thread.start()
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> bool:
        self._running.clear()
        listener, self._listener = self._listener, None
        if listener is not None:
            listener.close()
        thread = self._thread
        if thread is not None:
            thread.join(self._shutdown_timeout_seconds)
        try:
            self._socket_path.unlink()
        except FileNotFoundError:
            pass
        if thread is not None and thread.is_alive():
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
                connection.settimeout(self._io_timeout_seconds)
                response = self._handle_connection(connection)
                try:
                    connection.sendall(_encode(response))
                except OSError:
                    # A provider may disconnect after its bounded one-way request.
                    # Dispatch is parent-owned and must still complete exactly once.
                    pass

    def _handle_connection(self, connection: socket.socket) -> dict[str, object]:
        try:
            deadline = time.monotonic() + self._io_timeout_seconds
            raw = _read_line(connection, deadline=deadline, clock=time.monotonic)
            request = json.loads(raw.decode("utf-8"))
            if canonical_json(request) != raw:
                return _error("invalid_request", "request must use canonical JSON")
            if time.monotonic() >= deadline:
                return _error("request_timeout", "request timed out")
            return self._dispatch(request)
        except _ProtocolError as error:
            return _error(error.code, error.detail)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError):
            # Validation failures can originate below the protocol boundary;
            # never reflect their text because it may contain process details.
            return _error("invalid_request", "request validation failed")
        except Exception:
            return _error("internal_error", "parent verification helper failed")

    def _dispatch(self, value: object) -> dict[str, object]:
        request = _require_mapping(value, "request")
        if set(request) != _ENVELOPE_KEYS:
            raise _ProtocolError("invalid_request", "request envelope is invalid")
        if request["protocol_version"] != PROTOCOL_VERSION:
            raise _ProtocolError("unsupported_protocol", "protocol version is unsupported")
        if request["run_id"] != self._run_id or request["nonce"] != self._descriptor.nonce:
            raise _ProtocolError("forbidden", "run ID or nonce is invalid")
        operation = request["operation"]
        if not isinstance(operation, str):
            raise _ProtocolError("invalid_request", "operation is invalid")
        payload = _require_mapping(request["payload"], "payload")
        if operation == "verify_focused":
            return self._verify_focused(payload)
        if operation == "declare_final_set":
            return self._declare_final_set(payload)
        if operation == "verify_final":
            return self._verify_final(payload)
        if operation == "record_liveness":
            return self._record_liveness(payload)
        raise _ProtocolError("unknown_operation", "operation is not supported")

    def _execute(self, command: ExactCommand, candidate_head: str, operation: str) -> dict[str, object]:
        with self._dispatch_lock:
            with self._active_lock:
                self._active_command_deadline = time.monotonic() + command.deadline_seconds
            try:
                receipt = self._evidence.execute(command, candidate_head=candidate_head)
            finally:
                with self._active_lock:
                    self._active_command_deadline = None
        return {"ok": True, "operation": operation, "artifact": {"digest": receipt.artifact.digest}}

    def _verify_focused(self, payload: Mapping[str, object]) -> dict[str, object]:
        if set(payload) != {"candidate_head", "command"}:
            raise ValueError("focused verification payload is invalid")
        return self._execute(_command(payload["command"], expected_role="focused"), _candidate_head(payload["candidate_head"]), "verify_focused")

    def _declare_final_set(self, payload: Mapping[str, object]) -> dict[str, object]:
        if set(payload) != {"candidate_head", "final_set"}:
            raise ValueError("final-set declaration payload is invalid")
        candidate_head = _candidate_head(payload["candidate_head"])
        final_set = _require_mapping(payload["final_set"], "final set")
        if final_set.get("candidate_head") != candidate_head:
            raise ValueError("final set candidate head does not match request")
        with self._dispatch_lock:
            if self._final_set_digest is not None:
                raise _ProtocolError("final_set_sealed", "a final verification set is already sealed")
            artifact = self._evidence.declare_final_set(final_set, candidate_head)
            self._final_set_digest = artifact.digest
            self._final_candidate_head = candidate_head
        return {"ok": True, "operation": "declare_final_set", "artifact": {"digest": artifact.digest}}

    def _verify_final(self, payload: Mapping[str, object]) -> dict[str, object]:
        if set(payload) != {"candidate_head", "set_digest", "command_index"}:
            raise ValueError("final verification payload is invalid")
        candidate_head = _candidate_head(payload["candidate_head"])
        set_digest = require_digest(payload["set_digest"])
        index = payload["command_index"]
        if not isinstance(index, int) or isinstance(index, bool) or index < 0:
            raise ValueError("final command index is invalid")
        with self._dispatch_lock:
            if set_digest != self._final_set_digest:
                raise _ProtocolError("final_set_unavailable", "final verification set is not sealed by this helper")
            if candidate_head != self._final_candidate_head:
                raise _ProtocolError("candidate_head_mismatch", "candidate head does not match the sealed final verification set")
            command = self._evidence.load_final_command(set_digest, index)
        return self._execute(command, candidate_head, "verify_final")

    def _record_liveness(self, payload: Mapping[str, object]) -> dict[str, object]:
        if set(payload) != {"sample"} or not isinstance(payload["sample"], Mapping):
            raise ValueError("liveness payload is invalid")
        with self._dispatch_lock:
            self._evidence.record_liveness(dict(payload["sample"]))
        return {"ok": True, "operation": "record_liveness", "artifact": {}}


@dataclass(frozen=True)
class _ProtocolError(Exception):
    code: str
    detail: str


def _read_line(connection: socket.socket, *, deadline: float, clock: Any = time.monotonic) -> bytes:
    chunks: list[bytes] = []
    size = 0
    while True:
        remaining = deadline - clock()
        if remaining <= 0:
            raise _ProtocolError("request_timeout", "request timed out")
        connection.settimeout(remaining)
        try:
            block = connection.recv(min(8192, MAX_MESSAGE_BYTES + 1 - size))
        except TimeoutError as error:
            raise _ProtocolError("request_timeout", "request timed out") from error
        if not block:
            raise _ProtocolError("invalid_request", "request must contain one newline-terminated JSON value")
        size += len(block)
        if size > MAX_MESSAGE_BYTES:
            raise _ProtocolError("request_too_large", "request exceeds byte limit")
        chunks.append(block)
        joined = b"".join(chunks)
        newline = joined.find(b"\n")
        if newline >= 0:
            if newline != len(joined) - 1:
                raise _ProtocolError("invalid_request", "request must contain exactly one JSON line")
            # The provider is required to half-close after its single request.
            # Waiting for EOF avoids responding before that shutdown reaches the
            # peer, which keeps the client-side shutdown deterministic.
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
            return joined[:-1]


def _encode(response: Mapping[str, object]) -> bytes:
    encoded = canonical_json(dict(response)) + b"\n"
    if len(encoded) > MAX_MESSAGE_BYTES:
        return b'{"detail":"response exceeds byte limit","error_code":"response_too_large","ok":false}\n'
    return encoded


def helper_client(socket_path: Path, nonce: str, request: Mapping[str, object]) -> dict[str, object]:
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
            client.settimeout(_CLIENT_TIMEOUT_SECONDS)
            client.connect(str(path))
            client.sendall(encoded)
            client.shutdown(socket.SHUT_WR)
            raw = _read_line(
                client,
                deadline=time.monotonic() + _CLIENT_TIMEOUT_SECONDS,
                clock=time.monotonic,
            )
    except (OSError, _ProtocolError) as error:
        raise RuntimeError(_bounded_detail(error)) from None
    try:
        response = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError("helper response is invalid") from error
    if not isinstance(response, dict) or not isinstance(response.get("ok"), bool):
        raise RuntimeError("helper response is invalid")
    if not response["ok"]:
        raise RuntimeError(_bounded_detail(response.get("error_code", "helper request failed")))
    return response
