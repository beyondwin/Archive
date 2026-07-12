#!/usr/bin/env python3
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from cpe_runtime.autonomy import (
    Action,
    AutonomyDecision,
    DecisionOption,
    decide,
    needs_user_input,
)
from cpe_runtime.failure_policy import classify_failure, classify_same_root
from cpe_runtime.operator_decisions import decision_event_payload
from cpe_runtime.supervisor import supervise


def assert_raises_text(error_type: type[BaseException], expected: str, callback) -> None:
    try:
        callback()
    except error_type as exc:
        assert str(exc) == expected, (str(exc), expected)
    else:
        raise AssertionError(f"expected {error_type.__name__}: {expected}")


def check_decision_policy() -> object:
    options = (
        DecisionOption(
            action="follow repository pattern",
            basis="repository_pattern",
            confidence="high",
            reversible=True,
            affected_tasks=("T2",),
        ),
        DecisionOption(
            action="honor approved plan",
            basis="approved_documents",
            confidence="high",
            reversible=True,
            affected_tasks=("T2", "T1"),
        ),
        DecisionOption(
            action="minimize external calls",
            basis="execution_economy",
            confidence="medium",
            reversible=True,
            affected_tasks=("T2",),
        ),
    )
    decision = decide(options)
    assert decision.selected == "honor approved plan", decision
    assert decision.alternatives == (
        "follow repository pattern",
        "minimize external calls",
    ), decision
    assert decision.basis == "approved_documents", decision
    assert decision.affected_tasks == ("T1", "T2"), decision
    assert decision.approval_basis == "standing_autonomy_policy", decision
    assert decision.user_input_required is False, decision
    assert len(decision.decision_id) == 64, decision
    assert decision == decide(tuple(reversed(options))), "decision must be order-independent"
    assert "user_approved" not in repr(decision)

    payload = decision_event_payload(decision)
    assert payload == {
        "decision_id": decision.decision_id,
        "selected_action": decision.selected,
        "alternatives": list(decision.alternatives),
        "basis": decision.basis,
        "confidence": decision.confidence,
        "reversible": decision.reversible,
        "affected_tasks": list(decision.affected_tasks),
        "approval_basis": "standing_autonomy_policy",
        "user_input_required": False,
    }, payload

    assert_raises_text(ValueError, "decision_options_required", lambda: decide(()))
    assert_raises_text(
        ValueError,
        "invalid_decision_basis",
        lambda: decide((DecisionOption("guess", "personal_preference"),)),
    )
    assert_raises_text(
        ValueError,
        "invalid_decision_id",
        lambda: AutonomyDecision(
            decision_id="f" * 64,
            selected="forged",
            alternatives=(),
            basis="approved_documents",
            confidence="high",
            reversible=True,
            affected_tasks=(),
            approval_basis="standing_autonomy_policy",
        ),
    )
    return decision


def check_authority_boundary() -> None:
    for action in (
        Action(purchase_or_billing_change=True),
        Action(credentials_or_new_authority=True),
        Action(irreversible_external_action=True),
        Action(remote_push=True),
        Action(protected_branch_merge=True),
        Action(material_product_contract_conflict=True),
        Action(lowers_approved_security_or_privacy=True),
    ):
        assert needs_user_input(action) is True, action

    assert needs_user_input(Action(reversible=True, external=False)) is False
    assert needs_user_input(Action(reversible=True, external=True)) is False
    assert needs_user_input(Action(reversible=False, external=True)) is True
    assert_raises_text(TypeError, "action_required", lambda: needs_user_input(object()))


def check_failure_table() -> None:
    expected = {
        "contract_invalid": "block_dispatch",
        "environment_unavailable": "bootstrap_and_recheck",
        "provider_transient": "wait_external",
        "product_defect": "repair",
        "review_scope_expansion": "backlog_and_continue",
        "static_hardening": "backlog_and_continue",
        "runtime_defect": "pause_for_runtime_upgrade",
        "external_effect_blocked": "wait_external",
        "evidence_integrity_failure": "block_release",
    }
    for category, action in expected.items():
        decision = classify_failure(category, root_cause_key=f"root:{category}")
        assert decision.action == action, decision

    transient = classify_failure("provider_transient", root_cause_key="provider:quota")
    assert transient.preserve_run_id is True, transient
    assert transient.preserve_attempt_id is True, transient
    assert transient.consumes_repair is False, transient

    for count in (0, 1):
        repair = classify_same_root(count, release_impact=False)
        assert repair.action == "repair" and repair.consumes_repair is True, repair
        assert repair.repair_root_update == ("same-root", count + 1), repair
    assert classify_same_root(2, release_impact=False).action == "backlog_and_continue"
    release_block = classify_same_root(2, release_impact=True)
    assert release_block.action == "block_release"
    assert release_block.impact_class == "acceptance_or_approved_product_behavior"
    roots = {"defect:parser": 1}
    roots_before = dict(roots)
    rooted = classify_failure(
        "product_defect",
        root_cause_key="defect:parser",
        repair_roots=roots,
    )
    assert rooted.repair_count == 1, rooted
    assert rooted.repair_root_update == ("defect:parser", 2), rooted
    assert roots == roots_before, "failure classification mutated projected roots"
    assert classify_failure(
        "evidence_integrity_failure",
        root_cause_key="evidence:mixed-run",
        repair_count=0,
    ).action == "block_release"
    assert_raises_text(
        ValueError,
        "unknown_failure_category",
        lambda: classify_failure("model_disagreement", root_cause_key="model:1"),
    )
    assert_raises_text(
        ValueError,
        "invalid_repair_count",
        lambda: classify_same_root(-1, release_impact=False),
    )
    assert_raises_text(
        ValueError,
        "root_cause_key_required",
        lambda: classify_same_root(0, release_impact=False, root_cause_key=""),
    )
    assert_raises_text(
        ValueError,
        "release_impact_not_applicable",
        lambda: classify_failure(
            "review_scope_expansion",
            root_cause_key="review:scope",
            release_impact=True,
        ),
    )


def check_supervision(decision: object) -> None:
    state = {
        "schema_version": "4",
        "run_id": "run-standing-autonomy",
        "lifecycle": "running",
        "tasks": {
            "T1": {"status": "waiting_user", "dependencies": []},
            "T2": {"status": "ready", "dependencies": []},
            "T3": {
                "status": "waiting_external",
                "dependencies": [],
            },
            "T4": {"status": "ready", "dependencies": ["T1"]},
        },
        "attempts": [
            {
                "task_id": "T3",
                "attempt_id": "T3.implementation.1",
                "kind": "implementation",
                "status": "started",
            }
        ],
        "wait_reason": "provider_transient",
        "notifications": [],
    }
    before = deepcopy(state)
    result = supervise(
        state,
        recovered_external_tasks=frozenset({"T3"}),
        decisions=(decision, decision),
    )
    assert state == before, "supervision mutated projected state"
    assert result.run_id == state["run_id"]
    assert [(action.kind, action.task_id) for action in result.actions] == [
        ("schedule_task", "T2"),
        ("resume_external", "T3"),
    ], result
    resumed = result.actions[1]
    assert resumed.run_id == state["run_id"], resumed
    assert resumed.attempt_id == "T3.implementation.1", resumed
    assert resumed.preserve_attempt is True, resumed
    assert all(action.task_id != "T4" for action in result.actions), result
    assert len(result.notifications) == 1, result
    assert result.notifications[0].decision_id == decision.decision_id
    assert result.notifications[0].dedupe_key == decision.decision_id

    notified_state = deepcopy(state)
    notified_state["notifications"] = [
        {"decision_id": decision.decision_id, "dedupe_key": decision.decision_id}
    ]
    repeated = supervise(notified_state, decisions=(decision, decision))
    assert repeated.notifications == (), repeated
    assert all(action.task_id != "T3" for action in repeated.actions), repeated

    user_decision = decide(
        (
            DecisionOption(
                "request remote push approval",
                "approved_documents",
                authority=Action(remote_push=True),
                affected_tasks=("T1",),
            ),
        )
    )
    user_result = supervise(notified_state, decisions=(user_decision, user_decision))
    assert user_decision.user_input_required is True
    assert len(user_result.notifications) == 1
    assert user_result.notifications[0].kind == "user_decision_required"

    assert_raises_text(
        ValueError,
        "unsupported_run_schema",
        lambda: supervise({**state, "schema_version": "3"}),
    )
    invalid = deepcopy(state)
    invalid["tasks"]["T2"]["status"] = "mystery"
    assert_raises_text(ValueError, "invalid_task_status", lambda: supervise(invalid))
    assert_raises_text(
        ValueError,
        "invalid_external_recovery_task",
        lambda: supervise(state, recovered_external_tasks=frozenset({"T99"})),
    )
    assert_raises_text(
        ValueError,
        "invalid_run_lifecycle",
        lambda: supervise({**state, "lifecycle": "mystery"}),
    )


def main() -> int:
    decision = check_decision_policy()
    check_authority_boundary()
    check_failure_table()
    check_supervision(decision)
    print(
        '{"passed": true, "checks": {'
        '"autonomy": true, "authority": true, "failure_policy": true, '
        '"supervision": true, "notification_dedupe": true}}'
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
