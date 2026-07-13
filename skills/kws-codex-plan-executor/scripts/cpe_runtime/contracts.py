"""Strict schema-4 value contracts shared by the lean CPE runtime."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
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
EVENT_TYPES = frozenset(
    {
        "run.created",
        "documents.snapshotted",
        "map.generation_created",
        "task.started",
        "task.reported",
        "review.reported",
        "autonomy.recorded",
        "authority.opened",
        "authority.resolved",
        "run.interrupted",
        "audit.reported",
        "integration.reported",
        "run.completed",
        "run.failed",
    }
)

_EVENT_PAYLOAD_SCHEMAS = {
    "run.created": (
        frozenset({"run_id", "manifest_sha256"}),
        {"run_id": "id", "manifest_sha256": "hash"},
    ),
    "documents.snapshotted": (
        frozenset({"document_set_sha256", "document_ids", "snapshot_sha256s"}),
        {
            "document_set_sha256": "hash",
            "document_ids": "ids",
            "snapshot_sha256s": "hashes",
        },
    ),
    "map.generation_created": (
        frozenset({"generation_id"}),
        {
            "generation_id": "id",
            "map_sha256": "hash",
            "artifact_paths": "paths",
        },
    ),
    "task.started": (
        frozenset({"task_id", "attempt_id", "strategy_key"}),
        {
            "task_id": "id",
            "attempt_id": "id",
            "role": "id",
            "strategy_key": "strategy",
        },
    ),
    "task.reported": (
        frozenset({"task_id", "attempt_id", "status", "artifact_paths"}),
        {
            "task_id": "id",
            "attempt_id": "id",
            "status": "status",
            "commit": "commit",
            "strategy_key": "strategy",
            "result_sha256": "hash",
            "artifact_paths": "paths",
        },
    ),
    "review.reported": (
        frozenset({"task_id", "review_id", "status", "verdict", "artifact_paths"}),
        {
            "task_id": "id",
            "review_id": "id",
            "status": "status",
            "commit": "commit",
            "verdict": "verdict",
            "result_sha256": "hash",
            "artifact_paths": "paths",
        },
    ),
    "autonomy.recorded": (
        frozenset({"decision_id", "strategy_key", "decision_sha256", "artifact_paths"}),
        {
            "decision_id": "id",
            "strategy_key": "strategy",
            "decision_sha256": "hash",
            "task_ids": "ids",
            "artifact_paths": "paths",
        },
    ),
    "authority.opened": (
        frozenset({"authority_id", "authority_code", "status", "artifact_paths"}),
        {
            "authority_id": "id",
            "authority_code": "authority",
            "status": "status",
            "task_ids": "ids",
            "artifact_paths": "paths",
        },
    ),
    "authority.resolved": (
        frozenset({"authority_id", "status", "resolution_sha256", "artifact_paths"}),
        {
            "authority_id": "id",
            "status": "status",
            "resolution_sha256": "hash",
            "artifact_paths": "paths",
        },
    ),
    "run.interrupted": (
        frozenset({"status", "failure_code"}),
        {"status": "status", "failure_code": "failure", "artifact_paths": "paths"},
    ),
    "audit.reported": (
        frozenset({"audit_id", "status", "commit", "verdict", "artifact_paths"}),
        {
            "audit_id": "id",
            "status": "status",
            "commit": "commit",
            "verdict": "verdict",
            "report_sha256": "hash",
            "artifact_paths": "paths",
        },
    ),
    "integration.reported": (
        frozenset({"integration_id", "status", "commit", "verdict", "artifact_paths"}),
        {
            "integration_id": "id",
            "status": "status",
            "commit": "commit",
            "verdict": "verdict",
            "report_sha256": "hash",
            "artifact_paths": "paths",
        },
    ),
    "run.completed": (
        frozenset({"status", "commit", "result_sha256", "artifact_paths"}),
        {
            "status": "status",
            "commit": "commit",
            "result_sha256": "hash",
            "artifact_paths": "paths",
        },
    ),
    "run.failed": (
        frozenset({"status", "failure_code"}),
        {"status": "status", "failure_code": "failure", "artifact_paths": "paths"},
    ),
}

_HEX_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_HEX_COMMIT = re.compile(r"[0-9a-f]{7,64}\Z")
_EVENT_STATUSES = RUN_STATUSES | CHILD_STATUSES | frozenset(
    {"started", "resolved", "passed", "blocked"}
)
_EVENT_STATUS_VALUES = {
    "task.reported": CHILD_STATUSES,
    "review.reported": CHILD_STATUSES,
    "authority.opened": frozenset({"waiting_authority"}),
    "authority.resolved": frozenset({"resolved", "running"}),
    "run.interrupted": frozenset({"interrupted"}),
    "audit.reported": CHILD_STATUSES | frozenset({"passed"}),
    "integration.reported": CHILD_STATUSES | frozenset({"passed"}),
    "run.completed": frozenset({"completed"}),
    "run.failed": frozenset({"failed"}),
}

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


@dataclass(frozen=True, order=True)
class DocumentRelationship:
    relationship_type: str
    target_document_id: str

    def to_json(self) -> dict[str, str]:
        return {
            "relationship_type": self.relationship_type,
            "target_document_id": self.target_document_id,
        }


@dataclass(frozen=True)
class InputDocument:
    document_id: str
    role: str
    original_path: str
    snapshot_path: str
    sha256: str
    byte_length: int
    input_order: int
    relationships: tuple[DocumentRelationship, ...] = ()

    def to_json(self) -> dict[str, object]:
        return {
            "document_id": self.document_id,
            "role": self.role,
            "original_path": self.original_path,
            "snapshot_path": self.snapshot_path,
            "sha256": self.sha256,
            "byte_length": self.byte_length,
            "input_order": self.input_order,
            "relationships": [item.to_json() for item in self.relationships],
        }


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


def _bounded_event_string(value: object, field: str, limit: int = 256) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > limit
        or any(ord(character) < 0x20 for character in value)
    ):
        raise ValueError(f"event {field} must be a bounded non-control string")
    return value


def _bounded_event_array(value: object, field: str, kind: str) -> list[str]:
    if not isinstance(value, list) or len(value) > 64:
        raise ValueError(f"event {field} must be an array with at most 64 entries")
    result: list[str] = []
    for item in value:
        if kind == "paths":
            normalized = normalize_relative_path(item) if isinstance(item, str) else ""
            if not normalized or len(normalized) > 512:
                raise ValueError(f"event {field} contains an invalid artifact path")
            parsed = normalized
        elif kind == "hashes":
            if not isinstance(item, str) or _HEX_SHA256.fullmatch(item) is None:
                raise ValueError(f"event {field} contains an invalid SHA-256")
            parsed = item
        else:
            parsed = _bounded_event_string(item, field)
        if parsed in result and kind != "hashes":
            raise ValueError(f"event {field} entries must be unique")
        result.append(parsed)
    return result


def validate_event_payload(
    event_type: str, payload: Mapping[str, object]
) -> dict[str, object]:
    """Return a bounded payload for one approved durable event type."""

    if event_type not in EVENT_TYPES:
        raise ValueError(f"unknown event type: {event_type}")
    if not isinstance(payload, Mapping):
        raise ValueError("event payload must be an object")
    required, fields = _EVENT_PAYLOAD_SCHEMAS[event_type]
    keys = frozenset(payload)
    allowed = frozenset(fields)
    if not required <= keys or not keys <= allowed:
        missing = sorted(required - keys)
        extra = sorted(keys - allowed)
        raise ValueError(
            f"event payload keys differ for {event_type}: missing={missing}, extra={extra}"
        )

    validated: dict[str, object] = {}
    for field, value in payload.items():
        kind = fields[field]
        if kind in {"ids", "hashes", "paths"}:
            validated[field] = _bounded_event_array(value, field, kind)
        elif kind == "hash":
            if not isinstance(value, str) or _HEX_SHA256.fullmatch(value) is None:
                raise ValueError(f"event {field} must be a lowercase SHA-256")
            validated[field] = value
        elif kind == "commit":
            if value is not None and (
                not isinstance(value, str) or _HEX_COMMIT.fullmatch(value) is None
            ):
                raise ValueError(f"event {field} must be null or a Git commit hash")
            validated[field] = value
        elif kind == "status":
            parsed = _bounded_event_string(value, field, 64)
            if parsed not in _EVENT_STATUSES:
                raise ValueError(f"event {field} is not an approved status")
            allowed_statuses = _EVENT_STATUS_VALUES.get(event_type)
            if allowed_statuses is not None and parsed not in allowed_statuses:
                raise ValueError(f"event {field} is invalid for {event_type}")
            validated[field] = parsed
        elif kind == "verdict":
            if value is not None and not isinstance(value, str):
                raise ValueError(f"event {field} must be null or a string")
            if value not in VERDICTS:
                raise ValueError(f"event {field} is not an approved verdict")
            validated[field] = value
        elif kind == "authority":
            parsed = _bounded_event_string(value, field, 128)
            if parsed not in AUTHORITY_CODES:
                raise ValueError(f"event {field} is not an approved authority code")
            validated[field] = parsed
        else:
            validated[field] = _bounded_event_string(
                value, field, 512 if kind in {"strategy", "failure"} else 256
            )
    if len(canonical_json(validated)) > 16 * 1024:
        raise ValueError("event payload exceeds 16 KiB")
    return validated


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
