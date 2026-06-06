"""Tests for phase_boundary.py — boundary writes + emit isolation."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import phase_boundary as pb  # noqa: E402


@pytest.fixture(autouse=True)
def _no_real_emit(monkeypatch):
    """Capture emits instead of shelling out to the agentlens CLI."""
    calls = []
    monkeypatch.setattr(pb, "_emit", lambda run, etype, payload: calls.append((run, etype, payload)))
    return calls


def _write(tmp_path, data):
    p = tmp_path / "state.json"
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return p


def _read(p):
    return json.loads(p.read_text(encoding="utf-8"))


# --- task-start ------------------------------------------------------------

def test_task_start_stamps_pre_sha_and_started_single_plan(tmp_path):
    p = _write(tmp_path, {"schema_version": "2", "tasks": {}})
    pb.cmd_task_start(p, "task_3", "abc123")
    st = _read(p)
    assert st["current_pre_task_sha"] == "abc123"  # run-level
    assert st["tasks"]["task_3"]["timing"]["started"].endswith("Z")


def test_task_start_multi_plan_timing_in_active_pre_sha_run_level(tmp_path):
    p = _write(tmp_path, {
        "schema_version": "2", "active_plan": 1,
        "plan_chain": [{"tasks": {}}, {"tasks": {}}],
    })
    pb.cmd_task_start(p, "task_0", "deadbeef")
    st = _read(p)
    assert st["current_pre_task_sha"] == "deadbeef"  # top-level, not in chain
    assert "current_pre_task_sha" not in st["plan_chain"][1]
    assert st["plan_chain"][1]["tasks"]["task_0"]["timing"]["started"].endswith("Z")


# --- task-complete ---------------------------------------------------------

def test_task_complete_writes_result_and_forces_completed(tmp_path, _no_real_emit):
    p = _write(tmp_path, {"schema_version": "2", "tasks": {}})
    result = {"status": "COMPLETE", "risk": "mid", "review_tier": "PASS", "commit": "f00"}
    payload = pb.cmd_task_complete(p, "task_1", result, "run-xyz")
    st = _read(p)
    assert st["tasks"]["task_1"]["status"] == "COMPLETE"
    assert st["tasks"]["task_1"]["timing"]["completed"].endswith("Z")
    assert st["last_completed_task"] == "task_1"
    assert st["last_completed_at"].endswith("Z")
    # emit fired with derived payload
    assert _no_real_emit == [("run-xyz", "task_completed", payload and json.dumps(payload, ensure_ascii=False))]


def test_task_complete_multi_plan_pointers_in_active(tmp_path):
    p = _write(tmp_path, {
        "schema_version": "2", "active_plan": 0,
        "plan_chain": [{"tasks": {}, "last_completed_task": None}, {"tasks": {}}],
    })
    pb.cmd_task_complete(p, "task_2", {"status": "COMPLETE", "commit": "c"}, None)
    st = _read(p)
    assert st["plan_chain"][0]["tasks"]["task_2"]["status"] == "COMPLETE"
    assert st["plan_chain"][0]["last_completed_task"] == "task_2"
    assert "last_completed_task" not in st  # not written top-level


def test_task_complete_no_run_id_still_writes_state(tmp_path, _no_real_emit):
    p = _write(tmp_path, {"schema_version": "2", "tasks": {}})
    pb.cmd_task_complete(p, "task_0", {"status": "COMPLETE"}, None)
    assert _read(p)["tasks"]["task_0"]["status"] == "COMPLETE"
    # emit still called (helper decides to no-op on empty run id)
    assert _no_real_emit[0][0] is None


# --- task-complete: quality_trend writer (v2.28 D003) ----------------------

def test_task_complete_appends_quality_score_to_trend(tmp_path):
    p = _write(tmp_path, {"schema_version": "2", "tasks": {}})
    pb.cmd_task_complete(p, "task_1", {"status": "COMPLETE", "quality_score": 0.9}, None)
    assert _read(p)["quality_trend"] == [0.9]


def test_task_complete_quality_trend_caps_at_10(tmp_path):
    p = _write(tmp_path, {"schema_version": "2", "tasks": {},
                          "quality_trend": [0.1] * 10})
    pb.cmd_task_complete(p, "task_1", {"status": "COMPLETE", "quality_score": 0.95}, None)
    qt = _read(p)["quality_trend"]
    assert len(qt) == 10
    assert qt[-1] == 0.95 and qt[0] == 0.1  # oldest dropped, newest kept


def test_task_complete_no_quality_score_leaves_trend_untouched(tmp_path):
    p = _write(tmp_path, {"schema_version": "2", "tasks": {}, "quality_trend": [0.5]})
    pb.cmd_task_complete(p, "task_1", {"status": "COMPLETE"}, None)
    assert _read(p)["quality_trend"] == [0.5]


def test_task_complete_quality_trend_in_active_tree(tmp_path):
    p = _write(tmp_path, {"schema_version": "2", "active_plan": 1,
                          "plan_chain": [{"tasks": {}}, {"tasks": {}}]})
    pb.cmd_task_complete(p, "task_0", {"status": "COMPLETE", "quality_score": 0.8}, None)
    st = _read(p)
    assert st["plan_chain"][1]["quality_trend"] == [0.8]
    assert "quality_trend" not in st  # not written top-level


# --- phase-emit ------------------------------------------------------------

def test_phase_emit_phase_0_started_setdefaults_started_at(tmp_path, _no_real_emit):
    p = _write(tmp_path, {"schema_version": "2", "timestamps": {"started_at": None, "completed_at": None}})
    pb.cmd_phase_emit(p, "phase_0_started", "r1", '{"task_count":3}')
    st = _read(p)
    assert st["timestamps"]["started_at"].endswith("Z")
    assert _no_real_emit == [("r1", "phase_0_started", '{"task_count":3}')]


def test_phase_emit_phase_0_preserves_existing_started_at(tmp_path):
    p = _write(tmp_path, {"schema_version": "2", "timestamps": {"started_at": "2026-01-01T00:00:00Z"}})
    pb.cmd_phase_emit(p, "phase_0_started", "r1", None)
    assert _read(p)["timestamps"]["started_at"] == "2026-01-01T00:00:00Z"


def test_phase_emit_phase_2_complete_overwrites_completed_at(tmp_path):
    p = _write(tmp_path, {"schema_version": "2", "timestamps": {"completed_at": None}})
    pb.cmd_phase_emit(p, "phase_2_complete", "r1", None)
    assert _read(p)["timestamps"]["completed_at"].endswith("Z")


def test_phase_emit_compaction_emits_only_no_state_change(tmp_path, _no_real_emit):
    p = _write(tmp_path, {"schema_version": "2", "timestamps": {"started_at": "x", "completed_at": "y"}})
    before = _read(p)
    pb.cmd_phase_emit(p, "compaction", "r1", '{"after":2}')
    assert _read(p) == before
    assert _no_real_emit == [("r1", "compaction", '{"after":2}')]


def test_phase_emit_no_run_id_is_silent_noop(tmp_path, _no_real_emit):
    # _emit is monkeypatched, but verify None run id path still stamps timestamp
    p = _write(tmp_path, {"schema_version": "2", "timestamps": {}})
    pb.cmd_phase_emit(p, "phase_2_complete", None, None)
    assert _read(p)["timestamps"]["completed_at"].endswith("Z")


# --- emit isolation: a broken CLI must not fail the boundary ---------------

def test_emit_swallows_missing_cli(monkeypatch):
    # Real _emit with a bogus binary name → OSError swallowed, returns None.
    monkeypatch.setattr(pb.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(OSError("no cli")))
    assert pb._emit("r", "compaction", None) is None
