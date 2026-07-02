#!/usr/bin/env python3
"""Deterministic contract checks for the executor skill instructions."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def section(text: str, start_heading: str, next_heading: str) -> str:
    start = text.find(start_heading)
    if start == -1:
        return ""
    end = text.find(next_heading, start + len(start_heading))
    return text[start:end if end != -1 else len(text)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill", required=True, help="Path to SKILL.md")
    args = parser.parse_args()

    skill_path = Path(args.skill)
    skill_dir = skill_path.resolve().parent
    text = skill_path.read_text(encoding="utf-8")
    template = (skill_dir / "templates" / "fresh-session-prompt.txt").read_text(encoding="utf-8")
    execution = (skill_dir / "references" / "execution-cycle.md").read_text(encoding="utf-8")
    headless = (skill_dir / "references" / "headless-runner.md").read_text(encoding="utf-8")
    state_schema = (skill_dir / "references" / "state-schema.md").read_text(encoding="utf-8")
    learning = (skill_dir / "references" / "learning-log.md").read_text(encoding="utf-8")
    event_journal = (skill_dir / "references" / "event-journal.md").read_text(encoding="utf-8")
    subagents = (skill_dir / "references" / "subagent-run-store.md").read_text(encoding="utf-8")
    pre_dispatch = (skill_dir / "references" / "pre-dispatch-pipeline.md").read_text(encoding="utf-8")
    plan_executability = (skill_dir / "scripts" / "audit_plan_executability.py").read_text(encoding="utf-8")
    audit_common = (skill_dir / "scripts" / "cpe_audit_common.py").read_text(encoding="utf-8")
    replay = (skill_dir / "scripts" / "normalize_cpe_run.py").read_text(encoding="utf-8")
    user_guide = (skill_dir / "docs" / "user-guide.ko.md").read_text(encoding="utf-8")
    state_logging = (skill_dir / "docs" / "state-and-logging.md").read_text(encoding="utf-8")
    eval_coverage = (skill_dir / "docs" / "eval-coverage-cpe.md").read_text(encoding="utf-8")
    checklist = (skill_dir / "references" / "prompt-export-checklist.md").read_text(encoding="utf-8")
    eval_run = (skill_dir / "evals" / "run.sh").read_text(encoding="utf-8")
    invocation = section(text, "## Invocation", "## Hard Boundary")
    runtime = "\n".join([text, template, execution, headless, state_schema, learning, event_journal, subagents, pre_dispatch])
    normalized = re.sub(r"\s+", " ", runtime)

    banned = [
        ".codex-" + "orchestrator",
        "append_" + "run_event.py",
        "append_" + "learning_event.py",
        "~/.codex/" + "learning",
        "events." + "jsonl",
        "event_" + "journal_path",
        "last_" + "event_seq",
        "latest-state " + "compatibility",
        "backwards-" + "compatible",
    ]

    skill_version = re.search(r'(?m)^[ \t]*version:[ \t]*"(\d+\.\d+\.\d+)"', text)

    checks = {
        "version_parseable_semver": bool(skill_version),
        "resume_argument": "resume=latest|<state-path>" in invocation,
        "subagents_on_default": "subagents=auto|on|off" in invocation and "default `on`" in invocation,
        "subagents_on_is_subagent_first_default": "subagent-first default" in normalized
        and "subagent_strategy" in state_schema
        and "Subagent records are execution artifacts" in subagents,
        "subagents_auto_requires_user_request": "`subagents=auto` does not by itself authorize spawning" in subagents
        and "Do not spawn subagents when `subagents=auto` without an explicit user request" in normalized,
        "subagents_on_requires_task_packet": "`subagents=on`" in pre_dispatch
        and "current_task_packet_path" in pre_dispatch
        and "readable" in pre_dispatch,
        "delegated_subagent_context_limited": all(
            token in runtime
            for token in ("task id", "task packet path", "state path", "write scope", "verification expectation")
        ),
        "main_agent_reviews_post_diff_and_state": "post-diff and state" in runtime
        and "before accepting subagent output" in runtime,
        "subagents_not_raw_full_plan_context": "use task packets, not raw full-plan context" in normalized
        and "Do not ask a subagent to infer its write scope from the entire plan" in normalized,
        "subagents_on_default_documented": "subagents=on" in template
        and "기본값" in template
        and "subagents=off" in template,
        "subagents_off_local_only": "subagents=off" in text and "local-only" in text,
        "worktree_root_contract": "dedicated non-conflicting git worktree under\n`~/.codex/worktrees/`" in text
        or "dedicated non-conflicting git worktree under `~/.codex/worktrees/`" in text,
        "worktree_shape": "~/.codex/worktrees/<run_id>" in runtime
        and "<plan-slug>-<YYYYMMDD-HHMMSS>" in runtime,
        "orchestrator_shape": "~/.codex/orchestrator/<run_id>" in runtime
        and "~/.codex/orchestrator/<run_id>/state.json" in runtime,
        "resume_scans_orchestrator": "~/.codex/orchestrator/*/state.json" in runtime,
        "worktree_contains_only_code": "worktree contains only normal repository files" in text
        and "작업 worktree에는 코드와 일반 git working tree 파일만 둔다" in template,
        "prompt_export_no_artifacts": "Prompt and handoff modes are export-only" in text
        and "Do not create `~/.codex/orchestrator`" in text
        and "worktree, state, context snapshot" in template,
        "task_contract_before_edits": "No edits before" in text and "TASK EXECUTION CONTRACT" in template,
        "files_aliases": all(token in text for token in ("Affected files", "Modified files", "수정 파일")),
        "execution_parses_before_dirty": execution.find("Parse the plan") < execution.find("Classify dirty files"),
        "no_main_implementation_contract": "Do not implement from `main`" in execution and "Do not implement from `main`" in headless,
        "worktree_uniqueness_contract": all(token in runtime for token in ("git worktree list --porcelain", "branch name already exists", "append the run_id")),
        "headless_runner_uses_sandbox_argument": "HEADLESS_SANDBOX" in headless and "read-only" in headless,
        "headless_avoids_nested_exec": "Do not launch another nested `codex exec`" in headless
        and "do not launch another nested codex exec" in eval_run,
        "superpowers_tdd_contract": all(token in runtime for token in ("using-superpowers", "test-driven-development", "RED evidence", "GREEN evidence")),
        "superpowers_compatibility_contract": all(
            token in runtime
            for token in (
                "scripts/audit_superpowers_compatibility.py",
                "thin_stateful_bridge",
                "Superpowers-native execution loop",
                "Prompt, handoff, headless, resume, and inspection remain CPE-owned modes",
            )
        ),
        "tdd_scope_not_headless_only": "not a headless-only rule" in normalized and "interactive and headless" in normalized,
        "skill_path_resolution_guard": all(
            token in normalized
            for token in (
                "Resolve skill paths from the active skill registry/root mapping",
                "Do not hard-code `.system`",
                "classify it as an operator path-resolution error",
            )
        ),
        "graphify_freshness_guard": all(
            token in normalized
            for token in (
                "graphify-out/GRAPH_REPORT.md",
                "Built from commit",
                "git rev-parse HEAD",
                "graphify update .",
                "completion_audit.verification_evidence",
            )
        ),
        "cache_strategy_contract": all(
            token in runtime
            for token in (
                "references/cache-strategy.md",
                "scripts/audit_prompt_cache.py",
                "stable prefix",
                "hot tail",
                "prompt_audit.dynamic_marker_violations",
            )
        ),
        "graphify_audit_contract": all(
            token in runtime
            for token in (
                "scripts/check_graphify_freshness.py",
                "graphify_audit",
                "Built from commit",
                "graphify update .",
            )
        ),
        "plan_executability_audit_contract": all(
            token in runtime
            for token in (
                "audit_plan_executability.py",
                "plan_executability_audit",
                "thin_stateful_bridge",
                "before task contracts or edits",
            )
        ),
        "plan_executability_script_reuses_reason_vocabulary": all(
            token in plan_executability + audit_common
            for token in (
                "adaptive_policy_local_fast_path_docs_only",
                "adaptive_policy_local_fast_path_small_scope",
                "adaptive_policy_local_fast_path_linear_task",
                "adaptive_policy_local_fast_path_low_parallel_value",
                "risk_marker_requires_operator_review",
            )
        ),
        "plan_executability_eval_in_harness": "check_plan_executability_audit.py" in eval_run,
        "run_quality_cleanup_contract": all(
            token in runtime + user_guide + state_logging
            for token in (
                "delegation_policy_expected_local_fallback",
                "delegation_policy_missing_dispatch_evidence",
                "raw_blocking_issue_count",
                "structured residual risk",
                "normalize_cpe_run.py",
                "eval-coverage-cpe.md",
            )
        ),
        "cpe_replay_eval_in_harness": "check_cpe_replay.py" in eval_run
        and "forbidden_patterns" in replay
        and "Normalized replay forbidden patterns" in eval_coverage,
        "korean_user_guide_mentions_readiness_summary": "readiness summary" in user_guide
        and "plan_executability_audit" in user_guide,
        "preflight_dispatch_contract": all(
            token in runtime
            for token in (
                "scripts/preflight_dispatch.py",
                "delegate",
                "local_fallback",
                "block",
                "dispatch_decisions",
            )
        ),
        "context_snapshot_contract": all(token in runtime + checklist for token in ("context.json", "context_snapshot_path", "context_basis_hash")),
        "context_health_contract": all(token in runtime + checklist for token in ("context_health", "handoff_ready", "next_action")),
        "completion_audit_contract": all(token in runtime + checklist for token in ("completion_audit", "prompt_to_artifact_checklist", "verification_evidence")),
        "lifecycle_outcome_contract": all(token in runtime + checklist for token in ("lifecycle_outcome", "handoff_reason", "finished", "blocked", "failed")),
        "unit_manifest_contract": all(token in runtime for token in ("unit_manifest", "allowed_write_globs", "forbidden_write_globs"))
        and "finished runs require every completed task to have a valid" in normalized,
        "learning_log_execution_only": "execution-only" in learning
        and "interactive" in learning
        and "headless" in learning
        and "prompt" in learning
        and "handoff" in learning
        and "not logging modes" in learning,
        "learning_log_lifecycle": all(token in learning for token in ("agentlens event append", "run-close", "kws-cpe.learning.")),
        "agentlens_outcome_mapping": all(
            token in learning
            for token in (
                "finished -> success",
                "blocked -> partial",
                "failed -> failed",
                "cancelled -> cancelled",
            )
        ),
        "agentlens_replay_contract": "kws-cpe.<event>" in event_journal and "State remains authoritative" in event_journal,
        "learning_events_include_redacted_run_identity": all(
            token in learning + event_journal for token in ("run_id", "run_dir_ref", "state_path_ref")
        )
        and "absolute home paths" in learning
        and "absolute home paths" in event_journal,
        "learning_privacy_guard": all(token in learning for token in ("redacted-context", "Do not store full conversation transcripts", "Do not store secrets")),
        "high_risk_matrix_contract": all(token in template for token in ("high-risk verification matrix", "misleading success", "stale state", "hung")),
        "headless_result_schema_contract": all(token in runtime for token in ("status", "run_id", "state_path", "summary", "changed_files", "verification", "open_gaps", "residual_risk", "next_action")),
        "headless_sandbox_template_mapping": "headless_sandbox: {{HEADLESS_SANDBOX}}" in template
        and "HEADLESS_SANDBOX" in template,
        "handoff_checkpoint_handoff_only": "HANDOFF CHECKPOINT:\n{{HANDOFF_CHECKPOINT}}" not in template
        and "HANDOFF CHECKPOINT" in text,
        "legacy_runtime_removed": not any(token in runtime for token in banned),
        "removed_scripts_absent": not (skill_dir / "scripts" / ("compare_" + "agentlens_events.py")).exists()
        and not (skill_dir / "scripts" / ("check_" + "learning_log_health.py")).exists(),
    }

    failures = [name for name, passed in checks.items() if not passed]
    payload = {"skill": str(skill_path), "passed": not failures, "checks": checks, "failures": failures}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
