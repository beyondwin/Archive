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
    "format_version", "contract_version", "run_id", "source_repository",
    "base_commit", "branch", "worktree", "documents", "superpowers_skill",
    "git_identity", "sandbox", "approval_policy", "integration_policy",
    "remote_action_policy", "created_at",
}
_STATE_KEYS = {
    "status", "controller_session_id", "controller_generation",
    "fresh_fallback_used", "active_pid", "active_process_group",
    "last_observed_head", "tracked_clean", "untracked_present", "status_digest",
    "last_process_class", "last_exit_code", "resume_capsule", "blocker",
    "updated_at",
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
    order: int
    source_path: str
    snapshot_path: str
    sha256: str
    byte_length: int

    def to_payload(self) -> dict[str, object]:
        return {
            "order": self.order,
            "source_path": self.source_path,
            "snapshot_path": self.snapshot_path,
            "sha256": self.sha256,
            "byte_length": self.byte_length,
        }


@dataclass(frozen=True)
class GitIdentity:
    author_name: str
    author_email: str
    committer_name: str
    committer_email: str

    def to_payload(self) -> dict[str, str]:
        values = {
            "author_name": self.author_name,
            "author_email": self.author_email,
            "committer_name": self.committer_name,
            "committer_email": self.committer_email,
        }
        for name, value in values.items():
            _require_utf8_bytes(value, maximum=256, minimum=1, name=f"Git identity {name}")
        return values


@dataclass(frozen=True)
class RunManifest:
    format_version: int
    contract_version: int
    run_id: str
    source_repository: str
    base_commit: str
    branch: str
    worktree: str
    documents: tuple[DocumentRecord, ...]
    superpowers_skill: str
    git_identity: GitIdentity
    sandbox: str
    approval_policy: str
    integration_policy: str
    remote_action_policy: str
    created_at: str

    def to_payload(self) -> dict[str, object]:
        payload = {
            "format_version": self.format_version,
            "contract_version": self.contract_version,
            "run_id": self.run_id,
            "source_repository": self.source_repository,
            "base_commit": self.base_commit,
            "branch": self.branch,
            "worktree": self.worktree,
            "documents": [record.to_payload() for record in self.documents],
            "superpowers_skill": self.superpowers_skill,
            "git_identity": self.git_identity.to_payload(),
            "sandbox": self.sandbox,
            "approval_policy": self.approval_policy,
            "integration_policy": self.integration_policy,
            "remote_action_policy": self.remote_action_policy,
            "created_at": self.created_at,
        }
        RunStore.validate_manifest_payload(payload)
        return payload


@dataclass(frozen=True)
class RunState:
    status: str
    controller_session_id: str | None
    controller_generation: int
    fresh_fallback_used: bool
    active_pid: int | None
    active_process_group: int | None
    last_observed_head: str
    tracked_clean: bool
    untracked_present: bool
    status_digest: str
    last_process_class: str | None
    last_exit_code: int | None
    resume_capsule: Mapping[str, object] | None
    blocker: Mapping[str, object] | None
    updated_at: str

    def to_payload(self) -> dict[str, object]:
        payload = {
            "status": self.status,
            "controller_session_id": self.controller_session_id,
            "controller_generation": self.controller_generation,
            "fresh_fallback_used": self.fresh_fallback_used,
            "active_pid": self.active_pid,
            "active_process_group": self.active_process_group,
            "last_observed_head": self.last_observed_head,
            "tracked_clean": self.tracked_clean,
            "untracked_present": self.untracked_present,
            "status_digest": self.status_digest,
            "last_process_class": self.last_process_class,
            "last_exit_code": self.last_exit_code,
            "resume_capsule": (
                None if self.resume_capsule is None
                else dict(self.resume_capsule)
            ),
            "blocker": None if self.blocker is None else dict(self.blocker),
            "updated_at": self.updated_at,
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
                order=ordinal,
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

    def __init__(self, path: Path, *, shared: bool = False) -> None:
        self.path = path
        self.shared = shared
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
        operation = fcntl.LOCK_SH if self.shared else fcntl.LOCK_EX
        fcntl.flock(self.descriptor, operation | fcntl.LOCK_NB)
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
    def validate_manifest_payload(payload: object) -> dict[str, object]:
        if not isinstance(payload, dict) or set(payload) != _MANIFEST_KEYS:
            raise ValueError("format-5 manifest is invalid")
        if payload["format_version"] != FORMAT_VERSION or payload["contract_version"] != CONTRACT_VERSION:
            raise ValueError("format-5 manifest is invalid")
        run_id = payload["run_id"]
        if not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id):
            raise ValueError("format-5 manifest is invalid")
        for name in ("source_repository", "worktree"):
            value = payload[name]
            if not isinstance(value, str) or not Path(value).is_absolute():
                raise ValueError("format-5 manifest is invalid")
        if not isinstance(payload["base_commit"], str) or not SHA40.fullmatch(payload["base_commit"]):
            raise ValueError("format-5 manifest is invalid")
        if payload["sandbox"] not in SANDBOXES or payload["superpowers_skill"] not in SUPERPOWERS_SKILLS:
            raise ValueError("format-5 manifest is invalid")
        for name in (
            "branch", "approval_policy", "integration_policy", "remote_action_policy", "created_at",
        ):
            _require_utf8_bytes(payload[name], maximum=512, minimum=1, name="format-5 manifest")
        identity = payload["git_identity"]
        if not isinstance(identity, dict) or set(identity) != {
            "author_name", "author_email", "committer_name", "committer_email",
        }:
            raise ValueError("format-5 manifest is invalid")
        GitIdentity(**identity).to_payload()
        documents = payload["documents"]
        if not isinstance(documents, list) or not documents:
            raise ValueError("format-5 manifest is invalid")
        expected_order = 1
        for record in documents:
            if not isinstance(record, dict) or set(record) != {
                "order", "source_path", "snapshot_path", "sha256", "byte_length",
            }:
                raise ValueError("format-5 manifest is invalid")
            order = record["order"]
            if not isinstance(order, int) or isinstance(order, bool) or order != expected_order:
                raise ValueError("format-5 manifest is invalid")
            expected_order += 1
            for name in ("source_path", "snapshot_path"):
                value = record[name]
                if not isinstance(value, str) or not Path(value).is_absolute():
                    raise ValueError("format-5 manifest is invalid")
            if not isinstance(record["sha256"], str) or not SHA256.fullmatch(record["sha256"]):
                raise ValueError("format-5 manifest is invalid")
            size = record["byte_length"]
            if not isinstance(size, int) or isinstance(size, bool) or size < 0:
                raise ValueError("format-5 manifest is invalid")
        return dict(payload)

    @staticmethod
    def validate_state_payload(payload: object) -> dict[str, object]:
        if not isinstance(payload, dict) or set(payload) != _STATE_KEYS:
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
        for name in ("active_pid", "active_process_group"):
            value = payload[name]
            if value is not None and (
                not isinstance(value, int) or isinstance(value, bool) or value <= 0
            ):
                raise ValueError("format-5 state is invalid")
        if not isinstance(payload["last_observed_head"], str) or not SHA40.fullmatch(payload["last_observed_head"]):
            raise ValueError("format-5 state is invalid")
        if not isinstance(payload["status_digest"], str) or not SHA256.fullmatch(payload["status_digest"]):
            raise ValueError("format-5 state is invalid")
        if not isinstance(payload["tracked_clean"], bool) or not isinstance(payload["untracked_present"], bool):
            raise ValueError("format-5 state is invalid")
        for name in ("controller_session_id", "last_process_class"):
            value = payload[name]
            if value is not None:
                _require_utf8_bytes(value, maximum=512, minimum=1, name="format-5 state")
        exit_code = payload["last_exit_code"]
        if exit_code is not None and (not isinstance(exit_code, int) or isinstance(exit_code, bool)):
            raise ValueError("format-5 state is invalid")
        capsule = payload["resume_capsule"]
        if capsule is not None:
            validate_resume_capsule(capsule)
        blocker = payload["blocker"]
        if blocker is not None and not isinstance(blocker, Mapping):
            raise ValueError("format-5 state is invalid")
        _require_utf8_bytes(payload["updated_at"], maximum=128, minimum=1, name="format-5 state")
        return dict(payload)

    @classmethod
    def _run_root(cls, codex_home: Path, run_id: str) -> Path:
        if not isinstance(codex_home, Path) or not RUN_ID.fullmatch(run_id):
            raise ValueError("format-5 run identity is invalid")
        return codex_home.resolve() / "cpe-v3" / "runs" / run_id

    @classmethod
    def _validate_document_snapshots(cls, run_root: Path, manifest: RunManifest) -> None:
        inputs = run_root / "inputs"
        if inputs.is_symlink() or not inputs.is_dir():
            raise ValueError("prepared run root must contain only input snapshots")
        snapshots = {Path(record.snapshot_path) for record in manifest.documents}
        actual_snapshots = set(inputs.iterdir())
        if (
            not snapshots
            or snapshots != actual_snapshots
            or any(snapshot.parent != inputs for snapshot in snapshots)
            or any(not stat.S_ISREG(entry.lstat().st_mode) for entry in actual_snapshots)
        ):
            raise ValueError("manifest documents do not match input snapshots")
        for record in manifest.documents:
            snapshot = Path(record.snapshot_path)
            payload = snapshot.read_bytes()
            if hashlib.sha256(payload).hexdigest() != record.sha256 or len(payload) != record.byte_length:
                raise ValueError("manifest snapshot digest is invalid")

    @classmethod
    def create(cls, codex_home: Path, manifest: RunManifest, state: RunState) -> "RunStore":
        run_root = cls._run_root(codex_home, manifest.run_id)
        if run_root.is_symlink() or not run_root.is_dir() or run_root.parent.is_symlink():
            raise ValueError("prepared run root is invalid")
        run_root = run_root.resolve(strict=True)
        _private_directory(run_root)
        if set(run_root.iterdir()) != {run_root / "inputs"}:
            raise ValueError("prepared run root must contain only input snapshots")
        manifest_payload = manifest.to_payload()
        state_payload = state.to_payload()
        cls._validate_document_snapshots(run_root, manifest)
        store = cls(run_root, manifest, state)
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

    @classmethod
    def open(cls, codex_home: Path, run_id: str) -> "RunStore":
        run_root = cls._run_root(codex_home, run_id)
        if run_root.is_symlink() or not run_root.is_dir():
            raise ValueError("format-5 run root is unavailable")
        run_root = run_root.resolve(strict=True)
        try:
            manifest_payload = json.loads((run_root / "manifest.json").read_text(encoding="utf-8"))
            state_payload = json.loads((run_root / "state.json").read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("format-5 run state is unavailable") from exc
        manifest = cls._manifest_from_payload(cls.validate_manifest_payload(manifest_payload))
        if manifest.run_id != run_id:
            raise ValueError("format-5 run identity is invalid")
        state = cls._state_from_payload(cls.validate_state_payload(state_payload))
        cls._validate_document_snapshots(run_root, manifest)
        return cls(run_root, manifest, state)

    @staticmethod
    def _manifest_from_payload(payload: Mapping[str, object]) -> RunManifest:
        records = tuple(
            DocumentRecord(
                order=record["order"],
                source_path=record["source_path"],
                snapshot_path=record["snapshot_path"],
                sha256=record["sha256"],
                byte_length=record["byte_length"],
            )
            for record in payload["documents"]
        )
        identity = payload["git_identity"]
        return RunManifest(
            format_version=payload["format_version"],
            contract_version=payload["contract_version"],
            run_id=payload["run_id"],
            source_repository=payload["source_repository"],
            base_commit=payload["base_commit"],
            branch=payload["branch"],
            worktree=payload["worktree"],
            documents=records,
            superpowers_skill=payload["superpowers_skill"],
            git_identity=GitIdentity(**identity),
            sandbox=payload["sandbox"],
            approval_policy=payload["approval_policy"],
            integration_policy=payload["integration_policy"],
            remote_action_policy=payload["remote_action_policy"],
            created_at=payload["created_at"],
        )

    @staticmethod
    def _state_from_payload(payload: Mapping[str, object]) -> RunState:
        return RunState(
            status=payload["status"],
            controller_session_id=payload["controller_session_id"],
            controller_generation=payload["controller_generation"],
            fresh_fallback_used=payload["fresh_fallback_used"],
            active_pid=payload["active_pid"],
            active_process_group=payload["active_process_group"],
            last_observed_head=payload["last_observed_head"],
            tracked_clean=payload["tracked_clean"],
            untracked_present=payload["untracked_present"],
            status_digest=payload["status_digest"],
            last_process_class=payload["last_process_class"],
            last_exit_code=payload["last_exit_code"],
            resume_capsule=payload["resume_capsule"],
            blocker=payload["blocker"],
            updated_at=payload["updated_at"],
        )

    def save_state(self, state: RunState) -> None:
        payload = state.to_payload()
        atomic_private_write(
            self.state_path,
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"),
            0o600,
        )
        self.state = state

    def write_handoff(self, payload: Mapping[str, object]) -> Path:
        if not isinstance(payload, Mapping):
            raise ValueError("handoff is invalid")
        atomic_private_write(
            self.handoff_path,
            json.dumps(dict(payload), sort_keys=True, separators=(",", ":")).encode("utf-8"),
            0o600,
        )
        return self.handoff_path

    def lock(self, shared: bool = False) -> RunLock:
        return RunLock(self.lock_path, shared=shared)
