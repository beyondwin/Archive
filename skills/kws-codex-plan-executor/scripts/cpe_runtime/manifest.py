from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from .model_policy import policy_hash, policy_payload


def canonical_hash(payload: object) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative_ref(path: Path) -> str:
    return str(path.resolve())


def file_record(path: Path) -> dict[str, str]:
    return {"ref": relative_ref(path), "sha256": sha256_file(path)}


def create_manifest(run_id: str, mode: str, workspace: Path, worktree: Path, plan: Path, spec: Path | None, task_graph: list[dict], pricing_snapshot: Path) -> dict:
    return {
        "schema_version": "3", "run_id": run_id, "mode": mode,
        "workspace_ref": relative_ref(workspace), "execution_worktree_ref": relative_ref(worktree),
        "plan": file_record(plan), "spec": file_record(spec) if spec else None,
        "task_graph": task_graph, "plan_graph_hash": canonical_hash(task_graph),
        "model_policy": policy_payload(), "model_policy_hash": policy_hash(),
        "pricing_snapshot": file_record(pricing_snapshot), "pricing_snapshot_hash": sha256_file(pricing_snapshot),
    }


def write_manifest(path: Path, manifest: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        handle.write("\n")
        handle.flush(); os.fsync(handle.fileno())


def load_manifest(path: Path) -> dict:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "3":
        raise ValueError("unsupported_schema")
    return manifest
