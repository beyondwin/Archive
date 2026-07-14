"""Private atomic state and input snapshots for the sequential CPE runner."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence


RUN_STATUSES = {"running", "completed", "blocked", "failed", "interrupted"}
PLAN_STATUSES = {"pending", "running", "completed", "blocked", "failed", "interrupted"}
_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")


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
    """Own one format-version-1 state file beneath a private run root."""

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
    ) -> "StateStore":
        if not plans:
            raise ValueError("at least one plan is required")
        if run_root.exists():
            raise ValueError("run root already exists")
        if not _SHA_PATTERN.fullmatch(source_commit):
            raise ValueError("source commit must be a full Git object ID")
        repository = source_repository.resolve(strict=True)
        if not repository.is_dir() or repository.is_symlink():
            raise ValueError("source repository must be a real directory")
        _private_directory(run_root.parent)
        _private_directory(run_root)
        for name in ("inputs", "results", "logs"):
            _private_directory(run_root / name)

        records: list[dict[str, Any]] = []
        seen: set[Path] = set()
        for role, paths in (("spec", specs), ("plan", plans)):
            for order, declared in enumerate(paths):
                source, payload = _read_document(declared)
                if source in seen:
                    raise ValueError("duplicate input paths are not allowed")
                seen.add(source)
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
                "result_path": None,
            }
            for record in records
            if record["role"] == "plan"
        ]
        state = {
            "format_version": 1,
            "run_id": run_id,
            "status": "running",
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
        store.append_event("run.created", status="running")
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
        if not isinstance(payload, dict) or payload.get("format_version") != 1:
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
        if set(state) != required or state.get("format_version") != 1:
            raise ValueError("invalid format-version-1 state")
        if state["status"] not in RUN_STATUSES:
            raise ValueError("unknown run status")
        if not _SHA_PATTERN.fullmatch(str(state["source_commit"])):
            raise ValueError("invalid source commit")
        if not isinstance(state["inputs"], list) or not isinstance(state["plans"], list) or not state["plans"]:
            raise ValueError("state inputs and plans are invalid")
        index = state["current_plan_index"]
        if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index <= len(state["plans"]):
            raise ValueError("current plan index is invalid")

        inputs_root = self.root / "inputs"
        results_root = self.root / "results"
        plan_ids = []
        for record in state["inputs"]:
            if not isinstance(record, dict) or set(record) != {
                "document_id", "role", "source_path", "snapshot_path", "sha256", "byte_length", "input_order"
            }:
                raise ValueError("input record is invalid")
            if record["role"] not in {"spec", "plan"}:
                raise ValueError("input role is invalid")
            snapshot = _inside(Path(record["snapshot_path"]), inputs_root, "snapshot")
            if not snapshot.is_file() or snapshot.is_symlink():
                raise ValueError("snapshot is not a regular file")
            payload = snapshot.read_bytes()
            if hashlib.sha256(payload).hexdigest() != record["sha256"] or len(payload) != record["byte_length"]:
                raise ValueError("snapshot digest or size changed")
            if record["role"] == "plan":
                plan_ids.append(record["document_id"])

        for position, record in enumerate(state["plans"]):
            if not isinstance(record, dict) or set(record) != {
                "plan_id", "status", "starting_commit", "accepted_commit", "attempt_count", "result_path"
            }:
                raise ValueError("plan record is invalid")
            if record["plan_id"] != plan_ids[position] or record["status"] not in PLAN_STATUSES:
                raise ValueError("plan identity or status is invalid")
            if not isinstance(record["attempt_count"], int) or isinstance(record["attempt_count"], bool) or record["attempt_count"] < 0:
                raise ValueError("plan attempt count is invalid")
            for name in ("starting_commit", "accepted_commit"):
                value = record[name]
                if value is not None and not _SHA_PATTERN.fullmatch(str(value)):
                    raise ValueError(f"plan {name} is invalid")
            if record["result_path"] is not None:
                _inside(Path(record["result_path"]), results_root, "result")

    def save(self) -> None:
        self._validate()
        temporary = self.root / f".state.{os.getpid()}.tmp"
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            payload = json.dumps(self.state, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            os.write(descriptor, payload)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(temporary, self.state_path)
        self.state_path.chmod(0o600)
        directory = os.open(self.root, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    def append_event(self, kind: str, **details: object) -> None:
        if not kind or len(kind) > 100:
            raise ValueError("event kind must be bounded")
        event = {"at": datetime.now(timezone.utc).isoformat(), "kind": kind, **details}
        line = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        descriptor = os.open(self.events_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(descriptor, line.encode("utf-8"))
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        self.events_path.chmod(0o600)
