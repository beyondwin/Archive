from __future__ import annotations

import json
import os
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from .db import AgentRunwayDb
from .models import AGENTLENS_EVENT_SCHEMA, AGENTRUNWAY_VERSION, EVENT_SCHEMA


SECRET_KEYS = {"token", "api_key", "secret", "password"}
MAX_EVENT_PAYLOAD_BYTES = 3500
AGENTLENS_EVENT_PHASES = {
    "run",
    "contract",
    "worker",
    "review",
    "verification",
    "retry",
    "quality",
    "merge",
    "resume",
    "apply",
    "finish",
}
AGENTLENS_PHASE_ALIASES = {
    "agentlens": "run",
    "artifacts": "contract",
    "gate": "retry",
    "planning": "run",
    "simulation": "worker",
}


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


def _payload_size(payload: dict[str, Any]) -> int:
    return len(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8"))


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _trust_impact(outcome: str, payload: dict[str, Any]) -> str:
    if payload.get("payload_truncated") or payload.get("simulation") is True:
        return "downgrades_trust"
    if outcome == "success":
        return "supports_success"
    if outcome in {"failed", "blocked"}:
        return "supports_failure"
    if outcome == "partial":
        return "requires_attention"
    return "neutral"


def _list_or_empty(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _agentlens_phase(value: Any, *, event_type: str) -> str:
    if event_type == "agentrunway.run_finished":
        return "finish"
    phase = str(value or "run")
    phase = AGENTLENS_PHASE_ALIASES.get(phase, phase)
    return phase if phase in AGENTLENS_EVENT_PHASES else "run"


def _bound_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if _payload_size(payload) <= MAX_EVENT_PAYLOAD_BYTES:
        return payload
    bounded = dict(payload)
    omission = {"omitted": True, "reason": "size"}
    for key in ("gate_result", "previous_candidate", "changed_files"):
        if key in bounded:
            bounded[key] = omission
    bounded["payload_truncated"] = True
    if _payload_size(bounded) <= MAX_EVENT_PAYLOAD_BYTES:
        return bounded
    protected = {
        "schema",
        "run_id",
        "agentrunway_run_id",
        "phase",
        "outcome",
        "severity",
        "summary",
        "privacy",
        "payload_truncated",
        "task_id",
        "attempt_id",
        "candidate_id",
        "gate_id",
        "evidence_refs",
        "artifact_refs",
        "trust_impact",
        "spec_refs",
        "status",
        "simulation",
    }
    truncated_keys = [key for key in bounded if key not in protected]
    bounded["truncated_keys"] = truncated_keys
    for key in truncated_keys:
        bounded[key] = omission
    if _payload_size(bounded) <= MAX_EVENT_PAYLOAD_BYTES:
        return bounded
    for key in truncated_keys:
        bounded.pop(key, None)
    if _payload_size(bounded) <= MAX_EVENT_PAYLOAD_BYTES:
        return bounded
    bounded["summary"] = str(bounded.get("summary", ""))[:512]
    return bounded


def build_event_payload(run_id: str, phase: str, outcome: str, summary: str, **extra: Any) -> dict[str, Any]:
    payload = {
        "schema": EVENT_SCHEMA,
        "run_id": run_id,
        "agentrunway_run_id": run_id,
        "phase": phase,
        "outcome": outcome,
        "severity": "error" if outcome == "failed" else ("info" if outcome == "success" else "warn"),
        "summary": summary[:1200],
        "payload_truncated": False,
        "privacy": {"redacted": True, "policy": "home paths and secret-like keys"},
    }
    payload.update(extra)
    return _bound_payload(redact_payload(payload))


def build_agentlens_event_envelope(
    *,
    event_id: int,
    event_type: str,
    payload: dict[str, Any],
    occurred_at: str | None = None,
) -> dict[str, Any]:
    run_id = str(payload.get("run_id") or payload.get("agentrunway_run_id") or "")
    outcome = str(payload.get("outcome") or "unknown")
    timestamp = occurred_at or _utc_now_iso()
    event = {
        "schema": AGENTLENS_EVENT_SCHEMA,
        "event_id": f"evt_{event_id:06d}",
        "run_id": run_id,
        "event_type": event_type,
        "producer": {"name": "agentrunway", "version": AGENTRUNWAY_VERSION},
        "occurred_at": timestamp,
        "sequence": event_id,
        "phase": _agentlens_phase(payload.get("phase"), event_type=event_type),
        "outcome": outcome,
        "severity": str(payload.get("severity") or "info"),
        "evidence_refs": _list_or_empty(payload.get("evidence_refs")),
        "artifact_refs": _list_or_empty(payload.get("artifact_refs")),
        "trust_impact": str(payload.get("trust_impact") or _trust_impact(outcome, payload)),
        "summary": str(payload.get("summary") or "")[:1200],
        "payload": payload,
    }
    for key in ("task_id", "attempt_id", "candidate_id", "gate_id"):
        value = payload.get(key)
        if value is not None:
            event[key] = str(value)
    return event


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
        payload_with_name = dict(payload)
        payload_with_name.setdefault("event_name", event_type)
        redacted = redact_payload(payload_with_name)
        event_id = self.db.insert_event(event_type=event_type, payload=redacted, status="agentlens_pending", error=None)
        status = "agentlens_disabled"
        error: str | None = None
        if self.agentlens_emitter is not None:
            try:
                outbound_payload = dict(redacted)
                outbound_payload["agentlens_status"] = "agentlens_emitted"
                self.agentlens_emitter.emit(
                    event_type,
                    build_agentlens_event_envelope(
                        event_id=event_id,
                        event_type=event_type,
                        payload=outbound_payload,
                    ),
                )
            except Exception as exc:
                status = "agentlens_failed"
                error = str(exc)
            else:
                status = "agentlens_emitted"
        journal_payload = dict(redacted)
        journal_payload["agentlens_status"] = status
        if error is not None:
            journal_payload["agentlens_error"] = str(redact_payload(error))
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.db.update_event(event_id, payload=journal_payload, status=status, error=error)
        event_line = build_agentlens_event_envelope(
            event_id=event_id,
            event_type=event_type,
            payload=journal_payload,
        )
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event_line, ensure_ascii=False, sort_keys=True) + "\n")
        return EventRecord(id=event_id, event_type=event_type, status=status, payload=journal_payload, error=error)

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
