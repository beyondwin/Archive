from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from .events import read_events
from .kernel import Kernel, Transition, rebuild_snapshot
from .manifest import load_manifest
from .projector import project
from .reconciliation import reconcile
from .validation import validate_run


SAFE_ACTIONS = {
    "rebuild_snapshot",
    "regenerate_derived_reports",
    "mark_stale_attempt_interrupted",
    "reconnect_existing_evidence",
}


@dataclass(frozen=True)
class RepairPlan:
    actions: list[str]
    findings: list[dict[str, object]]
    dry_run: bool = True

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def plan_repairs(run_dir: Path) -> RepairPlan:
    report = reconcile(run_dir)
    actions = list(
        dict.fromkeys(
            str(item["repair_action"])
            for item in report.findings
            if item.get("repair_action") in SAFE_ACTIONS
        )
    )
    return RepairPlan(actions, report.findings)


def apply_repair(run_dir: Path, action: str, *, details: dict[str, object] | None = None) -> dict[str, object]:
    run_dir = run_dir.expanduser().resolve()
    if action not in SAFE_ACTIONS:
        raise ValueError("unsafe repair action")
    try:
        manifest = load_manifest(run_dir / "run_manifest.json")
    except ValueError as exc:
        if str(exc) == "unsupported_schema":
            raise ValueError("unsupported_schema") from exc
        raise
    before_validation = validate_run(run_dir).as_dict()
    plan = plan_repairs(run_dir)
    if action == "rebuild_snapshot":
        if action not in plan.actions:
            raise ValueError("repair action is not justified by current drift")
        state = rebuild_snapshot(run_dir)
        return {"action": action, "applied": True, "state": state, "validation": validate_run(run_dir).as_dict()}
    if action == "regenerate_derived_reports":
        return {"action": action, "applied": True, "note": "derived reports are regenerated on read"}

    state = project(manifest, read_events(run_dir / "events.jsonl"))
    payload = {
        "action": action,
        "before": details or {"last_event": state.get("last_event")},
        "after": details or {"status": "interrupted" if action == "mark_stale_attempt_interrupted" else "reconnected"},
    }
    kernel = Kernel(run_dir)
    kernel.transition(Transition("repair.applied", payload))
    post = validate_run(run_dir)
    state = project(manifest, read_events(run_dir / "events.jsonl"))
    if not post.passed and state["lifecycle"] == "running":
        kernel.transition(
            Transition(
                "run.status_changed",
                {"from": "running", "to": "blocked", "reason": "repair_post_validation_failed"},
            )
        )
    return {
        "action": action,
        "applied": True,
        "before_validation": before_validation,
        "after_validation": validate_run(run_dir).as_dict(),
    }
