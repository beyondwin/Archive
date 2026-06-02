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

import glob
import json
import os
from collections import Counter, defaultdict

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
