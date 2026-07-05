#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "analyze_recent_runs.py"


def write_state(run_dir: Path, run_id: str, *, grade: str, followups: list[str], completion: bool = True) -> None:
    run_dir.mkdir(parents=True)
    state = {
        "schema_version": "1",
        "run_id": run_id,
        "mode": "interactive",
        "run_dir": str(run_dir),
        "state_path": str(run_dir / "state.json"),
        "workspace": str(run_dir.parent.parent / "worktrees" / run_id),
        "worktree": str(run_dir.parent.parent / "worktrees" / run_id),
        "execution_worktree": str(run_dir.parent.parent / "worktrees" / run_id),
        "lifecycle_outcome": "finished",
        "subagents_requested": True,
        "completion_audit": {
            "passed": completion,
            "prompt_to_artifact_checklist": ["implemented requested artifacts"],
            "verification_evidence": [{"class": "verification_bundle", "name": "fixture"}],
            "residual_risk": [],
        },
        "run_quality": {
            "schema_version": "1",
            "grade": grade,
            "validation_status": "passed" if completion else "failed",
            "open_followups": followups,
            "readiness": {"fixable_issue_count": 0, "plan_executability_fixable_issue_count": 0},
            "dispatch_consistency": {},
            "context_quality": {"full_spec_fallback_count": 1 if "full_spec_fallback_present" in followups else 0},
            "verification_quality": {},
        },
        "tasks": {
            "task_1": {
                "status": "completed",
                "unit_manifest": {
                    "tool_policy": "implementation",
                    "allowed_write_globs": ["src/app.py"],
                    "forbidden_write_globs": [".git/**"],
                },
                "subagent_strategy": {
                    "mode": "local_fallback",
                    "reason": "spawn_agent tool policy requires explicit user delegation intent",
                    "run_ids": [],
                },
            }
        },
        "dispatch_decisions": [
            {
                "task_id": "task_1",
                "decision": "local_fallback",
                "reason": "spawn_agent tool policy requires explicit user delegation intent",
                "failed_prerequisites": ["spawn_policy_requires_explicit_user_request"],
            }
        ],
        "delegation_policy": {
            "requested_mode": "on",
            "requested_source": "default",
            "explicit_user_delegation_request": False,
            "spawn_policy": "explicit-request-required",
            "effective_mode": "local_fallback",
            "reason": "spawn_agent tool policy requires explicit user delegation intent",
            "policy_kind": "adaptive",
            "safety_gate": "failed",
            "value_gate": "skipped",
            "signals": {},
        },
    }
    (run_dir / "state.json").write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    failures: list[str] = []
    checks: dict[str, bool] = {}
    with tempfile.TemporaryDirectory(prefix="cpe-recent-rubric-") as temp:
        home = Path(temp)
        orch = home / ".codex" / "orchestrator"
        write_state(orch / "green-run", "green-run", grade="green", followups=[])
        write_state(
            orch / "info-run",
            "info-run",
            grade="yellow",
            followups=["agentlens_missing", "delegation_policy_expected_local_fallback"],
        )
        write_state(
            orch / "yellow-run",
            "yellow-run",
            grade="yellow",
            followups=["full_spec_fallback_present", "delegation_policy_expected_local_fallback"],
        )
        write_state(orch / "red-run", "red-run", grade="red", followups=["schema_drift"], completion=False)
        output = home / "report.json"
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--codex-home",
                str(home / ".codex"),
                "--recent",
                "3",
                "--include-finished",
                "--output",
                str(output),
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        report = json.loads(output.read_text(encoding="utf-8")) if output.is_file() else {}
        summary = report.get("summary", {})
        rubric = report.get("rubric", {})
        checks["script_succeeds"] = result.returncode == 0
        checks["counts_runs"] = summary.get("finished_passed_count") == 3 and summary.get("run_count") == 4
        checks["counts_grades"] = (
            summary.get("green_count") == 1
            and summary.get("green_with_info_count") == 1
            and summary.get("yellow_count") == 1
            and summary.get("red_count") == 1
        )
        checks["counts_taxonomy"] = (
            summary.get("actionable_followup_count") == 1 and summary.get("informational_followup_count") == 4
        )
        checks["rubric_uses_info_class"] = (
            rubric.get("delegation_efficiency") == "green-with-info"
            and rubric.get("validator_maintainability") in {"green", "green-with-info"}
        )
        for name, passed in checks.items():
            if not passed:
                failures.append(name)
    print(json.dumps({"passed": not failures, "checks": checks, "failures": failures}, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
