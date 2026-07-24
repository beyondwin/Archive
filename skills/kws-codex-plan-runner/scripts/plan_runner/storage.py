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
    FORMAT_VERSION,
    PLAN_STATUSES,
    RUN_STATUSES,
    canonical_json,
    require_full_sha,
    sha256_json,
)
from .git_ops import GitIdentity


BEFORE_STATE_REPLACE = "artifact_durable_before_state_replace"
AFTER_STATE_REPLACE = "state_replaced"

_CONTRACT_VERSION = 1
_PROVIDER = "codex"
_RUN_ID = re.compile(
    r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?"
    r"-[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_ARTIFACT_KIND = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_STATE_KEYS = {
    "format_version",
    "contract_version",
    "provider",
    "run_id",
    "revision",
    "state_digest",
    "status",
    "integration",
    "immutable_config",
    "runner_runtime",
    "repository",
    "inputs",
    "plans",
    "current_plan_index",
    "task_ledger",
    "sessions",
    "attempts",
    "artifact_refs",
    "failure",
    "finalization",
}
_IMMUTABLE_STATE_KEYS = (
    "format_version",
    "contract_version",
    "provider",
    "run_id",
    "integration",
    "immutable_config",
    "runner_runtime",
    "repository",
    "inputs",
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


def atomic_private_write(path: Path, payload: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_name("." + path.name + "." + uuid.uuid4().hex + ".tmp")
    descriptor = os.open(
        str(temporary),
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        mode,
    )
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("private artifact must be a regular file")
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short write")
            view = view[written:]
        os.fchmod(descriptor, mode)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    try:
        os.replace(str(temporary), str(path))
        directory = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _reject_symlink_components(path: Path, *, boundary: Path | None = None) -> None:
    candidate = path.absolute()
    stop = boundary.absolute() if boundary is not None else None
    current = candidate
    while True:
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            metadata = None
        if metadata is not None and stat.S_ISLNK(metadata.st_mode):
            raise ValueError(f"path contains an unsafe symlink component: {current}")
        if current == stop or current.parent == current:
            return
        if stop is not None:
            try:
                current.relative_to(stop)
            except ValueError as error:
                raise ValueError("path is outside the private run root") from error
        current = current.parent


def _require_private_directory(path: Path) -> None:
    _reject_symlink_components(path)
    try:
        metadata = path.lstat()
    except FileNotFoundError as error:
        raise ValueError(f"private directory is missing: {path}") from error
    if not stat.S_ISDIR(metadata.st_mode):
        raise ValueError(f"private directory must be a real directory: {path}")
    if metadata.st_uid != os.getuid():
        raise ValueError(f"private directory has the wrong owner: {path}")
    if stat.S_IMODE(metadata.st_mode) & 0o022:
        raise ValueError(f"private directory is group/other writable: {path}")


def _require_private_regular(path: Path, description: str) -> os.stat_result:
    _reject_symlink_components(path)
    try:
        metadata = path.lstat()
    except FileNotFoundError as error:
        raise ValueError(f"{description} is missing") from error
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError(f"{description} must be a regular file")
    if metadata.st_uid != os.getuid():
        raise ValueError(f"{description} has the wrong owner")
    if stat.S_IMODE(metadata.st_mode) & 0o022:
        raise ValueError(f"{description} is not private")
    return metadata


def _read_utf8_regular(path: Path) -> tuple[Path, bytes]:
    if not path.is_absolute():
        raise ValueError("input must be an absolute regular file")
    try:
        _reject_symlink_components(path)
    except ValueError as error:
        raise ValueError("input must be a regular file without symlinks") from error
    try:
        metadata = path.lstat()
        descriptor = os.open(
            str(path),
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        )
    except OSError as error:
        raise ValueError(f"input is not a readable UTF-8 regular file: {path}") from error
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or not stat.S_ISREG(opened.st_mode)
            or (metadata.st_dev, metadata.st_ino) != (opened.st_dev, opened.st_ino)
        ):
            raise ValueError("input must be a regular file")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        payload = b"".join(chunks)
        payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(f"input is not a readable UTF-8 regular file: {path}") from error
    finally:
        os.close(descriptor)
    return path.absolute(), payload


def _validate_run_id(run_id: object) -> str:
    if not isinstance(run_id, str) or _RUN_ID.fullmatch(run_id) is None:
        raise ValueError("run ID must be a sanitized slug plus a UUIDv4")
    return run_id


def _state_digest(state: Mapping[str, object]) -> str:
    without_digest = dict(state)
    without_digest.pop("state_digest", None)
    return sha256_json(without_digest)


def _safe_artifact_reference(
    root: Path, reference: object, *, require_file: bool
) -> tuple[ArtifactRef, Path]:
    if not isinstance(reference, Mapping) or set(reference) != {
        "kind",
        "digest",
        "relative_path",
    }:
        raise ValueError("artifact reference is invalid")
    kind = reference["kind"]
    digest = reference["digest"]
    relative_path = reference["relative_path"]
    if not isinstance(kind, str) or _ARTIFACT_KIND.fullmatch(kind) is None:
        raise ValueError("artifact kind is invalid")
    if not isinstance(digest, str) or _DIGEST.fullmatch(digest) is None:
        raise ValueError("artifact digest is invalid")
    expected = Path("artifacts") / kind / f"{digest}.json"
    if (
        not isinstance(relative_path, str)
        or Path(relative_path).is_absolute()
        or relative_path != expected.as_posix()
        or ".." in Path(relative_path).parts
    ):
        raise ValueError("unsafe relative artifact path")
    artifact_path = root / expected
    _reject_symlink_components(artifact_path, boundary=root)
    if require_file:
        if not artifact_path.parent.exists():
            raise ValueError("missing artifact")
        _require_private_directory(artifact_path.parent)
        if not artifact_path.exists():
            raise ValueError("missing artifact")
        _require_private_regular(artifact_path, "referenced artifact")
        payload = artifact_path.read_bytes()
        try:
            value = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("referenced artifact is invalid JSON") from error
        if canonical_json(value) != payload or sha256_json(value) != digest:
            raise ValueError("referenced artifact digest mismatch")
    return ArtifactRef(kind=kind, digest=digest, relative_path=str(expected)), artifact_path


def _validate_state(
    root: Path,
    state: object,
    *,
    expected_provider: str = _PROVIDER,
    expected_revision: int | None = None,
) -> dict[str, object]:
    if not isinstance(state, dict) or set(state) != _STATE_KEYS:
        raise ValueError("run state envelope is invalid")
    if state["format_version"] != FORMAT_VERSION:
        raise ValueError("unknown state format version")
    if state["contract_version"] != _CONTRACT_VERSION:
        raise ValueError("unknown state contract version")
    if state["provider"] != expected_provider:
        raise ValueError("wrong provider")
    _validate_run_id(state["run_id"])
    revision = state["revision"]
    if (
        not isinstance(revision, int)
        or isinstance(revision, bool)
        or revision < 1
        or (expected_revision is not None and revision != expected_revision)
    ):
        raise ValueError("state revision is non-monotonic")
    if state["state_digest"] != _state_digest(state):
        raise ValueError("state digest mismatch")
    if state["status"] not in RUN_STATUSES:
        raise ValueError("invalid run status")
    if state["integration"] != "not_observed":
        raise ValueError("integration state is invalid")
    if not isinstance(state["immutable_config"], dict):
        raise ValueError("immutable config is invalid")
    GitIdentity.from_mapping(state["immutable_config"].get("git_identity"))
    if not isinstance(state["runner_runtime"], dict):
        raise ValueError("runner runtime is invalid")

    repository = state["repository"]
    if not isinstance(repository, dict) or set(repository) != {
        "source_repository",
        "source_commit",
        "worktree",
        "branch",
    }:
        raise ValueError("repository identity is invalid")
    if (
        not isinstance(repository["source_repository"], str)
        or not Path(repository["source_repository"]).is_absolute()
        or not isinstance(repository["worktree"], str)
        or not Path(repository["worktree"]).is_absolute()
        or not isinstance(repository["branch"], str)
        or not repository["branch"]
    ):
        raise ValueError("repository identity is invalid")
    require_full_sha(repository["source_commit"])

    inputs = state["inputs"]
    plans = state["plans"]
    if not isinstance(inputs, list) or not isinstance(plans, list) or not plans:
        raise ValueError("state inputs and plans are invalid")
    role_orders = {"spec": 0, "plan": 0}
    plan_inputs: list[dict[str, object]] = []
    inputs_root = root / "inputs"
    for item in inputs:
        if not isinstance(item, dict) or set(item) != {
            "document_id",
            "role",
            "source_path",
            "snapshot_path",
            "sha256",
            "byte_length",
            "input_order",
        }:
            raise ValueError("input record is invalid")
        role = item["role"]
        if role not in role_orders:
            raise ValueError("input role is invalid")
        order = role_orders[role]
        if item["input_order"] != order or item["document_id"] != f"{role}-{order + 1:02d}":
            raise ValueError("input order is invalid")
        role_orders[role] += 1
        if (
            not isinstance(item["source_path"], str)
            or not Path(item["source_path"]).is_absolute()
            or not isinstance(item["snapshot_path"], str)
            or not Path(item["snapshot_path"]).is_absolute()
            or not isinstance(item["sha256"], str)
            or _DIGEST.fullmatch(item["sha256"]) is None
            or not isinstance(item["byte_length"], int)
            or isinstance(item["byte_length"], bool)
            or item["byte_length"] < 0
        ):
            raise ValueError("input metadata is invalid")
        snapshot = Path(item["snapshot_path"])
        source_suffix = Path(item["source_path"]).suffix or ".txt"
        expected_snapshot = inputs_root / f"{item['document_id']}{source_suffix}"
        if snapshot != expected_snapshot or ".." in snapshot.parts:
            raise ValueError("input snapshot path is unsafe")
        try:
            snapshot.relative_to(inputs_root)
        except ValueError as error:
            raise ValueError("input snapshot is outside the private run root") from error
        _reject_symlink_components(snapshot, boundary=root)
        _require_private_regular(snapshot, "input snapshot")
        snapshot_payload = snapshot.read_bytes()
        if (
            len(snapshot_payload) != item["byte_length"]
            or hashlib.sha256(snapshot_payload).hexdigest() != item["sha256"]
        ):
            raise ValueError("input snapshot digest mismatch")
        try:
            snapshot_payload.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError("input snapshot is not UTF-8") from error
        if role == "plan":
            plan_inputs.append(item)
    if role_orders["spec"] < 1 or role_orders["plan"] < 1:
        raise ValueError("at least one spec and one plan are required")
    if len(plans) != len(plan_inputs):
        raise ValueError("plan state count does not match plan inputs")
    for position, (plan, source) in enumerate(zip(plans, plan_inputs, strict=True)):
        if not isinstance(plan, dict) or set(plan) != {
            "plan_id",
            "status",
            "input_order",
            "source_path",
            "snapshot_path",
            "sha256",
            "byte_length",
        }:
            raise ValueError("plan record is invalid")
        if plan["status"] not in PLAN_STATUSES:
            raise ValueError("invalid plan status")
        expected = {
            "plan_id": source["document_id"],
            "input_order": position,
            "source_path": source["source_path"],
            "snapshot_path": source["snapshot_path"],
            "sha256": source["sha256"],
            "byte_length": source["byte_length"],
        }
        if any(plan[name] != value for name, value in expected.items()):
            raise ValueError("plan identity is invalid")

    current_index = state["current_plan_index"]
    if (
        not isinstance(current_index, int)
        or isinstance(current_index, bool)
        or not 0 <= current_index <= len(plans)
    ):
        raise ValueError("current plan index is invalid")
    for name in ("task_ledger", "sessions", "attempts", "artifact_refs"):
        if not isinstance(state[name], list):
            raise ValueError(f"{name} must be a list")
    for reference in state["artifact_refs"]:
        _safe_artifact_reference(root, reference, require_file=True)
    return state


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
    ) -> StateStore:
        root = root.absolute()
        if provider != _PROVIDER:
            raise ValueError("wrong provider")
        _validate_run_id(run_id)
        require_full_sha(source_commit)
        _reject_symlink_components(source_repository)
        if not source_repository.is_absolute() or source_repository.is_symlink():
            raise ValueError("source repository must be a real directory")
        try:
            repository = source_repository.resolve(strict=True)
        except OSError as error:
            raise ValueError("source repository must be a real directory") from error
        if not repository.is_dir():
            raise ValueError("source repository must be a real directory")
        if not worktree.is_absolute():
            raise ValueError("worktree path must be absolute")
        _reject_symlink_components(worktree)
        if not isinstance(branch, str) or not branch:
            raise ValueError("branch is invalid")
        if not specs or not plans:
            raise ValueError("at least one spec and one plan are required")
        if root.exists() or root.is_symlink():
            raise ValueError("run root already exists")

        prepared: list[tuple[str, int, Path, bytes]] = []
        seen: set[Path] = set()
        for role, paths in (("spec", specs), ("plan", plans)):
            for order, path in enumerate(paths):
                source, payload = _read_utf8_regular(path)
                if source in seen:
                    raise ValueError("duplicate input paths are not allowed")
                seen.add(source)
                prepared.append((role, order, source, payload))

        root.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        _require_private_directory(root.parent)
        root.mkdir(mode=0o700)
        for directory in (root / "inputs", root / "artifacts"):
            directory.mkdir(mode=0o700)
            _require_private_directory(directory)
        _require_private_directory(root)

        records: list[dict[str, object]] = []
        for role, order, source, payload in prepared:
            document_id = f"{role}-{order + 1:02d}"
            suffix = source.suffix if source.suffix else ".txt"
            snapshot = root / "inputs" / f"{document_id}{suffix}"
            atomic_private_write(snapshot, payload)
            record = {
                "document_id": document_id,
                "role": role,
                "source_path": str(source),
                "snapshot_path": str(snapshot),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "byte_length": len(payload),
                "input_order": order,
            }
            records.append(record)
        plan_records = [
            {
                "plan_id": item["document_id"],
                "status": "pending",
                "input_order": item["input_order"],
                "source_path": item["source_path"],
                "snapshot_path": item["snapshot_path"],
                "sha256": item["sha256"],
                "byte_length": item["byte_length"],
            }
            for item in records
            if item["role"] == "plan"
        ]
        state: dict[str, object] = {
            "format_version": FORMAT_VERSION,
            "contract_version": _CONTRACT_VERSION,
            "provider": provider,
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
            "task_ledger": [],
            "sessions": [],
            "attempts": [],
            "artifact_refs": [],
            "failure": None,
            "finalization": None,
        }
        state["state_digest"] = _state_digest(state)
        _validate_state(root, state, expected_revision=1)
        atomic_private_write(root / "state.json", canonical_json(state))
        return cls(root, state)

    @classmethod
    def open(cls, root: Path) -> StateStore:
        root = root.absolute()
        _reject_symlink_components(root)
        _require_private_directory(root)
        _require_private_directory(root / "inputs")
        _require_private_directory(root / "artifacts")
        state_path = root / "state.json"
        _require_private_regular(state_path, "run state")
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("run state is unavailable or invalid") from error
        validated = _validate_state(root, state)
        return cls(root, validated)

    def snapshot(self) -> dict[str, object]:
        return copy.deepcopy(self._state)

    def put_artifact(self, kind: str, payload: object) -> ArtifactRef:
        if not isinstance(kind, str) or _ARTIFACT_KIND.fullmatch(kind) is None:
            raise ValueError("artifact kind is invalid")
        encoded = canonical_json(payload)
        digest = sha256_json(payload)
        relative = Path("artifacts") / kind / f"{digest}.json"
        path = self.root / relative
        artifact_directory = path.parent
        artifact_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        _require_private_directory(self.root)
        _require_private_directory(self.root / "artifacts")
        _require_private_directory(artifact_directory)
        _reject_symlink_components(path, boundary=self.root)
        if path.exists() or path.is_symlink():
            _require_private_regular(path, "content-addressed artifact")
            if path.read_bytes() != encoded:
                raise ValueError("content-addressed artifact digest collision")
        else:
            atomic_private_write(path, encoded)
            _require_private_regular(path, "content-addressed artifact")
            if path.read_bytes() != encoded:
                raise ValueError("content-addressed artifact write mismatch")
        return ArtifactRef(kind=kind, digest=digest, relative_path=str(relative))

    def commit(self, next_state: Mapping[str, object]) -> dict[str, object]:
        _require_private_directory(self.root)
        _require_private_regular(self.state_path, "run state")
        try:
            disk_state = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("run state is unavailable or invalid") from error
        disk_state = _validate_state(self.root, disk_state)
        current_revision = self._state["revision"]
        if (
            not isinstance(current_revision, int)
            or disk_state["revision"] != current_revision
            or disk_state["state_digest"] != self._state["state_digest"]
        ):
            raise ValueError("state revision is non-monotonic")

        candidate = copy.deepcopy(dict(next_state))
        for key in _IMMUTABLE_STATE_KEYS:
            if candidate.get(key) != self._state[key]:
                raise ValueError(f"immutable state field changed: {key}")
        candidate["revision"] = current_revision + 1
        candidate["state_digest"] = _state_digest(candidate)
        _validate_state(
            self.root,
            candidate,
            expected_revision=current_revision + 1,
        )
        if self._fault_injector is not None:
            self._fault_injector(BEFORE_STATE_REPLACE)
        atomic_private_write(self.state_path, canonical_json(candidate))
        self._state = candidate
        if self._fault_injector is not None:
            self._fault_injector(AFTER_STATE_REPLACE)
        return self.snapshot()

    def referenced_artifact(self, reference: object) -> Path:
        _artifact, path = _safe_artifact_reference(
            self.root,
            reference,
            require_file=True,
        )
        return path


class RunLock:
    def __init__(self, path: Path) -> None:
        self.path = path.absolute()
        self._descriptor: int | None = None

    def __enter__(self) -> RunLock:
        _require_private_directory(self.path.parent)
        _reject_symlink_components(self.path, boundary=self.path.parent)
        try:
            descriptor = os.open(
                str(self.path),
                os.O_RDWR
                | os.O_CREAT
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
        except OSError as error:
            raise ValueError("run lock must be a private regular file") from error
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise ValueError("run lock must be a private regular file")
            if metadata.st_uid != os.getuid():
                raise ValueError("run lock has the wrong owner")
            os.fchmod(descriptor, 0o600)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                if error.errno in (errno.EACCES, errno.EAGAIN):
                    raise RuntimeError("run is busy") from error
                raise
        except BaseException:
            os.close(descriptor)
            raise
        self._descriptor = descriptor
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        descriptor = self._descriptor
        self._descriptor = None
        if descriptor is not None:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)
        return False
