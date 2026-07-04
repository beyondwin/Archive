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
    for name, passed in checks.items():
        if not passed:
            failures.append(name)
    print(json.dumps({"passed": not failures, "checks": checks, "failures": failures}, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
