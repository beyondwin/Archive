from __future__ import annotations

import fcntl
import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path


EVENT_TYPES = frozenset(
    {
        "run.status_changed",
        "task.status_changed",
        "attempt.started",
        "attempt.completed",
        "verdict.recorded",
        "evidence.attached",
        "candidate.checkpoint_recorded",
        "task.checkpoint_verified",
        "blocker.opened",
        "blocker.resolved",
        "decision.recorded",
        "notification.requested",
        "runtime.upgraded",
        "completion.recorded",
    }
)


def canonical_event_hash(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _fsync_dir(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def append_event(path: Path, unsigned: dict) -> dict:
    if unsigned.get("type") not in EVENT_TYPES:
        raise ValueError("unknown event type")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.seek(0)
        events = [json.loads(line) for line in handle if line.strip()]
        chain_errors = validate_chain(events)
        if chain_errors:
            raise ValueError("event_chain_invalid")
        previous = events[-1] if events else None
        event = {
            "seq": len(events) + 1,
            "event_id": uuid.uuid4().hex,
            "type": unsigned["type"],
            "at": datetime.now(timezone.utc).isoformat(),
            "actor": "cpe-runtime",
            "task_id": unsigned.get("task_id"),
            "attempt_id": unsigned.get("attempt_id"),
            "payload": unsigned.get("payload", {}),
            "previous_hash": previous["hash"] if previous else None,
        }
        event["hash"] = canonical_event_hash(event)
        handle.seek(0, os.SEEK_END)
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    _fsync_dir(path.parent)
    return event


def read_events(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("event_chain_invalid") from exc


def validate_chain(events: list[dict]) -> list[str]:
    errors: list[str] = []
    seen: set[object] = set()
    previous = None
    for index, event in enumerate(events, 1):
        if event.get("seq") != index:
            errors.append("invalid sequence")
        if event.get("event_id") in seen:
            errors.append("duplicate event ID")
        seen.add(event.get("event_id"))
        if event.get("previous_hash") != previous:
            errors.append("invalid predecessor")
        if event.get("type") not in EVENT_TYPES or event.get("actor") != "cpe-runtime":
            errors.append("invalid event envelope")
        actual = event.get("hash")
        body = dict(event)
        body.pop("hash", None)
        if actual != canonical_event_hash(body):
            errors.append("event hash mismatch")
        previous = actual
    return errors
