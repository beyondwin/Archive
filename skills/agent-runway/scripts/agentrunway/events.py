from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

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


def write_event_artifact(run_dir: Path, event_type: str, payload: dict[str, Any]) -> Path:
    event_dir = run_dir / "events"
    event_dir.mkdir(parents=True, exist_ok=True)
    safe_type = event_type.replace("/", "_").replace(" ", "_")
    path = event_dir / f"{safe_type}.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(redact_payload(payload), ensure_ascii=False, sort_keys=True) + "\n")
    return path
