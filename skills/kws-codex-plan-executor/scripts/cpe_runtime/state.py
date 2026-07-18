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


FORMAT_VERSION = 3
DEFAULT_SANDBOX_MODE = "danger-full-access"
DEFAULT_CONTROLLER_SLICE_SECONDS = 1200
MIN_CONTROLLER_SLICE_SECONDS = 1200
MAX_CONTROLLER_SLICE_SECONDS = 3600
SANDBOX_MODES = {"danger-full-access", "workspace-write"}
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
    "controller_slice_timeout_seconds": DEFAULT_CONTROLLER_SLICE_SECONDS,
    "max_progress_checkpoints": 6,
    "plan_wall_budget_seconds": 7200,
    "max_controller_launches": 6,
}
PRE_EXECUTION_WORKTREE_BLOCKER = {
    "kind": "verification_environment",
    "code": "worktree_creation_failed",
    "operation": "create_or_reconcile_worktree",
    "owner": "operator",
}
_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
_DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_DECISION_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_DECISION_REASONS = {
    "continue": {"productive_timeout", "first_no_progress_slice"},
    "checkpoint": {"child_checkpointed"},
    "block": {"child_blocked"},
    "fail": {"child_failed"},
    "stop_stalled": {"second_no_progress_slice", "child_stopped_without_completion"},
    "stop_budget": {
        "checkpoint_budget_exhausted",
        "launch_budget_exhausted",
        "wall_budget_exhausted",
    },
    "finish": {"child_completed"},
}


def validate_run_config(
    *, sandbox_mode: object, controller_slice_seconds: object,
) -> dict[str, object]:
    if sandbox_mode not in SANDBOX_MODES:
        raise ValueError("controller sandbox is invalid")
    if (
        not isinstance(controller_slice_seconds, int)
        or isinstance(controller_slice_seconds, bool)
        or not MIN_CONTROLLER_SLICE_SECONDS
        <= controller_slice_seconds
        <= MAX_CONTROLLER_SLICE_SECONDS
    ):
        raise ValueError("controller slice must be between 1200 and 3600 seconds")
    return {
        "sandbox_mode": sandbox_mode,
        "controller_slice_seconds": controller_slice_seconds,
    }


def _plan_budget(run_config: dict[str, object]) -> dict[str, int]:
    return {
        **DEFAULT_PLAN_BUDGET,
        "controller_slice_timeout_seconds": int(
            run_config["controller_slice_seconds"]
        ),
    }


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
    """Own one format-version-3 state file beneath a private run root."""

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
        sandbox_mode: str = DEFAULT_SANDBOX_MODE,
        controller_slice_seconds: int = DEFAULT_CONTROLLER_SLICE_SECONDS,
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
        run_config = validate_run_config(
            sandbox_mode=sandbox_mode,
            controller_slice_seconds=controller_slice_seconds,
        )
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
                "execution_ledger_event_digests": [],
                "pending_checkpoint_decision": None,
                "environment_fingerprint": None,
                "capability_probe_ids": [],
                "plan_started_at": None,
                "plan_elapsed_seconds": 0,
                "last_known_head": None,
                "result_path": None,
                "original_result_path": None,
                "budget": _plan_budget(run_config),
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
            "run_config": run_config,
            "current_plan_index": 0,
            "inputs": records,
            "plans": plan_records,
            "pre_execution_blocker": None,
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
        if version in {1, 2}:
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
            "run_config",
            "pre_execution_blocker",
        }
        if set(state) != required or state.get("format_version") != FORMAT_VERSION:
            raise ValueError("invalid format-version-3 state")
        run_config = state["run_config"]
        if not isinstance(run_config, dict) or set(run_config) != {
            "sandbox_mode", "controller_slice_seconds",
        }:
            raise ValueError("run config is invalid")
        if validate_run_config(**run_config) != run_config:
            raise ValueError("run config is invalid")
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
        blocker = state["pre_execution_blocker"]
        if blocker is not None and blocker != PRE_EXECUTION_WORKTREE_BLOCKER:
            raise ValueError("pre-execution blocker is invalid")
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
                "progress_fingerprint", "execution_ledger_event_digests",
                "pending_checkpoint_decision", "environment_fingerprint",
                "capability_probe_ids", "plan_started_at", "plan_elapsed_seconds",
                "last_known_head", "result_path", "original_result_path", "budget",
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
            for name in ("progress_fingerprint", "environment_fingerprint"):
                value = record[name]
                if value is not None and (
                    not isinstance(value, str) or not _DIGEST_PATTERN.fullmatch(value)
                ):
                    raise ValueError(f"plan {name} is invalid")
            if record["plan_started_at"] is not None and not isinstance(
                record["plan_started_at"], str,
            ):
                raise ValueError("plan plan_started_at is invalid")
            event_digests = record["execution_ledger_event_digests"]
            if (
                not isinstance(event_digests, list)
                or len(event_digests) > 4096
                or not all(
                    isinstance(value, str) and _DIGEST_PATTERN.fullmatch(value)
                    for value in event_digests
                )
                or len(event_digests) != len(set(event_digests))
            ):
                raise ValueError("plan execution ledger event digests are invalid")
            pending = record["pending_checkpoint_decision"]
            if pending is not None:
                pending_fields = {
                    "decision_id", "plan_id", "attempt", "decision", "reason",
                    "progress_fingerprint", "previous_progress_fingerprint",
                    "timed_out", "head", "evidence_manifest_sha256",
                }
                if (
                    not isinstance(pending, dict)
                    or set(pending) != pending_fields
                    or not isinstance(pending["decision_id"], str)
                    or not _DECISION_ID_PATTERN.fullmatch(pending["decision_id"])
                    or pending["plan_id"] != record["plan_id"]
                    or not isinstance(pending["attempt"], int)
                    or isinstance(pending["attempt"], bool)
                    or pending["attempt"] != record["attempt_count"]
                    or pending["decision"] not in _DECISION_REASONS
                    or pending["reason"] not in _DECISION_REASONS[pending["decision"]]
                    or not isinstance(pending["progress_fingerprint"], str)
                    or not _DIGEST_PATTERN.fullmatch(pending["progress_fingerprint"])
                    or not isinstance(pending["previous_progress_fingerprint"], str)
                    or not _DIGEST_PATTERN.fullmatch(
                        pending["previous_progress_fingerprint"]
                    )
                    or pending["previous_progress_fingerprint"]
                    != record["progress_fingerprint"]
                    or not isinstance(pending["timed_out"], bool)
                    or not isinstance(pending["head"], str)
                    or not _SHA_PATTERN.fullmatch(pending["head"])
                    or pending["head"] != record["last_known_head"]
                    or (
                        pending["decision"] == "finish"
                        and (
                            not isinstance(pending["evidence_manifest_sha256"], str)
                            or not _DIGEST_PATTERN.fullmatch(
                                pending["evidence_manifest_sha256"]
                            )
                        )
                    )
                    or (
                        pending["decision"] != "finish"
                        and pending["evidence_manifest_sha256"] is not None
                    )
                    or (
                        pending["timed_out"]
                        and pending["decision"] not in {
                            "continue", "stop_stalled", "stop_budget",
                        }
                    )
                    or (
                        not pending["timed_out"]
                        and (
                            pending["decision"] == "continue"
                            or (
                                pending["decision"] == "stop_stalled"
                                and pending["reason"]
                                != "child_stopped_without_completion"
                            )
                        )
                    )
                    or state["status"] != "running"
                    or record["status"] != "running"
                    or position != state["current_plan_index"]
                ):
                    raise ValueError("pending checkpoint decision is invalid")
            if (
                not isinstance(record["capability_probe_ids"], list)
                or not all(isinstance(value, str) for value in record["capability_probe_ids"])
            ):
                raise ValueError("plan capability probe IDs are invalid")
            budget = record["budget"]
            if (
                not isinstance(budget, dict)
                or set(budget) != set(DEFAULT_PLAN_BUDGET)
                or not all(
                    isinstance(value, int) and not isinstance(value, bool)
                    for value in budget.values()
                )
                or budget != _plan_budget(run_config)
            ):
                raise ValueError("plan budget is invalid")
            if pending is not None:
                changed = (
                    pending["progress_fingerprint"]
                    != pending["previous_progress_fingerprint"]
                )
                checkpoints_exhausted = (
                    record["progress_checkpoint_count"]
                    >= budget["max_progress_checkpoints"]
                )
                launches_exhausted = (
                    record["controller_launch_count"]
                    >= budget["max_controller_launches"]
                )
                wall_exhausted = (
                    record["plan_elapsed_seconds"]
                    >= budget["plan_wall_budget_seconds"]
                )
                reason = pending["reason"]
                reason_matches_state = {
                    "child_completed": not pending["timed_out"],
                    "child_checkpointed": (
                        not pending["timed_out"]
                        and not checkpoints_exhausted
                        and not launches_exhausted
                        and not wall_exhausted
                    ),
                    "child_blocked": not pending["timed_out"],
                    "child_failed": not pending["timed_out"],
                    "productive_timeout": (
                        pending["timed_out"]
                        and changed
                        and not checkpoints_exhausted
                        and not launches_exhausted
                        and not wall_exhausted
                    ),
                    "first_no_progress_slice": (
                        pending["timed_out"]
                        and not changed
                        and record["consecutive_no_progress_slices"] == 0
                        and not checkpoints_exhausted
                        and not launches_exhausted
                        and not wall_exhausted
                    ),
                    "second_no_progress_slice": (
                        pending["timed_out"]
                        and not changed
                        and record["consecutive_no_progress_slices"] >= 1
                        and not checkpoints_exhausted
                        and not launches_exhausted
                        and not wall_exhausted
                    ),
                    "child_stopped_without_completion": (
                        not pending["timed_out"]
                        and not checkpoints_exhausted
                        and not launches_exhausted
                        and not wall_exhausted
                    ),
                    "checkpoint_budget_exhausted": checkpoints_exhausted,
                    "launch_budget_exhausted": (
                        not checkpoints_exhausted and launches_exhausted
                    ),
                    "wall_budget_exhausted": (
                        not checkpoints_exhausted
                        and not launches_exhausted
                        and wall_exhausted
                    ),
                }.get(reason, False)
                if not reason_matches_state:
                    raise ValueError("pending checkpoint decision is invalid")
            if record["result_path"] is not None:
                declared_result = Path(record["result_path"])
                if declared_result.is_symlink():
                    raise ValueError("result must not be a symlink")
                result = _inside(declared_result, results_root, "result")
                if not result.is_file():
                    raise ValueError("result must be a regular file")
            original_result_path = record["original_result_path"]
            if original_result_path is not None:
                if record["result_path"] is None:
                    raise ValueError("original result requires a repaired result")
                declared_original = Path(original_result_path)
                if declared_original.is_symlink():
                    raise ValueError("original result must not be a symlink")
                original = _inside(
                    declared_original, results_root, "original result",
                )
                if not original.is_file() or original == result:
                    raise ValueError("original result must be a distinct regular file")
                try:
                    result.relative_to(results_root / "repaired")
                except ValueError as exc:
                    raise ValueError(
                        "repaired result is outside the repaired result root"
                    ) from exc

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
            "execution_ledger_event_digests": [],
            "pending_checkpoint_decision": None,
            "environment_fingerprint": None,
            "capability_probe_ids": [],
            "plan_started_at": None,
            "plan_elapsed_seconds": 0,
            "last_known_head": None,
            "result_path": None,
            "original_result_path": None,
            "budget": _plan_budget(state["run_config"]),
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
            if state["pre_execution_blocker"] is not None:
                raise ValueError("completed run cannot retain a pre-execution blocker")
            if state["status"] not in {"completed", "failed"}:
                raise ValueError("all plans complete but run is not terminal")
            return

        current = plans[completed_prefix]
        if state["pre_execution_blocker"] is not None:
            expected = {"plan_id": current["plan_id"], **pristine_fields}
            expected["status"] = "blocked"
            if (
                state["status"] != "blocked"
                or current != expected
            ):
                raise ValueError("pre-execution blocker state is invalid")
        elif current["status"] == "pending":
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
        reserved = {"event_id", "at", "source", "run_id", "category", "action"}
        if reserved & set(details):
            raise ValueError("event contains reserved envelope field")
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
