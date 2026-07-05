#!/usr/bin/env python3
from __future__ import annotations

from typing import Any


AGENTLENS_MISSING = "agentlens_missing"
MISSING_EXECUTION_WORKTREE = "missing_execution_worktree"
READINESS_FIXABLE_ISSUES = "readiness_fixable_issues"
PLAN_EXECUTABILITY_FIXABLE_ISSUES = "plan_executability_fixable_issues"
FULL_SPEC_FALLBACK_PRESENT = "full_spec_fallback_present"
DELEGATION_POLICY_EXPECTED_LOCAL_FALLBACK = "delegation_policy_expected_local_fallback"
DELEGATION_POLICY_PREVENTED_ALL_DELEGATION = "delegation_policy_prevented_all_delegation"
DELEGATION_POLICY_MISSING_DISPATCH_EVIDENCE = "delegation_policy_missing_dispatch_evidence"

STABLE_FOLLOWUP_ORDER = [
    AGENTLENS_MISSING,
    MISSING_EXECUTION_WORKTREE,
    READINESS_FIXABLE_ISSUES,
    PLAN_EXECUTABILITY_FIXABLE_ISSUES,
    FULL_SPEC_FALLBACK_PRESENT,
    DELEGATION_POLICY_EXPECTED_LOCAL_FALLBACK,
    DELEGATION_POLICY_PREVENTED_ALL_DELEGATION,
    DELEGATION_POLICY_MISSING_DISPATCH_EVIDENCE,
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


def _write_capable_task_ids(state: dict[str, Any]) -> list[str]:
    tasks = state.get("tasks")
    if not isinstance(tasks, dict):
        return []
    result: list[str] = []
    for task_id, task in tasks.items():
        if not isinstance(task, dict):
            continue
        manifest = task.get("unit_manifest") if isinstance(task.get("unit_manifest"), dict) else {}
        if manifest.get("write_capable") is False:
            continue
        if manifest.get("tool_policy") in {None, "implementation", "docs"}:
            result.append(str(task_id))
    return result


def delegation_followup(state: dict[str, Any]) -> str | None:
    dispatches = [item for item in state.get("dispatch_decisions", []) if isinstance(item, dict)]
    capability = state.get("delegation_capability") if isinstance(state.get("delegation_capability"), dict) else {}
    if (
        state.get("lifecycle_outcome") == "finished"
        and state.get("subagents_requested") is True
        and capability.get("spawn_policy") == "explicit-request-required"
        and capability.get("explicit_user_delegation_request") is False
        and capability.get("run_level_effective_mode") == "local_fallback"
    ):
        return DELEGATION_POLICY_EXPECTED_LOCAL_FALLBACK

    if (
        state.get("lifecycle_outcome") == "finished"
        and state.get("subagents_requested") is True
        and _write_capable_task_ids(state)
        and not dispatches
    ):
        return DELEGATION_POLICY_MISSING_DISPATCH_EVIDENCE

    policy = state.get("delegation_policy") if isinstance(state.get("delegation_policy"), dict) else {}
    if (
        _all_dispatches_local_due_to_spawn_policy(state)
        and policy.get("spawn_policy") == "explicit-request-required"
        and policy.get("explicit_user_delegation_request") is False
    ):
        return DELEGATION_POLICY_EXPECTED_LOCAL_FALLBACK

    if _all_dispatches_local_due_to_spawn_policy(state):
        return DELEGATION_POLICY_PREVENTED_ALL_DELEGATION

    return None


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
    delegation = delegation_followup(state)
    if delegation:
        found.add(delegation)
    return [item for item in STABLE_FOLLOWUP_ORDER if item in found]


def _agentlens_followup_is_actionable(state: dict[str, Any]) -> bool:
    status = state.get("agentlens_status")
    if isinstance(status, dict):
        return status.get("status") == "agentlens_emit_failed"
    return False


def _expected_local_fallback_is_informational(state: dict[str, Any]) -> bool:
    capability = state.get("delegation_capability") if isinstance(state.get("delegation_capability"), dict) else {}
    policy = state.get("delegation_policy") if isinstance(state.get("delegation_policy"), dict) else {}
    evidence = capability or policy
    return evidence.get("spawn_policy") == "explicit-request-required" and evidence.get(
        "explicit_user_delegation_request"
    ) is False


def followup_taxonomy(
    state: dict[str, Any],
    followups: list[str],
    *,
    missing_execution_worktree: bool | None = None,
) -> dict[str, object]:
    actionable: list[str] = []
    informational: list[str] = []
    release_blocking: list[str] = []
    terminal = state.get("lifecycle_outcome")
    for item in followups:
        if item == AGENTLENS_MISSING:
            if _agentlens_followup_is_actionable(state):
                actionable.append(item)
            else:
                informational.append(item)
        elif item == DELEGATION_POLICY_EXPECTED_LOCAL_FALLBACK:
            if _expected_local_fallback_is_informational(state):
                informational.append(item)
            else:
                actionable.append(item)
        elif item == MISSING_EXECUTION_WORKTREE:
            if terminal == "finished" and missing_execution_worktree is True:
                informational.append(item)
            else:
                actionable.append(item)
        elif item in {
            READINESS_FIXABLE_ISSUES,
            PLAN_EXECUTABILITY_FIXABLE_ISSUES,
            FULL_SPEC_FALLBACK_PRESENT,
            DELEGATION_POLICY_PREVENTED_ALL_DELEGATION,
            DELEGATION_POLICY_MISSING_DISPATCH_EVIDENCE,
        }:
            actionable.append(item)
        else:
            actionable.append(item)
    return {
        "schema_version": "1",
        "actionable_followups": actionable,
        "informational_followups": informational,
        "release_blocking_followups": release_blocking,
    }


def report_class_for(
    state: dict[str, Any],
    followups: list[str],
    taxonomy: dict[str, object],
    validation_status: str | None = None,
) -> str:
    state_grade = grade_for(state, followups, validation_status)
    if state_grade == "red":
        return "red"
    actionable = taxonomy.get("actionable_followups")
    informational = taxonomy.get("informational_followups")
    if isinstance(actionable, list) and actionable:
        return "yellow"
    if isinstance(informational, list) and informational:
        return "green-with-info"
    return "green"


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
