from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from .artifact_graph import build_artifact_graph
from .db import AgentRunwayDb


def format_run_status(run: dict[str, object]) -> str:
    tasks = run.get("tasks") if isinstance(run.get("tasks"), list) else []
    counts = Counter(str(task.get("status", "unknown")) for task in tasks if isinstance(task, dict))
    suffix = " ".join(f"{key}={value}" for key, value in sorted(counts.items()))
    return f"{run.get('run_id')} status={run.get('status')} {suffix}".strip()


def build_inspect_payload(*, run_json: dict[str, Any], db: AgentRunwayDb) -> dict[str, Any]:
    run_dir = Path(str(run_json["run_dir"]))
    graph = build_artifact_graph(run_dir=run_dir, db=db)
    coverage_path = run_dir / "coverage.json"
    coverage = json.loads(coverage_path.read_text(encoding="utf-8")) if coverage_path.exists() else graph["coverage"]
    return {
        "run_id": run_json.get("run_id"),
        "status": run_json.get("status"),
        "run_dir": str(run_dir),
        "tasks": db.list_tasks(),
        "workers": db.list_workers(),
        "merge_candidates": db.list_merge_candidates(),
        "artifact_graph": graph,
        "coverage": coverage,
        "agentlens": db.agentlens_summary(),
    }


def format_inspect_payload(payload: dict[str, Any]) -> str:
    agentlens = payload.get("agentlens", {})
    coverage = payload.get("coverage", {})
    return (
        f"{payload.get('run_id')} status={payload.get('status')} "
        f"tasks={len(payload.get('tasks', []))} "
        f"workers={len(payload.get('workers', []))} "
        f"covered={len(coverage.get('covered', []))} "
        f"blocked={len(coverage.get('blocked', []))} "
        f"agentlens_failed={agentlens.get('failed', 0)}"
    )
