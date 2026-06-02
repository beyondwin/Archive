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


def test_load_state_malformed(tmp_path):
    good = tmp_path / "good.json"
    good.write_text('{"a": 1}')
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert ar.load_state(str(good)) == {"a": 1}
    assert ar.load_state(str(bad)) is None
    assert ar.load_state(str(tmp_path / "missing.json")) is None


def test_build_report_aggregates_and_skips(tmp_path):
    r1 = tmp_path / "r1.json"
    _write(r1, {
        "plan": "/x/alpha/plan.md",
        "cost_ledger": {"totals": {"dispatches": 3, "input_tokens": 100,
                                   "cached_read_tokens": 50, "cost_usd": 1.0}},
        "tasks": {"t1": {"status": "COMPLETE", "review_tier": "PASS", "verifier_retries": 0}},
        "risk_levels": {"t1": "LOW"},
        "quality_trend": [0.9],
        "timestamps": {"started_at": "t0", "completed_at": "t1"},
    })
    bad = tmp_path / "bad.json"
    bad.write_text("{broken")

    report = ar.build_report([("r1", str(r1)), ("bad", str(bad))], filters={})
    assert len(report["runs"]) == 1
    assert report["runs"][0]["cache_hit_ratio"] == 0.5
    assert report["verifier_retry_distribution"]["LOW"] == {0: 1}
    assert report["skipped"] == ["bad"]
    assert report["gaps"] == []


def test_build_report_risk_filter(tmp_path):
    r1 = tmp_path / "r1.json"
    _write(r1, {
        "plan": "/x/alpha/plan.md",
        "tasks": {"t1": {"status": "COMPLETE", "review_tier": "PASS", "verifier_retries": 0},
                  "t2": {"status": "COMPLETE", "review_tier": "WARN", "verifier_retries": 2}},
        "risk_levels": {"t1": "LOW", "t2": "MID"},
    })
    report = ar.build_report([("r1", str(r1))], filters={"risk": "low"})
    assert report["verifier_retry_distribution"] == {"LOW": {0: 1}}


def test_render_json_roundtrip():
    report = {"runs": [], "verifier_retry_distribution": {}, "quality_fail_rate": 0.0,
              "recurring_issue_signatures": {}, "gaps": [], "skipped": []}
    out = ar.render_json(report)
    assert _json.loads(out) == report


def test_render_md_contains_sections():
    report = {
        "runs": [{"run_id": "r1", "plan_slug": "alpha", "tasks_done": 1, "tasks_total": 1,
                  "dispatches": 3, "cost_usd": 1.0, "input_tokens": 100, "output_tokens": 0,
                  "cached_read_tokens": 50, "cached_write_tokens": 0, "cache_hit_ratio": 0.5,
                  "started_at": "t0", "completed_at": "t1"}],
        "verifier_retry_distribution": {"LOW": {0: 9, 1: 1}, "MID": {0: 2}},
        "quality_fail_rate": 0.0,
        "recurring_issue_signatures": {"a.py:10:naming": 3},
        "gaps": ["r2: quality_trend empty"],
        "skipped": ["bad"],
    }
    md = ar.render_md(report)
    assert "| run_id |" in md or "run_id" in md
    assert "alpha" in md
    assert "LOW" in md and "Phase B gate" in md
    assert "a.py:10:naming" in md
    assert "quality_trend empty" in md
    assert "0.5" in md


def test_recurring_issue_signatures_tolerates_list_summaries():
    # A run whose task_summaries values are lists (not dicts) must not crash.
    state = {"plan": "/x/a/plan.md",
             "task_summaries": {"t1": ["not", "a", "dict"],
                                "t2": {"issue_keys": ["a.py:1:naming"]}}}
    out = ar.recurring_issue_signatures([state])
    assert out == {"a.py:1:naming": 1}


def test_main_json_format(tmp_path, capsys):
    orch = tmp_path / "orchestrator"
    _write(orch / "run-a-20260101-000000" / "state.json", {
        "plan": "/x/alpha/plan.md",
        "cost_ledger": {"totals": {"dispatches": 2, "input_tokens": 10, "cost_usd": 0.5}},
        "tasks": {"t1": {"status": "COMPLETE", "review_tier": "PASS", "verifier_retries": 0}},
        "risk_levels": {"t1": "LOW"},
        "quality_trend": [0.9],
        "timestamps": {"started_at": "t0", "completed_at": "t1"},
    })
    rc = ar.main(["--orchestrator-root", str(orch),
                  "--learning-root", str(tmp_path / "none"),
                  "--format", "json"])
    assert rc == 0
    captured = capsys.readouterr().out
    parsed = _json.loads(captured)
    assert parsed["runs"][0]["run_id"] == "run-a-20260101-000000"


def test_main_md_default(tmp_path, capsys):
    orch = tmp_path / "orchestrator"
    _write(orch / "run-a-20260101-000000" / "state.json", {"plan": "/x/a/plan.md"})
    rc = ar.main(["--orchestrator-root", str(orch),
                  "--learning-root", str(tmp_path / "none")])
    assert rc == 0
    assert "# Run Telemetry Aggregate" in capsys.readouterr().out


def test_verifier_retry_distribution_normalizes_risk_case():
    # Real corpus stores risk tiers lowercase; distribution keys must be canonical uppercase
    # so the render_md "LOW (Phase B gate input)" line populates.
    records = [
        {"risk": "low", "verifier_retries": 0},
        {"risk": "low", "verifier_retries": 1},
        {"risk": "mid", "verifier_retries": 0},
        {"risk": None, "verifier_retries": 0},
    ]
    dist = ar.verifier_retry_distribution(records)
    assert dist["LOW"] == {0: 1, 1: 1}
    assert dist["MID"] == {0: 1}
    assert dist["UNKNOWN"] == {0: 1}
    assert "low" not in dist and "mid" not in dist
