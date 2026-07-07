"""transitions.py — Deterministic transition rule engine (CME v3.0 T6).

This module codifies the guardrails that previously lived as prose in SKILL.md
into executable, deterministic Python. It is the heart of the CME v3.0 kernel.

Public API
----------
decide(state: dict) -> dict
    Inspect current state; return the next action dict.  Never mutates state.

apply_result(state: dict, task_id: str, role: str, payload: dict) -> dict
    Fold a validated sub-agent result into a NEW state (input state is never
    mutated — treat as immutable via deep-copy).

record_timing(state: dict, task_id: str, event: str, now_iso: str) -> dict
    Stamp a timing event on the task.  Returns a new state (immutable).

Rule sources
------------
Every rule below cites its authoritative document line(s):
  SKILL.md         — SKILL.md Guardrails table
  CYCLE            — references/phases/phase-1-task-cycle.md
  ESCALATION       — references/phases/phase-1-escalation.md

Conflict note (ADR pending — D001)
-----------------------------------
SPEC_FAULT >3 behaviour: the task brief (line 12) specifies escalate_to_user;
phase-1-task-cycle.md line 203 specifies SKIPPED + continue.  These are
semantically opposite.  This implementation follows the brief (escalate_to_user)
because (a) it is the explicit contract for the decide() output enum and (b) it
matches the principle that the kernel's job is to stop and surface what the
orchestrator's prose would silently skip.  The conflict must be resolved in a
formal ADR before v3.0 ships.
"""

from __future__ import annotations

import copy
from typing import Any

import statefile


# ── Fixed constants (SKILL.md: "Quality scoring thresholds are not user-
#    configurable", Guardrails row 'Quality scoring thresholds') ─────────────

SPEC_PASS = 0.85       # CYCLE line 151-156 tier table
QUALITY_PASS = 0.75    # CYCLE line 151-156 tier table
SPEC_WARN = 0.70       # CYCLE line 151-156 tier table
QUALITY_WARN = 0.60    # CYCLE line 151-156 tier table

REVIEW_RETRY_BUDGET = 3      # SKILL.md "Max 3 review retries per task"
VERIFIER_RETRY_BUDGET = 3    # SKILL.md (implied by CYCLE lines 281-296)
ESCALATION_BUDGET = 3        # SKILL.md "Max 3 escalations per task"; ESCALATION line 41
SPEC_FAULT_BUDGET = 3        # CYCLE line 203 spec-edit branch

QUALITY_TREND_MAX = 10       # SKILL.md "`quality_trend` is rolling, max 10"

# Compaction step order (task brief line 14: "batch verifier → docs → anchor")
COMPACT_STEPS = ["batch_verifier", "docs_updater", "anchor"]


# ── helpers ──────────────────────────────────────────────────────────────────

def _deep_copy(state: dict) -> dict:
    return copy.deepcopy(state)


def _active(state: dict) -> dict:
    """Return the active plan sub-tree (via statefile.active)."""
    return statefile.active(state)


def _compute_review_tier(spec_score: float, quality_score: float) -> str:
    """Compute reviewer tier from raw scores.

    Tier is computed by the KERNEL from scores; the LLM-reported status field
    is advisory only.  CYCLE lines 151-156.
    """
    if spec_score >= SPEC_PASS and quality_score >= QUALITY_PASS:
        return "PASS"
    if spec_score >= SPEC_WARN and quality_score >= QUALITY_WARN:
        return "WARN"
    return "FAIL"


def _terminal_statuses() -> set[str]:
    return {"COMPLETE", "SKIPPED", "PENDING_BATCH"}


def _all_tasks_terminal(active: dict) -> bool:
    """Return True when every declared task is in a terminal status."""
    tasks = active.get("tasks", {})
    if not tasks:
        return False
    return all(t.get("status") in _terminal_statuses() for t in tasks.values())


def _next_dispatch_task(active: dict) -> tuple[str | None, dict | None]:
    """Return (task_id, task_dict) of the first task that needs work, else None."""
    execution_plan = active.get("execution_plan", [])
    tasks = active.get("tasks", {})
    for group in execution_plan:
        for task_id in group:
            task = tasks.get(task_id, {})
            status = task.get("status", "IN_PROGRESS")
            if status in _terminal_statuses():
                continue
            return task_id, task
    return None, None


def _compaction_due(active: dict) -> bool:
    """Return True when the most-recently-completed task is a compaction point
    and we have not yet run compaction for it.

    CYCLE line 477: "if this task is a compaction point, go to Phase Transition".
    Guard: compare last_completed_task vs last_compaction_after_task.
    """
    compaction_points = active.get("compaction_points", [])
    if not compaction_points:
        return False
    last_completed = active.get("last_completed_task")
    last_compacted = active.get("last_compaction_after_task")
    if last_completed is None:
        return False
    if last_completed not in compaction_points:
        return False
    # Already compacted at this point
    if last_compacted == last_completed:
        return False
    return True


def _role_for_phase(phase: str) -> str:
    """Map task phase to the sub-agent role that should be dispatched next."""
    mapping = {
        "implement": "implementer",
        "review": "reviewer",
        "verify": "verifier",
    }
    return mapping.get(phase, "implementer")


def _attempt_number(task: dict) -> int:
    """Return the 1-based attempt number for the next dispatch of this task."""
    # Attempts = sum of all retries already consumed + 1
    review_retries = task.get("review_retries", 0)
    verifier_retries = task.get("verifier_retries", 0)
    escalations = task.get("escalations", 0)
    return review_retries + verifier_retries + escalations + 1


# ── public API ───────────────────────────────────────────────────────────────

def decide(state: dict) -> dict:
    """Return the next action dict from current state alone.

    Action shapes:
      {"action": "dispatch", "role": str, "task_id": str, "attempt": int}
      {"action": "run_command", "purpose": "baseline"|"acceptance", "command": str}
      {"action": "compact", "steps": list[str]}
      {"action": "escalate_to_user", "reason": str, "questions": list}
      {"action": "finalize"}
      {"action": "halt", "reason": str}
      {"action": "done"}

    Shape contract (T11 gate.partition_waves):
      state["execution_plan"] MUST be list[list[str]] — e.g. [["task_1"],["task_2","task_3"]].
      This is the EXACT shape gate.partition_waves() produces (v3.0 T11).
      _next_dispatch_task iterates: for group in execution_plan: for task_id in group.
      A shape mismatch (e.g. list[dict]) silently breaks task dispatch.
    """
    active = _active(state)

    # 1. Pending escalation to user takes highest priority.
    if state.get("pending_escalation"):
        pe = state["pending_escalation"]
        return {
            "action": "escalate_to_user",
            "reason": pe.get("reason", ""),
            "questions": pe.get("questions", []),
        }

    # 2. Compaction point: if last completed task is a compaction point and we
    #    haven't compacted it yet (CYCLE line 477).
    if _compaction_due(active):
        return {
            "action": "compact",
            "steps": list(COMPACT_STEPS),
        }

    # 3. All tasks terminal → finalize (SKILL.md: Phase 2 entry).
    if _all_tasks_terminal(active):
        return {"action": "finalize"}

    # 4. Find the next task needing work.
    task_id, task = _next_dispatch_task(active)
    if task_id is None:
        # No dispatchable task found but not all terminal — shouldn't happen.
        return {"action": "halt", "reason": "no_dispatchable_task"}

    # 5. Check for pending git reset (verifier FAIL requires reset before re-dispatch).
    if task.get("reset_pending"):
        sha = state.get("current_pre_task_sha", "")
        return {
            "action": "run_command",
            "purpose": "reset",
            "command": f"git reset --hard {sha}",
            "task_id": task_id,
        }

    phase = task.get("phase", "implement")
    role = _role_for_phase(phase)
    attempt = _attempt_number(task)

    return {
        "action": "dispatch",
        "role": role,
        "task_id": task_id,
        "attempt": attempt,
    }


def apply_result(state: dict, task_id: str, role: str, payload: dict) -> dict:
    """Return NEW state with the sub-agent result folded in.

    The input *state* is never mutated.
    """
    s = _deep_copy(state)
    active = _active(s)
    task = active["tasks"][task_id]

    if role == "implementer":
        _apply_implementer(s, active, task_id, task, payload)
    elif role == "reviewer":
        _apply_reviewer(s, active, task_id, task, payload)
    elif role == "verifier":
        _apply_verifier(s, active, task_id, task, payload)

    return s


def record_timing(state: dict, task_id: str, event: str, now_iso: str) -> dict:
    """Stamp *event* ('started' or 'completed') on *task_id*.timing in new state.

    CYCLE lines 40-48: timing must be written atomically; this function is the
    kernel-level equivalent of phase_boundary.py task-start / task-complete's
    timing stamp so that prose can never "forget" to call it (the kernel.py
    dispatch loop calls this automatically — TASK BRIEF requirement).

    Returns a new state dict (input is never mutated).
    """
    s = _deep_copy(state)
    active = _active(s)
    task = active["tasks"][task_id]
    timing = task.setdefault("timing", {})
    timing[event] = now_iso
    return s


# ── role-specific apply helpers ───────────────────────────────────────────────

def _apply_implementer(
    s: dict, active: dict, task_id: str, task: dict, payload: dict
) -> None:
    """Apply an implementer result.

    Rules:
    - DONE → task phase: "review"  (CYCLE Step 1 "Result: DONE")
    - ESCALATE → escalations +1; >3 → SKIPPED  (ESCALATION lines 41-49)
    """
    status = payload.get("status")
    if status == "DONE":
        task["phase"] = "review"
    elif status == "ESCALATE":
        task["escalations"] = task.get("escalations", 0) + 1
        # ESCALATION line 41: "If current_escalation_count > 3: halt that task"
        if task["escalations"] > ESCALATION_BUDGET:
            task["status"] = "SKIPPED"
            task["skip_reason"] = "escalation_exhausted"


def _apply_reviewer(
    s: dict, active: dict, task_id: str, task: dict, payload: dict
) -> None:
    """Apply a reviewer result.

    Rules (CYCLE lines 151-237, SKILL.md Guardrails):
    - Compute tier from spec_score/quality_score (kernel decides — NOT the LLM).
    - SPEC_FAULT (spec_contradicts|unclear): increment spec_clarifications;
        >3 → escalate_to_user (brief line 12; conflict with CYCLE line 203 noted
        in module docstring as pending ADR D001).
    - PASS: LOW → PENDING_BATCH; MID/HIGH → phase 'verify'.
    - WARN: same routing as PASS; additionally record warnings; no retry burned.
    - FAIL (implementer_omitted|none spec_fault): review_retries +1;
        >3 → SKIPPED + verification_gaps.
    """
    spec_score = float(payload.get("spec_score", 0.0))
    quality_score = float(payload.get("quality_score", 0.0))
    spec_fault = payload.get("spec_fault")  # "spec_contradicts"|"unclear"|None

    # CYCLE lines 196-199: spec_fault determines branch first.
    # "spec_contradicts" or "unclear" → spec-edit branch (non-burning).
    if spec_fault in ("spec_contradicts", "unclear"):
        # CYCLE line 203: "Increment task.spec_clarifications (NOT review_retries)"
        task["spec_clarifications"] = task.get("spec_clarifications", 0) + 1
        if task["spec_clarifications"] > SPEC_FAULT_BUDGET:
            # Brief line 12: escalate_to_user (see ADR D001 note in module docstring)
            s["pending_escalation"] = {
                "reason": f"spec_clarifications exceeded budget for {task_id}",
                "questions": [
                    f"Task {task_id} hit spec_clarification limit ({SPEC_FAULT_BUDGET}). "
                    "Please clarify the spec contradiction/ambiguity before continuing."
                ],
                "task_id": task_id,
            }
            task["status"] = "SKIPPED"
            task["skip_reason"] = "spec_clarifications_exhausted"
        return

    # Kernel-computed tier (deterministic; CYCLE lines 151-156)
    tier = _compute_review_tier(spec_score, quality_score)
    task["spec_score"] = spec_score
    task["quality_score"] = quality_score
    task["review_tier"] = tier

    risk = active.get("risk_levels", {}).get(task_id, "mid").lower()

    if tier == "PASS":
        _reviewer_pass_or_warn_route(active, task_id, task, risk)

    elif tier == "WARN":
        # SKILL.md "WARN tier does not retry"; CYCLE lines 172-184
        # Record warnings; no retry burned; route same as PASS.
        issues = payload.get("issues", [])
        # Store under task_summaries for this task
        active.setdefault("task_summaries", {}).setdefault(task_id, {})
        active["task_summaries"][task_id]["warnings"] = [
            i.get("description", str(i)) for i in issues
        ]
        _reviewer_pass_or_warn_route(active, task_id, task, risk)

    else:  # FAIL (non-spec-fault)
        # CYCLE lines 219-237 "Standard retry branch"
        task["review_retries"] = task.get("review_retries", 0) + 1
        if task["review_retries"] > REVIEW_RETRY_BUDGET:
            # CYCLE line 231-236: SKIP + continue
            task["status"] = "SKIPPED"
            task["skip_reason"] = "review_retries_exhausted"
            s.setdefault("verification_gaps", []).append({
                "task": task_id,
                "kind": "review",
                "attempts": task["review_retries"],
            })


def _reviewer_pass_or_warn_route(
    active: dict, task_id: str, task: dict, risk: str
) -> None:
    """Route a PASS or WARN reviewer result to the next phase.

    CYCLE line 240 (Step 3): LOW → PENDING_BATCH; MID/HIGH → phase 'verify'.
    SKILL.md "LOW tasks must reach batch verification".
    """
    if risk == "low":
        # LOW tasks skip per-task Verifier; go to batch verification
        task["status"] = "PENDING_BATCH"
        active.setdefault("low_tasks_pending_verification", [])
        if task_id not in active["low_tasks_pending_verification"]:
            active["low_tasks_pending_verification"].append(task_id)
    else:
        # MID or HIGH → proceed to per-task Verifier
        task["phase"] = "verify"


def _apply_verifier(
    s: dict, active: dict, task_id: str, task: dict, payload: dict
) -> None:
    """Apply a verifier result.

    Rules (CYCLE lines 279-296):
    - PASS → COMPLETE + last_completed_task + quality_trend (rolling 10).
    - FAIL → verifier_retries +1; set reset_pending.
        >3 → reset_pending + SKIPPED + verification_gaps.
    """
    status = payload.get("status")

    if status == "PASS":
        task["status"] = "COMPLETE"
        # Clear any pending reset
        task.pop("reset_pending", None)

        # Advance last_completed_task (CYCLE Step 4 "Latest pointers")
        active["last_completed_task"] = task_id

        # Append quality_score to rolling quality_trend (SKILL.md rolling 10).
        # The score was written by the reviewer step into the task dict.
        quality_score = task.get("quality_score")
        if quality_score is not None:
            trend = active.setdefault("quality_trend", [])
            trend.append(quality_score)
            if len(trend) > QUALITY_TREND_MAX:
                active["quality_trend"] = trend[-QUALITY_TREND_MAX:]

    else:  # FAIL (or unknown)
        # CYCLE line 281: "Increment verifier_retries"
        task["verifier_retries"] = task.get("verifier_retries", 0) + 1

        # CYCLE line 282-283: "Reset to pre-task state" — record directive
        # so kernel.py (Task 9) can honour it.
        task["reset_pending"] = True

        if task["verifier_retries"] > VERIFIER_RETRY_BUDGET:
            # CYCLE lines 291-296: SKIP + continue
            task["status"] = "SKIPPED"
            task["skip_reason"] = "verifier_retries_exhausted"
            s.setdefault("verification_gaps", []).append({
                "task": task_id,
                "kind": "verify",
                "attempts": task["verifier_retries"],
            })
