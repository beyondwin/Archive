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


def completed_task_subagent_run() -> dict:
    run = completed_subagent_run()
    run["write_scope"] = ["docs/example.md"]
    run["changed_files"] = ["docs/example.md"]
    run["overlap_rationale"] = "Subagent owned task_0 edits; parent reviewed and accepted the diff."
    return run


def boundary_attestation(*, match: bool = True, source_unchanged: bool = True) -> dict:
    root = worktree() if match else "/tmp/codex-home/source/Archive"
    return {
        "schema_version": "1",
        "execution_worktree": worktree(),
        "worker_cwd": root,
        "worker_git_root": root,
        "worker_head_before": "a" * 40,
        "worker_head_after": "b" * 40,
        "source_workspace": "/tmp/codex-home/source/Archive",
        "source_workspace_head_before": "c" * 40,
        "source_workspace_head_after": "c" * 40 if source_unchanged else "d" * 40,
        "execution_worktree_match": match,
        "source_workspace_unchanged": source_unchanged,
        "dirty_scope_after": [],
    }


def boundary_state() -> dict:
    state = v220_state()
    state["subagent_boundary_schema_version"] = "1"
    state["source_workspace"] = "/tmp/codex-home/source/Archive"
    state["execution_worktree"] = state["worktree"]
    state["agentlens_orchestration_run"] = "agentlens-run-boundary"
    state["dispatch_decisions"] = [valid_dispatch_decision("all pre-dispatch prerequisites passed")]
    state["run_quality"] = valid_run_quality()
    run = completed_task_subagent_run()
    run["id"] = "agent_boundary"
    run["boundary_attestation"] = boundary_attestation()
    run["accepted_as_final"] = True
    state["subagent_runs"] = [run]
    state["tasks"]["task_0"]["subagent_strategy"] = {
        "mode": "delegated",
        "reason": "all pre-dispatch prerequisites passed",
        "run_ids": ["agent_boundary"],
    }
    return state


def duplicate_final_attempt_state() -> dict:
    state = boundary_state()
    first = dict(state["subagent_runs"][0])
    first["id"] = "agent_attempt_1"
    first["attempt_group"] = "task_0:docs/example.md"
    first["attempt_index"] = 1
    first["accepted_as_final"] = True
    first["boundary_attestation"] = boundary_attestation()
    second = dict(first)
    second["id"] = "agent_attempt_2"
    second["attempt_index"] = 2
    state["subagent_runs"] = [first, second]
    state["tasks"]["task_0"]["subagent_strategy"]["run_ids"] = ["agent_attempt_1", "agent_attempt_2"]
    return state


def valid_command_observation() -> dict:
    return {
        "command": "pnpm test",
        "status": "failed",
        "category": "dependency_bootstrap",
        "evidence": "node_modules is missing in the fresh worktree.",
        "next_action": "Run pnpm install before retrying tests.",
    }


def valid_decision() -> dict:
    return {
        "id": "dec_0001",
        "task": "task_0",
        "decision": "Use task packets for spec slicing.",
        "files": ["docs/example.md"],
        "made_at": "2026-05-19T14:32:00Z",
        "supersedes": None,
        "superseded_by": None,
        "reason": None,
    }


def valid_warning() -> dict:
    return {
        "kind": "dependencies_likely_stale",
        "manifest": "package.json",
        "lockfile": "package-lock.json",
        "suggestion": "Run install before baseline.",
        "detected_at": "2026-05-19T14:32:00Z",
    }


def valid_run_quality() -> dict:
    return {
        "schema_version": "1",
        "validation_status": "passed",
        "terminal_state": "finished",
        "stale": False,
        "workspace_matches_execution_worktree": True,
        "score": 92,
        "grade": "green",
        "schema_drift": [],
        "open_followups": [],
        "readiness": {"task_count": 1, "fixable_issue_count": 0, "blocking_issue_count": 0},
        "dispatch_consistency": {"mismatch_count": 0, "override_count": 0},
        "context_quality": {"full_spec_fallback_count": 0},
        "verification_quality": {"completion_audit_passed": True, "verification_evidence_count": 1},
        "recommendations": [],
        "summary": "Run finished with validated state.",
    }


def valid_plan_executability_audit() -> dict:
    return {
        "path": f"{run_dir()}/plan_executability_audit.json",
        "grade": "yellow",
        "blocking_issue_count": 0,
        "fixable_issue_count": 1,
    }


def valid_dispatch_decision(reason: str = "Default subagent-first execution for an eligible task packet.") -> dict:
    return {
        "schema_version": "1",
        "task_id": "task_0",
        "decision": "delegate",
        "reason": reason,
        "write_scope": ["docs/example.md"],
        "failed_prerequisites": [],
    }


def v220_state() -> dict:
    state = base_state()
    rd = run_dir()
    state.update(
        {
            "spec_manifest_path": f"{rd}/spec_manifest.json",
            "task_packet_dir": f"{rd}/task_packets",
            "current_task_packet_path": f"{rd}/task_packets/task_0.json",
            "decisions_register": [valid_decision()],
            "preflight_warnings": [valid_warning()],
            "last_completed_task": "task_0",
            "last_completed_at": "2026-05-19T14:34:00Z",
            "compaction": {
                "points": [],
                "last_compaction_after_task": "task_0",
                "context_drop_count": 1,
            },
        }
    )
    state["tasks"]["task_0"].update(
        {
            "task_packet_path": f"{rd}/task_packets/task_0.json",
            "task_packet_sha256": "a" * 64,
            "spec_section_ids": ["S1"],
            "fallback_spec_used": False,
            "subagent_strategy": {
                "mode": "delegated",
                "run_ids": ["agent_123"],
                "reason": "Default subagent-first execution for an eligible task packet.",
            },
            "timing": {
                "started": "2026-05-19T14:31:00Z",
                "completed": "2026-05-19T14:34:00Z",
                "verified": "2026-05-19T14:35:00Z",
            },
        }
    )
    state["subagent_runs"] = [completed_task_subagent_run()]
    return state


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

    bad_residual_risk = base_state()
    bad_residual_risk["completion_audit"]["residual_risk"] = "This must be a list, not a scalar string."
    result = run_validator(script, bad_residual_risk)
    checks["finished_residual_risk_string_fails"] = (
        result.returncode != 0 and "completion_audit.residual_risk must be a list" in (result.stderr + result.stdout)
    )
    if not checks["finished_residual_risk_string_fails"]:
        failures.append("finished completion_audit.residual_risk should require a list")

    structured_residual_risk = base_state()
    structured_residual_risk["completion_audit"]["residual_risk"] = [
        {
            "owner": "operator",
            "class": "external_credentials",
            "summary": "Production deploy requires VM_PUBLIC_IP.",
            "blocks_release": False,
            "unblocks_when": "Operator provides credentials and reruns deploy smoke.",
            "evidence_ref": "completion_audit.verification_evidence[0]",
        }
    ]
    result = run_validator(script, structured_residual_risk)
    checks["structured_residual_risk_passes"] = result.returncode == 0
    if not checks["structured_residual_risk_passes"]:
        failures.append("valid structured residual risk should pass: " + (result.stderr or result.stdout))

    blocking_residual_risk = base_state()
    blocking_residual_risk["completion_audit"]["residual_risk"] = [
        {"owner": "operator", "class": "deployment", "summary": "Blocks release", "blocks_release": True}
    ]
    result = run_validator(script, blocking_residual_risk)
    checks["blocking_residual_risk_with_passed_completion_fails"] = (
        result.returncode != 0
        and "completion_audit.residual_risk blocks_release=true cannot coexist with finished passed completion"
        in (result.stderr + result.stdout)
    )
    if not checks["blocking_residual_risk_with_passed_completion_fails"]:
        failures.append("release-blocking residual risk should not coexist with passed finished completion")

    bad_verification_evidence = base_state()
    bad_verification_evidence["completion_audit"]["verification_evidence"] = "python3 evals/run.sh passed"
    result = run_validator(script, bad_verification_evidence)
    checks["finished_verification_evidence_string_fails"] = (
        result.returncode != 0
        and "completion_audit.verification_evidence must be a non-empty list" in (result.stderr + result.stdout)
    )
    if not checks["finished_verification_evidence_string_fails"]:
        failures.append("finished completion_audit.verification_evidence should require a non-empty list")

    task_view_fields = base_state()
    task_view_fields["tasks"]["task_0"]["task_packet_view_path"] = f"{task_view_fields['run_dir']}/task_packets/task_0.md"
    task_view_fields["tasks"]["task_0"]["task_packet_view_sha256"] = "a" * 64
    result = run_validator(script, task_view_fields)
    checks["task_packet_view_fields_pass"] = result.returncode == 0
    if not checks["task_packet_view_fields_pass"]:
        failures.append("valid task packet view path/hash fields should pass: " + (result.stderr or result.stdout))

    legacy_subagents_on_without_runs = base_state()
    legacy_subagents_on_without_runs["subagents_requested"] = True
    legacy_subagents_on_without_runs["subagent_runs"] = []
    result = run_validator(script, legacy_subagents_on_without_runs)
    checks["legacy_subagents_on_without_runs_passes"] = result.returncode == 0
    if not checks["legacy_subagents_on_without_runs_passes"]:
        failures.append("legacy v2.19 subagents on with no delegated runs should pass")

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

    boundary_valid = run_validator(script, boundary_state())
    checks["boundary_attestation_valid_passes"] = boundary_valid.returncode == 0
    if not checks["boundary_attestation_valid_passes"]:
        failures.append("valid boundary attestation should pass")

    missing_boundary = boundary_state()
    del missing_boundary["subagent_runs"][0]["boundary_attestation"]
    missing_boundary_result = run_validator(script, missing_boundary)
    checks["accepted_subagent_requires_boundary_attestation"] = (
        missing_boundary_result.returncode != 0
        and "boundary_attestation required" in (missing_boundary_result.stderr + missing_boundary_result.stdout)
    )
    if not checks["accepted_subagent_requires_boundary_attestation"]:
        failures.append("accepted subagent should require boundary attestation in boundary schema states")

    mismatch_boundary = boundary_state()
    mismatch_boundary["subagent_runs"][0]["boundary_attestation"] = boundary_attestation(match=False)
    mismatch_result = run_validator(script, mismatch_boundary)
    checks["boundary_mismatch_fails"] = (
        mismatch_result.returncode != 0
        and "worker_git_root must match execution_worktree" in (mismatch_result.stderr + mismatch_result.stdout)
    )
    if not checks["boundary_mismatch_fails"]:
        failures.append("worker git root outside execution worktree should fail")

    source_drift = boundary_state()
    source_drift["subagent_runs"][0]["boundary_attestation"] = boundary_attestation(source_unchanged=False)
    source_drift_result = run_validator(script, source_drift)
    checks["source_workspace_drift_requires_override"] = (
        source_drift_result.returncode != 0
        and "source_workspace_unchanged" in (source_drift_result.stderr + source_drift_result.stdout)
    )
    if not checks["source_workspace_drift_requires_override"]:
        failures.append("source workspace drift should fail without operator override")

    duplicate_final = duplicate_final_attempt_state()
    duplicate_final_result = run_validator(script, duplicate_final)
    checks["duplicate_final_attempts_fail"] = (
        duplicate_final_result.returncode != 0
        and "multiple final accepted subagent attempts" in (duplicate_final_result.stderr + duplicate_final_result.stdout)
    )
    if not checks["duplicate_final_attempts_fail"]:
        failures.append("multiple final accepted attempts for one attempt_group should fail")

    superseded_attempt = duplicate_final_attempt_state()
    superseded_attempt["subagent_runs"][0]["review_status"] = "rejected"
    superseded_attempt["subagent_runs"][0]["accepted_as_final"] = False
    superseded_attempt["subagent_runs"][0]["superseded_by"] = "agent_attempt_2"
    superseded_attempt["tasks"]["task_0"]["subagent_strategy"]["run_ids"] = ["agent_attempt_2"]
    superseded_result = run_validator(script, superseded_attempt)
    checks["superseded_attempt_lineage_passes"] = superseded_result.returncode == 0
    if not checks["superseded_attempt_lineage_passes"]:
        failures.append("rejected superseded attempt plus one final accepted run should pass")

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

    valid_v220 = run_validator(script, v220_state())
    checks["valid_v220_context_state_passes"] = valid_v220.returncode == 0
    if not checks["valid_v220_context_state_passes"]:
        failures.append("valid v2.20 context-intelligence state should pass: " + (valid_v220.stderr or valid_v220.stdout))

    v222 = v220_state()
    v222["agentlens_orchestration_run"] = "agentlens-run-123"
    v222["source_workspace"] = "/tmp/source"
    v222["execution_worktree"] = v222["worktree"]
    v222["delegation_policy"] = {
        "requested_mode": "on",
        "requested_source": "default",
        "explicit_user_delegation_request": False,
        "spawn_policy": "explicit-request-required",
        "effective_mode": "local_fallback",
        "reason": "spawn_agent tool policy requires explicit user delegation intent",
    }
    v222["delegation_capability"] = {
        "schema_version": "1",
        "spawn_policy": "explicit-request-required",
        "explicit_user_delegation_request": False,
        "run_level_effective_mode": "local_fallback",
        "reason": "spawn_agent tool policy requires explicit user delegation intent",
    }
    v222["agentlens_status"] = {
        "schema_version": "1",
        "status": "agentlens_unavailable",
        "blocking": False,
    }
    v222["dispatch_decisions"] = [valid_dispatch_decision()]
    v222["run_quality"] = valid_run_quality()
    v222["run_quality"]["grade"] = "yellow"
    v222["run_quality"]["open_followups"] = ["delegation_policy_expected_local_fallback"]
    v222["run_quality"]["operational_debt"] = {
        "schema_version": "1",
        "followups": ["delegation_policy_expected_local_fallback"],
        "count": 1,
        "blocking": False,
    }
    result = run_validator(script, v222)
    checks["v222_optional_fields_pass"] = result.returncode == 0
    if not checks["v222_optional_fields_pass"]:
        failures.append("valid v2.22 optional fields should pass: " + (result.stderr or result.stdout))

    valid_plan_audit = v220_state()
    valid_plan_audit["agentlens_orchestration_run"] = "agentlens-run-123"
    valid_plan_audit["execution_worktree"] = valid_plan_audit["worktree"]
    valid_plan_audit["run_quality"] = valid_run_quality()
    valid_plan_audit["dispatch_decisions"] = [valid_dispatch_decision()]
    valid_plan_audit["run_quality"]["grade"] = "yellow"
    valid_plan_audit["run_quality"]["open_followups"] = ["plan_executability_fixable_issues"]
    valid_plan_audit["run_quality"]["readiness"]["plan_executability_fixable_issue_count"] = 1
    valid_plan_audit["plan_executability_audit"] = valid_plan_executability_audit()
    result = run_validator(script, valid_plan_audit)
    checks["valid_plan_executability_audit_passes"] = result.returncode == 0
    if not checks["valid_plan_executability_audit_passes"]:
        failures.append("valid plan_executability_audit should pass: " + (result.stderr or result.stdout))

    plan_audit_mismatch = valid_plan_audit
    plan_audit_mismatch["run_quality"]["readiness"]["plan_executability_fixable_issue_count"] = 2
    result = run_validator(script, plan_audit_mismatch)
    checks["plan_executability_summary_mismatch_fails"] = (
        result.returncode != 0
        and "plan_executability_audit fixable count must match run_quality readiness"
        in (result.stderr + result.stdout)
    )
    if not checks["plan_executability_summary_mismatch_fails"]:
        failures.append("plan executability summary mismatch should fail")

    reduced_without_operator = v220_state()
    reduced_without_operator["agentlens_orchestration_run"] = "agentlens-run-123"
    reduced_without_operator["execution_worktree"] = reduced_without_operator["worktree"]
    reduced_without_operator["run_quality"] = valid_run_quality()
    reduced_without_operator["dispatch_decisions"] = [valid_dispatch_decision()]
    reduced_without_operator["plan_executability_audit"] = {
        "path": f"{run_dir()}/plan_executability_audit.json",
        "grade": "yellow",
        "raw_grade": "red",
        "blocking_issue_count": 0,
        "raw_blocking_issue_count": 2,
        "fixable_issue_count": 0,
        "raw_fixable_issue_count": 0,
    }
    result = run_validator(script, reduced_without_operator)
    checks["reduced_raw_blockers_require_operator_evidence"] = (
        result.returncode != 0
        and "plan_executability_audit reduced blocking count requires operator review evidence"
        in (result.stderr + result.stdout)
    )
    if not checks["reduced_raw_blockers_require_operator_evidence"]:
        failures.append("reduced raw blocker count should require operator review evidence")

    reduced_with_operator = reduced_without_operator
    reduced_with_operator["plan_executability_audit"]["operator_reviewed_blocking_issues"] = [
        "task_1:risk_marker_requires_operator_review"
    ]
    reduced_with_operator["plan_executability_audit"]["operator_decision"] = "Proceed after operator review."
    result = run_validator(script, reduced_with_operator)
    checks["reduced_raw_blockers_with_operator_evidence_passes"] = result.returncode == 0
    if not checks["reduced_raw_blockers_with_operator_evidence_passes"]:
        failures.append("reduced raw blocker count with operator review evidence should pass: " + (result.stderr or result.stdout))

    invalid_plan_audit = v220_state()
    invalid_plan_audit["plan_executability_audit"] = {
        "path": "",
        "grade": "purple",
        "blocking_issue_count": -1,
        "fixable_issue_count": "one",
    }
    result = run_validator(script, invalid_plan_audit)
    checks["invalid_plan_executability_audit_fails"] = (
        result.returncode != 0
        and "plan_executability_audit.path must be non-empty" in (result.stderr + result.stdout)
        and "plan_executability_audit.grade must be green, yellow, or red" in (result.stderr + result.stdout)
        and "plan_executability_audit.blocking_issue_count must be a non-negative integer"
        in (result.stderr + result.stdout)
        and "plan_executability_audit.fixable_issue_count must be a non-negative integer"
        in (result.stderr + result.stdout)
    )
    if not checks["invalid_plan_executability_audit_fails"]:
        failures.append("invalid plan_executability_audit should fail")

    blocked_without_blocker = base_state()
    blocked_without_blocker["lifecycle_outcome"] = "blocked"
    blocked_without_blocker["completion_audit"] = None
    blocked_without_blocker["handoff_reason"] = "Need operator input."
    blocked_without_blocker["timestamps"]["completed_at"] = None
    result = run_validator(script, blocked_without_blocker)
    checks["blocked_requires_current_blocker"] = (
        result.returncode != 0 and "blocked outcome requires current_blocker" in (result.stderr + result.stdout)
    )
    if not checks["blocked_requires_current_blocker"]:
        failures.append("blocked state should require current_blocker")

    failed_without_decision = base_state()
    failed_without_decision["lifecycle_outcome"] = "failed"
    failed_without_decision["completion_audit"] = None
    failed_without_decision["handoff_reason"] = "Verification cannot recover."
    failed_without_decision["timestamps"]["completed_at"] = None
    result = run_validator(script, failed_without_decision)
    checks["failed_requires_failure_decision"] = (
        result.returncode != 0 and "failed outcome requires failure_decision" in (result.stderr + result.stdout)
    )
    if not checks["failed_requires_failure_decision"]:
        failures.append("failed state should require failure_decision")

    finished_with_blocker = base_state()
    finished_with_blocker["current_blocker"] = {
        "category": "operator_input_required",
        "summary": "Waiting for approval.",
        "recoverable": True,
        "next_action_kind": "block",
    }
    result = run_validator(script, finished_with_blocker)
    checks["finished_with_current_blocker_fails"] = (
        result.returncode != 0 and "current_blocker must be cleared" in (result.stderr + result.stdout)
    )
    if not checks["finished_with_current_blocker_fails"]:
        failures.append("finished state should not retain current_blocker")

    finished_open_recovery = base_state()
    finished_open_recovery["recovery_attempts"] = [
        {"root_signature": "pytest:timeout", "status": "open", "decision": "retry"}
    ]
    result = run_validator(script, finished_open_recovery)
    checks["finished_open_recovery_fails"] = (
        result.returncode != 0 and "open recovery attempt" in (result.stderr + result.stdout)
    )
    if not checks["finished_open_recovery_fails"]:
        failures.append("finished state should not retain open recovery attempts")

    valid_blocked = base_state()
    valid_blocked["lifecycle_outcome"] = "blocked"
    valid_blocked["completion_audit"] = None
    valid_blocked["handoff_reason"] = "Need operator approval to expand file claims."
    valid_blocked["timestamps"]["completed_at"] = None
    valid_blocked["current_blocker"] = {
        "category": "plan_contract_gap",
        "summary": "File claim expansion requires operator decision.",
        "recoverable": True,
        "next_action_kind": "operator_decision",
    }
    result = run_validator(script, valid_blocked)
    checks["valid_blocked_state_passes"] = result.returncode == 0
    if not checks["valid_blocked_state_passes"]:
        failures.append("valid blocked state with structured blocker should pass: " + (result.stderr or result.stdout))

    valid_hardening_fields = v220_state()
    valid_hardening_fields["cache_strategy"] = {
        "mode": "interactive-default",
        "stable_prefix_policy": "static-first-hot-tail",
        "provider_cache_control": "unavailable",
        "prompt_audit_version": "1",
    }
    valid_hardening_fields["cache_observations"] = [
        {
            "observed_at": "2026-05-19T14:33:00Z",
            "source": "codex-metadata",
            "unit": "task_0",
            "mode": "interactive",
            "model": "gpt-5",
            "input_tokens": 100,
            "cached_read_tokens": None,
            "cached_write_tokens": None,
            "output_tokens": 20,
        }
    ]
    valid_hardening_fields["prompt_audit"] = {
        "last_checked_at": "2026-05-19T14:33:00Z",
        "stable_prefix_hashes": {"templates/fresh-session-prompt.txt": "abc"},
        "stable_prefix_bytes": {"templates/fresh-session-prompt.txt": 100},
        "dynamic_marker_violations": [],
    }
    valid_hardening_fields["graphify_audit"] = {
        "schema_version": "1",
        "graphify_present": True,
        "fresh": True,
        "update_required": False,
        "warnings": [],
        "errors": [],
    }
    valid_hardening_fields["completion_audit"]["verification_evidence"].append(
        {
            "command": "python3 scripts/check_graphify_freshness.py --repo-root $WORKTREE_ABS --update-ran",
            "status": "passed",
            "artifact": "graphify_audit",
        }
    )
    valid_hardening_fields["dispatch_decisions"] = [
        {
            "schema_version": "1",
            "task_id": "task_0",
            "decision": "delegate",
            "reason": "all pre-dispatch prerequisites passed",
            "write_scope": ["docs/example.md"],
            "failed_prerequisites": [],
        }
    ]
    valid_hardening_fields["tasks"]["task_0"]["subagent_strategy"]["reason"] = "all pre-dispatch prerequisites passed"
    result = run_validator(script, valid_hardening_fields)
    checks["valid_hardening_fields_pass"] = result.returncode == 0
    if not checks["valid_hardening_fields_pass"]:
        failures.append("valid cache, graphify, and dispatch fields should pass: " + (result.stderr or result.stdout))

    graphify_error = v220_state()
    graphify_error["graphify_audit"] = {
        "schema_version": "1",
        "graphify_present": True,
        "fresh": False,
        "update_required": True,
        "warnings": [],
        "errors": ["graphify report is stale and update evidence is missing"],
    }
    result = run_validator(script, graphify_error)
    checks["finished_graphify_errors_fail"] = result.returncode != 0 and "graphify_audit.errors" in (
        result.stderr + result.stdout
    )
    if not checks["finished_graphify_errors_fail"]:
        failures.append("finished state with graphify audit errors should fail")

    graphify_without_completion_evidence = v220_state()
    graphify_without_completion_evidence["graphify_audit"] = {
        "schema_version": "1",
        "graphify_present": True,
        "fresh": True,
        "update_required": False,
        "warnings": [],
        "errors": [],
    }
    result = run_validator(script, graphify_without_completion_evidence)
    checks["finished_graphify_requires_completion_evidence"] = result.returncode != 0 and (
        "graphify_audit must be referenced in completion_audit.verification_evidence"
        in (result.stderr + result.stdout)
    )
    if not checks["finished_graphify_requires_completion_evidence"]:
        failures.append("finished state with graphify_audit should reference it in completion audit evidence")

    dispatch_block = v220_state()
    dispatch_block["dispatch_decisions"] = [
        {
            "schema_version": "1",
            "task_id": "task_0",
            "decision": "block",
            "reason": "dirty files overlap delegated write scope",
            "write_scope": ["docs/example.md"],
            "failed_prerequisites": ["dirty_overlap:docs/example.md"],
        }
    ]
    result = run_validator(script, dispatch_block)
    checks["finished_dispatch_block_fails"] = result.returncode != 0 and "block decision" in (
        result.stderr + result.stdout
    )
    if not checks["finished_dispatch_block_fails"]:
        failures.append("finished state with dispatch block decision should fail")

    missing_subagent_strategy = v220_state()
    missing_subagent_strategy["tasks"]["task_0"].pop("subagent_strategy")
    result = run_validator(script, missing_subagent_strategy)
    checks["finished_v220_subagents_on_requires_subagent_strategy"] = (
        result.returncode != 0 and "subagent_strategy" in (result.stderr + result.stdout)
    )
    if not checks["finished_v220_subagents_on_requires_subagent_strategy"]:
        failures.append("finished v2.20 subagents=on task should require a subagent_strategy audit decision")

    local_fallback = v220_state()
    local_fallback["subagent_runs"] = []
    local_fallback["tasks"]["task_0"]["subagent_strategy"] = {
        "mode": "local_fallback",
        "run_ids": [],
        "reason": "No safe disjoint write scope was available after the pre-dispatch checks.",
    }
    result = run_validator(script, local_fallback)
    checks["finished_v220_local_fallback_with_reason_passes"] = result.returncode == 0
    if not checks["finished_v220_local_fallback_with_reason_passes"]:
        failures.append("finished v2.20 local fallback with a reason should pass: " + (result.stderr or result.stdout))

    adaptive_local_fast_path = v220_state()
    adaptive_local_fast_path["agentlens_orchestration_run"] = "agentlens-run-123"
    adaptive_local_fast_path["subagent_runs"] = []
    adaptive_local_fast_path["delegation_policy"] = {
        "requested_mode": "on",
        "requested_source": "default",
        "explicit_user_delegation_request": False,
        "spawn_policy": "available",
        "effective_mode": "local_fallback",
        "reason": "adaptive_policy_local_fast_path_docs_only",
        "policy_kind": "adaptive",
        "safety_gate": "passed",
        "value_gate": "local_fast_path",
        "signals": {
            "declared_file_count": 1,
            "allowed_write_glob_count": 1,
            "packet_budget_status": "green",
            "risk_markers": [],
        },
    }
    adaptive_local_fast_path["run_quality"] = valid_run_quality()
    adaptive_local_fast_path["dispatch_decisions"] = [
        {
            "schema_version": "1",
            "task_id": "task_0",
            "decision": "local_fallback",
            "reason": "adaptive_policy_local_fast_path_docs_only",
            "write_scope": ["docs/example.md"],
            "failed_prerequisites": [],
        }
    ]
    adaptive_local_fast_path["tasks"]["task_0"]["subagent_strategy"] = {
        "mode": "local_fallback",
        "reason": "adaptive_policy_local_fast_path_docs_only",
        "run_ids": [],
    }
    result = run_validator(script, adaptive_local_fast_path)
    checks["finished_adaptive_local_fast_path_passes"] = result.returncode == 0
    if not checks["finished_adaptive_local_fast_path_passes"]:
        failures.append("finished adaptive local fast path should pass: " + (result.stderr or result.stdout))

    advisory_fields = v220_state()
    advisory_fields["delegation_policy"] = {
        "requested_mode": "on",
        "requested_source": "default",
        "explicit_user_delegation_request": False,
        "spawn_policy": "explicit-request-required",
        "effective_mode": "local_fallback",
        "reason": "spawn_agent tool policy requires explicit user delegation intent",
        "policy_kind": "adaptive",
        "safety_gate": "failed",
        "value_gate": "skipped_by_spawn_policy",
        "signals": {
            "declared_file_count": 1,
            "allowed_write_glob_count": 1,
            "write_scope_count": 1,
            "dependency_count": 0,
            "packet_budget_status": "green",
            "estimated_chars": 10,
            "explicit_user_delegation_request": False,
            "risk_markers": [],
            "docs_only": True,
            "low_parallel_value": True,
        },
        "would_have_decision": "local_fallback",
        "would_have_reason": "adaptive_policy_local_fast_path_docs_only",
        "would_have_value_gate": "local_fast_path",
    }
    advisory_fields["agentlens_orchestration_run"] = "agentlens-run-123"
    advisory_fields["execution_worktree"] = advisory_fields["worktree"]
    advisory_fields["run_quality"] = valid_run_quality()
    advisory_fields["run_quality"]["grade"] = "yellow"
    advisory_fields["run_quality"]["open_followups"] = ["delegation_policy_expected_local_fallback"]
    advisory_fields["subagent_runs"] = []
    advisory_fields["dispatch_decisions"] = [
        {
            "schema_version": "1",
            "task_id": "task_0",
            "decision": "local_fallback",
            "reason": "spawn_agent tool policy requires explicit user delegation intent",
            "write_scope": ["docs/example.md"],
            "failed_prerequisites": ["spawn_policy_requires_explicit_user_request"],
        }
    ]
    advisory_fields["tasks"]["task_0"]["subagent_strategy"] = {
        "mode": "local_fallback",
        "reason": "spawn_agent tool policy requires explicit user delegation intent",
        "run_ids": [],
    }
    result = run_validator(script, advisory_fields)
    signals = advisory_fields["delegation_policy"]["signals"]
    checks["delegation_policy_models_explicit_request_fallback_shape"] = (
        result.returncode == 0
        and advisory_fields["delegation_policy"]["would_have_decision"] == "local_fallback"
        and advisory_fields["delegation_policy"]["would_have_value_gate"] == "local_fast_path"
        and advisory_fields["delegation_policy"]["would_have_reason"] == "adaptive_policy_local_fast_path_docs_only"
        and advisory_fields["delegation_policy"]["value_gate"] == "skipped_by_spawn_policy"
        and advisory_fields["delegation_policy"]["safety_gate"] == "failed"
        and signals.get("declared_file_count") == 1
        and signals.get("allowed_write_glob_count") == 1
        and signals.get("write_scope_count") == 1
        and signals.get("dependency_count") == 0
        and signals.get("packet_budget_status") == "green"
        and signals.get("estimated_chars") == 10
        and signals.get("docs_only") is True
        and signals.get("low_parallel_value") is True
    )
    if not checks["delegation_policy_models_explicit_request_fallback_shape"]:
        failures.append("delegation_policy should model the docs-only explicit-request fallback runtime shape")
    checks["delegation_policy_allows_would_have_fields"] = result.returncode == 0
    if not checks["delegation_policy_allows_would_have_fields"]:
        failures.append("delegation_policy should allow optional would-have advisory fields")

    malformed_would_have_decision = advisory_fields.copy()
    malformed_would_have_decision["delegation_policy"] = dict(advisory_fields["delegation_policy"])
    malformed_would_have_decision["delegation_policy"]["would_have_decision"] = "maybe"
    result = run_validator(script, malformed_would_have_decision)
    checks["delegation_policy_rejects_malformed_would_have_decision"] = (
        result.returncode != 0 and "delegation_policy.would_have_decision invalid" in (result.stderr + result.stdout)
    )
    if not checks["delegation_policy_rejects_malformed_would_have_decision"]:
        failures.append("delegation_policy.would_have_decision should reject malformed values")

    malformed_would_have_value_gate = advisory_fields.copy()
    malformed_would_have_value_gate["delegation_policy"] = dict(advisory_fields["delegation_policy"])
    malformed_would_have_value_gate["delegation_policy"]["would_have_value_gate"] = "fastest"
    result = run_validator(script, malformed_would_have_value_gate)
    checks["delegation_policy_rejects_malformed_would_have_value_gate"] = (
        result.returncode != 0 and "delegation_policy.would_have_value_gate invalid" in (result.stderr + result.stdout)
    )
    if not checks["delegation_policy_rejects_malformed_would_have_value_gate"]:
        failures.append("delegation_policy.would_have_value_gate should reject malformed values")

    empty_would_have_reason = advisory_fields.copy()
    empty_would_have_reason["delegation_policy"] = dict(advisory_fields["delegation_policy"])
    empty_would_have_reason["delegation_policy"]["would_have_reason"] = "   "
    result = run_validator(script, empty_would_have_reason)
    checks["delegation_policy_rejects_empty_would_have_reason"] = (
        result.returncode != 0 and "delegation_policy.would_have_reason must be non-empty" in (result.stderr + result.stdout)
    )
    if not checks["delegation_policy_rejects_empty_would_have_reason"]:
        failures.append("delegation_policy.would_have_reason should reject empty values")

    mismatch = v220_state()
    mismatch["subagent_runs"] = []
    mismatch["dispatch_decisions"] = [
        {
            "schema_version": "1",
            "task_id": "task_0",
            "decision": "local_fallback",
            "reason": "acceptance_command_missing",
            "write_scope": ["docs/example.md"],
            "failed_prerequisites": ["acceptance_command_missing"],
        }
    ]
    mismatch["tasks"]["task_0"]["subagent_strategy"] = {
        "mode": "local_fallback",
        "reason": "adaptive_policy_local_fast_path_docs_only",
        "run_ids": [],
    }
    result = run_validator(script, mismatch)
    checks["dispatch_strategy_mismatch_without_override_fails"] = (
        result.returncode != 0 and "subagent_strategy_override" in (result.stderr + result.stdout)
    )
    if not checks["dispatch_strategy_mismatch_without_override_fails"]:
        failures.append("dispatch/strategy mismatch should require override evidence")

    override = mismatch
    override["tasks"]["task_0"]["subagent_strategy_override"] = {
        "from_reason": "acceptance_command_missing",
        "to_reason": "adaptive_policy_local_fast_path_docs_only",
        "changed_at": "2026-05-19T14:34:30Z",
        "evidence": "Operator replaced a stale dry-run dispatch reason after acceptance was added before execution.",
        "operator_decision": "accept override",
    }
    result = run_validator(script, override)
    checks["dispatch_strategy_mismatch_with_override_passes"] = result.returncode == 0
    if not checks["dispatch_strategy_mismatch_with_override_passes"]:
        failures.append("dispatch/strategy override evidence should pass: " + (result.stderr or result.stdout))

    bad_adaptive_reason = v220_state()
    bad_adaptive_reason["subagent_runs"] = []
    bad_adaptive_reason["delegation_policy"] = {
        "requested_mode": "on",
        "requested_source": "default",
        "explicit_user_delegation_request": False,
        "spawn_policy": "available",
        "effective_mode": "local_fallback",
        "reason": "adaptive_policy_local_fast_path_unlisted",
        "policy_kind": "adaptive",
        "safety_gate": "passed",
        "value_gate": "local_fast_path",
        "signals": {},
    }
    bad_adaptive_reason["tasks"]["task_0"]["subagent_strategy"] = {
        "mode": "local_fallback",
        "reason": "adaptive_policy_local_fast_path_unlisted",
        "run_ids": [],
    }
    result = run_validator(script, bad_adaptive_reason)
    checks["finished_unknown_adaptive_reason_fails"] = (
        result.returncode != 0 and "known adaptive local fast path reason" in (result.stderr + result.stdout)
    )
    if not checks["finished_unknown_adaptive_reason_fails"]:
        failures.append("unknown adaptive local fast path reason should fail")

    delegated_without_run = v220_state()
    delegated_without_run["subagent_runs"] = []
    result = run_validator(script, delegated_without_run)
    checks["delegated_strategy_requires_reviewed_subagent_run"] = (
        result.returncode != 0 and "reviewed completed subagent_run" in (result.stderr + result.stdout)
    )
    if not checks["delegated_strategy_requires_reviewed_subagent_run"]:
        failures.append("delegated subagent_strategy should require a reviewed completed subagent_run")

    bad_manifest_path = v220_state()
    bad_manifest_path["spec_manifest_path"] = f"{run_dir()}/wrong.json"
    result = run_validator(script, bad_manifest_path)
    checks["bad_spec_manifest_path_fails"] = result.returncode != 0 and "spec_manifest_path" in (result.stderr + result.stdout)
    if not checks["bad_spec_manifest_path_fails"]:
        failures.append("spec_manifest_path should equal run_dir/spec_manifest.json")

    bad_packet_path = v220_state()
    bad_packet_path["current_task_packet_path"] = f"{run_dir()}/other/task_0.json"
    result = run_validator(script, bad_packet_path)
    checks["current_task_packet_outside_dir_fails"] = (
        result.returncode != 0 and "current_task_packet_path" in (result.stderr + result.stdout)
    )
    if not checks["current_task_packet_outside_dir_fails"]:
        failures.append("current_task_packet_path should live under task_packet_dir")

    bad_decisions = v220_state()
    bad_decisions["decisions_register"] = {"id": "dec_0001"}
    result = run_validator(script, bad_decisions)
    checks["decisions_register_must_be_list"] = result.returncode != 0 and "decisions_register" in (result.stderr + result.stdout)
    if not checks["decisions_register_must_be_list"]:
        failures.append("decisions_register should be a list")

    bad_warning = v220_state()
    bad_warning["preflight_warnings"] = [{"kind": "unknown", "detected_at": "2026-05-19T14:32:00Z"}]
    result = run_validator(script, bad_warning)
    checks["preflight_warning_kind_validated"] = result.returncode != 0 and "preflight_warnings[0].kind" in (result.stderr + result.stdout)
    if not checks["preflight_warning_kind_validated"]:
        failures.append("preflight warning kind should be validated")

    missing_timing = v220_state()
    missing_timing["tasks"]["task_0"]["timing"] = {"started": "2026-05-19T14:31:00Z"}
    result = run_validator(script, missing_timing)
    checks["completed_v220_task_requires_timing"] = result.returncode != 0 and "timing.completed" in (result.stderr + result.stdout)
    if not checks["completed_v220_task_requires_timing"]:
        failures.append("completed v2.20 tasks should require timing.started and timing.completed")

    bad_last_completed = v220_state()
    bad_last_completed["last_completed_task"] = "task_404"
    result = run_validator(script, bad_last_completed)
    checks["last_completed_task_must_exist"] = result.returncode != 0 and "last_completed_task" in (result.stderr + result.stdout)
    if not checks["last_completed_task_must_exist"]:
        failures.append("last_completed_task should reference a task or be null")

    missing_completed_timestamp = base_state()
    missing_completed_timestamp["timestamps"]["completed_at"] = None
    result = run_validator(script, missing_completed_timestamp)
    checks["finished_state_requires_completed_at"] = (
        result.returncode != 0 and "timestamps.completed_at" in (result.stderr + result.stdout)
    )
    if not checks["finished_state_requires_completed_at"]:
        failures.append("finished state should require timestamps.completed_at")

    missing_current_task = base_state()
    missing_current_task["current_task"] = "task_404"
    result = run_validator(script, missing_current_task)
    checks["current_task_must_exist"] = result.returncode != 0 and "current_task" in (result.stderr + result.stdout)
    if not checks["current_task_must_exist"]:
        failures.append("current_task should reference a task when tasks are present")

    payload_out = {"passed": not failures, "checks": checks, "failures": failures}
    print(json.dumps(payload_out, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
