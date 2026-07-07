"""test_cycle_e2e.py — Simulation e2e test for the kernel next/submit cycle (CME v3.0 T9).

This test drives the full task-cycle through the REAL CLI contract (subprocess),
exercising:
  - next → submit looping until finalize
  - timing auto-stamp (started/completed non-null post-run)
  - cost ledger auto-record (dispatches >= 5)
  - events.jsonl written
  - schema-invalid result rejection (accepted:false, no state corruption)

Regression-defense: these assertions prove the v2 "bookkeeping waived by prose" path is dead.
"""

import copy
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_HERE = os.path.dirname(os.path.abspath(__file__))
KERNEL = os.path.join(_HERE, "kernel.py")

# ── helpers ───────────────────────────────────────────────────────────────────

def _run_kernel(*args):
    """Run kernel.py with given args; return (returncode, parsed_json_or_None, raw_stdout)."""
    import subprocess
    cmd = [sys.executable, KERNEL] + list(args)
    result = subprocess.run(cmd, capture_output=True, text=True)
    raw = result.stdout.strip()
    parsed = None
    if raw:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            pass
    return result.returncode, parsed, raw


def _make_state(orch_dir: str) -> dict:
    """Build a minimal T3 v3 state for a 2-task plan (MID + LOW)."""
    return {
        "schema_version": 3,
        "status": "RUNNING",
        "plan": "test_plan.md",
        "spec": "",
        "worktree": orch_dir,
        "orchestrator_dir": orch_dir,
        "agentlens_run_id": None,
        "current_task": "task_1",
        "current_pre_task_sha": "abc1234",
        "risk_levels": {
            "task_1": "mid",
            "task_2": "low",
        },
        "execution_plan": [
            ["task_1"],
            ["task_2"],
        ],
        "tasks": {
            "task_1": {
                "status": "IN_PROGRESS",
                "phase": "implement",
                "title": "Implement feature A",
                "body": "Implement feature A as described.",
                "review_retries": 0,
                "verifier_retries": 0,
                "escalations": 0,
                "schema_violations": 0,
                "timing": {},
            },
            "task_2": {
                "status": "IN_PROGRESS",
                "phase": "implement",
                "title": "Implement feature B",
                "body": "Implement feature B as described.",
                "review_retries": 0,
                "verifier_retries": 0,
                "escalations": 0,
                "schema_violations": 0,
                "timing": {},
            },
        },
        "task_summaries": {},
        "quality_trend": [],
        "cost_ledger": {
            "by_task": {},
            "totals": {
                "input_tokens": 0,
                "output_tokens": 0,
                "cached_read_tokens": 0,
                "cached_write_tokens": 0,
                "cache_read_tokens": 0,
                "cache_creation_tokens": 0,
                "cost_usd": 0.0,
                "dispatches": 0,
            },
        },
        "compaction_points": [],
        "last_compaction_after_task": None,
        "last_completed_task": None,
        "implementer_model": "sonnet",
        "dispatch_config": {
            "implementer": "p",
            "reviewer": "p",
            "verifier_per_task": "p",
        },
    }


def _valid_implementer_payload() -> dict:
    return {
        "status": "DONE",
        "summary": "Implemented the feature.",
        "files_changed": ["feature.py"],
        "files_test_changed": ["test_feature.py"],
    }


def _valid_reviewer_payload() -> dict:
    # 0.0-1.0 scale (per reviewer_result.schema.json): 0.9 >= 0.85 PASS threshold.
    # Deliberately NOT 9.0 — a 0-10 value would trivially clear the 0.85 gate and
    # silently defeat it, meaning the test would pass even if the 0.0-1.0 schema
    # contract were reverted. 0.9/0.9 exercises the real contract.
    return {
        "status": "PASS",
        "spec_score": 0.9,
        "quality_score": 0.9,
        "issues": [],
    }


def _valid_verifier_payload() -> dict:
    return {
        "status": "PASS",
        "commands_run": ["python3 -m pytest"],
        "exit_codes": [0],
    }


def _write_result_file(path: str, payload: dict) -> None:
    """Write a fake `claude -p --output-format json` envelope to path."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    envelope = {
        "result": json.dumps(payload),
        "usage": {
            "input_tokens": 100,
            "output_tokens": 50,
        },
        "total_cost_usd": 0.01,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(envelope, f)


# ── Test 1: happy-path full cycle ─────────────────────────────────────────────

def test_full_cycle():
    """Drive implementer→reviewer→verifier(MID), LOW→PENDING_BATCH→batch_drain→COMPLETE, finalize.

    Regression assertions:
    1. Cycle progresses through all roles in order.
    2. Final next returns finalize (ONLY after batch drain is complete).
    2b: LOW-risk task_2 is drained: PENDING_BATCH → COMPLETE via batch verifier.
    3. timing.started AND timing.completed are non-null for ALL tasks.
    4. cost_ledger.totals.dispatches >= 5.
    5. events.jsonl exists and has lines.
    6. finalize succeeds with grade=green and no pending_batch_unverified residual risk.
    """
    with tempfile.TemporaryDirectory() as orch_dir:
        state_path = os.path.join(orch_dir, "state.json")
        state = _make_state(orch_dir)
        with open(state_path, "w") as f:
            json.dump(state, f, indent=2)

        dispatch_sequence = []  # track (role, task_id) order

        # Run until action is finalize (or too many iterations)
        for iteration in range(25):
            rc, action, raw = _run_kernel("next", "--state", state_path)
            assert rc == 0, f"iter {iteration}: next exited {rc}; stdout={raw!r}"
            assert action is not None, f"iter {iteration}: next returned no JSON; stdout={raw!r}"

            act = action.get("action")
            assert act is not None, f"iter {iteration}: action has no 'action' key: {action}"

            if act == "finalize":
                print(f"  iter {iteration}: FINALIZE reached")
                break

            assert act == "dispatch", (
                f"iter {iteration}: expected dispatch or finalize, got {act!r}: {action}"
            )

            role = action["role"]
            task_id = action["task_id"]
            result_path = action.get("result_path")
            assert result_path, f"iter {iteration}: dispatch has no result_path: {action}"

            # For batch verifier dispatches, record each task_id in task_ids
            is_batch = action.get("batch") is True
            if is_batch:
                for tid in action.get("task_ids", [task_id]):
                    dispatch_sequence.append((role, tid))
                print(f"  iter {iteration}: batch-verifier dispatch for task_ids={action.get('task_ids')}")
            else:
                dispatch_sequence.append((role, task_id))
                print(f"  iter {iteration}: dispatching {role} for {task_id}")

            # Write valid result for this role
            if role == "implementer":
                payload = _valid_implementer_payload()
            elif role == "reviewer":
                payload = _valid_reviewer_payload()
            elif role == "verifier":
                payload = _valid_verifier_payload()
            else:
                raise AssertionError(f"Unexpected role: {role!r}")

            _write_result_file(result_path, payload)

            rc, sub_result, raw = _run_kernel(
                "submit",
                "--state", state_path,
                "--task", task_id,
                "--role", role,
                "--result", result_path,
            )
            assert rc == 0, f"iter {iteration}: submit exited {rc}; stdout={raw!r}"
            assert sub_result is not None, f"iter {iteration}: submit returned no JSON"
            assert sub_result.get("accepted") is True, (
                f"iter {iteration}: submit not accepted: {sub_result}"
            )
        else:
            raise AssertionError("Cycle did not reach finalize within 25 iterations")

        # Assertion 1: dispatch sequence correctness
        # Expected: implementer/task_1, reviewer/task_1, verifier/task_1,
        #           implementer/task_2, reviewer/task_2,
        #           verifier/task_2 (batch drain — LOW task completes verification)
        expected = [
            ("implementer", "task_1"),
            ("reviewer", "task_1"),
            ("verifier", "task_1"),
            ("implementer", "task_2"),
            ("reviewer", "task_2"),
            ("verifier", "task_2"),  # batch drain
        ]
        assert dispatch_sequence == expected, (
            f"Wrong dispatch sequence.\nExpected: {expected}\nGot:      {dispatch_sequence}"
        )
        print("  ASSERT 1 PASS: dispatch sequence correct (includes batch drain)")

        # Read final state
        with open(state_path) as f:
            final_state = json.load(f)

        # Assertion 2: final next returns finalize (already asserted in loop above)
        print("  ASSERT 2 PASS: final next returned finalize")

        # Assertion 2b: LOW-risk task_2 was drained through batch verifier → COMPLETE
        assert final_state["tasks"]["task_2"]["status"] == "COMPLETE", (
            f"LOW task_2 should be COMPLETE after batch drain, got "
            f"{final_state['tasks']['task_2']['status']!r}"
        )
        print("  ASSERT 2b PASS: LOW task_2 status == COMPLETE (batch drain succeeded)")

        # Assertion 3: timing.started AND timing.completed non-null for ALL tasks
        tasks = final_state["tasks"]
        for tid, task in tasks.items():
            timing = task.get("timing", {})
            started = timing.get("started")
            completed = timing.get("completed")
            assert started is not None, f"task {tid}: timing.started is None; timing={timing}"
            assert completed is not None, f"task {tid}: timing.completed is None; timing={timing}"
            print(f"  ASSERT 3 PASS: task {tid} timing.started={started!r} timing.completed={completed!r}")

        # Assertion 4: dispatches >= 5
        dispatches = final_state["cost_ledger"]["totals"]["dispatches"]
        assert dispatches >= 5, (
            f"cost_ledger.totals.dispatches={dispatches} < 5 (expected >= 5)"
        )
        print(f"  ASSERT 4 PASS: cost_ledger.totals.dispatches={dispatches}")

        # Assertion 5: events.jsonl exists and has lines
        events_path = os.path.join(orch_dir, "events.jsonl")
        assert os.path.exists(events_path), f"events.jsonl not found at {events_path}"
        with open(events_path) as f:
            lines = [ln.strip() for ln in f if ln.strip()]
        assert len(lines) >= 1, "events.jsonl is empty"
        # Verify each line is valid JSON
        for ln in lines:
            rec = json.loads(ln)
            assert "event_type" in rec, f"events.jsonl line missing event_type: {ln!r}"
        print(f"  ASSERT 5 PASS: events.jsonl has {len(lines)} lines")

        # Assertion 6: finalize succeeds green with no pending_batch_unverified risk
        rc, fin_result, fin_raw = _run_kernel("finalize", "--state", state_path)
        assert rc == 0, f"finalize failed: rc={rc}, stdout={fin_raw!r}"
        assert fin_result is not None, f"finalize returned no JSON: {fin_raw!r}"
        assert "error" not in fin_result, f"finalize returned error: {fin_result}"
        assert fin_result.get("completion_passed") is True, (
            f"Expected completion_passed=True after full drain, got {fin_result!r}"
        )
        assert fin_result.get("grade") == "green", (
            f"Expected grade=green after full drain, got grade={fin_result.get('grade')!r}"
        )
        # Verify no pending_batch_unverified residual risk in state
        with open(state_path) as f:
            fin_state = json.load(f)
        residual_classes = [
            r.get("class")
            for r in fin_state.get("completion_audit", {}).get("residual_risk", [])
            if isinstance(r, dict)
        ]
        assert "pending_batch_unverified" not in residual_classes, (
            f"Expected no pending_batch_unverified after drain; got residual_risk={residual_classes}"
        )
        print(f"  ASSERT 6 PASS: finalize green + no pending_batch_unverified")

    print("TEST 1 PASS: full cycle (including batch drain)")


# ── Test 2: schema-invalid result rejection ───────────────────────────────────

def test_schema_violation_rejection():
    """Inject an invalid result; assert accepted:false and no state corruption.

    Regression assertion 6:
    - submit returns accepted:false with violations.
    - Task status/phase NOT advanced.
    - State not corrupted.
    """
    with tempfile.TemporaryDirectory() as orch_dir:
        state_path = os.path.join(orch_dir, "state.json")
        state = _make_state(orch_dir)
        with open(state_path, "w") as f:
            json.dump(state, f, indent=2)

        # First: get a valid dispatch action to find result_path
        rc, action, raw = _run_kernel("next", "--state", state_path)
        assert rc == 0, f"next failed: {raw!r}"
        assert action["action"] == "dispatch", f"Expected dispatch, got {action}"

        role = action["role"]
        task_id = action["task_id"]
        result_path = action["result_path"]

        # Capture pre-submit state
        with open(state_path) as f:
            pre_state = json.load(f)

        pre_task_status = pre_state["tasks"][task_id]["status"]
        pre_task_phase = pre_state["tasks"][task_id]["phase"]
        pre_dispatches = pre_state["cost_ledger"]["totals"]["dispatches"]

        # Write an INVALID payload (missing required fields for implementer)
        invalid_payload = {
            "status": "INVALID_VALUE",  # not in enum
            # missing summary, files_changed, files_test_changed
        }
        _write_result_file(result_path, invalid_payload)

        rc, sub_result, raw = _run_kernel(
            "submit",
            "--state", state_path,
            "--task", task_id,
            "--role", role,
            "--result", result_path,
        )
        # submit should exit 0 (not an error), but return accepted:false
        assert rc == 0, f"submit with invalid payload exited {rc}; stdout={raw!r}"
        assert sub_result is not None, f"submit returned no JSON: {raw!r}"
        assert sub_result.get("accepted") is False, (
            f"Expected accepted:false on invalid payload, got: {sub_result}"
        )
        assert "violations" in sub_result, f"No violations key in rejection: {sub_result}"
        assert len(sub_result["violations"]) > 0, "violations list is empty"
        print(f"  ASSERT 6a PASS: accepted:false with {len(sub_result['violations'])} violations")

        # State must NOT be corrupted: task status/phase unchanged
        with open(state_path) as f:
            post_state = json.load(f)

        post_task_status = post_state["tasks"][task_id]["status"]
        post_task_phase = post_state["tasks"][task_id]["phase"]
        assert post_task_status == pre_task_status, (
            f"Task status changed on rejection: {pre_task_status!r} → {post_task_status!r}"
        )
        assert post_task_phase == pre_task_phase, (
            f"Task phase changed on rejection: {pre_task_phase!r} → {post_task_phase!r}"
        )
        print("  ASSERT 6b PASS: task status/phase unchanged after rejection")

        # schema_violations counter should have incremented
        violations_count = post_state["tasks"][task_id].get("schema_violations", 0)
        assert violations_count >= 1, (
            f"schema_violations counter not incremented: {violations_count}"
        )
        print(f"  ASSERT 6c PASS: schema_violations={violations_count}")

        # ASSERT 6d: a rejected submit must NOT record cost (dispatches unchanged)
        post_dispatches = post_state["cost_ledger"]["totals"]["dispatches"]
        assert post_dispatches == pre_dispatches, (
            f"Rejected submit recorded cost: dispatches {pre_dispatches} → {post_dispatches}"
        )
        print(f"  ASSERT 6d PASS: dispatches unchanged on rejection ({post_dispatches})")

        # ASSERT 6e: a subsequent VALID submit for the same task resets
        # schema_violations to 0 (the "consecutive" guarantee, named in the brief).
        valid_payload = _valid_implementer_payload()
        _write_result_file(result_path, valid_payload)
        rc, sub_result, raw = _run_kernel(
            "submit",
            "--state", state_path,
            "--task", task_id,
            "--role", role,
            "--result", result_path,
        )
        assert rc == 0, f"valid submit after rejection exited {rc}; stdout={raw!r}"
        assert sub_result.get("accepted") is True, (
            f"Expected accepted:true on valid resubmit, got: {sub_result}"
        )
        with open(state_path) as f:
            reset_state = json.load(f)
        reset_count = reset_state["tasks"][task_id].get("schema_violations", None)
        assert reset_count == 0, (
            f"schema_violations not reset to 0 after valid submit: {reset_count}"
        )
        print("  ASSERT 6e PASS: schema_violations reset to 0 after valid submit")

    print("TEST 2 PASS: schema violation rejection")


# ── Test 3: run_command (purpose=reset) passthrough ──────────────────────────

def test_run_command_reset_passthrough():
    """next returns run_command with purpose=reset when reset_pending is set."""
    with tempfile.TemporaryDirectory() as orch_dir:
        state_path = os.path.join(orch_dir, "state.json")
        state = _make_state(orch_dir)
        # Manually set reset_pending on task_1
        state["tasks"]["task_1"]["reset_pending"] = True
        with open(state_path, "w") as f:
            json.dump(state, f, indent=2)

        rc, action, raw = _run_kernel("next", "--state", state_path)
        assert rc == 0, f"next failed: {raw!r}"
        assert action is not None, f"No JSON returned: {raw!r}"
        assert action.get("action") == "run_command", (
            f"Expected run_command, got: {action}"
        )
        assert action.get("purpose") == "reset", (
            f"Expected purpose=reset, got: {action.get('purpose')!r}"
        )
        assert "command" in action, f"No 'command' key in run_command action: {action}"
        assert "git reset" in action["command"], (
            f"Expected git reset in command, got: {action['command']!r}"
        )
        print(f"  run_command: {action['command']!r}")
    print("TEST 3 PASS: run_command purpose=reset passthrough")


# ── Test 4: check-stop behaviour ─────────────────────────────────────────────

def test_check_stop_not_done():
    """check-stop exits 0 when tasks are NOT all terminal."""
    with tempfile.TemporaryDirectory() as orch_dir:
        state_path = os.path.join(orch_dir, "state.json")
        state = _make_state(orch_dir)
        with open(state_path, "w") as f:
            json.dump(state, f, indent=2)

        rc, result, raw = _run_kernel("check-stop", "--state", state_path)
        assert rc == 0, f"check-stop returned {rc} when tasks not terminal; stdout={raw!r}"
    print("TEST 4 PASS: check-stop exits 0 when tasks not terminal")


def test_check_stop_all_terminal():
    """check-stop exits 2 when all tasks COMPLETE (zero PENDING_BATCH) and finalize not done."""
    with tempfile.TemporaryDirectory() as orch_dir:
        state_path = os.path.join(orch_dir, "state.json")
        state = _make_state(orch_dir)
        # Force both tasks terminal with ZERO PENDING_BATCH → finalize truly pending.
        state["tasks"]["task_1"]["status"] = "COMPLETE"
        state["tasks"]["task_2"]["status"] = "COMPLETE"
        with open(state_path, "w") as f:
            json.dump(state, f, indent=2)

        rc, result, raw = _run_kernel("check-stop", "--state", state_path)
        assert rc == 2, f"check-stop returned {rc} (expected 2); stdout={raw!r}"
    print("TEST 5 PASS: check-stop exits 2 when all terminal (no PENDING_BATCH) + finalize pending")


def test_check_stop_pending_batch_not_finalize_pending():
    """check-stop BLOCKS the stop (exit 2) when a PENDING_BATCH task lingers.

    T14b: decide() returns a batch-verify DISPATCH here — OUTSTANDING WORK. The
    Stop hook must be BLOCKED (exit 2) so the batch verifier + finalize still
    run; allowing the stop (exit 0) would ship LOW tasks UNVERIFIED (the wedge).
    It still distinguishes this state from finalize-pending via the halt reason.
    """
    with tempfile.TemporaryDirectory() as orch_dir:
        state_path = os.path.join(orch_dir, "state.json")
        state = _make_state(orch_dir)
        # All "terminal" but a batch drain is still due.
        state["tasks"]["task_1"]["status"] = "COMPLETE"
        state["tasks"]["task_2"]["status"] = "PENDING_BATCH"
        with open(state_path, "w") as f:
            json.dump(state, f, indent=2)

        rc, result, raw = _run_kernel("check-stop", "--state", state_path)
        assert rc == 2, (
            f"check-stop returned {rc} (expected 2: batch drain is outstanding "
            f"work, stop must be BLOCKED); stdout={raw!r}"
        )
        assert result.get("halt") == "batch_drain_pending", (
            f"expected halt=batch_drain_pending (distinct from finalize-pending), "
            f"got: {result!r}"
        )
        assert result.get("halt") != "all_tasks_terminal_finalize_pending", (
            f"batch drain must NOT masquerade as finalize-pending: {result!r}"
        )
    print("TEST 5b PASS: check-stop exits 2 (halt=batch_drain_pending) when PENDING_BATCH lingers")


def test_check_stop_finalized():
    """check-stop exits 0 when all tasks terminal AND status==FINALIZED."""
    with tempfile.TemporaryDirectory() as orch_dir:
        state_path = os.path.join(orch_dir, "state.json")
        state = _make_state(orch_dir)
        state["tasks"]["task_1"]["status"] = "COMPLETE"
        state["tasks"]["task_2"]["status"] = "PENDING_BATCH"
        state["status"] = "FINALIZED"
        with open(state_path, "w") as f:
            json.dump(state, f, indent=2)

        rc, result, raw = _run_kernel("check-stop", "--state", state_path)
        assert rc == 0, f"check-stop returned {rc} (expected 0 when finalized); stdout={raw!r}"
    print("TEST 6 PASS: check-stop exits 0 when already FINALIZED")


def test_halt_on_3_consecutive_violations():
    """After 3 consecutive schema violations, submit returns halt_pending:true."""
    with tempfile.TemporaryDirectory() as orch_dir:
        state_path = os.path.join(orch_dir, "state.json")
        state = _make_state(orch_dir)
        with open(state_path, "w") as f:
            json.dump(state, f, indent=2)

        # Get dispatch action
        rc, action, raw = _run_kernel("next", "--state", state_path)
        assert rc == 0, f"next failed: {raw!r}"
        role = action["role"]
        task_id = action["task_id"]
        result_path = action["result_path"]

        # Invalid payload
        invalid_payload = {"status": "INVALID_VALUE"}

        for i in range(1, 4):
            _write_result_file(result_path, invalid_payload)
            rc, sub_result, raw = _run_kernel(
                "submit",
                "--state", state_path,
                "--task", task_id,
                "--role", role,
                "--result", result_path,
            )
            assert rc == 0, f"submit {i} failed: {raw!r}"
            assert sub_result.get("accepted") is False, f"Expected rejected on attempt {i}"

            with open(state_path) as f:
                st = json.load(f)
            sv = st["tasks"][task_id].get("schema_violations", 0)
            print(f"  violation {i}: schema_violations={sv}")

            if i == 3:
                assert sub_result.get("halt_pending") is True, (
                    f"Expected halt_pending:true on 3rd violation, got: {sub_result}"
                )
                print(f"  HALT_PENDING signalled on 3rd violation")
            else:
                assert sub_result.get("halt_pending") is not True, (
                    f"halt_pending should not be set before 3rd consecutive violation"
                )

    print("TEST 7 PASS: halt_pending on 3rd consecutive violation")


# ── runner ────────────────────────────────────────────────────────────────────

_TESTS = [
    test_full_cycle,
    test_schema_violation_rejection,
    test_run_command_reset_passthrough,
    test_check_stop_not_done,
    test_check_stop_all_terminal,
    test_check_stop_pending_batch_not_finalize_pending,
    test_check_stop_finalized,
    test_halt_on_3_consecutive_violations,
]

if __name__ == "__main__":
    failures = []
    for fn in _TESTS:
        print(f"\n─── {fn.__name__} ───")
        try:
            fn()
        except Exception as e:
            import traceback
            print(f"FAIL: {e}")
            traceback.print_exc()
            failures.append(fn.__name__)

    print(f"\n{'=' * 60}")
    print(f"RESULTS: {len(_TESTS) - len(failures)}/{len(_TESTS)} passed")
    if failures:
        print(f"FAILED: {', '.join(failures)}")
        sys.exit(1)
    else:
        print("ALL TESTS PASS")
        sys.exit(0)
