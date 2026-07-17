"""Strict execution-ledger validation and bounded evidence sealing."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
from pathlib import Path, PurePosixPath

from .progress import ProgressSnapshot
from .state import StateStore

MAX_EVIDENCE_FILES = 128
MAX_EVIDENCE_FILE_BYTES = 1024 * 1024
MAX_EVIDENCE_TOTAL_BYTES = 8 * 1024 * 1024
MAX_EXECUTION_EVENT_BYTES = 16_384
TRUST_LEVELS = {"parent_observed", "child_attested", "derived", "hypothesis"}

_CATEGORIES = {
    "task", "review", "finding_fix", "verification", "capability",
    "checkpoint", "blocker", "obligation", "coordination",
}
_ACTIONS = {
    "recorded", "started", "completed", "failed", "blocked", "resolved",
    "approved", "rejected", "verified", "observed", "created", "updated",
    "checked", "satisfied", "waived", "requested", "responded",
}
_RESULTS = {
    "pass", "fail", "blocked", "skipped", "unavailable", "accepted", "closed",
}
_BASE_FIELDS = {
    "schema_version", "event_id", "source", "plan_id", "category", "action",
    "result", "evidence_refs",
}
_VARIANT_FIELDS = {
    "task": {"task_id", "duration_ms"},
    "review": {"review_id", "artifact_digest", "duration_ms"},
    "finding_fix": {"finding_ids", "fix_digest", "duration_ms"},
    "verification": {"command_id", "argv_digest", "evidence_key", "duration_ms"},
    "capability": {"capability_id", "capability_digest"},
    "checkpoint": {"checkpoint_id", "checkpoint_digest"},
    "blocker": {"blocker_id", "blocker_digest"},
    "obligation": {"obligation_id", "obligation_digest"},
    "coordination": {"coordination_id", "coordination_digest", "duration_ms"},
}
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


def _safe_reference(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("execution evidence reference is invalid")
    reference = PurePosixPath(value)
    if reference.is_absolute() or any(part in {"", ".", ".."} for part in reference.parts):
        raise ValueError("execution evidence reference escapes its root")
    return value


def validate_execution_event_schema(event: object, *, allow_private_sources: bool = False) -> None:
    if not isinstance(event, dict):
        raise ValueError("execution event must be an object")
    category = event.get("category")
    if category not in _CATEGORIES:
        raise ValueError("execution event category is invalid")
    allowed = _BASE_FIELDS | _VARIANT_FIELDS[str(category)]
    if set(event) != allowed:
        raise ValueError("execution event properties are invalid")
    if event["schema_version"] != 1 or isinstance(event["schema_version"], bool):
        raise ValueError("execution event schema version is invalid")
    for field in ("event_id", "plan_id"):
        if not isinstance(event[field], str) or not _IDENTIFIER.fullmatch(event[field]):
            raise ValueError(f"execution event {field} is invalid")
    source = event["source"]
    if source not in TRUST_LEVELS:
        raise ValueError("execution event trust level is invalid")
    if not allow_private_sources and source not in {"child_attested", "hypothesis"}:
        raise ValueError("worktree execution event trust level is invalid")
    if event["action"] not in _ACTIONS:
        raise ValueError("execution event action is invalid")
    if event["result"] not in _RESULTS:
        raise ValueError("execution event result is invalid")
    refs = event["evidence_refs"]
    if not isinstance(refs, list) or len(refs) > MAX_EVIDENCE_FILES:
        raise ValueError("execution evidence references are invalid")
    for reference in refs:
        _safe_reference(reference)
    for field in set(event) - _BASE_FIELDS:
        value = event[field]
        if field == "duration_ms":
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError("execution event duration is invalid")
        elif field == "finding_ids":
            if (
                not isinstance(value, list)
                or not value
                or not all(
                    isinstance(finding_id, str)
                    and _IDENTIFIER.fullmatch(finding_id)
                    for finding_id in value
                )
                or len(value) != len(set(value))
            ):
                raise ValueError("execution event finding IDs are invalid")
        elif field.endswith("digest") or field in {"argv_digest", "evidence_key"}:
            if not isinstance(value, str) or not _DIGEST.fullmatch(value):
                raise ValueError("execution event digest is invalid")
        elif not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
            raise ValueError("execution event identifier is invalid")


def append_execution_event(path: Path, event: dict[str, object]) -> None:
    normalized = dict(event)
    normalized.setdefault("schema_version", 1)
    validate_execution_event_schema(normalized, allow_private_sources=True)
    payload = (json.dumps(normalized, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    if len(payload) > MAX_EXECUTION_EVENT_BYTES:
        raise ValueError("execution event is too large")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("execution ledger must be a regular file")
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("execution ledger append made no progress")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _read_regular(path: Path, *, missing_message: str) -> bytes:
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as error:
        raise ValueError(missing_message) from error
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError(missing_message)
        if metadata.st_size > MAX_EVIDENCE_FILE_BYTES:
            raise ValueError("evidence file exceeds size limit")
        chunks: list[bytes] = []
        remaining = MAX_EVIDENCE_FILE_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(65_536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        if len(payload) > MAX_EVIDENCE_FILE_BYTES:
            raise ValueError("evidence file exceeds size limit")
        return payload
    finally:
        os.close(descriptor)


def validate_execution_ledger(path: Path, *, expected_plan_id: str) -> list[dict[str, object]]:
    payload = _read_regular(path, missing_message="required evidence is missing or redirected")
    return _validate_execution_ledger_payload(payload, expected_plan_id=expected_plan_id)


def execution_event_digest(event: dict[str, object]) -> str:
    """Digest canonical event content, not only its caller-selected identity."""
    validate_execution_event_schema(event)
    payload = json.dumps(
        event, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def read_progress_snapshot(run_root: Path, *, plan_index: int, head: str) -> ProgressSnapshot:
    """Project the current strict JSONL ledger into durable progress state."""
    if not isinstance(plan_index, int) or isinstance(plan_index, bool):
        raise ValueError("plan index is invalid")
    state = StateStore.open(run_root).state
    plans = state["plans"]
    if not 0 <= plan_index < len(plans):
        raise ValueError("plan index is invalid")
    plan_id = plans[plan_index]["plan_id"]
    ledger = Path(state["worktree"]) / ".superpowers" / "sdd" / "execution-ledger.jsonl"
    events = validate_execution_ledger(ledger, expected_plan_id=plan_id)
    completed = {
        event["task_id"] for event in events
        if event["category"] == "task"
        and event["action"] == "completed"
        and event["result"] == "pass"
    }
    started = [
        event["task_id"] for event in events
        if event["category"] == "task" and event["action"] == "started"
    ]
    current = next(
        (task_id for task_id in reversed(started) if task_id not in completed), None
    )
    return ProgressSnapshot(
        head=head,
        completed_task_ids=tuple(sorted(completed)),
        current_task_id=current,
        accepted_review_ids=tuple(sorted({
            event["review_id"] for event in events
            if event["category"] == "review" and event["result"] == "accepted"
        })),
        closed_finding_ids=tuple(sorted({
            finding_id for event in events
            if event["category"] == "finding_fix" and event["result"] == "closed"
            for finding_id in event["finding_ids"]
        })),
    )


def _validate_execution_ledger_payload(
    payload: bytes, *, expected_plan_id: str
) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    for line_number, line in enumerate(payload.splitlines(), start=1):
        if not line or len(line) > MAX_EXECUTION_EVENT_BYTES:
            raise ValueError(f"execution event {line_number} is too large or empty")
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ValueError(f"execution event {line_number} is invalid JSON") from error
        validate_execution_event_schema(event)
        if event["plan_id"] != expected_plan_id:
            raise ValueError("execution event plan identity is invalid")
        if event["event_id"] in seen_ids:
            raise ValueError("execution event id is duplicated")
        seen_ids.add(event["event_id"])
        events.append(event)
    if not events:
        raise ValueError("execution ledger is empty")
    return events


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_all(descriptor: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise OSError("evidence write made no progress")
        view = view[written:]


def _reject_symlink_components(root: Path, relative: PurePosixPath) -> None:
    current = root
    if current.is_symlink():
        raise ValueError("required evidence is missing or redirected")
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("required evidence is missing or redirected")


def _manifest_bytes(manifest: dict[str, object]) -> bytes:
    return json.dumps(
        manifest, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def _collect_plan_evidence(
    *, worktree: Path, plan_id: str, accepted_head: str,
) -> tuple[dict[str, object], list[tuple[str, bytes]]]:
    if not _IDENTIFIER.fullmatch(plan_id) or not re.fullmatch(r"[0-9a-f]{40,64}", accepted_head):
        raise ValueError("evidence identity is invalid")
    source_root = worktree / ".superpowers" / "sdd"
    _reject_symlink_components(worktree, PurePosixPath(".superpowers/sdd"))
    ledger = source_root / "execution-ledger.jsonl"
    ledger_payload = _read_regular(
        ledger, missing_message="required evidence is missing or redirected"
    )
    events = _validate_execution_ledger_payload(
        ledger_payload, expected_plan_id=plan_id
    )
    references: list[str] = []
    seen = {"execution-ledger.jsonl"}
    for event in events:
        for raw_reference in event["evidence_refs"]:
            reference = _safe_reference(raw_reference)
            if reference not in seen:
                seen.add(reference)
                references.append(reference)
    if len(seen) > MAX_EVIDENCE_FILES:
        raise ValueError("evidence file count exceeds limit")

    files: list[dict[str, object]] = []
    payloads: list[tuple[str, bytes]] = []
    total = 0
    for reference in ["execution-ledger.jsonl", *references]:
        _reject_symlink_components(source_root, PurePosixPath(reference))
        source = source_root.joinpath(*PurePosixPath(reference).parts)
        resolved_parent = source.parent.resolve(strict=True)
        if source_root.resolve(strict=True) not in (resolved_parent, *resolved_parent.parents):
            raise ValueError("evidence reference escapes its root")
        payload = (
            ledger_payload
            if reference == "execution-ledger.jsonl"
            else _read_regular(
                source,
                missing_message="required evidence is missing or redirected",
            )
        )
        total += len(payload)
        if total > MAX_EVIDENCE_TOTAL_BYTES:
            raise ValueError("evidence bundle exceeds size limit")
        payloads.append((reference, payload))
        files.append({
            "path": reference,
            "byte_length": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        })
    manifest: dict[str, object] = {
        "format_version": 2,
        "plan_id": plan_id,
        "accepted_head": accepted_head,
        "files": files,
        "total_byte_length": total,
    }
    return manifest, payloads


def prepare_plan_evidence(
    *, worktree: Path, plan_id: str, accepted_head: str,
) -> tuple[dict[str, object], str]:
    """Validate source evidence and return its immutable publication contract."""
    manifest, _ = _collect_plan_evidence(
        worktree=worktree, plan_id=plan_id, accepted_head=accepted_head,
    )
    return manifest, hashlib.sha256(_manifest_bytes(manifest)).hexdigest()


def _validate_published_evidence(
    target_root: Path,
    *,
    manifest: dict[str, object],
    payloads: list[tuple[str, bytes]],
) -> None:
    if target_root.is_symlink() or not target_root.is_dir():
        raise ValueError("sealed evidence target does not match journal contract")
    expected_files = {reference for reference, _ in payloads}
    expected_files.add("evidence-manifest.json")
    observed_files: set[str] = set()
    for path in target_root.rglob("*"):
        if path.is_symlink():
            raise ValueError("sealed evidence target does not match journal contract")
        if path.is_file():
            observed_files.add(path.relative_to(target_root).as_posix())
            if not stat.S_ISREG(path.stat().st_mode):
                raise ValueError("sealed evidence target does not match journal contract")
    if observed_files != expected_files:
        raise ValueError("sealed evidence target does not match journal contract")
    expected_payloads = dict(payloads)
    expected_payloads["evidence-manifest.json"] = _manifest_bytes(manifest)
    for reference, expected in expected_payloads.items():
        target = target_root.joinpath(*PurePosixPath(reference).parts)
        if stat.S_IMODE(target.stat().st_mode) != 0o400:
            raise ValueError("sealed evidence target does not match journal contract")
        if _read_regular(
            target,
            missing_message="sealed evidence target does not match journal contract",
        ) != expected:
            raise ValueError("sealed evidence target does not match journal contract")


def ingest_plan_evidence(
    *,
    run_root: Path,
    worktree: Path,
    plan_id: str,
    accepted_head: str,
    expected_manifest_sha256: str | None = None,
) -> dict[str, object]:
    manifest, payloads = _collect_plan_evidence(
        worktree=worktree, plan_id=plan_id, accepted_head=accepted_head,
    )
    manifest_payload = _manifest_bytes(manifest)
    manifest_sha256 = hashlib.sha256(manifest_payload).hexdigest()
    if (
        expected_manifest_sha256 is not None
        and (
            not _DIGEST.fullmatch(expected_manifest_sha256)
            or expected_manifest_sha256 != manifest_sha256
        )
    ):
        raise ValueError("evidence source changed after decision journal")

    evidence_root = run_root / "evidence"
    evidence_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    target_root = evidence_root / plan_id
    if target_root.exists() or target_root.is_symlink():
        _validate_published_evidence(
            target_root, manifest=manifest, payloads=payloads,
        )
        return manifest

    staging = Path(tempfile.mkdtemp(prefix=f".{plan_id}.", dir=evidence_root))
    published = False
    try:
        for reference, payload in payloads:
            target = staging.joinpath(*PurePosixPath(reference).parts)
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
            try:
                _write_all(descriptor, payload)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            target.chmod(0o400)
        manifest_path = staging / "evidence-manifest.json"
        manifest_path.write_bytes(manifest_payload)
        with manifest_path.open("rb") as stream:
            os.fsync(stream.fileno())
        manifest_path.chmod(0o400)
        for directory in sorted((path for path in staging.rglob("*") if path.is_dir()), reverse=True):
            _fsync_directory(directory)
        _fsync_directory(staging)
        staging.rename(target_root)
        published = True
        _fsync_directory(evidence_root)
        return manifest
    except BaseException:
        shutil.rmtree(target_root if published else staging, ignore_errors=True)
        if published:
            try:
                _fsync_directory(evidence_root)
            except OSError:
                pass
        raise
