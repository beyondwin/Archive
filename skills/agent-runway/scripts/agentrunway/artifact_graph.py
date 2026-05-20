from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .db import AgentRunwayDb


def _status_for_path(path: Path) -> str:
    return "done" if path.exists() else "missing"


def _load_coverage(run_dir: Path) -> dict[str, Any]:
    contract_path = run_dir / "contract.json"
    if contract_path.exists():
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        coverage = contract.get("coverage", {})
        return {
            "covered": list(coverage.get("covered", [])),
            "partial": list(coverage.get("partial", [])),
            "blocked": list(coverage.get("blocked", [])),
            "unreferenced": list(coverage.get("unreferenced", [])),
        }
    return {"covered": [], "partial": [], "blocked": [], "unreferenced": []}


def _derive_coverage(run_dir: Path, db: AgentRunwayDb) -> dict[str, Any]:
    coverage = _load_coverage(run_dir)
    blocked_refs: set[str] = set(coverage.get("blocked", []))
    covered_refs: set[str] = set(coverage.get("covered", []))
    for task in db.list_tasks():
        refs = json.loads(task["spec_refs_json"]) if isinstance(task.get("spec_refs_json"), str) else []
        if task["status"] == "blocked":
            blocked_refs.update(refs)
            covered_refs.difference_update(refs)
    coverage["covered"] = sorted(covered_refs)
    coverage["blocked"] = sorted(blocked_refs)
    return coverage


def _task_refs(task: dict[str, Any]) -> list[str]:
    refs = task.get("spec_refs_json")
    if isinstance(refs, str):
        return [str(ref) for ref in json.loads(refs)]
    return []


def _merge_candidates_by_task(db: AgentRunwayDb) -> dict[str, list[dict[str, Any]]]:
    by_task: dict[str, list[dict[str, Any]]] = {}
    for candidate in db.list_merge_candidates():
        by_task.setdefault(str(candidate["task_id"]), []).append(candidate)
    return by_task


def _has_merged_candidate_evidence(task: dict[str, Any], candidates: list[dict[str, Any]]) -> bool:
    for candidate in candidates:
        if candidate.get("status") != "merged":
            continue
        if not candidate.get("commits"):
            continue
        if task.get("phase") == "implementation" and not candidate.get("changed_files"):
            continue
        return True
    return False


def _derive_implementation_evidence_coverage(db: AgentRunwayDb) -> dict[str, list[str]]:
    planned_refs: set[str] = set()
    simulated_refs: set[str] = set()
    implemented_refs: set[str] = set()
    blocked_refs: set[str] = set()
    candidates_by_task = _merge_candidates_by_task(db)
    for task in db.list_tasks():
        refs = set(_task_refs(task))
        if not refs:
            continue
        planned_refs.update(refs)
        status = str(task.get("status") or "")
        candidates = candidates_by_task.get(str(task["task_id"]), [])
        candidate_statuses = {str(candidate.get("status") or "") for candidate in candidates}
        if status == "simulated_completed":
            simulated_refs.update(refs)
        if status == "merged" and _has_merged_candidate_evidence(task, candidates):
            implemented_refs.update(refs)
        if status in {"blocked", "failed"} or candidate_statuses.intersection({"merge_blocked", "merge_conflict"}):
            blocked_refs.update(refs)
    return {
        "planned": sorted(planned_refs),
        "simulated": sorted(simulated_refs),
        "implemented": sorted(implemented_refs),
        "blocked": sorted(blocked_refs),
    }


def build_artifact_graph(*, run_dir: Path, db: AgentRunwayDb) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = [
        {
            "id": "contract",
            "kind": "contract",
            "status": _status_for_path(run_dir / "contract.json"),
            "path": str(run_dir / "contract.json"),
        },
        {
            "id": "events",
            "kind": "events",
            "status": _status_for_path(run_dir / "events.jsonl"),
            "path": str(run_dir / "events.jsonl"),
        },
    ]
    for task in db.list_tasks():
        task_id = str(task["task_id"])
        nodes.append(
            {
                "id": f"{task_id}:packet",
                "kind": "task_packet",
                "task_id": task_id,
                "status": _status_for_path(run_dir / "packets" / f"{task_id}.json"),
                "path": str(run_dir / "packets" / f"{task_id}.json"),
            }
        )
    for worker in db.list_workers():
        task_id = str(worker["task_id"])
        worker_id = str(worker["worker_id"])
        result_name = "worker_result.json"
        if worker["role"] == "reviewer":
            result_name = "review_result.json"
        if worker["role"] == "verifier":
            result_name = "verification_result.json"
        result_path = run_dir / "artifacts" / task_id / worker_id / result_name
        nodes.append(
            {
                "id": f"{task_id}:{worker_id}:{result_name.removesuffix('.json')}",
                "kind": result_name.removesuffix(".json"),
                "task_id": task_id,
                "worker_id": worker_id,
                "status": _status_for_path(result_path),
                "path": str(result_path),
            }
        )
    for candidate in db.list_merge_candidates():
        status = "done" if candidate["status"] == "merged" else "failed" if candidate["status"] == "merge_conflict" else "ready"
        nodes.append(
            {
                "id": f"{candidate['task_id']}:{candidate['worker_id']}:merge_candidate",
                "kind": "merge_candidate",
                "task_id": candidate["task_id"],
                "worker_id": candidate["worker_id"],
                "status": status,
                "detail": candidate["status"],
            }
        )
    coverage = _derive_coverage(run_dir, db)
    implementation_evidence_coverage = _derive_implementation_evidence_coverage(db)
    coverage["implementation_evidence_coverage"] = implementation_evidence_coverage
    return {
        "nodes": nodes,
        "coverage": coverage,
        "implementation_evidence_coverage": implementation_evidence_coverage,
    }


def write_artifact_graph(*, run_dir: Path, db: AgentRunwayDb) -> dict[str, Any]:
    payload = build_artifact_graph(run_dir=run_dir, db=db)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "artifact_graph.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (run_dir / "coverage.json").write_text(
        json.dumps(payload["coverage"], ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return payload
