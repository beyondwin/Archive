from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .evidence import verify_ref
from .events import read_events
from .kernel import Kernel, Transition, rebuild_snapshot
from .manifest import load_verified_manifest
from .projector import RETRY_PHASE_STATES, project
from .reconciliation import reconcile
from .validation import validate_integrity


SAFE_ACTIONS = {
    "rebuild_snapshot",
    "regenerate_derived_reports",
    "mark_stale_attempt_interrupted",
    "reconnect_existing_evidence",
    "resolve_blocker",
    "schedule_retry",
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


def _state(run_dir: Path, manifest: dict) -> dict:
    return project(manifest, read_events(run_dir / "events.jsonl"))


def _canonical(value: object) -> str | None:
    return json.dumps(value, sort_keys=True, separators=(",", ":")) if isinstance(value, dict) else None


def _refs_indexed(state: dict, refs: object) -> bool:
    if not isinstance(refs, list) or not refs or any(not isinstance(ref, dict) for ref in refs):
        return False
    indexed = {
        _canonical(item.get("ref"))
        for item in state.get("artifact_index") or []
        if isinstance(item, dict)
    }
    return all(_canonical(ref) in indexed for ref in refs)


def _derive_delta(action: str, details: dict[str, object], before: dict) -> dict[str, object]:
    if action == "rebuild_snapshot":
        return {"snapshot_matches_replay": True}
    if action == "mark_stale_attempt_interrupted" and isinstance(details.get("attempt_id"), str):
        return {f"attempt_status:{details['attempt_id']}": "interrupted"}
    if action == "resolve_blocker" and isinstance(details.get("blocker_id"), str):
        return {f"blocker_status:{details['blocker_id']}": "resolved"}
    if action == "schedule_retry" and isinstance(details.get("task_id"), str):
        phase = details.get("phase")
        target = RETRY_PHASE_STATES.get(str(phase))
        return {f"task_status:{details['task_id']}": target} if target else {}
    if action == "reconnect_existing_evidence":
        return {"artifact_index_count": len(before.get("artifact_index") or []) + 1}
    return {}


def _list_record(items: object, identity: str) -> object:
    if not isinstance(items, list):
        return None
    keys = ("attempt_id", "blocker_id", "task_id")
    matches = [item for item in items if isinstance(item, dict) and any(item.get(key) == identity for key in keys)]
    return matches[0] if len(matches) == 1 else None


def _path_value(state: dict, path: str) -> object:
    value: object = state
    for part in path.split("."):
        if isinstance(value, dict):
            if part not in value:
                return None
            value = value[part]
        elif isinstance(value, list):
            value = _list_record(value, part)
            if value is None:
                return None
        else:
            return None
    return value


def _observe(run_dir: Path, state: dict, expected: dict[str, object]) -> tuple[bool, dict[str, object]]:
    observed: dict[str, object] = {}
    for path, wanted in expected.items():
        if path == "snapshot_matches_replay":
            try:
                snapshot = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                value: object = False
            else:
                value = snapshot == state
        elif path == "artifact_index_count":
            value = len(state.get("artifact_index") or [])
        elif path.startswith("attempt_status:"):
            record = _list_record(state.get("attempts"), path.removeprefix("attempt_status:"))
            value = record.get("status") if isinstance(record, dict) else None
        elif path.startswith("blocker_status:"):
            record = _list_record(state.get("blocker_history"), path.removeprefix("blocker_status:"))
            value = record.get("status") if isinstance(record, dict) else None
        elif path.startswith("task_status:"):
            task = state.get("tasks", {}).get(path.removeprefix("task_status:"))
            value = task.get("status") if isinstance(task, dict) else None
        else:
            value = _path_value(state, path)
        observed[path] = value
    return observed == expected, observed


def _not_applied(action: str, expected: dict[str, object], observed: dict[str, object] | None = None) -> dict[str, object]:
    return {
        "action": action,
        "applied": False,
        "reason": "expected_projection_delta_not_observed",
        "expected_projection_delta": expected,
        "observed_projection_delta": observed or {},
    }


def apply_repair(
    run_dir: Path,
    action: str,
    *,
    details: dict[str, object] | None = None,
    expected_projection_delta: dict[str, object] | None = None,
) -> dict[str, object]:
    """Apply one compensating action and prove its declared replay projection."""
    run_dir = run_dir.expanduser().resolve()
    if action not in SAFE_ACTIONS:
        raise ValueError("unsafe repair action")
    manifest = load_verified_manifest(run_dir / "run_manifest.json")
    before = _state(run_dir, manifest)
    details = dict(details or {})
    derived = _derive_delta(action, details, before)
    expected = dict(
        derived
        if expected_projection_delta is None
        else expected_projection_delta
    )
    if not expected or any(not isinstance(path, str) or not path for path in expected):
        raise ValueError("expected_projection_delta_required")
    if not derived or expected != derived:
        raise ValueError("expected_projection_delta_mismatch")

    validation = validate_integrity(run_dir)
    allowed = {"snapshot_missing", "snapshot_replay_mismatch"} if action == "rebuild_snapshot" else set()
    if set(validation.errors) - allowed:
        raise ValueError(f"repair_precondition_invalid:{','.join(validation.errors)}")

    kernel = Kernel(run_dir)
    changed = False
    if action == "rebuild_snapshot":
        if action not in plan_repairs(run_dir).actions:
            return _not_applied(action, expected)
        rebuild_snapshot(run_dir)
        changed = True
    elif action == "regenerate_derived_reports":
        return _not_applied(action, expected)
    elif action == "mark_stale_attempt_interrupted":
        attempt_id = details.get("attempt_id")
        matches = [item for item in before.get("attempts") or [] if item.get("attempt_id") == attempt_id and item.get("status") == "started"]
        refs = details.get("evidence_refs") or (matches[0].get("evidence_refs") if len(matches) == 1 else None)
        if len(matches) == 1 and _refs_indexed(before, refs):
            attempt = matches[0]
            kernel.transition(
                Transition(
                    "attempt.completed",
                    {
                        "status": "interrupted",
                        "attestation": {"verified": False, "source": "recovery"},
                        "usage": {},
                        "latency_ms": 0,
                        "evidence_refs": refs,
                    },
                    task_id=attempt.get("task_id"),
                    attempt_id=str(attempt_id),
                )
            )
            changed = True
    elif action == "reconnect_existing_evidence":
        ref = details.get("ref")
        task_id = details.get("task_id")
        attempt_id = details.get("attempt_id")
        already = [_canonical(item.get("ref")) for item in before.get("artifact_index") or [] if isinstance(item, dict)]
        if (
            isinstance(ref, dict)
            and verify_ref(run_dir, ref) == []
            and _canonical(ref) not in already
            and isinstance(task_id, str)
            and task_id in before.get("tasks", {})
        ):
            kernel.transition(
                Transition(
                    "evidence.attached",
                    {"kind": ref.get("kind"), "ref": ref},
                    task_id=task_id,
                    attempt_id=str(attempt_id) if attempt_id is not None else None,
                )
            )
            changed = True
    elif action == "resolve_blocker":
        blocker_id = details.get("blocker_id")
        matches = [item for item in before.get("active_blockers") or [] if item.get("blocker_id") == blocker_id]
        refs = details.get("evidence_refs") or (matches[0].get("evidence_refs") if len(matches) == 1 else None)
        if len(matches) == 1 and _refs_indexed(before, refs):
            blocker = matches[0]
            kernel.transition(
                Transition(
                    "blocker.resolved",
                    {"blocker_id": blocker_id, "evidence_refs": refs, "resolution": "evidence_backed_recovery"},
                    task_id=blocker.get("task_id"),
                )
            )
            changed = True
    elif action == "schedule_retry":
        task_id = details.get("task_id")
        phase = details.get("phase")
        refs = details.get("evidence_refs")
        if (
            isinstance(task_id, str)
            and before.get("tasks", {}).get(task_id, {}).get("status") == "blocked"
            and phase in RETRY_PHASE_STATES
            and not any(item.get("task_id") == task_id for item in before.get("active_blockers") or [])
            and _refs_indexed(before, refs)
        ):
            kernel.transition(
                Transition(
                    "task.retry_scheduled",
                    {
                        "phase": phase,
                        "root_cause_key": str(details.get("root_cause_key") or f"resume:{phase}"),
                        "worktree_revision": before.get("worktree_revision", 0),
                        "evidence_refs": refs,
                    },
                    task_id=task_id,
                )
            )
            changed = True

    after = _state(run_dir, manifest)
    observed_ok, observed = _observe(run_dir, after, expected)
    if not changed or not observed_ok:
        return _not_applied(action, expected, observed)
    kernel.transition(
        Transition(
            "repair.applied",
            {
                "action": action,
                "before": {path: _observe(run_dir, before, {path: value})[1][path] for path, value in expected.items()},
                "after": observed,
                "expected_projection_delta": expected,
                "observed_projection_delta": observed,
                "applied": True,
            },
        )
    )
    return {
        "action": action,
        "applied": True,
        "expected_projection_delta": expected,
        "observed_projection_delta": observed,
        "validation": validate_integrity(run_dir).as_dict(),
    }
