"""drift.py — Drift detection and safe repair (CME v3.0 T13).

Ported and adapted from:
  - skills/kws-codex-plan-executor/scripts/reconcile_state.py
  - skills/kws-codex-plan-executor/scripts/repair_runs.py

In v3 the kernel is the single state writer, so most drift cannot occur on the
normal kernel path. This module DEFENDS migrated/legacy runs and detects
inconsistencies that can sneak in when state is imported from CPE or edited
manually.

Drift detection vocabulary
--------------------------
Blocking (un-waivable):
  timing_inverted              — task timing.completed < timing.started.
                                 Time cannot run backwards; this is always a
                                 data-corruption indicator. Un-waivable because
                                 any repair would silently destroy evidence of
                                 when the task actually ran.
  residual_pending_batch       — run status COMPLETE but a task is still
                                 PENDING_BATCH (batch verifier never drained).
  zero_dispatches_with_completed_tasks — cost_ledger.totals.dispatches==0 but
                                 at least one COMPLETE task exists. The kernel
                                 always increments dispatches before marking
                                 complete; zero = state was written outside the
                                 kernel path (import / manual edit).
  worktree_missing             — state.worktree path is set, the run has started
                                 (a task past SETUP), but os.path.isdir is False.
                                 A lost worktree means the run cannot continue and
                                 cannot be auto-repaired → blocking.

Repairable (safe / recorded, no data destroyed):
  missing_timing               — terminal task (COMPLETE/SKIPPED) whose
                                 timing is null or missing started/completed.
                                 Cannot occur on the normal kernel path (T6
                                 record_timing stamps before dispatch) but
                                 defends migrated legacy runs. Auto-fixable by
                                 stamping synthetic timestamps.
  complete_missing_result      — COMPLETE task with no result file matching
                                 *<task_id>*.json under <orch_dir>/results/.
                                 GUARDED: only evaluated when results/ exists as a
                                 directory. Classified repairable (integrity
                                 signal): repair_safe RECORDS it without mutating
                                 — a missing result file cannot be synthesized, so
                                 there is nothing to fabricate, but it is not
                                 severe enough to hard-block a run whose state
                                 otherwise says the task passed.

Dead CPE detectors (no v3 analog, not ported):
  missing-context-health-timestamp — CPE tracks context_health / timestamps.
                                     CME v3 has no context_health field.
  finished-with-open-carried-acceptance — CPE-specific lifecycle field.
  completed-task-missing-unit-manifest  — CPE-specific per-task manifest.
  context-basis-hash-mismatch           — CPE context snapshot hash check.

Public API
----------
check(state, orch_dir) -> {"blocking": [...], "repairable": [...]}
    Each item: {"kind": str, "detail": str}.

repair_safe(state, orch_dir) -> dict
    Deep-copy state; stamp missing timestamps on repairable items only.
    Never touches blocking items.
    Appends repair history to state["drift"]["records"].
    Returns updated state (input never mutated).

repair_stale_run(state_path, apply: bool = False) -> dict
    Dry-run by default (apply=False → NO file changes).
    apply=True → writes lifecycle=blocked_stale into the state file (atomic).
    Never deletes files.
"""

from __future__ import annotations

import copy
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ── helpers ───────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _terminal_task_statuses() -> frozenset[str]:
    """Task statuses that represent a terminal (finished) task.

    Vocabulary from transitions._terminal_statuses() + verifier PASS branch:
    COMPLETE is the primary terminal (verifier PASS).
    SKIPPED is also terminal (budget exhausted / escalation exhausted).
    PENDING_BATCH is terminal for the per-task cycle (awaits batch verifier),
    but a residual PENDING_BATCH after run finalization is itself a drift kind.
    """
    return frozenset({"COMPLETE", "SKIPPED", "PENDING_BATCH"})


def _item(kind: str, detail: str) -> dict:
    return {"kind": kind, "detail": detail}


def _active(state: dict) -> dict:
    """Return the active plan sub-tree (mirrors statefile.active)."""
    if "plan_chain" in state:
        return state["plan_chain"][state["active_plan"]]
    return state


# ── detectors ─────────────────────────────────────────────────────────────────

def _detect_timing_inverted(active: dict) -> list[dict]:
    """Detect tasks where completed < started (un-waivable data corruption)."""
    items: list[dict] = []
    tasks = active.get("tasks", {})
    if not isinstance(tasks, dict):
        return items
    for task_id, task in tasks.items():
        if not isinstance(task, dict):
            continue
        timing = task.get("timing")
        if not isinstance(timing, dict):
            continue
        started = timing.get("started")
        completed = timing.get("completed")
        if isinstance(started, str) and isinstance(completed, str):
            try:
                if completed < started:  # ISO-8601 lexicographic compare is valid
                    items.append(_item(
                        "timing_inverted",
                        f"{task_id}: timing.completed ({completed!r}) < "
                        f"timing.started ({started!r}) — data corruption indicator",
                    ))
            except Exception:
                pass
    return items


def _detect_missing_timing(active: dict) -> list[dict]:
    """Detect terminal tasks with null/missing timing (migrated-run defense)."""
    items: list[dict] = []
    tasks = active.get("tasks", {})
    if not isinstance(tasks, dict):
        return items
    terminal = _terminal_task_statuses()
    for task_id, task in tasks.items():
        if not isinstance(task, dict):
            continue
        status = task.get("status", "")
        if status not in terminal:
            continue
        timing = task.get("timing")
        if timing is None:
            items.append(_item(
                "missing_timing",
                f"{task_id}: status={status!r} but timing is null "
                "(can't occur on kernel path; likely migrated run)",
            ))
        elif isinstance(timing, dict):
            if not timing.get("started") and not timing.get("completed"):
                items.append(_item(
                    "missing_timing",
                    f"{task_id}: status={status!r} but timing.started and "
                    "timing.completed are both absent",
                ))
    return items


def _detect_residual_pending_batch(state: dict, active: dict) -> list[dict]:
    """Detect PENDING_BATCH tasks when the run is finalized (COMPLETE/DONE)."""
    run_status = state.get("status", "")
    if run_status not in ("COMPLETE", "DONE", "FINISHED"):
        return []
    items: list[dict] = []
    tasks = active.get("tasks", {})
    if not isinstance(tasks, dict):
        return items
    for task_id, task in tasks.items():
        if isinstance(task, dict) and task.get("status") == "PENDING_BATCH":
            items.append(_item(
                "residual_pending_batch",
                f"{task_id}: status=PENDING_BATCH after run finalization "
                "(batch verifier never drained)",
            ))
    return items


def _detect_worktree_missing(state: dict, active: dict) -> list[dict]:
    """Detect a lost execution worktree on a started run (blocking, un-repairable).

    Conditions (all must hold to avoid false positives):
    - state["worktree"] is a non-empty string, AND
    - the run has started (at least one task NOT in SETUP), AND
    - os.path.isdir(worktree) is False.

    A lost worktree means the run cannot continue and cannot be auto-repaired.
    """
    worktree = state.get("worktree")
    if not isinstance(worktree, str) or not worktree.strip():
        return []
    tasks = active.get("tasks", {})
    if not isinstance(tasks, dict):
        return []
    # Run has started iff at least one task is past SETUP.
    started = any(
        isinstance(t, dict) and t.get("status") not in (None, "SETUP", "PENDING")
        for t in tasks.values()
    )
    if not started:
        return []
    if os.path.isdir(worktree):
        return []
    return [_item(
        "worktree_missing",
        f"worktree {worktree!r} does not exist on disk but the run has started "
        "(run cannot continue; not auto-repairable)",
    )]


def _detect_complete_missing_result(state: dict, active: dict, orch_dir: str) -> list[dict]:
    """Detect COMPLETE tasks with no result file (integrity signal, repairable).

    GUARDED against false positives: only evaluated when
    <orch_dir>/results/ exists as a directory. A fresh/migrated run with no
    results dir must NOT flag every task.

    For each COMPLETE task, if no file matching *<task_id>*.json exists in
    <orch_dir>/results/, emit a drift item.
    """
    if not isinstance(orch_dir, str) or not orch_dir:
        return []
    results_dir = os.path.join(orch_dir, "results")
    if not os.path.isdir(results_dir):
        return []  # false-positive guard: no results dir → skip entirely

    try:
        result_files = os.listdir(results_dir)
    except OSError:
        return []

    items: list[dict] = []
    tasks = active.get("tasks", {})
    if not isinstance(tasks, dict):
        return items
    for task_id, task in tasks.items():
        if not isinstance(task, dict) or task.get("status") != "COMPLETE":
            continue
        has_result = any(
            task_id in fname and fname.endswith(".json")
            for fname in result_files
        )
        if not has_result:
            items.append(_item(
                "complete_missing_result",
                f"{task_id}: status=COMPLETE but no result file matching "
                f"*{task_id}*.json in {results_dir!r} (integrity gap)",
            ))
    return items


def _detect_zero_dispatches_with_completed_tasks(active: dict, state: dict) -> list[dict]:
    """Detect dispatches==0 when completed tasks exist (non-waivable)."""
    # Navigate cost_ledger from full state (not active sub-plan, since ledger is global)
    cost_ledger = state.get("cost_ledger")
    if not isinstance(cost_ledger, dict):
        return []
    totals = cost_ledger.get("totals")
    if not isinstance(totals, dict):
        return []
    dispatches = totals.get("dispatches", 0)
    if dispatches != 0:
        return []

    tasks = active.get("tasks", {})
    if not isinstance(tasks, dict):
        return []
    has_completed = any(
        isinstance(t, dict) and t.get("status") == "COMPLETE"
        for t in tasks.values()
    )
    if has_completed:
        return [_item(
            "zero_dispatches_with_completed_tasks",
            "cost_ledger.totals.dispatches==0 but COMPLETE tasks exist "
            "(kernel always increments dispatches; state written outside kernel path)",
        )]
    return []


# ── public API: check ─────────────────────────────────────────────────────────

def check(state: dict, orch_dir: str) -> dict[str, list[dict]]:
    """Detect drift in *state*.

    Returns::

        {
            "blocking":   [{"kind": str, "detail": str}, ...],
            "repairable": [{"kind": str, "detail": str}, ...],
        }

    *orch_dir* is used by the complete_missing_result detector (guarded on
    <orch_dir>/results/ existing) and reserved for future result-file checks.
    """
    active = _active(state)

    blocking: list[dict] = []
    repairable: list[dict] = []

    # ── blocking detectors ────────────────────────────────────────────────────
    blocking.extend(_detect_timing_inverted(active))
    blocking.extend(_detect_residual_pending_batch(state, active))
    blocking.extend(_detect_zero_dispatches_with_completed_tasks(active, state))
    blocking.extend(_detect_worktree_missing(state, active))

    # ── repairable detectors ──────────────────────────────────────────────────
    # missing_timing: exclude tasks already flagged blocking for the same task by
    # timing_inverted (timing present-but-wrong) or residual_pending_batch — a
    # task must never appear in both lists.
    inverted_task_ids = {
        item["detail"].split(":")[0]
        for item in blocking
        if item["kind"] == "timing_inverted"
    }
    pending_batch_task_ids = {
        item["detail"].split(":")[0]
        for item in blocking
        if item["kind"] == "residual_pending_batch"
    }
    excluded_task_ids = inverted_task_ids | pending_batch_task_ids
    for item in _detect_missing_timing(active):
        task_id = item["detail"].split(":")[0]
        if task_id not in excluded_task_ids:
            repairable.append(item)

    # complete_missing_result: integrity signal, repairable (see report/module
    # note). Guarded on <orch_dir>/results/ existing to avoid flagging every
    # task on a fresh/migrated run with no results dir.
    repairable.extend(_detect_complete_missing_result(state, active, orch_dir))

    return {"blocking": blocking, "repairable": repairable}


# ── public API: repair_safe ───────────────────────────────────────────────────

def repair_safe(state: dict, orch_dir: str) -> dict:
    """Repair only safe (repairable) drift items.

    Rules:
    - Deep-copy state first (input never mutated).
    - Call statefile.active() on the COPY.
    - For each repairable item, apply the safe repair.
    - NEVER touch blocking items.
    - Append repair history to state["drift"]["records"].
    - Return the updated state.

    Currently handled:
      missing_timing          → stamp timing.started = timing.completed = now_iso()
                                (conservative: identical timestamps flag the repair)
      complete_missing_result → RECORD only, no mutation. A missing result file
                                cannot be synthesized, so there is nothing to
                                fabricate; the record surfaces the integrity gap.
    """
    s = copy.deepcopy(state)
    active = _active(s)

    result = check(state, orch_dir)  # check ORIGINAL (pre-copy) for detection
    repairable_items = result["repairable"]

    if not repairable_items:
        return s

    now = _now_iso()
    records: list[dict] = []

    # Index tasks for fast access
    tasks = active.get("tasks", {})

    for item in repairable_items:
        kind = item["kind"]
        if kind == "missing_timing":
            # Extract task_id from detail ("task_id: ...message...")
            task_id = item["detail"].split(":")[0].strip()
            task = tasks.get(task_id)
            if task is not None:
                # Stamp both started and completed to the same repair timestamp.
                # Using identical timestamps is a deliberate signal that this
                # is a synthetic stamp, not a real measurement.
                if task.get("timing") is None:
                    task["timing"] = {}
                timing = task["timing"]
                if not isinstance(timing, dict):
                    task["timing"] = {}
                    timing = task["timing"]
                if not timing.get("started"):
                    timing["started"] = now
                if not timing.get("completed"):
                    timing["completed"] = now
                records.append({
                    "kind": kind,
                    "detail": item["detail"],
                    "repaired_at": now,
                    "repair": f"stamped {task_id}.timing.started and .completed = {now!r}",
                })
        elif kind == "complete_missing_result":
            # Integrity signal — RECORD only, never mutate state. There is no
            # safe synthetic fix for a missing result file.
            records.append({
                "kind": kind,
                "detail": item["detail"],
                "recorded_at": now,
                "repair": "recorded only (missing result file cannot be synthesized)",
            })

    # Write repair history into drift section
    drift_section = s.setdefault("drift", {})
    existing_records = drift_section.get("records", [])
    if not isinstance(existing_records, list):
        existing_records = []
    drift_section["records"] = existing_records + records
    drift_section["last_repair_at"] = now

    return s


# ── public API: repair_stale_run ──────────────────────────────────────────────

def repair_stale_run(
    state_path: "str | os.PathLike[str]",
    apply: bool = False,
) -> dict[str, Any]:
    """Plan or apply a conservative stale-run repair.

    Parameters
    ----------
    state_path : path to the run's state.json
    apply      : False (default) → dry-run, NO changes written;
                 True  → mark lifecycle=blocked_stale (atomic write)

    Returns a report dict with keys:
        dry_run      : bool
        state_path   : str
        action       : "mark_blocked_stale" | "no_action_needed" | str
        applied      : bool
        before       : dict | None
        after        : dict | None

    NEVER deletes files.
    """
    path = Path(state_path)

    try:
        raw = path.read_text(encoding="utf-8")
        state = json.loads(raw)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        return {
            "dry_run": not apply,
            "state_path": str(path),
            "action": "error",
            "applied": False,
            "error": str(exc),
            "before": None,
            "after": None,
        }

    # Determine if stale repair is warranted: run is non-terminal
    run_status = state.get("status", "")
    is_non_terminal = run_status not in ("COMPLETE", "DONE", "FINISHED", "FAILED", "BLOCKED")
    already_marked = state.get("lifecycle") == "blocked_stale"

    if not is_non_terminal or already_marked:
        return {
            "dry_run": not apply,
            "state_path": str(path),
            "action": "no_action_needed",
            "applied": False,
            "reason": (
                "already marked blocked_stale" if already_marked
                else f"run status {run_status!r} is already terminal"
            ),
            "before": {"lifecycle": state.get("lifecycle"), "status": run_status},
            "after": None,
        }

    report: dict[str, Any] = {
        "dry_run": not apply,
        "state_path": str(path),
        "action": "mark_blocked_stale",
        "before": {"lifecycle": state.get("lifecycle"), "status": run_status},
    }

    if not apply:
        report["applied"] = False
        report["after"] = None
        return report

    # Apply: deep-copy and patch
    patched = copy.deepcopy(state)
    patched["lifecycle"] = "blocked_stale"
    now = _now_iso()
    patched.setdefault("drift", {})["blocked_stale_at"] = now

    # Atomic write (mirrors statefile.write_state pattern)
    tmp_fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as handle:
            json.dump(patched, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(tmp_name, str(path))
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise

    report["applied"] = True
    report["after"] = {"lifecycle": patched.get("lifecycle"), "status": patched.get("status")}
    return report
