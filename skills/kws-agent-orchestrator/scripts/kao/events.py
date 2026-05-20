from __future__ import annotations

import os
from copy import deepcopy
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
        "kao_run_id": run_id,
        "phase": phase,
        "outcome": outcome,
        "severity": "info" if outcome == "success" else "warn",
        "summary": summary[:1200],
        "privacy": {"redacted": True, "policy": "home paths and secret-like keys"},
    }
    payload.update(extra)
    return redact_payload(payload)
