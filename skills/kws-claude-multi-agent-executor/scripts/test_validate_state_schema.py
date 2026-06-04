"""Tests for validate_state_schema.py — canonical state.json shape checks."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import validate_state_schema as vss  # noqa: E402


def _write(tmp_path, data):
    p = tmp_path / "state.json"
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return p


CANONICAL_SINGLE = {
    "schema_version": "2",
    "mode": "interactive_attached",
    "dispatch_config": {"final_sweep": "agent"},
    "cost_ledger": {"totals": {"dispatches": 3}},
    "risk_levels": {"task_1": "low", "task_2": "mid"},
    "execution_plan": [{"wave": 0, "parallel_groups": [["task_1"]]}],
    "tasks": {
        "task_1": {"status": "COMPLETE"},
        "task_2": {"status": "COMPLETE"},
    },
}

# The actual readmates-member-reading-experience-20260604 divergence.
READMATES_BAD = {
    "schema_version": "2",
    "mode": "interactive_attached",
    "risk_levels": {"task_A1": "low", "task_B2": "high", "task_D1": "verify"},
    "execution_order": ["task_A1", "task_B2", "task_D1"],
    "tasks": {},
    "task_summaries": {
        "task_A1": {"status": "DONE"},
        "task_B2": {"status": "DONE"},
        "task_D1": {"status": "DONE"},
    },
}


def test_canonical_single_plan_passes(tmp_path):
    p = _write(tmp_path, CANONICAL_SINGLE)
    result = vss.validate(json.loads(p.read_text()))
    assert result["passed"] is True
    assert result["violations"] == []


def test_readmates_shape_flags_empty_tasks(tmp_path):
    result = vss.validate(READMATES_BAD)
    assert result["passed"] is False
    codes = {v["code"] for v in result["violations"]}
    assert "tasks_empty_but_declared" in codes
    assert "execution_order_without_plan" in codes
    assert "risk_value_invalid" in codes


def test_readmates_missing_runlevel_fields(tmp_path):
    result = vss.validate(READMATES_BAD)
    codes = {v["code"] for v in result["violations"]}
    assert "missing_dispatch_config" in codes
    assert "missing_cost_ledger" in codes


def test_invalid_mode_flagged(tmp_path):
    bad = dict(CANONICAL_SINGLE, mode="nonsense_mode")
    result = vss.validate(bad)
    codes = {v["code"] for v in result["violations"]}
    assert "mode_invalid" in codes


def test_multi_plan_chain_per_tree(tmp_path):
    multi = {
        "schema_version": "2",
        "mode": "plan_chain_running",
        "dispatch_config": {}, "cost_ledger": {"totals": {"dispatches": 1}},
        "active_plan": 0,
        "plan_chain": [
            {"risk_levels": {"t1": "low"}, "execution_plan": [], "tasks": {"t1": {"status": "COMPLETE"}}},
            {"risk_levels": {"t2": "mid"}, "execution_order": ["t2"], "tasks": {},
             "task_summaries": {"t2": {"status": "DONE"}}},
        ],
    }
    result = vss.validate(multi)
    assert result["passed"] is False
    # the violation must be attributed to plan_chain[1]
    assert any(v["scope"] == "plan_chain[1]" and v["code"] == "tasks_empty_but_declared"
               for v in result["violations"])


def test_exit_code_broken_state(tmp_path):
    p = tmp_path / "broken.json"
    p.write_text("{not json", encoding="utf-8")
    assert vss.main(["--state", str(p)]) == 2


def test_exit_code_pass_and_fail(tmp_path):
    good = _write(tmp_path, CANONICAL_SINGLE)
    assert vss.main(["--state", str(good)]) == 0
    bad = _write(tmp_path, READMATES_BAD)
    assert vss.main(["--state", str(bad)]) == 1
