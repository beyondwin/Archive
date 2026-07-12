"""Immutable, content-addressed task contracts for CPE v4."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import Literal, Mapping, cast

from .manifest import sha256_bytes


TASK_CONTRACT_SCHEMA_VERSION = "cpe.task-contract.v4"
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


def contract_from_body(body: object, expected_digest: str) -> TaskContractV4:
    if not isinstance(body, Mapping):
        raise ValueError("task_contract_invalid")
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
