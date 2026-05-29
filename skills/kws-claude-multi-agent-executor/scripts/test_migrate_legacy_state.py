"""Tests for migrate_legacy_state.py — the v2.12 plan2_state → plan_chain shim."""
import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import migrate_legacy_state as mig  # noqa: E402

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "migrate_legacy_state.py")


def _legacy_two_plan():
    """A representative v2.12 two-plan state.json mid-run on plan 2."""
    return {
        "schema_version": "2",
        "mode": "plan2_running",
        "active_plan": "plan2",
        "plan": "plans/p1.md",
        "spec": "specs/p1.md",
        "branch": "feat-123",
        "worktree": "/home/u/.claude/worktrees/feat-123",
        "test_command": "pytest",
        "implementer_model": {"used": "sonnet", "default": "sonnet"},
        # run-level cost/budget (must stay top-level, untouched)
        "cost_ledger": {"by_task": {"plan1::task_0::implementer": {}}, "by_role": {},
                        "by_model": {}, "totals": {"dispatches": 3, "cost_usd": 1.5}},
        "budget_cap_usd": None,
        "timestamps": {"started_at": "2026-01-01T00:00:00Z", "completed_at": None},
        "current_task": 1,
        "current_pre_task_sha": "abc",
        # plan 1's per-plan data lives at top level in v2.12
        "tasks": {"task_0": {"status": "COMPLETE", "commit": "c0"}},
        "task_summaries": {"task_0": {"key_decision": "did the thing"}},
        "quality_trend": [0.9],
        "baseline": {"passing": 10, "failing": 0},
        "risk_levels": {"task_0": "low"},
        "last_completed_task": "task_0",
        "plan_review": {"status": "PASS", "warnings": []},
        # plan 2's data lives under plan2_state
        "plan2_state": {
            "status": "running",
            "plan_path": "plans/p2.md",
            "spec_path": "specs/p2.md",
            "blocked_until": "task_0=COMPLETE",
            "tasks": {"task_0": {"status": "COMPLETE", "commit": "d0"}},
            "task_summaries": {},
            "quality_trend": [0.8],
            "baseline": {"passing": 11, "failing": 0},
            "risk_levels": {"task_0": "mid"},
        },
    }


# --- migrate() unit --------------------------------------------------------

def test_migrate_two_plan_builds_chain():
    st = _legacy_two_plan()
    changed, reason = mig.migrate(st)
    assert changed and reason == "migrated"
    assert "plan2_state" not in st
    assert isinstance(st["plan_chain"], list) and len(st["plan_chain"]) == 2
    assert st["active_plan"] == 1  # "plan2" → index 1


def test_migrate_plan0_gets_top_level_per_plan_data():
    st = _legacy_two_plan()
    mig.migrate(st)
    e0 = st["plan_chain"][0]
    assert e0["index"] == 0
    assert e0["plan_path"] == "plans/p1.md" and e0["spec_path"] == "specs/p1.md"
    assert e0["tasks"]["task_0"]["commit"] == "c0"
    assert e0["quality_trend"] == [0.9]
    assert e0["baseline"] == {"passing": 10, "failing": 0}
    # moved out of top level
    assert "tasks" not in st and "quality_trend" not in st and "baseline" not in st


def test_migrate_plan1_gets_plan2_state_data():
    st = _legacy_two_plan()
    mig.migrate(st)
    e1 = st["plan_chain"][1]
    assert e1["index"] == 1
    assert e1["plan_path"] == "plans/p2.md" and e1["spec_path"] == "specs/p2.md"
    assert e1["status"] == "running"
    assert e1["blocked_until"] == "task_0=COMPLETE"
    assert e1["tasks"]["task_0"]["commit"] == "d0"
    assert e1["risk_levels"] == {"task_0": "mid"}


def test_migrate_preserves_run_level_fields():
    st = _legacy_two_plan()
    mig.migrate(st)
    assert st["cost_ledger"]["totals"]["dispatches"] == 3
    assert st["timestamps"]["started_at"] == "2026-01-01T00:00:00Z"
    assert st["current_pre_task_sha"] == "abc"
    assert st["test_command"] == "pytest"


def test_migrate_missing_per_plan_field_gets_default():
    st = _legacy_two_plan()
    mig.migrate(st)
    # plan2_state had no execution_plan / global_constraints → defaults applied
    assert st["plan_chain"][1]["execution_plan"] == []
    assert st["plan_chain"][1]["global_constraints"] == {"shared_files": {}}
    assert st["plan_chain"][1]["last_compaction_after_task"] == -1


def test_migrate_idempotent_on_modern_chain():
    st = {"schema_version": "2", "plan_chain": [{"index": 0, "tasks": {}}], "active_plan": 0}
    changed, reason = mig.migrate(st)
    assert not changed and reason == "already-plan_chain"


def test_migrate_noop_single_plan():
    st = {"schema_version": "2", "tasks": {"task_0": {}}, "active_plan": "plan1",
          "plan2_state": None}
    changed, reason = mig.migrate(st)
    assert not changed and reason == "single-plan-no-plan2_state"
    assert "plan_chain" not in st
    assert st["tasks"]["task_0"] == {}  # untouched


def test_migrate_active_plan1_string_maps_to_zero():
    st = _legacy_two_plan()
    st["active_plan"] = "plan1"
    mig.migrate(st)
    assert st["active_plan"] == 0


def test_migrate_rejects_non_object_plan2_state():
    st = {"schema_version": "2", "plan2_state": "garbage"}
    with pytest.raises(ValueError):
        mig.migrate(st)


def test_chain_entries_do_not_alias_default():
    st = _legacy_two_plan()
    mig.migrate(st)
    st["plan_chain"][0]["execution_plan"].append("x")
    assert st["plan_chain"][1]["execution_plan"] == []  # independent objects


# --- CLI -------------------------------------------------------------------

def test_cli_migrates_file(tmp_path):
    p = tmp_path / "state.json"
    p.write_text(json.dumps(_legacy_two_plan()), encoding="utf-8")
    r = subprocess.run([sys.executable, SCRIPT, "--state", str(p)],
                       capture_output=True, text=True)
    assert r.returncode == 0
    assert json.loads(r.stdout)["changed"] is True
    st = json.loads(p.read_text(encoding="utf-8"))
    assert len(st["plan_chain"]) == 2 and "plan2_state" not in st
    # second run is a no-op
    r2 = subprocess.run([sys.executable, SCRIPT, "--state", str(p)],
                        capture_output=True, text=True)
    assert json.loads(r2.stdout)["changed"] is False


def test_cli_dry_run_does_not_write(tmp_path):
    p = tmp_path / "state.json"
    original = _legacy_two_plan()
    p.write_text(json.dumps(original), encoding="utf-8")
    r = subprocess.run([sys.executable, SCRIPT, "--state", str(p), "--dry-run"],
                       capture_output=True, text=True)
    assert r.returncode == 0
    out = json.loads(r.stdout)
    assert out["changed"] is True and out["dry_run"] is True
    # file unchanged
    assert json.loads(p.read_text(encoding="utf-8")) == original
