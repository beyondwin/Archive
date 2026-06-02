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
