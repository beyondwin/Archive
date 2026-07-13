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
MAP_SCHEMA_VERSION = 1
REQUIREMENT_DISPOSITIONS = frozenset(
    {
        "planned",
        "preexisting_verify",
        "explicit_non_goal",
        "approved_deferred",
        "conflict",
        "unmapped",
    }
)
REQUIREMENT_KINDS = frozenset(
    {
        "normative",
        "goal",
        "non_goal",
        "decision",
        "constraint",
        "amendment",
        "supersession",
    }
)
_DECISION_KINDS_BY_ROLE = {
    "spec": frozenset(
        {"goal", "non_goal", "approved", "amendment", "supersession", "unresolved"}
    ),
    "plan": frozenset(
        {"checkpoint", "authority_decision", "external_effect", "ordering", "approved"}
    ),
    "program_plan": frozenset(
        {
            "plan_order",
            "wave_order",
            "ownership",
            "integration_gate",
            "supersession",
            "authority_rule",
            "approved",
        }
    ),
}
_CONSTRAINT_KINDS_BY_ROLE = {
    "spec": frozenset({"global", "scoped", "interface", "file"}),
    "plan": frozenset({"global", "task", "file", "interface", "acceptance"}),
    "program_plan": frozenset({"global", "plan", "wave", "ownership", "integration"}),
}
_GRAPH_EDGE_KINDS = frozenset(
    {"task_dependency", "plan_order", "wave_order", "cross_plan_dependency"}
)
_HOTSPOT_KINDS = frozenset({"shared_file", "interface"})

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
_MAPPED_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}(?::[A-Za-z0-9][A-Za-z0-9._-]{0,127})?\Z")
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


def _map_object(
    payload: object, *, fields: frozenset[str], name: str
) -> dict[str, object]:
    if not isinstance(payload, Mapping) or frozenset(payload) != fields:
        raise ValueError(f"{name} must have exactly these fields: {sorted(fields)}")
    return dict(payload)


def _map_id(value: object, name: str) -> str:
    if not isinstance(value, str) or _MAPPED_ID.fullmatch(value) is None:
        raise ValueError(f"{name} must be a bounded global ID")
    return value


def _map_hash(value: object, name: str) -> str:
    if not isinstance(value, str) or _HEX_SHA256.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256")
    return value


def _map_text(value: object, name: str, limit: int = 16_384) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > limit
        or "\x00" in value
    ):
        raise ValueError(f"{name} must be bounded non-empty text")
    return value


def _map_string_list(
    value: object, name: str, *, allow_empty: bool = True, limit: int = 256
) -> list[str]:
    if not isinstance(value, list) or (not allow_empty and not value) or len(value) > limit:
        raise ValueError(f"{name} must be a bounded array")
    result: list[str] = []
    for item in value:
        parsed = _map_text(item, f"{name} entry", 4096)
        if parsed in result:
            raise ValueError(f"{name} entries must be unique")
        result.append(parsed)
    return result


_SOURCE_REFERENCE_FIELDS = frozenset(
    {
        "document_id",
        "heading",
        "line_start",
        "line_end",
        "source_sha256",
        "exact_excerpt",
    }
)


def _validate_source_reference(
    payload: object,
    *,
    document_hashes: Mapping[str, str] | None = None,
    name: str = "source reference",
) -> dict[str, object]:
    value = _map_object(payload, fields=_SOURCE_REFERENCE_FIELDS, name=name)
    document_id = _map_id(value["document_id"], f"{name} document_id")
    heading = _map_text(value["heading"], f"{name} heading", 1024)
    line_start = value["line_start"]
    line_end = value["line_end"]
    if (
        not isinstance(line_start, int)
        or isinstance(line_start, bool)
        or not isinstance(line_end, int)
        or isinstance(line_end, bool)
        or line_start < 1
        or line_end < line_start
    ):
        raise ValueError(f"{name} line range is invalid")
    source_sha256 = _map_hash(value["source_sha256"], f"{name} source SHA")
    if document_hashes is not None:
        if document_id not in document_hashes:
            raise ValueError(f"{name} names an unknown document")
        if source_sha256 != document_hashes[document_id]:
            raise ValueError(f"{name} source SHA does not match the immutable document")
    exact_excerpt = _map_text(value["exact_excerpt"], f"{name} exact_excerpt", 256_000)
    return {
        "document_id": document_id,
        "heading": heading,
        "line_start": line_start,
        "line_end": line_end,
        "source_sha256": source_sha256,
        "exact_excerpt": exact_excerpt,
    }


def _validate_source_references(
    value: object,
    *,
    document_hashes: Mapping[str, str] | None = None,
    name: str,
    allow_empty: bool = False,
) -> list[dict[str, object]]:
    if not isinstance(value, list) or (not allow_empty and not value) or len(value) > 256:
        raise ValueError(f"{name} must be a bounded array")
    result = [
        _validate_source_reference(
            item, document_hashes=document_hashes, name=f"{name} entry"
        )
        for item in value
    ]
    encoded = [canonical_json(item) for item in result]
    if len(set(encoded)) != len(encoded):
        raise ValueError(f"{name} entries must be unique")
    return result


def _validate_authority_ids(value: object, name: str) -> list[str]:
    return [
        _map_id(item, f"{name} authority_id")
        for item in _map_string_list(value, f"{name} authority_ids")
    ]


def _validate_binding(
    payload: Mapping[str, object],
    *,
    document_hashes: Mapping[str, str],
    text_field: str,
    name: str,
) -> dict[str, object]:
    value = _map_object(
        payload,
        fields=frozenset({text_field, "source_references", "authority_ids"}),
        name=name,
    )
    references = _validate_source_references(
        value["source_references"],
        document_hashes=document_hashes,
        name=f"{name} source_references",
        allow_empty=True,
    )
    authority_ids = _validate_authority_ids(value["authority_ids"], name)
    if not references and not authority_ids:
        raise ValueError(f"{name} must bind to immutable source or recorded authority")
    return {
        text_field: _map_text(value[text_field], f"{name} {text_field}", 4096),
        "source_references": references,
        "authority_ids": authority_ids,
    }


def _validate_bindings(
    value: object,
    *,
    document_hashes: Mapping[str, str],
    text_field: str,
    name: str,
    allow_empty: bool = True,
) -> list[dict[str, object]]:
    if not isinstance(value, list) or (not allow_empty and not value) or len(value) > 4096:
        raise ValueError(f"{name} must be a bounded array")
    result = [
        _validate_binding(
            item,
            document_hashes=document_hashes,
            text_field=text_field,
            name=f"{name} entry",
        )
        for item in value
    ]
    encoded = [canonical_json(item) for item in result]
    if len(encoded) != len(set(encoded)):
        raise ValueError(f"{name} entries must be unique")
    return result


def _validate_dependency_edges(
    value: object,
    *,
    document_hashes: Mapping[str, str],
    name: str,
) -> list[dict[str, object]]:
    if not isinstance(value, list) or len(value) > 4096:
        raise ValueError(f"{name} must be a bounded array")
    result: list[dict[str, object]] = []
    task_ids: set[str] = set()
    for raw_edge in value:
        edge = _map_object(
            raw_edge,
            fields=frozenset({"task_id", "source_references", "authority_ids"}),
            name=f"{name} entry",
        )
        task_id = _map_id(edge["task_id"], f"{name} task_id")
        if task_id in task_ids:
            raise ValueError(f"{name} task IDs must be unique")
        task_ids.add(task_id)
        references = _validate_source_references(
            edge["source_references"],
            document_hashes=document_hashes,
            name=f"{name} source_references",
            allow_empty=True,
        )
        authority_ids = _validate_authority_ids(edge["authority_ids"], name)
        if not references and not authority_ids:
            raise ValueError(f"{name} must bind to immutable source or recorded authority")
        result.append(
            {
                "task_id": task_id,
                "source_references": references,
                "authority_ids": authority_ids,
            }
        )
    return result


def _validate_graph_edges(
    value: object,
    *,
    document_hashes: Mapping[str, str],
    name: str,
) -> list[dict[str, object]]:
    if not isinstance(value, list) or len(value) > 4096:
        raise ValueError(f"{name} must be a bounded array")
    result: list[dict[str, object]] = []
    for raw_edge in value:
        edge = _map_object(
            raw_edge,
            fields=frozenset(
                {
                    "predecessor_id",
                    "successor_id",
                    "kind",
                    "source_references",
                    "authority_ids",
                }
            ),
            name=f"{name} entry",
        )
        kind = edge["kind"]
        if kind not in _GRAPH_EDGE_KINDS:
            raise ValueError(f"{name} has an unknown edge kind")
        references = _validate_source_references(
            edge["source_references"],
            document_hashes=document_hashes,
            name=f"{name} source_references",
            allow_empty=True,
        )
        authority_ids = _validate_authority_ids(edge["authority_ids"], name)
        if not references and not authority_ids:
            raise ValueError(f"{name} must bind to immutable source or recorded authority")
        result.append(
            {
                "predecessor_id": _map_id(
                    edge["predecessor_id"], f"{name} predecessor_id"
                ),
                "successor_id": _map_id(
                    edge["successor_id"], f"{name} successor_id"
                ),
                "kind": kind,
                "source_references": references,
                "authority_ids": authority_ids,
            }
        )
    encoded = [canonical_json(item) for item in result]
    if len(encoded) != len(set(encoded)):
        raise ValueError(f"{name} entries must be unique")
    return result


def _validate_plan_wave_graph(
    payload: object,
    *,
    document_hashes: Mapping[str, str],
    name: str,
) -> dict[str, object]:
    value = _map_object(
        payload,
        fields=frozenset({"plans", "waves", "edges"}),
        name=name,
    )
    node_fields = frozenset(
        {"node_id", "member_ids", "source_references", "authority_ids"}
    )

    def nodes(raw: object, node_name: str) -> list[dict[str, object]]:
        if not isinstance(raw, list) or len(raw) > 4096:
            raise ValueError(f"{node_name} must be a bounded array")
        result: list[dict[str, object]] = []
        node_ids: set[str] = set()
        for raw_node in raw:
            node = _map_object(raw_node, fields=node_fields, name=f"{node_name} entry")
            node_id = _map_id(node["node_id"], f"{node_name} node_id")
            if node_id in node_ids:
                raise ValueError(f"{node_name} node IDs must be unique")
            node_ids.add(node_id)
            references = _validate_source_references(
                node["source_references"],
                document_hashes=document_hashes,
                name=f"{node_name} source_references",
                allow_empty=True,
            )
            authority_ids = _validate_authority_ids(node["authority_ids"], node_name)
            if not references and not authority_ids:
                raise ValueError(
                    f"{node_name} must bind to immutable source or recorded authority"
                )
            result.append(
                {
                    "node_id": node_id,
                    "member_ids": [
                        _map_id(item, f"{node_name} member_id")
                        for item in _map_string_list(
                            node["member_ids"], f"{node_name} member_ids", allow_empty=False
                        )
                    ],
                    "source_references": references,
                    "authority_ids": authority_ids,
                }
            )
        return result

    return {
        "plans": nodes(value["plans"], f"{name} plans"),
        "waves": nodes(value["waves"], f"{name} waves"),
        "edges": _validate_graph_edges(
            value["edges"], document_hashes=document_hashes, name=f"{name} edges"
        ),
    }


def _validate_hotspots(
    value: object,
    *,
    document_hashes: Mapping[str, str],
    name: str,
) -> list[dict[str, object]]:
    if not isinstance(value, list) or len(value) > 4096:
        raise ValueError(f"{name} must be a bounded array")
    fields = frozenset(
        {
            "hotspot_id",
            "kind",
            "location",
            "task_ids",
            "source_references",
            "authority_ids",
        }
    )
    result: list[dict[str, object]] = []
    ids: set[str] = set()
    for raw_item in value:
        item = _map_object(raw_item, fields=fields, name=f"{name} entry")
        hotspot_id = _map_id(item["hotspot_id"], f"{name} hotspot_id")
        if hotspot_id in ids:
            raise ValueError(f"{name} IDs must be unique")
        ids.add(hotspot_id)
        kind = item["kind"]
        if kind not in _HOTSPOT_KINDS:
            raise ValueError(f"{name} has an unknown kind")
        references = _validate_source_references(
            item["source_references"],
            document_hashes=document_hashes,
            name=f"{name} source_references",
            allow_empty=True,
        )
        authority_ids = _validate_authority_ids(item["authority_ids"], name)
        if not references and not authority_ids:
            raise ValueError(f"{name} must bind to immutable source or recorded authority")
        result.append(
            {
                "hotspot_id": hotspot_id,
                "kind": kind,
                "location": _map_text(item["location"], f"{name} location", 4096),
                "task_ids": [
                    _map_id(task_id, f"{name} task_id")
                    for task_id in _map_string_list(item["task_ids"], f"{name} task_ids")
                ],
                "source_references": references,
                "authority_ids": authority_ids,
            }
        )
    return result


def _validate_role_records(
    value: object,
    *,
    document_hashes: Mapping[str, str],
    name: str,
    id_field: str,
    roles: Mapping[str, frozenset[str]],
    include_affected_ids: bool,
    expected_role: str | None = None,
) -> list[dict[str, object]]:
    if not isinstance(value, list) or len(value) > 4096:
        raise ValueError(f"{name} must be a bounded array")
    fields = {id_field, "role", "kind", "statement", "source_references", "authority_ids"}
    if include_affected_ids:
        fields.add("affected_ids")
    result: list[dict[str, object]] = []
    ids: set[str] = set()
    for raw_item in value:
        item = _map_object(raw_item, fields=frozenset(fields), name=f"{name} entry")
        record_id = _map_id(item[id_field], f"{name} {id_field}")
        if record_id in ids:
            raise ValueError(f"{name} IDs must be unique")
        ids.add(record_id)
        role = item["role"]
        kind = item["kind"]
        if expected_role is not None and role != expected_role:
            raise ValueError(f"{name} must match its document role")
        if role not in roles or kind not in roles[role]:
            raise ValueError(f"{name} kind is invalid for its document role")
        parsed = _validate_binding(
            {
                "statement": item["statement"],
                "source_references": item["source_references"],
                "authority_ids": item["authority_ids"],
            },
            document_hashes=document_hashes,
            text_field="statement",
            name=f"{name} entry",
        )
        record = {id_field: record_id, "role": role, "kind": kind, **parsed}
        if include_affected_ids:
            record["affected_ids"] = [
                _map_id(identifier, f"{name} affected_id")
                for identifier in _map_string_list(
                    item["affected_ids"], f"{name} affected_ids"
                )
            ]
        result.append(record)
    return result


def _referenced_authority_ids(value: object) -> set[str]:
    result: set[str] = set()
    if isinstance(value, Mapping):
        for key, child in value.items():
            if key == "authority_ids" and isinstance(child, list):
                result.update(str(item) for item in child)
            else:
                result.update(_referenced_authority_ids(child))
    elif isinstance(value, list):
        for child in value:
            result.update(_referenced_authority_ids(child))
    return result


def _validate_program_authority_items(
    value: object, *, document_hashes: Mapping[str, str], task_ids: set[str]
) -> list[dict[str, object]]:
    if not isinstance(value, list) or len(value) > 256:
        raise ValueError("program authority_items must be a bounded array")
    fields = frozenset(
        {
            "authority_id",
            "authority_code",
            "affected_task_ids",
            "question",
            "options",
            "recommended",
            "source_references",
        }
    )
    result: list[dict[str, object]] = []
    authority_ids: set[str] = set()
    for raw_item in value:
        item = _map_object(raw_item, fields=fields, name="program authority item")
        authority_id = _map_id(item["authority_id"], "authority_id")
        if authority_id in authority_ids:
            raise ValueError("program authority item IDs must be unique")
        authority_ids.add(authority_id)
        authority_code = item["authority_code"]
        if authority_code not in AUTHORITY_CODES:
            raise ValueError("program authority item has an unknown authority code")
        affected_task_ids = [
            _map_id(task_id, "authority affected task_id")
            for task_id in _map_string_list(
                item["affected_task_ids"],
                "authority affected_task_ids",
                allow_empty=False,
            )
        ]
        if not set(affected_task_ids) <= task_ids:
            raise ValueError("program authority item names an unknown task")
        options = _map_string_list(
            item["options"], "authority options", allow_empty=False
        )
        if len(options) < 2:
            raise ValueError("program authority item needs at least two options")
        recommended = _map_text(item["recommended"], "authority recommended", 1024)
        if recommended not in options:
            raise ValueError("program authority recommendation must be one option")
        references = _validate_source_references(
            item["source_references"],
            document_hashes=document_hashes,
            name="authority source_references",
        )
        result.append(
            {
                "authority_id": authority_id,
                "authority_code": authority_code,
                "affected_task_ids": affected_task_ids,
                "question": _map_text(item["question"], "authority question", 4096),
                "options": options,
                "recommended": recommended,
                "source_references": references,
            }
        )
    return result


def _validate_document_authority_items(
    value: object, *, document_id: str, source_sha256: str
) -> list[dict[str, object]]:
    if not isinstance(value, list) or len(value) > 256:
        raise ValueError("document authority_items must be a bounded array")
    fields = frozenset(
        {"authority_id", "authority_code", "question", "source_references"}
    )
    result: list[dict[str, object]] = []
    authority_ids: set[str] = set()
    for raw_item in value:
        item = _map_object(raw_item, fields=fields, name="document authority item")
        authority_id = _map_id(item["authority_id"], "document authority_id")
        if authority_id in authority_ids:
            raise ValueError("document authority item IDs must be unique")
        authority_ids.add(authority_id)
        authority_code = item["authority_code"]
        if authority_code not in AUTHORITY_CODES:
            raise ValueError("document authority item has an unknown authority code")
        result.append(
            {
                "authority_id": authority_id,
                "authority_code": authority_code,
                "question": _map_text(
                    item["question"], "document authority question", 4096
                ),
                "source_references": _validate_source_references(
                    item["source_references"],
                    document_hashes={document_id: source_sha256},
                    name="document authority source_references",
                ),
            }
        )
    return result


def validate_document_map(
    payload: object, *, document: InputDocument
) -> dict[str, object]:
    """Validate one mapper's structural, digest-bound navigation artifact."""

    fields = frozenset(
        {
            "schema_version",
            "document_id",
            "role",
            "source_sha256",
            "requirements",
            "task_candidates",
            "dependencies",
            "authority_items",
            "verification_commands",
            "plan_wave_graph",
            "hotspots",
            "decisions",
            "constraints",
        }
    )
    value = _map_object(payload, fields=fields, name="document map")
    if value["schema_version"] != MAP_SCHEMA_VERSION:
        raise ValueError("document map schema_version must be 1")
    if value["document_id"] != document.document_id:
        raise ValueError("document map document_id does not match its input")
    if value["role"] != document.role:
        raise ValueError("document map role does not match its input")
    if _map_hash(value["source_sha256"], "document map source SHA") != document.sha256:
        raise ValueError("document map source SHA does not match its immutable input")
    document_hashes = {document.document_id: document.sha256}
    authority_items = _validate_document_authority_items(
        value["authority_items"],
        document_id=document.document_id,
        source_sha256=document.sha256,
    )
    document_authority_ids = {
        str(item["authority_id"]) for item in authority_items
    }

    requirement_fields = frozenset(
        {
            "requirement_id",
            "kind",
            "heading",
            "line_start",
            "line_end",
            "exact_excerpt",
            "constraints",
        }
    )
    requirements_value = value["requirements"]
    if not isinstance(requirements_value, list) or len(requirements_value) > 4096:
        raise ValueError("document map requirements must be a bounded array")
    requirements: list[dict[str, object]] = []
    requirement_ids: set[str] = set()
    for raw_requirement in requirements_value:
        requirement = _map_object(
            raw_requirement, fields=requirement_fields, name="mapped requirement"
        )
        requirement_id = _map_id(requirement["requirement_id"], "requirement_id")
        if not requirement_id.startswith(f"{document.document_id}:R"):
            raise ValueError("requirement_id must be globally scoped to its document")
        if requirement_id in requirement_ids:
            raise ValueError("requirement IDs must be unique")
        requirement_ids.add(requirement_id)
        kind = _map_text(requirement["kind"], "requirement kind", 64)
        if kind not in REQUIREMENT_KINDS:
            raise ValueError("requirement kind is not approved by the mapping schema")
        heading = _map_text(requirement["heading"], "requirement heading", 1024)
        line_start = requirement["line_start"]
        line_end = requirement["line_end"]
        if (
            not isinstance(line_start, int)
            or isinstance(line_start, bool)
            or not isinstance(line_end, int)
            or isinstance(line_end, bool)
            or line_start < 1
            or line_end < line_start
        ):
            raise ValueError("mapped requirement line range is invalid")
        requirements.append(
            {
                "requirement_id": requirement_id,
                "kind": kind,
                "heading": heading,
                "line_start": line_start,
                "line_end": line_end,
                "exact_excerpt": _map_text(
                    requirement["exact_excerpt"], "requirement exact_excerpt", 256_000
                ),
                "constraints": _validate_bindings(
                    requirement["constraints"],
                    document_hashes=document_hashes,
                    text_field="statement",
                    name="requirement constraints",
                ),
            }
        )

    candidate_fields = frozenset(
        {
            "task_id",
            "title",
            "heading",
            "line_start",
            "line_end",
            "exact_excerpt",
            "requirement_ids",
            "dependencies",
            "dependency_edges",
            "acceptance",
            "global_constraints",
            "upstream_interface_commitments",
        }
    )
    candidates_value = value["task_candidates"]
    if not isinstance(candidates_value, list) or len(candidates_value) > 4096:
        raise ValueError("document map task_candidates must be a bounded array")
    candidates: list[dict[str, object]] = []
    candidate_ids: set[str] = set()
    for raw_candidate in candidates_value:
        candidate = _map_object(
            raw_candidate, fields=candidate_fields, name="task candidate"
        )
        task_id = _map_id(candidate["task_id"], "task candidate task_id")
        if document.role == "plan" and not task_id.startswith(f"{document.document_id}:T"):
            raise ValueError("task candidate ID must be globally scoped to its plan")
        if task_id in candidate_ids:
            raise ValueError("task candidate IDs must be unique")
        candidate_ids.add(task_id)
        line_start = candidate["line_start"]
        line_end = candidate["line_end"]
        if (
            not isinstance(line_start, int)
            or isinstance(line_start, bool)
            or not isinstance(line_end, int)
            or isinstance(line_end, bool)
            or line_start < 1
            or line_end < line_start
        ):
            raise ValueError("task candidate line range is invalid")
        dependencies = [
            _map_id(item, "task candidate dependency")
            for item in _map_string_list(
                candidate["dependencies"], "task candidate dependencies"
            )
        ]
        dependency_edges = _validate_dependency_edges(
            candidate["dependency_edges"],
            document_hashes=document_hashes,
            name="task candidate dependency_edges",
        )
        if dependencies != [str(edge["task_id"]) for edge in dependency_edges]:
            raise ValueError("task candidate dependency edges differ from dependencies")
        candidates.append(
            {
                "task_id": task_id,
                "title": _map_text(candidate["title"], "task candidate title", 1024),
                "heading": _map_text(candidate["heading"], "task candidate heading", 1024),
                "line_start": line_start,
                "line_end": line_end,
                "exact_excerpt": _map_text(
                    candidate["exact_excerpt"], "task candidate exact_excerpt", 256_000
                ),
                "requirement_ids": [
                    _map_id(item, "task candidate requirement_id")
                    for item in _map_string_list(
                        candidate["requirement_ids"], "task candidate requirement_ids"
                    )
                ],
                "dependencies": dependencies,
                "dependency_edges": dependency_edges,
                "acceptance": _validate_bindings(
                    candidate["acceptance"],
                    document_hashes=document_hashes,
                    text_field="command",
                    name="task candidate acceptance",
                ),
                "global_constraints": _validate_bindings(
                    candidate["global_constraints"],
                    document_hashes=document_hashes,
                    text_field="statement",
                    name="task candidate global_constraints",
                ),
                "upstream_interface_commitments": _validate_bindings(
                    candidate["upstream_interface_commitments"],
                    document_hashes=document_hashes,
                    text_field="statement",
                    name="task candidate upstream interface commitments",
                ),
            }
        )

    dependencies = _validate_graph_edges(
        value["dependencies"],
        document_hashes=document_hashes,
        name="document dependencies",
    )
    verification_commands = _map_string_list(
        value["verification_commands"], "document verification_commands"
    )
    plan_wave_graph = _validate_plan_wave_graph(
        value["plan_wave_graph"],
        document_hashes=document_hashes,
        name="document plan_wave_graph",
    )
    hotspots = _validate_hotspots(
        value["hotspots"], document_hashes=document_hashes, name="document hotspots"
    )
    decisions = _validate_role_records(
        value["decisions"],
        document_hashes=document_hashes,
        name="document decisions",
        id_field="decision_id",
        roles=_DECISION_KINDS_BY_ROLE,
        include_affected_ids=False,
        expected_role=document.role,
    )
    constraints = _validate_role_records(
        value["constraints"],
        document_hashes=document_hashes,
        name="document constraints",
        id_field="constraint_id",
        roles=_CONSTRAINT_KINDS_BY_ROLE,
        include_affected_ids=True,
        expected_role=document.role,
    )
    bound_authority_ids = _referenced_authority_ids(
        {
            "requirements": requirements,
            "task_candidates": candidates,
            "dependencies": dependencies,
            "plan_wave_graph": plan_wave_graph,
            "hotspots": hotspots,
            "decisions": decisions,
            "constraints": constraints,
        }
    )
    if not bound_authority_ids <= document_authority_ids:
        raise ValueError("document map binding names an unknown authority item")
    return {
        "schema_version": MAP_SCHEMA_VERSION,
        "document_id": document.document_id,
        "role": document.role,
        "source_sha256": document.sha256,
        "requirements": requirements,
        "task_candidates": candidates,
        "dependencies": dependencies,
        "authority_items": authority_items,
        "verification_commands": verification_commands,
        "plan_wave_graph": plan_wave_graph,
        "hotspots": hotspots,
        "decisions": decisions,
        "constraints": constraints,
    }


def validate_program_map(
    payload: object, *, document_hashes: Mapping[str, str]
) -> dict[str, object]:
    """Validate a global task graph and honest requirement dispositions."""

    required_fields = frozenset(
        {
            "schema_version",
            "generation",
            "document_map_sha256s",
            "tasks",
            "coverage",
            "final_verification_commands",
            "authority_items",
            "plan_wave_graph",
            "hotspots",
            "decisions",
            "constraints",
        }
    )
    if not isinstance(payload, Mapping):
        raise ValueError("program map must be an object")
    keys = frozenset(payload)
    if keys not in {required_fields, required_fields | {"task_splits"}}:
        raise ValueError("program map fields are invalid")
    value = dict(payload)
    if value["schema_version"] != MAP_SCHEMA_VERSION or value["generation"] != 1:
        raise ValueError("program map must be schema 1 generation 1")
    if not isinstance(document_hashes, Mapping) or not document_hashes:
        raise ValueError("document_hashes must be a non-empty mapping")
    normalized_document_hashes = {
        _map_id(document_id, "program document ID"): _map_hash(
            digest, "program document SHA"
        )
        for document_id, digest in document_hashes.items()
    }
    document_ids = set(normalized_document_hashes)
    hashes = value["document_map_sha256s"]
    if not isinstance(hashes, Mapping) or set(hashes) != document_ids:
        raise ValueError("program map document-map IDs are incomplete or unknown")
    document_map_sha256s = {
        _map_id(document_id, "document map ID"): _map_hash(digest, "document map SHA")
        for document_id, digest in hashes.items()
    }

    task_fields = frozenset(
        {
            "task_id",
            "title",
            "dependencies",
            "dependency_edges",
            "document_ids",
            "requirement_ids",
            "acceptance",
            "global_constraints",
            "upstream_interface_commitments",
            "brief_path",
        }
    )
    tasks_value = value["tasks"]
    if not isinstance(tasks_value, list) or not tasks_value or len(tasks_value) > 4096:
        raise ValueError("program map tasks must be a bounded non-empty array")
    tasks: list[dict[str, object]] = []
    task_ids: set[str] = set()
    brief_paths: set[str] = set()
    for raw_task in tasks_value:
        task = _map_object(raw_task, fields=task_fields, name="program task")
        task_id = _map_id(task["task_id"], "program task_id")
        if task_id in task_ids:
            raise ValueError("program task IDs must be unique")
        task_ids.add(task_id)
        dependencies = [
            _map_id(item, "task dependency")
            for item in _map_string_list(task["dependencies"], "task dependencies")
        ]
        dependency_edges = _validate_dependency_edges(
            task["dependency_edges"],
            document_hashes=normalized_document_hashes,
            name="program task dependency_edges",
        )
        if dependencies != [str(edge["task_id"]) for edge in dependency_edges]:
            raise ValueError("program task dependency edges differ from dependencies")
        task_document_ids = [
            _map_id(item, "task document_id")
            for item in _map_string_list(
                task["document_ids"], "task document_ids", allow_empty=False
            )
        ]
        if not set(task_document_ids) <= document_ids:
            raise ValueError("program task names an unknown document")
        requirement_ids = [
            _map_id(item, "task requirement_id")
            for item in _map_string_list(task["requirement_ids"], "task requirement_ids")
        ]
        brief_path = normalize_relative_path(
            _map_text(task["brief_path"], "task brief_path", 512)
        )
        if not brief_path.startswith("briefs/") or not brief_path.endswith(".json"):
            raise ValueError("task brief_path must be a JSON artifact below briefs")
        if brief_path in brief_paths:
            raise ValueError("task brief paths must be unique")
        brief_paths.add(brief_path)
        tasks.append(
            {
                "task_id": task_id,
                "title": _map_text(task["title"], "program task title", 1024),
                "dependencies": dependencies,
                "dependency_edges": dependency_edges,
                "document_ids": task_document_ids,
                "requirement_ids": requirement_ids,
                "acceptance": _validate_bindings(
                    task["acceptance"],
                    document_hashes=normalized_document_hashes,
                    text_field="command",
                    name="program task acceptance",
                ),
                "global_constraints": _validate_bindings(
                    task["global_constraints"],
                    document_hashes=normalized_document_hashes,
                    text_field="statement",
                    name="program task global_constraints",
                ),
                "upstream_interface_commitments": _validate_bindings(
                    task["upstream_interface_commitments"],
                    document_hashes=normalized_document_hashes,
                    text_field="statement",
                    name="program task upstream interface commitments",
                ),
                "brief_path": brief_path,
            }
        )

    by_id = {str(task["task_id"]): task for task in tasks}
    for task in tasks:
        unknown = set(task["dependencies"]) - task_ids
        if unknown:
            raise ValueError(f"task has unknown dependency: {sorted(unknown)}")
        if task["task_id"] in task["dependencies"]:
            raise ValueError("task dependency graph contains a cycle")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(task_id: str) -> None:
        if task_id in visiting:
            raise ValueError("task dependency graph contains a cycle")
        if task_id in visited:
            return
        visiting.add(task_id)
        for dependency in by_id[task_id]["dependencies"]:
            visit(str(dependency))
        visiting.remove(task_id)
        visited.add(task_id)

    for task in tasks:
        visit(str(task["task_id"]))
    seen: set[str] = set()
    for task in tasks:
        if not set(task["dependencies"]) <= seen:
            raise ValueError("program tasks are not in topological order")
        seen.add(str(task["task_id"]))

    coverage_value = value["coverage"]
    if not isinstance(coverage_value, Mapping) or len(coverage_value) > 16_384:
        raise ValueError("program coverage must be an object")
    coverage: dict[str, dict[str, object]] = {}
    task_edges: dict[str, set[str]] = {task_id: set() for task_id in task_ids}
    for raw_requirement_id, raw_record in coverage_value.items():
        requirement_id = _map_id(raw_requirement_id, "coverage requirement_id")
        record = _map_object(
            raw_record,
            fields=frozenset(
                {
                    "disposition",
                    "task_ids",
                    "reason",
                    "source_references",
                    "authority_ids",
                }
            ),
            name="coverage record",
        )
        disposition = record["disposition"]
        if disposition not in REQUIREMENT_DISPOSITIONS:
            raise ValueError("coverage disposition is not approved by the design")
        coverage_task_ids = [
            _map_id(item, "coverage task_id")
            for item in _map_string_list(record["task_ids"], "coverage task_ids")
        ]
        if not set(coverage_task_ids) <= task_ids:
            raise ValueError("coverage names an unknown task")
        reason = record["reason"]
        source_references = _validate_source_references(
            record["source_references"],
            document_hashes=normalized_document_hashes,
            name="coverage source_references",
            allow_empty=True,
        )
        authority_ids = _validate_authority_ids(record["authority_ids"], "coverage")
        if not source_references and not authority_ids:
            raise ValueError("coverage disposition must bind to source or authority")
        if disposition == "planned":
            if not coverage_task_ids or reason is not None:
                raise ValueError("planned coverage needs tasks and a null reason")
        else:
            if coverage_task_ids or not isinstance(reason, str) or not reason.strip():
                raise ValueError("non-planned coverage needs no tasks and a recorded reason")
        if disposition == "approved_deferred" and not authority_ids:
            raise ValueError("approved_deferred coverage needs recorded authority")
        for task_id in coverage_task_ids:
            task_edges[task_id].add(requirement_id)
        coverage[requirement_id] = {
            "disposition": disposition,
            "task_ids": coverage_task_ids,
            "reason": reason,
            "source_references": source_references,
            "authority_ids": authority_ids,
        }
    for task in tasks:
        if set(task["requirement_ids"]) != task_edges[str(task["task_id"])]:
            raise ValueError("task requirement IDs differ from planned coverage edges")

    split_fields = frozenset(
        {"source_task_id", "split_task_ids", "source_references", "reason"}
    )
    split_values = value.get("task_splits", [])
    if not isinstance(split_values, list) or len(split_values) > 1024:
        raise ValueError("task_splits must be a bounded array")
    task_splits: list[dict[str, object]] = []
    split_sources: set[str] = set()
    split_targets: set[str] = set()
    for raw_split in split_values:
        split = _map_object(raw_split, fields=split_fields, name="task split")
        source_task_id = _map_id(split["source_task_id"], "split source_task_id")
        split_task_ids = [
            _map_id(item, "split task_id")
            for item in _map_string_list(
                split["split_task_ids"], "split task_ids", allow_empty=False
            )
        ]
        if source_task_id in task_ids or source_task_id in split_sources:
            raise ValueError("split source task must be one replaced unique task")
        if len(split_task_ids) < 2 or not set(split_task_ids) <= task_ids:
            raise ValueError("task split must name at least two resulting tasks")
        if split_targets & set(split_task_ids):
            raise ValueError("split task targets must not overlap")
        references = _validate_source_references(
            split["source_references"],
            document_hashes=normalized_document_hashes,
            name="task split source_references",
        )
        split_sources.add(source_task_id)
        split_targets.update(split_task_ids)
        task_splits.append(
            {
                "source_task_id": source_task_id,
                "split_task_ids": split_task_ids,
                "source_references": references,
                "reason": _map_text(split["reason"], "task split reason", 4096),
            }
        )

    authority_items = _validate_program_authority_items(
        value["authority_items"],
        document_hashes=normalized_document_hashes,
        task_ids=task_ids,
    )
    plan_wave_graph = _validate_plan_wave_graph(
        value["plan_wave_graph"],
        document_hashes=normalized_document_hashes,
        name="program plan_wave_graph",
    )
    hotspots = _validate_hotspots(
        value["hotspots"],
        document_hashes=normalized_document_hashes,
        name="program hotspots",
    )
    decisions = _validate_role_records(
        value["decisions"],
        document_hashes=normalized_document_hashes,
        name="program decisions",
        id_field="decision_id",
        roles=_DECISION_KINDS_BY_ROLE,
        include_affected_ids=False,
    )
    constraints = _validate_role_records(
        value["constraints"],
        document_hashes=normalized_document_hashes,
        name="program constraints",
        id_field="constraint_id",
        roles=_CONSTRAINT_KINDS_BY_ROLE,
        include_affected_ids=True,
    )
    known_authority_ids = {
        str(item["authority_id"]) for item in authority_items
    }
    referenced_authority_ids = _referenced_authority_ids(
        {
            "tasks": tasks,
            "coverage": coverage,
            "task_splits": task_splits,
            "plan_wave_graph": plan_wave_graph,
            "hotspots": hotspots,
            "decisions": decisions,
            "constraints": constraints,
        }
    )
    if not referenced_authority_ids <= known_authority_ids:
        raise ValueError("program map binding names an unknown authority item")
    return {
        "schema_version": MAP_SCHEMA_VERSION,
        "generation": 1,
        "document_map_sha256s": document_map_sha256s,
        "tasks": tasks,
        "coverage": coverage,
        "task_splits": task_splits,
        "plan_wave_graph": plan_wave_graph,
        "hotspots": hotspots,
        "decisions": decisions,
        "constraints": constraints,
        "final_verification_commands": _map_string_list(
            value["final_verification_commands"],
            "final verification commands",
            allow_empty=False,
        ),
        "authority_items": authority_items,
    }


def validate_task_brief(
    payload: object,
    *,
    program_map_sha256: str,
    document_hashes: Mapping[str, str],
) -> dict[str, object]:
    """Validate one immutable, lossless, source- and program-bound task brief."""

    fields = frozenset(
        {
            "schema_version",
            "task_id",
            "program_map_sha256",
            "title",
            "dependencies",
            "dependency_edges",
            "source_references",
            "global_constraints",
            "acceptance",
            "upstream_interface_commitments",
            "expected_report_path",
        }
    )
    value = _map_object(payload, fields=fields, name="task brief")
    if value["schema_version"] != MAP_SCHEMA_VERSION:
        raise ValueError("task brief schema_version must be 1")
    expected_sha = _map_hash(program_map_sha256, "expected program map SHA")
    if _map_hash(value["program_map_sha256"], "task brief program map SHA") != expected_sha:
        raise ValueError("task brief program map SHA does not match")
    normalized_hashes = {
        _map_id(document_id, "brief document ID"): _map_hash(digest, "brief document SHA")
        for document_id, digest in document_hashes.items()
    }
    references = _validate_source_references(
        value["source_references"],
        document_hashes=normalized_hashes,
        name="task brief source_references",
    )
    constraints = _validate_bindings(
        value["global_constraints"],
        document_hashes=normalized_hashes,
        text_field="statement",
        name="task brief global_constraints",
    )
    dependencies = [
        _map_id(item, "task brief dependency")
        for item in _map_string_list(value["dependencies"], "task brief dependencies")
    ]
    dependency_edges = _validate_dependency_edges(
        value["dependency_edges"],
        document_hashes=normalized_hashes,
        name="task brief dependency_edges",
    )
    if dependencies != [str(edge["task_id"]) for edge in dependency_edges]:
        raise ValueError("task brief dependency edges differ from dependencies")
    expected_report_path = normalize_relative_path(
        _map_text(value["expected_report_path"], "expected report path", 512)
    )
    if not expected_report_path.startswith("reports/"):
        raise ValueError("task brief expected report path must be below reports")
    return {
        "schema_version": MAP_SCHEMA_VERSION,
        "task_id": _map_id(value["task_id"], "task brief task_id"),
        "program_map_sha256": expected_sha,
        "title": _map_text(value["title"], "task brief title", 1024),
        "dependencies": dependencies,
        "dependency_edges": dependency_edges,
        "source_references": references,
        "global_constraints": constraints,
        "acceptance": _validate_bindings(
            value["acceptance"],
            document_hashes=normalized_hashes,
            text_field="command",
            name="task brief acceptance",
        ),
        "upstream_interface_commitments": _validate_bindings(
            value["upstream_interface_commitments"],
            document_hashes=normalized_hashes,
            text_field="statement",
            name="task brief upstream interface commitments",
        ),
        "expected_report_path": expected_report_path,
    }


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
