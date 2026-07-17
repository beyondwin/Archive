"""Deterministic, same-run verification receipts for CPE child workflows."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Mapping

from .launcher import _terminate_group
from .state import atomic_private_write


MAX_VERIFICATION_LOG_BYTES = 1 * 1024 * 1024
MAX_REQUIRED_ARTIFACTS = 64
_PHASES = {"task", "affected", "branch_final", "merged_main"}
_MUTABLE_POLICIES = {"immutable", "digest_complete", "always_execute"}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class VerificationRequest:
    run_id: str
    command_id: str
    argv: tuple[str, ...]
    cwd: Path
    head: str
    environment_fingerprint: str
    phase: Literal["task", "affected", "branch_final", "merged_main"]
    input_digest: str
    deterministic: bool
    mutable_input_policy: Literal[
        "immutable", "digest_complete", "always_execute"
    ]
    required_artifact_paths: tuple[str, ...]
    timeout_seconds: int


@dataclass(frozen=True)
class VerificationReceipt:
    schema_version: int
    receipt_id: str
    run_id: str
    cache_key: str
    request: Mapping[str, object]
    status: Literal["passed", "failed", "timed_out", "interrupted"]
    exit_code: int | None
    started_at: str
    finished_at: str
    stdout_path: str
    stderr_path: str
    stdout_digest: str
    stderr_digest: str
    artifacts: tuple[Mapping[str, object], ...]


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _request_document(request: VerificationRequest) -> dict[str, object]:
    return {
        "run_id": request.run_id,
        "command_id": request.command_id,
        "argv": list(request.argv),
        "cwd": str(request.cwd.resolve(strict=True)),
        "head": request.head,
        "environment_fingerprint": request.environment_fingerprint,
        "phase": request.phase,
        "input_digest": request.input_digest,
        "deterministic": request.deterministic,
        "mutable_input_policy": request.mutable_input_policy,
        "required_artifact_paths": list(request.required_artifact_paths),
        "timeout_seconds": request.timeout_seconds,
    }


def _validate_request(request: VerificationRequest) -> None:
    if not request.run_id or not request.command_id:
        raise ValueError("verification identifiers must be non-empty")
    if (
        not isinstance(request.argv, tuple)
        or not request.argv
        or any(not isinstance(item, str) or not item for item in request.argv)
    ):
        raise ValueError("verification argv must be a non-empty string tuple")
    if request.phase not in _PHASES:
        raise ValueError("verification phase is invalid")
    if request.mutable_input_policy not in _MUTABLE_POLICIES:
        raise ValueError("mutable input policy is invalid")
    if request.mutable_input_policy == "digest_complete" and (
        not _SHA256.fullmatch(request.input_digest)
        or request.input_digest == "0" * 64
    ):
        raise ValueError(
            "digest-complete verification requires a non-placeholder input digest"
        )
    if not isinstance(request.deterministic, bool):
        raise ValueError("deterministic must be boolean")
    if isinstance(request.timeout_seconds, bool) or request.timeout_seconds <= 0:
        raise ValueError("verification timeout must be positive")
    if len(request.required_artifact_paths) > MAX_REQUIRED_ARTIFACTS:
        raise ValueError("too many required verification artifacts")


def verification_cache_key(request: VerificationRequest) -> str:
    """Return the approved eight-part content key; run identity is separate."""
    _validate_request(request)
    payload = {
        "schema_version": 1,
        "command_id": request.command_id,
        "argv_digest": _sha256_bytes(
            json.dumps(list(request.argv), separators=(",", ":")).encode("utf-8")
        ),
        "cwd": str(request.cwd.resolve(strict=True)),
        "head": request.head,
        "environment_fingerprint": request.environment_fingerprint,
        "phase": request.phase,
        "input_digest": request.input_digest,
        "mutable_input_policy": request.mutable_input_policy,
    }
    return _sha256_bytes(_canonical_json(payload))


def _reject_symlink_components(path: Path, stop: Path) -> None:
    stop_resolved = stop.resolve(strict=True)
    candidate = path.absolute()
    try:
        relative = candidate.relative_to(stop_resolved)
    except ValueError as exc:
        raise ValueError("verification path escapes its worktree") from exc
    current = stop_resolved
    for component in relative.parts:
        current = current / component
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(metadata.st_mode):
            raise ValueError("verification path contains a symlink")


def _prepare_layout(evidence_root: Path, cwd: Path) -> tuple[Path, Path, Path]:
    absolute_root = evidence_root.absolute()
    if len(absolute_root.parents) < 3 or absolute_root.parts[-3:] != (
        ".superpowers",
        "sdd",
        "verification",
    ):
        raise ValueError("evidence root must be .superpowers/sdd/verification")
    lexical_worktree = absolute_root.parents[2]
    worktree_resolved = lexical_worktree.resolve(strict=True)
    normalized_root = worktree_resolved / ".superpowers" / "sdd" / "verification"
    _reject_symlink_components(normalized_root, worktree_resolved)
    for directory in (
        worktree_resolved / ".superpowers",
        worktree_resolved / ".superpowers" / "sdd",
        normalized_root,
    ):
        directory.mkdir(mode=0o700, exist_ok=True)
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError("verification directory is unsafe")
    root_resolved = normalized_root.resolve(strict=True)
    try:
        cwd_relative = cwd.absolute().relative_to(lexical_worktree)
    except ValueError:
        cwd_relative = cwd.resolve(strict=True).relative_to(worktree_resolved)
    normalized_cwd = worktree_resolved / cwd_relative
    _reject_symlink_components(normalized_cwd, worktree_resolved)
    cwd_resolved = normalized_cwd.resolve(strict=True)
    try:
        cwd_resolved.relative_to(worktree_resolved)
    except ValueError as exc:
        raise ValueError("verification cwd is outside the active worktree") from exc
    return root_resolved, worktree_resolved, cwd_resolved


def _safe_relative_file(root: Path, relative: str, expected_parent: str) -> Path:
    candidate_relative = Path(relative)
    if (
        candidate_relative.is_absolute()
        or ".." in candidate_relative.parts
        or not candidate_relative.parts
        or candidate_relative.parts[0] != expected_parent
    ):
        raise ValueError("receipt references an unsafe evidence path")
    candidate = root / candidate_relative
    _reject_symlink_components(candidate, root)
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("receipt evidence escapes its root") from exc
    metadata = candidate.lstat()
    if candidate.is_symlink() or not stat.S_ISREG(metadata.st_mode):
        raise ValueError("receipt evidence is not a regular file")
    return resolved


def _artifact_record(worktree: Path, relative: str) -> dict[str, object]:
    candidate_relative = Path(relative)
    if (
        candidate_relative.is_absolute()
        or not candidate_relative.parts
        or ".." in candidate_relative.parts
    ):
        raise ValueError("required artifact path is unsafe")
    candidate = worktree / candidate_relative
    _reject_symlink_components(candidate, worktree)
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(worktree)
    except ValueError as exc:
        raise ValueError("required artifact escapes the worktree") from exc
    metadata = candidate.lstat()
    if candidate.is_symlink() or not stat.S_ISREG(metadata.st_mode):
        raise ValueError("required artifact must be a regular file")
    return {
        "path": candidate_relative.as_posix(),
        "bytes": metadata.st_size,
        "sha256": _sha256_file(resolved),
    }


def _bounded_output(stream: object) -> bytes:
    stream.seek(0, os.SEEK_END)  # type: ignore[attr-defined]
    size = stream.tell()  # type: ignore[attr-defined]
    if size <= MAX_VERIFICATION_LOG_BYTES:
        stream.seek(0)  # type: ignore[attr-defined]
        return stream.read()  # type: ignore[attr-defined,no-any-return]
    marker = (
        f"[cpe verification log truncated; discarded_bytes={size - MAX_VERIFICATION_LOG_BYTES}]\n"
    ).encode("ascii")
    retained = MAX_VERIFICATION_LOG_BYTES - len(marker)
    stream.seek(size - retained)  # type: ignore[attr-defined]
    return marker + stream.read(retained)  # type: ignore[attr-defined,no-any-return]


def _receipt_from_document(document: Mapping[str, object]) -> VerificationReceipt:
    artifacts = document.get("artifacts")
    request = document.get("request")
    if not isinstance(artifacts, list) or not isinstance(request, dict):
        raise ValueError("verification receipt shape is invalid")
    return VerificationReceipt(
        schema_version=int(document["schema_version"]),
        receipt_id=str(document["receipt_id"]),
        run_id=str(document["run_id"]),
        cache_key=str(document["cache_key"]),
        request=request,
        status=str(document["status"]),  # type: ignore[arg-type]
        exit_code=document["exit_code"] if isinstance(document["exit_code"], int) else None,
        started_at=str(document["started_at"]),
        finished_at=str(document["finished_at"]),
        stdout_path=str(document["stdout_path"]),
        stderr_path=str(document["stderr_path"]),
        stdout_digest=str(document["stdout_digest"]),
        stderr_digest=str(document["stderr_digest"]),
        artifacts=tuple(item for item in artifacts if isinstance(item, dict)),
    )


def execute_verification(
    evidence_root: Path,
    request: VerificationRequest,
) -> VerificationReceipt:
    """Execute an argv without a shell and atomically publish immutable evidence."""
    _validate_request(request)
    root, worktree, cwd = _prepare_layout(evidence_root, request.cwd)
    cache_key = verification_cache_key(request)
    execution_id = uuid.uuid4().hex
    started_at = _iso_now()
    started = time.monotonic()
    status_name: Literal["passed", "failed", "timed_out", "interrupted"]
    exit_code: int | None = None
    with tempfile.TemporaryFile() as stdout_stream, tempfile.TemporaryFile() as stderr_stream:
        process = subprocess.Popen(
            list(request.argv),
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=stdout_stream,
            stderr=stderr_stream,
            shell=False,
            start_new_session=True,
        )
        try:
            exit_code = process.wait(timeout=request.timeout_seconds)
            status_name = "passed" if exit_code == 0 else "failed"
        except subprocess.TimeoutExpired:
            _terminate_group(process, 0.1)
            status_name = "timed_out"
        except KeyboardInterrupt:
            _terminate_group(process, 0.1)
            status_name = "interrupted"
        stdout_payload = _bounded_output(stdout_stream)
        stderr_payload = _bounded_output(stderr_stream)

    logs = root / "logs"
    logs.mkdir(mode=0o700, exist_ok=True)
    stdout_path = logs / f"{execution_id}.stdout.log"
    stderr_path = logs / f"{execution_id}.stderr.log"
    atomic_private_write(stdout_path, stdout_payload, mode=0o400)
    atomic_private_write(stderr_path, stderr_payload, mode=0o400)

    artifacts: list[dict[str, object]] = []
    if status_name == "passed":
        artifacts = [
            _artifact_record(worktree, path)
            for path in request.required_artifact_paths
        ]
    finished_at = _iso_now()
    receipt_document: dict[str, object] = {
        "schema_version": 1,
        "run_id": request.run_id,
        "cache_key": cache_key,
        "request": _request_document(request),
        "status": status_name,
        "exit_code": exit_code,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_ms": max(0, round((time.monotonic() - started) * 1000)),
        "stdout_path": stdout_path.relative_to(root).as_posix(),
        "stderr_path": stderr_path.relative_to(root).as_posix(),
        "stdout_digest": _sha256_bytes(stdout_payload),
        "stderr_digest": _sha256_bytes(stderr_payload),
        "artifacts": artifacts,
        "source": "child_attested",
        "evidence_root_digest": _sha256_bytes(str(root).encode("utf-8")),
    }
    receipt_id = _sha256_bytes(_canonical_json(receipt_document))
    receipt_document["receipt_id"] = receipt_id
    receipt_path = root / "receipts" / f"{receipt_id}.json"
    atomic_private_write(receipt_path, _canonical_json(receipt_document), mode=0o400)

    if (
        status_name == "passed"
        and request.deterministic
        and request.mutable_input_policy != "always_execute"
    ):
        index_document = {
            "schema_version": 1,
            "cache_key": cache_key,
            "receipt_path": receipt_path.relative_to(root).as_posix(),
            "evidence_root_digest": receipt_document["evidence_root_digest"],
        }
        atomic_private_write(
            root / "indexes" / f"{cache_key}.json",
            _canonical_json(index_document),
            mode=0o400,
        )
    return _receipt_from_document(receipt_document)


def _corruption_event(root: Path, cache_key: str, reason_code: str) -> None:
    payload = _canonical_json(
        {
            "schema_version": 1,
            "event": "verification.receipt_corrupt",
            "cache_key": cache_key,
            "reason_code": reason_code,
        }
    ) + b"\n"
    target = root / "corruption-events.jsonl"
    if target.exists() and (target.is_symlink() or not target.is_file()):
        return
    descriptor = os.open(
        target,
        os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _load_json(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("not_regular")
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("not_object")
    return document


def validate_recorded_receipt_path(
    evidence_root: Path,
    request: VerificationRequest,
    receipt_reference: str,
) -> VerificationReceipt | None:
    """Validate the exact immutable receipt named by one ledger event."""
    _validate_request(request)
    root, worktree, _cwd = _prepare_layout(evidence_root, request.cwd)
    cache_key = verification_cache_key(request)
    try:
        root_digest = _sha256_bytes(str(root).encode("utf-8"))
        receipt_path = _safe_relative_file(
            root, receipt_reference, "receipts"
        )
        document = _load_json(receipt_path)
        receipt_id = document.get("receipt_id")
        unsigned = dict(document)
        unsigned.pop("receipt_id", None)
        if (
            document.get("schema_version") != 1
            or not isinstance(receipt_id, str)
            or _sha256_bytes(_canonical_json(unsigned)) != receipt_id
            or receipt_path.name != f"{receipt_id}.json"
            or document.get("cache_key") != cache_key
            or document.get("run_id") != request.run_id
            or document.get("evidence_root_digest") != root_digest
            or document.get("source") != "child_attested"
            or document.get("status") != "passed"
            or document.get("request") != _request_document(request)
        ):
            raise ValueError("invalid_receipt")
        stdout = _safe_relative_file(root, str(document.get("stdout_path")), "logs")
        stderr = _safe_relative_file(root, str(document.get("stderr_path")), "logs")
        if (
            _sha256_file(stdout) != document.get("stdout_digest")
            or _sha256_file(stderr) != document.get("stderr_digest")
        ):
            raise ValueError("log_digest_mismatch")
        artifact_documents = document.get("artifacts")
        if not isinstance(artifact_documents, list):
            raise ValueError("invalid_artifacts")
        try:
            current_artifacts = [
                _artifact_record(worktree, path)
                for path in request.required_artifact_paths
            ]
        except (OSError, ValueError):
            return None
        if artifact_documents != current_artifacts:
            return None
        return _receipt_from_document(document)
    except (KeyError, OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        _corruption_event(root, cache_key, "invalid_receipt_evidence")
        return None


def validate_recorded_receipt(
    evidence_root: Path,
    request: VerificationRequest,
) -> VerificationReceipt | None:
    """Validate the current indexed receipt without changing its reuse policy."""
    _validate_request(request)
    root, _worktree, _cwd = _prepare_layout(evidence_root, request.cwd)
    cache_key = verification_cache_key(request)
    index_path = root / "indexes" / f"{cache_key}.json"
    if not index_path.exists():
        return None
    try:
        index = _load_json(index_path)
        root_digest = _sha256_bytes(str(root).encode("utf-8"))
        if (
            index.get("schema_version") != 1
            or index.get("cache_key") != cache_key
            or index.get("evidence_root_digest") != root_digest
            or not isinstance(index.get("receipt_path"), str)
        ):
            raise ValueError("invalid_index")
        return validate_recorded_receipt_path(
            evidence_root, request, str(index["receipt_path"])
        )
    except (KeyError, OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        _corruption_event(root, cache_key, "invalid_receipt_index")
        return None


def find_reusable_receipt(
    evidence_root: Path,
    request: VerificationRequest,
) -> VerificationReceipt | None:
    """Return a strict successful reusable receipt, or ``None`` on any miss."""
    _validate_request(request)
    if not request.deterministic or request.mutable_input_policy == "always_execute":
        return None
    return validate_recorded_receipt(evidence_root, request)


def _regular_source(path: Path) -> Path:
    if not path.is_absolute() or path.is_symlink():
        raise ValueError("verification helper requires an absolute regular source")
    try:
        resolved = path.resolve(strict=True)
        metadata = path.lstat()
    except OSError as exc:
        raise ValueError("verification helper requires an absolute regular source") from exc
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError("verification helper requires an absolute regular source")
    return resolved


def materialize_helper_descriptor(run_root: Path, cpe_script: Path) -> Path:
    """Publish the read-only helper argv and bind it to exact source digests."""
    cpe_source = _regular_source(cpe_script)
    verification_source = _regular_source(
        cpe_source.parent / "cpe_runtime" / "verification.py"
    )
    descriptor = {
        "schema_version": 1,
        "argv_prefix": ["python3", str(cpe_source), "verify"],
        "source_digests": {
            "cpe.py": _sha256_file(cpe_source),
            "cpe_runtime/verification.py": _sha256_file(verification_source),
        },
    }
    encoded = _canonical_json(descriptor)
    path = run_root / "tools" / "run-and-record.json"
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file():
            raise ValueError("verification helper descriptor is not regular")
        try:
            current = path.read_bytes()
        except OSError as exc:
            raise ValueError("verification helper descriptor is unreadable") from exc
        if current != encoded or stat.S_IMODE(path.stat().st_mode) != 0o400:
            raise ValueError("verification helper descriptor was replaced")
        return path
    atomic_private_write(path, encoded, mode=0o400)
    return path
