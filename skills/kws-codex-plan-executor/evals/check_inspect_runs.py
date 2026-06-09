#!/usr/bin/env python3
"""Deterministic checks for read-only CPE run inspection."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


def write_state(codex_home: Path, run_id: str, plan: str, outcome: str | None = None, create_worktree: bool = True) -> None:
    run_dir = codex_home / "orchestrator" / run_id
    worktree = codex_home / "worktrees" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    if create_worktree:
        worktree.mkdir(parents=True, exist_ok=True)
    state = {
        "run_id": run_id,
        "plan": plan,
        "worktree": str(worktree),
        "run_dir": str(run_dir),
        "state_path": str(run_dir / "state.json"),
        "context_snapshot_path": str(run_dir / "context.json"),
        "current_task": "task_2",
        "last_completed_task": "task_1",
        "lifecycle_outcome": outcome,
        "current_blocker": {
            "category": "plan_contract_gap",
            "summary": "Needs operator decision.",
            "recoverable": True,
            "next_action_kind": "operator_decision",
        },
        "context_health": {"handoff_ready": True, "next_action": "Resume task_2."},
    }
    (run_dir / "state.json").write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    (run_dir / "context.json").write_text(json.dumps({"context_budget": {"status": "yellow"}}), encoding="utf-8")


def inspect(codex_home: Path, plan: str, include_finished: bool = False) -> tuple[subprocess.CompletedProcess[str], dict]:
    script = Path(__file__).resolve().parents[1] / "scripts" / "inspect_runs.py"
    output = codex_home / "report.json"
    cmd = [
        sys.executable,
        str(script),
        "--codex-home",
        str(codex_home),
        "--plan",
        plan,
        "--output",
        str(output),
    ]
    if include_finished:
        cmd.append("--include-finished")
    result = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    data = json.loads(output.read_text(encoding="utf-8")) if output.is_file() else {}
    return result, data


def inspect_all(codex_home: Path, *extra: str) -> tuple[subprocess.CompletedProcess[str], dict]:
    script = Path(__file__).resolve().parents[1] / "scripts" / "inspect_runs.py"
    output = codex_home / "report.json"
    cmd = [
        sys.executable,
        str(script),
        "--codex-home",
        str(codex_home),
        "--all-plans",
        "--recent",
        "10",
        "--output",
        str(output),
        *extra,
    ]
    result = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    data = json.loads(output.read_text(encoding="utf-8")) if output.is_file() else {}
    return result, data


def main() -> int:
    failures: list[str] = []
    checks: dict[str, bool] = {}

    with tempfile.TemporaryDirectory(prefix="codex-inspect-runs-") as temp:
        home = Path(temp) / ".codex"
        write_state(home, "run-one", "docs/plan.md")
        result, data = inspect(home, "docs/plan.md")
        checks["one_active_run_reported"] = (
            result.returncode == 0 and len(data.get("active_runs", [])) == 1 and data.get("ambiguous") is False
        )
        if not checks["one_active_run_reported"]:
            failures.append("one active run for same plan should be reported without ambiguity")
        run = data.get("active_runs", [{}])[0]
        checks["recovery_fields_reported"] = (
            run.get("last_completed_task") == "task_1"
            and run.get("current_blocker_category") == "plan_contract_gap"
            and run.get("next_action_kind") == "operator_decision"
            and run.get("handoff_ready") is True
            and run.get("context_budget_status") == "yellow"
        )
        if not checks["recovery_fields_reported"]:
            failures.append("inspect output should include blocker, next action, handoff, and context budget fields")

    with tempfile.TemporaryDirectory(prefix="codex-inspect-runs-") as temp:
        home = Path(temp) / ".codex"
        write_state(home, "run-one", "docs/plan.md")
        write_state(home, "run-two", "docs/plan.md")
        result, data = inspect(home, "docs/plan.md")
        checks["multiple_active_runs_ambiguous"] = (
            result.returncode == 0 and len(data.get("active_runs", [])) == 2 and data.get("ambiguous") is True
        )
        if not checks["multiple_active_runs_ambiguous"]:
            failures.append("multiple active runs for same plan should set ambiguous=true")

    with tempfile.TemporaryDirectory(prefix="codex-inspect-runs-") as temp:
        home = Path(temp) / ".codex"
        write_state(home, "missing-worktree", "docs/plan.md", create_worktree=False)
        result, data = inspect(home, "docs/plan.md")
        run = (data.get("active_runs") or [{}])[0]
        checks["missing_worktree_reported"] = (
            result.returncode == 0
            and run.get("missing_worktree") is True
            and run.get("orphaned_worktree") is False
        )
        if not checks["missing_worktree_reported"]:
            failures.append("missing worktree should be reported without mutation")

    with tempfile.TemporaryDirectory(prefix="codex-inspect-runs-") as temp:
        home = Path(temp) / ".codex"
        write_state(home, "finished", "docs/plan.md", outcome="finished")
        default_result, default = inspect(home, "docs/plan.md")
        include_result, include = inspect(home, "docs/plan.md", include_finished=True)
        checks["finished_ignored_unless_included"] = (
            default_result.returncode == 0
            and default.get("active_runs") == []
            and include_result.returncode == 0
            and len(include.get("active_runs", [])) == 1
        )
        if not checks["finished_ignored_unless_included"]:
            failures.append("finished runs should be ignored unless --include-finished is passed")

    with tempfile.TemporaryDirectory(prefix="codex-inspect-runs-") as temp:
        home = Path(temp) / ".codex"
        write_state(home, "active-old", "docs/plan-a.md")
        write_state(home, "finished-new", "docs/plan-b.md", outcome="finished")
        result, data = inspect_all(home, "--validate-state", "--quality-report", "--stale-hours", "0")
        summary = data.get("summary", {})
        checks["all_plans_quality_summary_reported"] = (
            result.returncode == 0
            and summary.get("total") == 2
            and summary.get("finished") == 1
            and summary.get("non_terminal") == 1
            and summary.get("stale_non_terminal") == 1
        )
        if not checks["all_plans_quality_summary_reported"]:
            failures.append("all-plans quality report should summarize finished, non-terminal, and stale runs")

    payload = {"passed": not failures, "checks": checks, "failures": failures}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
