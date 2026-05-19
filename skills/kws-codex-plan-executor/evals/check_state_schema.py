#!/usr/bin/env python3
"""Deterministic checks for validate_state.py contract enforcement."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


RUN_ID = "example-plan-20260519-143022"


def run_dir() -> str:
    return f"/tmp/codex-home/.codex/orchestrator/{RUN_ID}"


def worktree() -> str:
    return f"/tmp/codex-home/.codex/worktrees/{RUN_ID}"


REQUIRED_CONTRACT = {
    "scope": "Create one docs note.",
    "files_to_inspect": ["docs/example.md"],
    "allowed_edits": ["docs/example.md"],
    "forbidden_edits": ["docs/unrelated.md"],
    "acceptance_command_or_honest_substitute": "test -f docs/example.md",
}


def unit_manifest() -> dict:
    return {
        "unit_type": "execute-task",
        "context_mode": "focused",
        "required_skills": ["using-superpowers", "test-driven-development"],
        "tool_policy": "implementation",
        "allowed_write_globs": ["docs/example.md"],
        "forbidden_write_globs": ["docs/unrelated.md"],
        "artifact_policy": "inline-summary",
        "max_context_chars": 60000,
    }


def base_state() -> dict:
    rd = run_dir()
    return {
        "schema_version": "1",
        "run_id": RUN_ID,
        "mode": "interactive",
        "workspace": "/tmp/repo",
        "plan": "/tmp/repo/plan.md",
        "branch": f"codex/{RUN_ID}",
        "worktree": worktree(),
        "run_dir": rd,
        "state_path": f"{rd}/state.json",
        "context_snapshot_path": f"{rd}/context.json",
        "context_basis_hash": "0" * 64,
        "context_health": {
            "status": "green",
            "last_checked_at": "2026-05-19T14:35:00Z",
            "context_snapshot_present": True,
            "context_basis_hash_recorded": True,
            "active_task_contract_present": True,
            "next_action": "Report finished outcome with verification evidence.",
            "open_questions": [],
            "known_assumptions": [],
            "handoff_ready": True,
        },
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
        "subagents_requested": True,
        "subagent_runs": [],
        "tasks": {
            "task_0": {
                "status": "completed",
                "risk": "low",
                "files_declared": ["docs/example.md"],
                "contract": dict(REQUIRED_CONTRACT),
                "unit_manifest": unit_manifest(),
                "review_retries": 0,
                "verifier_retries": 0,
            }
        },
        "timestamps": {
            "started_at": "2026-05-19T14:30:22Z",
            "updated_at": "2026-05-19T14:35:00Z",
            "completed_at": "2026-05-19T14:35:00Z",
        },
    }


def completed_subagent_run() -> dict:
    return {
        "id": "agent_123",
        "owner_task": "task_0",
        "mode": "fork_context",
        "write_scope": ["docs/subagent.md"],
        "status": "completed",
        "result_summary": "Updated the delegated docs note.",
        "changed_files": ["docs/subagent.md"],
        "review_status": "accepted",
        "merged_at": "2026-05-19T14:34:00Z",
    }


def valid_command_observation() -> dict:
    return {
        "command": "pnpm test",
        "status": "failed",
        "category": "dependency_bootstrap",
        "evidence": "node_modules is missing in the fresh worktree.",
        "next_action": "Run pnpm install before retrying tests.",
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
        failures.append("valid v2.19 state should pass: " + (valid.stderr or valid.stdout))

    subagents_default_on = base_state()
    subagents_default_on["subagents_requested"] = False
    subagents_default_on["subagent_runs"] = []
    result = run_validator(script, subagents_default_on)
    checks["subagents_auto_without_runs_passes"] = result.returncode == 0
    if not checks["subagents_auto_without_runs_passes"]:
        failures.append("subagents auto with no explicit request should pass")

    subagents_off = base_state()
    subagents_off["subagents_requested"] = False
    subagents_off["subagent_runs"] = []
    result = run_validator(script, subagents_off)
    checks["subagents_off_without_runs_passes"] = result.returncode == 0
    if not checks["subagents_off_without_runs_passes"]:
        failures.append("subagents off with no runs should pass")

    completed_subagent = base_state()
    completed_subagent["subagent_runs"] = [completed_subagent_run()]
    result = run_validator(script, completed_subagent)
    checks["completed_reviewed_subagent_passes"] = result.returncode == 0
    if not checks["completed_reviewed_subagent_passes"]:
        failures.append("completed reviewed subagent record should pass")

    unknown_owner = base_state()
    run = completed_subagent_run()
    run["owner_task"] = "task_404"
    unknown_owner["subagent_runs"] = [run]
    result = run_validator(script, unknown_owner)
    checks["subagent_unknown_owner_task_fails"] = (
        result.returncode != 0 and "owner_task must reference a task in state" in (result.stderr + result.stdout)
    )
    if not checks["subagent_unknown_owner_task_fails"]:
        failures.append("subagent owner_task should reference an existing task")

    empty_scope = base_state()
    run = completed_subagent_run()
    run["write_scope"] = []
    empty_scope["subagent_runs"] = [run]
    result = run_validator(script, empty_scope)
    checks["subagent_empty_write_scope_fails"] = (
        result.returncode != 0 and "write_scope must be a non-empty list" in (result.stderr + result.stdout)
    )
    if not checks["subagent_empty_write_scope_fails"]:
        failures.append("subagent write_scope should be non-empty")

    changed_outside_scope = base_state()
    run = completed_subagent_run()
    run["changed_files"] = ["src/outside.py"]
    changed_outside_scope["subagent_runs"] = [run]
    result = run_validator(script, changed_outside_scope)
    checks["subagent_changed_files_outside_scope_fails"] = (
        result.returncode != 0 and "changed_files must match write_scope" in (result.stderr + result.stdout)
    )
    if not checks["subagent_changed_files_outside_scope_fails"]:
        failures.append("completed subagent changed_files should match write_scope")

    active_overlap = base_state()
    active_a = completed_subagent_run()
    active_a["id"] = "agent_active_a"
    active_a["status"] = "running"
    active_a["review_status"] = "unreviewed"
    active_a["changed_files"] = []
    active_a["write_scope"] = ["docs/**"]
    active_b = completed_subagent_run()
    active_b["id"] = "agent_active_b"
    active_b["status"] = "queued"
    active_b["review_status"] = "unreviewed"
    active_b["changed_files"] = []
    active_b["write_scope"] = ["docs/example.md"]
    active_overlap["lifecycle_outcome"] = None
    active_overlap["completion_audit"] = None
    active_overlap["subagent_runs"] = [active_a, active_b]
    result = run_validator(script, active_overlap)
    checks["active_subagent_write_scope_overlap_fails"] = (
        result.returncode != 0 and "active subagent write_scope overlap" in (result.stderr + result.stdout)
    )
    if not checks["active_subagent_write_scope_overlap_fails"]:
        failures.append("active subagent write scope overlap should require a rationale")

    empty_allowed_globs = base_state()
    empty_allowed_globs["tasks"]["task_0"]["unit_manifest"]["allowed_write_globs"] = []
    result = run_validator(script, empty_allowed_globs)
    checks["unit_manifest_empty_allowed_globs_fails"] = (
        result.returncode != 0 and "unit_manifest.allowed_write_globs must be non-empty" in (result.stderr + result.stdout)
    )
    if not checks["unit_manifest_empty_allowed_globs_fails"]:
        failures.append("implementation unit_manifest should require non-empty allowed_write_globs")

    subagent_without_opt_in = base_state()
    subagent_without_opt_in["subagents_requested"] = False
    subagent_without_opt_in["subagent_runs"] = [completed_subagent_run()]
    result = run_validator(script, subagent_without_opt_in)
    checks["subagent_runs_without_opt_in_fails"] = (
        result.returncode != 0 and "subagent_runs requires subagents_requested=true" in (result.stderr + result.stdout)
    )
    if not checks["subagent_runs_without_opt_in_fails"]:
        failures.append("subagent runs should require subagents_requested=true")

    old_journal = base_state()
    old_journal["event_" + "journal_path"] = "legacy"
    old_journal["last_" + "event_seq"] = 1
    result = run_validator(script, old_journal)
    checks["old_journal_metadata_fails"] = (
        result.returncode != 0 and "legacy event journal metadata is not supported" in (result.stderr + result.stdout)
    )
    if not checks["old_journal_metadata_fails"]:
        failures.append("old journal metadata should fail")

    bad_worktree = base_state()
    bad_worktree["worktree"] = "/tmp/repo"
    result = run_validator(script, bad_worktree)
    checks["bad_worktree_path_fails"] = result.returncode != 0 and "worktree must end" in (result.stderr + result.stdout)
    if not checks["bad_worktree_path_fails"]:
        failures.append("worktree outside ~/.codex/worktrees shape should fail")

    bad_run_dir = base_state()
    bad_run_dir["run_dir"] = "/tmp/repo/orchestrator"
    bad_run_dir["state_path"] = "/tmp/repo/orchestrator/state.json"
    result = run_validator(script, bad_run_dir)
    checks["bad_run_dir_fails"] = result.returncode != 0 and "run_dir must end" in (result.stderr + result.stdout)
    if not checks["bad_run_dir_fails"]:
        failures.append("run_dir outside ~/.codex/orchestrator shape should fail")

    running_subagent = base_state()
    running = completed_subagent_run()
    running["status"] = "running"
    running["review_status"] = "unreviewed"
    running["changed_files"] = []
    running_subagent["subagent_runs"] = [running]
    result = run_validator(script, running_subagent)
    checks["finished_running_subagent_fails"] = result.returncode != 0 and "running subagent" in (result.stderr + result.stdout)
    if not checks["finished_running_subagent_fails"]:
        failures.append("finished run with running subagent should fail")

    overlapping = base_state()
    overlap = completed_subagent_run()
    overlap["write_scope"] = ["docs/example.md"]
    overlap["changed_files"] = ["docs/example.md"]
    overlapping["subagent_runs"] = [overlap]
    result = run_validator(script, overlapping)
    checks["subagent_overlap_without_rationale_fails"] = result.returncode != 0 and "overlap_rationale" in (result.stderr + result.stdout)
    if not checks["subagent_overlap_without_rationale_fails"]:
        failures.append("subagent write overlap should require rationale")

    valid_observation = base_state()
    valid_observation["command_observations"] = [valid_command_observation()]
    result = run_validator(script, valid_observation)
    checks["valid_command_observation_passes"] = result.returncode == 0
    if not checks["valid_command_observation_passes"]:
        failures.append("valid command_observation should pass")

    invalid_observation = base_state()
    observation = valid_command_observation()
    observation["category"] = "mystery"
    invalid_observation["command_observations"] = [observation]
    result = run_validator(script, invalid_observation)
    checks["invalid_command_observation_category_fails"] = result.returncode != 0 and "command_observations[0].category" in (result.stderr + result.stdout)
    if not checks["invalid_command_observation_category_fails"]:
        failures.append("invalid command_observation category should fail")

    payload_out = {"passed": not failures, "checks": checks, "failures": failures}
    print(json.dumps(payload_out, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
