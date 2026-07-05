#!/usr/bin/env python3
"""Inspect active or stale kws-cpe runs without mutating them."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import validate_state
except Exception:
    validate_state = None

try:
    import run_quality_debt
except Exception:
    run_quality_debt = None


FINISHED_OUTCOMES = {"finished", "blocked", "failed", "cancelled"}


def die(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def redacted(path_text: object, codex_home: Path) -> str:
    if not isinstance(path_text, str) or not path_text:
        return ""
    path = Path(path_text).expanduser()
    try:
        rel = path.resolve(strict=False).relative_to(codex_home.resolve(strict=False))
    except ValueError:
        return str(path)
    return str(Path("~/.codex") / rel)


def mtime_iso(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_state(path: Path) -> dict | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def plan_matches(state_plan: object, requested_plan: str) -> bool:
    if not isinstance(state_plan, str):
        return False
    if state_plan == requested_plan:
        return True
    return Path(state_plan).as_posix() == Path(requested_plan).as_posix()


def validation_result(state: dict[str, Any] | None, enabled: bool) -> tuple[str, list[str]]:
    if not enabled:
        return "not_checked", []
    if state is None:
        return "unreadable", ["state file is unreadable"]
    if validate_state is None:
        return "unreadable", ["validate_state import failed"]
    try:
        errors = validate_state.validate(state)
    except Exception as exc:
        return "unreadable", [f"validate_state failed: {exc}"]
    return ("passed" if not errors else "failed", errors)


def inspection_observations(*, terminal: bool, missing_worktree: bool, observed_after_completion: bool) -> dict[str, Any]:
    display_class = "green"
    if missing_worktree and terminal and observed_after_completion:
        display_class = "green-with-info"
    elif missing_worktree:
        display_class = "yellow"
    return {
        "schema_version": "1",
        "missing_execution_worktree": missing_worktree,
        "observed_after_completion": observed_after_completion,
        "display_class": display_class,
    }


def run_quality(
    state: dict[str, Any] | None,
    state_path: Path,
    stale_hours: float,
    validate: bool,
) -> dict[str, Any]:
    outcome = state.get("lifecycle_outcome") if state else None
    terminal = outcome in FINISHED_OUTCOMES
    age_hours = (time.time() - state_path.stat().st_mtime) / 3600
    validation_status, errors = validation_result(state, validate)
    workspace = state.get("workspace") if state else None
    execution_worktree = (state.get("execution_worktree") or state.get("worktree")) if state else None
    workspace_matches = bool(workspace and execution_worktree and str(workspace) == str(execution_worktree))
    missing_worktree = not (isinstance(execution_worktree, str) and Path(execution_worktree).exists())
    stale = not terminal and age_hours >= stale_hours
    open_followups: list[str] = []
    summary_parts: list[str] = []
    if stale:
        open_followups.append("stale_non_terminal_run")
        summary_parts.append("stale non-terminal")
    elif not terminal:
        summary_parts.append("non-terminal")
    else:
        summary_parts.append("terminal")
    if missing_worktree:
        open_followups.append("missing_execution_worktree")
        summary_parts.append("missing execution worktree")
    if workspace and execution_worktree and not workspace_matches:
        open_followups.append("workspace_execution_worktree_mismatch")
    if validation_status == "failed":
        open_followups.append("state_schema_drift")
    existing_quality = state.get("run_quality") if isinstance(state, dict) and isinstance(state.get("run_quality"), dict) else {}
    base_followups = (
        list(existing_quality.get("open_followups", [])) if isinstance(existing_quality.get("open_followups"), list) else []
    )
    current_followups = list(base_followups)
    for item in open_followups:
        if item not in current_followups:
            current_followups.append(item)

    durable_missing_worktree = missing_worktree and not terminal
    if run_quality_debt is not None and state:
        for item in run_quality_debt.stable_followups(state, missing_execution_worktree=durable_missing_worktree):
            if item not in current_followups:
                current_followups.append(item)
        operational_debt = run_quality_debt.operational_debt_summary(
            state,
            missing_execution_worktree=durable_missing_worktree,
        )
        grade = run_quality_debt.grade_for(state, current_followups, validation_status)
    else:
        operational_debt = {
            "schema_version": "1",
            "followups": current_followups,
            "count": len(current_followups),
            "blocking": False,
        }
        grade = "red" if validation_status == "failed" else ("yellow" if current_followups else "green")

    observed_after_completion = terminal and current_followups != base_followups
    observations = inspection_observations(
        terminal=terminal,
        missing_worktree=missing_worktree,
        observed_after_completion=observed_after_completion,
    )
    result = {
        "schema_version": "1",
        "validation_status": validation_status,
        "terminal_state": outcome or "none",
        "stale": stale,
        "workspace_matches_execution_worktree": workspace_matches,
        "schema_drift": errors,
        "open_followups": current_followups,
        "operational_debt": operational_debt,
        "grade": grade,
        "observed_after_completion": observed_after_completion,
        "inspection_observations": observations,
        "summary": "; ".join(summary_parts),
    }
    for key in ("score", "readiness", "dispatch_consistency", "context_quality", "verification_quality", "recommendations"):
        if key in existing_quality and key not in result:
            result[key] = existing_quality[key]
    return result


def task_strategy_count(state: dict[str, Any] | None, mode: str) -> int:
    if not state:
        return 0
    tasks = state.get("tasks")
    if not isinstance(tasks, dict):
        return 0
    count = 0
    for task in tasks.values():
        if not isinstance(task, dict):
            continue
        strategy = task.get("subagent_strategy")
        if isinstance(strategy, dict) and strategy.get("mode") == mode:
            count += 1
    return count


def summary_counters(records: list[dict[str, Any]]) -> dict[str, int]:
    summary = {
        "total": len(records),
        "finished": 0,
        "non_terminal": 0,
        "validation_passed": 0,
        "validation_failed": 0,
        "stale_non_terminal": 0,
        "workspace_not_execution_worktree": 0,
        "delegated_tasks": 0,
        "local_fallback_tasks": 0,
    }
    for record in records:
        quality = record.get("run_quality") if isinstance(record.get("run_quality"), dict) else {}
        terminal_state = quality.get("terminal_state") or record.get("lifecycle_outcome")
        terminal = terminal_state in FINISHED_OUTCOMES
        if terminal:
            summary["finished"] += 1
        else:
            summary["non_terminal"] += 1
        if quality.get("validation_status") == "passed":
            summary["validation_passed"] += 1
        elif quality.get("validation_status") == "failed":
            summary["validation_failed"] += 1
        if quality.get("stale") is True and not terminal:
            summary["stale_non_terminal"] += 1
        if quality.get("workspace_matches_execution_worktree") is False:
            summary["workspace_not_execution_worktree"] += 1
        summary["delegated_tasks"] += int(record.get("delegated_tasks") or 0)
        summary["local_fallback_tasks"] += int(record.get("local_fallback_tasks") or 0)
    return summary


def state_record(
    state: dict[str, Any] | None,
    state_path: Path,
    codex_home: Path,
    *,
    include_quality: bool,
    stale_hours: float,
    validate: bool,
) -> dict[str, Any]:
    state = state or {}
    worktree = Path(str(state.get("worktree") or ""))
    blocker = state.get("current_blocker") if isinstance(state.get("current_blocker"), dict) else {}
    health = state.get("context_health") if isinstance(state.get("context_health"), dict) else {}
    budget = {}
    context_path = Path(str(state.get("context_snapshot_path") or ""))
    if context_path.is_file():
        context = load_state(context_path)
        budget = context.get("context_budget", {}) if isinstance(context, dict) else {}
    record = {
        "run_id": state.get("run_id") or state_path.parent.name,
        "state_path": redacted(str(state_path), codex_home),
        "worktree": redacted(str(worktree), codex_home),
        "current_task": state.get("current_task"),
        "last_completed_task": state.get("last_completed_task"),
        "lifecycle_outcome": state.get("lifecycle_outcome"),
        "current_blocker_category": blocker.get("category"),
        "next_action_kind": blocker.get("next_action_kind") or health.get("next_action"),
        "handoff_ready": health.get("handoff_ready"),
        "context_budget_status": budget.get("status"),
        "missing_worktree": not worktree.exists(),
        "orphaned_worktree": False,
        "state_mtime": mtime_iso(state_path),
    }
    if include_quality:
        record["plan"] = state.get("plan")
        record["delegated_tasks"] = task_strategy_count(state, "delegated")
        record["local_fallback_tasks"] = task_strategy_count(state, "local_fallback")
        record["run_quality"] = run_quality(state if state else None, state_path, stale_hours, validate)
    return record


def inspect_runs(
    codex_home: Path,
    plan: str,
    include_finished: bool,
    *,
    quality_report: bool = False,
    stale_hours: float = 24.0,
    validate: bool = False,
) -> dict:
    orchestrator = codex_home / "orchestrator"
    records: list[dict] = []
    if orchestrator.is_dir():
        for state_path in sorted(orchestrator.glob("*/state.json")):
            state = load_state(state_path)
            if not state or not plan_matches(state.get("plan"), plan):
                continue
            outcome = state.get("lifecycle_outcome")
            if outcome in FINISHED_OUTCOMES and not include_finished:
                continue
            records.append(
                state_record(
                    state,
                    state_path,
                    codex_home,
                    include_quality=quality_report,
                    stale_hours=stale_hours,
                    validate=validate,
                )
            )
    return {
        "schema_version": "1",
        "plan": plan,
        "active_runs": records,
        "ambiguous": len(records) > 1,
    }


def inspect_all_runs(
    codex_home: Path,
    recent: int | None,
    quality_report: bool,
    stale_hours: float,
    validate: bool,
) -> dict:
    orchestrator = codex_home / "orchestrator"
    state_paths = list(orchestrator.glob("*/state.json")) if orchestrator.is_dir() else []
    if recent is not None:
        state_paths = sorted(state_paths, key=lambda path: path.stat().st_mtime, reverse=True)[:recent]
    else:
        state_paths = sorted(state_paths)
    records = [
        state_record(
            load_state(state_path),
            state_path,
            codex_home,
            include_quality=quality_report,
            stale_hours=stale_hours,
            validate=validate,
        )
        for state_path in state_paths
    ]
    report: dict[str, Any] = {
        "schema_version": "1",
        "all_plans": True,
        "recent": recent,
        "runs": records,
    }
    if quality_report:
        report["summary"] = summary_counters(records)
    return report


def render_report(report: dict[str, Any], jsonl: bool) -> str:
    if not jsonl:
        return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if report.get("all_plans") is True:
        records = report.get("runs") if isinstance(report.get("runs"), list) else []
    else:
        records = report.get("active_runs") if isinstance(report.get("active_runs"), list) else []
    return "".join(
        json.dumps(record, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n" for record in records
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-home", required=True)
    parser.add_argument("--plan")
    parser.add_argument("--all-plans", action="store_true")
    parser.add_argument("--recent", type=int)
    parser.add_argument("--stale-hours", type=float, default=24.0)
    parser.add_argument("--validate-state", action="store_true")
    parser.add_argument("--quality-report", action="store_true")
    parser.add_argument("--jsonl", action="store_true")
    parser.add_argument("--output")
    parser.add_argument("--include-finished", action="store_true")
    args = parser.parse_args()
    if not args.all_plans and not args.plan:
        die("--plan is required unless --all-plans is set")
    if args.recent is not None and args.recent < 0:
        die("--recent must be non-negative")

    codex_home = Path(args.codex_home).expanduser().resolve()
    if args.all_plans:
        report = inspect_all_runs(codex_home, args.recent, args.quality_report, args.stale_hours, args.validate_state)
    else:
        report = inspect_runs(
            codex_home,
            args.plan,
            args.include_finished,
            quality_report=args.quality_report,
            stale_hours=args.stale_hours,
            validate=args.validate_state,
        )
    text = render_report(report, args.jsonl)
    if args.output:
        output = Path(args.output).expanduser()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
        if args.jsonl:
            print(text, end="")
        else:
            print(output)
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
