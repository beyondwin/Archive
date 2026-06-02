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
