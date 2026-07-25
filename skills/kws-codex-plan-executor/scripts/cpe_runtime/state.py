"""Private format-5 state and opaque input snapshots for CPE."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
import uuid
from dataclasses import dataclass, fields
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
_MAX_PERSISTED_JSON_BYTES = 16 * 1024 * 1024
_MAX_LEGACY_STATE_BYTES = 64 * 1024
_MANIFEST_ERROR = "format-5 manifest is invalid"
_STATE_ERROR = "format-5 state is invalid"
_RESUME_ERROR = "resume capsule is invalid"
_UNAVAILABLE_ERROR = "format-5 run state is unavailable"
_LEGACY_ERROR = "legacy run state is unavailable"
_RESUME_KEYS = ("head_commit", "worktree_status_digest", "note", "evidence_refs")
def _require(condition: bool, error: str) -> None:
    if not condition:
        raise ValueError(error)
def _names(model: object) -> tuple[str, ...]:
    return tuple(field.name for field in fields(model))
def _payload(record: object) -> dict[str, object]:
    return {field.name: getattr(record, field.name) for field in fields(record)}
def _exact(value: object, names: Sequence[str], error: str, *, mapping: bool = False) -> dict[str, object]:
    expected_type = Mapping if mapping else dict
    _require(isinstance(value, expected_type) and set(value) == set(names), error)
    return dict(value)
def _matches(value: object, pattern: re.Pattern[str]) -> bool:
    return isinstance(value, str) and pattern.fullmatch(value) is not None
def _integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)
def _require_utf8_bytes(value: object, *, maximum: int, name: str, minimum: int = 0) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} is invalid")
    try:
        length = len(value.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise ValueError(f"{name} is invalid") from exc
    _require(minimum <= length <= maximum, f"{name} is invalid")
    return value
def _json_bytes(payload: Mapping[str, object]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
def _read_private_json(path: Path, maximum: int = _MAX_PERSISTED_JSON_BYTES,
                       error: str = _UNAVAILABLE_ERROR) -> object:
    no_follow = getattr(os, "O_NOFOLLOW", None)
    _require(isinstance(no_follow, int) and no_follow != 0, _UNAVAILABLE_ERROR)
    descriptor: int | None = None
    try:
        descriptor = os.open(path, os.O_RDONLY | no_follow | os.O_NONBLOCK)
        metadata = os.fstat(descriptor)
        _require(
            stat.S_ISREG(metadata.st_mode)
            and metadata.st_size <= maximum,
            error,
        )
        with os.fdopen(descriptor, "rb", closefd=True) as stream:
            descriptor = None
            payload = stream.read(maximum + 1)
        _require(len(payload) <= maximum, error)
        return json.loads(payload.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError(error) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
def read_legacy_format(codex_home: Path, run_id: str) -> tuple[int, Path]:
    """Read only the root version from the exact bounded legacy state path."""
    _require(isinstance(codex_home, Path) and _matches(run_id, RUN_ID), _LEGACY_ERROR)
    root = codex_home.resolve() / "orchestrator" / run_id
    payload = _read_private_json(root / "state.json", _MAX_LEGACY_STATE_BYTES, _LEGACY_ERROR)
    _require(isinstance(payload, dict), _LEGACY_ERROR)
    version = payload.get("format_version")
    _require(_integer(version) and version in (1, 2, 3, 4), _LEGACY_ERROR)
    return version, root
def _write_all(descriptor: int, payload: bytes) -> None:
    remaining = memoryview(payload)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            raise OSError("short write while persisting format-5 state")
        remaining = remaining[written:]
def _private_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    _require(not path.is_symlink() and path.is_dir(), "private run directory is invalid")
    path.chmod(0o700)
def atomic_private_write(path: Path, payload: bytes, mode: int = 0o600) -> None:
    """Atomically write one private regular file beside its destination."""
    _require(not path.parent.is_symlink() and path.parent.is_dir(), "private artifact parent is invalid")
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    descriptor: int | None = None
    try:
        descriptor = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), mode,
        )
        _require(stat.S_ISREG(os.fstat(descriptor).st_mode), "private artifact must be a regular file")
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
@dataclass(frozen=True)
class DocumentSource:
    path: Path
@dataclass(frozen=True)
class DocumentRecord:
    order: int; source_path: str; snapshot_path: str
    sha256: str; byte_length: int

    def to_payload(self) -> dict[str, object]:
        return _payload(self)
@dataclass(frozen=True)
class GitIdentity:
    author_name: str; author_email: str
    committer_name: str; committer_email: str

    def to_payload(self) -> dict[str, object]:
        values = _payload(self)
        for name, value in values.items():
            _require_utf8_bytes(value, maximum=256, minimum=1, name=f"Git identity {name}")
        return values
@dataclass(frozen=True)
class RunManifest:
    format_version: int; contract_version: int; run_id: str
    source_repository: str; base_commit: str; branch: str; worktree: str
    documents: tuple[DocumentRecord, ...]; superpowers_skill: str
    git_identity: GitIdentity; sandbox: str; approval_policy: str
    integration_policy: str; remote_action_policy: str; created_at: str

    def to_payload(self) -> dict[str, object]:
        payload = _payload(self)
        payload["documents"] = [record.to_payload() for record in self.documents]
        payload["git_identity"] = self.git_identity.to_payload()
        RunStore.validate_manifest_payload(payload)
        return payload
@dataclass(frozen=True)
class RunState:
    status: str; controller_session_id: str | None; controller_generation: int
    fresh_fallback_used: bool; active_pid: int | None
    active_process_group: int | None; last_observed_head: str
    tracked_clean: bool; untracked_present: bool; status_digest: str
    last_process_class: str | None; last_exit_code: int | None
    resume_capsule: Mapping[str, object] | None
    blocker: Mapping[str, object] | None; updated_at: str

    def to_payload(self) -> dict[str, object]:
        payload = _payload(self)
        for name in ("resume_capsule", "blocker"):
            if payload[name] is not None:
                payload[name] = dict(payload[name])
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
    _require(bool(sources), "at least one input document is required")
    _require(not run_root.exists() or (not run_root.is_symlink() and run_root.is_dir()), "private run directory is invalid")
    _private_directory(run_root)
    inputs = run_root / "inputs"
    _private_directory(inputs)
    _require(set(run_root.iterdir()) == {inputs}, "prepared run root contains non-input artifacts")
    _require(not any(inputs.iterdir()), "input snapshots already exist")
    records: list[DocumentRecord] = []
    identities: set[tuple[int, int]] = set()
    for ordinal, declared in enumerate(sources, start=1):
        _require(isinstance(declared, DocumentSource) and isinstance(declared.path, Path), "input source is invalid")
        identity, payload = _open_source(declared.path)
        _require(identity not in identities, "duplicate input file identity")
        identities.add(identity)
        snapshot = inputs / f"document-{ordinal:03d}-{declared.path.name}"
        atomic_private_write(snapshot, payload)
        records.append(DocumentRecord(
            ordinal, str(declared.path.resolve(strict=True)), str(snapshot.resolve(strict=True)),
            hashlib.sha256(payload).hexdigest(), len(payload),
        ))
    return tuple(records)
def validate_resume_capsule(value: object) -> dict[str, object]:
    payload = _exact(value, _RESUME_KEYS, _RESUME_ERROR, mapping=True)
    _require(_matches(payload["head_commit"], SHA40), _RESUME_ERROR)
    _require(_matches(payload["worktree_status_digest"], SHA256), _RESUME_ERROR)
    note = _require_utf8_bytes(payload["note"], maximum=MAX_RESUME_NOTE_BYTES, name="resume capsule")
    references = payload["evidence_refs"]
    _require(isinstance(references, list) and len(references) <= MAX_EVIDENCE_REFS, _RESUME_ERROR)
    normalized_refs = [
        _require_utf8_bytes(reference, maximum=512, minimum=1, name="resume capsule")
        for reference in references
    ]
    return dict(head_commit=payload["head_commit"], worktree_status_digest=payload["worktree_status_digest"],
                note=note, evidence_refs=normalized_refs)
class RunLock:
    """An advisory exclusive writer lock that children may inherit."""
    def __init__(self, path: Path, *, shared: bool = False) -> None:
        self.path, self.shared, self.descriptor = path, shared, None
    def __enter__(self) -> "RunLock":
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor = os.open(self.path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        self.descriptor = descriptor
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise ValueError("run lock must be a regular file")
            os.fchmod(descriptor, 0o600)
            operation = fcntl.LOCK_SH if self.shared else fcntl.LOCK_EX
            fcntl.flock(descriptor, operation | fcntl.LOCK_NB)
        except BaseException:
            try:
                os.close(descriptor)
            finally:
                self.descriptor = None
            raise
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
    """Own mutable state beside an immutable format-5 manifest."""
    def __init__(self, root: Path, manifest: RunManifest, state: RunState) -> None:
        self.root, self.manifest, self.state = root, manifest, state
        self.manifest_path = root / "manifest.json"
        self.state_path = root / "state.json"
        self.lock_path = root / "run.lock"
        self.handoff_path = root / "handoff.json"
    @staticmethod
    def validate_manifest_payload(payload: object) -> dict[str, object]:
        data = _exact(payload, _names(RunManifest), _MANIFEST_ERROR)
        _require(data["format_version"] == FORMAT_VERSION and data["contract_version"] == CONTRACT_VERSION, _MANIFEST_ERROR)
        _require(_matches(data["run_id"], RUN_ID), _MANIFEST_ERROR)
        for name in ("source_repository", "worktree"):
            _require(isinstance(data[name], str) and Path(data[name]).is_absolute(), _MANIFEST_ERROR)
        _require(_matches(data["base_commit"], SHA40), _MANIFEST_ERROR)
        _require(data["sandbox"] in SANDBOXES and data["superpowers_skill"] in SUPERPOWERS_SKILLS, _MANIFEST_ERROR)
        for name in ("branch", "approval_policy", "integration_policy", "remote_action_policy", "created_at"):
            _require_utf8_bytes(data[name], maximum=512, minimum=1, name="format-5 manifest")
        identity = _exact(data["git_identity"], _names(GitIdentity), _MANIFEST_ERROR)
        GitIdentity(**identity).to_payload()
        documents = data["documents"]
        _require(isinstance(documents, list) and bool(documents), _MANIFEST_ERROR)
        for expected_order, value in enumerate(documents, start=1):
            record = _exact(value, _names(DocumentRecord), _MANIFEST_ERROR)
            _require(_integer(record["order"]) and record["order"] == expected_order, _MANIFEST_ERROR)
            for name in ("source_path", "snapshot_path"):
                _require(isinstance(record[name], str) and Path(record[name]).is_absolute(), _MANIFEST_ERROR)
            _require(_matches(record["sha256"], SHA256), _MANIFEST_ERROR)
            _require(_integer(record["byte_length"]) and record["byte_length"] >= 0, _MANIFEST_ERROR)
        return data
    @staticmethod
    def validate_state_payload(payload: object) -> dict[str, object]:
        data = _exact(payload, _names(RunState), _STATE_ERROR)
        _require(data["status"] in STATUSES, _STATE_ERROR)
        generation, fallback = data["controller_generation"], data["fresh_fallback_used"]
        _require(_integer(generation) and generation in (0, 1) and isinstance(fallback, bool)
                 and fallback == (generation == 1), _STATE_ERROR)
        for name in ("active_pid", "active_process_group"):
            value = data[name]
            _require(value is None or (_integer(value) and value > 0), _STATE_ERROR)
        _require(_matches(data["last_observed_head"], SHA40), _STATE_ERROR)
        _require(_matches(data["status_digest"], SHA256), _STATE_ERROR)
        _require(isinstance(data["tracked_clean"], bool) and isinstance(data["untracked_present"], bool), _STATE_ERROR)
        for name in ("controller_session_id", "last_process_class"):
            if data[name] is not None:
                _require_utf8_bytes(data[name], maximum=512, minimum=1, name="format-5 state")
        exit_code = data["last_exit_code"]
        _require(exit_code is None or _integer(exit_code), _STATE_ERROR)
        if data["resume_capsule"] is not None:
            validate_resume_capsule(data["resume_capsule"])
        _require(data["blocker"] is None or isinstance(data["blocker"], Mapping), _STATE_ERROR)
        _require_utf8_bytes(data["updated_at"], maximum=128, minimum=1, name="format-5 state")
        return data
    @classmethod
    def _run_root(cls, codex_home: Path, run_id: str) -> Path:
        _require(isinstance(codex_home, Path) and _matches(run_id, RUN_ID), "format-5 run identity is invalid")
        return codex_home.resolve() / "cpe-v3" / "runs" / run_id
    @classmethod
    def _validate_document_snapshots(cls, run_root: Path, manifest: RunManifest) -> None:
        inputs = run_root / "inputs"
        _require(not inputs.is_symlink() and inputs.is_dir(), "prepared run root must contain only input snapshots")
        snapshots = {Path(record.snapshot_path) for record in manifest.documents}
        actual_snapshots = set(inputs.iterdir())
        _require(bool(snapshots) and snapshots == actual_snapshots
                 and all(snapshot.parent == inputs for snapshot in snapshots)
                 and all(stat.S_ISREG(entry.lstat().st_mode) for entry in actual_snapshots),
                 "manifest documents do not match input snapshots")
        for record in manifest.documents:
            payload = Path(record.snapshot_path).read_bytes()
            _require(hashlib.sha256(payload).hexdigest() == record.sha256
                     and len(payload) == record.byte_length, "manifest snapshot digest is invalid")
    @classmethod
    def create(cls, codex_home: Path, manifest: RunManifest, state: RunState) -> "RunStore":
        run_root = cls._run_root(codex_home, manifest.run_id)
        _require(not run_root.is_symlink() and run_root.is_dir() and not run_root.parent.is_symlink(),
                 "prepared run root is invalid")
        run_root = run_root.resolve(strict=True)
        _private_directory(run_root)
        _require(set(run_root.iterdir()) == {run_root / "inputs"},
                 "prepared run root must contain only input snapshots")
        manifest_payload, state_payload = manifest.to_payload(), state.to_payload()
        cls._validate_document_snapshots(run_root, manifest)
        store = cls(run_root, manifest, state)
        atomic_private_write(store.manifest_path, _json_bytes(manifest_payload), 0o400)
        atomic_private_write(store.state_path, _json_bytes(state_payload), 0o600)
        return store
    @classmethod
    def open(cls, codex_home: Path, run_id: str) -> "RunStore":
        run_root = cls._run_root(codex_home, run_id)
        _require(not run_root.is_symlink() and run_root.is_dir(), "format-5 run root is unavailable")
        run_root = run_root.resolve(strict=True)
        manifest_payload = _read_private_json(run_root / "manifest.json")
        state_payload = _read_private_json(run_root / "state.json")
        manifest = cls._manifest_from_payload(cls.validate_manifest_payload(manifest_payload))
        _require(manifest.run_id == run_id, "format-5 run identity is invalid")
        state = cls._state_from_payload(cls.validate_state_payload(state_payload))
        cls._validate_document_snapshots(run_root, manifest)
        return cls(run_root, manifest, state)
    @staticmethod
    def _manifest_from_payload(payload: Mapping[str, object]) -> RunManifest:
        values = dict(payload)
        values["documents"] = tuple(DocumentRecord(**record) for record in values["documents"])
        values["git_identity"] = GitIdentity(**values["git_identity"])
        return RunManifest(**values)
    @staticmethod
    def _state_from_payload(payload: Mapping[str, object]) -> RunState:
        return RunState(**dict(payload))
    def save_state(self, state: RunState) -> None:
        atomic_private_write(self.state_path, _json_bytes(state.to_payload()), 0o600)
        self.state = state
    def write_handoff(self, payload: Mapping[str, object]) -> Path:
        _require(isinstance(payload, Mapping), "handoff is invalid")
        atomic_private_write(self.handoff_path, _json_bytes(dict(payload)), 0o600)
        return self.handoff_path
    def lock(self, shared: bool = False) -> RunLock:
        return RunLock(self.lock_path, shared=shared)
