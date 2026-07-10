from __future__ import annotations

import fcntl
import hashlib
import json
import os
import secrets
import shutil
import tempfile
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .events import WRITABLE_EVENT_TYPES, append_event, read_events, validate_chain
from .evidence import verify_ref
from .manifest import load_verified_manifest, resolve_ref, validate_manifest
from .model_policy import CORE_ROUTE
from .packets import PacketDraft, verify_packet
from .projector import (
    RETRY_PHASE_STATES,
    RUN_TRANSITIONS,
    TASK_TRANSITIONS,
    owned_active_blocker,
    project,
    valid_attempt_completion,
    valid_evidence_refs,
    valid_verdict,
)


TASK_COMPLETION_ATTEMPT_KINDS = frozenset({"implementation", "task_review", "verification"})


@dataclass(frozen=True)
class Transition:
    event_type: str
    payload: dict[str, object]
    task_id: str | None = None
    attempt_id: str | None = None


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


def _completion_ready(run_dir: Path, manifest: dict, state: dict) -> bool:
    if not state.get("tasks") or any(item.get("status") != "completed" for item in state["tasks"].values()):
        return False
    if state.get("active_blockers", state.get("blockers", [])):
        return False
    for task_id in state["tasks"]:
        if not TASK_COMPLETION_ATTEMPT_KINDS.issubset(_attempt_kinds(state, task_id)):
            return False
        kinds = {item.get("kind") for item in state.get("artifact_index", []) if item.get("task_id") == task_id}
        if not {"acceptance", "verification"}.issubset(kinds):
            return False
    if "final_review" not in _attempt_kinds(state, None):
        return False
    audit = state.get("completion_audit")
    if validate_manifest(manifest):
        return False
    try:
        for task_id in state["tasks"]:
            verify_packet(run_dir, manifest, task_id)
    except ValueError:
        return False
    snapshot = run_dir / "state.json"
    if not snapshot.is_file():
        return False
    try:
        if json.loads(snapshot.read_text(encoding="utf-8")) != state:
            return False
    except (OSError, json.JSONDecodeError):
        return False
    for item in state.get("artifact_index", []):
        ref = item.get("ref")
        if not isinstance(ref, dict) or verify_ref(run_dir, ref):
            return False
    audit_evidence = audit.get("verification_evidence") if isinstance(audit, dict) else None
    indexed_refs = {
        json.dumps(item.get("ref"), sort_keys=True)
        for item in state.get("artifact_index", [])
        if isinstance(item.get("ref"), dict)
    }
    if not isinstance(audit_evidence, list) or not audit_evidence:
        return False
    audit_refs = set()
    for ref in audit_evidence:
        if not isinstance(ref, dict) or json.dumps(ref, sort_keys=True) not in indexed_refs or verify_ref(run_dir, ref):
            return False
        audit_refs.add(json.dumps(ref, sort_keys=True))
    if audit_refs != indexed_refs:
        return False
    try:
        worktree = resolve_ref(str(manifest["execution_worktree_ref"]))
        result = subprocess.run(["git", "status", "--porcelain=v1", "--untracked-files=all"], cwd=worktree, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode:
            return False
        changed = {line[3:].split(" -> ")[-1] for line in result.stdout.splitlines() if len(line) >= 4}
        claims = {str(path) for task in manifest.get("task_graph", []) for path in task.get("file_claims", [])}
        if not changed.issubset(claims):
            return False
        expected_head = ((manifest.get("source_git") or {}).get("head"))
        if expected_head:
            head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=worktree, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if head.returncode or head.stdout.strip() != expected_head:
                return False
    except (OSError, KeyError, ValueError):
        return False
    return bool(
        isinstance(audit, dict)
        and audit.get("passed") is True
        and audit.get("verification_evidence")
        and audit.get("prompt_to_artifact_checklist")
    )


def _validate_transition(run_dir: Path, manifest: dict, state: dict, command: Transition) -> None:
    if command.event_type not in WRITABLE_EVENT_TYPES:
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
        if target == "completed" and not _completion_ready(run_dir, manifest, state):
            raise ValueError("completion gate failed")
        return
    if command.event_type == "task.status_changed":
        if command.task_id not in state["tasks"]:
            raise ValueError("unknown task")
        current = state["tasks"][command.task_id]["status"]
        if payload.get("from") != current:
            raise ValueError("task transition from mismatch")
        target = payload.get("to")
        if target not in TASK_TRANSITIONS.get(current, set()):
            raise ValueError("invalid task transition")
        if target == "completed" and not TASK_COMPLETION_ATTEMPT_KINDS.issubset(
            _attempt_kinds(state, command.task_id)
        ):
            raise ValueError("task completion gate failed")
        return
    if command.task_id is not None and command.task_id not in state["tasks"]:
        raise ValueError("unknown task")
    if command.event_type == "task.retry_scheduled":
        phase = payload.get("phase")
        revision = payload.get("worktree_revision")
        if phase not in RETRY_PHASE_STATES:
            raise ValueError("invalid retry phase")
        if (
            state["tasks"][command.task_id]["status"] != "blocked"
            or not isinstance(payload.get("root_cause_key"), str)
            or not payload["root_cause_key"]
            or not isinstance(revision, int)
            or isinstance(revision, bool)
            or revision != state.get("worktree_revision", 0)
            or any(item.get("task_id") == command.task_id for item in state.get("active_blockers", []))
            or not valid_evidence_refs(payload.get("evidence_refs"))
        ):
            raise ValueError("invalid retry payload")
    elif command.event_type == "attempt.started":
        if (
            not command.attempt_id
            or not isinstance(payload.get("kind"), str)
            or not payload["kind"]
            or any(item.get("attempt_id") == command.attempt_id for item in state.get("attempts", []))
        ):
            raise ValueError("invalid attempt payload")
    elif command.event_type == "attempt.completed":
        if not valid_attempt_completion(state, command.task_id, command.attempt_id, payload):
            raise ValueError("invalid attempt payload")
    elif command.event_type == "verdict.recorded":
        if not valid_verdict(state, command.task_id, command.attempt_id, payload):
            raise ValueError("invalid verdict payload")
    elif command.event_type == "worktree.revision_recorded":
        source = payload.get("from")
        target = payload.get("to")
        digest = payload.get("patch_sha256")
        valid_digest = (
            isinstance(digest, str)
            and len(digest) == 64
            and all(character in "0123456789abcdef" for character in digest)
        )
        if (
            not isinstance(source, int)
            or isinstance(source, bool)
            or not isinstance(target, int)
            or isinstance(target, bool)
            or source != state.get("worktree_revision", 0)
            or target != source + 1
            or not valid_digest
        ):
            raise ValueError("invalid worktree revision payload")
        changed_files = payload.get("changed_files")
        if changed_files is not None and (
            not isinstance(changed_files, list)
            or any(not isinstance(path, str) or not path for path in changed_files)
        ):
            raise ValueError("invalid worktree revision payload")
        payload_attempt_id = payload.get("attempt_id")
        if payload_attempt_id is not None and (
            not isinstance(payload_attempt_id, str) or not payload_attempt_id
        ):
            raise ValueError("invalid worktree revision payload")
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
    elif command.event_type == "blocker.updated":
        blocker_id = payload.get("blocker_id")
        if (
            not isinstance(blocker_id, str)
            or owned_active_blocker(state, command.task_id, blocker_id) is None
            or len(payload) < 2
            or bool({"status", "task_id"} & payload.keys())
        ):
            raise ValueError("invalid blocker update payload")
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
    elif command.event_type == "completion.recorded":
        if payload.get("passed") is not True:
            raise ValueError("completion evidence must pass")
    elif command.event_type == "context.updated":
        if payload.get("status") not in {"green", "yellow", "red"}:
            raise ValueError("invalid context payload")
    elif command.event_type == "repair.applied":
        if not payload.get("action") or "before" not in payload or "after" not in payload:
            raise ValueError("invalid repair payload")


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


class RunKernel(Kernel):
    @classmethod
    def initialize(cls, run_dir: Path, manifest: dict, packet_drafts: list[PacketDraft]) -> "RunKernel":
        run_dir = run_dir.expanduser().resolve()
        if run_dir.exists():
            raise FileExistsError(run_dir)
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
        errors = validate_manifest(initialized_manifest)
        if errors:
            raise ValueError(errors[0])
        run_dir.parent.mkdir(parents=True, exist_ok=True)
        stage = run_dir.parent / f".{run_dir.name}.initialize-{secrets.token_hex(6)}"
        stage.mkdir(mode=0o700)
        published = False
        try:
            for draft in packet_drafts:
                _write_packet_exclusive(stage, draft)
            write_path = stage / "run_manifest.json"
            from .manifest import write_manifest

            write_manifest(write_path, initialized_manifest)
            staged_manifest = load_verified_manifest(write_path)
            for draft in packet_drafts:
                if verify_packet(stage, staged_manifest, draft.task_id) != draft:
                    raise ValueError("packet_digest_mismatch")
            os.replace(stage, run_dir)
            _fsync_dir(run_dir.parent)
            published = True
        finally:
            if not published:
                shutil.rmtree(stage, ignore_errors=True)
        return cls(run_dir)


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
