#!/usr/bin/env python3
"""test_drift.py — TDD suite for drift.py (CME v3.0 T13).

Tests:
  (a) terminal task with null timing → appears in repairable
  (b) completed < started (timing_inverted) → appears in blocking (un-waivable)
  (c) after repair_safe, repairable item is gone AND a record written to state["drift"]["records"]
  (d) repair_stale_run(dry-run) makes NO file changes
  negative: clean state → empty blocking + repairable (anti-vacuous guard)

__main__ runs ALL defined test functions. sys.exit(1) on any failure.
"""

from __future__ import annotations

import copy
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import drift


# ── shared fixture helpers ───────────────────────────────────────────────────

def _base_state(
    *,
    task_status: str = "COMPLETE",
    timing: dict | None = None,
    dispatches: int = 1,
    worktree: str | None = "/some/worktree",
) -> dict:
    """Minimal CME v3 state with one completed task."""
    task: dict = {
        "status": task_status,
        "phase": "verify",
        "review_retries": 0,
        "verifier_retries": 0,
        "escalations": 0,
    }
    if timing is not None:
        task["timing"] = timing
    state: dict = {
        "schema_version": 3,
        "status": "COMPLETE",
        "current_task": None,
        "last_completed_task": "task_1",
        "worktree": worktree,
        "orchestrator_dir": "/some/orch",
        "risk_levels": {"task_1": "mid"},
        "execution_plan": [["task_1"]],
        "tasks": {"task_1": task},
        "task_summaries": {},
        "quality_trend": [],
        "cost_ledger": {"totals": {"dispatches": dispatches}, "by_task": {}},
        "compaction_points": [],
        "last_compaction_after_task": None,
        "drift": {},
    }
    return state


def _orch_dir_with_result(task_id: str = "task_1") -> tuple[str, str]:
    """Create a temp orch dir with a verifier result file. Return (orch_dir, tmp_dir_path)."""
    tmp = tempfile.mkdtemp()
    results_dir = os.path.join(tmp, "results")
    os.makedirs(results_dir)
    # Create a dummy verifier result file (minimal valid filename)
    result_file = os.path.join(results_dir, f"verifier_{task_id}_a1.json")
    with open(result_file, "w") as f:
        json.dump({"status": "PASS"}, f)
    return tmp, tmp


# ── TEST (a): terminal task with null timing → repairable ────────────────────

def test_null_timing_terminal_task_is_repairable():
    """A COMPLETE task with timing=None or {} appears in repairable (migrated-run defense)."""
    # timing present but both started and completed are None
    state = _base_state(task_status="COMPLETE", timing=None)
    state["tasks"]["task_1"]["timing"] = None  # explicitly null
    result = drift.check(state, "/some/orch")
    kinds = [item["kind"] for item in result["repairable"]]
    assert "missing_timing" in kinds, (
        f"Expected 'missing_timing' in repairable, got repairable={result['repairable']!r}"
    )
    assert result["blocking"] == [], (
        f"null timing should be repairable, not blocking; got blocking={result['blocking']!r}"
    )
    print("TEST (a) PASS: null timing terminal task → repairable")


# ── TEST (b): timing_inverted → blocking (un-waivable) ───────────────────────

def test_timing_inverted_is_blocking_unwaivable():
    """completed < started → appears in blocking, kind=timing_inverted (un-waivable)."""
    state = _base_state(
        task_status="COMPLETE",
        timing={"started": "2025-01-01T10:00:00Z", "completed": "2025-01-01T09:00:00Z"},
    )
    result = drift.check(state, "/some/orch")
    kinds = [item["kind"] for item in result["blocking"]]
    assert "timing_inverted" in kinds, (
        f"Expected 'timing_inverted' in blocking, got blocking={result['blocking']!r}"
    )
    # Must be un-waivable: confirm the item doesn't also appear in repairable
    rep_kinds = [item["kind"] for item in result["repairable"]]
    assert "timing_inverted" not in rep_kinds, (
        "timing_inverted must NOT appear in repairable (it is un-waivable)"
    )
    print("TEST (b) PASS: timing_inverted → blocking (un-waivable)")


# ── TEST (c): repair_safe removes repairable, writes records ─────────────────

def test_repair_safe_clears_repairable_and_writes_records():
    """After repair_safe: repairable item gone AND record written to state['drift']['records']."""
    state = _base_state(task_status="COMPLETE", timing=None)
    state["tasks"]["task_1"]["timing"] = None
    # Pre-check: repairable present
    before = drift.check(state, "/some/orch")
    assert any(item["kind"] == "missing_timing" for item in before["repairable"]), (
        "Pre-condition: missing_timing should be in repairable before repair"
    )

    repaired_state = drift.repair_safe(state, "/some/orch")
    # Recheck: repairable should be gone
    after = drift.check(repaired_state, "/some/orch")
    repairable_kinds = [item["kind"] for item in after["repairable"]]
    assert "missing_timing" not in repairable_kinds, (
        f"After repair_safe, missing_timing should be gone; still in repairable={after['repairable']!r}"
    )
    # Records written
    records = repaired_state.get("drift", {}).get("records", [])
    assert len(records) > 0, (
        "repair_safe must write at least one record to state['drift']['records']"
    )
    record_kinds = [r.get("kind") for r in records]
    assert "missing_timing" in record_kinds, (
        f"Expected 'missing_timing' in drift records; got {records!r}"
    )
    print("TEST (c) PASS: repair_safe clears repairable + writes records")


# ── TEST (d): repair_stale_run dry-run makes NO file changes ─────────────────

def test_repair_stale_run_dryrun_no_file_changes():
    """repair_stale_run(dry_run=True, apply=False) must NOT modify any files."""
    with tempfile.TemporaryDirectory() as tmp:
        state_path = os.path.join(tmp, "state.json")
        state = _base_state(task_status="COMPLETE", timing={"started": "2024-01-01T00:00:00Z"})
        state["status"] = "RUNNING"  # non-terminal, stale
        state["worktree"] = "/missing/worktree"
        with open(state_path, "w") as f:
            json.dump(state, f)

        # Record file bytes before
        with open(state_path, "rb") as f:
            before_bytes = f.read()

        # dry-run (default)
        result = drift.repair_stale_run(state_path, apply=False)

        # File must be unchanged
        with open(state_path, "rb") as f:
            after_bytes = f.read()

        assert before_bytes == after_bytes, (
            "repair_stale_run(apply=False) must NOT modify state file"
        )
        # Result should be a dict
        assert isinstance(result, dict), (
            f"repair_stale_run must return a dict, got {type(result)}"
        )
        print("TEST (d) PASS: repair_stale_run dry-run makes no file changes")


# ── TEST (negative): clean state → empty blocking + repairable ────────────────

def test_clean_state_empty_drift():
    """A clean, valid state produces no blocking and no repairable items (anti-vacuous guard)."""
    orch_dir, tmp = _orch_dir_with_result("task_1")
    try:
        state = _base_state(
            task_status="COMPLETE",
            timing={"started": "2025-01-01T10:00:00Z", "completed": "2025-01-01T11:00:00Z"},
            dispatches=1,
            worktree=orch_dir,  # worktree exists
        )
        result = drift.check(state, orch_dir)
        assert result["blocking"] == [], (
            f"Clean state should have no blocking drift; got {result['blocking']!r}"
        )
        assert result["repairable"] == [], (
            f"Clean state should have no repairable drift; got {result['repairable']!r}"
        )
        print("TEST (negative) PASS: clean state → empty blocking + repairable")
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


# ── TEST (e): dispatches==0 with completed tasks → blocking ──────────────────

def test_dispatches_zero_with_completed_tasks_blocking():
    """dispatches==0 on a run that has completed tasks → blocking (non-waivable)."""
    state = _base_state(
        task_status="COMPLETE",
        timing={"started": "2025-01-01T10:00:00Z", "completed": "2025-01-01T11:00:00Z"},
        dispatches=0,
    )
    result = drift.check(state, "/some/orch")
    kinds = [item["kind"] for item in result["blocking"]]
    assert "zero_dispatches_with_completed_tasks" in kinds, (
        f"Expected 'zero_dispatches_with_completed_tasks' in blocking; got {result['blocking']!r}"
    )
    print("TEST (e) PASS: dispatches==0 with completed tasks → blocking")


# ── TEST (f): PENDING_BATCH residual after finalize → blocking ────────────────

def test_pending_batch_residual_after_finalize_blocking():
    """Residual PENDING_BATCH task when run status is COMPLETE → blocking."""
    state = _base_state(
        task_status="PENDING_BATCH",
        timing={"started": "2025-01-01T10:00:00Z"},
        dispatches=1,
    )
    # Run is complete but task is still PENDING_BATCH
    state["status"] = "COMPLETE"
    result = drift.check(state, "/some/orch")
    kinds = [item["kind"] for item in result["blocking"]]
    assert "residual_pending_batch" in kinds, (
        f"Expected 'residual_pending_batch' in blocking; got {result['blocking']!r}"
    )
    print("TEST (f) PASS: residual PENDING_BATCH after finalize → blocking")


# ── TEST (g): repair_safe does NOT mutate input state ────────────────────────

def test_repair_safe_immutability():
    """repair_safe must not mutate input state."""
    state = _base_state(task_status="COMPLETE", timing=None)
    state["tasks"]["task_1"]["timing"] = None
    original = copy.deepcopy(state)
    _ = drift.repair_safe(state, "/some/orch")
    assert state == original, (
        "repair_safe must not mutate input state (deep-copy discipline)"
    )
    print("TEST (g) PASS: repair_safe does not mutate input state")


# ── TEST (h): repair_safe does NOT touch blocking items ──────────────────────

def test_repair_safe_never_touches_blocking():
    """repair_safe on a timing_inverted state: blocking item remains; timestamps NOT touched."""
    state = _base_state(
        task_status="COMPLETE",
        timing={"started": "2025-01-01T10:00:00Z", "completed": "2025-01-01T09:00:00Z"},
    )
    original_timing = copy.deepcopy(state["tasks"]["task_1"]["timing"])

    repaired = drift.repair_safe(state, "/some/orch")

    # blocking still detected
    after = drift.check(repaired, "/some/orch")
    assert any(item["kind"] == "timing_inverted" for item in after["blocking"]), (
        "timing_inverted must still appear in blocking after repair_safe"
    )
    # timestamps NOT changed
    assert repaired["tasks"]["task_1"]["timing"] == original_timing, (
        "repair_safe must NOT modify timing on a blocking (timing_inverted) item"
    )
    print("TEST (h) PASS: repair_safe never touches blocking items")


# ── TEST (i): repair_stale_run apply=True marks lifecycle:blocked_stale ──────

def test_repair_stale_run_apply_marks_blocked_stale():
    """repair_stale_run(apply=True) marks lifecycle=blocked_stale in the state file."""
    with tempfile.TemporaryDirectory() as tmp:
        state_path = os.path.join(tmp, "state.json")
        state = _base_state(task_status="COMPLETE", timing={"started": "2024-01-01T00:00:00Z"})
        state["status"] = "RUNNING"  # non-terminal
        with open(state_path, "w") as f:
            json.dump(state, f)

        result = drift.repair_stale_run(state_path, apply=True)

        # File should now carry lifecycle=blocked_stale
        with open(state_path) as f:
            written = json.load(f)
        assert written.get("lifecycle") == "blocked_stale", (
            f"repair_stale_run(apply=True) must set lifecycle=blocked_stale; "
            f"got lifecycle={written.get('lifecycle')!r}"
        )
        assert isinstance(result, dict), "repair_stale_run must return dict"
        print("TEST (i) PASS: repair_stale_run(apply=True) marks lifecycle:blocked_stale")


# ── main: run ALL test functions ─────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        test_null_timing_terminal_task_is_repairable,
        test_timing_inverted_is_blocking_unwaivable,
        test_repair_safe_clears_repairable_and_writes_records,
        test_repair_stale_run_dryrun_no_file_changes,
        test_clean_state_empty_drift,
        test_dispatches_zero_with_completed_tasks_blocking,
        test_pending_batch_residual_after_finalize_blocking,
        test_repair_safe_immutability,
        test_repair_safe_never_touches_blocking,
        test_repair_stale_run_apply_marks_blocked_stale,
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
