from __future__ import annotations

import fcntl
import hashlib
import json
import os
import secrets
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .events import EVENT_TYPES, append_event, read_events, validate_chain
from .manifest import load_verified_manifest, validate_manifest
from .model_policy import CORE_ROUTE
from .packets import PacketDraft, verify_packet
from .projector import (
    RUN_TRANSITIONS,
    TASK_TRANSITIONS,
    owned_active_blocker,
    project,
    valid_attempt_completion,
    valid_evidence_refs,
    valid_verdict,
    valid_verified_checkpoint_payload,
    validate_task_status_change,
)
from .runtime_upgrade import RuntimeIdentity, validate_runtime_upgrade
from .validation import validate_completion


TASK_COMPLETION_ATTEMPT_KINDS = frozenset({"implementation", "task_review"})


@dataclass(frozen=True)
class Transition:
    event_type: str
    payload: dict[str, object]
    task_id: str | None = None
    attempt_id: str | None = None


@dataclass(frozen=True)
class PreparedRun:
    """A fully fsynced private run tree that has not been published yet."""

    run_dir: Path
    stage: Path

    def cleanup(self) -> None:
        if self.stage.exists():
            shutil.rmtree(self.stage, ignore_errors=True)

    def publish(self) -> "RunKernel":
        if self.run_dir.exists():
            raise FileExistsError(self.run_dir)
        if not self.stage.is_dir():
            raise ValueError("prepared_run_missing")
        os.replace(self.stage, self.run_dir)
        _fsync_dir(self.run_dir.parent)
        manifest = load_verified_manifest(self.run_dir / "run_manifest.json")
        events = read_events(self.run_dir / "events.jsonl")
        if validate_chain(events):
            raise ValueError("event_chain_invalid")
        replayed = project(manifest, events)
        cached = json.loads((self.run_dir / "state.json").read_text(encoding="utf-8"))
        if cached != replayed:
            raise ValueError("snapshot_replay_mismatch")
        return RunKernel(self.run_dir)


def _fsync_dir(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write_snapshot(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw_path = tempfile.mkstemp(prefix=".state.", suffix=".tmp", dir=path.parent)
    tmp = Path(raw_path)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(state, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        _fsync_dir(path.parent)
    finally:
        tmp.unlink(missing_ok=True)


def _core_attempt_ok(attempt: dict) -> bool:
    attestation = attempt.get("attestation") or {}
    return (
        attempt.get("status") == "completed"
        and attestation.get("verified") is True
        and attestation.get("actual_model") == CORE_ROUTE.model
        and attestation.get("actual_reasoning") == CORE_ROUTE.reasoning
    )


def _attempt_kinds(state: dict, task_id: str | None) -> set[str]:
    return {
        str(item.get("kind"))
        for item in state.get("attempts", [])
        if item.get("task_id") == task_id and _core_attempt_ok(item)
    }


def _validate_transition(run_dir: Path, manifest: dict, state: dict, command: Transition) -> None:
    if manifest.get("schema_version") != "4" or state.get("schema_version") != "4":
        raise ValueError("unsupported_run_schema")
    if command.event_type not in EVENT_TYPES:
        raise ValueError("unknown event type")
    payload = command.payload
    if not isinstance(payload, dict):
        raise ValueError("invalid event payload")
    if state["lifecycle"] in {"completed", "failed"}:
        raise ValueError("terminal run is immutable")
    if command.event_type == "run.status_changed":
        if payload.get("from") != state["lifecycle"]:
            raise ValueError("run transition from mismatch")
        target = payload.get("to")
        if target not in RUN_TRANSITIONS.get(state["lifecycle"], set()):
            raise ValueError("invalid run transition")
        if target == "completed":
            report = validate_completion(run_dir, candidate_state=state)
            if not report.passed:
                raise ValueError(f"completion gate failed: {','.join(report.errors)}")
        return
    if command.event_type == "task.status_changed":
        validate_task_status_change(
            state, command.task_id, payload, command.attempt_id
        )
        target = payload.get("to")
        if target == "completed":
            if not TASK_COMPLETION_ATTEMPT_KINDS.issubset(
                _attempt_kinds(state, command.task_id)
            ):
                raise ValueError("task completion model gate failed")
            verified = [
                item
                for item in state.get("verified_checkpoints", [])
                if item.get("task_id") == command.task_id
            ]
            if not verified:
                raise ValueError("task completion verified checkpoint missing")
            deterministic = [
                item
                for item in state.get("artifact_index", [])
                if item.get("task_id") == command.task_id
                and item.get("kind") == "deterministic_verification"
            ]
            if not deterministic:
                raise ValueError("task completion deterministic verification missing")
            checkpoint = verified[-1]
            current_deterministic = [
                item
                for item in deterministic
                if item.get("candidate_commit") == checkpoint.get("commit")
                and item.get("contract_sha256")
                == checkpoint.get("contract_sha256")
                and item.get("passed") is True
            ]
            if not current_deterministic:
                raise ValueError("task completion deterministic verification stale")
        return
    if command.task_id is not None and command.task_id not in state["tasks"]:
        raise ValueError("unknown task")
    if command.event_type == "attempt.started":
        if (
            not command.attempt_id
            or not isinstance(payload.get("kind"), str)
            or not payload["kind"]
            or any(item.get("attempt_id") == command.attempt_id for item in state.get("attempts", []))
            or state["attempt_budget"]["used"] >= state["attempt_budget"]["limit"]
        ):
            raise ValueError("invalid attempt payload")
    elif command.event_type == "attempt.completed":
        if not valid_attempt_completion(state, command.task_id, command.attempt_id, payload):
            raise ValueError("invalid attempt payload")
    elif command.event_type == "verdict.recorded":
        if not valid_verdict(state, command.task_id, command.attempt_id, payload):
            raise ValueError("invalid verdict payload")
    elif command.event_type == "candidate.checkpoint_recorded":
        commits = (payload.get("predecessor"), payload.get("commit"), payload.get("tree"))
        if (
            any(
                not isinstance(value, str)
                or len(value) != 40
                or any(character not in "0123456789abcdef" for character in value)
                for value in commits
            )
            or not isinstance(payload.get("patch_sha256"), str)
            or len(str(payload["patch_sha256"])) != 64
            or any(
                character not in "0123456789abcdef"
                for character in str(payload["patch_sha256"])
            )
        ):
            raise ValueError("invalid checkpoint payload")
        changed_files = payload.get("changed_files")
        if not isinstance(changed_files, list) or any(
            not isinstance(path, str) or not path for path in changed_files
        ):
            raise ValueError("invalid checkpoint payload")
    elif command.event_type == "task.checkpoint_verified":
        if not valid_verified_checkpoint_payload(payload):
            raise ValueError("invalid checkpoint payload")
    elif command.event_type == "blocker.opened":
        required = ("blocker_id", "category", "owner", "resume_condition")
        if (
            any(not isinstance(payload.get(key), str) or not payload[key] for key in required)
            or any(
                item.get("blocker_id") == payload.get("blocker_id")
                for item in state.get("blocker_history", [])
            )
        ):
            raise ValueError("invalid blocker payload")
        root_cause_key = payload.get("root_cause_key")
        if root_cause_key is not None and (
            not isinstance(root_cause_key, str) or not root_cause_key
        ):
            raise ValueError("invalid blocker payload")
    elif command.event_type == "blocker.resolved":
        blocker_id = payload.get("blocker_id")
        if (
            not isinstance(blocker_id, str)
            or owned_active_blocker(state, command.task_id, blocker_id) is None
            or bool({"status", "task_id"} & payload.keys())
            or not valid_evidence_refs(payload.get("evidence_refs"))
        ):
            raise ValueError("invalid blocker resolution payload")
    elif command.event_type == "evidence.attached":
        if not isinstance(payload.get("ref"), dict) or not payload.get("kind"):
            raise ValueError("invalid evidence payload")
        if payload.get("kind") == "deterministic_verification" and (
            not isinstance(payload.get("candidate_commit"), str)
            or not isinstance(payload.get("contract_sha256"), str)
            or payload.get("passed") is not True
        ):
            raise ValueError("invalid evidence payload")
    elif command.event_type == "decision.recorded":
        if (
            not isinstance(payload.get("selected_action"), str)
            or not payload["selected_action"]
            or not isinstance(payload.get("basis"), str)
            or not payload["basis"]
            or payload.get("approval_basis") not in {
                "standing_autonomy_policy",
                "direct_user_approval",
            }
        ):
            raise ValueError("invalid decision payload")
        if payload.get("decision_kind") == "repair_root_updated" and (
            not isinstance(payload.get("root_cause_key"), str)
            or not payload["root_cause_key"]
            or type(payload.get("repair_count")) is not int
            or payload["repair_count"] not in {1, 2}
        ):
            raise ValueError("invalid decision payload")
        if payload.get("decision_kind") == "backlog_added" and not isinstance(
            payload.get("backlog_item"), dict
        ):
            raise ValueError("invalid decision payload")
    elif command.event_type == "notification.requested":
        if not isinstance(payload.get("dedupe_key"), str) or not payload["dedupe_key"]:
            raise ValueError("invalid notification payload")
    elif command.event_type == "runtime.upgraded":
        validate_runtime_upgrade(
            RuntimeIdentity.from_mapping(state.get("runtime")),
            payload,
            checkpoint_head=state.get("checkpoint_head"),
            verified_checkpoints=state.get("verified_checkpoints", []),
        )
    elif command.event_type == "completion.recorded":
        if payload.get("passed") is not True:
            raise ValueError("completion evidence must pass")
        candidate = {**state, "completion_audit": dict(payload)}
        report = validate_completion(run_dir, candidate_state=candidate)
        if not report.passed:
            raise ValueError(f"completion gate failed: {','.join(report.errors)}")


def transition_run(run_dir: Path, command: Transition, snapshot_writer=atomic_write_snapshot) -> dict:
    run_dir = run_dir.resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    lock_path = run_dir / ".kernel.lock"
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        manifest = load_verified_manifest(run_dir / "run_manifest.json")
        events_path = run_dir / "events.jsonl"
        events = read_events(events_path)
        if validate_chain(events):
            raise ValueError("event_chain_invalid")
        state = project(manifest, events)
        _validate_transition(run_dir, manifest, state, command)
        append_event(
            events_path,
            {
                "type": command.event_type,
                "payload": command.payload,
                "task_id": command.task_id,
                "attempt_id": command.attempt_id,
            },
        )
        state = project(manifest, read_events(events_path))
        snapshot_writer(run_dir / "state.json", state)
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    return state


class Kernel:
    def __init__(self, run_dir: Path):
        self.run_dir = run_dir.resolve()
        self._snapshot_writer = atomic_write_snapshot

    def transition(self, command: Transition) -> dict:
        return transition_run(self.run_dir, command, snapshot_writer=self._snapshot_writer)

    @property
    def state(self) -> dict:
        """Return the replayed durable state; never trust the snapshot as input."""
        manifest = load_verified_manifest(self.run_dir / "run_manifest.json")
        events = read_events(self.run_dir / "events.jsonl")
        if validate_chain(events):
            raise ValueError("event_chain_invalid")
        return project(manifest, events)

    def store_patch_evidence(self, patch_bytes: bytes) -> dict[str, str]:
        if not isinstance(patch_bytes, bytes) or not patch_bytes:
            raise ValueError("patch evidence must be non-empty bytes")
        digest = hashlib.sha256(patch_bytes).hexdigest()
        artifacts = self.run_dir / "artifacts"
        artifacts.mkdir(mode=0o700, exist_ok=True)
        if artifacts.is_symlink():
            raise ValueError("patch evidence root must not be a symlink")
        root = artifacts / "patches"
        root.mkdir(mode=0o700, exist_ok=True)
        if root.is_symlink() or root.resolve().parent != self.run_dir.resolve() / "artifacts":
            raise ValueError("patch evidence path escapes run root")
        target = root / f"{digest}.patch"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(target, flags, 0o600)
        except FileExistsError:
            if target.is_symlink():
                raise ValueError("existing patch evidence is not a regular file")
            read_descriptor = os.open(target, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            try:
                with os.fdopen(read_descriptor, "rb", closefd=False) as handle:
                    existing = handle.read()
            finally:
                os.close(read_descriptor)
            if existing != patch_bytes:
                raise ValueError("existing patch evidence has different content")
        else:
            try:
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(patch_bytes)
                    handle.flush()
                    os.fsync(handle.fileno())
            finally:
                _fsync_dir(root)
        return {
            "kind": "patch",
            "path": target.relative_to(self.run_dir).as_posix(),
            "sha256": digest,
            "media_type": "application/octet-stream",
        }


def _write_packet_exclusive(root: Path, draft: PacketDraft) -> None:
    path = root / draft.relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(draft.content)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)
    _fsync_dir(path.parent)


def _stage_input_snapshots(
    root: Path,
    manifest: dict,
    input_sources: tuple[object, ...] | None,
) -> list[dict[str, str]]:
    """Copy verified invocation inputs into the unpublished initialization tree."""

    records: list[tuple[str, bytes, str]] = []
    if input_sources is not None:
        doc_index = 0
        seen: set[str] = set()
        for source in input_sources:
            role = getattr(source, "role", None)
            content = getattr(source, "content", None)
            digest = getattr(source, "sha256", None)
            if role == "doc":
                label = f"doc-{doc_index:03d}"
                doc_index += 1
            elif role in {"plan", "spec"} and role not in seen:
                label = str(role)
                seen.add(label)
            else:
                raise ValueError("compiled_input_shape_invalid")
            if not isinstance(content, bytes) or hashlib.sha256(content).hexdigest() != digest:
                raise ValueError("compiled_input_digest_mismatch")
            records.append((label, content, str(digest)))
    else:
        source_records: list[tuple[str, dict]] = []
        if isinstance(manifest.get("plan"), dict):
            source_records.append(("plan", manifest["plan"]))
        if isinstance(manifest.get("spec"), dict):
            source_records.append(("spec", manifest["spec"]))
        source_records.extend(
            (f"doc-{index:03d}", record)
            for index, record in enumerate(manifest.get("docs") or [])
            if isinstance(record, dict)
        )
        for label, record in source_records:
            source = Path(str(record["ref"])).expanduser().resolve()
            content = source.read_bytes()
            digest = hashlib.sha256(content).hexdigest()
            if digest != record.get("sha256"):
                raise ValueError("manifest_hash_mismatch")
            records.append((label, content, digest))
    snapshots: list[dict[str, str]] = []
    input_root = root / "artifacts" / "inputs"
    input_root.mkdir(parents=True, mode=0o700)
    for label, content, digest in records:
        target = input_root / f"{label}.snapshot"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(target, flags, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        snapshots.append(
            {
                "role": label,
                "path": target.relative_to(root).as_posix(),
                "sha256": digest,
            }
        )
    _fsync_dir(input_root)
    return snapshots


def _validation_manifest_for_stage(manifest: dict, stage: Path, snapshots: list[dict[str, str]]) -> dict:
    """Point a validation-only copy at unpublished bytes without changing durable refs."""

    by_role = {item["role"]: item for item in snapshots}

    def staged_record(label: str, durable: object) -> dict[str, str] | None:
        if durable is None:
            return None
        if not isinstance(durable, dict) or label not in by_role:
            raise ValueError("compiled_input_shape_invalid")
        snapshot = by_role[label]
        if durable.get("sha256") != snapshot["sha256"]:
            raise ValueError("compiled_input_digest_mismatch")
        return {"ref": str(stage / snapshot["path"]), "sha256": snapshot["sha256"]}

    candidate = dict(manifest)
    candidate["plan"] = staged_record("plan", manifest.get("plan"))
    candidate["spec"] = staged_record("spec", manifest.get("spec"))
    docs = manifest.get("docs")
    if not isinstance(docs, list):
        raise ValueError("compiled_input_shape_invalid")
    candidate["docs"] = [staged_record(f"doc-{index:03d}", record) for index, record in enumerate(docs)]
    return candidate


class RunKernel(Kernel):
    @classmethod
    def prepare(
        cls,
        run_dir: Path,
        manifest: dict,
        packet_drafts: list[PacketDraft],
        *,
        input_sources: tuple[object, ...] | None = None,
    ) -> PreparedRun:
        run_dir = run_dir.expanduser().resolve()
        if run_dir.exists():
            raise FileExistsError(run_dir)
        if manifest.get("schema_version") != "4":
            raise ValueError("unsupported_run_schema")
        task_ids = [str(task.get("id")) for task in manifest.get("task_graph", []) if isinstance(task, dict)]
        draft_ids = [draft.task_id for draft in packet_drafts]
        if len(draft_ids) != len(set(draft_ids)) or set(draft_ids) != set(task_ids):
            raise ValueError("packet_index_incomplete")
        for draft in packet_drafts:
            if hashlib.sha256(draft.content).hexdigest() != draft.sha256:
                raise ValueError("packet_digest_mismatch")
        initialized_manifest = dict(manifest)
        initialized_manifest["task_packets"] = [
            {
                "task_id": draft.task_id,
                "path": draft.relative_path,
                "media_type": draft.media_type,
                "sha256": draft.sha256,
            }
            for draft in packet_drafts
        ]
        run_dir.parent.mkdir(parents=True, exist_ok=True)
        stage = run_dir.parent / f".{run_dir.name}.initialize-{secrets.token_hex(6)}"
        stage.mkdir(mode=0o700)
        try:
            snapshots = _stage_input_snapshots(stage, initialized_manifest, input_sources)
            initialized_manifest["input_snapshots"] = snapshots
            for draft in packet_drafts:
                _write_packet_exclusive(stage, draft)
            validation_manifest = _validation_manifest_for_stage(initialized_manifest, stage, snapshots)
            errors = validate_manifest(validation_manifest)
            if errors:
                raise ValueError(errors[0])
            write_path = stage / "run_manifest.json"
            from .manifest import write_manifest

            write_manifest(write_path, initialized_manifest)
            for draft in packet_drafts:
                if verify_packet(stage, initialized_manifest, draft.task_id) != draft:
                    raise ValueError("packet_digest_mismatch")
            events_path = stage / "events.jsonl"
            append_event(
                events_path,
                {
                    "type": "run.status_changed",
                    "payload": {
                        "from": "created",
                        "to": "ready",
                    },
                },
            )
            events = read_events(events_path)
            if validate_chain(events):
                raise ValueError("event_chain_invalid")
            atomic_write_snapshot(stage / "state.json", project(initialized_manifest, events))
            _fsync_dir(stage)
            return PreparedRun(run_dir, stage)
        except BaseException:
            shutil.rmtree(stage, ignore_errors=True)
            raise

    @classmethod
    def initialize(
        cls,
        run_dir: Path,
        manifest: dict,
        packet_drafts: list[PacketDraft],
        *,
        input_sources: tuple[object, ...] | None = None,
    ) -> "RunKernel":
        """Compatibility wrapper for callers that do not need a pre-worktree stage."""

        prepared = cls.prepare(
            run_dir,
            manifest,
            packet_drafts,
            input_sources=input_sources,
        )
        try:
            return prepared.publish()
        finally:
            prepared.cleanup()


def rebuild_snapshot(run_dir: Path) -> dict:
    run_dir = run_dir.resolve()
    lock_path = run_dir / ".kernel.lock"
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        manifest = load_verified_manifest(run_dir / "run_manifest.json")
        events = read_events(run_dir / "events.jsonl")
        if validate_chain(events):
            raise ValueError("event_chain_invalid")
        state = project(manifest, events)
        atomic_write_snapshot(run_dir / "state.json", state)
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    return state
