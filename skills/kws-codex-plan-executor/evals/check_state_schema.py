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
        "event_journal_path": ".codex-orchestrator/runs/20260513T000000Z-archive-codex-example-abcdef0-a1b2c3/events.jsonl",
        "last_event_seq": 1,
        "context_health": {
            "status": "green",
            "last_checked_at": "2026-05-14T10:00:00Z",
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
        "tasks": {
            "task_0": {
                "status": "pending",
                "risk": "low",
                "files_declared": ["docs/example.md"],
                "contract": dict(REQUIRED_CONTRACT),
                "unit_manifest": unit_manifest(),
                "review_retries": 0,
                "verifier_retries": 0,
            }
        },
        "timestamps": {
            "started_at": "2026-05-14T09:00:00Z",
            "updated_at": "2026-05-14T10:00:00Z",
            "completed_at": "2026-05-14T10:00:00Z",
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
        "merged_at": "2026-05-14T09:45:00Z",
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
        failures.append("valid state with task contract should pass")
    checks["valid_unit_manifest_passes"] = valid.returncode == 0
    if not checks["valid_unit_manifest_passes"]:
        failures.append("valid unit_manifest should pass")

    no_subagents_requested = base_state()
    no_subagents_requested["subagents_requested"] = False
    no_subagents_requested["subagent_runs"] = []
    no_subagents = run_validator(script, no_subagents_requested)
    checks["subagents_off_without_runs_passes"] = no_subagents.returncode == 0
    if not checks["subagents_off_without_runs_passes"]:
        failures.append("subagents off with no subagent_runs should pass")

    completed_subagent = base_state()
    completed_subagent["subagents_requested"] = True
    completed_subagent["subagent_runs"] = [completed_subagent_run()]
    completed_subagent_result = run_validator(script, completed_subagent)
    checks["completed_reviewed_subagent_passes"] = completed_subagent_result.returncode == 0
    if not checks["completed_reviewed_subagent_passes"]:
        failures.append("completed reviewed subagent record should pass")

    subagent_without_opt_in = base_state()
    subagent_without_opt_in["subagent_runs"] = [completed_subagent_run()]
    subagent_without_opt_in_result = run_validator(script, subagent_without_opt_in)
    checks["subagent_runs_without_opt_in_fails"] = (
        subagent_without_opt_in_result.returncode != 0
        and "subagent_runs requires subagents_requested=true" in (
            subagent_without_opt_in_result.stderr + subagent_without_opt_in_result.stdout
        )
    )
    if not checks["subagent_runs_without_opt_in_fails"]:
        failures.append("subagent_runs should require subagents_requested=true")

    completed_subagent_missing_changed_files = base_state()
    completed_subagent_missing_changed_files["subagents_requested"] = True
    missing_changed_run = completed_subagent_run()
    del missing_changed_run["changed_files"]
    completed_subagent_missing_changed_files["subagent_runs"] = [missing_changed_run]
    missing_changed_result = run_validator(script, completed_subagent_missing_changed_files)
    checks["completed_subagent_missing_changed_files_fails"] = (
        missing_changed_result.returncode != 0
        and "changed_files" in (missing_changed_result.stderr + missing_changed_result.stdout)
    )
    if not checks["completed_subagent_missing_changed_files_fails"]:
        failures.append("completed subagent record missing changed_files should fail")

    finished_unreviewed_subagent = base_state()
    finished_unreviewed_subagent["subagents_requested"] = True
    unreviewed_run = completed_subagent_run()
    unreviewed_run["review_status"] = "unreviewed"
    finished_unreviewed_subagent["subagent_runs"] = [unreviewed_run]
    unreviewed_result = run_validator(script, finished_unreviewed_subagent)
    checks["finished_unreviewed_subagent_fails"] = (
        unreviewed_result.returncode != 0
        and "review_status=unreviewed" in (unreviewed_result.stderr + unreviewed_result.stdout)
    )
    if not checks["finished_unreviewed_subagent_fails"]:
        failures.append("finished run with unreviewed subagent result should fail")

    finished_running_subagent = base_state()
    finished_running_subagent["subagents_requested"] = True
    running_run = completed_subagent_run()
    running_run["status"] = "running"
    running_run["review_status"] = "unreviewed"
    running_run["changed_files"] = []
    finished_running_subagent["subagent_runs"] = [running_run]
    running_result = run_validator(script, finished_running_subagent)
    checks["finished_running_subagent_fails"] = (
        running_result.returncode != 0
        and "running subagent" in (running_result.stderr + running_result.stdout)
    )
    if not checks["finished_running_subagent_fails"]:
        failures.append("finished run with running subagent should fail")

    overlapping_subagent_without_rationale = base_state()
    overlapping_subagent_without_rationale["subagents_requested"] = True
    overlapping_run = completed_subagent_run()
    overlapping_run["write_scope"] = ["docs/example.md"]
    overlapping_run["changed_files"] = ["docs/example.md"]
    overlapping_subagent_without_rationale["subagent_runs"] = [overlapping_run]
    overlapping_result = run_validator(script, overlapping_subagent_without_rationale)
    checks["subagent_current_task_overlap_without_rationale_fails"] = (
        overlapping_result.returncode != 0
        and "overlap_rationale" in (overlapping_result.stderr + overlapping_result.stdout)
    )
    if not checks["subagent_current_task_overlap_without_rationale_fails"]:
        failures.append("subagent write_scope overlapping current task should require overlap_rationale")

    overlapping_subagent_with_rationale = base_state()
    overlapping_subagent_with_rationale["subagents_requested"] = True
    overlapping_allowed_run = completed_subagent_run()
    overlapping_allowed_run["write_scope"] = ["docs/example.md"]
    overlapping_allowed_run["changed_files"] = ["docs/example.md"]
    overlapping_allowed_run["overlap_rationale"] = "Parent task delegated one declared docs file and will review before merge."
    overlapping_subagent_with_rationale["subagent_runs"] = [overlapping_allowed_run]
    overlapping_allowed_result = run_validator(script, overlapping_subagent_with_rationale)
    checks["subagent_current_task_overlap_with_rationale_passes"] = overlapping_allowed_result.returncode == 0
    if not checks["subagent_current_task_overlap_with_rationale_passes"]:
        failures.append("subagent write_scope overlapping current task should pass with overlap_rationale")

    valid_observation = base_state()
    valid_observation["command_observations"] = [valid_command_observation()]
    valid_observation_result = run_validator(script, valid_observation)
    checks["valid_command_observation_passes"] = valid_observation_result.returncode == 0
    if not checks["valid_command_observation_passes"]:
        failures.append("valid command_observation should pass")

    invalid_observation_category = base_state()
    invalid_category = valid_command_observation()
    invalid_category["category"] = "mystery"
    invalid_observation_category["command_observations"] = [invalid_category]
    invalid_observation_category_result = run_validator(script, invalid_observation_category)
    checks["invalid_command_observation_category_fails"] = (
        invalid_observation_category_result.returncode != 0
        and "command_observations[0].category" in (
            invalid_observation_category_result.stderr + invalid_observation_category_result.stdout
        )
    )
    if not checks["invalid_command_observation_category_fails"]:
        failures.append("invalid command_observation category should fail")

    missing_observation_fields = base_state()
    missing_fields = valid_command_observation()
    del missing_fields["evidence"]
    missing_observation_fields["command_observations"] = [missing_fields]
    missing_observation_fields_result = run_validator(script, missing_observation_fields)
    checks["missing_command_observation_fields_fails"] = (
        missing_observation_fields_result.returncode != 0
        and "command_observations[0] missing field evidence" in (
            missing_observation_fields_result.stderr + missing_observation_fields_result.stdout
        )
    )
    if not checks["missing_command_observation_fields_fails"]:
        failures.append("command_observation missing required fields should fail")

    unknown_observation_without_risk = base_state()
    unknown_without_risk = valid_command_observation()
    unknown_without_risk["category"] = "unknown"
    unknown_observation_without_risk["command_observations"] = [unknown_without_risk]
    unknown_without_risk_result = run_validator(script, unknown_observation_without_risk)
    checks["finished_unknown_observation_without_residual_risk_fails"] = (
        unknown_without_risk_result.returncode != 0
        and "unknown command observation" in (
            unknown_without_risk_result.stderr + unknown_without_risk_result.stdout
        )
    )
    if not checks["finished_unknown_observation_without_residual_risk_fails"]:
        failures.append("finished unknown command_observation should require completion_audit residual_risk")

    unknown_observation_with_risk = base_state()
    unknown_with_risk = valid_command_observation()
    unknown_with_risk["category"] = "unknown"
    unknown_observation_with_risk["command_observations"] = [unknown_with_risk]
    unknown_observation_with_risk["completion_audit"]["residual_risk"] = [
        "Command pnpm test had bounded evidence but final category remained unknown."
    ]
    unknown_with_risk_result = run_validator(script, unknown_observation_with_risk)
    checks["finished_unknown_observation_with_residual_risk_passes"] = unknown_with_risk_result.returncode == 0
    if not checks["finished_unknown_observation_with_residual_risk_passes"]:
        failures.append("finished unknown command_observation should pass when residual_risk mentions command")

    invalid_unit_type = base_state()
    invalid_unit_type["tasks"]["task_0"]["unit_manifest"]["unit_type"] = "mystery"
    invalid_unit_type_result = run_validator(script, invalid_unit_type)
    checks["invalid_unit_type_fails"] = (
        invalid_unit_type_result.returncode != 0
        and "unit_manifest.unit_type" in (invalid_unit_type_result.stderr + invalid_unit_type_result.stdout)
    )
    if not checks["invalid_unit_type_fails"]:
        failures.append("unknown unit_manifest.unit_type should fail")

    invalid_tool_policy = base_state()
    invalid_tool_policy["tasks"]["task_0"]["unit_manifest"]["tool_policy"] = "admin"
    invalid_tool_policy_result = run_validator(script, invalid_tool_policy)
    checks["invalid_tool_policy_fails"] = (
        invalid_tool_policy_result.returncode != 0
        and "unit_manifest.tool_policy" in (invalid_tool_policy_result.stderr + invalid_tool_policy_result.stdout)
    )
    if not checks["invalid_tool_policy_fails"]:
        failures.append("unknown unit_manifest.tool_policy should fail")

    finished_missing_manifest = base_state()
    finished_missing_manifest["tasks"]["task_0"]["status"] = "completed"
    del finished_missing_manifest["tasks"]["task_0"]["unit_manifest"]
    finished_missing_manifest_result = run_validator(script, finished_missing_manifest)
    checks["finished_missing_unit_manifest_for_completed_task_fails"] = (
        finished_missing_manifest_result.returncode != 0
        and "unit_manifest is required" in (finished_missing_manifest_result.stderr + finished_missing_manifest_result.stdout)
    )
    if not checks["finished_missing_unit_manifest_for_completed_task_fails"]:
        failures.append("finished completed task missing unit_manifest should fail")

    implementation_without_write_globs = base_state()
    implementation_without_write_globs["tasks"]["task_0"]["unit_manifest"]["allowed_write_globs"] = []
    implementation_without_write_globs_result = run_validator(script, implementation_without_write_globs)
    checks["implementation_manifest_without_allowed_write_globs_fails"] = (
        implementation_without_write_globs_result.returncode != 0
        and "requires allowed_write_globs" in (
            implementation_without_write_globs_result.stderr + implementation_without_write_globs_result.stdout
        )
    )
    if not checks["implementation_manifest_without_allowed_write_globs_fails"]:
        failures.append("implementation unit_manifest without allowed_write_globs should fail")

    readonly_with_write_globs = base_state()
    readonly_with_write_globs["tasks"]["task_0"]["unit_manifest"]["tool_policy"] = "read-only"
    readonly_with_write_globs_result = run_validator(script, readonly_with_write_globs)
    checks["read_only_manifest_with_write_globs_fails"] = (
        readonly_with_write_globs_result.returncode != 0
        and "read-only unit_manifest" in (readonly_with_write_globs_result.stderr + readonly_with_write_globs_result.stdout)
    )
    if not checks["read_only_manifest_with_write_globs_fails"]:
        failures.append("read-only unit_manifest with write globs should fail")

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

    missing_context_health = base_state()
    del missing_context_health["context_health"]
    missing_context_health_result = run_validator(script, missing_context_health)
    checks["missing_context_health_fails"] = (
        missing_context_health_result.returncode != 0
        and "context_health" in (missing_context_health_result.stderr + missing_context_health_result.stdout)
    )
    if not checks["missing_context_health_fails"]:
        failures.append("interactive state after preflight should include context_health")

    invalid_context_health_status = base_state()
    invalid_context_health_status["context_health"]["status"] = "okay"
    invalid_context_health_status_result = run_validator(script, invalid_context_health_status)
    checks["invalid_context_health_status_fails"] = (
        invalid_context_health_status_result.returncode != 0
        and "context_health.status" in (
            invalid_context_health_status_result.stderr + invalid_context_health_status_result.stdout
        )
    )
    if not checks["invalid_context_health_status_fails"]:
        failures.append("context_health.status should reject invalid values")

    finished_context_not_handoff_ready = base_state()
    finished_context_not_handoff_ready["context_health"]["handoff_ready"] = False
    finished_context_not_handoff_ready_result = run_validator(script, finished_context_not_handoff_ready)
    checks["finished_context_not_handoff_ready_fails"] = (
        finished_context_not_handoff_ready_result.returncode != 0
        and "context_health.handoff_ready" in (
            finished_context_not_handoff_ready_result.stderr + finished_context_not_handoff_ready_result.stdout
        )
    )
    if not checks["finished_context_not_handoff_ready_fails"]:
        failures.append("finished lifecycle outcome should require context_health.handoff_ready")

    finished_missing_context_health_checked_at = base_state()
    finished_missing_context_health_checked_at["context_health"]["last_checked_at"] = None
    finished_missing_context_health_checked_at_result = run_validator(script, finished_missing_context_health_checked_at)
    checks["finished_missing_context_health_checked_at_fails"] = (
        finished_missing_context_health_checked_at_result.returncode != 0
        and "context_health.last_checked_at" in (
            finished_missing_context_health_checked_at_result.stderr
            + finished_missing_context_health_checked_at_result.stdout
        )
    )
    if not checks["finished_missing_context_health_checked_at_fails"]:
        failures.append("finished lifecycle outcome should require context_health.last_checked_at")

    finished_stale_context_health_timestamp = base_state()
    finished_stale_context_health_timestamp["context_health"]["last_checked_at"] = "2026-05-14T09:59:59Z"
    finished_stale_context_health_timestamp_result = run_validator(script, finished_stale_context_health_timestamp)
    checks["finished_stale_context_health_timestamp_fails"] = (
        finished_stale_context_health_timestamp_result.returncode != 0
        and "context_health.last_checked_at must not be older than timestamps.updated_at"
        in (
            finished_stale_context_health_timestamp_result.stderr
            + finished_stale_context_health_timestamp_result.stdout
        )
    )
    if not checks["finished_stale_context_health_timestamp_fails"]:
        failures.append("finished lifecycle outcome should reject stale context_health.last_checked_at")

    intermediate_stale_context_health_timestamp = base_state()
    intermediate_stale_context_health_timestamp["lifecycle_outcome"] = None
    intermediate_stale_context_health_timestamp["completion_audit"] = None
    intermediate_stale_context_health_timestamp["context_health"]["last_checked_at"] = "2026-05-14T09:59:59Z"
    intermediate_stale = run_validator(script, intermediate_stale_context_health_timestamp)
    checks["intermediate_stale_context_health_timestamp_passes"] = intermediate_stale.returncode == 0
    if not checks["intermediate_stale_context_health_timestamp_passes"]:
        failures.append("stale context_health timestamp should be non-blocking before terminal finished outcome")

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

    finished_missing_event_journal_path = base_state()
    del finished_missing_event_journal_path["event_journal_path"]
    missing_journal_path = run_validator(script, finished_missing_event_journal_path)
    checks["finished_missing_event_journal_path_fails"] = (
        missing_journal_path.returncode != 0 and "event_journal_path" in (
            missing_journal_path.stderr + missing_journal_path.stdout
        )
    )
    if not checks["finished_missing_event_journal_path_fails"]:
        failures.append("finished lifecycle outcome should require event_journal_path")

    finished_wrong_event_journal_path = base_state()
    finished_wrong_event_journal_path["event_journal_path"] = ".codex-orchestrator/events.jsonl"
    wrong_journal_path = run_validator(script, finished_wrong_event_journal_path)
    checks["finished_wrong_event_journal_path_fails"] = (
        wrong_journal_path.returncode != 0 and "event_journal_path must be" in (
            wrong_journal_path.stderr + wrong_journal_path.stdout
        )
    )
    if not checks["finished_wrong_event_journal_path_fails"]:
        failures.append("finished lifecycle outcome should require matching event_journal_path")

    finished_stale_last_event_seq = base_state()
    finished_stale_last_event_seq["last_event_seq"] = 0
    stale_event_seq = run_validator(script, finished_stale_last_event_seq)
    checks["finished_stale_last_event_seq_fails"] = (
        stale_event_seq.returncode != 0 and "last_event_seq" in (stale_event_seq.stderr + stale_event_seq.stdout)
    )
    if not checks["finished_stale_last_event_seq_fails"]:
        failures.append("finished lifecycle outcome should require positive last_event_seq")

    finished_open_carried_acceptance = base_state()
    finished_open_carried_acceptance["tasks"]["task_0"]["carried_acceptance"] = {
        "status": "open",
        "metric": "front index chunk size",
        "baseline_value": "208.78 kB after task_5",
        "current_value": "221.68 kB after task_6",
        "reason": "Host feature barrel remains statically reachable until task_7.",
        "depends_on_task": "task_7",
        "next_action": "Resolve host barrel coupling and rerun pnpm --dir front build.",
    }
    open_carried = run_validator(script, finished_open_carried_acceptance)
    checks["finished_open_carried_acceptance_fails"] = (
        open_carried.returncode != 0 and "open carried_acceptance" in (open_carried.stderr + open_carried.stdout)
    )
    if not checks["finished_open_carried_acceptance_fails"]:
        failures.append("open carried_acceptance is not allowed for lifecycle_outcome=finished")

    finished_resolved_carried_acceptance = base_state()
    finished_resolved_carried_acceptance["tasks"]["task_0"]["carried_acceptance"] = {
        "status": "resolved",
        "metric": "front index chunk size",
        "baseline_value": "208.78 kB after task_5",
        "current_value": "198.12 kB after task_7",
        "reason": "Final bundle metric improved below the carried baseline.",
        "depends_on_task": "task_7",
        "next_action": "No follow-up; completion audit contains final bundle evidence.",
    }
    finished_resolved_carried_acceptance["completion_audit"]["verification_evidence"].append(
        {"metric": "front index chunk size", "status": "passed", "value": "198.12 kB"}
    )
    resolved_carried = run_validator(script, finished_resolved_carried_acceptance)
    checks["finished_resolved_carried_acceptance_passes"] = resolved_carried.returncode == 0
    if not checks["finished_resolved_carried_acceptance_passes"]:
        failures.append("resolved carried_acceptance should pass for lifecycle_outcome=finished")

    intermediate_open_carried_acceptance = base_state()
    intermediate_open_carried_acceptance["lifecycle_outcome"] = None
    intermediate_open_carried_acceptance["completion_audit"] = None
    intermediate_open_carried_acceptance["tasks"]["task_0"]["carried_acceptance"] = dict(
        finished_open_carried_acceptance["tasks"]["task_0"]["carried_acceptance"]
    )
    intermediate_open = run_validator(script, intermediate_open_carried_acceptance)
    checks["intermediate_open_carried_acceptance_passes"] = intermediate_open.returncode == 0
    if not checks["intermediate_open_carried_acceptance_passes"]:
        failures.append("open carried_acceptance should pass before terminal finished outcome")

    method_required_without_evidence = base_state()
    method_required_without_evidence["method_audit"] = {
        "required": ["test-driven-development"],
        "applied": [],
        "missing": [],
        "waived": [],
    }
    method_missing = run_validator(script, method_required_without_evidence)
    checks["method_required_without_evidence_fails"] = (
        method_missing.returncode != 0
        and "required method test-driven-development" in (method_missing.stderr + method_missing.stdout)
    )
    if not checks["method_required_without_evidence_fails"]:
        failures.append("required method test-driven-development has no applied or waived evidence")

    tdd_green_only = base_state()
    tdd_green_only["method_audit"] = {
        "required": ["test-driven-development"],
        "applied": [
            {
                "skill": "test-driven-development",
                "phase": "implementation",
                "status": "applied",
                "evidence_refs": ["tasks.task_0.green_evidence"],
                "summary": "GREEN passed after implementation.",
            }
        ],
        "missing": [],
        "waived": [],
    }
    tdd_green_only_result = run_validator(script, tdd_green_only)
    checks["method_tdd_requires_red_and_green_fails"] = (
        tdd_green_only_result.returncode != 0
        and "test-driven-development requires RED and GREEN evidence references"
        in (tdd_green_only_result.stderr + tdd_green_only_result.stdout)
    )
    if not checks["method_tdd_requires_red_and_green_fails"]:
        failures.append("test-driven-development requires RED and GREEN evidence references")

    review_without_findings = base_state()
    review_without_findings["method_audit"] = {
        "required": ["review"],
        "applied": [
            {
                "skill": "review",
                "phase": "review",
                "status": "applied",
                "evidence_refs": ["review.summary"],
                "summary": "Review completed.",
            }
        ],
        "missing": [],
        "waived": [],
    }
    review_without_findings_result = run_validator(script, review_without_findings)
    checks["method_review_requires_findings_fails"] = (
        review_without_findings_result.returncode != 0
        and "review method requires findings or residual-risk evidence"
        in (review_without_findings_result.stderr + review_without_findings_result.stdout)
    )
    if not checks["method_review_requires_findings_fails"]:
        failures.append("review method requires findings or residual-risk evidence")

    docs_waived_tdd = base_state()
    docs_waived_tdd["method_audit"] = {
        "required": ["test-driven-development"],
        "applied": [],
        "missing": [],
        "waived": [
            {
                "skill": "test-driven-development",
                "phase": "implementation",
                "reason": "Docs-only planning change with no behavior implementation.",
            }
        ],
    }
    docs_waived_tdd_result = run_validator(script, docs_waived_tdd)
    checks["method_docs_tdd_waiver_passes"] = docs_waived_tdd_result.returncode == 0
    if not checks["method_docs_tdd_waiver_passes"]:
        failures.append("docs-only run with TDD waiver and reason should pass")

    complete_method_audit = base_state()
    complete_method_audit["method_audit"] = {
        "required": [
            "using-superpowers",
            "test-driven-development",
            "verification-before-completion",
            "review",
        ],
        "applied": [
            {
                "skill": "using-superpowers",
                "phase": "pre-implementation",
                "status": "applied",
                "evidence_refs": ["tasks.task_0.contract"],
                "summary": "Skill gate acknowledged before edits.",
            },
            {
                "skill": "test-driven-development",
                "phase": "implementation",
                "status": "applied",
                "evidence_refs": ["tasks.task_0.red_evidence", "tasks.task_0.green_evidence"],
                "summary": "RED failed before implementation; GREEN passed after fix.",
            },
            {
                "skill": "verification-before-completion",
                "phase": "verification",
                "status": "applied",
                "evidence_refs": ["completion_audit.verification_evidence"],
                "summary": "Completion claimed after recorded verification.",
            },
            {
                "skill": "review",
                "phase": "review",
                "status": "applied",
                "evidence_refs": ["review.findings", "review.residual_risk"],
                "summary": "Review completed with no blocking findings.",
            },
        ],
        "missing": [],
        "waived": [],
    }
    complete_method_audit_result = run_validator(script, complete_method_audit)
    checks["method_complete_audit_passes"] = complete_method_audit_result.returncode == 0
    if not checks["method_complete_audit_passes"]:
        failures.append("complete method audit with evidence should pass")

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
