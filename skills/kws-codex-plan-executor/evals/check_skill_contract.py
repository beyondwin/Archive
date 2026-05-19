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

    checks = {
        "version_2191": 'version: "2.19.1"' in text,
        "resume_argument": "resume=latest|<state-path>" in invocation,
        "subagents_auto_default": "subagents=auto|on|off" in invocation and "default `auto`" in invocation,
        "subagents_on_is_explicit": "explicitly permits subagents for this run" in invocation
        and "Subagent records are opt-in execution artifacts" in subagents,
        "subagents_auto_requires_user_request": "`subagents=auto` does not by itself authorize spawning" in subagents
        and "Do not spawn\nsubagents when `subagents=auto` without an explicit user request" in text,
        "subagents_on_requires_task_packet": "`subagents=on`" in pre_dispatch
        and "current_task_packet_path" in pre_dispatch
        and "readable" in pre_dispatch,
        "delegated_subagent_context_limited": all(
            token in runtime
            for token in ("task id", "task packet path", "state path", "write scope", "verification expectation")
        ),
        "main_agent_reviews_post_diff_and_state": "post-diff and state" in runtime
        and "before accepting subagent output" in runtime,
        "subagents_not_raw_full_plan_context": "dispatch from task packets, not raw full-plan\ncontext" in text
        and "Do not ask a subagent to infer its write scope from the entire plan" in text,
        "no_subagents_by_default": "Use `spawn_agent` by default" not in runtime
        and "Dispatch subagents by default" not in runtime
        and "subagents 기본값은 on" not in template,
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
        "tdd_scope_not_headless_only": "not a headless-only rule" in normalized and "interactive and headless" in normalized,
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
