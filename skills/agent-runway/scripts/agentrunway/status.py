from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from .artifact_graph import build_artifact_graph
from .db import AgentRunwayDb
from .diagnostics import diagnose_run


def next_operator_action(run_json: dict[str, Any], agentlens: dict[str, Any]) -> str:
    diagnosis = run_json.get("diagnosis")
    if isinstance(diagnosis, dict) and diagnosis.get("next_action"):
        return str(diagnosis["next_action"])

    db_path = run_json.get("state_db")
    if isinstance(db_path, str) and db_path:
        try:
            db = AgentRunwayDb.open(Path(db_path))
            return diagnose_run(run_json=run_json, db=db).next_action
        except Exception:
            pass

    status = str(run_json.get("status") or "unknown")
    tasks = run_json.get("tasks") if isinstance(run_json.get("tasks"), list) else []
    blocked = any(isinstance(task, dict) and task.get("status") == "blocked" for task in tasks)
    if status == "finished":
        return "apply or inspect artifacts"
    if blocked or status in {"blocked", "failed"}:
        return "inspect blocked tasks and run resume --dry-run"
    if status == "cancelled":
        return "inspect events before restarting"
    if str(agentlens.get("last_status")) == "agentlens_failed" or int(agentlens.get("failed", 0) or 0) > 0:
        return "inspect AgentLens failures and continue monitoring"
    if status in {"created", "running"}:
        return "continue monitoring"
    if status == "missing":
        return "none"
    return "inspect run state"


def format_run_status(run: dict[str, object]) -> str:
    tasks = run.get("tasks") if isinstance(run.get("tasks"), list) else []
    counts = Counter(str(task.get("status", "unknown")) for task in tasks if isinstance(task, dict))
    suffix = " ".join(f"{key}={value}" for key, value in sorted(counts.items()))
    agentlens = run.get("agentlens") if isinstance(run.get("agentlens"), dict) else {}
    diagnosis = run.get("diagnosis") if isinstance(run.get("diagnosis"), dict) else {}
    next_action = diagnosis.get("next_action") or run.get("next_action")
    diagnosis_bits = ""
    if diagnosis:
        diagnosis_bits = f" diagnosis={diagnosis.get('status')} reason={diagnosis.get('reason')}"
    return (
        f"{run.get('run_id')} status={run.get('status')} {suffix}{diagnosis_bits} "
        f"agentlens={agentlens.get('last_status', 'unknown')} next_action={next_action}"
    ).strip()


def build_inspect_payload(*, run_json: dict[str, Any], db: AgentRunwayDb) -> dict[str, Any]:
    run_dir = Path(str(run_json["run_dir"]))
    graph = build_artifact_graph(run_dir=run_dir, db=db)
    coverage_path = run_dir / "coverage.json"
    coverage = json.loads(coverage_path.read_text(encoding="utf-8")) if coverage_path.exists() else graph["coverage"]
    agentlens = db.agentlens_summary()
    diagnosis = diagnose_run(run_json=run_json, db=db).to_dict()
    return {
        "run_id": run_json.get("run_id"),
        "status": run_json.get("status"),
        "run_dir": str(run_dir),
        "tasks": db.list_tasks(),
        "workers": db.list_workers(),
        "merge_candidates": db.list_merge_candidates(),
        "artifact_graph": graph,
        "coverage": coverage,
        "agentlens": agentlens,
        "diagnosis": diagnosis,
        "next_action": diagnosis["next_action"],
    }


def format_inspect_payload(payload: dict[str, Any]) -> str:
    agentlens = payload.get("agentlens", {})
    coverage = payload.get("coverage", {})
    diagnosis = payload.get("diagnosis", {})
    return (
        f"{payload.get('run_id')} status={payload.get('status')} "
        f"diagnosis={diagnosis.get('status')} "
        f"reason={diagnosis.get('reason')} "
        f"tasks={len(payload.get('tasks', []))} "
        f"workers={len(payload.get('workers', []))} "
        f"covered={len(coverage.get('covered', []))} "
        f"blocked={len(coverage.get('blocked', []))} "
        f"agentlens_failed={agentlens.get('failed', 0)} "
        f"next_action={payload.get('next_action')}"
    )
