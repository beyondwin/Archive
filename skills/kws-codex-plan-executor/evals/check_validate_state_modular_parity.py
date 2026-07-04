#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


VALIDATOR = Path(__file__).resolve().parents[1] / "scripts" / "validate_state.py"


def base_state(run_dir: Path) -> dict:
    return {
        "schema_version": "1",
        "run_id": "parity-run",
        "mode": "interactive",
        "run_dir": str(run_dir),
        "state_path": str(run_dir / "state.json"),
        "workspace": str(run_dir.parent.parent / "worktrees" / "parity-run"),
        "plan": str(run_dir / "plan.md"),
        "branch": "codex/parity-run",
        "worktree": str(run_dir.parent.parent / "worktrees" / "parity-run"),
        "execution_worktree": str(run_dir.parent.parent / "worktrees" / "parity-run"),
        "agentlens_orchestration_run": "agentlens-parity",
        "lifecycle_outcome": "finished",
        "subagents_requested": False,
        "context_snapshot_path": str(run_dir / "context.json"),
        "context_basis_hash": "a" * 64,
        "context_health": {
            "status": "green",
            "last_checked_at": "2026-07-04T00:01:00Z",
            "context_snapshot_present": True,
            "context_basis_hash_recorded": True,
            "active_task_contract_present": False,
            "next_action": "complete",
            "open_questions": [],
            "known_assumptions": [],
            "handoff_ready": True,
        },
        "completion_audit": {
            "passed": True,
            "prompt_to_artifact_checklist": ["artifact matches prompt"],
            "verification_evidence": [
                {"class": "verification_bundle", "name": "parity", "commands": ["python3 evals/check.py"], "status": "passed"}
            ],
            "residual_risk": [],
        },
        "current_task": None,
        "current_phase": "complete",
        "tasks": {},
        "run_quality": {
            "schema_version": "1",
            "validation_status": "passed",
            "terminal_state": "finished",
            "stale": False,
            "workspace_matches_execution_worktree": True,
            "score": 100,
            "grade": "green",
            "schema_drift": [],
            "open_followups": [],
            "readiness": {"task_count": 0, "fixable_issue_count": 0, "blocking_issue_count": 0},
            "dispatch_consistency": {"mismatch_count": 0, "override_count": 0},
            "context_quality": {"full_spec_fallback_count": 0},
            "verification_quality": {"completion_audit_passed": True},
            "recommendations": [],
            "summary": "Run finished with validated state.",
        },
        "timestamps": {
            "started_at": "2026-07-04T00:00:00Z",
            "updated_at": "2026-07-04T00:01:00Z",
            "completed_at": "2026-07-04T00:01:00Z",
        },
    }


def run_validator(state: dict, path: Path) -> subprocess.CompletedProcess[str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    (path.parent / "context.json").write_text(
        json.dumps({"basis_hash": state["context_basis_hash"]}) + "\n",
        encoding="utf-8",
    )
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return subprocess.run([sys.executable, str(VALIDATOR), str(path)], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def main() -> int:
    failures: list[str] = []
    checks: dict[str, bool] = {}
    with tempfile.TemporaryDirectory(prefix="cpe-validate-parity-") as temp:
        run_dir = Path(temp) / ".codex" / "orchestrator" / "parity-run"
        valid = base_state(run_dir)
        result = run_validator(valid, run_dir / "state.json")
        checks["valid_state_passes"] = result.returncode == 0
        invalid = base_state(run_dir / "invalid")
        invalid["completion_audit"]["passed"] = False
        result = run_validator(invalid, run_dir / "invalid" / "state.json")
        checks["invalid_finished_completion_fails"] = (
            result.returncode != 0 and "completion_audit.passed" in (result.stderr + result.stdout)
        )
        graphify_invalid = base_state(run_dir / "graphify-invalid")
        graphify_invalid["graphify_audit"] = {
            "schema_version": "1",
            "graphify_present": True,
            "update_required": False,
            "fresh": True,
            "errors": ["boom"],
            "warnings": [],
        }
        result = run_validator(graphify_invalid, run_dir / "graphify-invalid" / "state.json")
        checks["graphify_errors_fail_finished_state"] = (
            result.returncode != 0 and "graphify_audit.errors" in (result.stderr + result.stdout)
        )
        prompt_invalid = base_state(run_dir / "prompt-invalid")
        prompt_invalid["prompt_audit"] = {"schema_version": "1", "dynamic_marker_violations": ["timestamp"]}
        result = run_validator(prompt_invalid, run_dir / "prompt-invalid" / "state.json")
        checks["prompt_dynamic_markers_fail_finished_state"] = (
            result.returncode != 0 and "dynamic_marker_violations" in (result.stderr + result.stdout)
        )
        plan_invalid = base_state(run_dir / "plan-invalid")
        plan_invalid["plan_executability_audit"] = {
            "path": str(run_dir / "plan-invalid" / "plan_executability_audit.json"),
            "grade": "red",
            "blocking_issue_count": 1,
            "fixable_issue_count": 0,
        }
        result = run_validator(plan_invalid, run_dir / "plan-invalid" / "state.json")
        checks["red_plan_audit_fails_finished_state"] = (
            result.returncode != 0 and "plan_executability_audit" in (result.stderr + result.stdout)
        )
        quality_invalid = base_state(run_dir / "quality-invalid")
        quality_invalid["run_quality"]["open_followups"] = ["agentlens_missing"]
        result = run_validator(quality_invalid, run_dir / "quality-invalid" / "state.json")
        checks["green_run_quality_with_followups_fails"] = (
            result.returncode != 0 and "run_quality.grade" in (result.stderr + result.stdout)
        )
        delegation_invalid = base_state(run_dir / "delegation-invalid")
        delegation_invalid["delegation_policy"] = {"requested_mode": "invalid"}
        result = run_validator(delegation_invalid, run_dir / "delegation-invalid" / "state.json")
        checks["invalid_delegation_policy_fails"] = (
            result.returncode != 0 and "delegation_policy" in (result.stderr + result.stdout)
        )
        task_invalid = base_state(run_dir / "task-invalid")
        task_invalid["subagents_requested"] = True
        task_invalid["tasks"] = {
            "task_1": {
                "status": "completed",
                "risk": "medium",
                "files_declared": ["src/app.py"],
                "contract": {
                    "scope": "write",
                    "files_to_inspect": ["src/app.py"],
                    "allowed_edits": ["src/app.py"],
                    "forbidden_edits": [".git/**"],
                    "acceptance_command_or_honest_substitute": "python3 -m pytest",
                },
                "unit_manifest": {
                    "unit_type": "execute-task",
                    "context_mode": "focused",
                    "required_skills": ["using-superpowers", "test-driven-development"],
                    "tool_policy": "implementation",
                    "allowed_write_globs": ["src/app.py"],
                    "forbidden_write_globs": [".git/**"],
                    "artifact_policy": "inline-summary",
                    "max_context_chars": 60000,
                },
                "review_retries": 0,
                "verifier_retries": 0,
                "timing": {
                    "started": "2026-07-04T00:00:00Z",
                    "completed": "2026-07-04T00:01:00Z",
                    "verified": "2026-07-04T00:01:00Z",
                },
            }
        }
        task_invalid["current_task"] = "task_1"
        task_invalid["run_quality"]["grade"] = "yellow"
        task_invalid["run_quality"]["open_followups"] = ["delegation_policy_missing_dispatch_evidence"]
        task_invalid["run_quality"]["operational_debt"] = {
            "schema_version": "1",
            "followups": ["delegation_policy_missing_dispatch_evidence"],
            "count": 1,
            "blocking": False,
        }
        result = run_validator(task_invalid, run_dir / "task-invalid" / "state.json")
        checks["completed_write_task_requires_strategy"] = (
            result.returncode != 0 and "subagent_strategy" in (result.stderr + result.stdout)
        )
    for name, passed in checks.items():
        if not passed:
            failures.append(name)
    print(json.dumps({"passed": not failures, "checks": checks, "failures": failures}, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
