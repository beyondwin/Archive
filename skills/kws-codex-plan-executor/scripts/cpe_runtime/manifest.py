from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from pathlib import PurePosixPath

from .model_policy import policy_hash, policy_payload


def canonical_hash(payload: object) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def relative_ref(path: Path) -> str:
    resolved = path.expanduser().resolve()
    home = Path.home().resolve()
    try:
        return f"~/{resolved.relative_to(home).as_posix()}"
    except ValueError:
        return str(resolved)


def resolve_ref(value: str) -> Path:
    return Path(value).expanduser().resolve()


def file_record(path: Path) -> dict[str, str]:
    return {"ref": relative_ref(path), "sha256": sha256_file(path)}


def _fsync_dir(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def create_manifest(
    run_id: str,
    mode: str,
    workspace: Path,
    worktree: Path,
    plan: Path,
    spec: Path | None,
    task_graph: list[dict],
    pricing_snapshot: Path,
    *,
    docs: list[Path] | None = None,
    source_head: str | None = None,
    source_status: list[str] | None = None,
) -> dict:
    if not run_id or "/" in run_id or run_id in {".", ".."}:
        raise ValueError("invalid run_id")
    ids = [str(item.get("id", "")) for item in task_graph]
    if any(not item for item in ids) or len(ids) != len(set(ids)):
        raise ValueError("task graph requires unique task ids")
    return {
        "schema_version": "3",
        "run_id": run_id,
        "mode": mode,
        "workspace_ref": relative_ref(workspace),
        "execution_worktree_ref": relative_ref(worktree),
        "plan": file_record(plan),
        "spec": file_record(spec) if spec else None,
        "docs": [file_record(path) for path in (docs or [])],
        "task_graph": task_graph,
        "plan_graph_hash": canonical_hash(task_graph),
        "model_policy": policy_payload(),
        "model_policy_hash": policy_hash(),
        "pricing_snapshot": file_record(pricing_snapshot),
        "pricing_snapshot_hash": sha256_file(pricing_snapshot),
        "source_git": {"head": source_head, "status": list(source_status or [])},
        "task_packets": [],
    }


def write_manifest(path: Path, manifest: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    _fsync_dir(path.parent)


def load_manifest(path: Path) -> dict:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "3":
        raise ValueError("unsupported_schema")
    required = {
        "run_id", "workspace_ref", "execution_worktree_ref", "plan", "task_graph",
        "plan_graph_hash", "model_policy", "model_policy_hash", "pricing_snapshot",
        "pricing_snapshot_hash",
    }
    if not required.issubset(manifest):
        raise ValueError("manifest_invalid")
    return manifest


def load_verified_manifest(path: Path) -> dict:
    manifest = load_manifest(path)
    errors = validate_manifest(manifest)
    if errors:
        raise ValueError(errors[0])
    return manifest


def validate_manifest(manifest: dict) -> list[str]:
    errors: list[str] = []
    if manifest.get("plan_graph_hash") != canonical_hash(manifest.get("task_graph")):
        errors.append("manifest_hash_mismatch")
    if manifest.get("model_policy") != policy_payload() or manifest.get("model_policy_hash") != policy_hash():
        errors.append("model_policy_hash_mismatch")
    records = [manifest.get("plan"), manifest.get("spec"), manifest.get("pricing_snapshot")]
    records.extend(manifest.get("docs") or [])
    for record in records:
        if record is None:
            continue
        if not isinstance(record, dict) or not record.get("ref") or not record.get("sha256"):
            errors.append("manifest_hash_mismatch")
            continue
        path = resolve_ref(str(record["ref"]))
        if not path.is_file() or sha256_file(path) != record["sha256"]:
            errors.append("manifest_hash_mismatch")
    pricing = manifest.get("pricing_snapshot") or {}
    if pricing.get("sha256") != manifest.get("pricing_snapshot_hash"):
        errors.append("pricing_snapshot_hash_mismatch")
    packet_entries = manifest.get("task_packets")
    if not isinstance(packet_entries, list):
        errors.append("packet_index_invalid")
    else:
        seen: set[str] = set()
        task_ids = {str(task.get("id")) for task in manifest.get("task_graph", []) if isinstance(task, dict)}
        for entry in packet_entries:
            if not isinstance(entry, dict):
                errors.append("packet_index_invalid")
                continue
            task_id = entry.get("task_id")
            path = entry.get("path")
            digest = entry.get("sha256")
            if (
                not isinstance(task_id, str)
                or task_id not in task_ids
                or task_id in seen
                or not isinstance(path, str)
                or PurePosixPath(path) != PurePosixPath("artifacts", "task-packets", f"{task_id}.json")
                or entry.get("media_type") != "application/json"
                or not isinstance(digest, str)
                or len(digest) != 64
            ):
                errors.append("packet_index_invalid")
            seen.add(str(task_id))
    return list(dict.fromkeys(errors))
