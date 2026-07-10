from __future__ import annotations

import fcntl
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import uuid


def _hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def append_event(path: Path, unsigned: dict) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.seek(0); events = [json.loads(line) for line in handle if line.strip()]
        previous = events[-1] if events else None
        event = {
            "seq": len(events) + 1, "event_id": uuid.uuid4().hex,
            "at": datetime.now(timezone.utc).isoformat(), "actor": "cpe-runtime",
            **unsigned, "previous_hash": previous["hash"] if previous else None,
        }
        event["hash"] = _hash(event)
        handle.seek(0, 2); handle.write(json.dumps(event, sort_keys=True) + "\n"); handle.flush()
        import os; os.fsync(handle.fileno()); fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    return event


def read_events(path: Path) -> list[dict]:
    if not path.exists(): return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def validate_chain(events: list[dict]) -> list[str]:
    errors = []; seen = set(); previous = None
    for index, event in enumerate(events, 1):
        if event.get("seq") != index: errors.append("invalid sequence")
        if event.get("event_id") in seen: errors.append("duplicate event ID")
        seen.add(event.get("event_id"))
        if event.get("previous_hash") != previous: errors.append("invalid predecessor")
        actual = event.get("hash"); body = dict(event); body.pop("hash", None)
        if actual != _hash(body): errors.append("event hash mismatch")
        previous = actual
    return errors
