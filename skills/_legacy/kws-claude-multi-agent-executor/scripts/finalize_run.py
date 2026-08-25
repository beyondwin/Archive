#!/usr/bin/env python3
# DEPRECATED (v3.0 T15 cutover): the CME v3 kernel owns finalization via
# scripts/kernel/kernel.py finalize (drift.check + quality.build_run_quality +
# completion_audit). The kernel orchestrator does NOT call this script. NOT deleted
# because it is still referenced by the v2 Stop-gate template/test
# (references/hooks/finalization-stop-gate.sh.template, test_finalization_stop_gate.py)
# and evals/check_skill_contract.py (a v2 contract eval). Retire with those v2 orphans (T16).
"""Finalization-consistency gate for a kws-claude-multi-agent-executor run.

Checks that a run that claims to be finished is actually finalized:
completed_at stamped, no LOW task left PENDING_BATCH, cost ledger populated,
per-task timing present. `--fix` performs only the one genuinely-safe write
(stamp completed_at); everything else is a loud report, never a silent mutation.

Exit 0: no unfixable FAIL (WARNs allowed).
Exit 1: at least one FAIL (after --fix, if used).
Exit 2: validator could not parse state.json.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from materialize_worktree_hooks import check_problems as _hook_problems
except Exception:  # noqa: BLE001 — fail-open if the helper is unavailable
    _hook_problems = None


def _active_trees(state: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    chain = state.get("plan_chain")
    if isinstance(chain, list):
        return [(f"plan_chain[{i}]", entry) for i, entry in enumerate(chain)]
    return [("state", state)]


def _parse_iso(value: Any) -> "datetime | None":
    """Tolerant ISO-8601 parse, normalized to naive UTC.

    Returns None on anything non-parseable so corrupt values fall through to the
    existing null/absence handling rather than crashing. Normalizing to naive UTC
    lets an aware/naive pair (e.g. a 'Z' value vs. a bare one) still compare.
    """
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _worktree_hook_problems(state: dict[str, Any]) -> list[str] | None:
    """Inspect the worktree's .claude/settings.json for missing safety hooks.

    Returns a (possibly empty) problem list when the file is present and
    parseable, or None when the check cannot run — helper unavailable, no
    `worktree`, file absent/unparseable. None means *skip*, never *fail*: a
    replayed or cleaned-up worktree must not false-positive. A live run whose
    settings.json parses but lacks the Stop gate (the run-2 hand-write shape)
    returns a non-empty list and is caught.
    """
    if _hook_problems is None:
        return None
    worktree = state.get("worktree")
    if not worktree:
        return None
    path = Path(worktree) / ".claude" / "settings.json"
    if not path.is_file():
        return None
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(settings, dict):
        return None
    return _hook_problems(settings)


def _gap_counts(state: dict[str, Any]) -> tuple[int, int]:
    """Actual (verification_gaps, docs_gaps) counts aggregated across all trees."""
    vg = dg = 0
    for _scope, tree in _active_trees(state):
        vg += len(tree.get("verification_gaps") or [])
        dg += len(tree.get("docs_gaps") or [])
    return vg, dg


def evaluate(state: dict[str, Any], report_dir: "Path | None" = None) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []

    def add(level: str, scope: str, code: str, detail: str, fixable: bool = False) -> None:
        findings.append({"level": level, "scope": scope, "code": code,
                         "detail": detail, "fixable": fixable})

    # Run-level: completed_at.
    completed_at = (state.get("timestamps") or {}).get("completed_at")
    if not completed_at:
        add("FAIL", "state", "completed_at_null",
            "timestamps.completed_at is null/absent", fixable=True)

    # Run-level: cost ledger dispatches. v2.27: blocking unless explicitly waived.
    if not state.get("cost_tracking_waived"):
        dispatches = ((state.get("cost_ledger") or {}).get("totals") or {}).get("dispatches", 0)
        if not dispatches:
            add("FAIL", "state", "cost_dispatches_zero",
                "cost_ledger.totals.dispatches == 0 (accumulate_cost.py never ran); "
                "set cost_tracking_waived to opt out")

    # Per-tree task checks.
    terminal_total = 0
    terminal_null_started = 0
    for scope, tree in _active_trees(state):
        tasks = tree.get("tasks")
        tasks = tasks if isinstance(tasks, dict) else {}
        for task_id, task in tasks.items():
            status = task.get("status")
            if status not in ("COMPLETE", "SKIPPED"):
                add("FAIL", scope, "task_not_terminal",
                    f"{task_id}: status={status!r} (expected COMPLETE/SKIPPED)")
                continue
            if task.get("verifier") == "PENDING_BATCH":
                add("FAIL", scope, "verifier_pending_batch",
                    f"{task_id}: verifier still PENDING_BATCH (final LOW sweep never wrote back)")
            terminal_total += 1
            timing = task.get("timing") or {}
            if not timing.get("started"):
                terminal_null_started += 1
                add("WARN", scope, "timing_started_missing",
                    f"{task_id}: timing.started absent (per-task duration uncomputable)")
            # v2.28 (D003): physically-impossible ordering. UNCONDITIONAL — not
            # gated by timing_tracking_waived (that hatch governs *absence* of
            # timing; an inverted pair is *corruption*, e.g. a hand-typed KST
            # wall-clock stamped 'Z'). Non-parseable values return None and fall
            # through to the null/absence handling above without crashing.
            started = timing.get("started")
            completed = timing.get("completed")
            if started and completed:
                s, c = _parse_iso(started), _parse_iso(completed)
                if s is not None and c is not None and s > c:
                    add("FAIL", scope, "timing_inverted",
                        f"{task_id}: timing.started ({started}) > "
                        f"timing.completed ({completed}) — impossible ordering "
                        "(hand-typed / wrong-TZ timestamp)")

    # v2.27: systemic timing drift. Every terminal task missing timing.started is
    # an unambiguous skip of phase_boundary.py task-start, not a one-off. Blocking
    # unless explicitly waived. Partial misses stay per-task WARN above.
    if (terminal_total > 0 and terminal_null_started == terminal_total
            and not state.get("timing_tracking_waived")):
        add("FAIL", "state", "timing_tracking_absent",
            f"all {terminal_total} terminal tasks have null timing.started "
            "(phase_boundary.py task-start never ran); set timing_tracking_waived to opt out")

    # v2.28 (D003): telemetry coverage — WARN only (best-effort per v2.10/v2.17).
    reviewed = 0
    trend_len = 0
    for _, tree in _active_trees(state):
        trend_len += len(tree.get("quality_trend") or [])
        for task in (tree.get("tasks") or {}).values():
            if task.get("status") in ("COMPLETE", "SKIPPED") and (
                    task.get("review_tier") or task.get("review")):
                reviewed += 1
    if reviewed > 0 and trend_len < reviewed:
        add("WARN", "state", "quality_trend_sparse",
            f"quality_trend has {trend_len} entries for {reviewed} reviewed tasks")
    if not state.get("agentlens_orchestration_run"):
        add("WARN", "state", "agentlens_run_absent",
            "agentlens_orchestration_run is null — observability pipeline was dark")

    # v2.27 (D003): worktree safety hooks must be wired. Backstop for a run that
    # skipped Phase 0 Step 2.5 (so the Stop gate was never installed) yet still
    # reached the Phase 2 finalize call — the residual gap the --check preflight
    # alone could not close. Skips silently when settings.json can't be inspected
    # (replay / cleaned worktree) so it never false-positives off-host.
    if not state.get("hooks_wiring_waived"):
        hook_problems = _worktree_hook_problems(state)
        if hook_problems:
            add("FAIL", "state", "hooks_not_wired",
                "worktree .claude/settings.json missing safety hooks ("
                + "; ".join(hook_problems)
                + "); re-run Phase 0 Step 2.5 or set hooks_wiring_waived to opt out")

    # v2.29 (I7): read-only cross-check of run_report.json's failure_summary
    # against the actual state gap counts. WARN only — run_report.json is a
    # report artifact, not load-bearing state; a mismatch flags a stale/buggy
    # report build, never blocks finalization. Skips silently when no report_dir
    # is supplied or no run_report.json exists (existing call sites unaffected).
    if report_dir is not None:
        report_path = Path(report_dir) / "run_report.json"
        if report_path.is_file():
            try:
                report = json.loads(report_path.read_text(encoding="utf-8"))
                by_class = (report.get("failure_summary") or {}).get("by_class") or {}
            except (json.JSONDecodeError, OSError):
                by_class = None
            if isinstance(by_class, dict):
                vg, dg = _gap_counts(state)
                if by_class.get("verification_gap") != vg or by_class.get("docs_gap") != dg:
                    add("WARN", "state", "failure_summary_mismatch",
                        f"run_report.json failure_summary by_class "
                        f"(verification_gap={by_class.get('verification_gap')}, "
                        f"docs_gap={by_class.get('docs_gap')}) disagrees with state gaps "
                        f"(verification_gap={vg}, docs_gap={dg}); rebuild build_final_report.py")

    # Run-level consistency: a COMPLETE run must be fully finalized.
    if state.get("status") == "COMPLETE":
        if any(f["code"] in ("completed_at_null", "verifier_pending_batch") for f in findings):
            add("FAIL", "state", "complete_but_unfinalized",
                "status==COMPLETE but completed_at null or a task is PENDING_BATCH")

    unfixable_fail = any(f["level"] == "FAIL" and not f["fixable"] for f in findings)
    any_fail = any(f["level"] == "FAIL" for f in findings)
    return {"passed": not any_fail, "unfixable_fail": unfixable_fail, "findings": findings}


def apply_fix(state_path: Path) -> dict[str, Any]:
    """Stamp completed_at if null. Atomic. Returns the post-fix evaluation."""
    state = json.loads(state_path.read_text(encoding="utf-8"))
    ts = state.setdefault("timestamps", {})
    if not ts.get("completed_at"):
        ts["completed_at"] = state.get("last_completed_at") or \
            datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        tmp = state_path.with_suffix(state_path.suffix + ".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, state_path)
    return evaluate(state, report_dir=state_path.parent)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", required=True, type=Path)
    ap.add_argument("--check", action="store_true", help="report only (default)")
    ap.add_argument("--fix", action="store_true", help="stamp completed_at, then re-check")
    ap.add_argument("--active-plan", default="auto")  # accepted for contract parity
    args = ap.parse_args(argv)

    try:
        if args.fix:
            result = apply_fix(args.state)
        else:
            state = json.loads(args.state.read_text(encoding="utf-8"))
            result = evaluate(state, report_dir=args.state.parent)
    except Exception as exc:  # noqa: BLE001 — broken state is exit 2 by contract
        print(json.dumps({"passed": False, "error": f"unparseable state.json: {exc}"}))
        return 2

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
