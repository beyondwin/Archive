"""Tests for the finalization Stop-hook (finalization-stop-gate.sh.template).

The hook is materialized at Phase 0 Step 2.5 into <orch_dir>/hooks/. These tests
copy the template to an executable temp path and drive it via subprocess against
crafted state.json fixtures, passing this repo's real scripts/ dir as $2 so the
two validators resolve. Contract under test:

  - mid-run (any non-terminal task)            -> exit 0 (allow stop)
  - fresh run (no completed work)              -> exit 0 (allow stop)
  - all-terminal + clean + finalized           -> exit 0 (allow stop)
  - all-terminal + unfinalized (source-match)  -> exit 2 (block stop)
  - all-terminal + non-canonical (readmates)   -> exit 2 (block stop)
"""
import json
import os
import shutil
import subprocess
import sys

import pytest

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPTS_DIR)
TEMPLATE = os.path.join(
    SKILL_DIR, "references", "hooks", "finalization-stop-gate.sh.template"
)

pytestmark = pytest.mark.skipif(
    shutil.which("jq") is None or shutil.which("python3") is None,
    reason="hook requires jq and python3 on PATH",
)


def _hook(tmp_path):
    dst = tmp_path / "finalization-stop-gate.sh"
    shutil.copyfile(TEMPLATE, dst)
    os.chmod(dst, 0o755)
    return str(dst)


def _state(tmp_path, data):
    p = tmp_path / "state.json"
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return str(p)


def _run(hook, state):
    return subprocess.run(
        [hook, state, SCRIPTS_DIR],
        input="{}",
        capture_output=True,
        text=True,
    )


CLEAN_FINALIZED = {
    "status": "COMPLETE",
    "schema_version": "2",
    "mode": "interactive_attached",
    "timestamps": {"started_at": "2026-06-04T12:00:00Z",
                   "completed_at": "2026-06-04T14:00:00Z"},
    "cost_ledger": {"totals": {"dispatches": 5}},
    "dispatch_config": {"mode": "interactive_attached"},
    "risk_levels": {"task_1": "low"},
    "execution_plan": [["task_1"]],
    "tasks": {
        "task_1": {"status": "COMPLETE", "verifier": "PASS",
                   "timing": {"started": "x", "completed": "y"}},
    },
}

MID_RUN = {
    "status": "RUNNING",
    "timestamps": {"started_at": "2026-06-04T12:00:00Z", "completed_at": None},
    "current_task": 2,
    "risk_levels": {"task_1": "low", "task_2": "mid"},
    "execution_plan": [["task_1"], ["task_2"]],
    "tasks": {
        "task_1": {"status": "COMPLETE", "verifier": "PASS",
                   "timing": {"started": "x", "completed": "y"}},
        "task_2": {"status": "IN_PROGRESS"},
    },
}

FRESH = {
    "status": "RUNNING",
    "timestamps": {"started_at": "2026-06-04T12:00:00Z", "completed_at": None},
    "current_task": None,
    "risk_levels": {},
    "execution_plan": [],
    "tasks": {},
}

# status=COMPLETE, all tasks terminal, but task_10 verifier still PENDING_BATCH
# and completed_at null -> finalize_run blocks.
SOURCE_MATCHING_BAD = {
    "status": "COMPLETE",
    "last_completed_at": "2026-06-04T23:04:22.658323",
    "timestamps": {"started_at": "2026-06-04T12:06:54Z", "completed_at": None},
    "cost_ledger": {"totals": {"dispatches": 0}},
    "dispatch_config": {"mode": "interactive_attached"},
    "current_task": 10,
    "last_completed_task": 10,
    "risk_levels": {"task_9": "low", "task_10": "mid"},
    "execution_plan": [["task_9"], ["task_10"]],
    "tasks": {
        "task_9": {"status": "COMPLETE", "verifier": "PASS",
                   "timing": {"completed": "z"}},
        "task_10": {"status": "COMPLETE", "verifier": "PENDING_BATCH",
                    "timing": {"completed": "z"}},
    },
}

# status=null, current_task=null, last_completed_task set, completed_at set, but
# tasks{} empty while risk_levels declares 12 -> validate_state_schema blocks.
READMATES_BAD = {
    "status": None,
    "current_task": None,
    "last_completed_task": "task_D2",
    "timestamps": {"started_at": "2026-06-04T10:00:00Z",
                   "completed_at": "2026-06-04T11:00:00Z"},
    "dispatch_config": {"mode": "interactive_attached"},
    "cost_ledger": {"totals": {"dispatches": 3}},
    "execution_order": ["task_A1", "task_D2"],
    "risk_levels": {f"task_{i}": "low" for i in range(12)},
    "task_summaries": {"task_D2": {"status": "COMPLETE"}},
    "tasks": {},
}


def test_clean_finalized_allows_stop(tmp_path):
    r = _run(_hook(tmp_path), _state(tmp_path, CLEAN_FINALIZED))
    assert r.returncode == 0, r.stderr


def test_mid_run_allows_stop(tmp_path):
    r = _run(_hook(tmp_path), _state(tmp_path, MID_RUN))
    assert r.returncode == 0, r.stderr


def test_fresh_run_allows_stop(tmp_path):
    r = _run(_hook(tmp_path), _state(tmp_path, FRESH))
    assert r.returncode == 0, r.stderr


def test_source_matching_unfinalized_blocks_stop(tmp_path):
    r = _run(_hook(tmp_path), _state(tmp_path, SOURCE_MATCHING_BAD))
    assert r.returncode == 2, r.stdout
    assert "finalization gate" in r.stderr.lower()


def test_readmates_non_canonical_blocks_stop(tmp_path):
    r = _run(_hook(tmp_path), _state(tmp_path, READMATES_BAD))
    assert r.returncode == 2, r.stdout
    assert "finalization gate" in r.stderr.lower()


def test_missing_state_fails_open(tmp_path):
    hook = _hook(tmp_path)
    r = subprocess.run(
        [hook, str(tmp_path / "does-not-exist.json"), SCRIPTS_DIR],
        input="{}", capture_output=True, text=True,
    )
    assert r.returncode == 0


def test_missing_scripts_arg_fails_open(tmp_path):
    hook = _hook(tmp_path)
    r = subprocess.run(
        [hook, _state(tmp_path, SOURCE_MATCHING_BAD)],
        input="{}", capture_output=True, text=True,
    )
    assert r.returncode == 0


# v2.27: canonical + finalized EXCEPT bookkeeping drift (dispatches 0, all tasks
# null timing.started, not waived). Before the v2.27 finalize severities this
# finalized green; after them the Stop gate must block it.
DRIFT_ONLY = {
    "status": "COMPLETE",
    "schema_version": "2",
    "mode": "interactive_attached",
    "timestamps": {"started_at": "2026-06-06T10:00:00Z",
                   "completed_at": "2026-06-06T11:00:00Z"},
    "cost_ledger": {"totals": {"dispatches": 0}},
    "dispatch_config": {"mode": "interactive_attached"},
    "risk_levels": {"task_1": "low", "task_2": "low"},
    "execution_plan": [["task_1"], ["task_2"]],
    "tasks": {
        "task_1": {"status": "COMPLETE", "verifier": "PASS", "timing": {"completed": "c"}},
        "task_2": {"status": "COMPLETE", "verifier": "PASS", "timing": {"completed": "c"}},
    },
}

DRIFT_WAIVED = dict(
    DRIFT_ONLY, cost_tracking_waived=True, timing_tracking_waived=True,
)


def test_drift_only_blocks_stop(tmp_path):
    r = _run(_hook(tmp_path), _state(tmp_path, DRIFT_ONLY))
    assert r.returncode == 2, r.stdout
    assert "finalization gate" in r.stderr.lower()


def test_drift_waived_allows_stop(tmp_path):
    r = _run(_hook(tmp_path), _state(tmp_path, DRIFT_WAIVED))
    assert r.returncode == 0, r.stderr


# v2.27 (D003): canonical + finalized + bookkept run, but the worktree
# settings.json was never wired with the safety hooks (the run-2 hand-write
# shape: $schema + permissions, no hooks). The finalize backstop must block the
# stop; the hooks_wiring_waived hatch must reach back through the gate.
def _unwired_worktree(tmp_path, *, hooks=False):
    wt = tmp_path / "wt"
    (wt / ".claude").mkdir(parents=True)
    settings = {"$schema": "x", "permissions": {"allow": []}}
    (wt / ".claude" / "settings.json").write_text(
        json.dumps(settings), encoding="utf-8")
    return str(wt)


def test_unwired_hooks_blocks_stop(tmp_path):
    state = dict(CLEAN_FINALIZED, worktree=_unwired_worktree(tmp_path))
    r = _run(_hook(tmp_path), _state(tmp_path, state))
    assert r.returncode == 2, r.stdout
    assert "finalization gate" in r.stderr.lower()


def test_unwired_hooks_waived_allows_stop(tmp_path):
    state = dict(CLEAN_FINALIZED, worktree=_unwired_worktree(tmp_path),
                 hooks_wiring_waived=True)
    r = _run(_hook(tmp_path), _state(tmp_path, state))
    assert r.returncode == 0, r.stderr


# v2.28 (D002): the run-3 shape — every task terminal, but status:null and
# current_task still set (Phase 2 never ran). Matches neither prose end-signal;
# the v2.28 all-terminal trigger must still force the gate -> exit 2.
RUN3_ALL_TERMINAL_UNFINALIZED = {
    "status": None,
    "schema_version": "2",
    "mode": "interactive_attached",
    "timestamps": {"started_at": "2026-06-06T11:57:00Z", "completed_at": None},
    "cost_ledger": {"totals": {"dispatches": 0}},
    "dispatch_config": {"mode": "interactive_attached"},
    "current_task": 2,
    "last_completed_task": None,
    "risk_levels": {"task_1": "low", "task_2": "low"},
    "execution_plan": [["task_1"], ["task_2"]],
    "tasks": {
        "task_1": {"status": "COMPLETE", "verifier": "PASS",
                   "timing": {"started": "x", "completed": "y"}},
        "task_2": {"status": "COMPLETE", "verifier": "PASS",
                   "timing": {"started": "x", "completed": "y"}},
    },
}


def test_all_terminal_unfinalized_blocks_stop(tmp_path):
    r = _run(_hook(tmp_path), _state(tmp_path, RUN3_ALL_TERMINAL_UNFINALIZED))
    assert r.returncode == 2, r.stdout
    assert "finalization gate" in r.stderr.lower()


# --- v2.28 regression replay: drive the gate against the REAL captured runs ----
# scripts/fixtures/v2.28/ holds verbatim post-v2.27 state.json snapshots. Both
# run-2 and run-3 are all-terminal; the gate must force finalization on the
# unfinalized ones. These reuse the same subprocess harness as the synthetic
# tests above, but point it at the real captured shapes — the strongest possible
# proof the Stop gate catches what slipped through before.
_REAL_FIX = os.path.join(SCRIPTS_DIR, "fixtures", "v2.28")


def _real(name):
    with open(os.path.join(_REAL_FIX, name), encoding="utf-8") as fh:
        return json.load(fh)


def test_replay_run3_all_terminal_unfinalized_blocks_stop(tmp_path):
    # run-3 was captured all-terminal but with status:null / current_task still set
    # and Phase 2 never run — exactly the structural gap D002 closes. It is ALSO
    # genuinely unfinalized (cost_dispatches_zero + tasks 1-5 timing_inverted), so
    # finalize_run --check fails. The gate must block the stop. Drive the REAL
    # fixture verbatim (no edits) — it already exhibits the all-terminal-unfinalized
    # condition.
    r = _run(_hook(tmp_path), _state(tmp_path, _real("run3_session_package.json")))
    assert r.returncode == 2, r.stdout
    assert "finalization gate" in r.stderr.lower()
    assert "timing_inverted" in r.stderr  # the honest defect surfaced by the gate


def test_replay_run2_all_terminal_unfinalized_blocks_stop(tmp_path):
    # run-2 (readmates chain) was captured already FINALIZED on its active plan_chain
    # tree (all tasks terminal, completed_at stamped, cost waived) so the gate would
    # correctly exit 0 on the verbatim fixture. To replay the all-terminal-UNfinalized
    # condition the gate is meant to catch, strip the finalization marker honestly
    # (null out timestamps.completed_at) — mirroring how Task 2's RUN3_ALL_TERMINAL
    # fixture constructs the same done-but-unfinalized shape. The active tree's tasks
    # stay all-terminal, so the structural trigger still fires and finalize_run now
    # flags completed_at_null -> exit 2.
    state = _real("run2_readmates_chain.json")
    state.setdefault("timestamps", {})["completed_at"] = None  # strip finalization marker
    r = _run(_hook(tmp_path), _state(tmp_path, state))
    assert r.returncode == 2, r.stdout
    assert "finalization gate" in r.stderr.lower()
    assert "completed_at_null" in r.stderr  # the stripped marker is the honest blocker
