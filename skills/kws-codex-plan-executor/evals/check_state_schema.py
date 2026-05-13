#!/usr/bin/env python3
"""Deterministic checks for validate_state.py contract enforcement."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


REQUIRED_CONTRACT = {
    "scope": "Create one docs note.",
    "files_to_inspect": ["docs/example.md"],
    "allowed_edits": [
        "docs/example.md",
        ".codex-orchestrator/runs/20260513T000000Z-archive-codex-example-abcdef0-a1b2c3/state.json",
    ],
    "forbidden_edits": ["docs/unrelated.md"],
    "acceptance_command_or_honest_substitute": "test -f docs/example.md",
}


def base_state() -> dict:
    return {
        "schema_version": "1",
        "run_id": "20260513T000000Z-archive-codex-example-abcdef0-a1b2c3",
        "mode": "interactive",
        "workspace": "/tmp/repo",
        "plan": "/tmp/repo/plan.md",
        "branch": "codex/example",
        "worktree": "/tmp/repo",
        "run_dir": ".codex-orchestrator/runs/20260513T000000Z-archive-codex-example-abcdef0-a1b2c3",
        "state_path": ".codex-orchestrator/runs/20260513T000000Z-archive-codex-example-abcdef0-a1b2c3/state.json",
        "context_snapshot_path": ".codex-orchestrator/runs/20260513T000000Z-archive-codex-example-abcdef0-a1b2c3/context.json",
        "context_basis_hash": "0" * 64,
        "current_task": "task_0",
        "current_phase": "task_loop",
        "lifecycle_outcome": "finished",
        "handoff_reason": "",
        "completion_audit": {
            "passed": True,
            "prompt_to_artifact_checklist": ["Task 0 mapped to docs/example.md"],
            "verification_evidence": [{"command": "test -f docs/example.md", "status": "passed"}],
            "open_gaps": [],
            "residual_risk": [],
        },
        "tasks": {
            "task_0": {
                "status": "pending",
                "risk": "low",
                "files_declared": ["docs/example.md"],
                "contract": dict(REQUIRED_CONTRACT),
                "review_retries": 0,
                "verifier_retries": 0,
            }
        },
        "timestamps": {"started_at": None, "updated_at": None, "completed_at": None},
    }


def run_validator(script: Path, payload: dict) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory(prefix="codex-state-schema-") as temp:
        state_path = Path(temp) / "state.json"
        state_path.write_text(json.dumps(payload), encoding="utf-8")
        return subprocess.run(
            [sys.executable, str(script), str(state_path)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )


def main() -> int:
    script = Path(__file__).resolve().parents[1] / "scripts" / "validate_state.py"
    checks: dict[str, bool] = {}
    failures: list[str] = []

    valid = run_validator(script, base_state())
    checks["valid_contract_passes"] = valid.returncode == 0
    if not checks["valid_contract_passes"]:
        failures.append("valid state with task contract should pass")

    missing_contract = base_state()
    del missing_contract["tasks"]["task_0"]["contract"]
    missing = run_validator(script, missing_contract)
    checks["missing_contract_fails"] = missing.returncode != 0 and "contract" in (missing.stderr + missing.stdout)
    if not checks["missing_contract_fails"]:
        failures.append("state without task contract should fail")

    incomplete_contract = base_state()
    del incomplete_contract["tasks"]["task_0"]["contract"]["forbidden_edits"]
    incomplete = run_validator(script, incomplete_contract)
    checks["incomplete_contract_fails"] = incomplete.returncode != 0 and "forbidden_edits" in (
        incomplete.stderr + incomplete.stdout
    )
    if not checks["incomplete_contract_fails"]:
        failures.append("state with incomplete task contract should fail")

    missing_run = base_state()
    del missing_run["run_id"]
    missing_run_result = run_validator(script, missing_run)
    checks["missing_run_id_fails"] = missing_run_result.returncode != 0 and "run_id" in (
        missing_run_result.stderr + missing_run_result.stdout
    )
    if not checks["missing_run_id_fails"]:
        failures.append("state without run_id should fail")

    mismatched_state_path = base_state()
    mismatched_state_path["state_path"] = ".codex-orchestrator/state.json"
    mismatch = run_validator(script, mismatched_state_path)
    checks["mismatched_state_path_fails"] = mismatch.returncode != 0 and "state_path" in (
        mismatch.stderr + mismatch.stdout
    )
    if not checks["mismatched_state_path_fails"]:
        failures.append("state_path should point at the matching per-run state")

    missing_context = base_state()
    del missing_context["context_snapshot_path"]
    missing_context_result = run_validator(script, missing_context)
    checks["missing_context_snapshot_fails"] = missing_context_result.returncode != 0 and "context_snapshot_path" in (
        missing_context_result.stderr + missing_context_result.stdout
    )
    if not checks["missing_context_snapshot_fails"]:
        failures.append("interactive state after preflight should include context_snapshot_path")

    mismatched_context = base_state()
    mismatched_context["context_snapshot_path"] = ".codex-orchestrator/context.json"
    mismatched_context_result = run_validator(script, mismatched_context)
    checks["mismatched_context_snapshot_fails"] = mismatched_context_result.returncode != 0 and "context_snapshot_path" in (
        mismatched_context_result.stderr + mismatched_context_result.stdout
    )
    if not checks["mismatched_context_snapshot_fails"]:
        failures.append("context_snapshot_path should point at the matching per-run context")

    finished_without_audit = base_state()
    del finished_without_audit["completion_audit"]
    no_audit = run_validator(script, finished_without_audit)
    checks["finished_without_audit_fails"] = no_audit.returncode != 0 and "completion_audit" in (
        no_audit.stderr + no_audit.stdout
    )
    if not checks["finished_without_audit_fails"]:
        failures.append("finished lifecycle outcome should require completion_audit")

    finished_empty_evidence = base_state()
    finished_empty_evidence["completion_audit"]["verification_evidence"] = []
    empty_evidence = run_validator(script, finished_empty_evidence)
    checks["finished_empty_evidence_fails"] = empty_evidence.returncode != 0 and "verification_evidence" in (
        empty_evidence.stderr + empty_evidence.stdout
    )
    if not checks["finished_empty_evidence_fails"]:
        failures.append("finished completion_audit should require verification evidence")

    blocked = base_state()
    blocked["lifecycle_outcome"] = "blocked"
    blocked["handoff_reason"] = "waiting for user decision"
    del blocked["completion_audit"]
    blocked_result = run_validator(script, blocked)
    checks["blocked_with_handoff_reason_passes"] = blocked_result.returncode == 0
    if not checks["blocked_with_handoff_reason_passes"]:
        failures.append("blocked lifecycle outcome with handoff_reason should pass")

    blocked_no_reason = base_state()
    blocked_no_reason["lifecycle_outcome"] = "blocked"
    blocked_no_reason["handoff_reason"] = ""
    del blocked_no_reason["completion_audit"]
    blocked_no_reason_result = run_validator(script, blocked_no_reason)
    checks["blocked_without_handoff_reason_fails"] = blocked_no_reason_result.returncode != 0 and "handoff_reason" in (
        blocked_no_reason_result.stderr + blocked_no_reason_result.stdout
    )
    if not checks["blocked_without_handoff_reason_fails"]:
        failures.append("blocked lifecycle outcome should require handoff_reason")

    invalid_lifecycle = base_state()
    invalid_lifecycle["lifecycle_outcome"] = "done"
    invalid_lifecycle_result = run_validator(script, invalid_lifecycle)
    checks["invalid_lifecycle_fails"] = invalid_lifecycle_result.returncode != 0 and "lifecycle_outcome" in (
        invalid_lifecycle_result.stderr + invalid_lifecycle_result.stdout
    )
    if not checks["invalid_lifecycle_fails"]:
        failures.append("invalid lifecycle_outcome should fail")

    payload = {"passed": not failures, "checks": checks, "failures": failures}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
