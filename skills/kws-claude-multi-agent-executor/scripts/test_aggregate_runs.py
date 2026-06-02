import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import aggregate_runs as ar


def test_flatten_tasks_single_plan():
    state = {
        "tasks": {
            "task_1": {"status": "COMPLETE", "review_tier": "PASS",
                       "review_retries": 0, "verifier_retries": 0, "escalation_count": 0},
            "task_2": {"status": "COMPLETE", "review_tier": "WARN",
                       "review_retries": 1, "verifier_retries": 2, "escalation_count": 0},
        },
        "risk_levels": {"task_1": "LOW", "task_2": "MID"},
    }
    recs = ar.flatten_tasks(state)
    by_id = {r["task_id"]: r for r in recs}
    assert by_id["task_1"]["risk"] == "LOW"
    assert by_id["task_1"]["plan_index"] == 0
    assert by_id["task_2"]["risk"] == "MID"
    assert by_id["task_2"]["verifier_retries"] == 2


def test_flatten_tasks_plan_chain():
    state = {
        "plan_chain": [
            {"tasks": {"task_1": {"status": "COMPLETE", "review_tier": "PASS",
                                  "review_retries": 0, "verifier_retries": 0,
                                  "escalation_count": 0}},
             "risk_levels": {"task_1": "LOW"}},
            {"tasks": {"task_1": {"status": "COMPLETE", "review_tier": "FAIL",
                                  "review_retries": 3, "verifier_retries": 1,
                                  "escalation_count": 1}},
             "risk_levels": {"task_1": "HIGH"}},
        ]
    }
    recs = ar.flatten_tasks(state)
    assert len(recs) == 2
    assert {r["plan_index"] for r in recs} == {0, 1}
    assert sorted(r["risk"] for r in recs) == ["HIGH", "LOW"]


def test_cache_hit_ratio():
    assert ar.cache_hit_ratio({"input_tokens": 1000, "cached_read_tokens": 250}) == 0.25
    assert ar.cache_hit_ratio({"input_tokens": 0, "cached_read_tokens": 0}) == 0.0


def test_summarize_run():
    state = {
        "plan": "/abs/docs/experiments/v2.22-dispatch-optimization/plan.md",
        "timestamps": {"started_at": "2026-05-31T20:00:00Z",
                       "completed_at": "2026-05-31T21:00:00Z"},
        "cost_ledger": {"totals": {"cost_usd": 12.35, "input_tokens": 657788,
                                   "output_tokens": 1234, "cached_read_tokens": 0,
                                   "cached_write_tokens": 0, "dispatches": 19}},
        "tasks": {"task_1": {"status": "COMPLETE"}, "task_2": {"status": "SKIPPED"}},
        "risk_levels": {},
    }
    s = ar.summarize_run("v2-22-...-20260531-201758", state)
    assert s["plan_slug"] == "v2.22-dispatch-optimization"
    assert s["dispatches"] == 19
    assert s["cost_usd"] == 12.35
    assert s["tasks_done"] == 1
    assert s["cache_hit_ratio"] == 0.0
    assert s["started_at"] == "2026-05-31T20:00:00Z"


def test_verifier_retry_distribution():
    recs = [
        {"risk": "LOW", "verifier_retries": 0, "review_tier": "PASS"},
        {"risk": "LOW", "verifier_retries": 0, "review_tier": "PASS"},
        {"risk": "LOW", "verifier_retries": 1, "review_tier": "PASS"},
        {"risk": "MID", "verifier_retries": 2, "review_tier": "WARN"},
        {"risk": None,  "verifier_retries": 0, "review_tier": "PASS"},
    ]
    dist = ar.verifier_retry_distribution(recs)
    assert dist["LOW"] == {0: 2, 1: 1}
    assert dist["MID"] == {2: 1}
    assert dist["UNKNOWN"] == {0: 1}


def test_quality_fail_rate():
    recs = [
        {"review_tier": "PASS"}, {"review_tier": "PASS"},
        {"review_tier": "FAIL"}, {"review_tier": None},
    ]
    assert round(ar.quality_fail_rate(recs), 3) == 0.333
    assert ar.quality_fail_rate([]) == 0.0


def test_quality_drift():
    state = {"quality_trend": [0.6, 0.6, 0.6, 0.6, 0.6, 0.9, 0.9, 0.9, 0.9, 0.9]}
    assert round(ar.quality_drift(state), 3) == 0.3
    assert ar.quality_drift({"quality_trend": []}) == 0.0


def test_recurring_issue_signatures():
    states = [
        {"task_summaries": {"task_1": {"issue_keys": ["a.py:10:naming"]},
                            "task_2": {"issue_keys": ["a.py:10:naming", "b.py:5:dead"]}}},
        {"plan_chain": [
            {"task_summaries": {"task_1": {"issue_keys": ["a.py:10:naming"]}}}]},
    ]
    sigs = ar.recurring_issue_signatures(states)
    assert sigs["a.py:10:naming"] == 3
    assert sigs["b.py:5:dead"] == 1
    assert list(sigs.keys())[0] == "a.py:10:naming"


def test_detect_observability_gaps():
    state = {
        "cost_ledger": {"totals": {"dispatches": 0}},
        "quality_trend": [],
        "timestamps": {"started_at": None, "completed_at": None},
    }
    gaps = ar.detect_observability_gaps("run-x", state)
    joined = " | ".join(gaps)
    assert "dispatches=0" in joined
    assert "quality_trend empty" in joined
    assert "started_at" in joined

    clean = {
        "cost_ledger": {"totals": {"dispatches": 5}},
        "quality_trend": [0.9],
        "timestamps": {"started_at": "t0", "completed_at": "t1"},
    }
    assert ar.detect_observability_gaps("run-y", clean) == []


import json as _json


def _write(p: Path, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_json.dumps(obj))


def test_discover_run_files_live_and_archived(tmp_path):
    orch = tmp_path / "orchestrator"
    learn = tmp_path / "learning"
    _write(orch / "run-a-20260101-000000" / "state.json", {"plan": "/p/a/plan.md"})
    _write(orch / "run-b-20260102-000000" / "state.json", {"plan": "/p/b/plan.md"})
    _write(learn / "2026-01-02" / "run-b-20260102-000000" / "artifacts" / "state.final.json",
           {"plan": "/p/b/plan.md", "final": True})

    found = dict((rid, path) for rid, path in
                 ar.discover_run_files(str(orch), str(learn)))
    assert "run-a-20260101-000000" in found
    assert found["run-a-20260101-000000"].endswith("state.json")
    assert found["run-b-20260102-000000"].endswith("state.final.json")


def test_discover_run_files_missing_roots(tmp_path):
    assert ar.discover_run_files(str(tmp_path / "nope"), str(tmp_path / "nada")) == []
