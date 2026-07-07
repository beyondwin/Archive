"""quality.py — Run quality assessment, completion audit, and normalization (CME v3.0 T14).

Ported and adapted from:
  - skills/kws-codex-plan-executor/scripts/run_quality_debt.py
  - skills/kws-codex-plan-executor/scripts/normalize_cpe_run.py

Absorbs check logic from:
  - scripts/finalize_run.py (finalize consistency checks)
  - scripts/validate_state_schema.py (schema validation items)
  - scripts/validate_method_audit.py (method audit checks)

Public API
----------
build_run_quality(state, orch_dir) -> dict
    Produce the run quality assessment.
    Keys: readiness, dispatch_consistency, context_quality, verification_quality,
          open_followups, grade.
    CRITICAL SEPARATION: product correctness (all tasks verified/complete) is SEPARATE
    from executor efficiency (packet fallbacks, schema-violation counts, recovery-unknown
    counts). A run can be product-green but executor-yellow. Executor debt alone must NOT
    fail an otherwise-correct product, and a clean executor must NOT hide an incorrect product.

build_completion_audit(state) -> dict
    Keys: passed, checklist, verification_evidence, residual_risk.
    If ANY residual_risk item has blocks_release=True, passed MUST be False.

normalize_run(state) -> dict
    Deterministic eval summary (COUNTS + class names only, NO raw content).
    Runs forbidden-pattern scan (sk-, /Users/, full-transcript markers).
    The normalize output itself must NOT contain home paths / secrets / full transcripts.
"""

from __future__ import annotations

import copy
from typing import Any


# ── constants ─────────────────────────────────────────────────────────────────

_TERMINAL_STATUSES = frozenset({"COMPLETE", "SKIPPED", "PENDING_BATCH"})
_VERIFIED_STATUSES = frozenset({"COMPLETE"})

# Forbidden-pattern markers (names must NOT themselves be forbidden patterns)
_FORBIDDEN_PATTERNS = [
    ("secret_key_prefix", "sk-"),
    ("absolute_home_path", "/Users/"),
    ("full_prompt_marker", "BEGIN FULL PROMPT"),
]


# ── helpers ───────────────────────────────────────────────────────────────────

def _active(state: dict) -> dict:
    """Return the active plan sub-tree."""
    if "plan_chain" in state:
        return state["plan_chain"][state["active_plan"]]
    return state


def _all_tasks(state: dict) -> dict[str, Any]:
    return _active(state).get("tasks") or {}


def _safe_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _count_int(value: Any, default: int = 0) -> int:
    return value if isinstance(value, int) else default


# ── forbidden-pattern scan ────────────────────────────────────────────────────

def _forbidden_pattern_scan(texts: list[str]) -> list[str]:
    """Scan a list of text strings for forbidden patterns.

    Returns a list of marker names (NOT the forbidden patterns themselves).
    Marker names are designed to NOT themselves be forbidden patterns.
    """
    joined = "\n".join(t for t in texts if isinstance(t, str))
    found: list[str] = []
    for marker, needle in _FORBIDDEN_PATTERNS:
        if needle in joined and marker not in found:
            found.append(marker)
    return found


def _extract_content_texts(state: dict) -> list[str]:
    """Extract content/text fields from state for forbidden-pattern scanning.

    IMPORTANT: Only scans content fields (task bodies, summaries, etc.).
    Does NOT scan infrastructure path fields (worktree, orchestrator_dir, etc.)
    to avoid false-positives on legitimate /Users/ paths in those fields.
    """
    texts: list[str] = []
    tasks = _all_tasks(state)
    for task in tasks.values():
        if not isinstance(task, dict):
            continue
        for field in ("body", "next_task_summary", "last_summary", "review_notes", "verifier_notes"):
            val = task.get(field)
            if isinstance(val, str):
                texts.append(val)

    # Context health summaries
    health = _safe_dict(state.get("context_health"))
    for item in _safe_list(health.get("hot_tail_summaries")):
        if isinstance(item, dict) and isinstance(item.get("summary"), str):
            texts.append(item["summary"])

    # Task summaries
    for v in _safe_dict(state.get("task_summaries")).values():
        if isinstance(v, str):
            texts.append(v)
        elif isinstance(v, dict) and isinstance(v.get("summary"), str):
            texts.append(v["summary"])

    return texts


# ── readiness section ─────────────────────────────────────────────────────────

def _build_readiness(state: dict) -> dict[str, Any]:
    """Assess run-readiness: timing, cost ledger, task completion."""
    tasks = _all_tasks(state)
    terminal_total = 0
    terminal_missing_timing = 0
    inverted_timing = 0
    pending_batch_count = 0

    for task in tasks.values():
        if not isinstance(task, dict):
            continue
        status = task.get("status", "")
        if status not in _TERMINAL_STATUSES:
            continue
        terminal_total += 1

        if status == "PENDING_BATCH":
            pending_batch_count += 1

        timing = _safe_dict(task.get("timing"))
        started = timing.get("started")
        completed = timing.get("completed")
        if not started or not completed:
            terminal_missing_timing += 1
        elif isinstance(started, str) and isinstance(completed, str) and completed < started:
            inverted_timing += 1

    # Cost ledger check
    cost_ledger = _safe_dict(state.get("cost_ledger"))
    totals = _safe_dict(cost_ledger.get("totals"))
    dispatches = _count_int(totals.get("dispatches"))
    completed_count = sum(
        1 for t in tasks.values()
        if isinstance(t, dict) and t.get("status") == "COMPLETE"
    )
    zero_dispatches_issue = (dispatches == 0 and completed_count > 0)

    # completed_at stamp
    timestamps = _safe_dict(state.get("timestamps"))
    has_completed_at = bool(timestamps.get("completed_at"))

    fixable_issue_count = 0
    if not has_completed_at and terminal_total > 0:
        fixable_issue_count += 1

    return {
        "terminal_task_count": terminal_total,
        "timing_missing_count": terminal_missing_timing,
        "timing_inverted_count": inverted_timing,
        "pending_batch_count": pending_batch_count,
        "zero_dispatches_with_completed_tasks": zero_dispatches_issue,
        "has_completed_at": has_completed_at,
        "fixable_issue_count": fixable_issue_count,
        "dispatches": dispatches,
    }


# ── dispatch consistency section ──────────────────────────────────────────────

def _build_dispatch_consistency(state: dict) -> dict[str, Any]:
    """Assess dispatch record consistency."""
    tasks = _all_tasks(state)
    schema_violation_total = 0
    recovery_unknown_count = 0

    for task in tasks.values():
        if not isinstance(task, dict):
            continue
        # Use cumulative counter (set by handle_submit)
        schema_violation_total += _count_int(task.get("total_schema_violations"))
        # Recovery items with unknown resolution
        for rec in _safe_list(task.get("recovery_events")):
            if isinstance(rec, dict) and rec.get("resolution") == "unknown":
                recovery_unknown_count += 1

    return {
        "total_schema_violations": schema_violation_total,
        "recovery_unknown_count": recovery_unknown_count,
    }


# ── context quality section ───────────────────────────────────────────────────

def _build_context_quality(state: dict) -> dict[str, Any]:
    """Assess context quality: spec fallbacks, compaction events."""
    tasks = _all_tasks(state)
    full_spec_fallback_count = sum(
        1 for t in tasks.values()
        if isinstance(t, dict) and t.get("fallback_spec_used") is True
    )

    compaction_points = _safe_list(state.get("compaction_points"))
    compaction_count = len(compaction_points)

    return {
        "full_spec_fallback_count": full_spec_fallback_count,
        "compaction_count": compaction_count,
    }


# ── verification quality section ──────────────────────────────────────────────

def _build_verification_quality(state: dict) -> dict[str, Any]:
    """Assess verification quality: how many tasks were fully verified."""
    tasks = _all_tasks(state)
    complete_count = 0
    skipped_count = 0
    pending_batch_count = 0
    verification_gap_count = 0

    for task in tasks.values():
        if not isinstance(task, dict):
            continue
        status = task.get("status", "")
        if status == "COMPLETE":
            complete_count += 1
        elif status == "SKIPPED":
            skipped_count += 1
            # A SKIPPED task that was not by-design (e.g. escalation exhausted)
            # is a verification gap
            if _count_int(task.get("escalations")) >= 4:
                verification_gap_count += 1
            else:
                verification_gap_count += 1  # all SKIPs are gaps
        elif status == "PENDING_BATCH":
            pending_batch_count += 1

    total_tasks = len(tasks)
    all_terminal = total_tasks > 0 and all(
        t.get("status") in _TERMINAL_STATUSES
        for t in tasks.values() if isinstance(t, dict)
    )

    return {
        "complete_count": complete_count,
        "skipped_count": skipped_count,
        "pending_batch_count": pending_batch_count,
        "verification_gap_count": verification_gap_count,
        "total_tasks": total_tasks,
        "all_tasks_terminal": all_terminal,
    }


# ── open followups ────────────────────────────────────────────────────────────

def _compute_open_followups(
    state: dict,
    readiness: dict,
    dispatch_consistency: dict,
    context_quality: dict,
    verification_quality: dict,
) -> list[str]:
    """Compute executor-efficiency followup items (does NOT include product failures)."""
    followups: list[str] = []

    # Spec fallbacks
    if context_quality.get("full_spec_fallback_count", 0) > 0:
        followups.append("full_spec_fallback_present")

    # Schema violations (executor debt)
    if dispatch_consistency.get("total_schema_violations", 0) > 0:
        followups.append("schema_violations_present")

    # Recovery unknowns
    if dispatch_consistency.get("recovery_unknown_count", 0) > 0:
        followups.append("recovery_unknown_present")

    # Missing timing
    if readiness.get("timing_missing_count", 0) > 0:
        followups.append("timing_data_missing")

    # Zero dispatches with completed tasks (integrity signal)
    if readiness.get("zero_dispatches_with_completed_tasks", False):
        followups.append("zero_dispatches_with_completed_tasks")

    return followups


# ── grade computation ─────────────────────────────────────────────────────────

def _compute_grade(
    state: dict,
    readiness: dict,
    verification_quality: dict,
    open_followups: list[str],
    completion_audit: dict | None = None,
) -> str:
    """Compute overall grade.

    CRITICAL SEPARATION:
    - Product correctness (all tasks complete/verified) → red if broken
    - Executor efficiency (followups) → yellow if non-empty
    - Both clean → green

    Product failures are checked FIRST and always override executor grade.

    completion_audit is consulted to enforce the invariant that a passing grade
    cannot mask an incorrect product (e.g. SKIPPED tasks with blocks_release=True
    will have passed=False, which MUST yield grade=red).
    """
    # Product correctness check via completion_audit (most authoritative)
    if completion_audit is not None:
        if completion_audit.get("passed") is False:
            return "red"

    # Product correctness check via task statuses
    tasks = _all_tasks(state)
    total_tasks = len(tasks)
    if total_tasks == 0:
        # Empty task set is a red flag
        return "red"

    all_terminal = all(
        t.get("status") in _TERMINAL_STATUSES
        for t in tasks.values() if isinstance(t, dict)
    )
    if not all_terminal:
        # Product broken: tasks not yet complete
        return "red"

    # Check timing_inverted (always red — data corruption)
    if readiness.get("timing_inverted_count", 0) > 0:
        return "red"

    # Executor efficiency followups → yellow (product is OK)
    if open_followups:
        return "yellow"

    return "green"


# ── public API: build_run_quality ─────────────────────────────────────────────

def build_run_quality(state: dict, orch_dir: str) -> dict:
    """Produce the run quality assessment.

    Returns:
        {
            "readiness": {...},
            "dispatch_consistency": {...},
            "context_quality": {"full_spec_fallback_count": int, ...},
            "verification_quality": {...},
            "open_followups": [str, ...],
            "grade": "green" | "yellow" | "red",
        }

    CRITICAL SEPARATION:
    - Product correctness (all tasks verified/complete) → determines red/not-red
    - Executor efficiency (fallbacks, violations, recovery) → determines yellow vs green
    A run can be product-green but executor-yellow; executor debt does NOT fail a
    correct product; a clean executor does NOT hide an incorrect product.
    """
    state = copy.deepcopy(state)

    # Build completion_audit FIRST so grade can consult product correctness.
    # This enforces the critical separation: completion_audit.passed=False (e.g.
    # SKIPPED task with blocks_release=True) must yield grade=red, not green.
    completion_audit = build_completion_audit(state)

    readiness = _build_readiness(state)
    dispatch_consistency = _build_dispatch_consistency(state)
    context_quality = _build_context_quality(state)
    verification_quality = _build_verification_quality(state)
    open_followups = _compute_open_followups(
        state, readiness, dispatch_consistency, context_quality, verification_quality
    )
    grade = _compute_grade(
        state, readiness, verification_quality, open_followups, completion_audit
    )

    return {
        "readiness": readiness,
        "dispatch_consistency": dispatch_consistency,
        "context_quality": context_quality,
        "verification_quality": verification_quality,
        "open_followups": open_followups,
        "grade": grade,
    }


# ── public API: build_completion_audit ────────────────────────────────────────

def build_completion_audit(state: dict) -> dict:
    """Produce the completion audit.

    Returns:
        {
            "passed": bool,
            "checklist": [...],
            "verification_evidence": [...],
            "residual_risk": [{"class": str, "summary": str, "blocks_release": bool}, ...],
        }

    INVARIANT: If ANY residual_risk item has blocks_release=True, passed MUST be False.
    """
    state = copy.deepcopy(state)
    tasks = _all_tasks(state)
    checklist: list[dict] = []
    verification_evidence: list[dict] = []
    residual_risk: list[dict] = []

    # ── Checklist: all tasks reached a terminal status ────────────────────────
    all_terminal = True
    for task_id, task in tasks.items():
        if not isinstance(task, dict):
            continue
        status = task.get("status", "")
        is_terminal = status in _TERMINAL_STATUSES
        if not is_terminal:
            all_terminal = False
        checklist.append({
            "item": f"{task_id}_terminal",
            "status": status,
            "passed": is_terminal,
        })

    # ── Checklist: all tasks have timing ─────────────────────────────────────
    for task_id, task in tasks.items():
        if not isinstance(task, dict):
            continue
        timing = _safe_dict(task.get("timing"))
        has_timing = bool(timing.get("started") and timing.get("completed"))
        checklist.append({
            "item": f"{task_id}_timing",
            "passed": has_timing,
        })

    # ── Verification evidence: COMPLETE tasks ─────────────────────────────────
    for task_id, task in tasks.items():
        if not isinstance(task, dict):
            continue
        if task.get("status") == "COMPLETE":
            evidence_item: dict = {
                "class": "task_complete",
                "task_id": task_id,
            }
            # Record phase that was reached
            if task.get("phase"):
                evidence_item["final_phase"] = task["phase"]
            verification_evidence.append(evidence_item)

    # ── Residual risk: SKIPPED tasks ─────────────────────────────────────────
    for task_id, task in tasks.items():
        if not isinstance(task, dict):
            continue
        status = task.get("status", "")
        if status == "SKIPPED":
            residual_risk.append({
                "class": "task_skipped",
                "summary": (
                    f"{task_id} was skipped (escalations="
                    f"{task.get('escalations', 0)})"
                ),
                "blocks_release": True,  # SKIPPED tasks block release
            })

    # ── Residual risk: PENDING_BATCH tasks (batch verification not drained) ─────
    # Defense-in-depth: a correctly-driven run (with T14b drain) will never reach
    # finalize with PENDING_BATCH tasks, but if it does they block release.
    # Symmetric with SKIPPED: blocks_release=true → passed=false → grade=red.
    for task_id, task in tasks.items():
        if not isinstance(task, dict):
            continue
        if task.get("status") == "PENDING_BATCH":
            residual_risk.append({
                "class": "pending_batch_unverified",
                "summary": f"{task_id}: batch verification not drained",
                "blocks_release": True,
            })

    # ── Residual risk: incomplete tasks (not terminal) ────────────────────────
    for task_id, task in tasks.items():
        if not isinstance(task, dict):
            continue
        status = task.get("status", "")
        if status not in _TERMINAL_STATUSES:
            residual_risk.append({
                "class": "task_incomplete",
                "summary": f"{task_id}: status={status!r} (not terminal)",
                "blocks_release": True,
            })

    # ── Residual risk: timing inverted (data corruption indicator) ────────────
    for task_id, task in tasks.items():
        if not isinstance(task, dict):
            continue
        timing = _safe_dict(task.get("timing"))
        started = timing.get("started")
        completed = timing.get("completed")
        if isinstance(started, str) and isinstance(completed, str) and completed < started:
            residual_risk.append({
                "class": "timing_data_corruption",
                "summary": (
                    f"{task_id}: timing.completed ({completed!r}) < "
                    f"timing.started ({started!r})"
                ),
                "blocks_release": False,  # Data corruption is serious but doesn't block release
                # (already covered by grade=red via readiness)
            })

    # ── INVARIANT: blocks_release → passed=False ──────────────────────────────
    any_blocking = any(
        isinstance(r, dict) and r.get("blocks_release") is True
        for r in residual_risk
    )
    passed = not any_blocking

    return {
        "passed": passed,
        "checklist": checklist,
        "verification_evidence": verification_evidence,
        "residual_risk": residual_risk,
    }


# ── public API: normalize_run ─────────────────────────────────────────────────

def normalize_run(state: dict) -> dict:
    """Produce a deterministic eval summary with forbidden-pattern scan.

    Returns COUNTS + class names only — NO raw content, NO home paths,
    NO secrets, NO full transcripts.

    Also runs forbidden-pattern scan on content fields and returns the
    scan result (marker names only, NOT the raw patterns themselves).
    """
    state = copy.deepcopy(state)
    tasks = _all_tasks(state)
    completion = _safe_dict(state.get("completion_audit"))
    quality = _safe_dict(state.get("run_quality"))
    cost_ledger = _safe_dict(state.get("cost_ledger"))
    totals = _safe_dict(cost_ledger.get("totals"))

    # Scan content fields (NOT infrastructure path fields)
    content_texts = _extract_content_texts(state)
    forbidden_found = _forbidden_pattern_scan(content_texts)

    # Compute counts
    complete_count = sum(
        1 for t in tasks.values()
        if isinstance(t, dict) and t.get("status") == "COMPLETE"
    )
    skipped_count = sum(
        1 for t in tasks.values()
        if isinstance(t, dict) and t.get("status") == "SKIPPED"
    )
    pending_batch_count = sum(
        1 for t in tasks.values()
        if isinstance(t, dict) and t.get("status") == "PENDING_BATCH"
    )
    full_spec_fallback_count = sum(
        1 for t in tasks.values()
        if isinstance(t, dict) and t.get("fallback_spec_used") is True
    )
    total_schema_violations = sum(
        _count_int(t.get("total_schema_violations"))
        for t in tasks.values()
        if isinstance(t, dict)
    )

    # Residual risk classes only (no summaries/raw content)
    residual_risk_classes = sorted({
        r["class"]
        for r in _safe_list(completion.get("residual_risk"))
        if isinstance(r, dict) and isinstance(r.get("class"), str)
    })

    # Verification evidence classes only
    verification_evidence_classes = sorted({
        e["class"]
        for e in _safe_list(completion.get("verification_evidence"))
        if isinstance(e, dict) and isinstance(e.get("class"), str)
    })

    return {
        "schema_version": "1",
        "run_id": state.get("run_id"),
        "task_count": len(tasks),
        "complete_count": complete_count,
        "skipped_count": skipped_count,
        "pending_batch_count": pending_batch_count,
        "full_spec_fallback_count": full_spec_fallback_count,
        "total_schema_violations": total_schema_violations,
        "completion_passed": completion.get("passed") is True,
        "run_quality_grade": quality.get("grade"),
        "open_followups": _safe_list(quality.get("open_followups")),
        "dispatches": _count_int(totals.get("dispatches")),
        "residual_risk_classes": residual_risk_classes,
        "verification_evidence_classes": verification_evidence_classes,
        "forbidden_patterns_found": forbidden_found,
    }
