from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from .kernel import rebuild_snapshot
from .reconciliation import reconcile
SAFE_ACTIONS = {"rebuild_snapshot", "regenerate_derived_reports", "mark_stale_attempt_interrupted", "reconnect_existing_evidence"}
@dataclass(frozen=True)
class RepairPlan:
    actions: list[str]; findings: list[dict]
def plan_repairs(run_dir: Path) -> RepairPlan:
    report = reconcile(run_dir); return RepairPlan([item["repair_action"] for item in report.findings if item.get("repair_action") in SAFE_ACTIONS], report.findings)
def apply_repair(run_dir: Path, action: str) -> dict:
    if action not in SAFE_ACTIONS: raise ValueError("unsafe repair action")
    if action == "rebuild_snapshot": return rebuild_snapshot(run_dir)
    return {"action": action, "status": "planned"}
