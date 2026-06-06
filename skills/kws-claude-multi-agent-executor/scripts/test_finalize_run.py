"""Tests for finalize_run.py — finalization-consistency gate + safe --fix."""
import json
import os
import sys
from datetime import datetime  # noqa: E402  (top of file alongside json/os/sys)

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
    assert "cost_dispatches_zero" in fails          # v2.27: WARN -> FAIL
    assert "timing_tracking_absent" in fails        # v2.27: all tasks null-started
    warns = {f["code"] for f in result["findings"] if f["level"] == "WARN"}
    assert "timing_started_missing" in warns        # per-task WARN retained


def test_cost_waived_suppresses_dispatch_warning(tmp_path):
    waived = dict(SOURCE_MATCHING_BAD, cost_tracking_waived=True)
    result = fr.evaluate(waived)
    codes = {f["code"] for f in result["findings"]}
    assert "cost_dispatches_zero" not in codes      # suppressed entirely


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


# --- v2.27: cost/timing drift become blocking FAIL (D002) ------------------

# run-2 shape: no cost_ledger, all tasks null timing.started, not waived.
RUN2_DRIFT = {
    "status": "COMPLETE",
    "timestamps": {"started_at": "a", "completed_at": "b"},
    "tasks": {
        "task_1": {"status": "COMPLETE", "verifier": "PASS", "timing": {"completed": "c"}},
        "task_2": {"status": "COMPLETE", "verifier": "PASS", "timing": {"completed": "c"}},
    },
}

# run-1 shape: cost waived (dispatches 0 ok), but timing all null -> still FAIL.
RUN1_DRIFT = {
    "status": "COMPLETE",
    "cost_tracking_waived": True,
    "timestamps": {"started_at": "a", "completed_at": "b"},
    "cost_ledger": {"totals": {"dispatches": 0}},
    "tasks": {
        "task_1": {"status": "COMPLETE", "verifier": "PASS", "timing": {"completed": "c"}},
    },
}

# run-3 shape: dispatches + timing populated -> clean (no false positive).
RUN3_CLEAN = {
    "status": "COMPLETE",
    "timestamps": {"started_at": "a", "completed_at": "b"},
    "cost_ledger": {"totals": {"dispatches": 9}},
    "tasks": {
        "task_1": {"status": "COMPLETE", "verifier": "PASS",
                   "timing": {"started": "s", "completed": "c"}},
    },
}


def test_run2_drift_fails_on_cost_and_timing(tmp_path):
    result = fr.evaluate(RUN2_DRIFT)
    fails = {f["code"] for f in result["findings"] if f["level"] == "FAIL"}
    assert result["passed"] is False
    assert "cost_dispatches_zero" in fails
    assert "timing_tracking_absent" in fails


def test_run1_drift_fails_on_timing_only_cost_waived(tmp_path):
    result = fr.evaluate(RUN1_DRIFT)
    codes_by_level = {(f["level"], f["code"]) for f in result["findings"]}
    assert result["passed"] is False
    assert ("FAIL", "timing_tracking_absent") in codes_by_level
    assert "cost_dispatches_zero" not in {c for _, c in codes_by_level}  # waived


def test_run3_clean_no_false_positive(tmp_path):
    result = fr.evaluate(RUN3_CLEAN)
    assert result["passed"] is True
    assert [f for f in result["findings"] if f["level"] == "FAIL"] == []


def test_timing_waived_suppresses_aggregate(tmp_path):
    waived = dict(RUN2_DRIFT, timing_tracking_waived=True, cost_tracking_waived=True)
    result = fr.evaluate(waived)
    codes = {f["code"] for f in result["findings"]}
    assert "timing_tracking_absent" not in codes
    assert result["passed"] is True


# --- v2.27 (D003): worktree hook-wiring backstop at finalize ----------------

def _worktree_with_settings(tmp_path, settings):
    wt = tmp_path / "wt"
    (wt / ".claude").mkdir(parents=True)
    if settings is not None:
        (wt / ".claude" / "settings.json").write_text(
            json.dumps(settings), encoding="utf-8")
    return str(wt)


# A fully-wired settings.json: all four events present, Stop references the gate.
_WIRED_SETTINGS = {
    "permissions": {"allow": ["Bash(git status:*)"]},
    "hooks": {
        "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "x"}]}],
        "PostToolUse": [{"matcher": "Edit|Write",
                         "hooks": [{"type": "command", "command": "x"}]}],
        "SubagentStop": [{"hooks": [{"type": "command", "command": "x"}]}],
        "Stop": [{"hooks": [{"type": "command",
                             "command": "/o/hooks/finalization-stop-gate.sh /o/state.json /s"}]}],
    },
}

# run-2's actual on-disk shape: $schema + permissions, NO hooks block.
_UNWIRED_SETTINGS = {
    "$schema": "https://json.schemastore.org/claude-code-settings.json",
    "permissions": {"allow": ["Bash(git status:*)"]},
}


def test_unwired_worktree_hooks_fail(tmp_path):
    wt = _worktree_with_settings(tmp_path, _UNWIRED_SETTINGS)
    state = dict(RUN3_CLEAN, worktree=wt)  # otherwise-clean run
    result = fr.evaluate(state)
    fails = {f["code"] for f in result["findings"] if f["level"] == "FAIL"}
    assert "hooks_not_wired" in fails
    assert result["passed"] is False


def test_wired_worktree_hooks_pass(tmp_path):
    wt = _worktree_with_settings(tmp_path, _WIRED_SETTINGS)
    state = dict(RUN3_CLEAN, worktree=wt)
    result = fr.evaluate(state)
    codes = {f["code"] for f in result["findings"]}
    assert "hooks_not_wired" not in codes
    assert result["passed"] is True


def test_unwired_hooks_waived_suppresses(tmp_path):
    wt = _worktree_with_settings(tmp_path, _UNWIRED_SETTINGS)
    state = dict(RUN3_CLEAN, worktree=wt, hooks_wiring_waived=True)
    result = fr.evaluate(state)
    codes = {f["code"] for f in result["findings"]}
    assert "hooks_not_wired" not in codes
    assert result["passed"] is True


def test_absent_settings_skips_hook_check(tmp_path):
    wt = _worktree_with_settings(tmp_path, None)  # no settings.json on disk
    state = dict(RUN3_CLEAN, worktree=wt)
    result = fr.evaluate(state)
    codes = {f["code"] for f in result["findings"]}
    assert "hooks_not_wired" not in codes  # uninspectable -> skip, never fail
    assert result["passed"] is True


def test_no_worktree_key_skips_hook_check(tmp_path):
    result = fr.evaluate(RUN3_CLEAN)  # no worktree key at all
    codes = {f["code"] for f in result["findings"]}
    assert "hooks_not_wired" not in codes
    assert result["passed"] is True


def test_partial_timing_is_warn_not_fail(tmp_path):
    partial = {
        "status": "COMPLETE",
        "timestamps": {"started_at": "a", "completed_at": "b"},
        "cost_ledger": {"totals": {"dispatches": 4}},
        "tasks": {
            "task_1": {"status": "COMPLETE", "verifier": "PASS",
                       "timing": {"started": "s", "completed": "c"}},
            "task_2": {"status": "COMPLETE", "verifier": "PASS",
                       "timing": {"completed": "c"}},  # missing started
        },
    }
    result = fr.evaluate(partial)
    fails = {f["code"] for f in result["findings"] if f["level"] == "FAIL"}
    warns = {f["code"] for f in result["findings"] if f["level"] == "WARN"}
    assert "timing_tracking_absent" not in fails  # not ALL null -> no aggregate FAIL
    assert "timing_started_missing" in warns
    assert result["passed"] is True


# --- v2.28 (D003): timing_inverted — physically impossible ordering --------

# run-3 shape: started is a KST wall-clock with a bogus Z, completed is real UTC,
# so started (21:00Z) > completed (12:02Z) — completed 9h "before" started.
INVERTED = {
    "status": "COMPLETE",
    "timestamps": {"started_at": "a", "completed_at": "b"},
    "cost_ledger": {"totals": {"dispatches": 4}},
    "tasks": {
        "task_1": {"status": "COMPLETE", "verifier": "PASS",
                   "timing": {"started": "2026-06-06T21:00:00Z",
                              "completed": "2026-06-06T12:02:06Z"}},
    },
}


def test_inverted_timing_is_blocking_fail(tmp_path):
    result = fr.evaluate(INVERTED)
    fails = {f["code"] for f in result["findings"] if f["level"] == "FAIL"}
    assert "timing_inverted" in fails
    assert result["passed"] is False


def test_inverted_timing_fails_even_when_waived(tmp_path):
    # timing_tracking_waived governs ABSENCE, not corruption -> still FAIL.
    waived = dict(INVERTED, timing_tracking_waived=True, cost_tracking_waived=True)
    fails = {f["code"] for f in fr.evaluate(waived)["findings"] if f["level"] == "FAIL"}
    assert "timing_inverted" in fails


def test_normal_ordering_no_inverted(tmp_path):
    ok = {
        "status": "COMPLETE",
        "timestamps": {"started_at": "a", "completed_at": "b"},
        "cost_ledger": {"totals": {"dispatches": 1}},
        "tasks": {"task_1": {"status": "COMPLETE", "verifier": "PASS",
                             "timing": {"started": "2026-06-06T12:00:00Z",
                                        "completed": "2026-06-06T12:02:06Z"}}},
    }
    codes = {f["code"] for f in fr.evaluate(ok)["findings"]}
    assert "timing_inverted" not in codes


def test_unparseable_timing_no_inverted_no_crash(tmp_path):
    garbage = {
        "status": "COMPLETE",
        "timestamps": {"started_at": "a", "completed_at": "b"},
        "cost_ledger": {"totals": {"dispatches": 1}},
        "tasks": {"task_1": {"status": "COMPLETE", "verifier": "PASS",
                             "timing": {"started": "not-a-date", "completed": "also-bad"}}},
    }
    codes = {f["code"] for f in fr.evaluate(garbage)["findings"]}
    assert "timing_inverted" not in codes  # falls through to null/absent path
