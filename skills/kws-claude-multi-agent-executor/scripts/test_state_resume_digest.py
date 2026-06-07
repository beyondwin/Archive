"""Tests for state_resume_digest.py (v2.29 — I10).

The digest returns only live counters + pointers so a resumed session can boot
from the digest + plan instead of loading the full state.json.
"""
import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import state_resume_digest as srd  # noqa: E402

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state_resume_digest.py")


def _write(tmp_path, data):
    p = tmp_path / "state.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _single():
    return {
        "schema_version": "2", "mode": "interactive_attached", "active_plan": "plan1",
        "worktree": "/wt/r", "orchestrator_dir": "/orch/r", "test_command": "pytest -q",
        "current_task": 7, "current_step_within_task": 1, "last_completed_task": "task_6",
        "low_tasks_pending_verification": ["task_3"],
        "verification_gaps": [{"task": "task_5"}], "docs_gaps": [],
        "tasks": {
            "task_0": {"status": "COMPLETE"}, "task_1": {"status": "COMPLETE"},
            "task_5": {"status": "SKIPPED"}, "task_6": {"status": "COMPLETE"},
            "task_7": {"status": "IN_PROGRESS"},
        },
    }


def test_digest_single_plan_fields():
    d = srd.build_digest(_single())
    assert d["mode"] == "interactive_attached"
    assert d["active_plan"] == "plan1"
    assert d["current_task"] == 7
    assert d["current_step_within_task"] == 1
    assert d["last_completed_task"] == "task_6"
    assert d["worktree"] == "/wt/r"
    assert d["orchestrator_dir"] == "/orch/r"
    assert d["test_command"] == "pytest -q"


def test_digest_counts_and_gaps():
    d = srd.build_digest(_single())
    assert d["tasks_total"] == 5
    assert d["tasks_done"] == 3        # task_0, task_1, task_6
    assert d["tasks_skipped"] == 1     # task_5
    assert d["pending_verification"] == ["task_3"]
    assert d["gaps"] == {"verification": 1, "docs": 0}


def test_digest_multi_plan_resolves_active():
    state = {
        "schema_version": "2", "mode": "plan_chain_running", "active_plan": 1,
        "worktree": "/wt/r", "orchestrator_dir": "/orch/r", "test_command": "t",
        "current_task": 2,
        "plan_chain": [
            {"tasks": {"task_0": {"status": "COMPLETE"}}, "low_tasks_pending_verification": [],
             "verification_gaps": [], "docs_gaps": []},
            {"tasks": {"task_0": {"status": "COMPLETE"}, "task_1": {"status": "COMPLETE"},
                       "task_2": {"status": "PENDING"}},
             "low_tasks_pending_verification": ["task_0"],
             "last_completed_task": "task_1",
             "verification_gaps": [], "docs_gaps": [{"scope": "README"}]},
        ],
    }
    d = srd.build_digest(state)
    assert d["active_plan"] == 1
    assert d["tasks_total"] == 3       # active plan (index 1) only
    assert d["tasks_done"] == 2
    assert d["last_completed_task"] == "task_1"
    assert d["pending_verification"] == ["task_0"]
    assert d["gaps"] == {"verification": 0, "docs": 1}


def test_digest_is_compact_no_full_task_bodies():
    # The whole point: the digest must not embed full task dicts.
    d = srd.build_digest(_single())
    blob = json.dumps(d)
    assert "IN_PROGRESS" not in blob   # task status bodies not embedded
    assert "tasks" not in d            # no raw tasks map


# --- CLI -------------------------------------------------------------------

def test_cli_emits_json_exit_0(tmp_path):
    p = _write(tmp_path, _single())
    r = subprocess.run([sys.executable, SCRIPT, str(p)], capture_output=True, text=True)
    assert r.returncode == 0
    parsed = json.loads(r.stdout)
    assert parsed["current_task"] == 7


def test_cli_missing_state_exit_2(tmp_path):
    r = subprocess.run([sys.executable, SCRIPT, str(tmp_path / "nope.json")],
                       capture_output=True, text=True)
    assert r.returncode == 2
