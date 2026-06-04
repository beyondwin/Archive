"""Tests for finalize_run.py — finalization-consistency gate + safe --fix."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import finalize_run as fr  # noqa: E402


def _write(tmp_path, data):
    p = tmp_path / "state.json"
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return p


def _read(p):
    return json.loads(p.read_text(encoding="utf-8"))


CLEAN = {
    "status": "COMPLETE",
    "timestamps": {"started_at": "2026-06-04T12:00:00Z", "completed_at": "2026-06-04T14:00:00Z"},
    "cost_ledger": {"totals": {"dispatches": 5}},
    "tasks": {
        "task_1": {"status": "COMPLETE", "verifier": "PASS", "timing": {"started": "x", "completed": "y"}},
    },
}

# The actual source-matching-refinement-20260604 unfinalized shape.
SOURCE_MATCHING_BAD = {
    "status": "COMPLETE",
    "last_completed_at": "2026-06-04T23:04:22.658323",
    "timestamps": {"started_at": "2026-06-04T12:06:54Z", "completed_at": None},
    "cost_ledger": {"totals": {"dispatches": 0}},
    "tasks": {
        "task_9": {"status": "COMPLETE", "verifier": "PASS", "timing": {"completed": "z"}},
        "task_10": {"status": "COMPLETE", "verifier": "PENDING_BATCH", "timing": {"completed": "z"}},
    },
}


def test_clean_run_passes(tmp_path):
    result = fr.evaluate(CLEAN)
    assert result["passed"] is True
    assert [f for f in result["findings"] if f["level"] == "FAIL"] == []


def test_source_matching_flags_pending_and_completed_at(tmp_path):
    result = fr.evaluate(SOURCE_MATCHING_BAD)
    assert result["passed"] is False
    fails = {f["code"] for f in result["findings"] if f["level"] == "FAIL"}
    assert "verifier_pending_batch" in fails
    assert "completed_at_null" in fails
    warns = {f["code"] for f in result["findings"] if f["level"] == "WARN"}
    assert "cost_dispatches_zero" in warns
    assert "timing_started_missing" in warns


def test_cost_waived_suppresses_dispatch_warning(tmp_path):
    waived = dict(SOURCE_MATCHING_BAD, cost_tracking_waived=True)
    result = fr.evaluate(waived)
    warns = {f["code"] for f in result["findings"] if f["level"] == "WARN"}
    assert "cost_dispatches_zero" not in warns


def test_fix_stamps_completed_at_from_last_completed(tmp_path):
    p = _write(tmp_path, SOURCE_MATCHING_BAD)
    fr.apply_fix(p)
    st = _read(p)
    assert st["timestamps"]["completed_at"] == "2026-06-04T23:04:22.658323"


def test_fix_does_not_clear_pending_batch(tmp_path):
    p = _write(tmp_path, SOURCE_MATCHING_BAD)
    fr.apply_fix(p)
    st = _read(p)
    assert st["tasks"]["task_10"]["verifier"] == "PENDING_BATCH"


def test_check_exit_codes(tmp_path):
    good = _write(tmp_path, CLEAN)
    assert fr.main(["--state", str(good), "--check"]) == 0
    bad = _write(tmp_path, SOURCE_MATCHING_BAD)
    assert fr.main(["--state", str(bad), "--check"]) == 1


def test_fix_then_pass_only_if_no_unfixable_fail(tmp_path):
    # PENDING_BATCH is unfixable, so --fix still exits 1.
    bad = _write(tmp_path, SOURCE_MATCHING_BAD)
    assert fr.main(["--state", str(bad), "--fix"]) == 1
    # Remove the unfixable task; only completed_at remains -> --fix exits 0.
    only_completed = {
        "status": "COMPLETE",
        "last_completed_at": "2026-06-04T23:04:22.658323",
        "timestamps": {"started_at": "a", "completed_at": None},
        "cost_ledger": {"totals": {"dispatches": 2}},
        "tasks": {"task_1": {"status": "COMPLETE", "verifier": "PASS",
                             "timing": {"started": "s", "completed": "c"}}},
    }
    p = _write(tmp_path, only_completed)
    assert fr.main(["--state", str(p), "--fix"]) == 0


def test_multi_plan_chain_checks_each_tree(tmp_path):
    multi = {
        "status": "COMPLETE",
        "timestamps": {"started_at": "a", "completed_at": "b"},
        "cost_ledger": {"totals": {"dispatches": 4}},
        "plan_chain": [
            {"tasks": {"t1": {"status": "COMPLETE", "verifier": "PASS",
                              "timing": {"started": "s", "completed": "c"}}}},
            {"tasks": {"t2": {"status": "COMPLETE", "verifier": "PENDING_BATCH",
                              "timing": {"started": "s", "completed": "c"}}}},
        ],
    }
    result = fr.evaluate(multi)
    assert any(f["code"] == "verifier_pending_batch" and f["scope"] == "plan_chain[1]"
               for f in result["findings"])
