from __future__ import annotations

import copy
import errno
import fcntl
import hashlib
import json
import os
import re
import stat
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from .contracts import (
    CONTRACT_VERSION,
    FORMAT_VERSION,
    PLAN_STATUSES,
    RUN_STATUSES,
    canonical_json,
    require_full_sha,
    sha256_json,
)

BEFORE_STATE_REPLACE = "artifact_durable_before_state_replace"
AFTER_STATE_REPLACE = "state_replaced"

_PROVIDER = "claude"
_RUN_ID = re.compile(
    r"[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?"
    r"-[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z"
)
_KIND = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_STATE_FIELDS = frozenset(
    (
        "format_version", "contract_version", "provider", "run_id", "revision",
        "state_digest", "status", "integration", "immutable_config",
        "runner_runtime", "repository", "inputs", "plans", "current_plan_index",
        "sessions", "attempts", "artifact_refs", "failure",
    )
)
_LEGACY_STATE_FIELDS = _STATE_FIELDS | {"task_ledger", "finalization"}
_IMMUTABLE_FIELDS = (
    "format_version", "contract_version", "provider", "run_id", "integration",
    "immutable_config", "runner_runtime", "repository", "inputs",
)


@dataclass(frozen=True)
class ArtifactRef:
    kind: str
    digest: str
    relative_path: str

    def as_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "digest": self.digest,
            "relative_path": self.relative_path,
        }


def _sync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_private_write(path: Path, payload: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(temporary, flags, mode)
    try:
        view = memoryview(payload)
        while view:
            count = os.write(descriptor, view)
            if count <= 0:
                raise OSError("short private write")
            view = view[count:]
        os.fchmod(descriptor, mode)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    try:
        os.replace(temporary, path)
        _sync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _components_are_real(path: Path, boundary: Path | None = None) -> None:
    absolute = path.absolute()
    floor = boundary.absolute() if boundary else None
    cursor = absolute
    while True:
        if floor is not None:
            try:
                cursor.relative_to(floor)
            except ValueError as error:
                raise ValueError("path is outside the private run root") from error
        try:
            mode = cursor.lstat().st_mode
        except FileNotFoundError:
            mode = 0
        if mode and stat.S_ISLNK(mode):
            raise ValueError(f"path contains an unsafe symlink component: {cursor}")
        if cursor == floor or cursor.parent == cursor:
            return
        cursor = cursor.parent


def _private_directory(path: Path) -> None:
    _components_are_real(path)
    try:
        metadata = path.lstat()
    except FileNotFoundError as error:
        raise ValueError(f"private directory is missing: {path}") from error
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.getuid():
        raise ValueError(f"private directory must be owned real directory: {path}")
    if stat.S_IMODE(metadata.st_mode) & 0o022:
        raise ValueError(f"private directory is group/other writable: {path}")


def _private_file(path: Path, label: str) -> os.stat_result:
    _components_are_real(path)
    try:
        metadata = path.lstat()
    except FileNotFoundError as error:
        raise ValueError(f"{label} is missing") from error
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid():
        raise ValueError(f"{label} must be an owned regular file")
    if stat.S_IMODE(metadata.st_mode) & 0o022:
        raise ValueError(f"{label} is not private")
    return metadata


def _input_bytes(path: Path) -> tuple[Path, bytes]:
    if not path.is_absolute():
        raise ValueError("input must be an absolute regular file")
    _components_are_real(path)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        before = path.lstat()
        descriptor = os.open(path, flags)
    except OSError as error:
        raise ValueError("input must be a readable regular file") from error
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or (before.st_dev, before.st_ino) != (
            opened.st_dev, opened.st_ino
        ):
            raise ValueError("input must be a regular file")
        chunks = []
        while data := os.read(descriptor, 1024 * 1024):
            chunks.append(data)
        payload = b"".join(chunks)
        payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("input must be UTF-8") from error
    finally:
        os.close(descriptor)
    return path.absolute(), payload


def _run_id(value: object) -> str:
    if not isinstance(value, str) or _RUN_ID.fullmatch(value) is None:
        raise ValueError("run ID must be a sanitized slug plus a UUIDv4")
    return value


def _state_digest(state: Mapping[str, object]) -> str:
    body = dict(state)
    body.pop("state_digest", None)
    return sha256_json(body)


def _artifact(root: Path, value: object, *, require_file: bool) -> tuple[ArtifactRef, Path]:
    if not isinstance(value, Mapping) or set(value) != {"kind", "digest", "relative_path"}:
        raise ValueError("artifact reference is invalid")
    kind, digest, relative = value["kind"], value["digest"], value["relative_path"]
    if not isinstance(kind, str) or _KIND.fullmatch(kind) is None:
        raise ValueError("artifact kind is invalid")
    if not isinstance(digest, str) or _DIGEST.fullmatch(digest) is None:
        raise ValueError("artifact digest is invalid")
    expected = Path("artifacts") / kind / f"{digest}.json"
    if not isinstance(relative, str) or relative != expected.as_posix():
        raise ValueError("unsafe relative artifact path")
    path = root / expected
    _components_are_real(path, root)
    if require_file:
        _private_directory(path.parent)
        _private_file(path, "referenced artifact")
        encoded = path.read_bytes()
        try:
            decoded = json.loads(encoded.decode())
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("referenced artifact is invalid JSON") from error
        if encoded != canonical_json(decoded) or sha256_json(decoded) != digest:
            raise ValueError("referenced artifact digest mismatch")
    return ArtifactRef(kind, digest, expected.as_posix()), path


def _validate(root: Path, value: object, expected_revision: int | None = None) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("run state envelope is invalid")
    version = (value.get("format_version"), value.get("contract_version"))
    if version not in {
        (FORMAT_VERSION, CONTRACT_VERSION),
        (1, 1),
    }:
        raise ValueError("unknown state version")
    has_v2_shape = set(value) == _STATE_FIELDS
    expected_fields = (
        _STATE_FIELDS
        if version == (FORMAT_VERSION, CONTRACT_VERSION)
        else _STATE_FIELDS
        if has_v2_shape
        else _LEGACY_STATE_FIELDS
    )
    if set(value) != expected_fields:
        raise ValueError("run state envelope is invalid")
    if value["provider"] != _PROVIDER:
        raise ValueError("wrong provider")
    _run_id(value["run_id"])
    revision = value["revision"]
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise ValueError("state revision is non-monotonic")
    if expected_revision is not None and revision != expected_revision:
        raise ValueError("state revision is non-monotonic")
    if value["state_digest"] != _state_digest(value):
        raise ValueError("state digest mismatch")
    if value["status"] not in RUN_STATUSES or value["integration"] != "not_observed":
        raise ValueError("run status is invalid")
    if not isinstance(value["immutable_config"], dict) or not isinstance(value["runner_runtime"], dict):
        raise ValueError("immutable metadata is invalid")
    repository = value["repository"]
    if not isinstance(repository, dict) or set(repository) != {
        "source_repository", "source_commit", "worktree", "branch"
    }:
        raise ValueError("repository identity is invalid")
    if (
        not Path(repository["source_repository"]).is_absolute()
        or not Path(repository["worktree"]).is_absolute()
        or not isinstance(repository["branch"], str)
        or not repository["branch"]
    ):
        raise ValueError("repository identity is invalid")
    require_full_sha(repository["source_commit"])
    inputs, plans = value["inputs"], value["plans"]
    if not isinstance(inputs, list) or not isinstance(plans, list) or not plans:
        raise ValueError("state inputs and plans are invalid")
    role_counts = {"spec": 0, "plan": 0}
    plan_inputs = []
    for record in inputs:
        required = {
            "document_id", "role", "source_path", "snapshot_path", "sha256",
            "byte_length", "input_order",
        }
        if not isinstance(record, dict) or set(record) != required:
            raise ValueError("input record is invalid")
        role = record["role"]
        if role not in role_counts or record["input_order"] != role_counts[role]:
            raise ValueError("input order is invalid")
        expected_id = f"{role}-{role_counts[role] + 1:02d}"
        if record["document_id"] != expected_id:
            raise ValueError("input identity is invalid")
        role_counts[role] += 1
        source = Path(record["source_path"])
        snapshot = Path(record["snapshot_path"])
        suffix = source.suffix or ".txt"
        if not source.is_absolute() or snapshot != root / "inputs" / f"{expected_id}{suffix}":
            raise ValueError("input snapshot path is unsafe")
        if not isinstance(record["sha256"], str) or _DIGEST.fullmatch(record["sha256"]) is None:
            raise ValueError("input digest is invalid")
        _private_file(snapshot, "input snapshot")
        payload = snapshot.read_bytes()
        if len(payload) != record["byte_length"] or hashlib.sha256(payload).hexdigest() != record["sha256"]:
            raise ValueError("input snapshot digest mismatch")
        payload.decode("utf-8")
        if role == "plan":
            plan_inputs.append(record)
    if 0 in role_counts.values() or len(plan_inputs) != len(plans):
        raise ValueError("at least one spec and one plan are required")
    for position, (plan, source) in enumerate(zip(plans, plan_inputs, strict=True)):
        if not isinstance(plan, dict) or plan.get("status") not in PLAN_STATUSES:
            raise ValueError("invalid plan status")
        expected = {
            "plan_id": source["document_id"],
            "status": plan["status"],
            "input_order": position,
            "source_path": source["source_path"],
            "snapshot_path": source["snapshot_path"],
            "sha256": source["sha256"],
            "byte_length": source["byte_length"],
        }
        if version == (FORMAT_VERSION, CONTRACT_VERSION) or has_v2_shape:
            handoff = plan.get("handoff_digest")
            if handoff is not None and (
                not isinstance(handoff, str)
                or _DIGEST.fullmatch(handoff) is None
            ):
                raise ValueError("plan handoff digest is invalid")
            expected["handoff_digest"] = handoff
        if plan != expected:
            raise ValueError("plan identity is invalid")
    index = value["current_plan_index"]
    if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index <= len(plans):
        raise ValueError("current plan index is invalid")
    for name in ("sessions", "attempts", "artifact_refs"):
        if not isinstance(value[name], list):
            raise ValueError(f"{name} must be a list")
    if version == (1, 1):
        for name in ("task_ledger",):
            if name in value and not isinstance(value[name], list):
                raise ValueError(f"{name} must be a list")
    for reference in value["artifact_refs"]:
        _artifact(root, reference, require_file=True)
    return value


class StateStore:
    def __init__(
        self,
        root: Path,
        state: dict[str, object],
        *,
        fault_injector: Callable[[str], None] | None = None,
    ) -> None:
        self.root = root
        self.state_path = root / "state.json"
        self._state = state
        self._fault_injector = fault_injector

    @classmethod
    def create(
        cls,
        *,
        root: Path,
        provider: str,
        run_id: str,
        source_repository: Path,
        source_commit: str,
        worktree: Path,
        branch: str,
        specs: Sequence[Path],
        plans: Sequence[Path],
        immutable_config: Mapping[str, object],
        runner_runtime: Mapping[str, object],
    ) -> "StateStore":
        root = root.absolute()
        if provider != _PROVIDER:
            raise ValueError("wrong provider")
        _run_id(run_id)
        require_full_sha(source_commit)
        if not source_repository.is_absolute() or not worktree.is_absolute():
            raise ValueError("repository and worktree paths must be absolute")
        _components_are_real(source_repository)
        repository = source_repository.resolve()
        if not repository.is_dir():
            raise ValueError("source repository must be a real directory")
        _components_are_real(worktree)
        if not isinstance(branch, str) or not branch.startswith("claude-plan/"):
            raise ValueError("Claude branch must use claude-plan/")
        if not specs or not plans or root.exists() or root.is_symlink():
            raise ValueError("run root or required inputs are invalid")
        documents: list[tuple[str, int, Path, bytes]] = []
        seen = set()
        for role, paths in (("spec", specs), ("plan", plans)):
            for order, requested in enumerate(paths):
                source, payload = _input_bytes(requested)
                if source in seen:
                    raise ValueError("duplicate input paths are not allowed")
                seen.add(source)
                documents.append((role, order, source, payload))
        root.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        _private_directory(root.parent)
        root.mkdir(mode=0o700)
        (root / "inputs").mkdir(mode=0o700)
        (root / "artifacts").mkdir(mode=0o700)
        records = []
        for role, order, source, payload in documents:
            document_id = f"{role}-{order + 1:02d}"
            snapshot = root / "inputs" / f"{document_id}{source.suffix or '.txt'}"
            atomic_private_write(snapshot, payload)
            records.append(
                {
                    "document_id": document_id,
                    "role": role,
                    "source_path": str(source),
                    "snapshot_path": str(snapshot),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "byte_length": len(payload),
                    "input_order": order,
                }
            )
        plan_records = [
            {
                "plan_id": item["document_id"],
                "status": "pending",
                "input_order": item["input_order"],
                "source_path": item["source_path"],
                "snapshot_path": item["snapshot_path"],
                "sha256": item["sha256"],
                "byte_length": item["byte_length"],
                "handoff_digest": None,
            }
            for item in records if item["role"] == "plan"
        ]
        state: dict[str, object] = {
            "format_version": FORMAT_VERSION,
            "contract_version": CONTRACT_VERSION,
            "provider": _PROVIDER,
            "run_id": run_id,
            "revision": 1,
            "state_digest": "",
            "status": "resumable",
            "integration": "not_observed",
            "immutable_config": copy.deepcopy(dict(immutable_config)),
            "runner_runtime": copy.deepcopy(dict(runner_runtime)),
            "repository": {
                "source_repository": str(repository),
                "source_commit": source_commit,
                "worktree": str(worktree.absolute()),
                "branch": branch,
            },
            "inputs": records,
            "plans": plan_records,
            "current_plan_index": 0,
            "sessions": [],
            "attempts": [],
            "artifact_refs": [],
            "failure": None,
        }
        state["state_digest"] = _state_digest(state)
        _validate(root, state, 1)
        atomic_private_write(root / "state.json", canonical_json(state))
        return cls(root, state)

    @classmethod
    def open(cls, root: Path) -> "StateStore":
        root = root.absolute()
        _private_directory(root)
        _private_directory(root / "inputs")
        _private_directory(root / "artifacts")
        state_path = root / "state.json"
        _private_file(state_path, "run state")
        try:
            value = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ValueError("run state is unavailable or invalid") from error
        return cls(root, _validate(root, value))

    def snapshot(self) -> dict[str, object]:
        return copy.deepcopy(self._state)

    def put_artifact(self, kind: str, payload: object) -> ArtifactRef:
        if not isinstance(kind, str) or _KIND.fullmatch(kind) is None:
            raise ValueError("artifact kind is invalid")
        encoded = canonical_json(payload)
        digest = sha256_json(payload)
        ref = ArtifactRef(kind, digest, f"artifacts/{kind}/{digest}.json")
        path = self.root / ref.relative_path
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        _private_directory(path.parent)
        if path.exists() or path.is_symlink():
            _private_file(path, "content-addressed artifact")
            if path.read_bytes() != encoded:
                raise ValueError("content-addressed artifact digest collision")
        else:
            atomic_private_write(path, encoded)
        return ref

    def commit(self, next_state: Mapping[str, object]) -> dict[str, object]:
        if (
            self._state.get("format_version"),
            self._state.get("contract_version"),
        ) != (FORMAT_VERSION, CONTRACT_VERSION):
            raise ValueError("legacy_contract_requires_v1_runner")
        _private_file(self.state_path, "run state")
        try:
            disk = _validate(self.root, json.loads(self.state_path.read_text()))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError("run state is unavailable or invalid") from error
        revision = self._state["revision"]
        if disk["revision"] != revision or disk["state_digest"] != self._state["state_digest"]:
            raise ValueError("state revision is non-monotonic")
        candidate = copy.deepcopy(dict(next_state))
        for field in _IMMUTABLE_FIELDS:
            if candidate.get(field) != self._state[field]:
                raise ValueError(f"immutable state field changed: {field}")
        candidate["revision"] = revision + 1
        candidate["state_digest"] = _state_digest(candidate)
        _validate(self.root, candidate, revision + 1)
        if self._fault_injector:
            self._fault_injector(BEFORE_STATE_REPLACE)
        atomic_private_write(self.state_path, canonical_json(candidate))
        self._state = candidate
        if self._fault_injector:
            self._fault_injector(AFTER_STATE_REPLACE)
        return self.snapshot()

    def referenced_artifact(self, reference: object) -> Path:
        return _artifact(self.root, reference, require_file=True)[1]


class RunLock:
    def __init__(self, path: Path) -> None:
        self.path = path.absolute()
        self._fd: int | None = None

    def __enter__(self) -> "RunLock":
        _private_directory(self.path.parent)
        _components_are_real(self.path, self.path.parent)
        try:
            descriptor = os.open(
                self.path,
                os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid():
                raise ValueError("run lock must be a private regular file")
            os.fchmod(descriptor, 0o600)
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            if "descriptor" in locals():
                os.close(descriptor)
            if error.errno in (errno.EACCES, errno.EAGAIN):
                raise RuntimeError("run is busy") from error
            raise
        self._fd = descriptor
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> bool:
        descriptor, self._fd = self._fd, None
        if descriptor is not None:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)
        return False
