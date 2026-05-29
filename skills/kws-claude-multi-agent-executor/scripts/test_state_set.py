"""Tests for state_set.py — active-tree resolution, value modes, flock, readback."""
import json
import os
import subprocess
import sys
import threading

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import state_set as ss  # noqa: E402

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state_set.py")


def _write(tmp_path, data):
    p = tmp_path / "state.json"
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return p


def _read(p):
    return json.loads(p.read_text(encoding="utf-8"))


# --- active-tree resolution ------------------------------------------------

def test_single_plan_writes_top_level(tmp_path):
    p = _write(tmp_path, {"schema_version": "2", "tasks": {}})
    ss.state_set(p, "tasks.task_0.status", "value", "completed", "active")
    assert _read(p)["tasks"]["task_0"]["status"] == "completed"


def test_multi_plan_writes_into_active_chain_entry(tmp_path):
    p = _write(tmp_path, {
        "schema_version": "2",
        "active_plan": 1,
        "plan_chain": [{"tasks": {}}, {"tasks": {}}],
    })
    ss.state_set(p, "tasks.task_0.status", "value", "completed", "active")
    st = _read(p)
    assert st["plan_chain"][1]["tasks"]["task_0"]["status"] == "completed"
    # plan 0 untouched
    assert st["plan_chain"][0]["tasks"] == {}


def test_legacy_plan2_state_branch(tmp_path):
    p = _write(tmp_path, {"schema_version": "2", "active_plan": "plan2", "plan2_state": {}})
    ss.state_set(p, "tasks.task_0.status", "value", "x", "active")
    assert _read(p)["plan2_state"]["tasks"]["task_0"]["status"] == "x"


def test_active_plan1_string_is_top_level(tmp_path):
    p = _write(tmp_path, {"schema_version": "2", "active_plan": "plan1", "tasks": {}})
    ss.state_set(p, "tasks.task_0.status", "value", "x", "active")
    assert _read(p)["tasks"]["task_0"]["status"] == "x"


def test_run_scope_forces_top_level(tmp_path):
    p = _write(tmp_path, {
        "schema_version": "2", "active_plan": 0, "plan_chain": [{"tasks": {}}],
    })
    ss.state_set(p, "timestamps.completed_at", "now", None, "run")
    st = _read(p)
    assert "completed_at" in st["timestamps"]
    assert "timestamps" not in st["plan_chain"][0]


def test_leading_state_dot_forces_top_level(tmp_path):
    p = _write(tmp_path, {
        "schema_version": "2", "active_plan": 0, "plan_chain": [{}],
    })
    ss.state_set(p, "state.mode", "value", "headless_running", "active")
    st = _read(p)
    assert st["mode"] == "headless_running"
    assert "mode" not in st["plan_chain"][0]


def test_plan_chain_index_out_of_range_raises(tmp_path):
    p = _write(tmp_path, {"schema_version": "2", "active_plan": 5, "plan_chain": [{}]})
    with pytest.raises(ValueError):
        ss.state_set(p, "tasks.x", "value", 1, "active")


# --- dotted list-index paths (regression: plan_chain collapse) -------------

def test_dotted_list_index_does_not_collapse_chain(tmp_path):
    """Regression: `plan_chain.0.status` once replaced the whole list with a
    dict and dropped plan 0's data. It must navigate the list element instead."""
    p = _write(tmp_path, {
        "schema_version": "2",
        "active_plan": 1,
        "plan_chain": [
            {"tasks": {"task_0": {"status": "COMPLETE"}}},
            {"tasks": {}},
        ],
    })
    ss.state_set(p, "plan_chain.0.status", "value", "done", "run")
    st = _read(p)
    # plan_chain stays a list; element 0 keeps its data and gains the new field.
    assert isinstance(st["plan_chain"], list)
    assert st["plan_chain"][0]["tasks"]["task_0"]["status"] == "COMPLETE"
    assert st["plan_chain"][0]["status"] == "done"
    assert st["plan_chain"][1]["tasks"] == {}


def test_dotted_index_writes_non_active_plan_field(tmp_path):
    """Cross-Plan Trigger writes plan_chain[i+1].baseline while i is active."""
    p = _write(tmp_path, {
        "schema_version": "2",
        "active_plan": 0,
        "plan_chain": [{"tasks": {}}, {"tasks": {}}],
    })
    ss.state_set(p, "plan_chain.1.baseline.score", "value", 7, "run")
    st = _read(p)
    assert st["plan_chain"][1]["baseline"]["score"] == 7
    assert "baseline" not in st["plan_chain"][0]


def test_dotted_list_index_out_of_range_raises(tmp_path):
    p = _write(tmp_path, {"schema_version": "2", "plan_chain": [{}]})
    with pytest.raises(ValueError):
        ss.state_set(p, "plan_chain.3.x", "value", 1, "run")


def test_non_integer_segment_against_list_raises(tmp_path):
    p = _write(tmp_path, {"schema_version": "2", "plan_chain": [{}]})
    with pytest.raises(ValueError):
        ss.state_set(p, "plan_chain.foo.x", "value", 1, "run")


def test_descending_into_scalar_raises_not_clobbers(tmp_path):
    """An existing scalar intermediate must never be silently replaced."""
    p = _write(tmp_path, {"schema_version": "2", "mode": "headless_running"})
    with pytest.raises(ValueError):
        ss.state_set(p, "mode.sub.field", "value", 1, "run")
    # original scalar preserved
    assert _read(p)["mode"] == "headless_running"


# --- value modes -----------------------------------------------------------

def test_now_sets_iso_timestamp(tmp_path):
    p = _write(tmp_path, {"schema_version": "2"})
    val = ss.state_set(p, "ts", "now", None, "run")
    assert val.endswith("Z") and "T" in val


def test_inc_from_missing_treats_as_zero(tmp_path):
    p = _write(tmp_path, {"schema_version": "2"})
    val = ss.state_set(p, "counter", "inc", 3, "run")
    assert val == 3


def test_inc_accumulates(tmp_path):
    p = _write(tmp_path, {"schema_version": "2", "counter": 10})
    val = ss.state_set(p, "counter", "inc", 5, "run")
    assert val == 15


def test_append_from_missing_creates_list(tmp_path):
    p = _write(tmp_path, {"schema_version": "2"})
    ss.state_set(p, "events", "append", {"a": 1}, "run")
    val = ss.state_set(p, "events", "append", {"b": 2}, "run")
    assert val == [{"a": 1}, {"b": 2}]


def test_setdefault_writes_when_absent(tmp_path):
    p = _write(tmp_path, {"schema_version": "2"})
    val = ss.state_set(p, "budget_cap_usd", "setdefault", 5.0, "run")
    assert val == 5.0


def test_setdefault_preserves_existing(tmp_path):
    p = _write(tmp_path, {"schema_version": "2", "budget_cap_usd": 9.0})
    val = ss.state_set(p, "budget_cap_usd", "setdefault", 5.0, "run")
    assert val == 9.0


def test_missing_intermediate_path_autocreates_objects(tmp_path):
    p = _write(tmp_path, {"schema_version": "2", "tasks": {}})
    ss.state_set(p, "tasks.task_3.timing.completed", "now", None, "active")
    st = _read(p)
    assert isinstance(st["tasks"]["task_3"]["timing"]["completed"], str)


# --- readback --------------------------------------------------------------

def test_readback_failure_raises(tmp_path, monkeypatch):
    p = _write(tmp_path, {"schema_version": "2", "tasks": {}})
    monkeypatch.setattr(ss, "_atomic_write_json", lambda path, data: None)
    with pytest.raises(RuntimeError):
        ss.state_set(p, "tasks.task_0.status", "value", "x", "active")


# --- flock concurrency -----------------------------------------------------

def test_concurrent_increments_serialize(tmp_path):
    p = _write(tmp_path, {"schema_version": "2", "counter": 0})
    n = 20

    def worker():
        subprocess.run(
            [sys.executable, SCRIPT, "--state", str(p),
             "--field", "counter", "--inc", "1", "--plan-scope", "run"],
            check=True, capture_output=True,
        )

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert _read(p)["counter"] == n


# --- CLI -------------------------------------------------------------------

def test_cli_value_roundtrip(tmp_path):
    p = _write(tmp_path, {"schema_version": "2", "tasks": {}})
    r = subprocess.run(
        [sys.executable, SCRIPT, "--state", str(p),
         "--field", "tasks.task_0.status", "--value", '"completed"'],
        capture_output=True, text=True,
    )
    assert r.returncode == 0
    assert _read(p)["tasks"]["task_0"]["status"] == "completed"


def test_cli_missing_state_exits_nonzero(tmp_path):
    r = subprocess.run(
        [sys.executable, SCRIPT, "--state", str(tmp_path / "nope.json"),
         "--field", "x", "--now"],
        capture_output=True, text=True,
    )
    assert r.returncode == 1


def test_cli_inc_rejects_non_number(tmp_path):
    p = _write(tmp_path, {"schema_version": "2"})
    r = subprocess.run(
        [sys.executable, SCRIPT, "--state", str(p),
         "--field", "c", "--inc", '"x"', "--plan-scope", "run"],
        capture_output=True, text=True,
    )
    assert r.returncode == 1
