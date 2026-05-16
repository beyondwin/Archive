#!/usr/bin/env python3
"""Aggregate v2.12 implementer-model A/B run results.

Reads multiple state.json files (one per run), groups runs by
`implementer_model.used`, and emits:

  1. A per-arm summary across all tasks (mean spec_score, mean
     quality_score, tier distribution, total retries, total escalations,
     wall-time mean).
  2. A per-complexity-bucket breakdown so SMALL/MEDIUM/LARGE deltas are
     visible separately (the headline question of the experiment).
  3. Optional CSV dump for further analysis.

Usage:
    python3 aggregate.py state1.json state2.json ... [--csv out.csv]

The script is intentionally stdlib-only so it runs in any environment.
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


# ---- data model ----------------------------------------------------------


@dataclass
class TaskRow:
    run_id: str
    task_id: str
    arm: str  # "sonnet" or "opus"
    complexity: str  # "SMALL" / "MEDIUM" / "LARGE" / "UNKNOWN"
    risk: str
    spec_score: float | None
    quality_score: float | None
    review_tier: str | None
    review_retries: int
    verifier_retries: int
    escalations: int
    spec_clarifications: int
    duration_sec: float | None


@dataclass
class ArmStats:
    arm: str
    runs: int = 0
    tasks: int = 0
    by_complexity: dict[str, list[TaskRow]] = field(default_factory=dict)
    wall_times_sec: list[float] = field(default_factory=list)


# ---- loading -------------------------------------------------------------


def _safe_get(d: dict[str, Any], *path, default=None):
    cur: Any = d
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _arm_of(state: dict[str, Any]) -> str:
    used = _safe_get(state, "implementer_model", "used")
    if used in ("sonnet", "opus"):
        return used
    # Legacy state.json (pre-v2.12) — historically defaulted to sonnet.
    return "sonnet"


def _active_tasks(state: dict[str, Any]) -> dict[str, Any]:
    if state.get("active_plan") == "plan2":
        return _safe_get(state, "plan2_state", "tasks", default={}) or {}
    return state.get("tasks", {}) or {}


def _run_wall_time(state: dict[str, Any]) -> float | None:
    started = _parse_iso(_safe_get(state, "timestamps", "started_at"))
    completed = _parse_iso(_safe_get(state, "timestamps", "completed_at"))
    if not started or not completed:
        return None
    return (completed - started).total_seconds()


def load_state(path: Path) -> tuple[list[TaskRow], float | None, str]:
    state = json.loads(path.read_text())
    arm = _arm_of(state)
    run_id = state.get("branch") or path.parent.name or path.stem
    tasks = _active_tasks(state)
    rows: list[TaskRow] = []
    for task_id, t in tasks.items():
        if t.get("status") not in ("COMPLETE", "SKIPPED"):
            continue
        timing = t.get("timing") or {}
        started = _parse_iso(timing.get("started"))
        completed = _parse_iso(timing.get("completed"))
        duration = (
            (completed - started).total_seconds()
            if started and completed
            else None
        )
        rows.append(
            TaskRow(
                run_id=run_id,
                task_id=task_id,
                arm=arm,
                complexity=t.get("complexity") or "UNKNOWN",
                risk=t.get("risk") or "unknown",
                spec_score=t.get("spec_score"),
                quality_score=t.get("quality_score"),
                review_tier=t.get("review_tier"),
                review_retries=t.get("review_retries", 0),
                verifier_retries=t.get("verifier_retries", 0),
                escalations=t.get("escalations", 0),
                spec_clarifications=t.get("spec_clarifications", 0),
                duration_sec=duration,
            )
        )
    return rows, _run_wall_time(state), arm


# ---- analysis ------------------------------------------------------------


def _mean(xs: list[float]) -> float | None:
    xs = [x for x in xs if x is not None]
    return statistics.fmean(xs) if xs else None


def _stdev(xs: list[float]) -> float | None:
    xs = [x for x in xs if x is not None]
    return statistics.pstdev(xs) if len(xs) >= 2 else None


def _fmt(v: float | None, digits: int = 3) -> str:
    return f"{v:.{digits}f}" if v is not None else "—"


def _tier_dist(rows: list[TaskRow]) -> dict[str, int]:
    out: dict[str, int] = {"PASS": 0, "WARN": 0, "FAIL": 0, "OTHER": 0}
    for r in rows:
        key = r.review_tier if r.review_tier in out else "OTHER"
        out[key] += 1
    return out


def build_arm_stats(rows: list[TaskRow], wall_times: dict[str, list[float]]) -> dict[str, ArmStats]:
    arms: dict[str, ArmStats] = {}
    for r in rows:
        arm = arms.setdefault(r.arm, ArmStats(arm=r.arm))
        arm.tasks += 1
        arm.by_complexity.setdefault(r.complexity, []).append(r)
    for arm_name, wts in wall_times.items():
        if arm_name in arms:
            arms[arm_name].wall_times_sec = wts
            arms[arm_name].runs = len(wts)
    return arms


# ---- reporting -----------------------------------------------------------


def report(arms: dict[str, ArmStats]) -> str:
    lines: list[str] = []
    lines.append("=" * 78)
    lines.append("v2.12 — Implementer Opus vs Sonnet (aggregated)")
    lines.append("=" * 78)
    for arm_name in sorted(arms):
        arm = arms[arm_name]
        all_rows = [r for bucket in arm.by_complexity.values() for r in bucket]
        spec = _mean([r.spec_score for r in all_rows if r.spec_score is not None])
        qual = _mean([r.quality_score for r in all_rows if r.quality_score is not None])
        spec_sd = _stdev([r.spec_score for r in all_rows if r.spec_score is not None])
        qual_sd = _stdev([r.quality_score for r in all_rows if r.quality_score is not None])
        tiers = _tier_dist(all_rows)
        total_review_retries = sum(r.review_retries for r in all_rows)
        total_verifier_retries = sum(r.verifier_retries for r in all_rows)
        total_escalations = sum(r.escalations for r in all_rows)
        total_clarifications = sum(r.spec_clarifications for r in all_rows)
        wt_mean = _mean(arm.wall_times_sec)
        wt_sd = _stdev(arm.wall_times_sec)
        lines.append("")
        lines.append(f"### Arm: {arm_name.upper()}  (runs={arm.runs}, tasks={arm.tasks})")
        lines.append(f"  spec_score      mean={_fmt(spec)}  sd={_fmt(spec_sd)}")
        lines.append(f"  quality_score   mean={_fmt(qual)}  sd={_fmt(qual_sd)}")
        lines.append(
            f"  tiers           PASS={tiers['PASS']}  WARN={tiers['WARN']}  "
            f"FAIL={tiers['FAIL']}  OTHER={tiers['OTHER']}"
        )
        lines.append(
            f"  retries (total) review={total_review_retries}  "
            f"verifier={total_verifier_retries}  "
            f"escalations={total_escalations}  spec_clarif={total_clarifications}"
        )
        lines.append(
            f"  wall time (sec) mean={_fmt(wt_mean, 1)}  sd={_fmt(wt_sd, 1)}  n={len(arm.wall_times_sec)}"
        )
        lines.append("  by complexity:")
        for bucket in ("SMALL", "MEDIUM", "LARGE", "UNKNOWN"):
            rows = arm.by_complexity.get(bucket, [])
            if not rows:
                continue
            b_spec = _mean([r.spec_score for r in rows if r.spec_score is not None])
            b_qual = _mean([r.quality_score for r in rows if r.quality_score is not None])
            b_tiers = _tier_dist(rows)
            b_retries = sum(r.review_retries + r.verifier_retries for r in rows)
            lines.append(
                f"    {bucket:6s} n={len(rows):>3}  "
                f"spec={_fmt(b_spec)}  quality={_fmt(b_qual)}  "
                f"retries={b_retries}  "
                f"P/W/F={b_tiers['PASS']}/{b_tiers['WARN']}/{b_tiers['FAIL']}"
            )
    lines.append("")
    lines.append("=" * 78)
    lines.append("Delta (Opus - Sonnet) by complexity")
    lines.append("=" * 78)
    sonnet = arms.get("sonnet")
    opus = arms.get("opus")
    if not (sonnet and opus):
        lines.append("(need both arms to compute delta)")
    else:
        for bucket in ("SMALL", "MEDIUM", "LARGE", "UNKNOWN"):
            s_rows = sonnet.by_complexity.get(bucket, [])
            o_rows = opus.by_complexity.get(bucket, [])
            if not (s_rows and o_rows):
                continue
            ds_spec = (_mean([r.spec_score for r in o_rows]) or 0) - (
                _mean([r.spec_score for r in s_rows]) or 0
            )
            ds_qual = (_mean([r.quality_score for r in o_rows]) or 0) - (
                _mean([r.quality_score for r in s_rows]) or 0
            )
            s_retries = sum(r.review_retries + r.verifier_retries for r in s_rows) / max(len(s_rows), 1)
            o_retries = sum(r.review_retries + r.verifier_retries for r in o_rows) / max(len(o_rows), 1)
            lines.append(
                f"  {bucket:6s} Δspec={ds_spec:+.3f}  Δquality={ds_qual:+.3f}  "
                f"Δretries_per_task={o_retries - s_retries:+.2f}"
            )
    return "\n".join(lines) + "\n"


def write_csv(rows: list[TaskRow], out_path: Path) -> None:
    with out_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "run_id", "task_id", "arm", "complexity", "risk",
            "spec_score", "quality_score", "review_tier",
            "review_retries", "verifier_retries", "escalations",
            "spec_clarifications", "duration_sec",
        ])
        for r in rows:
            w.writerow([
                r.run_id, r.task_id, r.arm, r.complexity, r.risk,
                r.spec_score, r.quality_score, r.review_tier,
                r.review_retries, r.verifier_retries, r.escalations,
                r.spec_clarifications, r.duration_sec,
            ])


# ---- main ----------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("state_files", nargs="+", help="paths to state.json files")
    ap.add_argument("--csv", type=Path, help="optional CSV output path")
    args = ap.parse_args()

    all_rows: list[TaskRow] = []
    wall_times: dict[str, list[float]] = {"sonnet": [], "opus": []}

    for sp in args.state_files:
        p = Path(sp)
        if not p.exists():
            print(f"warning: state file not found: {p}", file=sys.stderr)
            continue
        rows, wt, arm = load_state(p)
        all_rows.extend(rows)
        if wt is not None:
            wall_times.setdefault(arm, []).append(wt)

    if not all_rows:
        print("no rows loaded — nothing to report", file=sys.stderr)
        return 1

    arms = build_arm_stats(all_rows, wall_times)
    print(report(arms))

    if args.csv:
        write_csv(all_rows, args.csv)
        print(f"CSV written: {args.csv}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
