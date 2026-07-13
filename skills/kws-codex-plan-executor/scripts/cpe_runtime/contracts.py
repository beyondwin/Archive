"""Strict schema-4 value contracts shared by the lean CPE runtime."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import PurePosixPath


SCHEMA_VERSION = 4
RUN_STATUSES = frozenset(
    {
        "mapping",
        "running",
        "waiting_authority",
        "interrupted",
        "final_audit",
        "completed",
        "failed",
    }
)
CHILD_STATUSES = frozenset(
    {
        "completed",
        "changes_requested",
        "waiting_authority",
        "interrupted",
        "failed",
    }
)
VERDICTS = frozenset({"pass", "changes_requested", "blocked", None})
AUTHORITY_CODES = frozenset(
    {
        "credential_required",
        "external_side_effect",
        "destructive_outside_worktree",
        "authoritative_document_conflict",
        "material_scope_expansion",
        "legal_security_policy_authority",
    }
)
CHILD_ROLES = frozenset(
    {
        "document_mapper",
        "program_mapper",
        "task_agent",
        "reviewer",
        "fix_agent",
        "investigator",
        "document_auditor",
        "program_final_integrator",
        "integration_fix_agent",
    }
)
WRITE_ROLES = frozenset({"task_agent", "fix_agent", "integration_fix_agent"})
VERDICT_ROLES = frozenset(
    {"reviewer", "document_auditor", "program_final_integrator"}
)

_CHILD_RESULT_KEYS = frozenset(
    {
        "role",
        "status",
        "item_id",
        "commit",
        "verdict",
        "failure_code",
        "authority_id",
        "strategy_key",
        "affected_document_ids",
        "artifact_paths",
        "summary",
    }
)


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def normalize_relative_path(value: str) -> str:
    """Return one unambiguous, normalized POSIX path below a run root."""

    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("artifact path must be a non-empty POSIX relative path")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("artifact path must be normalized without parent traversal")
    path = PurePosixPath(value)
    if path.is_absolute() or path.as_posix() != value or parts[0].endswith(":"):
        raise ValueError("artifact path must be a normalized relative path")
    return path.as_posix()


@dataclass(frozen=True)
class InputDocument:
    document_id: str
    role: str
    original_path: str
    snapshot_path: str
    sha256: str
    byte_length: int
    input_order: int

    def to_json(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ChildResult:
    role: str
    status: str
    item_id: str
    commit: str | None
    verdict: str | None
    failure_code: str | None
    authority_id: str | None
    strategy_key: str | None
    affected_document_ids: tuple[str, ...]
    artifact_paths: tuple[str, ...]
    summary: str


def _required_string(payload: Mapping[str, object], key: str) -> str:
    value = payload[key]
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _nullable_string(payload: Mapping[str, object], key: str) -> str | None:
    value = payload[key]
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be null or a non-empty string")
    return value


def _string_array(payload: Mapping[str, object], key: str) -> tuple[str, ...]:
    value = payload[key]
    if not isinstance(value, list):
        raise ValueError(f"{key} must be an array")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{key} entries must be non-empty strings")
        if item in result:
            raise ValueError(f"{key} entries must be unique")
        result.append(item)
    return tuple(result)


def validate_child_result(
    payload: Mapping[str, object], expected_role: str, expected_item_id: str
) -> ChildResult:
    """Validate an untrusted child handoff without a validation framework."""

    if not isinstance(payload, Mapping):
        raise ValueError("child result must be an object")
    keys = frozenset(payload.keys())
    if keys != _CHILD_RESULT_KEYS:
        missing = sorted(_CHILD_RESULT_KEYS - keys)
        extra = sorted(keys - _CHILD_RESULT_KEYS)
        raise ValueError(f"child result keys differ: missing={missing}, extra={extra}")

    role = _required_string(payload, "role")
    if role not in CHILD_ROLES:
        raise ValueError(f"unknown child role: {role}")
    if role != expected_role:
        raise ValueError("child role does not match the requested role")

    status = _required_string(payload, "status")
    if status not in CHILD_STATUSES:
        raise ValueError(f"unknown child status: {status}")
    item_id = _required_string(payload, "item_id")
    if item_id != expected_item_id:
        raise ValueError("child item_id does not match the requested item")

    commit = _nullable_string(payload, "commit")
    verdict_value = payload["verdict"]
    if verdict_value is not None and not isinstance(verdict_value, str):
        raise ValueError("verdict must be null or a string")
    if verdict_value not in VERDICTS:
        raise ValueError(f"unknown child verdict: {verdict_value}")
    verdict = verdict_value if isinstance(verdict_value, str) else None
    failure_code = _nullable_string(payload, "failure_code")
    authority_id = _nullable_string(payload, "authority_id")
    strategy_key = _nullable_string(payload, "strategy_key")
    affected_document_ids = _string_array(payload, "affected_document_ids")
    artifact_paths = tuple(
        normalize_relative_path(path)
        for path in _string_array(payload, "artifact_paths")
    )
    summary = _required_string(payload, "summary")
    if len(summary) > 2000:
        raise ValueError("summary must contain at most 2000 characters")

    if role in WRITE_ROLES and status == "completed" and commit is None:
        raise ValueError("a completed write role must report its commit")
    if role not in VERDICT_ROLES and verdict is not None:
        raise ValueError(f"role {role} cannot report a verdict")
    if authority_id is not None and authority_id not in AUTHORITY_CODES:
        raise ValueError(f"unknown authority code: {authority_id}")
    if status == "waiting_authority" and authority_id is None:
        raise ValueError("waiting_authority requires an allowlisted authority code")
    if status != "waiting_authority" and authority_id is not None:
        raise ValueError("authority code is legal only for waiting_authority")

    return ChildResult(
        role=role,
        status=status,
        item_id=item_id,
        commit=commit,
        verdict=verdict,
        failure_code=failure_code,
        authority_id=authority_id,
        strategy_key=strategy_key,
        affected_document_ids=affected_document_ids,
        artifact_paths=artifact_paths,
        summary=summary,
    )
