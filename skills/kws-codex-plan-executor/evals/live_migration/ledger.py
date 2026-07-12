"""Immutable, replayable filesystem ledger for paid-live evaluation evidence."""

from __future__ import annotations

import fcntl
import hmac
import json
import os
import shutil
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
_RELEASE_EVENT_SCHEMA = "cpe-quality-release-event.v4"
_RELEASE_EVENT_FIELDS = _EVENT_FIELDS
_RELEASE_EVENTS_FILE = "quality-release-events.jsonl"
_RELEASE_STATE_FILE = "quality-release-state.json"
_RELEASE_MANIFEST_DIR = "quality-release-manifests"
PREDECESSOR_ATTESTATION_SCHEMA = "cpe-quality-predecessor-attestation.v1"
PREDECESSOR_ATTESTATION_DOMAIN = "cpe-quality-predecessor-attestation.v1"
_PREDECESSOR_ATTESTATION_FILE = "quality-release-predecessor.json"
_PREDECESSOR_EVENT = "predecessor_release_attested"
_FINALIZED_EVENT = "release_evidence_finalized"
_GENERATION_DIR = "release-generations"
_GENERATION_FILES = (
    "checkpoint.json",
    "manifest.json",
    "result.json",
    "privacy-audit.json",
    "dogfood-result.json",
)
_PREDECESSOR_DIGEST_FIELDS = frozenset(
    {
        "predecessor_event_sha256",
        "predecessor_events_sha256",
        "predecessor_state_sha256",
        "predecessor_manifest_sha256",
        "predecessor_manifest_artifact_sha256",
        "predecessor_aggregate_sha256",
        "predecessor_aggregate_artifact_sha256",
        "predecessor_privacy_sha256",
        "predecessor_privacy_artifact_sha256",
        "attestation_sha256",
    }
)


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


def _read_release_events(root: Path) -> list[dict[str, object]]:
    path = root / _RELEASE_EVENTS_FILE
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise LedgerError(f"release lineage is unreadable: {exc}") from exc
    events: list[dict[str, object]] = []
    previous: str | None = None
    for sequence, line in enumerate(lines, start=1):
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise LedgerError("release lineage contains invalid JSON") from exc
        if not isinstance(event, dict) or set(event) != _RELEASE_EVENT_FIELDS:
            raise LedgerError("release lineage event fields are invalid")
        if (
            event.get("schema_version") != _RELEASE_EVENT_SCHEMA
            or event.get("sequence") != sequence
            or event.get("previous_sha256") != previous
            or not isinstance(event.get("payload"), dict)
        ):
            raise LedgerError("release lineage event chain is invalid")
        body = {key: event[key] for key in _RELEASE_EVENT_FIELDS if key != "event_sha256"}
        digest = sha256_bytes(canonical_json(body))
        if event.get("event_sha256") != digest:
            raise LedgerError("release lineage event digest is invalid")
        events.append(event)
        previous = digest
    return events


def _validate_predecessor_artifact(
    artifact: dict[str, object]
) -> dict[str, object]:
    required = {
        "schema_version",
        "domain",
        *_PREDECESSOR_DIGEST_FIELDS,
        "terminal_full_runs",
        "terminal_full_failures",
        "prior_checkpoint",
        "implementation_commit",
        "implementation_tree",
        "implementation_patch_sha256",
    }
    if set(artifact) != required:
        raise LedgerError("predecessor attestation fields are invalid")
    if (
        artifact.get("schema_version") != PREDECESSOR_ATTESTATION_SCHEMA
        or artifact.get("domain") != PREDECESSOR_ATTESTATION_DOMAIN
        or artifact.get("terminal_full_runs") != 1
        or artifact.get("terminal_full_failures") != 1
    ):
        raise LedgerError("predecessor attestation contract is invalid")
    if any(
        not isinstance(artifact.get(field), str)
        or _SHA256.fullmatch(str(artifact[field])) is None
        for field in _PREDECESSOR_DIGEST_FIELDS
    ):
        raise LedgerError("predecessor attestation digest is invalid")
    if (
        not isinstance(artifact.get("implementation_commit"), str)
        or re.fullmatch(r"[0-9a-f]{40}", str(artifact["implementation_commit"])) is None
        or not isinstance(artifact.get("implementation_tree"), str)
        or re.fullmatch(r"[0-9a-f]{40}", str(artifact["implementation_tree"])) is None
        or artifact.get("implementation_patch_sha256") != artifact.get("prior_checkpoint")
        or _SHA256.fullmatch(str(artifact.get("prior_checkpoint", ""))) is None
    ):
        raise LedgerError("predecessor implementation identity is invalid")
    body = {key: value for key, value in artifact.items() if key != "attestation_sha256"}
    expected_attestation = sha256_bytes(
        canonical_json({"domain": PREDECESSOR_ATTESTATION_DOMAIN, "body": body})
    )
    if not hmac.compare_digest(str(artifact["attestation_sha256"]), expected_attestation):
        raise LedgerError("predecessor attestation domain binding is invalid")
    return artifact


def _validate_predecessor_attestation(
    root: Path, event: dict[str, object]
) -> dict[str, object]:
    artifact_path = root / _PREDECESSOR_ATTESTATION_FILE
    if not artifact_path.is_file() or artifact_path.is_symlink():
        raise LedgerError("predecessor attestation artifact is missing")
    artifact = _validate_predecessor_artifact(
        _load_object(artifact_path, _PREDECESSOR_ATTESTATION_FILE)
    )
    payload = event.get("payload")
    if not isinstance(payload, dict) or set(payload) != {
        "attestation_sha256",
        "artifact_sha256",
        "predecessor_event_sha256",
    }:
        raise LedgerError("predecessor attestation event payload is invalid")
    artifact_sha256 = sha256_bytes(canonical_json(artifact))
    if (
        payload.get("attestation_sha256") != artifact.get("attestation_sha256")
        or payload.get("artifact_sha256") != artifact_sha256
        or payload.get("predecessor_event_sha256")
        != artifact.get("predecessor_event_sha256")
    ):
        raise LedgerError("predecessor attestation event differs from its artifact")
    return artifact


def _release_projection(
    events: list[dict[str, object]], root: Path
) -> dict[str, object]:
    runs: list[dict[str, object]] = []
    by_id: dict[str, dict[str, object]] = {}
    for event in events:
        payload = event["payload"]
        assert isinstance(payload, dict)
        if event["type"] == _PREDECESSOR_EVENT:
            if runs or event["sequence"] != 1:
                raise LedgerError("predecessor attestation must be the first release event")
            artifact = _validate_predecessor_attestation(root, event)
            runs.append(
                {
                    "kind": "predecessor_attestation",
                    "attestation_sha256": artifact["attestation_sha256"],
                    "manifest_sha256": artifact["predecessor_manifest_sha256"],
                    "checkpoint": artifact["prior_checkpoint"],
                    "terminal": True,
                    "passed": False,
                    "aggregate_sha256": artifact["predecessor_aggregate_sha256"],
                    "privacy_sha256": artifact["predecessor_privacy_sha256"],
                    "terminal_manifest_sha256": artifact["predecessor_manifest_sha256"],
                }
            )
        elif event["type"] == "release_run_registered":
            if str(payload.get("run_id")) in by_id:
                raise LedgerError("release run ID is registered more than once")
            record = {
                "run_id": payload["run_id"],
                "manifest_sha256": payload["manifest_sha256"],
                "checkpoint": payload["checkpoint"],
                "terminal": False,
                "passed": None,
                "aggregate_sha256": None,
                    "privacy_sha256": None,
                    "terminal_manifest_sha256": None,
            }
            runs.append(record)
            by_id[str(payload["run_id"])] = record
        elif event["type"] == "release_run_terminal":
            record = by_id.get(str(payload.get("run_id")))
            if record is None or record["terminal"] is True:
                raise LedgerError("release terminal event has no pending registered run")
            record.update(
                {
                    "terminal": True,
                    "passed": payload["passed"],
                    "aggregate_sha256": payload["aggregate_sha256"],
                    "privacy_sha256": payload["privacy_sha256"],
                    "terminal_manifest_sha256": payload["manifest_sha256"],
                }
            )
        elif event["type"] == _FINALIZED_EVENT:
            record = by_id.get(str(payload.get("run_id")))
            if record is None or record["terminal"] is True:
                raise LedgerError("release finalization has no pending registered run")
            _validate_release_generation(root, payload)
            record.update(
                {
                    "terminal": True,
                    "passed": True,
                    "aggregate_sha256": payload["aggregate_sha256"],
                    "privacy_sha256": payload["privacy_sha256"],
                    "terminal_manifest_sha256": payload["child_manifest_sha256"],
                    "generation_sha256": payload["generation_sha256"],
                    "proof_profile": payload["proof_profile"],
                    "dogfood_sha256": payload["dogfood_sha256"],
                    "checkpoint_sha256": payload["checkpoint_sha256"],
                }
            )
        else:
            raise LedgerError("release lineage event type is invalid")
    failures = sum(record["terminal"] and record["passed"] is False for record in runs)
    return {
        "schema_version": "cpe-quality-release-lineage.v4",
        "event_count": len(events),
        "last_event_sha256": events[-1]["event_sha256"] if events else None,
        "runs": runs,
        "terminal_full_runs": sum(bool(record["terminal"]) for record in runs),
        "terminal_full_failures": failures,
        "release_passed": any(record["terminal"] and record["passed"] is True for record in runs),
        "release_blocked": failures >= _MAX_TERMINAL_FULL_RUNS,
    }


def _validate_release_generation(root: Path, payload: dict[str, object]) -> Path:
    required = {
        "run_id",
        "generation_sha256",
        "child_manifest_sha256",
        "aggregate_sha256",
        "dogfood_sha256",
        "checkpoint_sha256",
        "privacy_sha256",
        "proof_profile",
        "file_sha256",
    }
    file_sha256 = payload.get("file_sha256")
    if (
        set(payload) != required
        or payload.get("proof_profile") not in {"critical_path_live", "full_paid_matrix"}
        or not isinstance(file_sha256, dict)
        or set(file_sha256) != set(_GENERATION_FILES)
        or any(not isinstance(value, str) or _SHA256.fullmatch(value) is None for value in file_sha256.values())
        or any(not isinstance(payload.get(field), str) or _SHA256.fullmatch(str(payload[field])) is None for field in (
            "generation_sha256", "child_manifest_sha256", "aggregate_sha256", "dogfood_sha256", "checkpoint_sha256", "privacy_sha256"
        ))
    ):
        raise LedgerError("release finalization payload is invalid")
    expected_generation = sha256_bytes(
        canonical_json(
            {
                "schema_version": "cpe.release-generation.v4",
                "file_sha256": {name: file_sha256[name] for name in _GENERATION_FILES},
            }
        )
    )
    if payload["generation_sha256"] != expected_generation:
        raise LedgerError("release generation digest is invalid")
    generation = root / _GENERATION_DIR / expected_generation
    if not generation.is_dir() or generation.is_symlink():
        raise LedgerError("release generation is missing")
    actual_names = {path.name for path in generation.iterdir()}
    if actual_names != set(_GENERATION_FILES):
        raise LedgerError("release generation file set is invalid")
    for name in _GENERATION_FILES:
        path = generation / name
        if not path.is_file() or path.is_symlink() or sha256_bytes(path.read_bytes()) != file_sha256[name]:
            raise LedgerError("release generation file digest is invalid")
    return generation


def _append_release_event_locked(
    root: Path, event_type: str, payload: dict[str, object]
) -> dict[str, object]:
    events = _read_release_events(root)
    body: dict[str, object] = {
        "schema_version": _RELEASE_EVENT_SCHEMA,
        "sequence": len(events) + 1,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "type": event_type,
        "payload": payload,
        "previous_sha256": events[-1]["event_sha256"] if events else None,
    }
    event = {**body, "event_sha256": sha256_bytes(canonical_json(body))}
    try:
        with (root / _RELEASE_EVENTS_FILE).open("ab") as stream:
            stream.write(canonical_json(event))
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        raise LedgerError(f"cannot append release lineage: {exc}") from exc
    return event


def replay_release_lineage(root: Path) -> dict[str, object]:
    release_root = Path(root)
    release_root.mkdir(parents=True, exist_ok=True)
    with _locked_run(release_root):
        projection = _release_projection(_read_release_events(release_root), release_root)
        _atomic_json(release_root / _RELEASE_STATE_FILE, projection)
        return projection


def validate_release_lineage(root: Path) -> dict[str, object]:
    """Validate a release chain and require byte-identical stored projection parity."""

    release_root = Path(root)
    if not release_root.is_dir() or release_root.is_symlink():
        raise LedgerError("release lineage root is invalid")
    with _locked_run(release_root):
        projection = _release_projection(_read_release_events(release_root), release_root)
        state_path = release_root / _RELEASE_STATE_FILE
        if (
            not state_path.is_file()
            or state_path.is_symlink()
            or state_path.read_bytes() != canonical_json(projection)
        ):
            raise LedgerError("release lineage projection differs from authoritative events")
        return projection


def finalize_release_generation(
    root: Path,
    *,
    run_id: str,
    payload_bytes: dict[str, bytes],
    child_manifest_sha256: str,
    aggregate_sha256: str,
    dogfood_sha256: str,
    checkpoint_sha256: str,
    privacy_sha256: str,
    proof_profile: str,
    crash_at: str | None = None,
) -> dict[str, object]:
    """Publish one fsynced generation, then one terminal lineage event and state."""

    if set(payload_bytes) != set(_GENERATION_FILES):
        raise LedgerError("release generation file set is invalid")
    release_root = Path(root)
    release_root.mkdir(parents=True, exist_ok=True)
    file_sha256 = {name: sha256_bytes(payload_bytes[name]) for name in _GENERATION_FILES}
    generation_sha256 = sha256_bytes(
        canonical_json(
            {
                "schema_version": "cpe.release-generation.v4",
                "file_sha256": {name: file_sha256[name] for name in _GENERATION_FILES},
            }
        )
    )
    payload: dict[str, object] = {
        "run_id": run_id,
        "generation_sha256": generation_sha256,
        "child_manifest_sha256": child_manifest_sha256,
        "aggregate_sha256": aggregate_sha256,
        "dogfood_sha256": dogfood_sha256,
        "checkpoint_sha256": checkpoint_sha256,
        "privacy_sha256": privacy_sha256,
        "proof_profile": proof_profile,
        "file_sha256": file_sha256,
    }
    with _locked_run(release_root):
        generation_root = release_root / _GENERATION_DIR
        generation_root.mkdir(mode=0o700, exist_ok=True)
        final = generation_root / generation_sha256
        temporary = generation_root / f"{generation_sha256}.tmp"
        if final.exists():
            _validate_release_generation(release_root, payload)
        else:
            if temporary.exists():
                if not temporary.is_dir() or temporary.is_symlink():
                    raise LedgerError("release generation temporary is invalid")
                shutil.rmtree(temporary)
            temporary.mkdir(mode=0o700)
            try:
                for name in _GENERATION_FILES:
                    _write_exclusive(temporary / name, payload_bytes[name])
                _fsync_directory(temporary)
                os.replace(temporary, final)
                _fsync_directory(generation_root)
            except BaseException:
                shutil.rmtree(temporary, ignore_errors=True)
                raise
        if crash_at == "generation_before_event":
            raise LedgerError("injected_generation_before_event")
        events = _read_release_events(release_root)
        finalized = [event for event in events if event["type"] == _FINALIZED_EVENT]
        if finalized:
            if len(finalized) != 1 or finalized[0]["payload"] != payload:
                raise LedgerError("a different release generation is already terminal")
            event = finalized[0]
        else:
            projection = _release_projection(events, release_root)
            runs = projection["runs"]
            target = next(
                (record for record in runs if record.get("run_id") == run_id), None
            )
            if target is None or target.get("terminal") is True:
                raise LedgerError("release finalization requires one pending registered run")
            event = _append_release_event_locked(release_root, _FINALIZED_EVENT, payload)
        if crash_at == "event_before_state":
            raise LedgerError("injected_event_before_state")
        _atomic_json(
            release_root / _RELEASE_STATE_FILE,
            _release_projection(_read_release_events(release_root), release_root),
        )
        return event


def terminal_release_generation(root: Path) -> tuple[dict[str, object], Path]:
    """Return the sole valid terminal generation referenced by stored lineage."""

    release_root = Path(root)
    projection = validate_release_lineage(release_root)
    events = _read_release_events(release_root)
    finalized = [event for event in events if event["type"] == _FINALIZED_EVENT]
    if len(finalized) != 1 or projection.get("release_passed") is not True:
        raise LedgerError("terminal release generation is missing")
    payload = finalized[0]["payload"]
    assert isinstance(payload, dict)
    return payload, _validate_release_generation(release_root, payload)


def _commit_predecessor_attestation(
    root: Path,
    artifact: dict[str, object],
    *,
    append_event_fn=None,
    write_state_fn=None,
) -> dict[str, object]:
    """Publish one validated digest-only predecessor artifact before its event."""

    if not isinstance(artifact, dict):
        raise LedgerError("predecessor attestation must be an object")
    _validate_predecessor_artifact(artifact)
    release_root = Path(root)
    release_root.mkdir(parents=True, exist_ok=True)
    artifact_bytes = canonical_json(artifact)
    with _locked_run(release_root):
        events = _read_release_events(release_root)
        predecessor_events = [event for event in events if event["type"] == _PREDECESSOR_EVENT]
        artifact_path = release_root / _PREDECESSOR_ATTESTATION_FILE
        if not events and not artifact_path.exists() and any(release_root.iterdir()):
            raise LedgerError("predecessor attestation requires a fresh evidence root")
        if artifact_path.exists():
            if (
                not artifact_path.is_file()
                or artifact_path.is_symlink()
                or artifact_path.read_bytes() != artifact_bytes
            ):
                raise LedgerError("different predecessor attestation is already stored")
        else:
            if events:
                raise LedgerError("predecessor attestation must precede release registration")
            _write_exclusive(artifact_path, artifact_bytes)
            _fsync_directory(release_root)
        if predecessor_events:
            if len(predecessor_events) != 1:
                raise LedgerError("multiple predecessor attestations are forbidden")
            _validate_predecessor_attestation(release_root, predecessor_events[0])
            (write_state_fn or _atomic_json)(
                release_root / _RELEASE_STATE_FILE,
                _release_projection(_read_release_events(release_root), release_root),
            )
            return predecessor_events[0]
        if events:
            raise LedgerError("predecessor attestation must be the first release event")
        event = (append_event_fn or _append_release_event_locked)(
            release_root,
            _PREDECESSOR_EVENT,
            {
                "attestation_sha256": artifact.get("attestation_sha256"),
                "artifact_sha256": sha256_bytes(artifact_bytes),
                "predecessor_event_sha256": artifact.get("predecessor_event_sha256"),
            },
        )
        (write_state_fn or _atomic_json)(
            release_root / _RELEASE_STATE_FILE,
            _release_projection(_read_release_events(release_root), release_root),
        )
        return event


def _release_manifest_path(root: Path, run_id: str) -> Path:
    return root / _RELEASE_MANIFEST_DIR / f"{quote(run_id, safe='-._~')}.json"


def load_registered_release_manifest(
    root: Path, run_id: str
) -> dict[str, object] | None:
    """Load the immutable parent copy needed after a pre-child-create crash."""

    release_root = Path(root)
    if not release_root.is_dir():
        return None
    with _locked_run(release_root):
        events = _read_release_events(release_root)
        projection = _release_projection(events, release_root)
        record = next(
            (
                item
                for item in projection["runs"]
                if item.get("run_id") == run_id
            ),
            None,
        )
        if record is None:
            return None
        manifest = _load_object(
            _release_manifest_path(release_root, run_id),
            f"registered release manifest {run_id}",
        )
        digest = _manifest_digest(manifest)
        if digest != record.get("manifest_sha256"):
            raise LedgerError("registered release manifest differs from its lineage event")
        return manifest


def register_release_run(
    root: Path,
    manifest: dict[str, object],
    *,
    append_event_fn=None,
) -> dict[str, object]:
    """Reserve one immutable release attempt before any provider execution."""

    if not isinstance(manifest, dict) or manifest.get("schema_version") != "cpe-quality-manifest.v4":
        raise LedgerError("release lineage requires a v4 manifest")
    run_id = manifest.get("run_id")
    manifest_sha256 = manifest.get("manifest_sha256")
    checkpoint = manifest.get("implementation_patch_sha256") or manifest.get(
        "implementation_commit"
    )
    if (
        not isinstance(run_id, str)
        or not run_id
        or not isinstance(manifest_sha256, str)
        or _SHA256.fullmatch(manifest_sha256) is None
        or not isinstance(checkpoint, str)
        or re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", checkpoint) is None
    ):
        raise LedgerError("release manifest binding is invalid")
    release_root = Path(root)
    release_root.mkdir(parents=True, exist_ok=True)
    with _locked_run(release_root):
        events = _read_release_events(release_root)
        projection = _release_projection(events, release_root)
        runs = projection["runs"]
        assert isinstance(runs, list)
        existing = next(
            (record for record in runs if record.get("run_id") == run_id), None
        )
        if existing is not None:
            if (
                existing.get("manifest_sha256") == manifest_sha256
                and existing.get("checkpoint") == checkpoint
                and existing.get("terminal") is False
            ):
                stored = _load_object(
                    _release_manifest_path(release_root, run_id),
                    f"registered release manifest {run_id}",
                )
                if canonical_json(stored) != canonical_json(manifest):
                    raise LedgerError("idempotent release manifest artifact differs")
                return next(
                    event
                    for event in events
                    if event["type"] == "release_run_registered"
                    and isinstance(event["payload"], dict)
                    and event["payload"].get("run_id") == run_id
                )
            raise LedgerError("release run ID is bound to a different or terminal manifest")
        if len(runs) >= _MAX_TERMINAL_FULL_RUNS or projection["release_passed"] is True:
            raise LedgerError("release terminal full run limit reached")
        if runs:
            previous = runs[-1]
            if previous.get("terminal") is not True or previous.get("passed") is not False:
                raise LedgerError("corrected release run requires one terminal failure")
            if previous.get("checkpoint") == checkpoint:
                raise LedgerError("corrected release run requires a changed checkpoint")
        manifest_path = _release_manifest_path(release_root, run_id)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_bytes = canonical_json(manifest)
        if manifest_path.exists():
            try:
                if manifest_path.read_bytes() != manifest_bytes:
                    raise LedgerError("release run manifest artifact differs")
            except OSError as exc:
                raise LedgerError(f"release manifest artifact is unreadable: {exc}") from exc
        else:
            _write_exclusive(manifest_path, manifest_bytes)
            _fsync_directory(manifest_path.parent)
        event = (append_event_fn or _append_release_event_locked)(
            release_root,
            "release_run_registered",
            {
                "run_id": run_id,
                "manifest_sha256": manifest_sha256,
                "checkpoint": checkpoint,
            },
        )
        _atomic_json(
            release_root / _RELEASE_STATE_FILE,
            _release_projection(_read_release_events(release_root), release_root),
        )
        return event


def recover_orphan_release_registration(
    root: Path, run_id: str
) -> dict[str, object] | None:
    """Recover a fsynced exact manifest whose registration event was not appended."""

    release_root = Path(root)
    if not release_root.is_dir():
        return None
    manifest_path = _release_manifest_path(release_root, run_id)
    if not manifest_path.is_file() or manifest_path.is_symlink():
        return None
    with _locked_run(release_root):
        manifest = _load_object(manifest_path, f"orphan release manifest {run_id}")
        digest = _manifest_digest(manifest)
        checkpoint = manifest.get("implementation_patch_sha256") or manifest.get(
            "implementation_commit"
        )
        catalog = manifest.get("model_catalog_sha256")
        if (
            manifest.get("schema_version") != "cpe-quality-manifest.v4"
            or manifest.get("run_id") != run_id
            or not isinstance(checkpoint, str)
            or re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", checkpoint) is None
            or not isinstance(catalog, str)
            or _SHA256.fullmatch(catalog) is None
        ):
            raise LedgerError("orphan release manifest contract is invalid")
        events = _read_release_events(release_root)
        projection = _release_projection(events, release_root)
        runs = projection["runs"]
        assert isinstance(runs, list)
        existing = next(
            (record for record in runs if record.get("run_id") == run_id), None
        )
        if existing is not None:
            if (
                existing.get("manifest_sha256") == digest
                and existing.get("checkpoint") == checkpoint
            ):
                return next(
                    event
                    for event in events
                    if event["type"] == "release_run_registered"
                    and isinstance(event["payload"], dict)
                    and event["payload"].get("run_id") == run_id
                )
            raise LedgerError("orphan manifest conflicts with registered release run")
        if len(runs) >= _MAX_TERMINAL_FULL_RUNS or projection["release_passed"] is True:
            raise LedgerError("orphan recovery exceeds release run limit")
        if runs:
            previous = runs[-1]
            if previous.get("terminal") is not True or previous.get("passed") is not False:
                raise LedgerError("orphan corrected run lacks a terminal predecessor failure")
            if previous.get("checkpoint") == checkpoint:
                raise LedgerError("orphan corrected run did not change checkpoint")
        event = _append_release_event_locked(
            release_root,
            "release_run_registered",
            {
                "run_id": run_id,
                "manifest_sha256": digest,
                "checkpoint": checkpoint,
            },
        )
        _atomic_json(
            release_root / _RELEASE_STATE_FILE,
            _release_projection(_read_release_events(release_root), release_root),
        )
        return event


def record_release_terminal(
    root: Path,
    *,
    run_id: str,
    manifest_sha256: str,
    passed: bool,
    aggregate_sha256: str,
    privacy_sha256: str,
) -> dict[str, object]:
    """Commit the post-aggregate and post-privacy terminal release verdict."""

    if (
        not isinstance(run_id, str)
        or not run_id
        or type(passed) is not bool
        or _SHA256.fullmatch(manifest_sha256 or "") is None
        or _SHA256.fullmatch(aggregate_sha256 or "") is None
        or _SHA256.fullmatch(privacy_sha256 or "") is None
    ):
        raise LedgerError("release terminal binding is invalid")
    release_root = Path(root)
    with _locked_run(release_root):
        projection = _release_projection(_read_release_events(release_root), release_root)
        runs = projection["runs"]
        assert isinstance(runs, list)
        target = next((record for record in runs if record.get("run_id") == run_id), None)
        if target is None or target.get("terminal") is True:
            raise LedgerError("release run is missing or already terminal")
        if target.get("manifest_sha256") != manifest_sha256:
            raise LedgerError("terminal aggregate manifest differs from registration")
        registered_manifest = _load_object(
            _release_manifest_path(release_root, run_id),
            f"registered release manifest {run_id}",
        )
        if _manifest_digest(registered_manifest) != target.get("manifest_sha256"):
            raise LedgerError("terminal release manifest differs from its registration")
        event = _append_release_event_locked(
            release_root,
            "release_run_terminal",
            {
                "run_id": run_id,
                "manifest_sha256": manifest_sha256,
                "passed": passed,
                "aggregate_sha256": aggregate_sha256,
                "privacy_sha256": privacy_sha256,
            },
        )
        _atomic_json(
            release_root / _RELEASE_STATE_FILE,
            _release_projection(_read_release_events(release_root), release_root),
        )
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
        envelope_sha256 = result.get("envelope_sha256")
        if envelope_sha256 is not None:
            if not isinstance(envelope_sha256, str) or _SHA256.fullmatch(envelope_sha256) is None:
                raise LedgerError("slot result envelope binding is invalid")
            index_body["envelope_sha256"] = envelope_sha256
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
            **(
                {"envelope_sha256": index["envelope_sha256"]}
                if "envelope_sha256" in index
                else {}
            ),
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
    if "envelope_sha256" in index:
        required_index.add("envelope_sha256")
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
    indexed_envelope = index.get("envelope_sha256")
    if indexed_envelope is not None and (
        _SHA256.fullmatch(str(indexed_envelope)) is None
        or payload.get("envelope_sha256") != indexed_envelope
        or _load_object(slot_path / "result.json", f"slot result for {key}").get("envelope_sha256")
        != indexed_envelope
    ):
        raise LedgerError(f"slot completion envelope digest mismatch: {key}")


def _key_object(key: SlotKey) -> dict[str, str]:
    return {"treatment_id": key.treatment_id, "case_id": key.case_id}


def replay_run(run_dir: Path, *, repair_state: bool = True) -> dict[str, object]:
    """Validate authoritative evidence, derive state, and atomically repair drift."""

    root = Path(run_dir)
    with _locked_run(root):
        return _replay_run_locked(root, repair_state=repair_state)


def _replay_run_locked(
    root: Path, *, repair_state: bool = True
) -> dict[str, object]:
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
    if current_state != expected_state and not repair_state:
        raise LedgerError("state.json differs from authoritative run events")
    if current_state != expected_state:
        _atomic_json(state_path, projection)
    return projection
