from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from .events import read_events
from .manifest import load_manifest
from .projector import RETRY_PHASE_STATES, project
from .validation import ValidationReport, validate_completion, validate_integrity


@dataclass(frozen=True)
class ReconciliationFinding:
    code: str
    severity: str
    message: str
    repair_action: str | None = None


@dataclass(frozen=True)
class ReconciliationReport:
    classification: str
    findings: list[dict[str, object]]

    def as_dict(self) -> dict[str, object]:
        return {"classification": self.classification, "findings": self.findings}


REPAIRABLE = {
    "snapshot_missing": "rebuild_snapshot",
    "snapshot_replay_mismatch": "rebuild_snapshot",
}

RESUME_PHASES = {
    "implementation_interrupted": "implementation",
    "acceptance_failed": "repair",
    "task_review_interrupted": "task_review",
    "task_review_changes_requested": "repair",
    "verification_interrupted": "acceptance",
    "verification_failed": "repair",
    "scope_policy_revalidated": "implementation",
    "scheduled_repair_retry": "repair",
}


@dataclass(frozen=True)
class ResumeDecision:
    action: str
    phase: str | None = None
    blocker_id: str | None = None
    evidence_refs: tuple[dict[str, object], ...] = ()


@dataclass(frozen=True)
class V4ResumeDecision:
    action: str
    task_id: str
    phase: str | None = None
    attempt_id: str | None = None
    checkpoint_head: str | None = None


def select_v4_resume(state: dict, task_id: str) -> V4ResumeDecision:
    """Select same-attempt quota resume or checkpoint-bound runtime resume."""

    if (
        not isinstance(state, dict)
        or state.get("schema_version") != "4"
        or not isinstance(task_id, str)
        or not task_id
    ):
        raise ValueError("invalid_v4_resume_state")
    if state.get("lifecycle") in {"completed", "failed"}:
        return V4ResumeDecision("terminal_noop", task_id)
    tasks = state.get("tasks")
    if not isinstance(tasks, dict) or not isinstance(tasks.get(task_id), dict):
        raise ValueError("invalid_v4_resume_task")
    task = tasks[task_id]
    if task.get("status") == "waiting_user":
        return V4ResumeDecision("await_user_authority", task_id)
    if task.get("status") != "waiting_external":
        return V4ResumeDecision("schedule", task_id)
    phase = task.get("resume_phase")
    if phase not in {"implementation", "repair", "task_review", "verification"}:
        raise ValueError("invalid_v4_resume_phase")
    persisted_attempt = task.get("active_attempt_id")
    active = [
        item
        for item in state.get("attempts", [])
        if isinstance(item, dict)
        and item.get("task_id") == task_id
        and item.get("status") == "started"
    ]
    if len(active) > 1:
        raise ValueError("active_model_attempt_ambiguous")
    if active:
        active_phase = str(active[0].get("kind") or "")
        if active_phase != phase:
            raise ValueError("invalid_v4_resume_phase")
        attempt_id = active[0].get("attempt_id")
        if (
            not isinstance(attempt_id, str)
            or not attempt_id
            or persisted_attempt != attempt_id
        ):
            raise ValueError("invalid_v4_resume_attempt")
        return V4ResumeDecision(
            "resume_same_attempt", task_id, phase=str(phase), attempt_id=attempt_id
        )
    if persisted_attempt is not None:
        raise ValueError("invalid_v4_resume_attempt")
    checkpoint = state.get("checkpoint_head")
    recorded = [
        item
        for item in state.get("verified_checkpoints", [])
        if isinstance(item, dict) and item.get("commit") == checkpoint
    ]
    if (
        isinstance(checkpoint, str)
        and len(checkpoint) == 40
        and all(character in "0123456789abcdef" for character in checkpoint)
        and len(recorded) == 1
    ):
        return V4ResumeDecision(
            "resume_verified_checkpoint",
            task_id,
            phase=str(phase),
            checkpoint_head=checkpoint,
        )
    return V4ResumeDecision("resume_phase", task_id, phase=str(phase))


def _canonical_ref(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    import json

    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _indexed_refs(state: dict, refs: object) -> tuple[dict[str, object], ...] | None:
    if not isinstance(refs, list) or not refs or any(not isinstance(ref, dict) for ref in refs):
        return None
    indexed = {
        _canonical_ref(item.get("ref"))
        for item in state.get("artifact_index") or []
        if isinstance(item, dict)
    }
    canonical = [_canonical_ref(ref) for ref in refs]
    if any(ref is None or ref not in indexed for ref in canonical):
        return None
    return tuple(dict(ref) for ref in refs)


def _resume_category(blocker: dict) -> str | None:
    category = str(blocker.get("category") or "")
    if category in RESUME_PHASES:
        return category
    root = str(blocker.get("root_cause_key") or "")
    if category == "policy_violation" and root.startswith("task_scope:"):
        return "scope_policy_revalidated"
    if root.startswith("implementation:") and "interrupt" in root:
        return "implementation_interrupted"
    if root.startswith("acceptance:"):
        return "acceptance_failed"
    if root.startswith("task_review:") and "interrupt" in root:
        return "task_review_interrupted"
    if root.startswith("task_review:") and "changes_requested" in root:
        return "task_review_changes_requested"
    if root.startswith("verification:"):
        return "verification_interrupted" if "interrupt" in root else "verification_failed"
    if root == "scheduled_retry:repair" or root.startswith(
        "repair:repair_did_not_advance_revision:"
    ):
        return "scheduled_repair_retry"
    return None


def _legacy_transient_phase(state: dict, blocker: dict) -> str | None:
    if blocker.get("category") != "transient":
        return None
    task_id = blocker.get("task_id")
    phases = {
        "implementation": "implementation",
        "task_review": "task_review",
        "verification": "acceptance",
        "repair": "repair",
    }
    for attempt in reversed(list(state.get("attempts") or [])):
        if (
            isinstance(attempt, dict)
            and attempt.get("task_id") == task_id
            and attempt.get("status") == "failed"
            and attempt.get("kind") in phases
        ):
            return phases[str(attempt["kind"])]
    return None


def select_resume(state: dict, integrity_report: ValidationReport) -> ResumeDecision:
    """Choose one deterministic resume action from replayed, integrity-valid state."""
    if not isinstance(state, dict) or not integrity_report.passed:
        errors = set(getattr(integrity_report, "errors", ()) or ())
        if errors == {"worktree_missing"}:
            return ResumeDecision("open_workspace_blocker")
        return ResumeDecision("reject")
    if state.get("lifecycle") == "completed":
        return ResumeDecision("complete")

    blockers = list(state.get("active_blockers") or [])
    if len(blockers) > 1:
        return ResumeDecision("reject")
    if blockers:
        blocker = blockers[0]
        if not isinstance(blocker, dict):
            return ResumeDecision("reject")
        if blocker.get("owner") == "operator" or blocker.get("category") == "operator_review":
            return ResumeDecision("remain_blocked", blocker_id=str(blocker.get("blocker_id") or "") or None)
        refs = _indexed_refs(state, blocker.get("evidence_refs"))
        category = _resume_category(blocker)
        blocker_id = blocker.get("blocker_id")
        phase = RESUME_PHASES[category] if category is not None else _legacy_transient_phase(state, blocker)
        if refs is None or phase is None or not isinstance(blocker_id, str) or not blocker_id:
            return ResumeDecision("reject")
        return ResumeDecision("retry", phase, blocker_id, refs)

    active = [
        item
        for item in state.get("attempts") or []
        if isinstance(item, dict) and item.get("status") == "started"
    ]
    if len(active) == 1:
        attempt = active[0]
        matching_refs = [
            item.get("ref")
            for item in state.get("artifact_index") or []
            if isinstance(item, dict)
            and item.get("attempt_id") == attempt.get("attempt_id")
            and isinstance(item.get("ref"), dict)
        ]
        refs = _indexed_refs(state, matching_refs) if matching_refs else ()
        phase = {
            "implementation": "implementation",
            "repair": "repair",
            "verification": "acceptance",
        }.get(str(attempt.get("kind")))
        return ResumeDecision("retry", phase, None, refs) if phase else ResumeDecision("reject")
    current_task = state.get("current_task")
    for queued in reversed(list(state.get("retry_queue") or [])):
        if not isinstance(queued, dict) or queued.get("task_id") != current_task:
            continue
        phase = str(queued.get("phase") or "")
        refs = _indexed_refs(state, queued.get("evidence_refs"))
        expected = RETRY_PHASE_STATES.get(phase)
        if (
            isinstance(current_task, str)
            and expected is not None
            and state.get("tasks", {}).get(current_task, {}).get("status") == expected
            and refs is not None
        ):
            return ResumeDecision("continue", phase, None, refs)
        return ResumeDecision("reject")
    return ResumeDecision("reject")


def reconcile(run_dir: Path, *, completion: bool = False) -> ReconciliationReport:
    """Classify canonical findings without treating healthy incompletion as drift.

    Recovery planning uses the default lifecycle adapter. Completion callers may
    request the strict profile before a terminal event exists.
    """
    integrity = validate_integrity(run_dir)
    report = validate_completion(run_dir) if completion else integrity
    if not completion and integrity.passed:
        try:
            manifest = load_manifest(run_dir / "run_manifest.json")
            replay = project(manifest, read_events(run_dir / "events.jsonl"))
        except (OSError, TypeError, ValueError):
            replay = None
        if isinstance(replay, dict) and replay.get("lifecycle") == "completed":
            report = validate_completion(run_dir)
    if report.classification == "unsupported_schema":
        return ReconciliationReport(
            "blocking_drift",
            [asdict(ReconciliationFinding("unsupported_schema", "blocking", "v2 state is unsupported and immutable"))],
        )
    findings: list[dict[str, object]] = []
    for code in report.errors:
        action = REPAIRABLE.get(code)
        findings.append(
            asdict(
                ReconciliationFinding(
                    code,
                    "repairable" if action else "blocking",
                    code.replace("_", " "),
                    action,
                )
            )
        )
    if not findings:
        try:
            manifest = load_manifest(run_dir / "run_manifest.json")
            state = project(manifest, read_events(run_dir / "events.jsonl"))
        except (OSError, TypeError, ValueError):
            classification = "blocking_drift"
        else:
            classification = "clean" if state.get("lifecycle") == "completed" else "clean_incomplete"
    elif all(item["severity"] == "repairable" for item in findings):
        classification = "repairable"
    else:
        classification = "blocking_drift"
    return ReconciliationReport(classification, findings)
