from __future__ import annotations

import json
from pathlib import Path, PurePosixPath

from .autonomy import AutonomyDecision


def decision_event_payload(decision: AutonomyDecision) -> dict[str, object]:
    """Convert one immutable autonomy decision to the durable v4 event shape."""

    if not isinstance(decision, AutonomyDecision):
        raise TypeError("autonomy_decision_required")
    return {
        "decision_id": decision.decision_id,
        "selected_action": decision.selected,
        "alternatives": list(decision.alternatives),
        "basis": decision.basis,
        "confidence": decision.confidence,
        "reversible": decision.reversible,
        "affected_tasks": list(decision.affected_tasks),
        "approval_basis": decision.approval_basis,
        "user_input_required": decision.user_input_required,
    }


def approved_scope_claims(
    run_dir: Path,
    state: dict[str, object],
    task_id: str,
    revision: int,
) -> list[str]:
    """Return a revision-bound, explicitly approved one-attempt scope extension."""

    for artifact in reversed(state.get("artifact_index", [])):
        if artifact.get("task_id") != task_id or artifact.get("kind") != "operator_decision":
            continue
        ref = artifact.get("ref")
        if not isinstance(ref, dict):
            continue
        try:
            payload = json.loads((run_dir / str(ref["path"])).read_text(encoding="utf-8"))
        except (KeyError, OSError, json.JSONDecodeError):
            continue
        claims = payload.get("additional_file_claims")
        if not (
            payload.get("kind") == "operator_decision"
            and payload.get("approved") is True
            and payload.get("scope_override_for_next_revision") is True
            and payload.get("task_id") == task_id
            and payload.get("worktree_revision") == revision
            and isinstance(claims, list)
            and claims
        ):
            continue
        normalized: list[str] = []
        for claim in claims:
            if not isinstance(claim, str) or not claim:
                return []
            path = PurePosixPath(claim)
            if path.is_absolute() or ".." in path.parts:
                return []
            normalized.append(claim)
        return list(dict.fromkeys(normalized))
    return []


def approved_cleanup_claims(
    run_dir: Path,
    state: dict[str, object],
    task_id: str,
    revision: int,
) -> list[str]:
    """Return scope claims that may only remove generated paths."""

    claims = approved_scope_claims(run_dir, state, task_id, revision)
    if not claims:
        return []
    for artifact in reversed(state.get("artifact_index", [])):
        if artifact.get("task_id") != task_id or artifact.get("kind") != "operator_decision":
            continue
        ref = artifact.get("ref")
        if not isinstance(ref, dict):
            continue
        try:
            payload = json.loads((run_dir / str(ref["path"])).read_text(encoding="utf-8"))
        except (KeyError, OSError, json.JSONDecodeError):
            continue
        if payload.get("task_id") != task_id or payload.get("worktree_revision") != revision:
            continue
        return claims if payload.get("cleanup_only_scope_override") is True else []
    return []
