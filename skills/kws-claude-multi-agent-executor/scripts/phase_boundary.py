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
        timing = result.setdefault("timing", {})
        timing["completed"] = ss._utc_now_iso()
        tasks[task] = result
        active["last_completed_task"] = task
        active["last_completed_at"] = ss._utc_now_iso()
    _locked_rmw(state_path, mutate)

    # State write succeeded; emit is best-effort.
    _emit(run_id, "task_completed", json.dumps(payload, ensure_ascii=False))
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
    except json.JSONDecodeError as exc:
        print(f"JSON parse failed: {exc}", file=sys.stderr)
        return 1
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"phase_boundary failed: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
