"""test_transitions.py — TDD suite for transitions.py (CME v3.0 T6).

Minimum 10 test functions; __main__ runs ALL of them.
Each test function ends with either assert/raise or print(OK indicator).
"""

import copy
import sys

import transitions


# ── shared fixture helpers ───────────────────────────────────────────────────

def _state_one_task(risk="mid", phase="implement", review_retries=0,
                    verifier_retries=0, escalations=0, quality_score=None,
                    quality_trend=None):
    task = {
        "status": "IN_PROGRESS",
        "phase": phase,
        "review_retries": review_retries,
        "verifier_retries": verifier_retries,
        "escalations": escalations,
        "timing": {},
    }
    if quality_score is not None:
        task["quality_score"] = quality_score
    return {
        "schema_version": 3,
        "status": "RUNNING",
        "current_task": "task_1",
        "current_pre_task_sha": "abc1234",
        "risk_levels": {"task_1": risk},
        "execution_plan": [["task_1"]],
        "tasks": {"task_1": task},
        "task_summaries": {},
        "quality_trend": quality_trend if quality_trend is not None else [],
        "cost_ledger": {"totals": {"dispatches": 0}, "by_task": {}},
        "compaction_points": [],
        "last_compaction_after_task": None,
        "last_completed_task": None,
    }


# ── TEST 1: implementer DONE → phase "review" ────────────────────────────────

def test_implementer_done_moves_to_review():
    s = _state_one_task()
    s2 = transitions.apply_result(
        s, "task_1", "implementer",
        {"status": "DONE", "summary": "x", "files_changed": ["a.py"],
         "files_test_changed": ["test_a.py"], "commit": "abc"},
    )
    assert s2["tasks"]["task_1"]["phase"] == "review", (
        f"Expected phase='review', got {s2['tasks']['task_1']['phase']!r}"
    )
    print("TEST 1 PASS: implementer DONE → phase review")


# ── TEST 2: implementer ESCALATE increments counter; >3 → SKIPPED ───────────

def test_implementer_escalate_cap():
    # First three ESCALATE calls should NOT mark SKIPPED.
    for count in range(1, 4):
        s = _state_one_task(escalations=count - 1)
        s2 = transitions.apply_result(
            s, "task_1", "implementer",
            {"status": "ESCALATE", "summary": "blocked",
             "files_changed": [], "files_test_changed": [],
             "escalate": {"type": "AMBIGUITY", "question": "?"}},
        )
        assert s2["tasks"]["task_1"]["escalations"] == count, (
            f"Expected escalations={count}, got "
            f"{s2['tasks']['task_1']['escalations']}"
        )
        assert s2["tasks"]["task_1"]["status"] != "SKIPPED", (
            f"escalation {count} should not SKIP"
        )

    # Escalation 4 (>3) → SKIPPED.
    s = _state_one_task(escalations=3)
    s2 = transitions.apply_result(
        s, "task_1", "implementer",
        {"status": "ESCALATE", "summary": "blocked",
         "files_changed": [], "files_test_changed": [],
         "escalate": {"type": "AMBIGUITY", "question": "?"}},
    )
    assert s2["tasks"]["task_1"]["status"] == "SKIPPED", (
        f"Expected SKIPPED after 4th escalation, got "
        f"{s2['tasks']['task_1']['status']!r}"
    )
    print("TEST 2 PASS: implementer ESCALATE counter; cap at >3 → SKIPPED")


# ── TEST 3: review FAIL burns retry; >3 → SKIPPED + verification_gaps ────────

def test_review_fail_burns_retry_then_skip():
    # review_retries=3 already consumed → next FAIL → SKIPPED
    s = _state_one_task(phase="review", review_retries=3)
    s2 = transitions.apply_result(
        s, "task_1", "reviewer",
        {"status": "FAIL", "spec_score": 0.5, "quality_score": 0.5, "issues": []},
    )
    assert s2["tasks"]["task_1"]["status"] == "SKIPPED", (
        f"Expected SKIPPED after review_retries>3, got "
        f"{s2['tasks']['task_1']['status']!r}"
    )
    assert "verification_gaps" in s2, (
        "Expected verification_gaps in state after SKIP"
    )
    print("TEST 3 PASS: review FAIL >3 → SKIPPED + verification_gaps")


# ── TEST 4: review WARN tier → no retry burned, forwards to verify ───────────

def test_warn_tier_proceeds_without_retry():
    # Scores in WARN band: spec≥0.70 AND quality≥0.60 but not both in PASS band
    s = _state_one_task(phase="review")
    s2 = transitions.apply_result(
        s, "task_1", "reviewer",
        {"status": "WARN", "spec_score": 0.72, "quality_score": 0.65,
         "issues": []},
    )
    assert s2["tasks"]["task_1"]["review_retries"] == 0, (
        "WARN must NOT burn a review retry"
    )
    # MID risk + WARN → should proceed to verify phase (not PENDING_BATCH)
    assert s2["tasks"]["task_1"]["phase"] == "verify", (
        f"Expected phase='verify' for MID risk WARN, got "
        f"{s2['tasks']['task_1']['phase']!r}"
    )
    print("TEST 4 PASS: review WARN tier → no retry, proceeds to verify")


# ── TEST 5: review LOW risk PASS → PENDING_BATCH ─────────────────────────────

def test_low_risk_pass_goes_pending_batch():
    s = _state_one_task(risk="low", phase="review")
    s2 = transitions.apply_result(
        s, "task_1", "reviewer",
        {"status": "PASS", "spec_score": 0.9, "quality_score": 0.8, "issues": []},
    )
    assert s2["tasks"]["task_1"]["status"] == "PENDING_BATCH", (
        f"Expected PENDING_BATCH for LOW risk PASS, got "
        f"{s2['tasks']['task_1']['status']!r}"
    )
    print("TEST 5 PASS: LOW risk review PASS → PENDING_BATCH")


# ── TEST 6: review LOW risk WARN → PENDING_BATCH (mirrors PASS for LOW) ──────

def test_low_risk_warn_goes_pending_batch():
    """LOW tasks skip per-task Verifier; WARN or PASS both land in PENDING_BATCH."""
    s = _state_one_task(risk="low", phase="review")
    s2 = transitions.apply_result(
        s, "task_1", "reviewer",
        {"status": "WARN", "spec_score": 0.72, "quality_score": 0.63,
         "issues": []},
    )
    assert s2["tasks"]["task_1"]["status"] == "PENDING_BATCH", (
        f"Expected PENDING_BATCH for LOW risk WARN, got "
        f"{s2['tasks']['task_1']['status']!r}"
    )
    # Retry budget not burned
    assert s2["tasks"]["task_1"]["review_retries"] == 0
    print("TEST 6 PASS: LOW risk review WARN → PENDING_BATCH, no retry burned")


# ── TEST 7: review MID risk PASS → phase "verify" ────────────────────────────

def test_mid_risk_pass_goes_verify():
    s = _state_one_task(risk="mid", phase="review")
    s2 = transitions.apply_result(
        s, "task_1", "reviewer",
        {"status": "PASS", "spec_score": 0.9, "quality_score": 0.8, "issues": []},
    )
    assert s2["tasks"]["task_1"]["phase"] == "verify", (
        f"Expected phase='verify' for MID risk PASS, got "
        f"{s2['tasks']['task_1']['phase']!r}"
    )
    print("TEST 7 PASS: MID risk review PASS → phase verify")


# ── TEST 8: SPEC_FAULT budget (non-burning; >3 → escalate_to_user) ───────────

def test_spec_fault_budget_non_burning():
    """SPEC_FAULT increments spec_clarifications, NOT review_retries.
    spec_clarifications > 3 → escalate_to_user recorded in state."""
    # First 3 SPEC_FAULT calls: spec_clarifications increments; review_retries stays 0
    for count in range(1, 4):
        s = _state_one_task(phase="review")
        s["tasks"]["task_1"]["spec_clarifications"] = count - 1
        s2 = transitions.apply_result(
            s, "task_1", "reviewer",
            {"status": "FAIL", "spec_score": 0.4, "quality_score": 0.5,
             "issues": [],
             "spec_fault": "spec_contradicts"},
        )
        assert s2["tasks"]["task_1"].get("spec_clarifications", 0) == count, (
            f"Expected spec_clarifications={count}"
        )
        assert s2["tasks"]["task_1"].get("review_retries", 0) == 0, (
            "SPEC_FAULT must NOT increment review_retries"
        )

    # 4th SPEC_FAULT (>3) → escalate_to_user
    s = _state_one_task(phase="review")
    s["tasks"]["task_1"]["spec_clarifications"] = 3
    s2 = transitions.apply_result(
        s, "task_1", "reviewer",
        {"status": "FAIL", "spec_score": 0.4, "quality_score": 0.5,
         "issues": [],
         "spec_fault": "spec_contradicts"},
    )
    # State records pending escalation AND marks the task SKIPPED (both, per the
    # apply_result contract) — assert both so a regression dropping either fails.
    assert s2.get("pending_escalation") is not None, (
        "After spec_clarifications>3, state must record pending_escalation"
    )
    assert s2["pending_escalation"].get("task_id") == "task_1"
    assert s2["tasks"]["task_1"]["status"] == "SKIPPED", (
        "After spec_clarifications>3, task must be SKIPPED"
    )
    assert s2["tasks"]["task_1"].get("skip_reason") == "spec_clarifications_exhausted"
    print("TEST 8 PASS: SPEC_FAULT non-burning budget; >3 → escalation signal")


# ── TEST 9: verifier PASS → COMPLETE + last_completed_task + quality_trend ───

def test_verifier_pass_complete_quality_trend():
    s = _state_one_task(risk="mid", phase="verify", quality_score=0.82)
    s2 = transitions.apply_result(
        s, "task_1", "verifier",
        {"status": "PASS", "commands_run": ["pytest"], "exit_codes": [0]},
    )
    assert s2["tasks"]["task_1"]["status"] == "COMPLETE", (
        f"Expected COMPLETE, got {s2['tasks']['task_1']['status']!r}"
    )
    assert s2.get("last_completed_task") == "task_1", (
        "Expected last_completed_task='task_1'"
    )
    assert len(s2.get("quality_trend", [])) == 1, (
        "Expected quality_trend to have 1 entry"
    )
    assert s2["quality_trend"][0] == 0.82
    print("TEST 9 PASS: verifier PASS → COMPLETE + last_completed_task + quality_trend")


# ── TEST 10: quality_trend rolling max 10 ────────────────────────────────────

def test_quality_trend_rolling_max_10():
    """quality_trend is capped at 10 entries (drop oldest)."""
    existing = [0.80] * 10
    s = _state_one_task(risk="mid", phase="verify", quality_score=0.75,
                        quality_trend=existing)
    s2 = transitions.apply_result(
        s, "task_1", "verifier",
        {"status": "PASS", "commands_run": ["pytest"], "exit_codes": [0]},
    )
    trend = s2.get("quality_trend", [])
    assert len(trend) == 10, f"Expected trend len=10, got {len(trend)}"
    assert trend[-1] == 0.75, f"Expected newest entry 0.75, got {trend[-1]}"
    print("TEST 10 PASS: quality_trend rolling max 10")


# ── TEST 11: verifier FAIL → verifier_retries+1 + reset directive ────────────

def test_verifier_fail_reset_directive():
    s = _state_one_task(risk="mid", phase="verify", quality_score=0.8)
    s["current_pre_task_sha"] = "dead1234"
    s2 = transitions.apply_result(
        s, "task_1", "verifier",
        {"status": "FAIL", "issues": [{"description": "test broke"}]},
    )
    assert s2["tasks"]["task_1"]["verifier_retries"] == 1, (
        f"Expected verifier_retries=1, got "
        f"{s2['tasks']['task_1'].get('verifier_retries')}"
    )
    # The reset SHA must be recorded somewhere accessible to decide()
    assert s2.get("current_pre_task_sha") == "dead1234", (
        "current_pre_task_sha must be preserved for reset"
    )
    assert s2["tasks"]["task_1"].get("reset_pending") is True, (
        "reset_pending flag must be set after verifier FAIL"
    )
    print("TEST 11 PASS: verifier FAIL → retries+1 + reset_pending flag")


# ── TEST 12: verifier FAIL >3 → reset + SKIPPED + verification_gaps ──────────

def test_verifier_fail_over_budget_skip():
    s = _state_one_task(risk="mid", phase="verify", quality_score=0.8,
                        verifier_retries=3)
    s["current_pre_task_sha"] = "dead1234"
    s2 = transitions.apply_result(
        s, "task_1", "verifier",
        {"status": "FAIL", "issues": [{"description": "test broke"}]},
    )
    assert s2["tasks"]["task_1"]["status"] == "SKIPPED", (
        f"Expected SKIPPED after verifier_retries>3, got "
        f"{s2['tasks']['task_1']['status']!r}"
    )
    assert "verification_gaps" in s2, "Expected verification_gaps in state"
    # Even when skipping, reset_pending must be set (git reset still needed)
    assert s2["tasks"]["task_1"].get("reset_pending") is True, (
        "reset_pending must be set even on verifier-retries-exhausted SKIP"
    )
    print("TEST 12 PASS: verifier FAIL >3 → SKIPPED + verification_gaps + reset_pending")


# ── TEST 13: all terminal → decide returns finalize ──────────────────────────

def test_all_terminal_decides_finalize():
    s = _state_one_task()
    s["tasks"]["task_1"].update(status="COMPLETE", phase=None)
    action = transitions.decide(s)
    assert action["action"] == "finalize", (
        f"Expected action='finalize', got {action!r}"
    )
    print("TEST 13 PASS: all tasks terminal → decide returns finalize")


# ── TEST 14: decide dispatch increments attempt number ───────────────────────

def test_decide_dispatch_increments_attempt():
    """decide() for a task that needs implementing returns dispatch with attempt."""
    s = _state_one_task(phase="implement")
    action = transitions.decide(s)
    assert action["action"] == "dispatch", (
        f"Expected dispatch, got {action!r}"
    )
    assert action["task_id"] == "task_1"
    assert action["role"] == "implementer"
    assert isinstance(action["attempt"], int) and action["attempt"] >= 1, (
        f"Expected attempt >= 1, got {action.get('attempt')}"
    )
    print("TEST 14 PASS: decide dispatch returns task_id + role + attempt")


# ── TEST 15: compaction trigger → decide returns compact ─────────────────────

def test_compact_trigger():
    """When active.compaction_points matches current task, decide returns compact."""
    s = _state_one_task()
    s["tasks"]["task_1"].update(status="COMPLETE", phase=None)
    # Add a second task already done, plus mark task_1 as a compaction point
    s["tasks"]["task_2"] = {
        "status": "IN_PROGRESS", "phase": "implement",
        "review_retries": 0, "verifier_retries": 0,
        "escalations": 0, "timing": {},
    }
    s["risk_levels"]["task_2"] = "mid"
    s["execution_plan"] = [["task_1"], ["task_2"]]
    s["current_task"] = "task_1"
    s["last_completed_task"] = "task_1"    # apply_result sets this on verifier PASS
    s["compaction_points"] = ["task_1"]   # task_1 is a compaction point
    s["last_compaction_after_task"] = None  # haven't compacted yet
    # Decide on state where task_1 just completed and is a compaction point
    # and task_2 needs dispatch
    action = transitions.decide(s)
    assert action["action"] == "compact", (
        f"Expected compact action, got {action!r}"
    )
    assert "steps" in action, "compact action must include steps field"
    assert len(action["steps"]) > 0
    print("TEST 15 PASS: compaction point triggers compact action with steps")


# ── TEST 16: apply_result is immutable (original state unchanged) ─────────────

def test_apply_result_immutable():
    """apply_result must not mutate the input state."""
    s = _state_one_task()
    orig = copy.deepcopy(s)
    transitions.apply_result(
        s, "task_1", "implementer",
        {"status": "DONE", "summary": "x", "files_changed": ["a.py"],
         "files_test_changed": [], "commit": "abc"},
    )
    assert s == orig, "apply_result must not mutate the input state dict"
    print("TEST 16 PASS: apply_result is immutable")


# ── TEST 17: record_timing stamps event on state ─────────────────────────────

def test_record_timing():
    s = _state_one_task()
    s2 = transitions.record_timing(s, "task_1", "started", "2026-07-06T10:00:00Z")
    assert s2["tasks"]["task_1"]["timing"]["started"] == "2026-07-06T10:00:00Z", (
        "record_timing must stamp timing.started"
    )
    # record_timing is also immutable
    assert "started" not in s["tasks"]["task_1"]["timing"], (
        "record_timing must not mutate original state"
    )
    s3 = transitions.record_timing(s2, "task_1", "completed", "2026-07-06T11:00:00Z")
    assert s3["tasks"]["task_1"]["timing"]["completed"] == "2026-07-06T11:00:00Z"
    print("TEST 17 PASS: record_timing stamps events correctly and is immutable")


# ── TEST 18: review FAIL increments retry then re-dispatches (not skip) ──────

def test_review_fail_increments_retry_under_budget():
    """review_retries=1 on FAIL → increments to 2, task stays in review phase."""
    s = _state_one_task(phase="review", review_retries=1)
    s2 = transitions.apply_result(
        s, "task_1", "reviewer",
        {"status": "FAIL", "spec_score": 0.5, "quality_score": 0.5, "issues": []},
    )
    assert s2["tasks"]["task_1"]["review_retries"] == 2, (
        f"Expected review_retries=2, got "
        f"{s2['tasks']['task_1'].get('review_retries')}"
    )
    assert s2["tasks"]["task_1"]["status"] != "SKIPPED", (
        "review_retries=2 is still within budget, must not SKIP"
    )
    print("TEST 18 PASS: review FAIL under budget → increments retry, no SKIP")


# ── TEST 19: decide returns batch-verify when only PENDING_BATCH tasks remain ──

def test_decide_batch_verify_when_only_pending_batch():
    """decide returns batch-verify action when all non-PENDING_BATCH tasks are
    terminal and ≥1 PENDING_BATCH task remains.

    A state with task_1=COMPLETE and task_2=PENDING_BATCH should return a
    dispatch action with batch=True and task_ids=[task_2], NOT finalize.
    """
    s = {
        "schema_version": 3,
        "status": "RUNNING",
        "current_task": "task_2",
        "current_pre_task_sha": "abc1234",
        "risk_levels": {"task_1": "mid", "task_2": "low"},
        "execution_plan": [["task_1"], ["task_2"]],
        "tasks": {
            "task_1": {
                "status": "COMPLETE",
                "phase": None,
                "review_retries": 0,
                "verifier_retries": 0,
                "escalations": 0,
                "timing": {},
            },
            "task_2": {
                "status": "PENDING_BATCH",
                "phase": None,
                "review_retries": 0,
                "verifier_retries": 0,
                "escalations": 0,
                "timing": {},
            },
        },
        "task_summaries": {},
        "quality_trend": [],
        "cost_ledger": {"totals": {"dispatches": 0}, "by_task": {}},
        "compaction_points": [],
        "last_compaction_after_task": None,
        "last_completed_task": "task_1",
    }
    action = transitions.decide(s)
    assert action.get("action") == "dispatch", (
        f"Expected action=dispatch for batch-verify, got {action!r}"
    )
    assert action.get("batch") is True, (
        f"Expected batch=True in batch-verify action, got {action!r}"
    )
    assert "task_ids" in action, (
        f"Expected task_ids in batch-verify action, got {action!r}"
    )
    assert "task_2" in action["task_ids"], (
        f"Expected task_2 in task_ids, got {action['task_ids']!r}"
    )
    assert action.get("role") == "verifier", (
        f"Expected role=verifier for batch-verify, got {action.get('role')!r}"
    )
    print("TEST 19 PASS: decide returns batch-verify dispatch when only PENDING_BATCH remains")


# ── TEST 20: decide returns finalize only when zero PENDING_BATCH remain ──────

def test_decide_finalize_only_when_no_pending_batch():
    """decide returns finalize ONLY when all tasks are COMPLETE or SKIPPED (no
    PENDING_BATCH). A state with all tasks COMPLETE and no PENDING_BATCH must
    return finalize.
    """
    s = {
        "schema_version": 3,
        "status": "RUNNING",
        "current_task": None,
        "current_pre_task_sha": "abc1234",
        "risk_levels": {"task_1": "mid", "task_2": "low"},
        "execution_plan": [["task_1"], ["task_2"]],
        "tasks": {
            "task_1": {
                "status": "COMPLETE",
                "phase": None,
                "review_retries": 0,
                "verifier_retries": 0,
                "escalations": 0,
                "timing": {},
            },
            "task_2": {
                "status": "COMPLETE",
                "phase": None,
                "review_retries": 0,
                "verifier_retries": 0,
                "escalations": 0,
                "timing": {},
            },
        },
        "task_summaries": {},
        "quality_trend": [],
        "cost_ledger": {"totals": {"dispatches": 0}, "by_task": {}},
        "compaction_points": [],
        "last_compaction_after_task": None,
        "last_completed_task": "task_2",
    }
    action = transitions.decide(s)
    assert action.get("action") == "finalize", (
        f"Expected finalize when no PENDING_BATCH tasks remain, got {action!r}"
    )
    print("TEST 20 PASS: decide returns finalize only when zero PENDING_BATCH remain")


# ── TEST 21: apply_result batch PASS → PENDING_BATCH → COMPLETE + quality_trend ─

def test_apply_result_batch_pass_completes_task():
    """apply_result with role=verifier on a PENDING_BATCH task with PASS status
    drives that task PENDING_BATCH → COMPLETE, updates last_completed_task, and
    appends to quality_trend.
    """
    s = {
        "schema_version": 3,
        "status": "RUNNING",
        "current_task": "task_1",
        "current_pre_task_sha": "abc1234",
        "risk_levels": {"task_1": "low"},
        "execution_plan": [["task_1"]],
        "tasks": {
            "task_1": {
                "status": "PENDING_BATCH",
                "phase": None,
                "review_retries": 0,
                "verifier_retries": 0,
                "escalations": 0,
                "quality_score": 0.88,  # set by reviewer step earlier
                "timing": {},
            },
        },
        "task_summaries": {},
        "quality_trend": [],
        "cost_ledger": {"totals": {"dispatches": 0}, "by_task": {}},
        "compaction_points": [],
        "last_compaction_after_task": None,
        "last_completed_task": None,
    }
    s2 = transitions.apply_result(
        s, "task_1", "verifier",
        {"status": "PASS", "commands_run": ["pytest"], "exit_codes": [0]},
    )
    assert s2["tasks"]["task_1"]["status"] == "COMPLETE", (
        f"Expected PENDING_BATCH → COMPLETE on batch PASS, got "
        f"{s2['tasks']['task_1']['status']!r}"
    )
    assert s2.get("last_completed_task") == "task_1", (
        f"Expected last_completed_task='task_1', got {s2.get('last_completed_task')!r}"
    )
    trend = s2.get("quality_trend", [])
    assert len(trend) == 1, f"Expected quality_trend length 1, got {len(trend)}"
    assert trend[0] == 0.88, f"Expected quality_trend[0]=0.88, got {trend[0]}"
    print("TEST 21 PASS: apply_result batch PASS drives PENDING_BATCH → COMPLETE + quality_trend")


# ── TEST 22: apply_result batch FAIL → PENDING_BATCH → SKIPPED + verification_gaps

def test_apply_result_batch_fail_skips_task():
    """apply_result with role=verifier on a PENDING_BATCH task with FAIL status
    drives that task → SKIPPED and appends to verification_gaps. LOW tasks get
    no per-task retry here (batch verification failure is a gap, run continues).
    """
    s = {
        "schema_version": 3,
        "status": "RUNNING",
        "current_task": "task_1",
        "current_pre_task_sha": "abc1234",
        "risk_levels": {"task_1": "low"},
        "execution_plan": [["task_1"]],
        "tasks": {
            "task_1": {
                "status": "PENDING_BATCH",
                "phase": None,
                "review_retries": 0,
                "verifier_retries": 0,
                "escalations": 0,
                "quality_score": 0.75,
                "timing": {},
            },
        },
        "task_summaries": {},
        "quality_trend": [],
        "cost_ledger": {"totals": {"dispatches": 0}, "by_task": {}},
        "compaction_points": [],
        "last_compaction_after_task": None,
        "last_completed_task": None,
    }
    s2 = transitions.apply_result(
        s, "task_1", "verifier",
        {"status": "FAIL", "issues": [{"description": "batch test failed"}]},
    )
    assert s2["tasks"]["task_1"]["status"] == "SKIPPED", (
        f"Expected PENDING_BATCH → SKIPPED on batch FAIL, got "
        f"{s2['tasks']['task_1']['status']!r}"
    )
    gaps = s2.get("verification_gaps", [])
    assert len(gaps) >= 1, f"Expected at least 1 verification_gap on batch FAIL, got {gaps!r}"
    gap = gaps[0]
    assert gap.get("task") == "task_1", f"Expected gap task=task_1, got {gap!r}"
    assert gap.get("kind") == "batch_verify", (
        f"Expected gap kind=batch_verify for LOW batch failure, got {gap.get('kind')!r}"
    )
    # Immutability: original state unchanged
    assert s["tasks"]["task_1"]["status"] == "PENDING_BATCH", (
        "apply_result must not mutate original state"
    )
    print("TEST 22 PASS: apply_result batch FAIL drives PENDING_BATCH → SKIPPED + verification_gaps")


# ── main: run ALL test functions ─────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        test_implementer_done_moves_to_review,
        test_implementer_escalate_cap,
        test_review_fail_burns_retry_then_skip,
        test_warn_tier_proceeds_without_retry,
        test_low_risk_pass_goes_pending_batch,
        test_low_risk_warn_goes_pending_batch,
        test_mid_risk_pass_goes_verify,
        test_spec_fault_budget_non_burning,
        test_verifier_pass_complete_quality_trend,
        test_quality_trend_rolling_max_10,
        test_verifier_fail_reset_directive,
        test_verifier_fail_over_budget_skip,
        test_all_terminal_decides_finalize,
        test_decide_dispatch_increments_attempt,
        test_compact_trigger,
        test_apply_result_immutable,
        test_record_timing,
        test_review_fail_increments_retry_under_budget,
        test_decide_batch_verify_when_only_pending_batch,
        test_decide_finalize_only_when_no_pending_batch,
        test_apply_result_batch_pass_completes_task,
        test_apply_result_batch_fail_skips_task,
    ]

    failed = []
    for fn in tests:
        try:
            fn()
        except Exception as exc:
            print(f"FAIL: {fn.__name__}: {exc}")
            failed.append(fn.__name__)

    print()
    print(f"Results: {len(tests) - len(failed)}/{len(tests)} passed")
    if failed:
        print(f"FAILED: {failed}")
        sys.exit(1)
    else:
        print("ALL TESTS PASSED")
