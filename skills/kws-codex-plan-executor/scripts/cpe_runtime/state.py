"""Private atomic state and input snapshots for the sequential CPE runner."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence


FORMAT_VERSION = 2
RUN_STATUSES = {
    "preparing",
    "ready",
    "running",
    "checkpointed",
    "completed",
    "blocked",
    "failed",
}
TRUST_LEVELS = {"parent_observed", "child_attested", "derived", "hypothesis"}
PLAN_STATUSES = {
    "pending",
    "running",
    "checkpointed",
    "completed",
    "blocked",
    "failed",
}
DEFAULT_PLAN_BUDGET = {
    "controller_slice_timeout_seconds": 3600,
    "max_progress_checkpoints": 6,
    "plan_wall_budget_seconds": 21_600,
    "max_controller_launches": 8,
}
_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
_DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _write_all(descriptor: int, payload: bytes) -> None:
    remaining = memoryview(payload)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            raise OSError("short write while persisting run state")
        remaining = remaining[written:]


def atomic_private_write(path: Path, payload: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
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
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _private_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.chmod(0o700)


def _inside(path: Path, parent: Path, name: str) -> Path:
    resolved = path.resolve(strict=True)
    try:
        resolved.relative_to(parent.resolve(strict=True))
    except ValueError as exc:
        raise ValueError(f"{name} is outside the private run root") from exc
    return resolved


def _read_document(path: Path) -> tuple[Path, bytes]:
    if not path.is_absolute() or path.is_symlink():
        raise ValueError("input paths must be absolute regular files")
    try:
        resolved = path.resolve(strict=True)
        metadata = resolved.stat()
        payload = resolved.read_bytes()
        payload.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError(f"input is not a readable UTF-8 file: {path}") from exc
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError(f"input is not a regular file: {path}")
    return resolved, payload


class StateStore:
    """Own one format-version-2 state file beneath a private run root."""

    def __init__(self, root: Path, state: dict[str, Any]) -> None:
        self.root = root
        self.state_path = root / "state.json"
        self.events_path = root / "events.jsonl"
        self.state = state

    @classmethod
    def create(
        cls,
        *,
        run_root: Path,
        run_id: str,
        source_repository: Path,
        source_commit: str,
        worktree: Path,
        branch: str,
        specs: Sequence[Path],
        plans: Sequence[Path],
        initial_status: str = "preparing",
    ) -> "StateStore":
        if not plans:
            raise ValueError("at least one plan is required")
        if initial_status not in {"preparing", "ready", "running"}:
            raise ValueError("initial run status is invalid")
        if run_root.exists():
            raise ValueError("run root already exists")
        if not _RUN_ID_PATTERN.fullmatch(run_id) or branch != f"codex/{run_id}":
            raise ValueError("run identity is invalid")
        if not _SHA_PATTERN.fullmatch(source_commit):
            raise ValueError("source commit must be a full Git object ID")
        repository = source_repository.resolve(strict=True)
        if not repository.is_dir() or repository.is_symlink():
            raise ValueError("source repository must be a real directory")
        prepared: list[tuple[str, int, Path, bytes]] = []
        seen: set[Path] = set()
        for role, paths in (("spec", specs), ("plan", plans)):
            for order, declared in enumerate(paths):
                source, payload = _read_document(declared)
                if source in seen:
                    raise ValueError("duplicate input paths are not allowed")
                seen.add(source)
                prepared.append((role, order, source, payload))

        _private_directory(run_root.parent)
        _private_directory(run_root)
        for name in ("inputs", "results", "logs", "evidence", "reports"):
            _private_directory(run_root / name)

        records: list[dict[str, Any]] = []
        for role, order, source, payload in prepared:
            document_id = f"{role}-{order + 1:02d}"
            suffix = source.suffix if source.suffix else ".txt"
            snapshot = run_root / "inputs" / f"{document_id}{suffix}"
            snapshot.write_bytes(payload)
            snapshot.chmod(0o600)
            records.append(
                {
                    "document_id": document_id,
                    "role": role,
                    "source_path": str(source),
                    "snapshot_path": str(snapshot.resolve()),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "byte_length": len(payload),
                    "input_order": order,
                }
            )

        plan_records = [
            {
                "plan_id": record["document_id"],
                "status": "pending",
                "starting_commit": None,
                "accepted_commit": None,
                "attempt_count": 0,
                "controller_launch_count": 0,
                "checkpoint_count": 0,
                "progress_checkpoint_count": 0,
                "consecutive_no_progress_slices": 0,
                "progress_fingerprint": None,
                "environment_fingerprint": None,
                "capability_probe_ids": [],
                "plan_started_at": None,
                "plan_elapsed_seconds": 0,
                "last_known_head": None,
                "result_path": None,
                "budget": dict(DEFAULT_PLAN_BUDGET),
            }
            for record in records
            if record["role"] == "plan"
        ]
        state = {
            "format_version": FORMAT_VERSION,
            "run_id": run_id,
            "status": initial_status,
            "source_repository": str(repository),
            "source_commit": source_commit,
            "worktree": str(worktree.resolve()),
            "branch": branch,
            "current_plan_index": 0,
            "inputs": records,
            "plans": plan_records,
        }
        store = cls(run_root.resolve(), state)
        store._validate()
        store.save()
        store.events_path.touch(mode=0o600)
        store.events_path.chmod(0o600)
        store.append_event("run.created", status=initial_status)
        return store

    @classmethod
    def open(cls, run_root: Path) -> "StateStore":
        if run_root.is_symlink():
            raise ValueError("run root must not be a symlink")
        try:
            root = run_root.resolve(strict=True)
            payload = json.loads((root / "state.json").read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("run state is unavailable or invalid") from exc
        version = payload.get("format_version") if isinstance(payload, dict) else None
        if version == 1:
            raise ValueError("unsupported_legacy_run")
        if version != FORMAT_VERSION:
            raise ValueError("unsupported_run_format")
        store = cls(root, payload)
        store._validate()
        return store

    def _validate(self) -> None:
        state = self.state
        required = {
            "format_version", "run_id", "status", "source_repository", "source_commit",
            "worktree", "branch", "current_plan_index", "inputs", "plans",
        }
        if set(state) != required or state.get("format_version") != FORMAT_VERSION:
            raise ValueError("invalid format-version-2 state")
        if not isinstance(state["run_id"], str) or not _RUN_ID_PATTERN.fullmatch(state["run_id"]) or state["branch"] != f"codex/{state['run_id']}":
            raise ValueError("run identity is invalid")
        if not all(isinstance(state[name], str) and Path(state[name]).is_absolute() for name in ("source_repository", "worktree")):
            raise ValueError("recorded repository paths are invalid")
        if state["status"] not in RUN_STATUSES:
            raise ValueError("unknown run status")
        if not _SHA_PATTERN.fullmatch(str(state["source_commit"])):
            raise ValueError("invalid source commit")
        if not isinstance(state["inputs"], list) or not isinstance(state["plans"], list) or not state["plans"]:
            raise ValueError("state inputs and plans are invalid")
        index = state["current_plan_index"]
        if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index <= len(state["plans"]):
            raise ValueError("current plan index is invalid")

        owned_directories = [
            self.root / name
            for name in ("inputs", "results", "logs", "evidence", "reports")
        ]
        for directory in owned_directories:
            if directory.is_symlink() or not directory.is_dir():
                raise ValueError("private run directory is missing or redirected")
            _inside(directory, self.root, "private run directory")
        inputs_root, results_root, _, _, _ = owned_directories
        plan_ids = []
        role_orders = {"spec": 0, "plan": 0}
        for record in state["inputs"]:
            if not isinstance(record, dict) or set(record) != {
                "document_id", "role", "source_path", "snapshot_path", "sha256", "byte_length", "input_order"
            }:
                raise ValueError("input record is invalid")
            if not isinstance(record["role"], str) or record["role"] not in {"spec", "plan"}:
                raise ValueError("input role is invalid")
            expected_order = role_orders[record["role"]]
            expected_id = f"{record['role']}-{expected_order + 1:02d}"
            if record["document_id"] != expected_id or record["input_order"] != expected_order:
                raise ValueError("input identity or order is invalid")
            role_orders[record["role"]] += 1
            source_path = Path(record["source_path"])
            if not source_path.is_absolute() or not isinstance(record["byte_length"], int) or isinstance(record["byte_length"], bool) or record["byte_length"] < 0 or not isinstance(record["sha256"], str) or not _DIGEST_PATTERN.fullmatch(record["sha256"]):
                raise ValueError("input metadata is invalid")
            snapshot = _inside(Path(record["snapshot_path"]), inputs_root, "snapshot")
            if not snapshot.is_file() or snapshot.is_symlink():
                raise ValueError("snapshot is not a regular file")
            payload = snapshot.read_bytes()
            try:
                payload.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError("snapshot is not UTF-8") from exc
            if hashlib.sha256(payload).hexdigest() != record["sha256"] or len(payload) != record["byte_length"]:
                raise ValueError("snapshot digest or size changed")
            if record["role"] == "plan":
                plan_ids.append(record["document_id"])

        if len(plan_ids) != len(state["plans"]):
            raise ValueError("plan input count does not match plan state")
        for position, record in enumerate(state["plans"]):
            if not isinstance(record, dict) or set(record) != {
                "plan_id", "status", "starting_commit", "accepted_commit",
                "attempt_count", "controller_launch_count", "checkpoint_count",
                "progress_checkpoint_count", "consecutive_no_progress_slices",
                "progress_fingerprint", "environment_fingerprint",
                "capability_probe_ids", "plan_started_at", "plan_elapsed_seconds",
                "last_known_head", "result_path", "budget",
            }:
                raise ValueError("plan record is invalid")
            if record["plan_id"] != plan_ids[position] or record["status"] not in PLAN_STATUSES:
                raise ValueError("plan identity or status is invalid")
            if not isinstance(record["attempt_count"], int) or isinstance(record["attempt_count"], bool) or record["attempt_count"] < 0:
                raise ValueError("plan attempt count is invalid")
            for name in (
                "controller_launch_count", "checkpoint_count",
                "progress_checkpoint_count", "consecutive_no_progress_slices",
                "plan_elapsed_seconds",
            ):
                value = record[name]
                if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                    raise ValueError(f"plan {name} is invalid")
            for name in ("starting_commit", "accepted_commit", "last_known_head"):
                value = record[name]
                if value is not None and not _SHA_PATTERN.fullmatch(str(value)):
                    raise ValueError(f"plan {name} is invalid")
            for name in ("progress_fingerprint", "environment_fingerprint", "plan_started_at"):
                value = record[name]
                if value is not None and not isinstance(value, str):
                    raise ValueError(f"plan {name} is invalid")
            if (
                not isinstance(record["capability_probe_ids"], list)
                or not all(isinstance(value, str) for value in record["capability_probe_ids"])
            ):
                raise ValueError("plan capability probe IDs are invalid")
            if record["budget"] != DEFAULT_PLAN_BUDGET:
                raise ValueError("plan budget is invalid")
            if record["result_path"] is not None:
                declared_result = Path(record["result_path"])
                if declared_result.is_symlink():
                    raise ValueError("result must not be a symlink")
                result = _inside(declared_result, results_root, "result")
                if not result.is_file():
                    raise ValueError("result must be a regular file")

        self._validate_semantics(plan_ids)

    def _validate_semantics(self, plan_ids: list[str]) -> None:
        state = self.state
        plans = state["plans"]
        if len(plan_ids) != len(plans):
            raise ValueError("plan input count does not match plan state")

        completed_prefix = 0
        for plan in plans:
            if plan["status"] != "completed":
                break
            completed_prefix += 1
        if state["current_plan_index"] != completed_prefix:
            raise ValueError("current plan index does not match completed prefix")

        pristine_fields = {
            "status": "pending",
            "starting_commit": None,
            "accepted_commit": None,
            "attempt_count": 0,
            "controller_launch_count": 0,
            "checkpoint_count": 0,
            "progress_checkpoint_count": 0,
            "consecutive_no_progress_slices": 0,
            "progress_fingerprint": None,
            "environment_fingerprint": None,
            "capability_probe_ids": [],
            "plan_started_at": None,
            "plan_elapsed_seconds": 0,
            "last_known_head": None,
            "result_path": None,
            "budget": dict(DEFAULT_PLAN_BUDGET),
        }
        for position, plan in enumerate(plans):
            if position < completed_prefix:
                if not all(
                    plan[name] is not None
                    for name in ("starting_commit", "accepted_commit", "result_path")
                ):
                    raise ValueError("completed plan evidence is incomplete")
                if plan["attempt_count"] < 1:
                    raise ValueError("completed plan attempt count is invalid")
            elif position > completed_prefix:
                expected = {"plan_id": plan["plan_id"], **pristine_fields}
                if plan != expected:
                    raise ValueError("future plan is not pristine")

        if completed_prefix == len(plans):
            if state["status"] != "completed":
                raise ValueError("all plans complete but run is not completed")
            return

        current = plans[completed_prefix]
        if current["status"] == "pending":
            expected = {"plan_id": current["plan_id"], **pristine_fields}
            if current != expected:
                raise ValueError("pending current plan is not pristine")
        elif (
            current["attempt_count"] < 1
            or current["starting_commit"] is None
            or current["result_path"] is None
            or current["accepted_commit"] is not None
        ):
            raise ValueError("active current plan evidence is incomplete")

        allowed = {
            "preparing": {"pending"},
            "ready": {"pending"},
            "running": {"pending", "running"},
            "checkpointed": {"checkpointed"},
            "blocked": {"blocked"},
            "failed": {"failed", "pending"},
        }
        if current["status"] not in allowed.get(state["status"], set()):
            raise ValueError("run and current plan statuses disagree")

    def save(self) -> None:
        self._validate()
        payload = json.dumps(
            self.state, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        atomic_private_write(self.state_path, payload)

    def append_event(
        self,
        action: str,
        *,
        source: str = "parent_observed",
        **details: object,
    ) -> None:
        if source not in TRUST_LEVELS:
            raise ValueError("event source is invalid")
        if not action or len(action) > 100:
            raise ValueError("event action must be bounded")
        forbidden = {"prompt", "transcript", "raw_output", "environment", "secret", "token"}
        if forbidden & set(details):
            raise ValueError("event contains forbidden content field")
        event = {
            "event_id": uuid.uuid4().hex,
            "at": datetime.now(timezone.utc).isoformat(),
            "source": source,
            "run_id": self.state["run_id"],
            "category": action.split(".", 1)[0],
            "action": action,
            **details,
        }
        encoded = (
            json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
        if len(encoded) > 16_384:
            raise ValueError("event record exceeds the bounded event contract")
        self._append_event_bytes(encoded)

    def _append_event_bytes(self, encoded: bytes) -> None:
        descriptor = os.open(
            self.events_path,
            os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise ValueError("event stream must be a regular file")
            _write_all(descriptor, encoded)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        self.events_path.chmod(0o600)
