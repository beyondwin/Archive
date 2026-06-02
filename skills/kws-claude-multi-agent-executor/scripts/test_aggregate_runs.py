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
