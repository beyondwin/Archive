#!/usr/bin/env python3
"""Summarize kws-codex-plan-executor run health via AgentLens.

Post-v2.17 AgentLens cutover (Task 13), this skill no longer writes a
`~/.codex/learning/kws-codex-plan-executor/` shard tree. All runs publish
to AgentLens; this helper queries the AgentLens runs catalog (`agentlens
status`) plus per-run events (`agentlens events`) to answer the same
"what runs do I have, did they finish, any warnings?" question.

Output: one summary line per run by default. `--json` emits the structured
form (preserved shape from pre-cutover callers).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import subprocess
import sys
from typing import Any


CPE_AGENT_PREFIXES = ("kws-cpe", "kws-codex-plan-executor")
TERMINAL_OUTCOMES = {"success", "blocked", "failed", "error", "cancelled"}


def _which_agentlens() -> str | None:
    return shutil.which("agentlens")


def _runs_from_agentlens(agentlens_bin: str) -> list[dict[str, Any]]:
    """Pull all runs from `agentlens status --format json`."""
    completed = subprocess.run(
        [agentlens_bin, "status", "--format", "json"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=10,
    )
    if completed.returncode != 0:
        return []
    raw = completed.stdout.strip()
    if not raw:
        return []
    data = json.loads(raw)
    if not isinstance(data, list):
        return []
    return [r for r in data if isinstance(r, dict)]


def _is_cpe_run(run: dict[str, Any]) -> bool:
    name = str(run.get("agent_name") or "")
    return any(name.startswith(prefix) for prefix in CPE_AGENT_PREFIXES)


def _count_cpe_events(agentlens_bin: str, run_id: str) -> int:
    completed = subprocess.run(
        [agentlens_bin, "events", "--run", run_id, "--type", "kws-cpe.*"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=10,
    )
    if completed.returncode != 0:
        return 0
    return sum(1 for line in completed.stdout.splitlines() if line.strip())


def _classify(run: dict[str, Any], *, now: dt.datetime, stale_after_minutes: int) -> tuple[str, list[str]]:
    outcome = str(run.get("agent_outcome") or "")
    if outcome in TERMINAL_OUTCOMES:
        return outcome, []

    sealed = str(run.get("sealed_phase") or "")
    if sealed == "final":
        return outcome or "unknown", []

    # Still active — check staleness from started_at.
    started = run.get("started_at")
    if isinstance(started, str):
        try:
            ts = dt.datetime.fromisoformat(started.replace("Z", "+00:00"))
        except ValueError:
            ts = None
        if ts is not None and ts.tzinfo is None:
            ts = ts.replace(tzinfo=dt.UTC)
        if ts is not None and now - ts > dt.timedelta(minutes=stale_after_minutes):
            return "stale_candidate", ["run_started_past_threshold_no_final"]
    return "in_progress", []


def summarize_run(
    agentlens_bin: str,
    run: dict[str, Any],
    *,
    now: dt.datetime,
    stale_after_minutes: int,
) -> dict[str, Any]:
    run_id = str(run.get("run_id") or "")
    status, warnings = _classify(run, now=now, stale_after_minutes=stale_after_minutes)
    event_count = _count_cpe_events(agentlens_bin, run_id) if run_id else 0
    return {
        "run_id": run_id,
        "status": status,
        "agent_name": run.get("agent_name"),
        "started_at": run.get("started_at"),
        "ended_at": run.get("ended_at"),
        "event_count": event_count,
        "event_note": (
            "routine_success_no_notable_events"
            if status == "success" and event_count == 0
            else None
        ),
        "warnings": warnings,
        "diagnostics": {"info": [], "warnings": warnings},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest", type=int, default=5)
    parser.add_argument("--stale-after-minutes", type=int, default=30)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    agentlens_bin = _which_agentlens()
    if agentlens_bin is None:
        msg = "agentlens CLI not on PATH — install AgentLens to query CPE run health"
        if args.json:
            print(json.dumps({"schema_version": "2", "error": msg, "runs": []}, indent=2))
        else:
            print(msg, file=sys.stderr)
        return 1

    runs = _runs_from_agentlens(agentlens_bin)
    cpe_runs = sorted(
        [r for r in runs if _is_cpe_run(r)],
        key=lambda r: str(r.get("started_at") or ""),
        reverse=True,
    )[: args.latest]

    now = dt.datetime.now(dt.UTC)
    summaries = [
        summarize_run(agentlens_bin, run, now=now, stale_after_minutes=args.stale_after_minutes)
        for run in cpe_runs
    ]

    if args.json:
        print(json.dumps({"schema_version": "2", "runs": summaries}, indent=2, sort_keys=True))
        return 0

    for item in summaries:
        warnings = ",".join(item["warnings"]) if item["warnings"] else "-"
        print(f"{item['status']:18} events={item['event_count']:>3} warnings={warnings} {item['run_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
