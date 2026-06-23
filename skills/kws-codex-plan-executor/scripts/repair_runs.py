#!/usr/bin/env python3
"""Plan and apply conservative repairs for stale kws-cpe run state."""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import inspect_runs
import validate_state


SAFE_ACTIONS = {"mark-blocked-stale"}
FINISHED_OUTCOMES = inspect_runs.FINISHED_OUTCOMES


def die(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def state_path_for_run(codex_home: Path, run_id: str) -> Path:
    return codex_home / "orchestrator" / run_id / "state.json"


def state_path_is_safe(codex_home: Path, run_id: str, state_path: Path, state: dict[str, Any]) -> tuple[bool, str]:
    expected = state_path_for_run(codex_home, run_id).resolve(strict=False)
    actual = state_path.resolve(strict=False)
    if actual != expected:
        return False, f"state file must be {expected}"
    if state.get("run_id") != run_id:
        return False, "state.run_id must match the orchestrator directory name"
    state_path_field = state.get("state_path")
    if not isinstance(state_path_field, str) or Path(state_path_field).resolve(strict=False) != expected:
        return False, "state.state_path must equal .codex/orchestrator/<run_id>/state.json"
    run_dir_field = state.get("run_dir")
    if not isinstance(run_dir_field, str) or Path(run_dir_field).resolve(strict=False) != expected.parent:
        return False, "state.run_dir must equal .codex/orchestrator/<run_id>"
    return True, ""


def validation_errors(state: dict[str, Any] | None) -> list[str]:
    if state is None:
        return ["state file is unreadable"]
    return validate_state.validate(state)


def candidate(
    *,
    run_id: str,
    state_path: str,
    followups: list[str],
    action: str,
    apply_safe: bool,
    reason: str,
    patch_preview: dict[str, Any] | None = None,
    validation_errors_value: list[str] | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "run_id": run_id,
        "state_path": state_path,
        "detected_followups": sorted(followups),
        "recommended_action": action,
        "apply_safe": apply_safe,
        "reason": reason,
        "state_patch_preview": patch_preview or {},
    }
    if validation_errors_value:
        item["validation_errors"] = validation_errors_value
    return item


def classify_record(record: dict[str, Any], codex_home: Path) -> dict[str, Any] | None:
    run_id = str(record.get("run_id") or "")
    if not run_id:
        return None
    state_path = state_path_for_run(codex_home, run_id)
    state = inspect_runs.load_state(state_path)
    quality = record.get("run_quality") if isinstance(record.get("run_quality"), dict) else {}
    followups = list(quality.get("open_followups") or [])
    validation_status = quality.get("validation_status")
    terminal_state = quality.get("terminal_state")
    missing_worktree = record.get("missing_worktree") is True or "missing_execution_worktree" in followups
    redacted_state_path = inspect_runs.redacted(str(state_path), codex_home)

    safe_path, path_reason = state_path_is_safe(codex_home, run_id, state_path, state or {})
    if not safe_path:
        return candidate(
            run_id=run_id,
            state_path=redacted_state_path,
            followups=followups,
            action="manual-review-required",
            apply_safe=False,
            reason=path_reason,
        )
    if validation_status == "failed":
        return candidate(
            run_id=run_id,
            state_path=redacted_state_path,
            followups=followups,
            action="manual-review-required",
            apply_safe=False,
            reason="state validation failed before repair",
            validation_errors_value=list(quality.get("schema_drift") or []),
        )
    if state is None or validation_status == "unreadable":
        return candidate(
            run_id=run_id,
            state_path=redacted_state_path,
            followups=followups,
            action="manual-review-required",
            apply_safe=False,
            reason="state file is unreadable",
        )
    if isinstance(state.get("current_blocker"), dict):
        return candidate(
            run_id=run_id,
            state_path=redacted_state_path,
            followups=followups,
            action="manual-review-required",
            apply_safe=False,
            reason="existing current_blocker must be reviewed before repair",
        )
    if terminal_state == "finished" and missing_worktree:
        return candidate(
            run_id=run_id,
            state_path=redacted_state_path,
            followups=followups,
            action="acknowledge-cleaned-worktree",
            apply_safe=False,
            reason="finished state should not be rewritten without cleanup acknowledgement support",
        )
    if terminal_state in FINISHED_OUTCOMES:
        return None
    if "stale_non_terminal_run" in followups and missing_worktree:
        return candidate(
            run_id=run_id,
            state_path=redacted_state_path,
            followups=followups,
            action="mark-blocked-stale",
            apply_safe=True,
            reason="non-terminal stale run cannot resume because execution worktree is missing",
            patch_preview={
                "lifecycle_outcome": "blocked",
                "current_phase": "recover",
                "current_blocker.category": "state_integrity_drift",
            },
        )
    return None


def summarize(candidates: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "candidate_count": len(candidates),
        "apply_safe_count": sum(1 for item in candidates if item.get("apply_safe") is True),
        "manual_review_count": sum(1 for item in candidates if item.get("recommended_action") == "manual-review-required"),
    }


def build_plan(codex_home: Path, recent: int | None, stale_hours: float, *, dry_run: bool = True) -> dict[str, Any]:
    report = inspect_runs.inspect_all_runs(
        codex_home,
        recent,
        quality_report=True,
        stale_hours=stale_hours,
        validate=True,
    )
    records = report.get("runs") if isinstance(report.get("runs"), list) else []
    candidates = []
    for record in records:
        item = classify_record(record, codex_home)
        if item is not None:
            candidates.append(item)
    return {
        "schema_version": "1",
        "checked_at": now_iso(),
        "dry_run": dry_run,
        "summary": summarize(candidates),
        "candidates": candidates,
    }


def render_plan(plan: dict[str, Any], jsonl: bool) -> str:
    if jsonl:
        rows = plan.get("candidates") if isinstance(plan.get("candidates"), list) else []
        return "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n" for row in rows)
    return json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def write_output(text: str, output: str | None) -> None:
    if output:
        output_path = Path(output).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text, encoding="utf-8")
        print(output_path)
    else:
        print(text, end="")


def build_blocked_state(state: dict[str, Any], run_id: str, checked_at: str) -> dict[str, Any]:
    patched = copy.deepcopy(state)
    timestamps = patched.setdefault("timestamps", {})
    timestamps["updated_at"] = checked_at
    if timestamps.get("completed_at") is None:
        timestamps["completed_at"] = checked_at
    patched["lifecycle_outcome"] = "blocked"
    patched["current_phase"] = "recover"
    patched["handoff_reason"] = f"Run {run_id} is stale and cannot resume because its execution worktree is missing."
    patched["current_blocker"] = {
        "category": "state_integrity_drift",
        "summary": f"Run {run_id} is stale and its execution worktree is missing.",
        "recoverable": True,
        "next_action_kind": "operator_decision",
    }
    health = patched.setdefault("context_health", {})
    health["status"] = "yellow"
    health["last_checked_at"] = checked_at
    health["handoff_ready"] = True
    health["next_action"] = "Inspect the blocked state and start a fresh CPE run if implementation should continue."
    health.setdefault("open_questions", [])
    health.setdefault("known_assumptions", [])
    return patched


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def apply_action(codex_home: Path, run_id: str, action: str, stale_hours: float) -> tuple[int, dict[str, Any]]:
    if action != "mark-blocked-stale":
        die(f"unsupported action: {action}")
    state_path = state_path_for_run(codex_home, run_id)
    state = inspect_runs.load_state(state_path)
    if state is None:
        die(f"state is not readable JSON: {state_path}")
    safe_path, path_reason = state_path_is_safe(codex_home, run_id, state_path, state)
    if not safe_path:
        plan = {
            "schema_version": "1",
            "checked_at": now_iso(),
            "dry_run": False,
            "summary": {"candidate_count": 1, "apply_safe_count": 0, "manual_review_count": 1},
            "candidates": [
                candidate(
                    run_id=run_id,
                    state_path=inspect_runs.redacted(str(state_path), codex_home),
                    followups=[],
                    action="manual-review-required",
                    apply_safe=False,
                    reason=path_reason,
                )
            ],
        }
        return 1, plan
    pre_errors = validate_state.validate(state)
    if pre_errors:
        plan = {
            "schema_version": "1",
            "checked_at": now_iso(),
            "dry_run": False,
            "summary": {"candidate_count": 1, "apply_safe_count": 0, "manual_review_count": 1},
            "candidates": [
                candidate(
                    run_id=run_id,
                    state_path=inspect_runs.redacted(str(state_path), codex_home),
                    followups=["state_schema_drift"],
                    action="manual-review-required",
                    apply_safe=False,
                    reason="state validation failed before repair",
                    validation_errors_value=pre_errors,
                )
            ],
        }
        return 1, plan
    record = inspect_runs.state_record(
        state,
        state_path,
        codex_home,
        include_quality=True,
        stale_hours=stale_hours,
        validate=True,
    )
    classified = classify_record(record, codex_home)
    if not classified or classified.get("recommended_action") != action or classified.get("apply_safe") is not True:
        plan = {
            "schema_version": "1",
            "checked_at": now_iso(),
            "dry_run": False,
            "summary": summarize([classified] if classified else []),
            "candidates": [classified] if classified else [],
        }
        return 1, plan
    checked_at = now_iso()
    patched = build_blocked_state(state, run_id, checked_at)
    post_errors = validate_state.validate(patched)
    if post_errors:
        failed = dict(classified)
        failed["apply_safe"] = False
        failed["recommended_action"] = "manual-review-required"
        failed["reason"] = "repaired state failed validation"
        failed["validation_errors"] = post_errors
        plan = {
            "schema_version": "1",
            "checked_at": checked_at,
            "dry_run": False,
            "summary": summarize([failed]),
            "candidates": [failed],
        }
        return 1, plan
    atomic_write_json(state_path, patched)
    applied = dict(classified)
    applied["applied"] = True
    applied["before"] = {
        "lifecycle_outcome": state.get("lifecycle_outcome"),
        "current_phase": state.get("current_phase"),
        "validation_status": "passed",
    }
    applied["after"] = {
        "lifecycle_outcome": patched.get("lifecycle_outcome"),
        "current_phase": patched.get("current_phase"),
        "validation_status": "passed",
    }
    plan = {
        "schema_version": "1",
        "checked_at": checked_at,
        "dry_run": False,
        "summary": summarize([applied]),
        "candidates": [applied],
    }
    return 0, plan


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-home", required=True)
    parser.add_argument("--recent", type=int, default=20)
    parser.add_argument("--stale-hours", type=float, default=24.0)
    parser.add_argument("--output")
    parser.add_argument("--jsonl", action="store_true")
    parser.add_argument("--run-id")
    parser.add_argument("--action")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.recent is not None and args.recent < 0:
        die("--recent must be non-negative")
    if args.stale_hours < 0:
        die("--stale-hours must be non-negative")
    if args.apply and (not args.run_id or not args.action):
        die("--apply requires --run-id and --action")
    if args.action and args.action not in SAFE_ACTIONS:
        die(f"--action must be one of {sorted(SAFE_ACTIONS)}")
    return args


def main() -> int:
    args = parse_args()
    codex_home = Path(args.codex_home).expanduser().resolve()
    if args.apply:
        code, plan = apply_action(codex_home, args.run_id, args.action, args.stale_hours)
        write_output(render_plan(plan, args.jsonl), args.output)
        if code == 0:
            item = (plan.get("candidates") or [{}])[0]
            print(
                "applied mark-blocked-stale: "
                f"{item.get('run_id')} "
                f"{item.get('before', {}).get('lifecycle_outcome')} -> "
                f"{item.get('after', {}).get('lifecycle_outcome')}; "
                f"validation={item.get('after', {}).get('validation_status')}"
            )
        return code
    plan = build_plan(codex_home, args.recent, args.stale_hours, dry_run=True)
    write_output(render_plan(plan, args.jsonl), args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
