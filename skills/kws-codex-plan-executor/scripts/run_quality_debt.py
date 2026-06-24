#!/usr/bin/env python3
from __future__ import annotations

from typing import Any


AGENTLENS_MISSING = "agentlens_missing"
MISSING_EXECUTION_WORKTREE = "missing_execution_worktree"
READINESS_FIXABLE_ISSUES = "readiness_fixable_issues"
PLAN_EXECUTABILITY_FIXABLE_ISSUES = "plan_executability_fixable_issues"
FULL_SPEC_FALLBACK_PRESENT = "full_spec_fallback_present"
DELEGATION_POLICY_PREVENTED_ALL_DELEGATION = "delegation_policy_prevented_all_delegation"

STABLE_FOLLOWUP_ORDER = [
    AGENTLENS_MISSING,
    MISSING_EXECUTION_WORKTREE,
    READINESS_FIXABLE_ISSUES,
    PLAN_EXECUTABILITY_FIXABLE_ISSUES,
    FULL_SPEC_FALLBACK_PRESENT,
    DELEGATION_POLICY_PREVENTED_ALL_DELEGATION,
]

EXECUTION_MODES = {"interactive", "headless"}
SPAWN_POLICY_REASONS = {
    "spawn_agent tool policy requires explicit user delegation intent",
    "spawn_policy_requires_explicit_user_request",
}


def _run_quality(state: dict[str, Any]) -> dict[str, Any]:
    value = state.get("run_quality")
    return value if isinstance(value, dict) else {}


def _count_from_quality(state: dict[str, Any], section: str, key: str) -> int:
    quality = _run_quality(state)
    payload = quality.get(section)
    if not isinstance(payload, dict):
        return 0
    value = payload.get(key)
    return value if isinstance(value, int) and value > 0 else 0


def _plan_executability_fixable_count(state: dict[str, Any]) -> int:
    audit = state.get("plan_executability_audit")
    if not isinstance(audit, dict):
        return 0
    value = audit.get("fixable_issue_count")
    return value if isinstance(value, int) and value > 0 else 0


def _has_execution_agentlens_gap(state: dict[str, Any]) -> bool:
    return (
        state.get("lifecycle_outcome") == "finished"
        and state.get("mode") in EXECUTION_MODES
        and not state.get("agentlens_orchestration_run")
    )


def _dispatch_reason_is_spawn_policy(decision: dict[str, Any]) -> bool:
    reason = decision.get("reason")
    failed = decision.get("failed_prerequisites")
    if isinstance(reason, str) and reason in SPAWN_POLICY_REASONS:
        return True
    return isinstance(failed, list) and "spawn_policy_requires_explicit_user_request" in failed


def _all_dispatches_local_due_to_spawn_policy(state: dict[str, Any]) -> bool:
    if state.get("subagents_requested") is not True:
        return False
    decisions = state.get("dispatch_decisions")
    if not isinstance(decisions, list) or not decisions:
        return False
    saw_local = False
    for decision in decisions:
        if not isinstance(decision, dict):
            return False
        if decision.get("decision") == "delegate":
            return False
        if decision.get("decision") != "local_fallback":
            return False
        if not _dispatch_reason_is_spawn_policy(decision):
            return False
        saw_local = True
    return saw_local


def stable_followups(
    state: dict[str, Any],
    *,
    missing_execution_worktree: bool | None = None,
) -> list[str]:
    found: set[str] = set()
    if _has_execution_agentlens_gap(state):
        found.add(AGENTLENS_MISSING)
    if missing_execution_worktree is True:
        found.add(MISSING_EXECUTION_WORKTREE)
    if _count_from_quality(state, "readiness", "fixable_issue_count") > 0:
        found.add(READINESS_FIXABLE_ISSUES)
    if _plan_executability_fixable_count(state) > 0:
        found.add(PLAN_EXECUTABILITY_FIXABLE_ISSUES)
    if _count_from_quality(state, "context_quality", "full_spec_fallback_count") > 0:
        found.add(FULL_SPEC_FALLBACK_PRESENT)
    if _all_dispatches_local_due_to_spawn_policy(state):
        found.add(DELEGATION_POLICY_PREVENTED_ALL_DELEGATION)
    return [item for item in STABLE_FOLLOWUP_ORDER if item in found]


def operational_debt_summary(
    state: dict[str, Any],
    *,
    missing_execution_worktree: bool | None = None,
) -> dict[str, object]:
    followups = stable_followups(state, missing_execution_worktree=missing_execution_worktree)
    return {
        "schema_version": "1",
        "followups": followups,
        "count": len(followups),
        "blocking": False,
    }


def grade_for(
    state: dict[str, Any],
    followups: list[str],
    validation_status: str | None = None,
) -> str:
    completion = state.get("completion_audit")
    completion_passed = isinstance(completion, dict) and completion.get("passed") is True
    if validation_status == "failed" or not completion_passed:
        return "red"
    return "yellow" if followups else "green"
