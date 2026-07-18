"""Strict execution-ledger validation and bounded evidence sealing."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from collections.abc import Collection
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .progress import ProgressSnapshot
from .result_validation import (
    RESULT_WIRE_FIELDS,
    normalize_result_v2,
    strict_json_object,
)
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
    "executed_uncached",
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
    "verification": {
        "command_id", "argv_digest", "evidence_key", "duration_ms",
        "requested_phase", "executed_phase", "avoided_executions",
    },
    "capability": {"capability_id", "capability_digest"},
    "checkpoint": {"checkpoint_id", "checkpoint_digest"},
    "blocker": {"blocker_id", "blocker_digest"},
    "obligation": {"obligation_id", "obligation_digest"},
    "coordination": {"coordination_id", "coordination_digest", "duration_ms"},
}
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_UNCACHED_REASONS = {"uncached_command_required", "verification_helper_fallback"}
_UNCACHED_PHASES = {"task", "affected", "branch_final"}
_UNCACHED_FIELDS = {"exit_code", "receipt_path", "reason_code"}


@dataclass(frozen=True)
class EnvelopeRepair:
    original_path: Path
    repaired_path: Path
    original_digest: str
    repaired_digest: str
    changed_fields: tuple[str, ...]


@dataclass
class _VerifiedArtifact:
    canonical_path: Path
    relative_path: PurePosixPath
    device: int
    inode: int
    size: int
    digest: str
    payload: bytes
    descriptor: int

    def __enter__(self) -> "_VerifiedArtifact":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        if self.descriptor >= 0:
            os.close(self.descriptor)
            self.descriptor = -1

    def same_identity(self, other: "_VerifiedArtifact") -> bool:
        return (
            self.relative_path == other.relative_path
            and self.device == other.device
            and self.inode == other.inode
            and self.size == other.size
            and self.digest == other.digest
        )


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
    is_uncached = category == "verification" and event.get("action") == "executed_uncached"
    allowed = _BASE_FIELDS | _VARIANT_FIELDS[str(category)]
    if is_uncached:
        allowed |= _UNCACHED_FIELDS
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
    if event["action"] == "executed_uncached" and category != "verification":
        raise ValueError("uncached execution category is invalid")
    if event["result"] not in _RESULTS:
        raise ValueError("execution event result is invalid")
    refs = event["evidence_refs"]
    if not isinstance(refs, list) or len(refs) > MAX_EVIDENCE_FILES:
        raise ValueError("execution evidence references are invalid")
    for reference in refs:
        _safe_reference(reference)
    if is_uncached and (
        refs != []
        or event.get("receipt_path") is not None
        or event.get("reason_code") not in _UNCACHED_REASONS
        or event.get("requested_phase") not in _UNCACHED_PHASES
        or event.get("executed_phase") != event.get("requested_phase")
        or event.get("avoided_executions") != 0
        or not isinstance(event.get("exit_code"), int)
        or isinstance(event.get("exit_code"), bool)
        or ((event["exit_code"] == 0) != (event["result"] == "pass"))
    ):
        raise ValueError("uncached verification evidence is invalid")
    if category == "verification" and (
        event.get("requested_phase") not in _UNCACHED_PHASES
        or event.get("executed_phase") not in _UNCACHED_PHASES
        or event.get("avoided_executions") not in {0, 1}
    ):
        raise ValueError("verification phase observations are invalid")
    if category == "verification" and event.get("action") == "verified":
        reused_event = str(event.get("event_id", "")).startswith("verification.reused:")
        if event.get("avoided_executions") != (1 if reused_event else 0):
            raise ValueError("verification avoided execution observation is invalid")
    for field in set(event) - _BASE_FIELDS:
        value = event[field]
        if field == "receipt_path":
            if value is not None:
                raise ValueError("uncached verification receipt must be null")
        elif field == "exit_code":
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError("verification exit code is invalid")
        elif field in {"duration_ms", "avoided_executions"}:
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError("execution event duration is invalid")
            if field == "avoided_executions" and value > 1:
                raise ValueError("verification avoided execution count is invalid")
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


def validate_execution_ledger(
    path: Path,
    *,
    expected_plan_id: str,
    allowed_prior_plan_ids: Collection[str] = (),
) -> list[dict[str, object]]:
    """Validate the whole ledger and project events for one active plan.

    A shared worktree may retain the last completed plan's ledger until the
    next controller slice replaces it. Callers must explicitly authorize only
    those completed predecessor identities; evidence sealing stays single-plan.
    """
    payload = _read_regular(path, missing_message="required evidence is missing or redirected")
    return _validate_execution_ledger_payload(
        payload,
        expected_plan_id=expected_plan_id,
        allowed_prior_plan_ids=allowed_prior_plan_ids,
    )


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
    prior_plan_ids = tuple(
        plan["plan_id"]
        for plan in plans[:plan_index]
        if plan["status"] == "completed"
    )
    ledger = Path(state["worktree"]) / ".superpowers" / "sdd" / "execution-ledger.jsonl"
    events = validate_execution_ledger(
        ledger,
        expected_plan_id=plan_id,
        allowed_prior_plan_ids=prior_plan_ids,
    )
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
    )


def _validate_execution_ledger_payload(
    payload: bytes,
    *,
    expected_plan_id: str,
    allowed_prior_plan_ids: Collection[str] = (),
) -> list[dict[str, object]]:
    if not isinstance(expected_plan_id, str) or not _IDENTIFIER.fullmatch(
        expected_plan_id
    ):
        raise ValueError("execution ledger plan identity is invalid")
    allowed_plan_ids = {expected_plan_id}
    for plan_id in allowed_prior_plan_ids:
        if not isinstance(plan_id, str) or not _IDENTIFIER.fullmatch(plan_id):
            raise ValueError("execution ledger plan identity is invalid")
        allowed_plan_ids.add(plan_id)
    events: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    saw_event = False
    for line_number, line in enumerate(payload.splitlines(), start=1):
        if not line or len(line) > MAX_EXECUTION_EVENT_BYTES:
            raise ValueError(f"execution event {line_number} is too large or empty")
        event = strict_json_object(line)
        if event is None:
            raise ValueError(f"execution event {line_number} is invalid JSON")
        validate_execution_event_schema(event)
        saw_event = True
        if event["plan_id"] not in allowed_plan_ids:
            raise ValueError("execution event plan identity is invalid")
        if event["event_id"] in seen_ids:
            raise ValueError("execution event id is duplicated")
        seen_ids.add(event["event_id"])
        if event["plan_id"] == expected_plan_id:
            events.append(event)
    if not saw_event:
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
                os.fchmod(descriptor, 0o400)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        manifest_path = staging / "evidence-manifest.json"
        descriptor = os.open(
            manifest_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            _write_all(descriptor, manifest_payload)
            os.fchmod(descriptor, 0o400)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
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


def _git_output(worktree: Path, *arguments: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "-C", str(worktree), *arguments],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout.strip()


def _open_verified_artifact(
    declared: Path,
    worktree: Path,
    *,
    allow_absolute: bool,
) -> _VerifiedArtifact | None:
    """Open a component-safe artifact and retain the verified descriptor."""
    try:
        root = worktree.resolve(strict=True)
        root_metadata = os.lstat(worktree)
    except OSError:
        return None
    if worktree != root or stat.S_ISLNK(root_metadata.st_mode) or not stat.S_ISDIR(
        root_metadata.st_mode
    ):
        return None

    raw_parts: tuple[str, ...]
    if declared.is_absolute():
        if not allow_absolute:
            return None
        try:
            raw_relative = declared.relative_to(root)
        except ValueError:
            return None
        normalized = Path(os.path.normpath(str(declared)))
        try:
            normalized.relative_to(root)
        except ValueError:
            return None
        raw_parts = raw_relative.parts
    else:
        if (
            not declared.parts
            or "\\" in str(declared)
            or any(part in {"", ".", ".."} for part in declared.parts)
        ):
            return None
        raw_parts = declared.parts

    # Reject paths whose traversal leaves the owned root even temporarily.
    depth = 0
    canonical_parts: list[str] = []
    for part in raw_parts:
        if part == ".":
            continue
        if part == "..":
            if depth == 0:
                return None
            depth -= 1
            canonical_parts.pop()
        else:
            depth += 1
            canonical_parts.append(part)
    if not canonical_parts:
        return None

    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        current = os.open(root, flags)
    except OSError:
        return None
    try:
        for position, part in enumerate(raw_parts):
            if part == ".":
                continue
            final = position == len(raw_parts) - 1
            try:
                visible = os.stat(part, dir_fd=current, follow_symlinks=False)
            except OSError:
                return None
            if stat.S_ISLNK(visible.st_mode):
                return None
            component_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            if not final:
                component_flags |= getattr(os, "O_DIRECTORY", 0)
            try:
                opened = os.open(part, component_flags, dir_fd=current)
            except OSError:
                return None
            metadata = os.fstat(opened)
            if (
                metadata.st_dev != visible.st_dev
                or metadata.st_ino != visible.st_ino
                or (final and not stat.S_ISREG(metadata.st_mode))
                or (not final and not stat.S_ISDIR(metadata.st_mode))
            ):
                os.close(opened)
                return None
            os.close(current)
            current = opened
        metadata = os.fstat(current)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_EVIDENCE_FILE_BYTES:
            return None
        chunks: list[bytes] = []
        remaining = MAX_EVIDENCE_FILE_BYTES + 1
        while remaining:
            chunk = os.read(current, min(65_536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        after = os.fstat(current)
        if (
            len(payload) > MAX_EVIDENCE_FILE_BYTES
            or after.st_dev != metadata.st_dev
            or after.st_ino != metadata.st_ino
            or after.st_size != metadata.st_size
            or len(payload) != metadata.st_size
        ):
            return None
        artifact = _VerifiedArtifact(
            canonical_path=root.joinpath(*canonical_parts),
            relative_path=PurePosixPath(*canonical_parts),
            device=metadata.st_dev,
            inode=metadata.st_ino,
            size=metadata.st_size,
            digest=hashlib.sha256(payload).hexdigest(),
            payload=payload,
            descriptor=current,
        )
        current = -1
        return artifact
    finally:
        if current >= 0:
            os.close(current)


def _valid_result_envelope(payload: dict[str, object]) -> bool:
    if set(payload) != RESULT_WIRE_FIELDS:
        return False
    normalized, error = normalize_result_v2(payload)
    if error is not None or normalized is None:
        return False
    if payload.get("status") != "completed" or payload.get("checkpoint") is not None or payload.get("blocker") is not None:
        return False
    verification = payload.get("verification")
    if not isinstance(verification, list) or not verification:
        return False
    identities: set[tuple[str, str, str]] = set()
    for item in verification:
        assert isinstance(item, dict)
        if item.get("exit_code") != 0:
            return False
        identity = (str(item["command_id"]), str(item["argv_digest"]), str(item["evidence_key"]))
        if identity in identities:
            return False
        identities.add(identity)
    receipt = payload.get("workflow_receipt")
    assert isinstance(receipt, dict)
    return (
        receipt.get("final_review_head") == payload["head_commit"]
        and receipt.get("open_finding_ids") == []
        and receipt.get("open_obligation_ids") == []
    )


def _semantic_projection(payload: dict[str, object]) -> dict[str, object]:
    projection = json.loads(json.dumps(payload))
    receipt = projection["workflow_receipt"]
    assert isinstance(receipt, dict)
    receipt["ledger_path"] = "<workflow-artifact-path>"
    receipt["final_review_path"] = "<workflow-artifact-path>"
    return projection


_PLAN_TERMINALS = {
    "plan.integrity_failed", "plan.evidence_failed", "plan.failed",
    "plan.blocked", "plan.completed",
}


def _bound_unsafe_failure(
    *, run_root: Path, plan_id: str, original_result_path: Path,
    original_digest: str,
) -> dict[str, object] | None:
    try:
        store = StateStore.open(run_root)
        plans = store.state["plans"]
        plan = next(
            record for record in plans
            if isinstance(record, dict) and record.get("plan_id") == plan_id
        )
        attempt = plan.get("attempt_count")
        if not isinstance(attempt, int) or isinstance(attempt, bool):
            return None
        declared_result = Path(str(plan.get("result_path"))).resolve(strict=True)
        failed_unrepaired = (
            store.state["status"] == "failed"
            and plan.get("status") == "failed"
            and plan.get("original_result_path") is None
            and declared_result == original_result_path.resolve(strict=True)
        )
        recorded_repair = False
        recorded_original = plan.get("original_result_path")
        if isinstance(recorded_original, str):
            recorded_repair = (
                store.state["status"] == "running"
                and plan.get("status") == "running"
                and Path(recorded_original).resolve(strict=True)
                == original_result_path.resolve(strict=True)
                and declared_result != original_result_path.resolve(strict=True)
            )
        if not failed_unrepaired and not recorded_repair:
            return None
        events = [strict_json_object(line) for line in store.events_path.read_bytes().splitlines()]
    except (OSError, ValueError, StopIteration):
        return None
    if any(event is None for event in events):
        return None
    terminals = [
        event for event in events
        if isinstance(event, dict)
        and event.get("action") in _PLAN_TERMINALS
        and event.get("plan_id") == plan_id
    ]
    if not terminals:
        return None
    failure = terminals[-1]
    expected_path = str(original_result_path.resolve(strict=True))
    if (
        failure.get("action") != "plan.integrity_failed"
        or failure.get("reason") != "unsafe_workflow_artifact"
        or failure.get("attempt") != attempt
        or failure.get("original_result_path") != expected_path
        or failure.get("original_result_sha256") != original_digest
    ):
        return None
    if failed_unrepaired:
        return failure
    repairs = [
        event for event in events
        if isinstance(event, dict)
        and event.get("action") == "result.envelope_repaired"
        and event.get("plan_id") == plan_id
    ]
    return failure if len(repairs) == 1 else None


def has_current_unsafe_envelope_failure(
    *, run_root: Path, original_result_path: Path,
) -> bool:
    """Return whether the current attempt is bound to this exact unsafe result."""
    with ExitStack() as stack:
        try:
            results_root = (run_root.resolve(strict=True) / "results").resolve(strict=True)
        except OSError:
            return False
        proof = _open_verified_artifact(original_result_path, results_root, allow_absolute=True)
        if proof is None:
            return False
        stack.enter_context(proof)
        payload = strict_json_object(proof.payload)
        return bool(
            payload
            and isinstance(payload.get("plan_id"), str)
            and _bound_unsafe_failure(
                run_root=run_root,
                plan_id=str(payload["plan_id"]),
                original_result_path=proof.canonical_path,
                original_digest=proof.digest,
            )
        )


def result_artifact_digest(run_root: Path, result_path: Path) -> str | None:
    """Digest a component-safe private result artifact."""
    try:
        results_root = (run_root.resolve(strict=True) / "results").resolve(strict=True)
    except OSError:
        return None
    proof = _open_verified_artifact(result_path, results_root, allow_absolute=True)
    if proof is None:
        return None
    with proof:
        return proof.digest


def _open_private_result(
    *, run_root: Path, result_path: Path, expected_digest: str,
) -> _VerifiedArtifact:
    if not _DIGEST.fullmatch(expected_digest):
        raise ValueError("private result digest is invalid")
    try:
        results_root = (run_root.resolve(strict=True) / "results").resolve(strict=True)
        root_metadata = os.lstat(results_root)
    except OSError as exc:
        raise ValueError("private result root is unavailable") from exc
    if (
        not stat.S_ISDIR(root_metadata.st_mode)
        or root_metadata.st_uid != os.geteuid()
        or stat.S_IMODE(root_metadata.st_mode) & 0o077
    ):
        raise ValueError("private result root ownership is invalid")
    proof = _open_verified_artifact(result_path, results_root, allow_absolute=True)
    if proof is None:
        raise ValueError("private result is unavailable or redirected")
    try:
        metadata = os.fstat(proof.descriptor)
        if (
            metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) != 0o400
            or proof.digest != expected_digest
        ):
            raise ValueError("private result does not match its recorded digest")
        return proof
    except BaseException:
        proof.close()
        raise


def read_private_result(
    *, run_root: Path, result_path: Path, expected_digest: str,
) -> bytes:
    """Read one digest-bound result through the private component boundary."""
    with _open_private_result(
        run_root=run_root,
        result_path=result_path,
        expected_digest=expected_digest,
    ) as proof:
        return proof.payload


def seal_private_result(
    *, run_root: Path, result_path: Path, expected_digest: str,
) -> None:
    """Verify and seal the exact digest-bound result descriptor."""
    proof = _open_private_result(
        run_root=run_root,
        result_path=result_path,
        expected_digest=expected_digest,
    )
    with ExitStack() as stack:
        stack.enter_context(proof)
        os.fchmod(proof.descriptor, 0o400)
        os.fsync(proof.descriptor)
        sealed = os.fstat(proof.descriptor)
        if (
            sealed.st_dev != proof.device
            or sealed.st_ino != proof.inode
            or sealed.st_size != proof.size
            or stat.S_IMODE(sealed.st_mode) != 0o400
        ):
            raise ValueError("private result changed while sealing")
        visible = _open_private_result(
            run_root=run_root,
            result_path=result_path,
            expected_digest=expected_digest,
        )
        if visible is None:
            raise ValueError("private result changed while sealing")
        stack.enter_context(visible)
        if (
            not proof.same_identity(visible)
            or stat.S_IMODE(os.fstat(visible.descriptor).st_mode) != 0o400
        ):
            raise ValueError("private result changed while sealing")


def _write_immutable_result(path: Path, payload: bytes) -> bool:
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o400,
        )
    except FileExistsError:
        try:
            metadata = os.lstat(path)
            return (
                stat.S_ISREG(metadata.st_mode)
                and stat.S_IMODE(metadata.st_mode) == 0o400
                and _read_regular(
                    path, missing_message="repaired result is unsafe",
                ) == payload
            )
        except (OSError, ValueError):
            return False
    except OSError:
        return False
    try:
        _write_all(descriptor, payload)
        os.fchmod(descriptor, 0o400)
        os.fsync(descriptor)
    except OSError:
        os.close(descriptor)
        try:
            path.unlink()
        except OSError:
            pass
        return False
    os.close(descriptor)
    try:
        _fsync_directory(path.parent)
    except OSError:
        return False
    return True


def repair_result_envelope(
    *,
    run_root: Path,
    worktree: Path,
    original_result_path: Path,
) -> EnvelopeRepair | None:
    """Normalize only safe absolute workflow artifact spellings."""
    with ExitStack() as stack:
        try:
            root = run_root.resolve(strict=True)
            results_root = (root / "results").resolve(strict=True)
        except OSError:
            return None
        original_proof = _open_verified_artifact(
            original_result_path, results_root, allow_absolute=True,
        )
        if original_proof is None:
            return None
        stack.enter_context(original_proof)
        original = original_proof.canonical_path
        original_bytes = original_proof.payload
        payload = strict_json_object(original_bytes)
        if payload is None or not _valid_result_envelope(payload):
            return None
        plan_id = str(payload["plan_id"])
        if _bound_unsafe_failure(
            run_root=root,
            plan_id=plan_id,
            original_result_path=original,
            original_digest=original_proof.digest,
        ) is None:
            return None
        if (
            _git_output(worktree, "rev-parse", "HEAD") != payload["head_commit"]
            or _git_output(worktree, "status", "--porcelain", "--untracked-files=all") != ""
        ):
            return None

        receipt = payload["workflow_receipt"]
        assert isinstance(receipt, dict)
        repaired = json.loads(json.dumps(payload))
        repaired_receipt = repaired["workflow_receipt"]
        assert isinstance(repaired_receipt, dict)
        changed_fields: list[str] = []
        artifact_declarations: dict[str, tuple[Path, bool]] = {}
        artifacts: dict[str, _VerifiedArtifact] = {}
        for field in ("ledger_path", "final_review_path"):
            declared = Path(str(receipt[field]))
            proof = _open_verified_artifact(declared, worktree, allow_absolute=True)
            if proof is None:
                return None
            stack.enter_context(proof)
            artifacts[field] = proof
            artifact_declarations[field] = (declared, True)
            if declared.is_absolute():
                repaired_receipt[field] = proof.relative_path.as_posix()
                changed_fields.append(f"/workflow_receipt/{field}")
        verification = payload["verification"]
        assert isinstance(verification, list)
        for index, item in enumerate(verification):
            assert isinstance(item, dict)
            raw_receipt = item.get("receipt_path")
            if raw_receipt in {None, ""}:
                continue
            declared = Path(str(raw_receipt))
            proof = _open_verified_artifact(declared, worktree, allow_absolute=False)
            if proof is None:
                return None
            stack.enter_context(proof)
            key = f"verification:{index}"
            artifacts[key] = proof
            artifact_declarations[key] = (declared, False)
        if not changed_fields or not _valid_result_envelope(repaired):
            return None
        if _semantic_projection(repaired) != _semantic_projection(payload):
            return None
        try:
            events = _validate_execution_ledger_payload(
                artifacts["ledger_path"].payload, expected_plan_id=plan_id,
            )
        except ValueError:
            return None
        expected_verification = {
            (
                str(item["command_id"]), str(item["argv_digest"]),
                str(item["evidence_key"]),
            )
            for item in payload["verification"]
            if isinstance(item, dict)
        }
        observed_verification = {
            (
                str(event["command_id"]), str(event["argv_digest"]),
                str(event["evidence_key"]),
            )
            for event in events
            if event.get("category") == "verification"
            and event.get("action") in {"verified", "executed_uncached"}
            and event.get("result") == "pass"
        }
        if (
            receipt.get("open_finding_ids") != []
            or receipt.get("open_obligation_ids") != []
            or expected_verification != observed_verification
        ):
            return None

        # Re-open through the owned root immediately before acceptance and
        # compare the complete descriptor proof to defeat component swaps.
        for key, (declared, allow_absolute) in artifact_declarations.items():
            current = _open_verified_artifact(
                declared, worktree, allow_absolute=allow_absolute,
            )
            if current is None:
                return None
            stack.enter_context(current)
            if not artifacts[key].same_identity(current):
                return None
        current_original = _open_verified_artifact(
            original_result_path, results_root, allow_absolute=True,
        )
        if current_original is None:
            return None
        stack.enter_context(current_original)
        if not original_proof.same_identity(current_original):
            return None
        repaired_bytes = json.dumps(
            repaired, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
        repaired_digest = hashlib.sha256(repaired_bytes).hexdigest()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,200}", original.stem):
            return None
        repaired_root = results_root / "repaired"
        try:
            repaired_root.mkdir(mode=0o700, parents=True, exist_ok=True)
            if repaired_root.is_symlink() or not repaired_root.is_dir():
                return None
            repaired_root.chmod(0o700)
        except OSError:
            return None
        repaired_path = repaired_root / f"{original.stem}-{repaired_digest}.json"
        if not _write_immutable_result(repaired_path, repaired_bytes):
            return None
        try:
            os.fchmod(original_proof.descriptor, 0o400)
            os.fsync(original_proof.descriptor)
        except OSError:
            return None
        return EnvelopeRepair(
            original_path=original,
            repaired_path=repaired_path,
            original_digest=original_proof.digest,
            repaired_digest=repaired_digest,
            changed_fields=tuple(changed_fields),
        )
