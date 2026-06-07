#!/usr/bin/env python3
"""Bundle the mandatory state writes + AgentLens emits at each phase boundary.

The recurring silent-skip regressions (phase_0_started never emitted,
timing.started/completed left null, task_completed dropped) all share one shape:
a *mandatory* action expressed as scattered prose, performed by the orchestrator
by hand, with nothing enforcing it. This helper collapses each boundary's
required writes into a single call site that is eval-checkable and far harder to
drop than the six prose paragraphs it replaces (see D002).

Subcommands:

  task-start --state <p> --task <id> --pre-sha <sha>
      Stamp run-level `current_pre_task_sha` and per-active
      `tasks.<id>.timing.started` in one atomic write. The pre-sha is the
      crash-recovery baseline (hard requirement); timing.started feeds the
      duration report. Both land together so neither can be silently skipped.

  task-complete --state <p> --task <id> --result-json <f> --run-id <r>
      Write the full task result under the active tree at `tasks.<id>`, force
      `tasks.<id>.timing.completed = now`, advance the active
      last_completed_task / last_completed_at pointers (one atomic write), then
      emit `kws-cme.task_completed`. Cost accumulation is NOT done here — it is a
      per-dispatch concern owned by accumulate_cost.py (see D002 refinement).

  phase-emit --state <p> --run-id <r>
             --type <phase_0_started|compaction|phase_2_complete>
             --payload-json <j>
      Emit `kws-cme.<type>` and stamp its paired run-level timestamp:
        phase_0_started  → timestamps.started_at  (setdefault — preserve earlier)
        phase_2_complete → timestamps.completed_at (overwrite)
        compaction       → no run-level timestamp (emit only)

Active-tree resolution + the flock-guarded R-M-W + atomic rename are reused from
state_set.py so there is exactly one implementation of the `<active>` rule.

AgentLens emits are best-effort: the `agentlens` CLI is invoked with stderr
discarded and a non-zero exit ignored, so observability never blocks execution.
Every NON-emit write (the state mutations) MUST still succeed — a failed state
write exits non-zero so the caller's hard-halt guardrail fires.

Exit codes:
- 0  success
- 1  argparse / IO / JSON / resolution / readback failure (stderr message)
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
import sys
from pathlib import Path

try:
    import state_set as ss  # type: ignore
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import state_set as ss  # type: ignore


EMIT_TYPES = ("phase_0_started", "compaction", "phase_2_complete")


def _locked_rmw(state_path: Path, mutate):
    """flock the sibling lock file, read state, run mutate(state), atomic-write."""
    lock_path = state_path.with_name(state_path.name + ".lock")
    lock = open(lock_path, "w", encoding="utf-8")
    fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
    try:
        with open(state_path, "r", encoding="utf-8") as fh:
            state = json.load(fh)
        mutate(state)
        ss._atomic_write_json(state_path, state)
    finally:
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()


def _emit(run_id: str | None, etype: str, payload_json: str | None) -> None:
    """Best-effort AgentLens event append. Never raises, never blocks."""
    if not run_id:
        return
    cmd = ["agentlens", "event", "append", "--run", run_id, "--type", f"kws-cme.{etype}"]
    if payload_json:
        cmd += ["--payload-json", payload_json]
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    except OSError:
        pass  # CLI absent — silent, run proceeds without observability


def _tee_event(orch_dir, etype: str, payload_json: str | None) -> None:
    """Append a boundary event to <orch_dir>/events.jsonl (v2.29 — I2).

    The orchestrator-single-writer local replay log: every boundary emit is
    teed here REGARDLESS of AgentLens reachability, so an all-agent attached run
    (the default, where the agentlens CLI is usually absent and every `_emit`
    no-ops) still produces a complete, ordered, machine-readable timeline. This
    is a fallback tee owned by the one orchestrator process — NOT the parallel
    Lens sink removed in v2.17, and NOT written by sub-agents (AGENTS.md compliance).

    Best-effort: a tee failure (bad dir, full disk) is swallowed — observability
    must never block plan execution, same contract as `_emit`.
    """
    try:
        payload = json.loads(payload_json) if payload_json else None
    except (ValueError, TypeError):
        payload = payload_json  # not JSON — preserve the raw string
    event = {"ts": ss._utc_now_iso(), "type": f"kws-cme.{etype}", "payload": payload}
    try:
        with open(os.path.join(str(orch_dir), "events.jsonl"), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")
    except OSError:
        pass  # local tee unavailable — silent, run proceeds


def _active(state: dict) -> dict:
    return ss.resolve_active_tree(state, "active", force_run=False)


def cmd_task_start(state_path: Path, task: str, pre_sha: str) -> None:
    def mutate(state: dict) -> None:
        state["current_pre_task_sha"] = pre_sha  # run-level crash baseline
        active = _active(state)
        tasks = active.setdefault("tasks", {})
        timing = tasks.setdefault(task, {}).setdefault("timing", {})
        timing["started"] = ss._utc_now_iso()
    _locked_rmw(state_path, mutate)


def cmd_task_complete(
    state_path: Path, task: str, result: dict, run_id: str | None
) -> dict:
    payload = {
        "task": task,
        "status": result.get("status", "COMPLETE"),
        "risk": result.get("risk"),
        "review_tier": result.get("review_tier"),
        "commit": result.get("commit"),
    }

    def mutate(state: dict) -> None:
        active = _active(state)
        tasks = active.setdefault("tasks", {})
        prior = tasks.get(task) or {}
        # Preserve the timing.started that task-start wrote: replacing the whole
        # task entry below would otherwise discard it, leaving started null at
        # finalize (defeats the D003 timing_inverted / timing_tracking checks).
        prior_started = (prior.get("timing") or {}).get("started")
        timing = result.setdefault("timing", {})
        if prior_started and not timing.get("started"):
            timing["started"] = prior_started
        timing["completed"] = ss._utc_now_iso()
        # Preserve the append-only retry_trace (v2.29 I3): it is written during
        # retries (before completion); the result object replaces the entry, so
        # carry it forward unless the result already supplies one.
        prior_trace = prior.get("retry_trace")
        if prior_trace and not result.get("retry_trace"):
            result["retry_trace"] = prior_trace
        tasks[task] = result
        active["last_completed_task"] = task
        active["last_completed_at"] = ss._utc_now_iso()
        score = result.get("quality_score")
        if score is not None:  # v2.28 (D003): single unskippable trend writer
            qt = active.setdefault("quality_trend", [])
            qt.append(score)
            del qt[:-10]  # cap at 10, keep newest
    _locked_rmw(state_path, mutate)

    # State write succeeded; emit + local tee are best-effort.
    payload_json = json.dumps(payload, ensure_ascii=False)
    _tee_event(state_path.parent, "task_completed", payload_json)
    _emit(run_id, "task_completed", payload_json)
    return payload


def cmd_phase_emit(
    state_path: Path, etype: str, run_id: str | None, payload_json: str | None
) -> None:
    # Paired run-level timestamp stamp (bundled so it cannot be skipped).
    if etype in ("phase_0_started", "phase_2_complete"):
        field = "started_at" if etype == "phase_0_started" else "completed_at"

        def mutate(state: dict) -> None:
            ts = state.setdefault("timestamps", {})
            if etype == "phase_0_started":
                if ts.get(field) is None:  # preserve a real earlier start, fill null/absent
                    ts[field] = ss._utc_now_iso()
            else:
                ts[field] = ss._utc_now_iso()
        _locked_rmw(state_path, mutate)
    # compaction: emit only, no run-level timestamp.

    _tee_event(state_path.parent, etype, payload_json)
    _emit(run_id, etype, payload_json)


def cmd_retry_trace(
    state_path: Path,
    task: str,
    kind: str,
    fault: str,
    tier: str | None,
    recurring_keys: list | None,
    attempt: int | None,
) -> None:
    """Append one append-only entry to `<active>.tasks.<task>.retry_trace` (v2.29 I3).

    `current_previous_issues` is a volatile single-slot buffer the orchestrator
    overwrites every retry, so "why did each retry happen" was lost. This records
    one immutable row per attempt (fault class, RECURRING ISSUE_KEYs, review tier)
    before that overwrite, giving build_final_report.py the per-task decision
    trace. Never mutates or removes an existing entry.
    """
    def mutate(state: dict) -> None:
        active = _active(state)
        tasks = active.setdefault("tasks", {})
        trace = tasks.setdefault(task, {}).setdefault("retry_trace", [])
        n = attempt if attempt is not None else (
            sum(1 for e in trace if e.get("kind") == kind) + 1
        )
        trace.append({
            "attempt": n,
            "kind": kind,
            "fault": fault,
            "recurring_keys": recurring_keys or [],
            "tier": tier,
            "ts": ss._utc_now_iso(),
        })
    _locked_rmw(state_path, mutate)


def cmd_emit(
    state_path: Path, etype: str, run_id: str | None, payload_json: str | None
) -> None:
    """Generic boundary emit (v2.29 — I2): local tee + best-effort AgentLens.

    Used for events that are NOT one of the three state-stamping phase types —
    e.g. `blocker` from the I1 retry-exhaustion SKIP path. Reads/writes NO state
    (the `<orch_dir>` is derived from the state path's parent only to locate
    events.jsonl); `etype` is free-form by design.
    """
    _tee_event(state_path.parent, etype, payload_json)
    _emit(run_id, etype, payload_json)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_start = sub.add_parser("task-start", help="stamp pre-sha + timing.started")
    p_start.add_argument("--state", required=True)
    p_start.add_argument("--task", required=True, help="e.g. task_3")
    p_start.add_argument("--pre-sha", required=True)

    p_done = sub.add_parser("task-complete", help="write result + timing + emit")
    p_done.add_argument("--state", required=True)
    p_done.add_argument("--task", required=True)
    p_done.add_argument("--result-json", required=True, help="path to result JSON file")
    p_done.add_argument("--run-id", default=None, help="AgentLens run id (empty → no emit)")

    p_emit = sub.add_parser("phase-emit", help="emit boundary event + paired stamp")
    p_emit.add_argument("--state", required=True)
    p_emit.add_argument("--run-id", default=None)
    p_emit.add_argument("--type", required=True, choices=EMIT_TYPES)
    p_emit.add_argument("--payload-json", default=None)

    p_rt = sub.add_parser("retry-trace", help="append an append-only retry_trace entry (I3)")
    p_rt.add_argument("--state", required=True)
    p_rt.add_argument("--task", required=True)
    p_rt.add_argument("--kind", required=True, choices=("review", "verify"))
    p_rt.add_argument("--fault", required=True, help="SPEC_FAULT class or verifier category")
    p_rt.add_argument("--tier", default=None, help="review tier (PASS/WARN/FAIL); omit for verify")
    p_rt.add_argument("--recurring-json", default=None, help="JSON array of RECURRING ISSUE_KEYs")
    p_rt.add_argument("--attempt", type=int, default=None, help="explicit attempt no.; default auto")

    p_gen = sub.add_parser("emit", help="generic boundary emit (tee + best-effort AgentLens)")
    p_gen.add_argument("--state", required=True, help="state.json path (parent = orch_dir for events.jsonl)")
    p_gen.add_argument("--run-id", default=None)
    p_gen.add_argument("--type", required=True, help="free-form event type, e.g. blocker")
    p_gen.add_argument("--payload-json", default=None)

    args = ap.parse_args(argv)

    if args.cmd != "phase-emit":
        state_path = Path(args.state)
        if not state_path.is_file():
            print(f"state.json not found at {state_path}", file=sys.stderr)
            return 1

    try:
        if args.cmd == "task-start":
            cmd_task_start(Path(args.state), args.task, args.pre_sha)
        elif args.cmd == "task-complete":
            rp = Path(args.result_json)
            if not rp.is_file():
                print(f"result JSON not found at {rp}", file=sys.stderr)
                return 1
            result = json.loads(rp.read_text(encoding="utf-8"))
            if not isinstance(result, dict):
                print("result JSON must be an object", file=sys.stderr)
                return 1
            payload = cmd_task_complete(Path(args.state), args.task, result, args.run_id or None)
            print(json.dumps(payload, ensure_ascii=False))
        elif args.cmd == "phase-emit":
            state_path = Path(args.state)
            if args.type in ("phase_0_started", "phase_2_complete") and not state_path.is_file():
                print(f"state.json not found at {state_path}", file=sys.stderr)
                return 1
            cmd_phase_emit(state_path, args.type, args.run_id or None, args.payload_json)
        elif args.cmd == "retry-trace":
            recurring = json.loads(args.recurring_json) if args.recurring_json else None
            if recurring is not None and not isinstance(recurring, list):
                print("--recurring-json must be a JSON array", file=sys.stderr)
                return 1
            cmd_retry_trace(Path(args.state), args.task, args.kind, args.fault,
                            args.tier, recurring, args.attempt)
        elif args.cmd == "emit":
            cmd_emit(Path(args.state), args.type, args.run_id or None, args.payload_json)
    except json.JSONDecodeError as exc:
        print(f"JSON parse failed: {exc}", file=sys.stderr)
        return 1
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"phase_boundary failed: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
