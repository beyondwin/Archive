"""Tests for build_final_report.py (v2.29 — I4 + I7 rollup).

Validates the machine-readable run_report.json schema and the Execution Summary
markdown structure/derived fields. The markdown layout mirrors
phase-2-finalization.md Step 2; the snapshot here locks that layout so a future
template drift is caught.
"""
import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import build_final_report as bfr  # noqa: E402

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "build_final_report.py")


def _state():
    return {
        "schema_version": "2", "mode": "interactive_attached", "active_plan": "plan1",
        "plan": "plans/p.md", "spec": "specs/s.md", "branch": "feat/x",
        "worktree": "/wt/run-123", "orchestrator_dir": "/orch/run-123",
        "implementer_model": {"used": "opus", "default": "sonnet"},
        "agentlens_orchestration_run": None,
        "cost_tracking_waived": True, "cost_tracking_waive_reason": "agent-dispatch-no-usage",
        "cost_ledger": {"totals": {"dispatches": 0, "cost_usd": 0.0}},
        "auto_resolved_count": 2,
        "spec_edits": [{"task": "task_1", "fault": "unclear", "auto_resolved": True,
                        "interpretation": "chose A", "ts": "t"}],
        "timestamps": {"started_at": "2026-06-07T10:00:00Z", "completed_at": "2026-06-07T10:42:00Z"},
        "quality_trend": [0.8, 0.9, 0.7, 0.85, 0.95, 0.6, 0.7, 0.75, 0.8, 0.9],
        "verification_gaps": [{"task": "task_3", "kind": "verify", "reason": "no result", "ts": "t"}],
        "docs_gaps": [],
        "tasks": {
            "task_0": {"status": "COMPLETE", "risk": "low", "complexity": "SMALL",
                       "spec_score": 0.95, "quality_score": 0.9, "review_tier": "PASS",
                       "escalations": 0, "review_retries": 0, "verifier_retries": 0,
                       "spec_clarifications": 0, "files": ["a.py"],
                       "timing": {"started": "2026-06-07T10:00:00Z", "completed": "2026-06-07T10:05:00Z"}},
            "task_1": {"status": "COMPLETE", "risk": "mid", "complexity": "MEDIUM",
                       "spec_score": 0.8, "quality_score": 0.65, "review_tier": "WARN",
                       "escalations": 1, "review_retries": 2, "verifier_retries": 0,
                       "spec_clarifications": 1, "files": ["b.py"],
                       "retry_trace": [{"attempt": 1, "kind": "review", "fault": "spec_unclear", "tier": "FAIL"}],
                       "timing": {"started": "2026-06-07T10:05:00Z", "completed": "2026-06-07T10:20:00Z"}},
            "task_3": {"status": "SKIPPED", "risk": "high", "skip_reason": "verifier_retries_exhausted",
                       "review_retries": 0, "verifier_retries": 4},
        },
        "task_summaries": {"task_1": {"warnings": ["quality borderline"], "files": ["b.py"],
                                      "key_decision": "used X"}},
    }


def _write(tmp_path, data):
    p = tmp_path / "state.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


# --- run_report.json schema ------------------------------------------------

def test_run_report_top_level_schema():
    rep = bfr.build_run_report(_state())
    assert rep["schema"] == "run_report/1"
    assert rep["mode"] == "interactive_attached"
    assert rep["plans"] == [{"index": 0, "plan_path": "plans/p.md", "status": "COMPLETE"}]
    assert {t["id"] for t in rep["tasks"]} == {"task_0", "task_1", "task_3"}
    assert "generated_at" in rep


def test_run_report_task_fields():
    rep = bfr.build_run_report(_state())
    t1 = next(t for t in rep["tasks"] if t["id"] == "task_1")
    assert t1["status"] == "COMPLETE" and t1["risk"] == "mid" and t1["tier"] == "WARN"
    assert t1["spec_score"] == 0.8 and t1["quality_score"] == 0.65
    assert t1["review_retries"] == 2 and t1["verifier_retries"] == 0
    assert t1["retry_trace"][0]["fault"] == "spec_unclear"
    assert t1["skip_reason"] is None
    t3 = next(t for t in rep["tasks"] if t["id"] == "task_3")
    assert t3["status"] == "SKIPPED" and t3["skip_reason"] == "verifier_retries_exhausted"


def test_run_report_quality_delta_and_warn():
    rep = bfr.build_run_report(_state())
    q = rep["quality"]
    # first5 mean = (0.8+0.9+0.7+0.85+0.95)/5 = 0.84 ; last5 = (0.6+0.7+0.75+0.8+0.9)/5 = 0.75
    assert round(q["delta"], 2) == round(0.75 - 0.84, 2)
    assert q["warn_count"] == 1
    assert q["trend"] == _state()["quality_trend"]


def test_run_report_gaps_autonomy_cost():
    rep = bfr.build_run_report(_state())
    assert len(rep["gaps"]["verification_gaps"]) == 1
    assert rep["gaps"]["docs_gaps"] == []
    assert rep["autonomy"]["auto_resolved_count"] == 2
    assert rep["autonomy"]["escalations_total"] == 1  # task_1 escalations
    assert rep["cost"]["waived"] is True
    assert rep["cost"]["reason"] == "agent-dispatch-no-usage"


# --- I7 failure_summary rollup ---------------------------------------------

def test_failure_summary_by_class():
    rep = bfr.build_run_report(_state())
    fs = rep["failure_summary"]
    assert fs["by_class"]["verifier_retries_exhausted"] == 1
    assert fs["by_class"]["review_retries_exhausted"] == 0
    assert fs["by_class"]["verification_gap"] == 1
    assert fs["by_class"]["docs_gap"] == 0
    assert fs["by_class"]["spec_unclear"] >= 1  # retry_trace fault + spec_edit
    assert fs["auto_resolved"] == 2
    assert {s["task"] for s in fs["skipped_tasks"]} == {"task_3"}
    assert any(e["resolved"] == "auto" for e in fs["escalations"])


# --- multi-plan ------------------------------------------------------------

def test_run_report_multi_plan_iterates_chain():
    state = {
        "schema_version": "2", "mode": "plan_chain_running", "active_plan": 1,
        "plan_chain": [
            {"index": 0, "plan_path": "p0.md", "status": "complete",
             "tasks": {"task_0": {"status": "COMPLETE", "risk": "low", "review_tier": "PASS"}},
             "quality_trend": [], "verification_gaps": [], "docs_gaps": []},
            {"index": 1, "plan_path": "p1.md", "status": "running",
             "tasks": {"task_0": {"status": "COMPLETE", "risk": "mid", "review_tier": "PASS"}},
             "quality_trend": [], "verification_gaps": [], "docs_gaps": []},
        ],
        "timestamps": {"started_at": None, "completed_at": None},
    }
    rep = bfr.build_run_report(state)
    assert [p["index"] for p in rep["plans"]] == [0, 1]
    assert {(t["plan_index"], t["id"]) for t in rep["tasks"]} == {(0, "task_0"), (1, "task_0")}


# --- markdown structure ----------------------------------------------------

def test_markdown_has_all_sections_and_task_row():
    md = bfr.build_markdown(_state())
    for section in ["## Execution Summary", "### Tasks", "### WARN-tier tasks",
                    "### Quality trend", "### Performance", "### Cleanup Status"]:
        assert section in md, f"missing {section}"
    assert "| Task 0 |" in md
    assert "WAIVED — agent-dispatch-no-usage" in md
    assert "00:42" in md  # wall time started→completed
    # WARN-tier section lists task_1
    assert "task_1" in md.split("### WARN-tier tasks")[1]


def test_markdown_dispatch_gaps_section_present_when_gaps():
    md = bfr.build_markdown(_state())
    assert "### Dispatch gaps" in md
    assert "task_3" in md.split("### Dispatch gaps")[1].split("###")[0]


def test_markdown_omits_dispatch_gaps_when_none():
    s = _state()
    s["verification_gaps"] = []
    s["docs_gaps"] = []
    md = bfr.build_markdown(s)
    assert "### Dispatch gaps" not in md


# --- CLI -------------------------------------------------------------------

def test_cli_writes_both_outputs(tmp_path):
    p = _write(tmp_path, _state())
    out_md = tmp_path / "report.md"
    out_json = tmp_path / "run_report.json"
    r = subprocess.run([sys.executable, SCRIPT, str(p),
                        "--out-md", str(out_md), "--out-json", str(out_json)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "## Execution Summary" in out_md.read_text()
    rep = json.loads(out_json.read_text())
    assert rep["schema"] == "run_report/1"
    # markdown also echoed to stdout for the orchestrator to inject
    assert "## Execution Summary" in r.stdout


def test_cli_orch_dir_defaults_run_report_path(tmp_path):
    p = _write(tmp_path, _state())
    r = subprocess.run([sys.executable, SCRIPT, str(p), "--orch-dir", str(tmp_path)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "run_report.json").is_file()


def test_cli_missing_state_exit_2(tmp_path):
    r = subprocess.run([sys.executable, SCRIPT, str(tmp_path / "nope.json")],
                       capture_output=True, text=True)
    assert r.returncode == 2
