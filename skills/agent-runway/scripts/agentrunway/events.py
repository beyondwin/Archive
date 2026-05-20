from __future__ import annotations

import json
import os
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .db import AgentRunwayDb
from .models import EVENT_SCHEMA


SECRET_KEYS = {"token", "api_key", "secret", "password"}


def redact_payload(payload: Any) -> Any:
    home = os.environ.get("HOME", "")
    if isinstance(payload, dict):
        redacted = {}
        for key, value in payload.items():
            if key.lower() in SECRET_KEYS:
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = redact_payload(value)
        return redacted
    if isinstance(payload, list):
        return [redact_payload(item) for item in payload]
    if isinstance(payload, str) and home:
        return payload.replace(home, "~")
    return deepcopy(payload)


def build_event_payload(run_id: str, phase: str, outcome: str, summary: str, **extra: Any) -> dict[str, Any]:
    payload = {
        "schema": EVENT_SCHEMA,
        "agentrunway_run_id": run_id,
        "phase": phase,
        "outcome": outcome,
        "severity": "info" if outcome == "success" else "warn",
        "summary": summary[:1200],
        "privacy": {"redacted": True, "policy": "home paths and secret-like keys"},
    }
    payload.update(extra)
    return redact_payload(payload)


class AgentLensEmitter(Protocol):
    def emit(self, event_type: str, payload: dict[str, object]) -> None:
        ...


@dataclass(frozen=True)
class EventRecord:
    id: int
    event_type: str
    status: str
    payload: dict[str, Any]
    error: str | None = None


class EventJournal:
    def __init__(self, *, db: AgentRunwayDb, run_dir: Path, agentlens_emitter: AgentLensEmitter | None = None):
        self.db = db
        self.run_dir = run_dir
        self.agentlens_emitter = agentlens_emitter
        self.events_path = run_dir / "events.jsonl"

    def record(self, event_type: str, payload: dict[str, Any]) -> EventRecord:
        redacted = redact_payload(payload)
        status = "agentlens_disabled"
        error: str | None = None
        if self.agentlens_emitter is not None:
            try:
                self.agentlens_emitter.emit(event_type, redacted)
            except Exception as exc:
                status = "agentlens_failed"
                error = str(exc)
            else:
                status = "agentlens_emitted"
        self.run_dir.mkdir(parents=True, exist_ok=True)
        event_line = {"event_type": event_type, "payload": redacted, "status": status, "error": error}
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event_line, ensure_ascii=False, sort_keys=True) + "\n")
        event_id = self.db.insert_event(event_type=event_type, payload=redacted, status=status, error=error)
        return EventRecord(id=event_id, event_type=event_type, status=status, payload=redacted, error=error)

    def list(self) -> list[dict[str, Any]]:
        return self.db.list_events()


def write_event_artifact(run_dir: Path, event_type: str, payload: dict[str, Any]) -> Path:
    event_dir = run_dir / "events"
    event_dir.mkdir(parents=True, exist_ok=True)
    safe_type = event_type.replace("/", "_").replace(" ", "_")
    path = event_dir / f"{safe_type}.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(redact_payload(payload), ensure_ascii=False, sort_keys=True) + "\n")
    return path
