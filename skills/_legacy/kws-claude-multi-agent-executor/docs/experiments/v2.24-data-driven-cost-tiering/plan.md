# v2.24 Phase A — Run/Telemetry Aggregator CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `scripts/aggregate_runs.py`, a read-only cross-run telemetry aggregator that summarizes the existing orchestrator run corpus and produces the gate-input findings (LOW-tier verifier-retry distribution + production cache-hit ratio) that v2.24 Phases B and C depend on.

**Architecture:** A pure-function core (operating on already-parsed `state.json` dicts) wrapped by a thin discovery+CLI shell. The existing `query_state.sh` / `query_run.sh` cover *single-run* queries; this tool is strictly *cross-run* aggregation and reuses their field conventions (`cost_ledger.totals`, per-task `review_tier`/`review_retries`, `plan_chain` flattening, `quality_trend`, `risk_levels`). It is observation-only: it reads existing artifacts and never writes `state.json`, never edits any `references/phases/*.md`, and is never invoked from orchestrator phase prose (the Goodhart guard / G5 invariant).

**Tech Stack:** Python 3 (stdlib only — `argparse`, `json`, `pathlib`, `collections`, `statistics`, `glob`), pytest. Matches the existing `scripts/*.py` + `scripts/test_*.py` convention (no external deps, no pytest config file — tests are plain `test_*.py` run via `python -m pytest scripts/`).

**Scope note:** This plan is v2.24 **Phase A only**. Phases B (Haiku Implementer tier) and C (cache TTL) are gated on this phase's runtime output and get their own plans authored after Task 10's findings are reviewed. See `spec.md` §2–3.

**Data-shape reference (verified against the live corpus and `scripts/query_state.sh`):**

```jsonc
// ~/.claude/orchestrator/<RUN_ID>/state.json  (live)
// ~/.claude/learning/kws-claude-multi-agent-executor/runs/<date>/<id>/artifacts/state.final.json  (archived)
{
  "plan": "/abs/path/to/plan.md",            // run-level; basename → plan slug
  "timestamps": { "started_at": "...", "completed_at": "..." },
  "cost_ledger": {
    "totals": {
      "cost_usd": 12.35, "input_tokens": 657788, "output_tokens": 1234,
      "cached_read_tokens": 0, "cached_write_tokens": 0, "dispatches": 19
      // NOTE: input_tokens INCLUDES cached_read_tokens (per v2.15 C3 formula
      //       session_input = input_tokens - cached_read_tokens).
      //       cache_hit_ratio = cached_read_tokens / input_tokens.
    }
  },
  // EITHER top-level (single-plan) OR repeated inside plan_chain[] (multi-plan):
  "tasks": { "task_1": { "status": "COMPLETE", "review_tier": "PASS",
                          "review_retries": 0, "verifier_retries": 0,
                          "escalation_count": 0 } },
  "task_summaries": { "task_1": { "warnings": [], "issue_keys": [] } },
  "quality_trend": [0.88, 0.91],
  "risk_levels": { "task_1": "LOW", "task_2": "MID" },
  "plan_chain": [ /* each element repeats tasks/task_summaries/quality_trend/risk_levels */ ]
}
```

Multi-plan flattening rule (matches the v2.13 method-audit validator and `query_state.sh`): if `plan_chain` is a non-empty array, iterate every element's per-plan tree; otherwise use the top level.

---

### Task 1: Module scaffold + `flatten_tasks()`

**Risk:** LOW

**Files:**
- Create: `scripts/aggregate_runs.py`
- Test: `scripts/test_aggregate_runs.py`

`flatten_tasks(state)` returns a list of per-task records, each `{"plan_index", "task_id", "status", "review_tier", "review_retries", "verifier_retries", "escalation_count", "risk"}`, correctly handling both single-plan and `plan_chain` shapes and joining each task to its risk tier from the same tree's `risk_levels`.

- [ ] **Step 1: Write the failing test**

```python
# scripts/test_aggregate_runs.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd skills/kws-claude-multi-agent-executor && python -m pytest scripts/test_aggregate_runs.py -v`
Expected: FAIL — `ModuleNotFoundError` / `AttributeError: module 'aggregate_runs' has no attribute 'flatten_tasks'`.

- [ ] **Step 3: Write minimal implementation**

```python
#!/usr/bin/env python3
"""aggregate_runs.py - read-only CROSS-RUN telemetry aggregator.

Summarizes the orchestrator run corpus (live ~/.claude/orchestrator/*/state.json
and archived ~/.claude/learning/.../runs/<date>/<id>/artifacts/state.final.json)
into per-run rows, retry distributions by risk tier, P4 QUALITY fail-rate,
quality-trend drift, recurring ISSUE_KEY signatures, and observability gaps.

Observation-only: reads existing artifacts, never mutates state.json, never
participates in orchestrator control flow (v2.24 G5 / Goodhart guard).

Single-run queries already exist in query_state.sh / query_run.sh; this tool is
strictly cross-run.
"""
from __future__ import annotations

QUALITY_THRESHOLD = 0.75  # P4 QUALITY threshold (not user-configurable).


def _plan_trees(state):
    """Yield (plan_index, per_plan_tree) for single-plan or plan_chain shapes."""
    chain = state.get("plan_chain")
    if isinstance(chain, list) and chain:
        for i, tree in enumerate(chain):
            yield i, (tree or {})
    else:
        yield 0, state


def flatten_tasks(state):
    """Flatten all tasks across plan trees into a list of records."""
    out = []
    for plan_index, tree in _plan_trees(state):
        tasks = tree.get("tasks") or {}
        risk_levels = tree.get("risk_levels") or {}
        for task_id, t in tasks.items():
            t = t or {}
            out.append({
                "plan_index": plan_index,
                "task_id": task_id,
                "status": t.get("status"),
                "review_tier": t.get("review_tier"),
                "review_retries": t.get("review_retries", 0) or 0,
                "verifier_retries": t.get("verifier_retries", 0) or 0,
                "escalation_count": t.get("escalation_count",
                                          t.get("escalations", 0)) or 0,
                "risk": risk_levels.get(task_id),
            })
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd skills/kws-claude-multi-agent-executor && python -m pytest scripts/test_aggregate_runs.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add skills/kws-claude-multi-agent-executor/scripts/aggregate_runs.py \
        skills/kws-claude-multi-agent-executor/scripts/test_aggregate_runs.py
git commit -m "feat(aggregate_runs): module scaffold + flatten_tasks across plan_chain"
```

---

### Task 2: `cache_hit_ratio()` + `summarize_run()`

**Risk:** LOW

**Files:**
- Modify: `scripts/aggregate_runs.py`
- Test: `scripts/test_aggregate_runs.py`

`cache_hit_ratio(totals)` = `cached_read_tokens / input_tokens` (0 when `input_tokens == 0`). `summarize_run(run_id, state)` returns a per-run dict: run_id, plan slug (basename of `state["plan"]`), tasks_done, dispatches, cost_usd, input/output/cached_read/cached_write tokens, cache_hit_ratio, started_at, completed_at.

- [ ] **Step 1: Write the failing test**

```python
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
    assert s["tasks_done"] == 1            # COMPLETE only
    assert s["cache_hit_ratio"] == 0.0
    assert s["started_at"] == "2026-05-31T20:00:00Z"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd skills/kws-claude-multi-agent-executor && python -m pytest scripts/test_aggregate_runs.py -k "cache_hit or summarize" -v`
Expected: FAIL — `AttributeError: module 'aggregate_runs' has no attribute 'cache_hit_ratio'`.

- [ ] **Step 3: Write minimal implementation**

```python
import os


def cache_hit_ratio(totals):
    totals = totals or {}
    inp = totals.get("input_tokens", 0) or 0
    cr = totals.get("cached_read_tokens", 0) or 0
    return (cr / inp) if inp else 0.0


def _plan_slug(state):
    plan_path = state.get("plan") or ""
    if not plan_path:
        return None
    base = os.path.basename(os.path.dirname(plan_path)) or os.path.basename(plan_path)
    return base or None


def summarize_run(run_id, state):
    totals = (state.get("cost_ledger") or {}).get("totals") or {}
    ts = state.get("timestamps") or {}
    tasks = flatten_tasks(state)
    return {
        "run_id": run_id,
        "plan_slug": _plan_slug(state),
        "tasks_done": sum(1 for t in tasks if t["status"] == "COMPLETE"),
        "tasks_total": len(tasks),
        "dispatches": totals.get("dispatches", 0) or 0,
        "cost_usd": totals.get("cost_usd", 0.0) or 0.0,
        "input_tokens": totals.get("input_tokens", 0) or 0,
        "output_tokens": totals.get("output_tokens", 0) or 0,
        "cached_read_tokens": totals.get("cached_read_tokens", 0) or 0,
        "cached_write_tokens": totals.get("cached_write_tokens", 0) or 0,
        "cache_hit_ratio": round(cache_hit_ratio(totals), 4),
        "started_at": ts.get("started_at"),
        "completed_at": ts.get("completed_at"),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd skills/kws-claude-multi-agent-executor && python -m pytest scripts/test_aggregate_runs.py -k "cache_hit or summarize" -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add skills/kws-claude-multi-agent-executor/scripts/aggregate_runs.py \
        skills/kws-claude-multi-agent-executor/scripts/test_aggregate_runs.py
git commit -m "feat(aggregate_runs): cache_hit_ratio + per-run summary"
```

---

### Task 3: `verifier_retry_distribution()` + `quality_fail_rate()`

**Risk:** LOW

**Files:**
- Modify: `scripts/aggregate_runs.py`
- Test: `scripts/test_aggregate_runs.py`

`verifier_retry_distribution(task_records)` returns `{risk_tier: {retry_count: n}}` (the LOW bucket is the Phase B gate input). `quality_fail_rate(task_records)` returns the fraction of tasks whose `review_tier == "FAIL"` among tasks with a non-null `review_tier` (proxy for P4 QUALITY failures; 0.0 when no scored tasks).

- [ ] **Step 1: Write the failing test**

```python
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
    # 1 FAIL of 3 scored (None excluded) → 0.333...
    assert round(ar.quality_fail_rate(recs), 3) == 0.333
    assert ar.quality_fail_rate([]) == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd skills/kws-claude-multi-agent-executor && python -m pytest scripts/test_aggregate_runs.py -k "distribution or fail_rate" -v`
Expected: FAIL — `AttributeError`.

- [ ] **Step 3: Write minimal implementation**

```python
from collections import defaultdict


def verifier_retry_distribution(task_records):
    dist = defaultdict(lambda: defaultdict(int))
    for r in task_records:
        tier = r.get("risk") or "UNKNOWN"
        dist[tier][r.get("verifier_retries", 0) or 0] += 1
    return {tier: dict(counts) for tier, counts in dist.items()}


def quality_fail_rate(task_records):
    scored = [r for r in task_records if r.get("review_tier") is not None]
    if not scored:
        return 0.0
    fails = sum(1 for r in scored if r.get("review_tier") == "FAIL")
    return fails / len(scored)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd skills/kws-claude-multi-agent-executor && python -m pytest scripts/test_aggregate_runs.py -k "distribution or fail_rate" -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add skills/kws-claude-multi-agent-executor/scripts/aggregate_runs.py \
        skills/kws-claude-multi-agent-executor/scripts/test_aggregate_runs.py
git commit -m "feat(aggregate_runs): verifier-retry distribution by risk + quality fail-rate"
```

---

### Task 4: `quality_drift()` + `recurring_issue_signatures()`

**Risk:** LOW

**Files:**
- Modify: `scripts/aggregate_runs.py`
- Test: `scripts/test_aggregate_runs.py`

`quality_drift(state)` = mean(last 5) − mean(first 5) over the concatenated `quality_trend` across plan trees (0.0 when fewer than 1 score). `recurring_issue_signatures(states)` counts ISSUE_KEY strings found at `task_summaries.<id>.issue_keys[]` across a list of states, returning a `{issue_key: count}` dict sorted by count desc (exact-match only — never fuzzy, per the ISSUE_KEY guardrail).

- [ ] **Step 1: Write the failing test**

```python
def test_quality_drift():
    state = {"quality_trend": [0.6, 0.6, 0.6, 0.6, 0.6, 0.9, 0.9, 0.9, 0.9, 0.9]}
    assert round(ar.quality_drift(state), 3) == 0.3          # last5=0.9, first5=0.6
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
    # sorted by count desc
    assert list(sigs.keys())[0] == "a.py:10:naming"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd skills/kws-claude-multi-agent-executor && python -m pytest scripts/test_aggregate_runs.py -k "drift or recurring" -v`
Expected: FAIL — `AttributeError`.

- [ ] **Step 3: Write minimal implementation**

```python
from collections import Counter


def _all_quality_scores(state):
    scores = []
    for _, tree in _plan_trees(state):
        qt = tree.get("quality_trend") or []
        scores.extend(qt)
    return scores


def quality_drift(state):
    qt = _all_quality_scores(state)
    if not qt:
        return 0.0
    first5 = qt[:5]
    last5 = qt[-5:]
    return (sum(last5) / len(last5)) - (sum(first5) / len(first5))


def recurring_issue_signatures(states):
    counter = Counter()
    for state in states:
        for _, tree in _plan_trees(state):
            summaries = tree.get("task_summaries") or {}
            for _, summary in summaries.items():
                for key in (summary or {}).get("issue_keys", []) or []:
                    counter[key] += 1
    return dict(counter.most_common())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd skills/kws-claude-multi-agent-executor && python -m pytest scripts/test_aggregate_runs.py -k "drift or recurring" -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add skills/kws-claude-multi-agent-executor/scripts/aggregate_runs.py \
        skills/kws-claude-multi-agent-executor/scripts/test_aggregate_runs.py
git commit -m "feat(aggregate_runs): quality drift + recurring ISSUE_KEY signatures"
```

---

### Task 5: `detect_observability_gaps()`

**Risk:** LOW

**Files:**
- Modify: `scripts/aggregate_runs.py`
- Test: `scripts/test_aggregate_runs.py`

`detect_observability_gaps(run_id, state)` returns a list of human-readable gap strings — flags `dispatches==0`, empty `quality_trend`, and null `timestamps.started_at`/`completed_at`. Reported only; never acted on (G5).

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd skills/kws-claude-multi-agent-executor && python -m pytest scripts/test_aggregate_runs.py -k "gaps" -v`
Expected: FAIL — `AttributeError`.

- [ ] **Step 3: Write minimal implementation**

```python
def detect_observability_gaps(run_id, state):
    gaps = []
    totals = (state.get("cost_ledger") or {}).get("totals") or {}
    if (totals.get("dispatches", 0) or 0) == 0:
        gaps.append(f"{run_id}: cost_ledger.totals.dispatches=0 (cost helper likely not called)")
    if not _all_quality_scores(state):
        gaps.append(f"{run_id}: quality_trend empty (no quality scores recorded)")
    ts = state.get("timestamps") or {}
    if not ts.get("started_at"):
        gaps.append(f"{run_id}: timestamps.started_at null")
    if not ts.get("completed_at"):
        gaps.append(f"{run_id}: timestamps.completed_at null")
    return gaps
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd skills/kws-claude-multi-agent-executor && python -m pytest scripts/test_aggregate_runs.py -k "gaps" -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add skills/kws-claude-multi-agent-executor/scripts/aggregate_runs.py \
        skills/kws-claude-multi-agent-executor/scripts/test_aggregate_runs.py
git commit -m "feat(aggregate_runs): observability-gap detection (report-only)"
```

---

### Task 6: `discover_run_files()` — live + archived discovery with dedup

**Risk:** MID

**Files:**
- Modify: `scripts/aggregate_runs.py`
- Test: `scripts/test_aggregate_runs.py`

`discover_run_files(orchestrator_root, learning_root)` returns a list of `(run_id, path)` tuples. It globs live `<orchestrator_root>/*/state.json` and archived `<learning_root>/*/*/artifacts/state.final.json`. When the same run_id appears in both, prefer the archived `state.final.json` (it is the frozen end-state). run_id = the orchestrator dir name for live, the `<id>` dir name for archived.

**Acceptance Criteria:**

```bash
cd skills/kws-claude-multi-agent-executor
python -m pytest scripts/test_aggregate_runs.py -k "discover" -v
# Expected: all discover tests PASS
```

- [ ] **Step 1: Write the failing test**

```python
import json as _json


def _write(p: Path, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_json.dumps(obj))


def test_discover_run_files_live_and_archived(tmp_path):
    orch = tmp_path / "orchestrator"
    learn = tmp_path / "learning"
    # live-only run
    _write(orch / "run-a-20260101-000000" / "state.json", {"plan": "/p/a/plan.md"})
    # run present in BOTH live and archived → archived wins
    _write(orch / "run-b-20260102-000000" / "state.json", {"plan": "/p/b/plan.md"})
    _write(learn / "2026-01-02" / "run-b-20260102-000000" / "artifacts" / "state.final.json",
           {"plan": "/p/b/plan.md", "final": True})

    found = dict((rid, path) for rid, path in
                 ar.discover_run_files(str(orch), str(learn)))
    assert "run-a-20260101-000000" in found
    assert found["run-a-20260101-000000"].endswith("state.json")
    # archived preferred for run-b
    assert found["run-b-20260102-000000"].endswith("state.final.json")


def test_discover_run_files_missing_roots(tmp_path):
    # Non-existent roots → empty list, no crash.
    assert ar.discover_run_files(str(tmp_path / "nope"), str(tmp_path / "nada")) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd skills/kws-claude-multi-agent-executor && python -m pytest scripts/test_aggregate_runs.py -k "discover" -v`
Expected: FAIL — `AttributeError: module 'aggregate_runs' has no attribute 'discover_run_files'`.

- [ ] **Step 3: Write minimal implementation**

```python
import glob


def discover_run_files(orchestrator_root, learning_root):
    """Return [(run_id, path)] preferring archived state.final.json over live."""
    archived = {}
    for path in glob.glob(os.path.join(learning_root, "*", "*", "artifacts", "state.final.json")):
        run_id = os.path.basename(os.path.dirname(os.path.dirname(path)))
        archived[run_id] = path

    live = {}
    for path in glob.glob(os.path.join(orchestrator_root, "*", "state.json")):
        run_id = os.path.basename(os.path.dirname(path))
        live[run_id] = path

    merged = {}
    for run_id, path in live.items():
        merged[run_id] = path
    for run_id, path in archived.items():   # archived wins on collision
        merged[run_id] = path
    return sorted(merged.items())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd skills/kws-claude-multi-agent-executor && python -m pytest scripts/test_aggregate_runs.py -k "discover" -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add skills/kws-claude-multi-agent-executor/scripts/aggregate_runs.py \
        skills/kws-claude-multi-agent-executor/scripts/test_aggregate_runs.py
git commit -m "feat(aggregate_runs): live+archived run discovery with archived-wins dedup"
```

---

### Task 7: `load_state()` + `build_report()` — corpus assembly with malformed-file tolerance

**Risk:** MID

**Files:**
- Modify: `scripts/aggregate_runs.py`
- Test: `scripts/test_aggregate_runs.py`

`load_state(path)` parses JSON, returning `None` (not raising) on malformed/unreadable files. `build_report(run_files, filters)` loads each run, applies `--since`/`--plan`/`--risk` filters, and assembles the full report dict: `runs[]` (per-run summaries), aggregate `verifier_retry_distribution`, `quality_fail_rate`, `recurring_issue_signatures`, `gaps[]`, and a `skipped[]` list of unparseable paths.

**Acceptance Criteria:**

```bash
cd skills/kws-claude-multi-agent-executor
python -m pytest scripts/test_aggregate_runs.py -k "load_state or build_report" -v
# Expected: all PASS
```

- [ ] **Step 1: Write the failing test**

```python
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
    assert report["gaps"] == []           # r1 is clean


def test_build_report_risk_filter(tmp_path):
    r1 = tmp_path / "r1.json"
    _write(r1, {
        "plan": "/x/alpha/plan.md",
        "tasks": {"t1": {"status": "COMPLETE", "review_tier": "PASS", "verifier_retries": 0},
                  "t2": {"status": "COMPLETE", "review_tier": "WARN", "verifier_retries": 2}},
        "risk_levels": {"t1": "LOW", "t2": "MID"},
    })
    report = ar.build_report([("r1", str(r1))], filters={"risk": "low"})
    # only LOW tasks counted in the distribution
    assert report["verifier_retry_distribution"] == {"LOW": {0: 1}}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd skills/kws-claude-multi-agent-executor && python -m pytest scripts/test_aggregate_runs.py -k "load_state or build_report" -v`
Expected: FAIL — `AttributeError`.

- [ ] **Step 3: Write minimal implementation**

```python
def load_state(path):
    try:
        with open(path, "r") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _passes_filters(run_id, state, filters):
    since = filters.get("since")
    if since:
        started = ((state.get("timestamps") or {}).get("started_at") or "")
        if started and started < since:
            return False
    plan_glob = filters.get("plan")
    if plan_glob:
        import fnmatch
        slug = _plan_slug(state) or ""
        if not fnmatch.fnmatch(slug, plan_glob):
            return False
    return True


def build_report(run_files, filters):
    filters = filters or {}
    risk_filter = (filters.get("risk") or "").upper() or None
    runs, all_task_recs, states, gaps, skipped = [], [], [], [], []

    for run_id, path in run_files:
        state = load_state(path)
        if state is None:
            skipped.append(run_id)
            continue
        if not _passes_filters(run_id, state, filters):
            continue
        runs.append(summarize_run(run_id, state))
        states.append(state)
        gaps.extend(detect_observability_gaps(run_id, state))
        recs = flatten_tasks(state)
        if risk_filter:
            recs = [r for r in recs if (r.get("risk") or "").upper() == risk_filter]
        all_task_recs.extend(recs)

    return {
        "runs": runs,
        "verifier_retry_distribution": verifier_retry_distribution(all_task_recs),
        "quality_fail_rate": round(quality_fail_rate(all_task_recs), 4),
        "recurring_issue_signatures": recurring_issue_signatures(states),
        "gaps": gaps,
        "skipped": skipped,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd skills/kws-claude-multi-agent-executor && python -m pytest scripts/test_aggregate_runs.py -k "load_state or build_report" -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add skills/kws-claude-multi-agent-executor/scripts/aggregate_runs.py \
        skills/kws-claude-multi-agent-executor/scripts/test_aggregate_runs.py
git commit -m "feat(aggregate_runs): corpus assembly with filters + malformed-file tolerance"
```

---

### Task 8: `render_md()` + `render_json()`

**Risk:** LOW

**Files:**
- Modify: `scripts/aggregate_runs.py`
- Test: `scripts/test_aggregate_runs.py`

`render_json(report)` = stable `json.dumps(report, indent=2, sort_keys=True)`. `render_md(report)` = a markdown report: a per-run table, the LOW-tier verifier-retry line (called out explicitly as the Phase B gate input), the aggregate quality fail-rate, top recurring issue signatures, and an observability-gaps section.

- [ ] **Step 1: Write the failing test**

```python
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
    assert "LOW" in md and "Phase B gate" in md     # gate input called out
    assert "a.py:10:naming" in md
    assert "quality_trend empty" in md
    assert "0.5" in md                              # cache_hit_ratio rendered
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd skills/kws-claude-multi-agent-executor && python -m pytest scripts/test_aggregate_runs.py -k "render" -v`
Expected: FAIL — `AttributeError`.

- [ ] **Step 3: Write minimal implementation**

```python
def render_json(report):
    return json.dumps(report, indent=2, sort_keys=True)


def render_md(report):
    lines = ["# Run Telemetry Aggregate", ""]
    lines.append("## Per-run summary")
    lines.append("")
    lines.append("| run_id | plan | done/total | dispatches | cost_usd | cache_hit | started |")
    lines.append("|--------|------|-----------|-----------|----------|-----------|---------|")
    for r in report["runs"]:
        lines.append(
            f"| {r['run_id']} | {r.get('plan_slug')} | "
            f"{r['tasks_done']}/{r['tasks_total']} | {r['dispatches']} | "
            f"{round(r['cost_usd'], 2)} | {r['cache_hit_ratio']} | {r.get('started_at')} |")
    lines.append("")

    lines.append("## Verifier-retry distribution by risk tier")
    lines.append("")
    low = report["verifier_retry_distribution"].get("LOW", {})
    lines.append(f"- **LOW (Phase B gate input):** {low}")
    for tier, counts in sorted(report["verifier_retry_distribution"].items()):
        if tier == "LOW":
            continue
        lines.append(f"- {tier}: {counts}")
    lines.append("")

    lines.append(f"## Quality fail-rate (P4 proxy): {report['quality_fail_rate']}")
    lines.append("")

    lines.append("## Recurring ISSUE_KEY signatures")
    lines.append("")
    sigs = report["recurring_issue_signatures"]
    if not sigs:
        lines.append("- (none recorded)")
    else:
        for key, count in sigs.items():
            lines.append(f"- `{key}` × {count}")
    lines.append("")

    lines.append("## Observability gaps (report-only)")
    lines.append("")
    if not report["gaps"]:
        lines.append("- (none)")
    else:
        for g in report["gaps"]:
            lines.append(f"- {g}")
    lines.append("")

    if report["skipped"]:
        lines.append(f"## Skipped (unparseable): {report['skipped']}")
    return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd skills/kws-claude-multi-agent-executor && python -m pytest scripts/test_aggregate_runs.py -k "render" -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add skills/kws-claude-multi-agent-executor/scripts/aggregate_runs.py \
        skills/kws-claude-multi-agent-executor/scripts/test_aggregate_runs.py
git commit -m "feat(aggregate_runs): markdown + json report rendering"
```

---

### Task 9: `main()` CLI wiring + `__main__`

**Risk:** MID

**Files:**
- Modify: `scripts/aggregate_runs.py`
- Test: `scripts/test_aggregate_runs.py`

`main(argv)` wires argparse (`--orchestrator-root`, `--learning-root`, `--since`, `--plan`, `--risk`, `--format md|json`, `--json <path>`), defaults the roots to `$HOME/.claude/orchestrator` and `$HOME/.claude/learning/kws-claude-multi-agent-executor/runs`, builds the report, and prints it. Returns exit code 0.

**Acceptance Criteria:**

```bash
cd skills/kws-claude-multi-agent-executor
python -m pytest scripts/test_aggregate_runs.py -v
# Expected: ALL tests PASS

# End-to-end smoke against the REAL corpus (read-only):
python scripts/aggregate_runs.py --format md | head -20
# Expected: a non-empty "# Run Telemetry Aggregate" report with at least one run row.

# Goodhart-guard invariant: the script is never called from phase prose.
! grep -rn "aggregate_runs" references/phases/
# Expected: no matches (grep exits 1, the leading ! makes the line succeed).
```

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd skills/kws-claude-multi-agent-executor && python -m pytest scripts/test_aggregate_runs.py -k "main" -v`
Expected: FAIL — `AttributeError: module 'aggregate_runs' has no attribute 'main'`.

- [ ] **Step 3: Write minimal implementation**

```python
import argparse


def _default_orchestrator_root():
    return os.path.join(os.path.expanduser("~"), ".claude", "orchestrator")


def _default_learning_root():
    return os.path.join(os.path.expanduser("~"), ".claude", "learning",
                        "kws-claude-multi-agent-executor", "runs")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Cross-run telemetry aggregator (read-only).")
    parser.add_argument("--orchestrator-root", default=_default_orchestrator_root())
    parser.add_argument("--learning-root", default=_default_learning_root())
    parser.add_argument("--since", default=None, help="ISO date; filter runs started on/after.")
    parser.add_argument("--plan", default=None, help="fnmatch glob over plan slug.")
    parser.add_argument("--risk", default=None, choices=["low", "mid", "high"])
    parser.add_argument("--format", default="md", choices=["md", "json"])
    parser.add_argument("--json", dest="json_out", default=None,
                        help="also write JSON report to this path.")
    args = parser.parse_args(argv)

    run_files = discover_run_files(args.orchestrator_root, args.learning_root)
    report = build_report(run_files, filters={
        "since": args.since, "plan": args.plan, "risk": args.risk})

    if args.json_out:
        with open(args.json_out, "w") as fh:
            fh.write(render_json(report))

    print(render_json(report) if args.format == "json" else render_md(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the full suite + real-corpus smoke + invariant check**

Run:
```bash
cd skills/kws-claude-multi-agent-executor
python -m pytest scripts/test_aggregate_runs.py -v
python scripts/aggregate_runs.py --format md | head -20
! grep -rn "aggregate_runs" references/phases/
```
Expected: all tests PASS; real-corpus smoke prints a non-empty report; grep finds no matches in phase prose.

- [ ] **Step 5: Commit**

```bash
git add skills/kws-claude-multi-agent-executor/scripts/aggregate_runs.py \
        skills/kws-claude-multi-agent-executor/scripts/test_aggregate_runs.py
git commit -m "feat(aggregate_runs): CLI entrypoint + end-to-end over real corpus"
```

---

### Task 10: Docs + gate findings (`F001-baseline-telemetry.md`)

**Risk:** LOW

**Files:**
- Create: `docs/how-to/aggregate-runs.md`
- Modify: `docs/deferred-candidates.md` (mark the "학습 로그용 집계자 / 리포팅 CLI" entry shipped)
- Create: `docs/experiments/v2.24-data-driven-cost-tiering/findings/F001-baseline-telemetry.md`

This task is documentation + analysis (no executable code → TDD not applicable; report `METHOD_AUDIT: tdd waived reason=docs-only-task`).

- [ ] **Step 1: Write the how-to doc**

Create `docs/how-to/aggregate-runs.md` with: purpose (cross-run aggregation, complements single-run `query_run.sh`), invocation examples (`python scripts/aggregate_runs.py`, `--risk low --format json`, `--since`), an explanation of each report section, and an explicit note that the tool is observation-only and must never be wired into orchestrator control flow (G5).

- [ ] **Step 2: Update deferred-candidates.md**

In `docs/deferred-candidates.md`, edit the "## 학습 로그용 집계자 / 리포팅 CLI" section: change status to **SHIPPED (v2.24 Phase A, 2026-06-02)**, point at `scripts/aggregate_runs.py`, and note that the data-gated candidates (Haiku tier, context_health active actions) can now be evaluated against real distributions via this tool.

- [ ] **Step 3: Generate the gate findings**

Run the aggregator over the real corpus and capture the gate inputs:
```bash
cd skills/kws-claude-multi-agent-executor
python scripts/aggregate_runs.py --json /tmp/v2.24-all.json --format md
python scripts/aggregate_runs.py --risk low --format md
```
Create `docs/experiments/v2.24-data-driven-cost-tiering/findings/F001-baseline-telemetry.md` recording, from the actual output:
- The per-run corpus summary (n runs, total cost, mean cache_hit_ratio).
- The **LOW-tier verifier-retry distribution** and whether it clears **B-GATE-1** (≥90% of LOW tasks at 0 retries) and **B-GATE-2** (QUALITY fail-rate < 5%) — with the measured numbers.
- The **production cache_hit_ratio** and whether a post-v2.22 run exists (Phase C C1 input); if none exists, state that explicitly as the C1 blocker.
- The observability gaps surfaced (e.g. runs with `dispatches=0` or empty `quality_trend`).
- A one-paragraph recommendation per phase: **Phase B → SHIP / SKIP / insufficient-data**, **Phase C → ephemeral-confirmed / needs-A-B / needs-post-v2.22-run** — each citing the measured number, not a guess.

- [ ] **Step 4: Verify docs render and findings are concrete**

Run:
```bash
cd skills/kws-claude-multi-agent-executor
test -f docs/how-to/aggregate-runs.md && echo "how-to OK"
test -f docs/experiments/v2.24-data-driven-cost-tiering/findings/F001-baseline-telemetry.md && echo "findings OK"
grep -q "SHIPPED" docs/deferred-candidates.md && echo "deferred updated"
grep -Eq "B-GATE-1|B-GATE-2" docs/experiments/v2.24-data-driven-cost-tiering/findings/F001-baseline-telemetry.md && echo "gates recorded"
```
Expected: all four echo lines print. The findings file must contain measured numbers (no "TBD" / placeholder).

- [ ] **Step 5: Commit**

```bash
git add skills/kws-claude-multi-agent-executor/docs/how-to/aggregate-runs.md \
        skills/kws-claude-multi-agent-executor/docs/deferred-candidates.md \
        skills/kws-claude-multi-agent-executor/docs/experiments/v2.24-data-driven-cost-tiering/findings/F001-baseline-telemetry.md
git commit -m "docs(v2.24): aggregator how-to + deferred-candidates update + F001 gate findings"
```

---

## Self-Review

**Spec coverage (spec.md §2 Phase A):**
- A1 (`scripts/aggregate_runs.py`, state.json primary + AgentLens secondary, per-run/distribution/recurring/gap outputs, md+json, filters) → Tasks 1–9. *Note: AgentLens-event enrichment (secondary source) is intentionally deferred within Phase A — the current corpus has a near-empty event log, so Task 7 assembles from `state.json` only. The AgentLens `cache_hit_ratio`/`wall_ms` enrichment is a follow-up once events are populated; F001 (Task 10) will record whether events exist to justify it.*
- A2 (`scripts/test_aggregate_runs.py` covering single-plan, plan_chain, empty quality_trend, dispatches==0, malformed file, events present/absent) → Tasks 1–9 fixtures. *The "events present/absent" fixture case collapses to "absent" given the deferral above; covered implicitly since no task reads events.*
- A3 (how-to doc + deferred-candidates update) → Task 10.
- Phase A acceptance (clean run over corpus, pytest green, no phase-prose diff / no state.json field / no runtime branch, LOW verifier_retry + cache_hit columns present) → Task 9 AC (smoke + grep invariant) and Task 10 (gate findings).

**Placeholder scan:** No "TBD"/"TODO"/"handle edge cases" in code steps; every code step shows complete code. Task 10 Step 3 intentionally defers concrete *numbers* to runtime (they come from the real corpus) but specifies exactly which numbers to record and the gate arithmetic — this is data capture, not a code placeholder.

**Type consistency:** Field names match across tasks and the live data shape — `cached_read_tokens`/`cached_write_tokens` (not `cache_read`), `review_tier`, `review_retries`, `verifier_retries`, `escalation_count`. Function names stable: `flatten_tasks`, `_plan_trees`, `summarize_run`, `cache_hit_ratio`, `verifier_retry_distribution`, `quality_fail_rate`, `quality_drift`, `_all_quality_scores`, `recurring_issue_signatures`, `detect_observability_gaps`, `discover_run_files`, `load_state`, `build_report`, `render_md`, `render_json`, `main`. `cache_hit_ratio` uses `cached_read_tokens / input_tokens` consistently (Task 2 defines, Task 8 renders the same value).

**Scope:** Phase A only, single cohesive module + its tests + docs. Phases B and C are explicitly out of this plan (gated on Task 10 findings) — correct decomposition per the writing-plans "working, testable software on its own" rule.
