#!/usr/bin/env python3
"""kernel.py — CME v3.0 Deterministic Kernel CLI (T9/T14).

Subcommands:
  init        — initialise a new run (T1)
  next        — decide and prepare the next action (T9)
  submit      — accept/reject a sub-agent result (T9)
  check-stop  — check stop condition (T9/T14)
  finalize    — finalise execution (T14)
  inspect     — inspect state (T14, read-only)
"""
import sys
import os
import json
import argparse
import datetime

_KERNEL_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _KERNEL_DIR)

import initcmd as _initcmd
import statefile
import transitions
import dispatch as _dispatch
import ledger as _ledger
import validate as _validate
import events as _events
import drift as _drift
import quality as _quality


# ── path helpers ──────────────────────────────────────────────────────────────

def _skill_dir() -> str:
    """Return the skill root (contains references/, scripts/, …)."""
    # kernel.py lives in scripts/kernel/ → skill_dir is two levels up.
    return os.path.abspath(os.path.join(_KERNEL_DIR, "..", ".."))


def _schema_path(role: str) -> str:
    sd = _skill_dir()
    schema_map = {
        "implementer": "implementer_result.schema.json",
        "reviewer": "reviewer_result.schema.json",
        "verifier": "verifier_result.schema.json",
        "docs_updater": "docs_updater_result.schema.json",
        "plan_reviewer": "plan_reviewer_result.schema.json",
    }
    filename = schema_map.get(role, f"{role}_result.schema.json")
    return os.path.join(sd, "references", "_schemas", filename)


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── handlers ─────────────────────────────────────────────────────────────────

def handle_init(args):
    home = os.environ.get("CME_HOME", os.path.expanduser("~"))
    repo_root = args.repo_root or os.getcwd()
    raw_args = args.args or ""
    dry_run = bool(args.dry_run)
    result = _initcmd.run_init(
        raw_args=raw_args,
        home=home,
        repo_root=repo_root,
        dry_run=dry_run,
    )
    return result


def handle_next(args):
    """Decide the next action and prepare dispatch materials if needed.

    Steps:
    1. Load state from --state path.
    2. transitions.decide(state) → action.
    3. If action == "dispatch":
       a. dispatch.build(state, action, skill_dir, orch_dir) → materials.
       b. transitions.record_timing(state, task_id, "started", now) — set-if-absent.
       c. Write updated state.
       d. Merge materials into action dict and return.
    4. Non-dispatch actions (run_command, compact, escalate_to_user, finalize, halt, done):
       return action as-is (no dispatch build, no state write needed).
    """
    state = statefile.read_state(args.state)
    action = transitions.decide(state)

    if action.get("action") == "dispatch":
        task_id = action["task_id"]
        skill_dir = _skill_dir()
        orch_dir = state.get("orchestrator_dir", os.path.dirname(args.state))

        # Build dispatch materials (writes prompt file, returns paths + command)
        materials = _dispatch.build(state, action, skill_dir, orch_dir)

        # record_timing: stamp "started" only if not already set (set-if-absent)
        active = statefile.active(state)
        task = active["tasks"][task_id]
        timing = task.get("timing", {})
        if not timing.get("started"):
            state = transitions.record_timing(state, task_id, "started", _utc_now_iso())

        # Persist state
        statefile.write_state(args.state, state)

        # Merge materials into the action and return
        result = dict(action)
        result.update(materials)
        return result

    # All other actions: pass through as-is (no state mutation at next time)
    return action


def handle_submit(args):
    """Accept or reject a sub-agent result.

    Steps:
    1. Load state.
    2. ledger.extract_payload(result_file) → (payload, usage).
    3. validate.check(payload, role_schema). If violations:
       - Increment tasks.<id>.schema_violations.
       - Write state.
       - Return {"accepted": false, "violations": [...], "retry_hint": ..., "halt_pending": bool}.
    4. If valid:
       - transitions.apply_result(state, task_id, role, payload) → new state.
       - If task reaches terminal status: record_timing("completed").
       - ledger.record(state, task_id, role, usage) → new state.
       - Reset schema_violations to 0.
       - events.emit("kws-cme.task_progress", ...).
       - Write state.
       - Return {"accepted": true, "next_hint": decide(state)["action"]}.
    """
    state = statefile.read_state(args.state)
    task_id = args.task
    role = args.role
    result_file = args.result

    # Read result file
    try:
        with open(result_file, encoding="utf-8") as f:
            result_text = f.read()
    except OSError as e:
        return {"error": f"cannot_read_result_file: {e}"}

    # Extract payload + usage from claude -p envelope
    try:
        payload, usage = _ledger.extract_payload(result_text)
    except _ledger.LedgerParseError as e:
        return {"error": f"ledger_parse_error: {e}"}

    # Load role schema
    schema_path = _schema_path(role)
    try:
        with open(schema_path, encoding="utf-8") as f:
            schema = json.load(f)
    except OSError as e:
        return {"error": f"cannot_read_schema: {e}"}

    # Validate payload against schema
    violations = _validate.check(payload, schema)
    if violations:
        # Increment schema_violations counter (consecutive halt guard)
        active = statefile.active(state)
        task = active["tasks"][task_id]
        task["schema_violations"] = task.get("schema_violations", 0) + 1
        sv = task["schema_violations"]
        # Increment cumulative total (durable, never reset — used by quality.py)
        task["total_schema_violations"] = task.get("total_schema_violations", 0) + 1

        statefile.write_state(args.state, state)

        rejection = {
            "accepted": False,
            "violations": violations,
            "retry_hint": (
                f"Result for role={role} task={task_id} failed schema validation. "
                f"Fix the following fields and re-submit: {'; '.join(violations[:3])}"
            ),
        }
        if sv >= 3:
            rejection["halt_pending"] = True
        return rejection

    # --- Valid payload ---

    # Apply result to state (immutable)
    state = transitions.apply_result(state, task_id, role, payload)

    # Stamp "completed" timing when the task reaches a terminal/phase-complete status
    active = statefile.active(state)
    task = active["tasks"][task_id]
    terminal_statuses = {"COMPLETE", "SKIPPED", "PENDING_BATCH"}
    if task.get("status") in terminal_statuses:
        state = transitions.record_timing(state, task_id, "completed", _utc_now_iso())

    # Record cost/usage in ledger (immutable chain)
    state = _ledger.record(state, task_id, role, usage)

    # Reset schema_violations counter on successful submission
    active2 = statefile.active(state)
    active2["tasks"][task_id]["schema_violations"] = 0

    # Emit task_progress event
    orch_dir = state.get("orchestrator_dir", os.path.dirname(args.state))
    agentlens_run_id = state.get("agentlens_run_id")
    _events.emit(
        orch_dir,
        "kws-cme.task_progress",
        {
            "task_id": task_id,
            "role": role,
            "task_status": task.get("status"),
            "task_phase": task.get("phase"),
        },
        agentlens_run_id,
    )

    # Persist updated state
    statefile.write_state(args.state, state)

    # Return accepted with next_hint
    next_action = transitions.decide(state)
    return {
        "accepted": True,
        "next_hint": next_action.get("action"),
    }


def handle_check_stop(args):
    """Check stop condition.

    Exit 2 (+reason) if all tasks terminal, ZERO PENDING_BATCH, AND finalize
    not done. If any PENDING_BATCH tasks linger, exit 0 (batch drain still due;
    finalize is NOT pending — mirrors decide()). Exit 0 otherwise.

    NOTE: We use a "halt" key in the returned dict to trigger main()'s exit 2
    path. This does NOT signal an error — it signals "stop requested".
    T14 adds the quality gate here.
    """
    state = statefile.read_state(args.state)
    active = statefile.active(state)

    # Already finalized
    if state.get("status") == "FINALIZED":
        return {"check_stop": "already_finalized", "stop": False}

    # Check if all tasks terminal
    tasks = active.get("tasks", {})
    terminal_statuses = {"COMPLETE", "SKIPPED", "PENDING_BATCH"}
    all_terminal = bool(tasks) and all(
        t.get("status") in terminal_statuses for t in tasks.values()
    )

    # Mirror decide() exactly: finalize is only "pending" when there are ZERO
    # PENDING_BATCH tasks. If any linger, decide() returns a batch-verify
    # dispatch (work remains) — check-stop must NOT signal finalize, or the Stop
    # hook finalizes with an outstanding batch drain and fails red opaquely (T14b).
    pending_batch = any(
        t.get("status") == "PENDING_BATCH" for t in tasks.values()
    )

    if all_terminal and pending_batch:
        # Batch drain still due → do not stop, do not signal finalize.
        return {"check_stop": "batch_drain_pending", "stop": False}

    if all_terminal:
        # All terminal, zero PENDING_BATCH, finalize not done → signal stop.
        # Use "halt" key to trigger exit(2) in main().
        return {
            "halt": "all_tasks_terminal_finalize_pending",
            "reason": "All tasks have reached terminal status. Finalize step required.",
        }

    return {"check_stop": "not_ready", "stop": False}


def handle_finalize(args):
    """Finalize execution.

    Order (strict):
    1. Load state.
    2. drift.check → REFUSE with error if blocking non-empty.
    3. Method audit validation (checklist item, not hard-refuse).
    4. Stamp timestamps.completed_at (set-if-absent).
    5. Build completion_audit + run_quality into state.
    6. Set state.status = "FINALIZED".
    7. events.emit("kws-cme.phase_2_complete", ...).
    8. Best-effort run-close (no hard fail on close errors).
    9. Save state.
    """
    state = statefile.read_state(args.state)
    orch_dir = state.get("orchestrator_dir", os.path.dirname(args.state))

    # ── Step 2: drift.check — REFUSE if blocking ──────────────────────────────
    drift_result = _drift.check(state, orch_dir)
    blocking = drift_result.get("blocking", [])
    if blocking:
        return {
            "error": "finalize_refused_blocking_drift",
            "blocking_drift": blocking,
            "reason": (
                f"finalize refused: {len(blocking)} blocking drift item(s) detected. "
                "Resolve drift before finalizing: "
                + "; ".join(item.get("kind", "?") for item in blocking[:3])
            ),
        }

    # ── Step 3: Method audit (absorb validate_method_audit check logic) ───────
    # Build a checklist; non-blocking (no hard refuse here — executor debt only)
    method_audit_warnings: list[str] = []
    active = statefile.active(state)
    tasks = active.get("tasks") or {}
    for task_id, task in tasks.items():
        if not isinstance(task, dict):
            continue
        if task.get("status") != "COMPLETE":
            continue
        audit = task.get("method_audit") or {}
        # Check required methods (docs-only vs executable)
        files_test = task.get("files_test")
        files = task.get("files", [])
        is_docs_only = (
            files_test == []
            or (files_test is None and files and all(str(f).endswith(".md") for f in files))
        )
        if is_docs_only:
            required = {"verification-before-completion"}
        else:
            required = {"test-driven-development", "verification-before-completion", "code-review-pass"}
        applied = {e.get("skill") for e in (audit.get("applied") or []) if isinstance(e, dict)}
        waived = {e.get("skill") for e in (audit.get("waived") or []) if isinstance(e, dict)}
        missing = sorted(required - applied - waived)
        if missing:
            method_audit_warnings.append(
                f"{task_id}: method_audit missing {missing}"
            )

    # ── Step 4: Stamp completed_at (set-if-absent) ────────────────────────────
    now = _utc_now_iso()
    timestamps = state.setdefault("timestamps", {})
    if not timestamps.get("completed_at"):
        timestamps["completed_at"] = now

    # ── Step 5: Build run_quality + completion_audit ──────────────────────────
    run_quality = _quality.build_run_quality(state, orch_dir)
    state["run_quality"] = run_quality
    completion_audit = _quality.build_completion_audit(state)
    state["completion_audit"] = completion_audit

    # ── Step 6: Set status = FINALIZED ────────────────────────────────────────
    state["status"] = "FINALIZED"

    # ── Step 7: Emit phase_2_complete event ───────────────────────────────────
    agentlens_run_id = state.get("agentlens_run_id")
    _events.emit(
        orch_dir,
        "kws-cme.phase_2_complete",
        {
            "grade": run_quality.get("grade"),
            "completion_passed": completion_audit.get("passed"),
            "method_audit_warnings": method_audit_warnings,
        },
        agentlens_run_id,
    )

    # ── Step 8: Best-effort run-close (no hard fail) ──────────────────────────
    # (placeholder for any close hooks; currently no-op)

    # ── Step 9: Save state ────────────────────────────────────────────────────
    statefile.write_state(args.state, state)

    return {
        "status": "finalized",
        "grade": run_quality.get("grade"),
        "completion_passed": completion_audit.get("passed"),
        "method_audit_warnings": method_audit_warnings,
    }


def handle_inspect(args):
    """Inspect state — read-only: print run_quality + normalize summary; NO state mutation."""
    state = statefile.read_state(args.state)
    orch_dir = state.get("orchestrator_dir", os.path.dirname(args.state))

    # Get run_quality from state (if finalized) or compute on-the-fly
    run_quality = state.get("run_quality")
    if not isinstance(run_quality, dict):
        run_quality = _quality.build_run_quality(state, orch_dir)

    # Compute normalize summary (read-only, no mutation)
    normalize_summary = _quality.normalize_run(state)

    return {
        "run_quality": run_quality,
        "normalize": normalize_summary,
        "grade": run_quality.get("grade"),
        "completion_passed": state.get("completion_audit", {}).get("passed"),
    }


# ── CLI wiring ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="CME v3.0 Deterministic Kernel")
    subparsers = parser.add_subparsers(dest="command", help="Subcommand")

    # init: no --state required
    parser_init = subparsers.add_parser("init", help="Initialize kernel")
    parser_init.add_argument("--args", default="", help="CME args string (plan=... spec=...)")
    parser_init.add_argument("--dry-run", action="store_true",
                             help="Plan only; no filesystem changes")
    parser_init.add_argument("--repo-root", default=None,
                             help="Source repo root (defaults to cwd)")

    # next: requires --state
    parser_next = subparsers.add_parser("next", help="Next transition")
    parser_next.add_argument("--state", required=True, help="State file path")

    # submit: requires --state, --task, --role, --result
    parser_submit = subparsers.add_parser("submit", help="Submit result")
    parser_submit.add_argument("--state", required=True, help="State file path")
    parser_submit.add_argument("--task", required=True, help="Task ID (e.g. task_1)")
    parser_submit.add_argument("--role", required=True, help="Role (implementer/reviewer/verifier)")
    parser_submit.add_argument("--result", required=True, help="Path to result JSON file")

    # check-stop: requires --state
    parser_check_stop = subparsers.add_parser("check-stop", help="Check stop condition")
    parser_check_stop.add_argument("--state", required=True, help="State file path")

    # finalize: requires --state
    parser_finalize = subparsers.add_parser("finalize", help="Finalize execution")
    parser_finalize.add_argument("--state", required=True, help="State file path")

    # inspect: requires --state
    parser_inspect = subparsers.add_parser("inspect", help="Inspect state")
    parser_inspect.add_argument("--state", required=True, help="State file path")

    args = parser.parse_args()

    handlers = {
        "init": handle_init,
        "next": handle_next,
        "submit": handle_submit,
        "check-stop": handle_check_stop,
        "finalize": handle_finalize,
        "inspect": handle_inspect,
    }

    if args.command not in handlers:
        result = {"error": "unknown_command"}
        print(json.dumps(result, ensure_ascii=False))
        sys.exit(3)

    result = handlers[args.command](args)
    print(json.dumps(result, ensure_ascii=False, indent=2))

    # Exit with code 3 if result contains an error key
    if "error" in result:
        sys.exit(3)
    # Exit code 2 for halt (check-stop all-terminal, dirty_worktree, etc.)
    if "halt" in result:
        sys.exit(2)


if __name__ == "__main__":
    main()
