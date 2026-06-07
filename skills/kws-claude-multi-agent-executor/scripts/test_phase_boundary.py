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


# --- task-complete: preserve timing.started (v2.28 instrumentation-integrity) ---

def test_task_complete_preserves_started_from_task_start(tmp_path):
    p = _write(tmp_path, {"schema_version": "2", "tasks": {}})
    pb.cmd_task_start(p, "task_1", "deadbeef")
    pb.cmd_task_complete(p, "task_1", {"status": "COMPLETE"}, None)
    t = _read(p)["tasks"]["task_1"]
    assert t["timing"]["started"]            # preserved, not clobbered
    assert t["timing"]["completed"]          # set by task-complete
    assert t["status"] == "COMPLETE"


def test_task_complete_does_not_overwrite_result_started(tmp_path):
    # if the result itself already carries a started, keep that one (don't lose it)
    p = _write(tmp_path, {"schema_version": "2", "tasks": {}})
    pb.cmd_task_start(p, "task_1", "deadbeef")
    pb.cmd_task_complete(p, "task_1",
                         {"status": "COMPLETE", "timing": {"started": "2020-01-01T00:00:00Z"}}, None)
    t = _read(p)["tasks"]["task_1"]
    assert t["timing"]["started"] == "2020-01-01T00:00:00Z"  # explicit result value wins


def test_task_complete_no_prior_started_is_fine(tmp_path):
    # task-complete without a preceding task-start: no started, but no crash, completed set
    p = _write(tmp_path, {"schema_version": "2", "tasks": {}})
    pb.cmd_task_complete(p, "task_1", {"status": "COMPLETE"}, None)
    t = _read(p)["tasks"]["task_1"]
    assert t["timing"].get("started") is None
    assert t["timing"]["completed"]


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


# --- I2: local events.jsonl tee (orchestrator single writer) ---------------

def _events(tmp_path):
    f = tmp_path / "events.jsonl"
    if not f.exists():
        return []
    return [json.loads(line) for line in f.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_task_complete_tees_event_to_events_jsonl(tmp_path):
    p = _write(tmp_path, {"schema_version": "2", "tasks": {}})
    pb.cmd_task_complete(p, "task_1", {"status": "COMPLETE", "commit": "f00"}, "run-x")
    evs = _events(tmp_path)
    assert len(evs) == 1
    assert evs[0]["type"] == "kws-cme.task_completed"
    assert evs[0]["payload"]["task"] == "task_1"
    assert evs[0]["ts"].endswith("Z")


def test_task_complete_tees_even_when_agentlens_absent(tmp_path):
    # run_id None means the AgentLens emit no-ops, but the local tee MUST still fire.
    p = _write(tmp_path, {"schema_version": "2", "tasks": {}})
    pb.cmd_task_complete(p, "task_0", {"status": "COMPLETE"}, None)
    evs = _events(tmp_path)
    assert len(evs) == 1 and evs[0]["type"] == "kws-cme.task_completed"


def test_phase_emit_tees_timeline_in_order(tmp_path):
    p = _write(tmp_path, {"schema_version": "2", "timestamps": {}})
    pb.cmd_phase_emit(p, "phase_0_started", None, '{"task_count":3}')
    pb.cmd_phase_emit(p, "compaction", None, '{"after":1}')
    pb.cmd_phase_emit(p, "phase_2_complete", None, None)
    types = [e["type"] for e in _events(tmp_path)]
    assert types == ["kws-cme.phase_0_started", "kws-cme.compaction", "kws-cme.phase_2_complete"]


def test_emit_subcommand_tees_arbitrary_type(tmp_path, _no_real_emit):
    p = _write(tmp_path, {"schema_version": "2", "tasks": {}})
    pb.cmd_emit(p, "blocker", "run-x", '{"task":"task_7","reason":"review_retries_exhausted"}')
    evs = _events(tmp_path)
    assert evs[0]["type"] == "kws-cme.blocker"
    assert evs[0]["payload"]["reason"] == "review_retries_exhausted"
    # still routes the best-effort AgentLens emit
    assert _no_real_emit == [("run-x", "blocker", '{"task":"task_7","reason":"review_retries_exhausted"}')]


def test_emit_subcommand_does_not_touch_state(tmp_path):
    p = _write(tmp_path, {"schema_version": "2", "tasks": {}})
    before = _read(p)
    pb.cmd_emit(p, "blocker", None, '{"task":"task_1"}')
    assert _read(p) == before


def test_tee_event_best_effort_on_bad_dir(tmp_path):
    # A non-writable / nonexistent orch dir must not raise (observability never blocks).
    bad = tmp_path / "does" / "not" / "exist"
    pb._tee_event(bad, "compaction", None)  # should silently no-op, not raise


def test_tee_event_keeps_non_json_payload_as_raw(tmp_path):
    pb._tee_event(tmp_path, "compaction", "not-json")
    assert _events(tmp_path)[0]["payload"] == "not-json"


# --- I3: per-task retry_trace[] (append-only audit log) --------------------

def test_retry_trace_appends_entry_single_plan(tmp_path):
    p = _write(tmp_path, {"schema_version": "2", "tasks": {}})
    pb.cmd_retry_trace(p, "task_3", "review", "spec_unclear", "WARN",
                       ["src/a.ts:42:logic"], None)
    tr = _read(p)["tasks"]["task_3"]["retry_trace"]
    assert len(tr) == 1
    e = tr[0]
    assert e["kind"] == "review" and e["fault"] == "spec_unclear"
    assert e["tier"] == "WARN" and e["recurring_keys"] == ["src/a.ts:42:logic"]
    assert e["attempt"] == 1 and e["ts"].endswith("Z")


def test_retry_trace_is_append_only_and_ordered(tmp_path):
    p = _write(tmp_path, {"schema_version": "2", "tasks": {}})
    pb.cmd_retry_trace(p, "task_1", "review", "implementer_omitted", "FAIL", None, None)
    pb.cmd_retry_trace(p, "task_1", "review", "spec_unclear", "FAIL", None, None)
    tr = _read(p)["tasks"]["task_1"]["retry_trace"]
    assert [e["attempt"] for e in tr] == [1, 2]  # auto-increment per kind, preserved order
    assert [e["fault"] for e in tr] == ["implementer_omitted", "spec_unclear"]


def test_retry_trace_attempt_increments_per_kind(tmp_path):
    p = _write(tmp_path, {"schema_version": "2", "tasks": {}})
    pb.cmd_retry_trace(p, "task_1", "review", "f", None, None, None)
    pb.cmd_retry_trace(p, "task_1", "verify", "test_fail", None, None, None)
    pb.cmd_retry_trace(p, "task_1", "verify", "test_fail", None, None, None)
    tr = _read(p)["tasks"]["task_1"]["retry_trace"]
    by_kind = [(e["kind"], e["attempt"]) for e in tr]
    assert by_kind == [("review", 1), ("verify", 1), ("verify", 2)]


def test_retry_trace_explicit_attempt_honored(tmp_path):
    p = _write(tmp_path, {"schema_version": "2", "tasks": {}})
    pb.cmd_retry_trace(p, "task_1", "review", "f", "WARN", None, 3)
    assert _read(p)["tasks"]["task_1"]["retry_trace"][0]["attempt"] == 3


def test_retry_trace_recurring_keys_default_empty(tmp_path):
    p = _write(tmp_path, {"schema_version": "2", "tasks": {}})
    pb.cmd_retry_trace(p, "task_1", "verify", "test_fail", None, None, None)
    assert _read(p)["tasks"]["task_1"]["retry_trace"][0]["recurring_keys"] == []


def test_retry_trace_multi_plan_writes_to_active(tmp_path):
    p = _write(tmp_path, {"schema_version": "2", "active_plan": 1,
                          "plan_chain": [{"tasks": {}}, {"tasks": {}}]})
    pb.cmd_retry_trace(p, "task_0", "review", "f", "WARN", None, None)
    st = _read(p)
    assert st["plan_chain"][1]["tasks"]["task_0"]["retry_trace"][0]["kind"] == "review"
    assert "tasks" in st["plan_chain"][0] and st["plan_chain"][0]["tasks"] == {}


def test_retry_trace_preserved_across_task_complete(tmp_path):
    # task-complete replaces the task entry with the result object; an existing
    # retry_trace must survive (it is an audit log, not transient).
    p = _write(tmp_path, {"schema_version": "2", "tasks": {}})
    pb.cmd_retry_trace(p, "task_1", "review", "f", "FAIL", None, None)
    pb.cmd_task_complete(p, "task_1", {"status": "COMPLETE", "commit": "c"}, None)
    t = _read(p)["tasks"]["task_1"]
    assert t["status"] == "COMPLETE"
    assert len(t["retry_trace"]) == 1 and t["retry_trace"][0]["fault"] == "f"
