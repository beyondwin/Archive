from __future__ import annotations

import fcntl
import json
import os
import tempfile
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .events import EVENT_TYPES, append_event, read_events, validate_chain
from .evidence import verify_ref
from .manifest import load_verified_manifest, resolve_ref, validate_manifest
from .model_policy import CORE_ROUTE
from .projector import RUN_TRANSITIONS, TASK_TRANSITIONS, project


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
    if state.get("blockers"):
        return False
    for task_id in state["tasks"]:
        if not {"implementation", "review", "verification"}.issubset(_attempt_kinds(state, task_id)):
            return False
        kinds = {item.get("kind") for item in state.get("artifact_index", []) if item.get("task_id") == task_id}
        if not {"acceptance", "verification"}.issubset(kinds):
            return False
    if "final_review" not in _attempt_kinds(state, None):
        return False
    audit = state.get("completion_audit")
    if validate_manifest(manifest):
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
        if target == "completed" and not {"implementation", "review", "verification"}.issubset(
            _attempt_kinds(state, command.task_id)
        ):
            raise ValueError("task completion gate failed")
        return
    if command.task_id is not None and command.task_id not in state["tasks"]:
        raise ValueError("unknown task")
    if command.event_type == "attempt.recorded":
        required = {"kind", "status", "attestation", "usage", "latency_ms"}
        if not required.issubset(payload) or not command.attempt_id:
            raise ValueError("invalid attempt payload")
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
