"""test_recovery.py — TDD suite for recovery.py (CME v3.0 T12).

Tests:
  (a) ModuleNotFoundError output → missing_local_env + 1st-occurrence bootstrap + budget NOT burned
  (b) same signature 2nd occurrence → escalate
  (c) assert-failure output → source_failure → implementer_retry + verifier_retries increments
  (d) signature determinism (same input = same hash, different input = different hash)
  (e) negative/vacuous-guard: no command_observation → transitions verifier FAIL path unchanged

__main__ runs ALL defined test functions. sys.exit(1) on any failure.
"""

from __future__ import annotations

import copy
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import recovery
import transitions


# ── shared state fixture ─────────────────────────────────────────────────────

def _base_state(verifier_retries: int = 0, recovery_attempts=None) -> dict:
    """Minimal CME v3 state for one MID-risk task in 'verify' phase."""
    task = {
        "status": "IN_PROGRESS",
        "phase": "verify",
        "review_retries": 0,
        "verifier_retries": verifier_retries,
        "escalations": 0,
        "quality_score": 0.85,
        "timing": {},
    }
    state = {
        "schema_version": 3,
        "status": "RUNNING",
        "current_task": "task_1",
        "current_pre_task_sha": "abc1234",
        "risk_levels": {"task_1": "mid"},
        "execution_plan": [["task_1"]],
        "tasks": {"task_1": task},
        "task_summaries": {},
        "quality_trend": [],
        "cost_ledger": {"totals": {"dispatches": 0}, "by_task": {}},
        "compaction_points": [],
        "last_compaction_after_task": None,
        "last_completed_task": None,
        "recovery_attempts": recovery_attempts if recovery_attempts is not None else [],
    }
    return state


# ── TEST 1: classify ModuleNotFoundError → missing_local_env ─────────────────

def test_classify_module_not_found_error():
    """ModuleNotFoundError in output_tail → category missing_local_env."""
    result = recovery.classify(
        command="python3 -m pytest tests/",
        exit_code=1,
        output_tail="Traceback (most recent call last):\n  ...\nModuleNotFoundError: No module named 'requests'",
    )
    assert result["category"] == "missing_local_env", (
        f"Expected missing_local_env, got {result['category']!r}"
    )
    assert result["evidence"], "evidence must be non-empty"
    print("TEST 1 PASS: classify ModuleNotFoundError → missing_local_env")


# ── TEST 2: classify assert failure → source_failure ─────────────────────────

def test_classify_assert_failure():
    """AssertionError in output → source_failure."""
    result = recovery.classify(
        command="python3 -m pytest tests/test_foo.py",
        exit_code=1,
        output_tail="AssertionError: assert 1 == 2\nFAILED tests/test_foo.py::test_bar",
    )
    assert result["category"] == "source_failure", (
        f"Expected source_failure, got {result['category']!r}"
    )
    assert result["evidence"], "evidence must be non-empty"
    print("TEST 2 PASS: classify AssertionError → source_failure")


# ── TEST 3: first-occurrence env failure → bootstrap, budget NOT burned ───────

def test_first_occurrence_env_bootstrap_no_budget_burn():
    """
    missing_local_env on first occurrence → action=bootstrap, verifier_retries unchanged.
    Passes the observation through transitions.apply_result to confirm budget not burned.
    """
    state = _base_state(verifier_retries=0)
    observation = {
        "command": "python3 -m pytest tests/",
        "exit_code": 1,
        "category": "missing_local_env",
        "evidence": "ModuleNotFoundError: No module named 'requests'",
    }
    decision = recovery.decide_recovery(state, "task_1", observation)
    assert decision["action"] == "bootstrap", (
        f"Expected bootstrap for missing_local_env 1st occurrence, got {decision['action']!r}"
    )
    assert "root_signature" in decision, "root_signature must be in decision"
    assert len(decision["root_signature"]) == 16, (
        f"root_signature must be 16 hex chars, got {decision['root_signature']!r}"
    )

    # Verify transitions does NOT burn verifier_retries when env-family first occurrence
    verifier_payload = {
        "status": "FAIL",
        "issues": [{"description": "ModuleNotFoundError: No module named 'requests'"}],
        "command_observation": observation,
    }
    s2 = transitions.apply_result(state, "task_1", "verifier", verifier_payload)
    assert s2["tasks"]["task_1"].get("verifier_retries", 0) == 0, (
        f"verifier_retries must NOT be burned on env-family first occurrence, "
        f"got {s2['tasks']['task_1'].get('verifier_retries')}"
    )
    print("TEST 3 PASS: env first-occurrence bootstrap, budget not burned")


# ── TEST 4: same signature 2nd occurrence → escalate ─────────────────────────

def test_same_signature_second_occurrence_escalate():
    """Same root_signature on 2nd call → action=escalate."""
    observation = {
        "command": "python3 -m pytest tests/",
        "exit_code": 1,
        "category": "missing_local_env",
        "evidence": "ModuleNotFoundError: No module named 'requests'",
    }
    # Pre-populate recovery_attempts with the same signature
    sig = recovery._root_signature(observation)
    prior_attempts = [{"root_signature": sig, "task_id": "task_1"}]
    state = _base_state(verifier_retries=0, recovery_attempts=prior_attempts)

    decision = recovery.decide_recovery(state, "task_1", observation)
    assert decision["action"] == "escalate", (
        f"Expected escalate on 2nd occurrence of same signature, got {decision['action']!r}"
    )
    assert decision["root_signature"] == sig, (
        "root_signature must be consistent between calls"
    )
    print("TEST 4 PASS: same signature 2nd occurrence → escalate")


# ── TEST 5: source_failure → implementer_retry + verifier_retries increments ──

def test_source_failure_implementer_retry_burns_budget():
    """
    source_failure → action=implementer_retry.
    transitions.apply_result with command_observation of source_failure
    MUST increment verifier_retries (routes to existing FAIL path).
    """
    state = _base_state(verifier_retries=0)
    observation = {
        "command": "python3 -m pytest tests/test_foo.py",
        "exit_code": 1,
        "category": "source_failure",
        "evidence": "AssertionError: assert 1 == 2",
    }
    decision = recovery.decide_recovery(state, "task_1", observation)
    assert decision["action"] == "implementer_retry", (
        f"Expected implementer_retry for source_failure, got {decision['action']!r}"
    )

    # transitions must burn verifier_retries for source_failure
    verifier_payload = {
        "status": "FAIL",
        "issues": [{"description": "AssertionError: assert 1 == 2"}],
        "command_observation": observation,
    }
    s2 = transitions.apply_result(state, "task_1", "verifier", verifier_payload)
    assert s2["tasks"]["task_1"].get("verifier_retries", 0) == 1, (
        f"verifier_retries must be incremented for source_failure, "
        f"got {s2['tasks']['task_1'].get('verifier_retries')}"
    )
    assert s2["tasks"]["task_1"].get("reset_pending") is True, (
        "reset_pending must be set after source_failure"
    )
    print("TEST 5 PASS: source_failure → implementer_retry + verifier_retries incremented")


# ── TEST 6: signature determinism ─────────────────────────────────────────────

def test_signature_determinism():
    """Same input always produces the same 16-char hex signature; different input produces different signature."""
    obs_a = {
        "command": "pytest tests/",
        "exit_code": 1,
        "category": "missing_local_env",
        "evidence": "ModuleNotFoundError: No module named 'numpy'",
    }
    obs_b = {
        "command": "pytest tests/other/",
        "exit_code": 1,
        "category": "source_failure",
        "evidence": "AssertionError: 2 != 3",
    }
    sig_a1 = recovery._root_signature(obs_a)
    sig_a2 = recovery._root_signature(obs_a)
    sig_b = recovery._root_signature(obs_b)

    assert sig_a1 == sig_a2, (
        f"Same input must yield same signature; got {sig_a1!r} vs {sig_a2!r}"
    )
    assert sig_a1 != sig_b, (
        f"Different input must yield different signature; both gave {sig_a1!r}"
    )
    assert len(sig_a1) == 16, f"Signature must be 16 chars, got {len(sig_a1)}"
    assert all(c in "0123456789abcdef" for c in sig_a1), (
        f"Signature must be lowercase hex, got {sig_a1!r}"
    )
    print("TEST 6 PASS: signature determinism")


# ── TEST 7: negative guard — no command_observation → original FAIL path ──────

def test_no_command_observation_uses_original_fail_path():
    """
    Verifier FAIL with NO command_observation → existing transitions path:
    verifier_retries increments (not blocked by recovery).
    Regression guard for transitions TEST 11 / TEST 12.
    """
    state = _base_state(verifier_retries=0)
    verifier_payload = {
        "status": "FAIL",
        "issues": [{"description": "test broke — unrelated to env"}],
        # NO command_observation key
    }
    s2 = transitions.apply_result(state, "task_1", "verifier", verifier_payload)
    assert s2["tasks"]["task_1"].get("verifier_retries", 0) == 1, (
        f"Without command_observation, verifier_retries must increment normally; "
        f"got {s2['tasks']['task_1'].get('verifier_retries')}"
    )
    assert s2["tasks"]["task_1"].get("reset_pending") is True, (
        "reset_pending must be set by original FAIL path"
    )
    print("TEST 7 PASS: no command_observation → original verifier FAIL path unchanged")


# ── TEST 8: unknown category — seam for T14 residual_risk ─────────────────────

def test_unknown_category_records_residual_risk():
    """
    category=unknown appends command to state.residual_risk_commands (T14 seam).
    """
    state = _base_state(verifier_retries=0)
    observation = {
        "command": "make check",
        "exit_code": 2,
        "category": "unknown",
        "evidence": "make: *** [check] Error 2",
    }
    verifier_payload = {
        "status": "FAIL",
        "issues": [],
        "command_observation": observation,
    }
    s2 = transitions.apply_result(state, "task_1", "verifier", verifier_payload)
    residual = s2.get("residual_risk_commands", [])
    assert "make check" in residual, (
        f"unknown category must append command to residual_risk_commands; got {residual!r}"
    )
    print("TEST 8 PASS: unknown category records residual_risk_commands seam for T14")


# ── TEST 9: dependency_bootstrap first occurrence → bootstrap, no budget burn ──

def test_dependency_bootstrap_first_occurrence():
    """dependency_bootstrap on 1st occurrence → action=bootstrap, not burning budget."""
    state = _base_state(verifier_retries=0)
    observation = {
        "command": "npm test",
        "exit_code": 1,
        "category": "dependency_bootstrap",
        "evidence": "node_modules not found; run npm install",
    }
    decision = recovery.decide_recovery(state, "task_1", observation)
    assert decision["action"] == "bootstrap", (
        f"Expected bootstrap for dependency_bootstrap 1st occurrence, got {decision['action']!r}"
    )

    verifier_payload = {
        "status": "FAIL",
        "issues": [],
        "command_observation": observation,
    }
    s2 = transitions.apply_result(state, "task_1", "verifier", verifier_payload)
    assert s2["tasks"]["task_1"].get("verifier_retries", 0) == 0, (
        f"dependency_bootstrap must NOT burn verifier_retries on 1st occurrence"
    )
    print("TEST 9 PASS: dependency_bootstrap 1st occurrence → bootstrap, no budget burn")


# ── TEST 10: apply_result with command_observation is still immutable ─────────

def test_apply_result_with_recovery_is_immutable():
    """apply_result with command_observation must not mutate input state."""
    state = _base_state(verifier_retries=0)
    orig = copy.deepcopy(state)
    observation = {
        "command": "pytest",
        "exit_code": 1,
        "category": "missing_local_env",
        "evidence": "ModuleNotFoundError: No module named 'pytest'",
    }
    verifier_payload = {
        "status": "FAIL",
        "issues": [],
        "command_observation": observation,
    }
    transitions.apply_result(state, "task_1", "verifier", verifier_payload)
    assert state == orig, "apply_result must not mutate input state when command_observation present"
    print("TEST 10 PASS: apply_result with recovery is immutable")


# ── main: run ALL test functions ─────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        test_classify_module_not_found_error,
        test_classify_assert_failure,
        test_first_occurrence_env_bootstrap_no_budget_burn,
        test_same_signature_second_occurrence_escalate,
        test_source_failure_implementer_retry_burns_budget,
        test_signature_determinism,
        test_no_command_observation_uses_original_fail_path,
        test_unknown_category_records_residual_risk,
        test_dependency_bootstrap_first_occurrence,
        test_apply_result_with_recovery_is_immutable,
    ]

    failed = []
    for fn in tests:
        try:
            fn()
        except Exception as exc:
            import traceback
            print(f"FAIL: {fn.__name__}: {exc}")
            traceback.print_exc()
            failed.append(fn.__name__)

    print()
    print(f"Results: {len(tests) - len(failed)}/{len(tests)} passed")
    if failed:
        print(f"FAILED: {failed}")
        sys.exit(1)
    else:
        print("ALL TESTS PASSED")
