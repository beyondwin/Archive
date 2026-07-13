from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from pathlib import Path
from pathlib import PurePosixPath

from .model_policy import policy_hash, policy_payload


RUN_SCHEMA_VERSION = "4"
COMPATIBILITY_EPOCH = "cpe-v4"


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


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _graph_value(graph: object, name: str) -> object:
    if isinstance(graph, Mapping):
        return graph.get(name)
    return getattr(graph, name)


def plan_graph_record(graph: object) -> dict[str, object]:
    """Return the complete canonical PlanGraph body plus its verified digest."""

    fields = (
        "schema_version",
        "spec_document_id",
        "program_document_id",
        "plan_documents",
        "plan_ids",
        "document_hashes",
        "spec_section_hashes",
        "tasks",
        "edges",
        "spec_coverage",
        "file_ownership",
        "ownership_authority",
        "file_ownership_patterns",
        "file_interface_writers",
        "plan_checkpoints",
        "global_integration_gate",
    )
    body = {name: _plain(_graph_value(graph, name)) for name in fields}
    expected = str(_graph_value(graph, "graph_sha256"))
    actual = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if actual != expected:
        raise ValueError("plan_graph_digest_mismatch")
    return {**body, "graph_sha256": expected}


def bind_plan_graph(manifest: dict, graph: object) -> dict:
    """Bind a manifest copy to one immutable, content-addressed PlanGraph."""

    bound = dict(manifest)
    bound["plan_graph"] = plan_graph_record(graph)
    return bound


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
    runtime_commit: str | None = None,
    plan_graph: object | None = None,
) -> dict:
    if not run_id or "/" in run_id or run_id in {".", ".."}:
        raise ValueError("invalid run_id")
    ids = [str(item.get("id", "")) for item in task_graph]
    if any(not item for item in ids) or len(ids) != len(set(ids)):
        raise ValueError("task graph requires unique task ids")
    manifest = {
        "schema_version": RUN_SCHEMA_VERSION,
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
        "runtime": {
            "runtime_commit": runtime_commit or source_head or "0" * 40,
            "compatibility_epoch": COMPATIBILITY_EPOCH,
        },
        "task_packets": [],
    }
    return bind_plan_graph(manifest, plan_graph) if plan_graph is not None else manifest


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
    if not isinstance(manifest, dict) or manifest.get("schema_version") != RUN_SCHEMA_VERSION:
        raise ValueError("unsupported_run_schema")
    required = {
        "run_id", "workspace_ref", "execution_worktree_ref", "plan", "task_graph",
        "plan_graph_hash", "model_policy", "model_policy_hash", "pricing_snapshot",
        "pricing_snapshot_hash", "runtime",
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
    if not isinstance(manifest, dict) or manifest.get("schema_version") != RUN_SCHEMA_VERSION:
        return ["unsupported_run_schema"]
    errors: list[str] = []
    if "plan_graph" in manifest:
        graph = manifest.get("plan_graph")
        if not isinstance(graph, dict):
            errors.append("plan_graph_invalid")
        else:
            expected = graph.get("graph_sha256")
            body = {key: value for key, value in graph.items() if key != "graph_sha256"}
            actual = hashlib.sha256(
                json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            graph_task_ids = set((graph.get("tasks") or {}).keys()) if isinstance(
                graph.get("tasks"), dict
            ) else set()
            task_ids = {
                str(task.get("id"))
                for task in manifest.get("task_graph", [])
                if isinstance(task, dict)
            }
            if (
                not isinstance(expected, str)
                or expected != actual
                or not graph_task_ids
                or task_ids != graph_task_ids
            ):
                errors.append("plan_graph_digest_mismatch")
    attempt_limit = manifest.get("attempt_budget_limit", 40)
    if type(attempt_limit) is not int or not 1 <= attempt_limit <= 40:
        errors.append("attempt_budget_limit_invalid")
    if "release_policy_sha256" in manifest:
        try:
            from .release_policy_v4 import load_release_policy

            release_policy = load_release_policy()
            if (
                manifest.get("release_policy_sha256") != release_policy["policy_sha256"]
                or attempt_limit != release_policy["dogfood_attempt_limit"]
                or len(manifest.get("task_graph") or []) != 1
                or manifest["task_graph"][0].get("task_contract_sha256")
                != release_policy["dogfood_task_contract_sha256"]
            ):
                errors.append("release_policy_binding_invalid")
        except (OSError, ValueError):
            errors.append("release_policy_binding_invalid")
    runtime = manifest.get("runtime")
    if (
        not isinstance(runtime, dict)
        or runtime.get("compatibility_epoch") != COMPATIBILITY_EPOCH
        or not isinstance(runtime.get("runtime_commit"), str)
        or len(runtime["runtime_commit"]) != 40
        or any(character not in "0123456789abcdef" for character in runtime["runtime_commit"])
    ):
        errors.append("runtime_identity_invalid")
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
