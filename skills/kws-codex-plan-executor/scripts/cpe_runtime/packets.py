from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .task_contracts import contract_from_body


PACKET_MEDIA_TYPE = "application/json"
PACKET_SCHEMA_VERSION = "3.1"
PACKET_V4_SCHEMA_VERSION = "cpe.task-packet.v4"
PACKET_VNEXT_SCHEMA_VERSION = "cpe.task-packet.vnext"
PACKET_ROLE_POLICY: dict[str, dict[str, bool]] = {
    "scout": {"read_only": True, "verdict_capable": False, "product_write": False},
    "implementation": {"read_only": False, "verdict_capable": False, "product_write": True},
    "task_review": {"read_only": True, "verdict_capable": True, "product_write": False},
    "verification": {"read_only": True, "verdict_capable": True, "product_write": False},
    "repair": {"read_only": False, "verdict_capable": False, "product_write": True},
    "final_review": {"read_only": True, "verdict_capable": True, "product_write": False},
}


@dataclass(frozen=True)
class PacketDraft:
    task_id: str
    relative_path: str
    media_type: str
    sha256: str
    content: bytes


def canonical_packet_bytes(payload: object) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def export_packet(path: Path, draft: PacketDraft) -> None:
    """Export a packet once, through the canonical immutable boundary."""
    path = path.expanduser()
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(draft.content)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)


def _compiled_value(compiled: object, name: str, default: object) -> object:
    if isinstance(compiled, dict):
        return compiled.get(name, default)
    return getattr(compiled, name, default)


def _source_value(source: object, name: str, default: object = None) -> object:
    if isinstance(source, dict):
        return source.get(name, default)
    return getattr(source, name, default)


def _spec_bytes(compiled: object) -> bytes | None:
    sources = _compiled_value(compiled, "sources", ())
    if not isinstance(sources, (list, tuple)):
        return None
    for source in sources:
        if _source_value(source, "role") == "spec":
            content = _source_value(source, "content")
            if isinstance(content, bytes):
                return content
    return None


def _spec_sections(compiled: object, task: dict) -> list[dict[str, object]]:
    refs = [str(item) for item in task.get("spec_refs", []) if str(item).strip()]
    manifest = _compiled_value(compiled, "spec_manifest", None)
    if manifest is None:
        if refs:
            raise ValueError("spec_manifest_missing")
        return []
    if not refs:
        raise ValueError("missing_explicit_spec_mapping")
    sections = manifest.get("sections") if isinstance(manifest, dict) else None
    if not isinstance(sections, dict):
        raise ValueError("spec_manifest_invalid")
    content = _spec_bytes(compiled)
    if content is None:
        raise ValueError("spec_snapshot_missing")
    lines = content.decode("utf-8").splitlines(keepends=True)
    selected: list[dict[str, object]] = []
    for ref in refs:
        section = sections.get(ref)
        if not isinstance(section, dict):
            raise ValueError(f"unknown_spec_ref:{ref}")
        start = int(section.get("line_start", 1))
        end = int(section.get("line_end", start))
        text = "".join(lines[start - 1 : end])
        expected = str(section.get("sha256") or "")
        actual = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if expected and expected != actual:
            raise ValueError(f"spec_section_digest_mismatch:{ref}")
        selected.append({"id": ref, "sha256": actual, "text": text})
    return selected


def build_packet(compiled: object, task: dict) -> PacketDraft:
    task_id = str(task.get("id") or "")
    if not task_id or "/" in task_id or task_id in {".", ".."}:
        raise ValueError("invalid_task_id")
    task_contract = task.get("task_contract")
    task_contract_sha256 = task.get("task_contract_sha256")
    if task_contract is not None or task_contract_sha256 is not None:
        if not isinstance(task_contract, dict) or not isinstance(task_contract_sha256, str):
            raise ValueError("task_contract_invalid")
        contract = contract_from_body(task_contract, task_contract_sha256)
        is_vnext = contract.schema_version == "cpe.task-contract.vnext"
        packet_task_id = (
            contract.qualified_task_id if is_vnext else contract.task_id
        )
        if packet_task_id != task_id:
            raise ValueError("task_contract_id_mismatch")
        payload = {
            "schema_version": (
                PACKET_VNEXT_SCHEMA_VERSION if is_vnext else PACKET_V4_SCHEMA_VERSION
            ),
            "task_id": packet_task_id,
            "task_contract": contract.body(),
            "task_contract_sha256": contract.contract_sha256,
            "execution_contract": {
                "scope": "bounded task scope",
                "files_to_inspect": list(contract.file_claims),
                "allowed_edits": list(contract.file_claims),
                "forbidden_edits": list(contract.forbidden_paths),
                "acceptance_command_or_honest_substitute": "\n".join(contract.acceptance_commands),
            },
            "role_policy": PACKET_ROLE_POLICY,
            "source_hashes": contract.source_hashes,
        }
        content = canonical_packet_bytes(payload)
        return PacketDraft(
            task_id=task_id,
            relative_path=f"artifacts/task-packets/{task_id}.json",
            media_type=PACKET_MEDIA_TYPE,
            sha256=hashlib.sha256(content).hexdigest(),
            content=content,
        )
    contract = task.get("execution_contract") if isinstance(task.get("execution_contract"), dict) else {}
    claims = [str(item) for item in task.get("file_claims", [])]
    allowed = [str(item) for item in contract.get("allowed_paths", claims)]
    forbidden = [str(item) for item in contract.get("forbidden_paths", [])]
    acceptance = str(
        contract.get("acceptance_command") or task.get("acceptance_command") or ""
    ).strip()
    if not acceptance:
        raise ValueError("acceptance_command_missing")
    payload = {
        "schema_version": PACKET_SCHEMA_VERSION,
        "task_id": task_id,
        "task": task,
        "spec_sections": _spec_sections(compiled, task),
        "execution_contract": {
            "scope": "bounded task scope",
            "files_to_inspect": claims,
            "allowed_edits": allowed,
            "forbidden_edits": forbidden,
            "acceptance_command_or_honest_substitute": acceptance,
        },
        "required_methods": ["using-superpowers", "test-driven-development"],
        "role_policy": PACKET_ROLE_POLICY,
        "evidence_requirements": [
            "changed_files",
            "findings",
            "evidence_refs",
            "missing_evidence",
            "verification",
        ],
        "source_hashes": task.get("source_hashes") if isinstance(task.get("source_hashes"), dict) else {},
    }
    content = canonical_packet_bytes(payload)
    return PacketDraft(
        task_id=task_id,
        relative_path=f"artifacts/task-packets/{task_id}.json",
        media_type=PACKET_MEDIA_TYPE,
        sha256=hashlib.sha256(content).hexdigest(),
        content=content,
    )


def packet_entry(manifest: dict, task_id: str) -> dict[str, str]:
    entries = manifest.get("task_packets")
    if not isinstance(entries, list):
        raise ValueError("packet_not_indexed")
    matches = [entry for entry in entries if isinstance(entry, dict) and entry.get("task_id") == task_id]
    if len(matches) != 1:
        raise ValueError("packet_not_indexed")
    entry = matches[0]
    required = ("task_id", "path", "media_type", "sha256")
    if any(not isinstance(entry.get(key), str) or not entry.get(key) for key in required):
        raise ValueError("packet_index_invalid")
    return {key: str(entry[key]) for key in required}


def _read_no_follow(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            return handle.read()
    finally:
        os.close(descriptor)


def verify_packet(run_dir: Path, manifest: dict, task_id: str) -> PacketDraft:
    run_dir = run_dir.expanduser().resolve()
    entry = packet_entry(manifest, task_id)
    relative = PurePosixPath(entry["path"])
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("packet_path_invalid")
    expected_path = PurePosixPath("artifacts", "task-packets", f"{task_id}.json")
    if relative != expected_path or entry["media_type"] != PACKET_MEDIA_TYPE:
        raise ValueError("packet_index_invalid")
    path = run_dir.joinpath(*relative.parts)
    try:
        content = _read_no_follow(path)
    except OSError as exc:
        raise ValueError("packet_missing") from exc
    digest = hashlib.sha256(content).hexdigest()
    if digest != entry["sha256"]:
        raise ValueError("packet_digest_mismatch")
    try:
        payload = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("packet_invalid") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("task_id") != task_id
        or canonical_packet_bytes(payload) != content
    ):
        raise ValueError("packet_invalid")
    schema_version = payload.get("schema_version")
    if schema_version in {PACKET_V4_SCHEMA_VERSION, PACKET_VNEXT_SCHEMA_VERSION}:
        task_contract = payload.get("task_contract")
        task_contract_sha256 = payload.get("task_contract_sha256")
        if not isinstance(task_contract_sha256, str):
            raise ValueError("task_contract_invalid")
        contract = contract_from_body(task_contract, task_contract_sha256)
        contract_task_id = (
            contract.qualified_task_id
            if contract.schema_version == "cpe.task-contract.vnext"
            else contract.task_id
        )
        if contract_task_id != task_id:
            raise ValueError("task_contract_id_mismatch")
        if (
            schema_version == PACKET_VNEXT_SCHEMA_VERSION
            and contract.schema_version != "cpe.task-contract.vnext"
        ) or (
            schema_version == PACKET_V4_SCHEMA_VERSION
            and contract.schema_version != "cpe.task-contract.v4"
        ):
            raise ValueError("packet_contract_schema_mismatch")
        if payload.get("role_policy") != PACKET_ROLE_POLICY:
            raise ValueError("packet_role_policy_mismatch")
        if payload.get("source_hashes") != contract.source_hashes:
            raise ValueError("packet_source_hash_mismatch")
        expected_execution_contract = {
            "scope": "bounded task scope",
            "files_to_inspect": list(contract.file_claims),
            "allowed_edits": list(contract.file_claims),
            "forbidden_edits": list(contract.forbidden_paths),
            "acceptance_command_or_honest_substitute": "\n".join(contract.acceptance_commands),
        }
        if payload.get("execution_contract") != expected_execution_contract:
            raise ValueError("packet_contract_view_mismatch")
    elif schema_version != PACKET_SCHEMA_VERSION:
        raise ValueError("packet_invalid")
    return PacketDraft(task_id, entry["path"], entry["media_type"], entry["sha256"], content)
