"""Immutable, content-addressed task contracts for CPE v4."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import Literal, Mapping, cast

from .manifest import plan_graph_record, sha256_bytes, upstream_plan_graph_sha256


TASK_CONTRACT_SCHEMA_VERSION = "cpe.task-contract.v4"
TASK_CONTRACT_VNEXT_SCHEMA_VERSION = "cpe.task-contract.vnext"
TaskType = Literal[
    "tdd_implementation",
    "non_tdd_implementation",
    "documentation",
    "verification",
    "external_effect",
    "release_closeout",
]
TASK_TYPES = {
    "tdd_implementation",
    "non_tdd_implementation",
    "documentation",
    "verification",
    "external_effect",
    "release_closeout",
}


def canonical_contract_bytes(payload: object) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _json_copy(value: object) -> object:
    return json.loads(json.dumps(value, ensure_ascii=False))


class _FrozenDict(dict):
    """A JSON-compatible dict view that rejects mutation after construction."""

    def _reject_mutation(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        raise TypeError("TaskContractV4 nested state is immutable")

    __setitem__ = _reject_mutation
    __delitem__ = _reject_mutation
    clear = _reject_mutation
    pop = _reject_mutation
    popitem = _reject_mutation
    setdefault = _reject_mutation
    update = _reject_mutation
    __ior__ = _reject_mutation


def _deep_freeze(value: object) -> object:
    if isinstance(value, dict):
        return _FrozenDict({key: _deep_freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze(item) for item in value)
    return value


@dataclass(frozen=True)
class TaskContractV4:
    schema_version: str
    task_id: str
    title: str
    task_type: TaskType
    risk_class: str
    dependencies: tuple[str, ...]
    task_source: str
    task_source_sha256: str
    spec_sections: tuple[dict[str, str], ...]
    file_claims: tuple[str, ...]
    forbidden_paths: tuple[str, ...]
    acceptance_commands: tuple[str, ...]
    required_methods: tuple[str, ...]
    required_evidence: tuple[str, ...]
    checkpoint_message: str
    source_hashes: dict[str, object]
    contract_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "spec_sections",
            tuple(_deep_freeze(dict(section)) for section in self.spec_sections),
        )
        object.__setattr__(self, "source_hashes", _deep_freeze(dict(self.source_hashes)))

    def body(self) -> dict[str, object]:
        """Return the canonical digest body; the digest itself lives beside it."""
        return {
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "title": self.title,
            "task_type": self.task_type,
            "risk_class": self.risk_class,
            "dependencies": list(self.dependencies),
            "task_source": self.task_source,
            "task_source_sha256": self.task_source_sha256,
            "spec_sections": _json_copy(list(self.spec_sections)),
            "file_claims": list(self.file_claims),
            "forbidden_paths": list(self.forbidden_paths),
            "acceptance_commands": list(self.acceptance_commands),
            "required_methods": list(self.required_methods),
            "required_evidence": list(self.required_evidence),
            "checkpoint_message": self.checkpoint_message,
            "source_hashes": _json_copy(self.source_hashes),
        }


@dataclass(frozen=True)
class TaskContractVNext:
    schema_version: str
    plan_id: str
    task_id: str
    qualified_task_id: str
    document_sha256: str
    upstream_graph_sha256: str
    title: str
    task_type: TaskType
    risk_class: str
    dependencies: tuple[str, ...]
    task_source: str
    task_source_sha256: str
    spec_sections: tuple[dict[str, str], ...]
    file_claims: tuple[str, ...]
    forbidden_paths: tuple[str, ...]
    acceptance_commands: tuple[str, ...]
    required_methods: tuple[str, ...]
    required_evidence: tuple[str, ...]
    checkpoint_message: str
    source_hashes: dict[str, object]
    contract_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "spec_sections",
            tuple(_deep_freeze(dict(section)) for section in self.spec_sections),
        )
        object.__setattr__(self, "source_hashes", _deep_freeze(dict(self.source_hashes)))

    def body(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "plan_id": self.plan_id,
            "task_id": self.task_id,
            "qualified_task_id": self.qualified_task_id,
            "document_sha256": self.document_sha256,
            "upstream_graph_sha256": self.upstream_graph_sha256,
            "title": self.title,
            "task_type": self.task_type,
            "risk_class": self.risk_class,
            "dependencies": list(self.dependencies),
            "task_source": self.task_source,
            "task_source_sha256": self.task_source_sha256,
            "spec_sections": _json_copy(list(self.spec_sections)),
            "file_claims": list(self.file_claims),
            "forbidden_paths": list(self.forbidden_paths),
            "acceptance_commands": list(self.acceptance_commands),
            "required_methods": list(self.required_methods),
            "required_evidence": list(self.required_evidence),
            "checkpoint_message": self.checkpoint_message,
            "source_hashes": _json_copy(self.source_hashes),
        }


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def _acceptance_commands(task: Mapping[str, object]) -> tuple[str, ...]:
    explicit = _strings(task.get("acceptance_commands"))
    if explicit:
        return explicit
    command = str(task.get("acceptance_command") or "").strip()
    return tuple(line.strip() for line in command.splitlines() if line.strip())


def _spec_sections(value: object) -> tuple[dict[str, str], ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError("spec_sections_invalid")
    sections: list[dict[str, str]] = []
    for raw in value:
        if not isinstance(raw, Mapping):
            raise ValueError("spec_sections_invalid")
        section = {
            "id": str(raw.get("id") or ""),
            "sha256": str(raw.get("sha256") or ""),
            "text": str(raw.get("text") or ""),
        }
        if not section["id"] or not section["sha256"]:
            raise ValueError("spec_sections_invalid")
        sections.append(section)
    return tuple(sections)


def _source_hashes(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("source_hashes_invalid")
    copied = _json_copy(dict(value))
    if not isinstance(copied, dict):
        raise ValueError("source_hashes_invalid")
    return copied


def _validated_contract(contract: TaskContractV4, expected_digest: str) -> TaskContractV4:
    if contract.schema_version != TASK_CONTRACT_SCHEMA_VERSION:
        raise ValueError("task_contract_schema_invalid")
    if contract.task_type not in TASK_TYPES:
        raise ValueError("task_type_invalid")
    if not contract.task_id or not contract.title or not contract.task_source:
        raise ValueError("task_contract_incomplete")
    if not contract.acceptance_commands:
        raise ValueError("acceptance_command_missing")
    if sha256_bytes(contract.task_source.encode("utf-8")) != contract.task_source_sha256:
        raise ValueError("task_source_digest_mismatch")

    source_spec_hashes = contract.source_hashes.get("spec_sections", {})
    if not isinstance(source_spec_hashes, dict):
        raise ValueError("source_hashes_invalid")
    for section in contract.spec_sections:
        section_id = section["id"]
        actual = sha256_bytes(section["text"].encode("utf-8"))
        if actual != section["sha256"] or source_spec_hashes.get(section_id) != actual:
            raise ValueError(f"spec_section_digest_mismatch:{section_id}")

    actual_digest = sha256_bytes(canonical_contract_bytes(contract.body()))
    if actual_digest != expected_digest:
        raise ValueError("task_contract_digest_mismatch")
    return replace(contract, contract_sha256=actual_digest)


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _strict_string(body: dict[str, object], name: str) -> str:
    value = body[name]
    if type(value) is not str:
        raise ValueError("task_contract_invalid")
    return value


def _strict_strings(body: dict[str, object], name: str) -> tuple[str, ...]:
    value = body[name]
    if type(value) is not list or any(type(item) is not str for item in value):
        raise ValueError("task_contract_invalid")
    return tuple(value)


def _strict_spec_sections(body: dict[str, object]) -> tuple[dict[str, str], ...]:
    value = body["spec_sections"]
    if type(value) is not list:
        raise ValueError("task_contract_invalid")
    sections: list[dict[str, str]] = []
    for raw in value:
        if (
            type(raw) is not dict
            or set(raw) != {"id", "sha256", "text"}
            or any(type(raw[key]) is not str for key in raw)
        ):
            raise ValueError("task_contract_invalid")
        sections.append({key: raw[key] for key in ("id", "sha256", "text")})
    return tuple(sections)


def _strict_source_hashes(body: dict[str, object]) -> dict[str, object]:
    value = body["source_hashes"]
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise ValueError("task_contract_invalid")
    copied = _source_hashes(value)
    if copied != value:
        raise ValueError("task_contract_invalid")
    return copied


def _validate_authoritative_graph(
    contract: TaskContractVNext, plan_graph: object | None
) -> None:
    if plan_graph is None:
        raise ValueError("task_contract_plan_graph_missing")
    record = plan_graph_record(plan_graph)
    tasks = record.get("tasks")
    if not isinstance(tasks, dict):
        raise ValueError("task_contract_graph_task_missing")
    task = tasks.get(contract.qualified_task_id)
    if (
        not isinstance(task, dict)
        or task.get("plan_id") != contract.plan_id
        or task.get("task_id") != contract.task_id
    ):
        raise ValueError("task_contract_graph_task_missing")
    document_id = task.get("plan_document_id")
    document_hashes = record.get("document_hashes")
    if (
        not isinstance(document_id, str)
        or not isinstance(document_hashes, dict)
        or document_hashes.get(document_id) != contract.document_sha256
    ):
        raise ValueError("task_document_binding_mismatch")
    authoritative_claims = task.get("file_claims")
    authoritative_refs = task.get("spec_refs")
    if (
        not isinstance(authoritative_claims, list)
        or not isinstance(authoritative_refs, list)
        or any(type(item) is not str for item in authoritative_claims)
        or any(type(item) is not str for item in authoritative_refs)
        or tuple(sorted(authoritative_claims))
        != contract.file_claims
        or tuple(sorted(authoritative_refs))
        != tuple(section["id"] for section in contract.spec_sections)
    ):
        raise ValueError("task_contract_graph_scope_mismatch")
    if task.get("task_source_sha256") != contract.task_source_sha256:
        raise ValueError("task_contract_source_mismatch")
    coverage = record.get("spec_coverage")
    spec_section_hashes = record.get("spec_section_hashes")
    if not isinstance(coverage, dict) or not isinstance(spec_section_hashes, dict):
        raise ValueError("task_contract_graph_scope_mismatch")
    covered_sections = tuple(
        sorted(
            str(section_id)
            for section_id, owners in coverage.items()
            if isinstance(owners, list) and contract.qualified_task_id in owners
        )
    )
    if covered_sections != tuple(section["id"] for section in contract.spec_sections):
        raise ValueError("task_contract_graph_scope_mismatch")
    for section in contract.spec_sections:
        owners = coverage.get(section["id"])
        if (
            not isinstance(owners, list)
            or contract.qualified_task_id not in owners
            or spec_section_hashes.get(section["id"]) != section["sha256"]
        ):
            raise ValueError("task_contract_graph_scope_mismatch")
    edges = record.get("edges")
    if not isinstance(edges, list):
        raise ValueError("task_contract_graph_dependency_mismatch")
    predecessors = sorted(
        edge[0]
        for edge in edges
        if isinstance(edge, list)
        and len(edge) == 2
        and all(isinstance(item, str) for item in edge)
        and edge[1] == contract.qualified_task_id
    )
    if (
        tuple(predecessors) != contract.dependencies
        or any(dependency not in tasks for dependency in contract.dependencies)
    ):
        raise ValueError("task_contract_graph_dependency_mismatch")
    if upstream_plan_graph_sha256(record, contract.plan_id) != contract.upstream_graph_sha256:
        raise ValueError("task_graph_binding_invalid")


def _validated_vnext_contract(
    contract: TaskContractVNext,
    expected_digest: str,
    *,
    plan_graph: object | None,
) -> TaskContractVNext:
    if contract.schema_version != TASK_CONTRACT_VNEXT_SCHEMA_VERSION:
        raise ValueError("task_contract_schema_invalid")
    if contract.task_type not in TASK_TYPES:
        raise ValueError("task_type_invalid")
    if (
        not contract.plan_id
        or "::" in contract.plan_id
        or not contract.task_id
        or "::" in contract.task_id
        or contract.qualified_task_id != f"{contract.plan_id}::{contract.task_id}"
    ):
        raise ValueError("qualified_task_id_invalid")
    if not _is_sha256(contract.document_sha256) or not _is_sha256(
        contract.upstream_graph_sha256
    ):
        raise ValueError("task_graph_binding_invalid")
    if any("::" not in dependency for dependency in contract.dependencies):
        raise ValueError("qualified_dependency_invalid")
    if (
        len(contract.dependencies) != len(set(contract.dependencies))
        or contract.qualified_task_id in contract.dependencies
        or contract.dependencies != tuple(sorted(contract.dependencies))
    ):
        raise ValueError("qualified_dependency_invalid")
    if (
        len(contract.file_claims) != len(set(contract.file_claims))
        or contract.file_claims != tuple(sorted(contract.file_claims))
    ):
        raise ValueError("task_contract_graph_scope_mismatch")
    section_ids = tuple(section["id"] for section in contract.spec_sections)
    if len(section_ids) != len(set(section_ids)) or section_ids != tuple(sorted(section_ids)):
        raise ValueError("task_contract_graph_scope_mismatch")
    if not contract.title or not contract.task_source or not contract.acceptance_commands:
        raise ValueError("task_contract_incomplete")
    if sha256_bytes(contract.task_source.encode("utf-8")) != contract.task_source_sha256:
        raise ValueError("task_source_digest_mismatch")
    source_spec_hashes = contract.source_hashes.get("spec_sections", {})
    if not isinstance(source_spec_hashes, dict):
        raise ValueError("source_hashes_invalid")
    if contract.source_hashes.get("plan") != contract.document_sha256:
        raise ValueError("task_document_binding_mismatch")
    if set(source_spec_hashes) != set(section_ids):
        raise ValueError("task_contract_graph_scope_mismatch")
    for section in contract.spec_sections:
        section_id = section["id"]
        actual = sha256_bytes(section["text"].encode("utf-8"))
        if actual != section["sha256"] or source_spec_hashes.get(section_id) != actual:
            raise ValueError(f"spec_section_digest_mismatch:{section_id}")
    _validate_authoritative_graph(contract, plan_graph)
    actual_digest = sha256_bytes(canonical_contract_bytes(contract.body()))
    if actual_digest != expected_digest:
        raise ValueError("task_contract_digest_mismatch")
    return replace(contract, contract_sha256=actual_digest)


def _vnext_contract_from_body(
    body: Mapping[str, object],
    expected_digest: str,
    *,
    plan_graph: object | None,
) -> TaskContractVNext:
    required = {
        "schema_version",
        "plan_id",
        "task_id",
        "qualified_task_id",
        "document_sha256",
        "upstream_graph_sha256",
        "title",
        "task_type",
        "risk_class",
        "dependencies",
        "task_source",
        "task_source_sha256",
        "spec_sections",
        "file_claims",
        "forbidden_paths",
        "acceptance_commands",
        "required_methods",
        "required_evidence",
        "checkpoint_message",
        "source_hashes",
    }
    if type(body) is not dict or set(body) != required or not _is_sha256(expected_digest):
        raise ValueError("task_contract_invalid")
    strict_body = cast(dict[str, object], body)
    contract = TaskContractVNext(
        schema_version=_strict_string(strict_body, "schema_version"),
        plan_id=_strict_string(strict_body, "plan_id"),
        task_id=_strict_string(strict_body, "task_id"),
        qualified_task_id=_strict_string(strict_body, "qualified_task_id"),
        document_sha256=_strict_string(strict_body, "document_sha256"),
        upstream_graph_sha256=_strict_string(strict_body, "upstream_graph_sha256"),
        title=_strict_string(strict_body, "title"),
        task_type=cast(TaskType, _strict_string(strict_body, "task_type")),
        risk_class=_strict_string(strict_body, "risk_class"),
        dependencies=_strict_strings(strict_body, "dependencies"),
        task_source=_strict_string(strict_body, "task_source"),
        task_source_sha256=_strict_string(strict_body, "task_source_sha256"),
        spec_sections=_strict_spec_sections(strict_body),
        file_claims=_strict_strings(strict_body, "file_claims"),
        forbidden_paths=_strict_strings(strict_body, "forbidden_paths"),
        acceptance_commands=_strict_strings(strict_body, "acceptance_commands"),
        required_methods=_strict_strings(strict_body, "required_methods"),
        required_evidence=_strict_strings(strict_body, "required_evidence"),
        checkpoint_message=_strict_string(strict_body, "checkpoint_message"),
        source_hashes=_strict_source_hashes(strict_body),
        contract_sha256=expected_digest,
    )
    if body != contract.body():
        raise ValueError("task_contract_invalid")
    return _validated_vnext_contract(contract, expected_digest, plan_graph=plan_graph)


def contract_from_body(
    body: object,
    expected_digest: str,
    *,
    plan_graph: object | None = None,
) -> TaskContractV4 | TaskContractVNext:
    if not isinstance(body, Mapping):
        raise ValueError("task_contract_invalid")
    if body.get("schema_version") == TASK_CONTRACT_VNEXT_SCHEMA_VERSION:
        return _vnext_contract_from_body(body, expected_digest, plan_graph=plan_graph)
    required = {
        "schema_version",
        "task_id",
        "title",
        "task_type",
        "risk_class",
        "dependencies",
        "task_source",
        "task_source_sha256",
        "spec_sections",
        "file_claims",
        "forbidden_paths",
        "acceptance_commands",
        "required_methods",
        "required_evidence",
        "checkpoint_message",
        "source_hashes",
    }
    if set(body) != required:
        raise ValueError("task_contract_invalid")
    task_type = str(body["task_type"])
    contract = TaskContractV4(
        schema_version=str(body["schema_version"]),
        task_id=str(body["task_id"]),
        title=str(body["title"]),
        task_type=cast(TaskType, task_type),
        risk_class=str(body["risk_class"]),
        dependencies=_strings(body["dependencies"]),
        task_source=str(body["task_source"]),
        task_source_sha256=str(body["task_source_sha256"]),
        spec_sections=_spec_sections(body["spec_sections"]),
        file_claims=_strings(body["file_claims"]),
        forbidden_paths=_strings(body["forbidden_paths"]),
        acceptance_commands=_strings(body["acceptance_commands"]),
        required_methods=_strings(body["required_methods"]),
        required_evidence=_strings(body["required_evidence"]),
        checkpoint_message=str(body["checkpoint_message"]),
        source_hashes=_source_hashes(body["source_hashes"]),
        contract_sha256=expected_digest,
    )
    return _validated_contract(contract, expected_digest)


def compile_task_contract(
    task: Mapping[str, object],
    *,
    spec_sections: tuple[dict[str, str], ...] = (),
    source_hashes: dict[str, object] | None = None,
) -> TaskContractV4:
    task_type_value = str(task.get("task_type") or "")
    if task_type_value not in TASK_TYPES:
        raise ValueError("task_type_invalid")
    task_type = cast(TaskType, task_type_value)
    task_id = str(task.get("id") or task.get("task_id") or "")
    title = str(task.get("title") or task_id)
    task_source = str(task.get("task_source") or "")
    execution_contract = task.get("execution_contract")
    execution_contract = execution_contract if isinstance(execution_contract, Mapping) else {}
    forbidden_paths = _strings(task.get("forbidden_paths")) or _strings(
        execution_contract.get("forbidden_paths")
    )
    required_methods = _strings(task.get("required_methods"))
    if not required_methods:
        required_methods = (
            ("using-superpowers", "test-driven-development")
            if task_type == "tdd_implementation"
            else ("using-superpowers",)
        )
    required_evidence = _strings(task.get("required_evidence"))
    if not required_evidence and task_type == "tdd_implementation":
        required_evidence = ("red", "green")
    acceptance_commands = _acceptance_commands(task)
    source_hashes_value = _source_hashes(source_hashes or task.get("source_hashes") or {})
    contract = TaskContractV4(
        schema_version=TASK_CONTRACT_SCHEMA_VERSION,
        task_id=task_id,
        title=title,
        task_type=task_type,
        risk_class=str(task.get("risk_class") or "high"),
        dependencies=_strings(task.get("dependencies")) or _strings(task.get("depends_on")),
        task_source=task_source,
        task_source_sha256=sha256_bytes(task_source.encode("utf-8")),
        spec_sections=_spec_sections(spec_sections),
        file_claims=_strings(task.get("file_claims")) or _strings(task.get("files")),
        forbidden_paths=forbidden_paths,
        acceptance_commands=acceptance_commands,
        required_methods=required_methods,
        required_evidence=required_evidence,
        checkpoint_message=str(task.get("checkpoint_message") or f"Complete {task_id}: {title}"),
        source_hashes=source_hashes_value,
        contract_sha256="",
    )
    digest = sha256_bytes(canonical_contract_bytes(contract.body()))
    return _validated_contract(replace(contract, contract_sha256=digest), digest)


def compile_task_contract_vnext(
    task: Mapping[str, object],
    *,
    plan_id: str,
    document_sha256: str,
    upstream_graph_sha256: str,
    spec_sections: tuple[dict[str, str], ...] = (),
    source_hashes: dict[str, object] | None = None,
    plan_graph: object,
) -> TaskContractVNext:
    """Compile one task whose identity and dependencies are globally qualified."""

    task_type_value = str(task.get("task_type") or "")
    if task_type_value not in TASK_TYPES:
        raise ValueError("task_type_invalid")
    task_type = cast(TaskType, task_type_value)
    task_id = str(task.get("id") or task.get("task_id") or "")
    task_source = str(task.get("task_source") or "")
    execution_contract = task.get("execution_contract")
    execution_contract = execution_contract if isinstance(execution_contract, Mapping) else {}
    forbidden_paths = _strings(task.get("forbidden_paths")) or _strings(
        execution_contract.get("forbidden_paths")
    )
    required_methods = _strings(task.get("required_methods"))
    if not required_methods:
        required_methods = (
            ("using-superpowers", "test-driven-development")
            if task_type == "tdd_implementation"
            else ("using-superpowers",)
        )
    required_evidence = _strings(task.get("required_evidence"))
    if not required_evidence and task_type == "tdd_implementation":
        required_evidence = ("red", "green")
    source_hashes_value = _source_hashes(source_hashes or task.get("source_hashes") or {})
    dependencies = _strings(task.get("dependencies")) or _strings(task.get("depends_on"))
    if len(dependencies) != len(set(dependencies)):
        raise ValueError("qualified_dependency_invalid")
    file_claims = _strings(task.get("file_claims")) or _strings(task.get("files"))
    if len(file_claims) != len(set(file_claims)):
        raise ValueError("task_contract_graph_scope_mismatch")
    spec_sections_value = _spec_sections(spec_sections)
    section_ids = tuple(section["id"] for section in spec_sections_value)
    if len(section_ids) != len(set(section_ids)):
        raise ValueError("task_contract_graph_scope_mismatch")
    contract = TaskContractVNext(
        schema_version=TASK_CONTRACT_VNEXT_SCHEMA_VERSION,
        plan_id=plan_id,
        task_id=task_id,
        qualified_task_id=f"{plan_id}::{task_id}",
        document_sha256=document_sha256,
        upstream_graph_sha256=upstream_graph_sha256,
        title=str(task.get("title") or task_id),
        task_type=task_type,
        risk_class=str(task.get("risk_class") or "high"),
        dependencies=tuple(sorted(dependencies)),
        task_source=task_source,
        task_source_sha256=sha256_bytes(task_source.encode("utf-8")),
        spec_sections=tuple(sorted(spec_sections_value, key=lambda section: section["id"])),
        file_claims=tuple(sorted(file_claims)),
        forbidden_paths=forbidden_paths,
        acceptance_commands=_acceptance_commands(task),
        required_methods=required_methods,
        required_evidence=required_evidence,
        checkpoint_message=str(
            task.get("checkpoint_message") or f"Complete {plan_id}::{task_id}"
        ),
        source_hashes=source_hashes_value,
        contract_sha256="",
    )
    digest = sha256_bytes(canonical_contract_bytes(contract.body()))
    return _validated_vnext_contract(
        replace(contract, contract_sha256=digest),
        digest,
        plan_graph=plan_graph,
    )
