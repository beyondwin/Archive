"""Private format-5 state and opaque input snapshots for CPE."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


FORMAT_VERSION = 5
CONTRACT_VERSION = 3
SUPERPOWERS_SKILLS = ("subagent-driven-development", "executing-plans")
SANDBOXES = ("workspace-write", "danger-full-access")
STATUSES = ("prepared", "running", "interrupted", "blocked", "failed", "handed_off")
RUN_ID = re.compile(r"^cpe-[0-9a-f]{16}$")
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
MAX_RESUME_NOTE_BYTES = 2048
MAX_EVIDENCE_REFS = 16

_MANIFEST_KEYS = {
    "format_version", "contract_version", "run_id", "git", "documents",
    "superpowers_skills", "sandbox",
}
_STATE_KEYS = {
    "format_version", "contract_version", "run_id", "status",
    "controller_generation", "fresh_fallback_used",
}


def _require_utf8_bytes(value: object, *, maximum: int, name: str, minimum: int = 0) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} is invalid")
    try:
        length = len(value.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise ValueError(f"{name} is invalid") from exc
    if not minimum <= length <= maximum:
        raise ValueError(f"{name} is invalid")
    return value


def _write_all(descriptor: int, payload: bytes) -> None:
    remaining = memoryview(payload)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            raise OSError("short write while persisting format-5 state")
        remaining = remaining[written:]


def _private_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink() or not path.is_dir():
        raise ValueError("private run directory is invalid")
    path.chmod(0o700)


def atomic_private_write(path: Path, payload: bytes, mode: int = 0o600) -> None:
    """Atomically write one private regular file beside its destination."""

    if path.parent.is_symlink() or not path.parent.is_dir():
        raise ValueError("private artifact parent is invalid")
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    descriptor: int | None = None
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            mode,
        )
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("private artifact must be a regular file")
        _write_all(descriptor, payload)
        os.fchmod(descriptor, mode)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        os.replace(temporary, path)
        directory_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _inside(path: Path, parent: Path, name: str) -> Path:
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(parent.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise ValueError(f"{name} is outside the private run root") from exc
    return resolved


@dataclass(frozen=True)
class DocumentSource:
    path: Path


@dataclass(frozen=True)
class DocumentRecord:
    source_path: str
    snapshot_path: str
    sha256: str
    byte_length: int

    def to_payload(self) -> dict[str, object]:
        return {
            "source_path": self.source_path,
            "snapshot_path": self.snapshot_path,
            "sha256": self.sha256,
            "byte_length": self.byte_length,
        }


@dataclass(frozen=True)
class GitIdentity:
    head_commit: str
    worktree_status_digest: str

    def to_payload(self) -> dict[str, str]:
        if not SHA40.fullmatch(self.head_commit) or not SHA256.fullmatch(self.worktree_status_digest):
            raise ValueError("Git identity is invalid")
        return {
            "head_commit": self.head_commit,
            "worktree_status_digest": self.worktree_status_digest,
        }


@dataclass(frozen=True)
class RunManifest:
    run_id: str
    git: GitIdentity
    documents: tuple[DocumentRecord, ...]
    superpowers_skills: tuple[str, ...]
    sandbox: str

    def to_payload(self) -> dict[str, object]:
        if not RUN_ID.fullmatch(self.run_id):
            raise ValueError("format-5 manifest is invalid")
        if not self.documents or not all(isinstance(record, DocumentRecord) for record in self.documents):
            raise ValueError("format-5 manifest is invalid")
        if self.superpowers_skills != SUPERPOWERS_SKILLS or self.sandbox not in SANDBOXES:
            raise ValueError("format-5 manifest is invalid")
        return {
            "format_version": FORMAT_VERSION,
            "contract_version": CONTRACT_VERSION,
            "run_id": self.run_id,
            "git": self.git.to_payload(),
            "documents": [record.to_payload() for record in self.documents],
            "superpowers_skills": list(self.superpowers_skills),
            "sandbox": self.sandbox,
        }


@dataclass(frozen=True)
class RunState:
    run_id: str
    status: str
    controller_generation: int
    fresh_fallback_used: bool

    def to_payload(self) -> dict[str, object]:
        payload = {
            "format_version": FORMAT_VERSION,
            "contract_version": CONTRACT_VERSION,
            "run_id": self.run_id,
            "status": self.status,
            "controller_generation": self.controller_generation,
            "fresh_fallback_used": self.fresh_fallback_used,
        }
        RunStore.validate_state_payload(payload)
        return payload


def _open_source(path: Path) -> tuple[tuple[int, int], bytes]:
    if not path.is_absolute() or path.is_symlink():
        raise ValueError("input paths must be absolute regular files")
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise ValueError(f"input is not a readable regular file: {path}") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError(f"input is not a regular file: {path}")
        with os.fdopen(descriptor, "rb", closefd=True) as source:
            descriptor = -1
            return (metadata.st_dev, metadata.st_ino), source.read()
    finally:
        if descriptor != -1:
            os.close(descriptor)


def snapshot_documents(*, run_root: Path, sources: Sequence[DocumentSource]) -> tuple[DocumentRecord, ...]:
    """Copy opaque absolute regular files once into global-order snapshots."""

    if not sources:
        raise ValueError("at least one input document is required")
    if run_root.exists() and (run_root.is_symlink() or not run_root.is_dir()):
        raise ValueError("private run directory is invalid")
    _private_directory(run_root)
    inputs = run_root / "inputs"
    _private_directory(inputs)
    if any(run_root.iterdir()) and any(child != inputs for child in run_root.iterdir()):
        raise ValueError("prepared run root contains non-input artifacts")
    if any(inputs.iterdir()):
        raise ValueError("input snapshots already exist")

    records: list[DocumentRecord] = []
    identities: set[tuple[int, int]] = set()
    for ordinal, declared in enumerate(sources, start=1):
        if not isinstance(declared, DocumentSource) or not isinstance(declared.path, Path):
            raise ValueError("input source is invalid")
        identity, payload = _open_source(declared.path)
        if identity in identities:
            raise ValueError("duplicate input file identity")
        identities.add(identity)
        snapshot = inputs / f"document-{ordinal:03d}-{declared.path.name}"
        atomic_private_write(snapshot, payload)
        records.append(
            DocumentRecord(
                source_path=str(declared.path.resolve(strict=True)),
                snapshot_path=str(snapshot.resolve(strict=True)),
                sha256=hashlib.sha256(payload).hexdigest(),
                byte_length=len(payload),
            )
        )
    return tuple(records)


def validate_resume_capsule(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != {
        "head_commit", "worktree_status_digest", "note", "evidence_refs",
    }:
        raise ValueError("resume capsule is invalid")
    head_commit = value["head_commit"]
    digest = value["worktree_status_digest"]
    if not isinstance(head_commit, str) or not SHA40.fullmatch(head_commit):
        raise ValueError("resume capsule is invalid")
    if not isinstance(digest, str) or not SHA256.fullmatch(digest):
        raise ValueError("resume capsule is invalid")
    note = _require_utf8_bytes(value["note"], maximum=MAX_RESUME_NOTE_BYTES, name="resume capsule")
    evidence_refs = value["evidence_refs"]
    if not isinstance(evidence_refs, list) or len(evidence_refs) > MAX_EVIDENCE_REFS:
        raise ValueError("resume capsule is invalid")
    normalized_refs = [
        _require_utf8_bytes(reference, maximum=512, minimum=1, name="resume capsule")
        for reference in evidence_refs
    ]
    return {
        "head_commit": head_commit,
        "worktree_status_digest": digest,
        "note": note,
        "evidence_refs": normalized_refs,
    }


class RunLock:
    """An advisory exclusive writer lock that children may inherit."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.descriptor: int | None = None

    def __enter__(self) -> "RunLock":
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.descriptor = os.open(
            self.path,
            os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        if not stat.S_ISREG(os.fstat(self.descriptor).st_mode):
            os.close(self.descriptor)
            self.descriptor = None
            raise ValueError("run lock must be a regular file")
        os.fchmod(self.descriptor, 0o600)
        fcntl.flock(self.descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return self

    def fileno(self) -> int:
        if self.descriptor is None:
            raise RuntimeError("run lock is not held")
        return self.descriptor

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self.descriptor is not None:
            fcntl.flock(self.descriptor, fcntl.LOCK_UN)
            os.close(self.descriptor)
            self.descriptor = None


class RunStore:
    """Own the minimal mutable state beside an immutable format-5 manifest."""

    def __init__(self, root: Path, manifest: RunManifest, state: RunState) -> None:
        self.root = root
        self.manifest = manifest
        self.state = state
        self.manifest_path = root / "manifest.json"
        self.state_path = root / "state.json"
        self.lock_path = root / "run.lock"
        self.handoff_path = root / "handoff.json"

    @staticmethod
    def validate_state_payload(payload: object) -> dict[str, object]:
        if not isinstance(payload, dict) or set(payload) != _STATE_KEYS:
            raise ValueError("format-5 state is invalid")
        if payload["format_version"] != FORMAT_VERSION or payload["contract_version"] != CONTRACT_VERSION:
            raise ValueError("format-5 state is invalid")
        run_id = payload["run_id"]
        if not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id):
            raise ValueError("format-5 state is invalid")
        if payload["status"] not in STATUSES:
            raise ValueError("format-5 state is invalid")
        generation = payload["controller_generation"]
        fallback = payload["fresh_fallback_used"]
        if (
            not isinstance(generation, int)
            or isinstance(generation, bool)
            or generation not in (0, 1)
            or not isinstance(fallback, bool)
            or fallback != (generation == 1)
        ):
            raise ValueError("format-5 state is invalid")
        return dict(payload)

    @classmethod
    def create(cls, *, run_root: Path, manifest: RunManifest, state: RunState) -> "RunStore":
        if run_root.is_symlink() or not run_root.is_dir() or run_root.parent.is_symlink():
            raise ValueError("prepared run root is invalid")
        _private_directory(run_root)
        inputs = run_root / "inputs"
        if inputs.is_symlink() or not inputs.is_dir() or set(run_root.iterdir()) != {inputs}:
            raise ValueError("prepared run root must contain only input snapshots")
        manifest_payload = manifest.to_payload()
        state_payload = state.to_payload()
        if manifest.run_id != state.run_id:
            raise ValueError("format-5 run identity is invalid")
        snapshots = {Path(record.snapshot_path).resolve(strict=True) for record in manifest.documents}
        actual_snapshots = {entry.resolve(strict=True) for entry in inputs.iterdir()}
        if not snapshots or snapshots != actual_snapshots:
            raise ValueError("manifest documents do not match input snapshots")
        for record in manifest.documents:
            snapshot = Path(record.snapshot_path).resolve(strict=True)
            if snapshot.is_symlink() or not snapshot.is_file() or _inside(snapshot, inputs, "snapshot") != snapshot:
                raise ValueError("manifest snapshot is invalid")
            payload = snapshot.read_bytes()
            if hashlib.sha256(payload).hexdigest() != record.sha256 or len(payload) != record.byte_length:
                raise ValueError("manifest snapshot digest is invalid")
        store = cls(run_root.resolve(strict=True), manifest, state)
        atomic_private_write(
            store.manifest_path,
            json.dumps(manifest_payload, sort_keys=True, separators=(",", ":")).encode("utf-8"),
            0o400,
        )
        atomic_private_write(
            store.state_path,
            json.dumps(state_payload, sort_keys=True, separators=(",", ":")).encode("utf-8"),
            0o600,
        )
        return store

    def save_state(self, state: RunState) -> None:
        if state.run_id != self.manifest.run_id:
            raise ValueError("format-5 run identity is invalid")
        payload = state.to_payload()
        atomic_private_write(
            self.state_path,
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"),
            0o600,
        )
        self.state = state

    def write_handoff(self, payload: Mapping[str, object]) -> None:
        if not isinstance(payload, Mapping):
            raise ValueError("handoff is invalid")
        atomic_private_write(
            self.handoff_path,
            json.dumps(dict(payload), sort_keys=True, separators=(",", ":")).encode("utf-8"),
            0o600,
        )
