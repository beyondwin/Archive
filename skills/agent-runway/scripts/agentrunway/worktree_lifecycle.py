from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .db import AgentRunwayDb
from .models import TaskSpec
from .task_classifier import classify_task


DIAGNOSIS_STATES = {
    "adapter_crashed",
    "blocked",
    "diff_scope_failed",
    "failed",
    "malformed_result",
    "method_audit_failed",
    "stalled",
    "timeout",
    "verification_failed",
}
def lifecycle_for_worker(*, role: str, state: str) -> str:
    if state in DIAGNOSIS_STATES:
        return "retained_for_diagnosis"
    if role == "implementer":
        if state in {"merge_ready", "merged", "validated"}:
            return "retained_for_apply"
        if state == "not_selected":
            return "evidence_archived"
        return "active"
    if role in {"reviewer", "verifier"}:
        if state == "validated":
            return "cleanup_eligible"
        return "active"
    return "active"


def reviewer_mode_for_task(task: TaskSpec, *, force_full_tree: bool = False) -> str:
    if force_full_tree:
        return "full_tree"
    return classify_task(task).review_mode


def archive_candidate_evidence(*, run_dir: Path, db: AgentRunwayDb, candidate: dict[str, Any]) -> Path:
    task_id = str(candidate["task_id"])
    worker_id = str(candidate["worker_id"])
    evidence_dir = run_dir / "artifacts" / task_id / worker_id / "candidate_evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    (evidence_dir / "commits.json").write_text(
        json.dumps(list(candidate.get("commits") or []), ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (evidence_dir / "changed_files.json").write_text(
        json.dumps(list(candidate.get("changed_files") or []), ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (evidence_dir / "worker.json").write_text(
        json.dumps(db.get_worker(worker_id), ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return evidence_dir
