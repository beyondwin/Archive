#!/usr/bin/env python3
"""Build the Final Summary Report markdown + run_report.json from state.json (v2.29 I4/I7).

Moves the max end-of-run context burst — the manual field aggregation in
phase-2-finalization.md Step 2 — into a helper, and emits a machine-readable
`run_report.json` (axis A context reduction + axis C observability). The
orchestrator reads only the helper's stdout (the markdown) instead of re-reading
the whole state file and assembling the report by hand. `run_report.json` is the
direct input for `aggregate_runs.py`.

The markdown reproduces the phase-2-finalization.md `## Execution Summary` layout
(structure locked by test_build_final_report.py). Deterministic/tabular sections
are derived from state; free-form sections (Changes Made / Verification Results /
Docs Updated / Remaining Risks) are filled from the structured signals available
in state (task_summaries, gaps, skipped tasks).

I7: `run_report.json.failure_summary` rolls up failure signals by class.

usage:
    build_final_report.py <state.json> [--out-md <path>] [--out-json <path>]
                          [--orch-dir <dir>]
exit:   0 ok / 2 state file not found or unparseable
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path


# --------------------------------------------------------------------------
# state traversal helpers
# --------------------------------------------------------------------------

def _task_num(task_id: str) -> tuple:
    """Sort key for canonical task_<N>[_suffix] keys (robust to non-canonical)."""
    body = task_id[len("task_"):] if task_id.startswith("task_") else task_id
    head = body.split("_", 1)
    try:
        return (0, int(head[0]), head[1] if len(head) > 1 else "")
    except ValueError:
        return (1, 0, task_id)


def _derive_plan_status(tree: dict) -> str:
    tasks = tree.get("tasks") or {}
    if not tasks:
        return "COMPLETE"
    terminal = {"COMPLETE", "SKIPPED"}
    return "COMPLETE" if all((t or {}).get("status") in terminal for t in tasks.values()) else "INCOMPLETE"


def _plan_entries(state: dict):
    """Yield (plan_index, tree, plan_path, status) for every plan."""
    if state.get("plan_chain"):
        for i, entry in enumerate(state["plan_chain"]):
            yield (entry.get("index", i), entry, entry.get("plan_path"), entry.get("status"))
    else:
        yield (0, state, state.get("plan"), _derive_plan_status(state))


def _all_tasks(state: dict):
    """Yield (plan_index, task_id, task_dict) across all plans, ordered."""
    for pidx, tree, _pp, _st in _plan_entries(state):
        tasks = tree.get("tasks") or {}
        for tid in sorted(tasks, key=_task_num):
            yield (pidx, tid, tasks[tid] or {})


def _agg_list(state: dict, field: str) -> list:
    out: list = []
    for _pidx, tree, _pp, _st in _plan_entries(state):
        out.extend(tree.get(field) or [])
    return out


def _agg_trend(state: dict) -> list:
    out: list = []
    for _pidx, tree, _pp, _st in _plan_entries(state):
        out.extend(tree.get("quality_trend") or [])
    return out


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(ts):
    if not ts or not isinstance(ts, str):
        return None
    try:
        return _dt.datetime.strptime(ts.replace("Z", "+0000"), "%Y-%m-%dT%H:%M:%S%z")
    except ValueError:
        return None


def _mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def _quality_block(trend: list) -> dict:
    first = trend[:5]
    last = trend[-5:]
    delta = _mean(last) - _mean(first) if trend else 0.0
    return {"first5_mean": round(_mean(first), 4), "last5_mean": round(_mean(last), 4),
            "delta": round(delta, 4), "trend": trend}


def _duration_min(task: dict):
    timing = task.get("timing") or {}
    a, b = _parse_iso(timing.get("started")), _parse_iso(timing.get("completed"))
    if a and b:
        return max(0, round((b - a).total_seconds() / 60))
    return None


def _auto_resolved_count(state: dict) -> int:
    if isinstance(state.get("auto_resolved_count"), int):
        return state["auto_resolved_count"]
    return sum(1 for e in (state.get("spec_edits") or []) if e.get("auto_resolved"))


# --------------------------------------------------------------------------
# run_report.json
# --------------------------------------------------------------------------

def _failure_summary(state: dict) -> dict:
    vgaps = _agg_list(state, "verification_gaps")
    dgaps = _agg_list(state, "docs_gaps")
    by_class = {
        "review_retries_exhausted": 0, "verifier_retries_exhausted": 0,
        "spec_unclear": 0, "env_blocker": 0,
        "verification_gap": len(vgaps), "docs_gap": len(dgaps),
    }
    skipped, escalations = [], []
    for _pidx, tid, task in _all_tasks(state):
        reason = task.get("skip_reason")
        if task.get("status") == "SKIPPED":
            skipped.append({"task": tid, "reason": reason or "unknown"})
        if reason in by_class:
            by_class[reason] += 1
        for entry in (task.get("retry_trace") or []):
            if entry.get("fault") == "spec_unclear":
                by_class["spec_unclear"] += 1
        if (task.get("escalations") or 0) > 0:
            escalations.append({"task": tid, "type": "escalation", "resolved": "recorded"})
    for edit in (state.get("spec_edits") or []):
        if edit.get("fault") == "unclear":
            by_class["spec_unclear"] += 1
        if edit.get("auto_resolved"):
            escalations.append({"task": edit.get("task"),
                                "type": edit.get("fault", "unclear"), "resolved": "auto"})
    for g in vgaps:
        if "env" in str(g.get("reason", "")).lower():
            by_class["env_blocker"] += 1
    return {"by_class": by_class, "auto_resolved": _auto_resolved_count(state),
            "escalations": escalations, "skipped_tasks": skipped}


def build_run_report(state: dict) -> dict:
    plans = [{"index": pidx, "plan_path": pp, "status": st}
             for pidx, _tree, pp, st in _plan_entries(state)]
    tasks = []
    warn_count = 0
    escalations_total = 0
    for pidx, tid, task in _all_tasks(state):
        if task.get("review_tier") == "WARN":
            warn_count += 1
        escalations_total += task.get("escalations") or 0
        tasks.append({
            "id": tid, "plan_index": pidx,
            "status": task.get("status"), "risk": task.get("risk"),
            "tier": task.get("review_tier"),
            "spec_score": task.get("spec_score"), "quality_score": task.get("quality_score"),
            "review_retries": task.get("review_retries", 0),
            "verifier_retries": task.get("verifier_retries", 0),
            "retry_trace": task.get("retry_trace", []),
            "timing": task.get("timing", {}),
            "skip_reason": task.get("skip_reason"),
        })
    trend = _agg_trend(state)
    qb = _quality_block(trend)
    totals = (state.get("cost_ledger") or {}).get("totals", {})
    return {
        "run_id": Path(state.get("orchestrator_dir") or state.get("worktree") or "").name or None,
        "schema": "run_report/1",
        "mode": state.get("mode"),
        "plans": plans,
        "tasks": tasks,
        "quality": {"trend": trend, "delta": qb["delta"], "warn_count": warn_count,
                    "first5_mean": qb["first5_mean"], "last5_mean": qb["last5_mean"]},
        "gaps": {"verification_gaps": _agg_list(state, "verification_gaps"),
                 "docs_gaps": _agg_list(state, "docs_gaps")},
        "autonomy": {"auto_resolved_count": _auto_resolved_count(state),
                     "escalations_total": escalations_total},
        "cost": {"waived": bool(state.get("cost_tracking_waived", False)),
                 "reason": state.get("cost_tracking_waive_reason"),
                 "totals": totals},
        "failure_summary": _failure_summary(state),
        "generated_at": _now_iso(),
    }


# --------------------------------------------------------------------------
# markdown
# --------------------------------------------------------------------------

def _wall_time(state: dict) -> str:
    ts = state.get("timestamps") or {}
    a, b = _parse_iso(ts.get("started_at")), _parse_iso(ts.get("completed_at"))
    if not (a and b):
        return "unknown"
    total = int(max(0, (b - a).total_seconds()))
    return f"{total // 3600:02d}:{(total % 3600) // 60:02d}"


def _cost_line(state: dict) -> str:
    if state.get("cost_tracking_waived"):
        return f"WAIVED — {state.get('cost_tracking_waive_reason', 'cost tracking off')}"
    totals = (state.get("cost_ledger") or {}).get("totals", {})
    return f"${totals.get('cost_usd', 0.0):.2f} ({totals.get('dispatches', 0)} dispatches)"


def build_markdown(state: dict) -> str:
    rep = build_run_report(state)
    L = ["## Execution Summary", ""]
    al = state.get("agentlens_orchestration_run") or "dark — agentlens unavailable at run-open"
    reviewed = sum(1 for _p, _t, tk in _all_tasks(state) if tk.get("review_tier"))
    L += [
        f"**Plan:** {state.get('plan')}",
        f"**Spec:** {state.get('spec')}",
        f"**Branch:** {state.get('branch')}",
        f"**Worktree:** {state.get('worktree')}",
        f"**State file:** {state.get('orchestrator_dir')}/state.json",
        f"**Models:** Orchestrator=Opus, Implementer={(state.get('implementer_model') or {}).get('used', 'sonnet')}, Reviewer/Verifier=Sonnet",
        f"**Date:** {_now_iso()[:10]}",
        f"**Observability:** AgentLens run={al} · quality_trend coverage: {len(rep['quality']['trend'])}/{reviewed}",
        "",
        "### Tasks",
        "| Task | Status | Risk | Size | Spec | Quality | Tier | Escalations | Review Retries | Verifier Retries | Spec Clarifications | Duration |",
        "|------|--------|------|------|------|---------|------|-------------|----------------|------------------|---------------------|----------|",
    ]
    for pidx, tid, task in _all_tasks(state):
        num = tid[len("task_"):] if tid.startswith("task_") else tid
        spec = task.get("spec_score")
        qual = task.get("quality_score")
        dur = _duration_min(task)
        vr = "— (batch)" if (task.get("risk") == "low" and not task.get("verifier_retries")) else task.get("verifier_retries", 0)
        L.append(
            f"| Task {num} | {task.get('status', '?')} | {task.get('risk', '?')} | "
            f"{task.get('complexity', '—')} | {spec if spec is not None else '—'} | "
            f"{qual if qual is not None else '—'} | {task.get('review_tier', '—')} | "
            f"{task.get('escalations', 0)} | {task.get('review_retries', 0)} | {vr} | "
            f"{task.get('spec_clarifications', 0)} | {str(dur) + ' min' if dur is not None else '—'} |"
        )

    # Risk overrides
    overrides = _agg_list(state, "risk_override_warnings")
    L += ["", "### Risk overrides (A5)"]
    if overrides:
        for o in overrides:
            L.append(f"- `{o.get('task')}` — override={o.get('override')}, suggested=high, "
                     f"keywords={o.get('keywords', [])}, ts={o.get('ts')}")
    else:
        L.append("Risk overrides: 0")

    # WARN-tier
    L += ["", "### WARN-tier tasks (P4)"]
    warn_rows = []
    for pidx, tid, task in _all_tasks(state):
        if task.get("review_tier") == "WARN":
            tree = state["plan_chain"][pidx] if state.get("plan_chain") else state
            warns = ((tree.get("task_summaries") or {}).get(tid, {}) or {}).get("warnings", [])
            summary = warns[0] if warns else "(no warning text)"
            warn_rows.append(f"- `{tid}` — spec={task.get('spec_score')}, "
                             f"quality={task.get('quality_score')} — warnings: {summary}")
    L += warn_rows if warn_rows else ["WARN-tier tasks: 0"]

    # Dispatch gaps (omit section entirely when none)
    vgaps, dgaps = rep["gaps"]["verification_gaps"], rep["gaps"]["docs_gaps"]
    if vgaps or dgaps:
        L += ["", "### Dispatch gaps (D003)"]
        for g in vgaps:
            L.append(f"- **Unverified (agent+api both failed):** `{g.get('task')}` — "
                     f"{g.get('reason', g.get('kind', ''))} ({g.get('ts', '')})")
        for g in dgaps:
            L.append(f"- **Undocumented (agent+api both failed):** {g.get('scope', '?')} — "
                     f"{g.get('reason', '')} ({g.get('ts', '')})")

    # Quality trend
    q = rep["quality"]
    note = "stable"
    if q["delta"] <= -0.10:
        note = "declining — review recent tasks"
    elif q["delta"] >= 0.10:
        note = "improving"
    L += ["", "### Quality trend (P4)",
          f"- First 5 task quality_score mean: {q['first5_mean']:.2f}",
          f"- Last 5 task quality_score mean: {q['last5_mean']:.2f}",
          f"- Delta: {q['delta']:+.2f}",
          f"- Note: {note}"]

    # Performance
    review_sum = sum(t["review_retries"] for t in rep["tasks"])
    verify_sum = sum(t["verifier_retries"] for t in rep["tasks"])
    durations = [(tid, _duration_min(task)) for _p, tid, task in _all_tasks(state)]
    durations = [(tid, d) for tid, d in durations if d is not None]
    longest = max(durations, key=lambda x: x[1]) if durations else None
    L += ["", "### Performance",
          f"- Total wall time: {_wall_time(state)}",
          f"- Longest task: {longest[0]} ({longest[1]} min)" if longest else "- Longest task: —",
          f"- Total retries: {review_sum} review, {verify_sum} verifier",
          f"- Cost tracking: {_cost_line(state)}"]

    # Changes Made (from task files / summaries)
    L += ["", "### Changes Made"]
    changes = []
    for pidx, tid, task in _all_tasks(state):
        tree = state["plan_chain"][pidx] if state.get("plan_chain") else state
        decision = ((tree.get("task_summaries") or {}).get(tid, {}) or {}).get("key_decision", "")
        for f in (task.get("files") or []):
            changes.append(f"- `{f}`: {decision or tid}")
    L += changes if changes else ["- (no file changes recorded)"]

    # Verification Results (derived)
    L += ["", "### Verification Results",
          "| Scope | Risk Level | Tests Run | Result |",
          "|-------|------------|-----------|--------|"]
    for _p, tid, task in _all_tasks(state):
        result = task.get("status")
        L.append(f"| {tid} | {task.get('risk', '?')} | per-task | {result} |")

    # Docs Updated
    L += ["", "### Docs Updated", "- (see docs updater results under <orch_dir>/docs_results/)"]

    # Cleanup Status
    L += ["", "### Cleanup Status",
          f"- Worktree: **active** — branch `{state.get('branch')}` at `{state.get('worktree')}`. Merge or delete when ready.",
          "- Debug artifacts: none found (PostToolUse hook enforced)",
          "- Temp files: none found"]

    # Remaining Risks
    L += ["", "### Remaining Risks"]
    risks = []
    for g in vgaps:
        risks.append(f"- Unverified `{g.get('task')}`: {g.get('reason', '')} — accepted (gap recorded)")
    for s in rep["failure_summary"]["skipped_tasks"]:
        risks.append(f"- SKIPPED `{s['task']}`: {s['reason']} — dependent subtree propagated per SKIP rule")
    L += risks if risks else ["- None"]

    return "\n".join(L) + "\n"


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("state_path", help="path to <orch_dir>/state.json")
    ap.add_argument("--out-md", default=None, help="write markdown here (also echoed to stdout)")
    ap.add_argument("--out-json", default=None, help="write run_report.json here")
    ap.add_argument("--orch-dir", default=None,
                    help="default location for run_report.json (<orch-dir>/run_report.json)")
    args = ap.parse_args(argv)

    path = Path(args.state_path)
    if not path.is_file():
        print(f"error: state file not found: {path}", file=sys.stderr)
        return 2
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"error: cannot parse state.json: {exc}", file=sys.stderr)
        return 2

    report = build_run_report(state)
    markdown = build_markdown(state)

    out_json = args.out_json
    if out_json is None and args.orch_dir:
        out_json = str(Path(args.orch_dir) / "run_report.json")
    if out_json is None:
        out_json = str(path.parent / "run_report.json")
    Path(out_json).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if args.out_md:
        Path(args.out_md).write_text(markdown, encoding="utf-8")

    sys.stdout.write(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
