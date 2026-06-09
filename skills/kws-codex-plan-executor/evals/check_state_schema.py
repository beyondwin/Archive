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
    result = run_validator(script, v222)
    checks["v222_optional_fields_pass"] = result.returncode == 0
    if not checks["v222_optional_fields_pass"]:
        failures.append("valid v2.22 optional fields should pass: " + (result.stderr or result.stdout))

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
