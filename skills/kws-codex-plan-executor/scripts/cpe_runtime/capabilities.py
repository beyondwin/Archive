"""Typed capability observations with stable environment fingerprints."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import re
from typing import Literal, Mapping, Sequence

TrustLevel = Literal["parent_observed", "child_attested", "derived", "hypothesis"]
Outcome = Literal["available", "unavailable", "unknown"]

_INCIDENTAL_DETAIL_KEYS = {
    "timestamp", "pid", "probe_port", "temporary_path", "raw_error", "duration_ms"
}
_ALLOWED_DETAIL_KEYS = {
    "loopback_bind": {"host", "host_family", "sandbox_policy"},
    "workspace_write": {"filesystem_type", "sandbox_policy"},
    "git": {"version", "worktree_supported"},
    "graphify_write": {"configured", "sandbox_policy"},
}
_OUTCOMES = {"available", "unavailable", "unknown"}
_TRUST_LEVELS = {"parent_observed", "child_attested", "derived", "hypothesis"}
_SECRET_LIKE_DETAIL_PARTS = {
    "token", "cookie", "password", "secret", "credential", "authorization",
    "apikey", "providerkey",
}
_REASON_CODE = re.compile(r"^[a-z]+(?:_[a-z]+)*$")


@dataclass(frozen=True)
class CapabilityObservation:
    capability: str
    scope: str
    outcome: Outcome
    reason_code: str
    observed_by: TrustLevel
    stable_details: Mapping[str, str]


def _non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value)


def _secret_like_detail_key(key: str) -> bool:
    normalized = "".join(character for character in key.lower() if character.isalnum())
    return any(part in normalized for part in _SECRET_LIKE_DETAIL_PARTS)


def validate_observation(observation: CapabilityObservation) -> None:
    """Reject malformed or unsafe observations before they affect decisions."""
    if not isinstance(observation, CapabilityObservation):
        raise ValueError("capability observation is invalid")
    for field in ("capability", "scope", "reason_code"):
        if not _non_empty_string(getattr(observation, field)):
            raise ValueError(f"capability observation {field} must be non-empty")
    if (not _REASON_CODE.fullmatch(observation.reason_code)
            or _secret_like_detail_key(observation.reason_code)):
        raise ValueError("capability observation reason code is unstable")
    if observation.outcome not in _OUTCOMES:
        raise ValueError("capability observation outcome is unsupported")
    if observation.observed_by not in _TRUST_LEVELS:
        raise ValueError("capability observation trust level is unsupported")
    if not isinstance(observation.stable_details, Mapping):
        raise ValueError("capability observation details must be a mapping")

    allowed_keys = (
        _ALLOWED_DETAIL_KEYS.get(observation.capability, set())
        | _INCIDENTAL_DETAIL_KEYS
    )
    for key, value in observation.stable_details.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ValueError("capability observation details must use string keys and values")
        if _secret_like_detail_key(key):
            raise ValueError("capability observation details must not include secrets")
        if key not in allowed_keys:
            raise ValueError("capability observation detail key is unsupported")


def canonicalize_observation(observation: CapabilityObservation) -> dict[str, object]:
    validate_observation(observation)
    details = {
        key: value
        for key, value in sorted(observation.stable_details.items())
        if key not in _INCIDENTAL_DETAIL_KEYS
        and key in _ALLOWED_DETAIL_KEYS.get(observation.capability, set())
    }
    return {
        "capability": observation.capability,
        "scope": observation.scope,
        "outcome": observation.outcome,
        "reason_code": observation.reason_code,
        "observed_by": observation.observed_by,
        "stable_details": details,
    }


def environment_fingerprint(observations: Sequence[CapabilityObservation]) -> str:
    payload = []
    for item in observations:
        canonical = canonicalize_observation(item)
        canonical.pop("observed_by")
        payload.append(canonical)
    payload.sort(key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")))
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(encoded).hexdigest()


def typed_blockers(observations: Sequence[CapabilityObservation]) -> list[dict[str, object]]:
    for item in observations:
        validate_observation(item)
    return [
        canonicalize_observation(item)
        for item in observations
        if item.outcome == "unavailable" and item.observed_by == "parent_observed"
    ]


def blocker_resume_decision(
    *, previous_fingerprint: str | None, current_fingerprint: str
) -> Literal["launch", "stop_unchanged"]:
    if previous_fingerprint is not None and previous_fingerprint == current_fingerprint:
        return "stop_unchanged"
    return "launch"
