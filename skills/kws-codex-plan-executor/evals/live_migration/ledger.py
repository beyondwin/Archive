"""Immutable, replayable filesystem ledger for paid-live evaluation evidence."""

from __future__ import annotations

import fcntl
import hmac
import json
import os
import tempfile
import uuid
import re
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import quote

from .contracts import SlotKey, canonical_json, sha256_bytes


EVENT_SCHEMA = "cpe-live-event.v1"
SLOT_INDEX_SCHEMA = "cpe-live-slot-index.v1"
_EVENT_FIELDS = frozenset(
    {
        "schema_version",
        "sequence",
        "timestamp",
        "type",
        "payload",
        "previous_sha256",
        "event_sha256",
    }
)
_RESERVED_SLOT_FILES = frozenset({"index.json", "result.json"})
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TERMINAL_FULL_RUN_EVENT = "terminal_full_run_recorded"
_MAX_TERMINAL_FULL_RUNS = 2


class LedgerError(RuntimeError):
    """Raised when ledger evidence is incomplete, mutable, or corrupt."""


@dataclass(frozen=True)
class LiveRun:
    """Stable handle for one immutable live-migration run."""

    run_dir: Path
    manifest: dict[str, object]
    manifest_sha256: str


def _load_object(path: Path, label: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LedgerError(f"{label} is invalid: {exc}") from exc
    if not isinstance(value, dict):
        raise LedgerError(f"{label} must contain an object")
    return value


def _manifest_digest(manifest: dict[str, object]) -> str:
    supplied = manifest.get("manifest_sha256")
    if not isinstance(supplied, str):
        raise LedgerError("manifest_sha256 is missing")
    body = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    expected = sha256_bytes(canonical_json(body))
    if not hmac.compare_digest(supplied, expected):
        raise LedgerError("manifest_sha256 does not match manifest content")
    return supplied


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@contextmanager
def _locked_run(run_dir: Path) -> Iterator[None]:
    """Serialize all authoritative evidence and projection transitions."""

    try:
        descriptor = os.open(run_dir, os.O_RDONLY)
    except OSError as exc:
        raise LedgerError(f"cannot lock run directory: {exc}") from exc
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical_json(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
        _fsync_directory(path.parent)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def _write_exclusive(path: Path, data: bytes) -> None:
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise LedgerError(f"{path.name} already exists") from exc
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _slot_component(value: str, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise LedgerError(f"{label} must be a non-empty string")
    if value in {".", ".."}:
        raise LedgerError(f"{label} must not be a dot segment")
    return quote(value, safe="-._~")


def _slot_path(run_dir: Path, key: SlotKey) -> Path:
    return (
        run_dir
        / "slots"
        / _slot_component(key.treatment_id, "treatment_id")
        / _slot_component(key.case_id, "case_id")
    )


def _manifest_slots(manifest: dict[str, object]) -> list[SlotKey]:
    raw_slots = manifest.get("slots")
    if not isinstance(raw_slots, list):
        raise LedgerError("manifest slots must be an array")
    slots: list[SlotKey] = []
    seen: set[SlotKey] = set()
    for position, raw in enumerate(raw_slots):
        if not isinstance(raw, dict):
            raise LedgerError(f"manifest slot {position} must be an object")
        treatment_id = raw.get("treatment_id")
        case_id = raw.get("case_id")
        if not isinstance(treatment_id, str) or not isinstance(case_id, str):
            raise LedgerError(f"manifest slot {position} has an invalid key")
        key = SlotKey(treatment_id, case_id)
        _slot_path(Path("."), key)
        if key in seen:
            raise LedgerError(f"manifest contains duplicate slot: {key}")
        seen.add(key)
        slots.append(key)
    return slots


def create_run(root: Path, manifest: dict[str, object]) -> LiveRun:
    """Create an immutable run manifest and return its stable handle."""

    if not isinstance(manifest, dict):
        raise LedgerError("manifest must be an object")
    manifest_copy = dict(manifest)
    manifest_sha256 = _manifest_digest(manifest_copy)
    _manifest_slots(manifest_copy)
    run_dir = Path(root)
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = run_dir / "manifest.json"
    _write_exclusive(manifest_path, canonical_json(manifest_copy))
    try:
        (run_dir / "slots").mkdir(exist_ok=True)
        _fsync_directory(run_dir)
    except BaseException:
        manifest_path.unlink(missing_ok=True)
        raise
    return LiveRun(run_dir, manifest_copy, manifest_sha256)


def _read_manifest(run_dir: Path) -> LiveRun:
    manifest = _load_object(run_dir / "manifest.json", "manifest.json")
    digest = _manifest_digest(manifest)
    _manifest_slots(manifest)
    return LiveRun(run_dir, manifest, digest)


def _replay_event_lines(lines: list[str]) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    previous_sha256: str | None = None
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            raise LedgerError(f"events.jsonl line {line_number} is empty")
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise LedgerError(f"events.jsonl line {line_number} is invalid JSON") from exc
        if not isinstance(event, dict) or set(event) != _EVENT_FIELDS:
            raise LedgerError(f"events.jsonl line {line_number} has invalid fields")
        if event["schema_version"] != EVENT_SCHEMA:
            raise LedgerError(f"events.jsonl line {line_number} has invalid schema")
        if event["sequence"] != line_number:
            raise LedgerError(f"events.jsonl line {line_number} has invalid sequence")
        if not isinstance(event["timestamp"], str) or not event["timestamp"]:
            raise LedgerError(f"events.jsonl line {line_number} has invalid timestamp")
        if not isinstance(event["type"], str) or not event["type"]:
            raise LedgerError(f"events.jsonl line {line_number} has invalid type")
        if not isinstance(event["payload"], dict):
            raise LedgerError(f"events.jsonl line {line_number} has invalid payload")
        if event["previous_sha256"] != previous_sha256:
            raise LedgerError(f"events.jsonl line {line_number} breaks the hash chain")
        body = {key: event[key] for key in _EVENT_FIELDS if key != "event_sha256"}
        expected = sha256_bytes(canonical_json(body))
        digest = event["event_sha256"]
        if not isinstance(digest, str) or not hmac.compare_digest(digest, expected):
            raise LedgerError(f"events.jsonl line {line_number} has invalid digest")
        events.append(event)
        previous_sha256 = digest
    return events


def _read_events_locked(stream: Any) -> list[dict[str, object]]:
    stream.seek(0)
    return _replay_event_lines(stream.readlines())


def append_event(
    run: LiveRun,
    event_type: str,
    payload: dict[str, object],
) -> dict[str, object]:
    """Append one fsynced canonical event to the strict hash chain."""

    if not isinstance(run, LiveRun):
        raise LedgerError("run must be a LiveRun")
    if not isinstance(event_type, str) or not event_type:
        raise LedgerError("event_type must be a non-empty string")
    if not isinstance(payload, dict):
        raise LedgerError("event payload must be an object")

    with _locked_run(run.run_dir):
        event = _append_event_locked(run, event_type, payload)
        _replay_run_locked(run.run_dir)
        return event


def record_terminal_full_run(
    run: LiveRun,
    *,
    checkpoint_sha256: str,
    passed: bool,
) -> dict[str, object]:
    """Record the initial terminal run or its sole corrected rerun."""

    if not isinstance(run, LiveRun):
        raise LedgerError("run must be a LiveRun")
    if not isinstance(checkpoint_sha256, str) or _SHA256.fullmatch(checkpoint_sha256) is None:
        raise LedgerError("terminal full run requires a SHA-256 checkpoint")
    if type(passed) is not bool:
        raise LedgerError("terminal full run passed must be boolean")
    with _locked_run(run.run_dir):
        projection = _replay_run_locked(run.run_dir)
        terminal_runs = int(projection["terminal_full_runs"])
        if terminal_runs >= _MAX_TERMINAL_FULL_RUNS:
            raise LedgerError("terminal full run limit reached")
        if terminal_runs and projection["terminal_full_run_passed"] is True:
            raise LedgerError("a passed terminal full run cannot be rerun")
        previous_checkpoint = projection["terminal_full_run_checkpoint_sha256"]
        if terminal_runs and previous_checkpoint == checkpoint_sha256:
            raise LedgerError("corrected terminal full run requires a changed checkpoint")
        event = _append_event_locked(
            run,
            _TERMINAL_FULL_RUN_EVENT,
            {
                "run_number": terminal_runs + 1,
                "checkpoint_sha256": checkpoint_sha256,
                "passed": passed,
            },
        )
        _replay_run_locked(run.run_dir)
        return event


def _append_event_locked(
    run: LiveRun,
    event_type: str,
    payload: dict[str, object],
    *,
    allow_slot_completed: bool = False,
) -> dict[str, object]:
    current = _read_manifest(run.run_dir)
    if current.manifest_sha256 != run.manifest_sha256:
        raise LedgerError("run manifest differs from the LiveRun handle")

    events_path = run.run_dir / "events.jsonl"
    try:
        with events_path.open("a+", encoding="utf-8") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            events = _read_events_locked(stream)
            body: dict[str, object] = {
                "schema_version": EVENT_SCHEMA,
                "sequence": len(events) + 1,
                "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "type": event_type,
                "payload": dict(payload),
                "previous_sha256": events[-1]["event_sha256"] if events else None,
            }
            event = {**body, "event_sha256": sha256_bytes(canonical_json(body))}
            _validate_event_semantics(
                current.manifest,
                [*events, event],
                allow_slot_completed=allow_slot_completed,
            )
            stream.seek(0, os.SEEK_END)
            stream.write(canonical_json(event).decode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
            return event
    except (OSError, UnicodeDecodeError) as exc:
        raise LedgerError(f"cannot append events.jsonl: {exc}") from exc


def commit_slot(
    run: LiveRun,
    key: SlotKey,
    files: dict[str, bytes],
    result: dict[str, object],
) -> None:
    """Atomically publish digest-indexed slot evidence, then journal completion."""

    if not isinstance(run, LiveRun):
        raise LedgerError("run must be a LiveRun")
    with _locked_run(run.run_dir):
        _commit_slot_locked(run, key, files, result)
        _replay_run_locked(run.run_dir)


def _commit_slot_locked(
    run: LiveRun,
    key: SlotKey,
    files: dict[str, bytes],
    result: dict[str, object],
) -> None:

    if not isinstance(key, SlotKey):
        raise LedgerError("key must be a SlotKey")
    current = _read_manifest(run.run_dir)
    if current.manifest_sha256 != run.manifest_sha256:
        raise LedgerError("run manifest differs from the LiveRun handle")
    if key not in set(_manifest_slots(current.manifest)):
        raise LedgerError(f"slot is not present in the manifest: {key}")
    if not isinstance(files, dict) or not files:
        raise LedgerError("slot files must be a non-empty object")
    if not isinstance(result, dict):
        raise LedgerError("slot result must be an object")
    for name, contents in files.items():
        if (
            not isinstance(name, str)
            or not name
            or Path(name).name != name
            or name in _RESERVED_SLOT_FILES
        ):
            raise LedgerError(f"invalid slot artifact name: {name!r}")
        if not isinstance(contents, bytes):
            raise LedgerError(f"slot artifact {name} must be bytes")

    final_path = _slot_path(run.run_dir, key)
    if final_path.exists():
        raise LedgerError(f"slot evidence already exists: {key}")
    slots_path = run.run_dir / "slots"
    slots_path.mkdir(exist_ok=True)
    temporary_path = slots_path / f".partial-{uuid.uuid4().hex}"
    temporary_path.mkdir(mode=0o700)
    try:
        file_digests: dict[str, str] = {}
        for name, contents in sorted(files.items()):
            _write_exclusive(temporary_path / name, contents)
            file_digests[name] = sha256_bytes(contents)
        result_bytes = canonical_json(result)
        _write_exclusive(temporary_path / "result.json", result_bytes)
        index_body: dict[str, object] = {
            "schema_version": SLOT_INDEX_SCHEMA,
            "treatment_id": key.treatment_id,
            "case_id": key.case_id,
            "files": file_digests,
            "result_sha256": sha256_bytes(result_bytes),
        }
        index = {
            **index_body,
            "slot_sha256": sha256_bytes(canonical_json(index_body)),
        }
        _write_exclusive(temporary_path / "index.json", canonical_json(index))
        _fsync_directory(temporary_path)
        final_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            temporary_path.rename(final_path)
        except FileExistsError as exc:
            raise LedgerError(f"slot evidence already exists: {key}") from exc
        _fsync_directory(final_path.parent)
    except BaseException:
        if temporary_path.exists():
            for child in temporary_path.iterdir():
                child.unlink()
            temporary_path.rmdir()
        raise

    _append_event_locked(
        run,
        "slot_completed",
        {
            "treatment_id": key.treatment_id,
            "case_id": key.case_id,
            "slot_sha256": index["slot_sha256"],
            "result_sha256": index["result_sha256"],
        },
        allow_slot_completed=True,
    )


def _event_slot_key(event: dict[str, object]) -> SlotKey:
    payload = event["payload"]
    assert isinstance(payload, dict)
    treatment_id = payload.get("treatment_id")
    case_id = payload.get("case_id")
    if not isinstance(treatment_id, str) or not isinstance(case_id, str):
        raise LedgerError(f"{event['type']} event has an invalid slot key")
    return SlotKey(treatment_id, case_id)


def _validate_event_semantics(
    manifest: dict[str, object],
    events: list[dict[str, object]],
    *,
    allow_slot_completed: bool,
) -> None:
    """Reject a candidate event sequence before any new bytes become durable."""

    slot_set = set(_manifest_slots(manifest))
    active: SlotKey | None = None
    completed: set[SlotKey] = set()
    terminal_checkpoints: list[str] = []
    terminal_passed = False
    for position, event in enumerate(events):
        event_type = event["type"]
        if event_type == _TERMINAL_FULL_RUN_EVENT:
            payload = event["payload"]
            assert isinstance(payload, dict)
            checkpoint = payload.get("checkpoint_sha256")
            passed = payload.get("passed")
            if (
                set(payload) != {"run_number", "checkpoint_sha256", "passed"}
                or payload.get("run_number") != len(terminal_checkpoints) + 1
                or not isinstance(checkpoint, str)
                or _SHA256.fullmatch(checkpoint) is None
                or type(passed) is not bool
            ):
                raise LedgerError("terminal full run event is invalid")
            if len(terminal_checkpoints) >= _MAX_TERMINAL_FULL_RUNS:
                raise LedgerError("terminal full run limit exceeded")
            if terminal_passed:
                raise LedgerError("a passed terminal full run cannot be rerun")
            if terminal_checkpoints and checkpoint == terminal_checkpoints[-1]:
                raise LedgerError("corrected terminal full run requires a changed checkpoint")
            terminal_checkpoints.append(checkpoint)
            terminal_passed = passed
            continue
        if event_type not in {
            "slot_started",
            "slot_retry_started",
            "slot_failed",
            "slot_completed",
        }:
            continue
        if (
            position == len(events) - 1
            and event_type == "slot_completed"
            and not allow_slot_completed
        ):
            raise LedgerError("slot_completed events must be created by commit_slot")
        key = _event_slot_key(event)
        if key not in slot_set:
            raise LedgerError(f"event references a slot outside the manifest: {key}")
        if event_type in {"slot_started", "slot_retry_started"}:
            if active is not None and active != key:
                raise LedgerError("multiple slots are active in the event replay")
            if key in completed:
                raise LedgerError(f"completed slot cannot be restarted: {key}")
            active = key
        elif event_type == "slot_failed":
            if active == key:
                active = None
        else:
            if key in completed:
                raise LedgerError(f"slot has duplicate completion events: {key}")
            completed.add(key)
            if active == key:
                active = None


def _validate_completed_slot(
    run_dir: Path,
    key: SlotKey,
    event: dict[str, object],
) -> None:
    slot_path = _slot_path(run_dir, key)
    if not slot_path.is_dir() or slot_path.is_symlink():
        raise LedgerError(f"completed slot evidence is missing: {key}")
    index = _load_object(slot_path / "index.json", f"slot index for {key}")
    required_index = {
        "schema_version",
        "treatment_id",
        "case_id",
        "files",
        "result_sha256",
        "slot_sha256",
    }
    if set(index) != required_index or index.get("schema_version") != SLOT_INDEX_SCHEMA:
        raise LedgerError(f"slot index has invalid fields: {key}")
    if index.get("treatment_id") != key.treatment_id or index.get("case_id") != key.case_id:
        raise LedgerError(f"slot index key mismatch: {key}")
    index_body = {name: value for name, value in index.items() if name != "slot_sha256"}
    expected_slot_digest = sha256_bytes(canonical_json(index_body))
    slot_digest = index.get("slot_sha256")
    if not isinstance(slot_digest, str) or not hmac.compare_digest(
        slot_digest, expected_slot_digest
    ):
        raise LedgerError(f"slot index digest mismatch: {key}")

    file_digests = index.get("files")
    if not isinstance(file_digests, dict) or not file_digests:
        raise LedgerError(f"slot index files are invalid: {key}")
    expected_names = set(file_digests) | _RESERVED_SLOT_FILES
    children = list(slot_path.iterdir())
    if (
        any(not child.is_file() or child.is_symlink() for child in children)
        or {child.name for child in children} != expected_names
    ):
        raise LedgerError(f"slot evidence is incomplete or malformed: {key}")
    for name, digest in file_digests.items():
        if not isinstance(name, str) or not isinstance(digest, str):
            raise LedgerError(f"slot artifact index is invalid: {key}")
        actual = sha256_bytes((slot_path / name).read_bytes())
        if not hmac.compare_digest(actual, digest):
            raise LedgerError(f"slot artifact digest mismatch: {key}/{name}")
    result_digest = sha256_bytes((slot_path / "result.json").read_bytes())
    indexed_result_digest = index.get("result_sha256")
    if not isinstance(indexed_result_digest, str) or not hmac.compare_digest(
        result_digest, indexed_result_digest
    ):
        raise LedgerError(f"slot result digest mismatch: {key}")
    payload = event["payload"]
    assert isinstance(payload, dict)
    if payload.get("slot_sha256") != slot_digest:
        raise LedgerError(f"slot completion digest mismatch: {key}")
    if payload.get("result_sha256") != indexed_result_digest:
        raise LedgerError(f"slot completion result digest mismatch: {key}")


def _key_object(key: SlotKey) -> dict[str, str]:
    return {"treatment_id": key.treatment_id, "case_id": key.case_id}


def replay_run(run_dir: Path) -> dict[str, object]:
    """Validate authoritative evidence, derive state, and atomically repair drift."""

    root = Path(run_dir)
    with _locked_run(root):
        return _replay_run_locked(root)


def _replay_run_locked(root: Path) -> dict[str, object]:
    run = _read_manifest(root)
    slots = _manifest_slots(run.manifest)
    slot_set = set(slots)
    events_path = root / "events.jsonl"
    try:
        if events_path.exists():
            with events_path.open("r", encoding="utf-8") as stream:
                fcntl.flock(stream.fileno(), fcntl.LOCK_SH)
                events = _read_events_locked(stream)
        else:
            events = []
    except (OSError, UnicodeDecodeError) as exc:
        raise LedgerError(f"events.jsonl is unreadable: {exc}") from exc

    _validate_event_semantics(run.manifest, events, allow_slot_completed=True)

    status: dict[SlotKey, str] = {}
    active: SlotKey | None = None
    completed_events: dict[SlotKey, dict[str, object]] = {}
    lifecycle_outcome: object = None
    terminal_full_runs = 0
    terminal_full_failures = 0
    terminal_full_run_passed = False
    terminal_full_run_checkpoint_sha256: str | None = None
    for event in events:
        event_type = event["type"]
        if event_type in {"slot_started", "slot_retry_started", "slot_failed", "slot_completed"}:
            key = _event_slot_key(event)
            if key not in slot_set:
                raise LedgerError(f"event references a slot outside the manifest: {key}")
            if event_type in {"slot_started", "slot_retry_started"}:
                if active is not None and active != key:
                    raise LedgerError("multiple slots are active in the event replay")
                active = key
                status[key] = "active"
            elif event_type == "slot_failed":
                status[key] = "failed"
                if active == key:
                    active = None
            else:
                if key in completed_events:
                    raise LedgerError(f"slot has duplicate completion events: {key}")
                status[key] = "completed"
                completed_events[key] = event
                if active == key:
                    active = None
        elif event_type == "run_completed":
            lifecycle_outcome = "completed"
        elif event_type == "run_failed":
            lifecycle_outcome = "failed"
        elif event_type in {"run_blocked", "run_stopped"}:
            lifecycle_outcome = "blocked"
        elif event_type == _TERMINAL_FULL_RUN_EVENT:
            payload = event["payload"]
            assert isinstance(payload, dict)
            terminal_full_runs += 1
            terminal_full_run_passed = bool(payload["passed"])
            terminal_full_run_checkpoint_sha256 = str(payload["checkpoint_sha256"])
            if not terminal_full_run_passed:
                terminal_full_failures += 1

    for key, event in completed_events.items():
        _validate_completed_slot(root, key, event)

    expected_paths = {_slot_path(root, key) for key in completed_events}
    slots_path = root / "slots"
    actual_paths: set[Path] = set()
    if slots_path.exists():
        for treatment_path in slots_path.iterdir():
            if treatment_path.name.startswith(".partial-"):
                continue
            if not treatment_path.is_dir() or treatment_path.is_symlink():
                raise LedgerError(f"invalid treatment evidence path: {treatment_path.name}")
            for slot_path in treatment_path.iterdir():
                if not slot_path.is_dir() or slot_path.is_symlink():
                    raise LedgerError(f"invalid slot evidence path: {slot_path}")
                actual_paths.add(slot_path)
    if actual_paths != expected_paths:
        raise LedgerError("published slot directories do not match completion events")

    completed = [key for key in slots if status.get(key) == "completed"]
    failed = [key for key in slots if status.get(key) == "failed"]
    pending = [key for key in slots if key not in set(completed + failed) and key != active]
    projection: dict[str, object] = {
        "manifest_sha256": run.manifest_sha256,
        "event_count": len(events),
        "last_event_sha256": events[-1]["event_sha256"] if events else None,
        "pending_slots": [_key_object(key) for key in pending],
        "completed_slots": [_key_object(key) for key in completed],
        "failed_slots": [_key_object(key) for key in failed],
        "active_slot": _key_object(active) if active is not None else None,
        "lifecycle_outcome": lifecycle_outcome,
        "terminal_full_runs": terminal_full_runs,
        "terminal_full_failures": terminal_full_failures,
        "terminal_full_run_passed": terminal_full_run_passed,
        "terminal_full_run_checkpoint_sha256": terminal_full_run_checkpoint_sha256,
        "release_blocked": terminal_full_failures >= _MAX_TERMINAL_FULL_RUNS,
    }
    state_path = root / "state.json"
    expected_state = canonical_json(projection)
    try:
        current_state = state_path.read_bytes() if state_path.exists() else None
    except OSError as exc:
        raise LedgerError(f"state.json is unreadable: {exc}") from exc
    if current_state != expected_state:
        _atomic_json(state_path, projection)
    return projection
