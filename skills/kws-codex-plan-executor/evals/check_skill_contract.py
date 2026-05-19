#!/usr/bin/env python3
"""Deterministic contract checks for the executor skill instructions."""

from __future__ import annotations

import argparse
import json
import re
import sys
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
    template_path = skill_dir / "templates" / "fresh-session-prompt.txt"
    headless_schema_path = skill_dir / "templates" / "headless-output-schema.json"
    checklist_path = skill_dir / "references" / "prompt-export-checklist.md"
    execution_path = skill_dir / "references" / "execution-cycle.md"
    headless_path = skill_dir / "references" / "headless-runner.md"
    state_schema_path = skill_dir / "references" / "state-schema.md"
    common_mistakes_path = skill_dir / "references" / "common-mistakes.md"
    learning_path = skill_dir / "references" / "learning-log.md"
    compare_script_path = skill_dir / "scripts" / "compare_agentlens_events.py"
    eval_run_path = skill_dir / "evals" / "run.sh"

    template = template_path.read_text(encoding="utf-8") if template_path.is_file() else ""
    headless_schema = headless_schema_path.read_text(encoding="utf-8") if headless_schema_path.is_file() else ""
    checklist = checklist_path.read_text(encoding="utf-8") if checklist_path.is_file() else ""
    execution = execution_path.read_text(encoding="utf-8") if execution_path.is_file() else ""
    headless = headless_path.read_text(encoding="utf-8") if headless_path.is_file() else ""
    state_schema = state_schema_path.read_text(encoding="utf-8") if state_schema_path.is_file() else ""
    learning = learning_path.read_text(encoding="utf-8") if learning_path.is_file() else ""
    eval_run = eval_run_path.read_text(encoding="utf-8") if eval_run_path.is_file() else ""
    invocation = section(text, "## Invocation", "## Hard Boundary")
    checks: dict[str, bool] = {}
    failures: list[str] = []

    parse_index = execution.find("Parse the plan")
    dirty_index = execution.find("Classify dirty files")
    all_runtime_text = text + execution + headless + template + state_schema
    normalized_runtime_text = re.sub(r"\s+", " ", all_runtime_text)
    unit_manifest_surfaces = (text, execution, headless, template, state_schema)

    expectations = {
        "resume_argument": "resume=latest|<state-path>" in invocation,
        "resume_ambiguity_stop": bool(re.search(r"multiple|ambiguous|둘 이상|여러", text, re.I))
        and "resume" in text,
        "task_contract_before_edits": "No edits before" in text
        and "TASK EXECUTION CONTRACT" in text,
        "validation_matrix": "## Validation Matrix" in text
        and all(token in text for token in ("`interactive`", "`headless`", "`prompt`", "`handoff`")),
        "dirty_classification": all(token in text for token in ("related", "unrelated", "dirty")),
        "files_aliases": all(token in text for token in ("Affected files", "Modified files", "수정 파일")),
        "danger_not_user_option": "danger-full-access" not in invocation
        and "--dangerously-bypass-approvals-and-sandbox" not in invocation,
        "prompt_uses_state_json": ".codex-orchestrator/state.json" in template
        and ".codex-orchestrator/session.json" not in template,
        "checklist_uses_state_json": ".codex-orchestrator/state.json" in checklist
        and ".codex-orchestrator/session.json" not in checklist,
        "prompt_subagents_opt_in": "subagents=on" in template
        and "fresh implementation subagent" not in template,
        "execution_parses_before_dirty_classification": parse_index != -1
        and dirty_index != -1
        and parse_index < dirty_index,
        "headless_runner_prepares_artifact_dir": "mkdir -p" in headless
        and ".codex-orchestrator" in headless,
        "headless_runner_uses_sandbox_argument": "HEADLESS_SANDBOX" in headless
        and "read-only" in headless,
        "headless_prompt_bootstraps_superpowers_tdd": all(
            token in template
            for token in ("using-superpowers", "test-driven-development")
        )
        and all(token in headless for token in ("using-superpowers", "test-driven-development"))
        and all(token in eval_run for token in ("using-superpowers", "test-driven-development")),
        "tdd_scope_not_headless_only": all(
            token in (text + execution + template + headless)
            for token in (
                "not a headless-only rule",
                "interactive and headless",
                "RED evidence",
            )
        ),
        "interactive_execution_bootstraps_superpowers_tdd": all(
            token in execution
            for token in ("using-superpowers", "test-driven-development", "RED evidence")
        ),
        "headless_target_avoids_nested_exec": bool(
            re.search(r"Do not launch\s+another nested `codex exec`", headless)
        )
        and "do not launch another nested codex exec" in eval_run,
        "common_mistakes_reference_valid": "references/common-mistakes.md" not in checklist
        or common_mistakes_path.is_file(),
        "learning_log_reference_exists": learning_path.is_file(),
        # v2.18 cutover (Task 13): the legacy append_learning_event.py and
        # append_run_event.py helpers were deleted. Parity with the historical
        # streams is now validated by scripts/compare_agentlens_events.py.
        "agentlens_compare_script_exists": compare_script_path.is_file(),
        "learning_log_execution_only": "execution-only" in text
        and "interactive" in learning
        and "headless" in learning
        and "prompt" in learning
        and "handoff" in learning
        and "not logging modes" in learning,
        "learning_log_user_local_path": "~/.codex/learning/kws-codex-plan-executor/runs/" in learning
        and "~/.codex/learning/kws-codex-plan-executor/runs/" in template,
        "learning_log_lifecycle": all(
            token in learning for token in ("agentlens event append", "run-close")
        )
        and "kws-cpe.learning." in learning
        and "kws-cpe.learning." in template,
        "per_run_orchestrator_state": ".codex-orchestrator/runs/<run_id>/state.json" in learning
        and ".codex-orchestrator/runs/<run_id>/state.json" in template
        and ".codex-orchestrator/runs/<run_id>/" in headless,
        "learning_events_include_run_identity": all(token in learning for token in ("run_id", "run_dir", "state_path"))
        and all(token in template for token in ("run_id", "run_dir", "state_path")),
        "learning_log_notable_boundaries": all(
            token in learning
            for token in (
                "blocker",
                "error",
                "verification_failure",
                "recurring_issue",
                "user_correction",
                "successful_workaround",
                "completion_learning",
            )
        ),
        "learning_log_privacy_guard": all(
            token in learning
            for token in ("redacted-context", "Do not store full conversation transcripts", "Do not store secrets")
        ),
        "context_snapshot_contract": all(
            token in (text + execution + headless + checklist)
            for token in ("context.json", "context_snapshot_path", "context_basis_hash")
        ),
        "context_health_contract": all(
            token in (text + execution + headless + checklist + template)
            for token in ("context_health", "handoff_ready", "next_action")
        ),
        "completion_audit_contract": all(
            token in (text + execution + headless + checklist)
            for token in ("completion_audit", "prompt_to_artifact_checklist", "verification_evidence")
        ),
        "lifecycle_outcome_contract": all(
            token in (text + execution + headless + checklist)
            for token in ("lifecycle_outcome", "handoff_reason", "finished", "blocked", "failed")
        ),
        "fresh_prompt_new_state_contracts": all(
            token in template
            for token in (
                "context.json",
                "context_snapshot_path",
                "context_basis_hash",
                "completion_audit",
                "prompt_to_artifact_checklist",
                "verification_evidence",
                "lifecycle_outcome",
                "handoff_reason",
            )
        ),
        "high_risk_matrix_contract": all(
            token in (execution + checklist + template)
            for token in ("high-risk verification matrix", "misleading success", "stale state", "hung")
        ),
        "execution_requires_dedicated_worktree": all(
            token in (text + execution + headless + checklist)
            for token in (
                "dedicated non-conflicting `codex/...` git worktree",
                "before any task contract or edits",
            )
        ),
        "worktree_uniqueness_contract": all(
            token in (execution + headless)
            for token in (
                "git worktree list --porcelain",
                "branch name already exists",
                "append the run_id",
            )
        ),
        "no_main_implementation_contract": "Do not implement from `main`" in execution
        and "Do not implement from `main`" in headless,
        "worktree_prompt_export_contract": all(
            token in template
            for token in (
                "dedicated non-conflicting `codex/...` git worktree",
                "TASK EXECUTION CONTRACT",
                "main",
                "git worktree list --porcelain",
                "append the run_id",
            )
        ),
        "unit_manifest_contract": all(
            all(token in surface for token in ("unit_manifest", "allowed_write_globs", "forbidden_write_globs"))
            for surface in unit_manifest_surfaces
        )
        and "finished runs require every completed task to have a valid manifest" in normalized_runtime_text,
        "headless_result_schema_contract": all(
            token in (headless + template + headless_schema)
            for token in (
                "status",
                "run_id",
                "state_path",
                "changed_files",
                "verification",
                "open_gaps",
                "residual_risk",
                "next_action",
            )
        )
        and "templates/headless-output-schema.json" in headless
        and "templates/headless-output-schema.json" in template,
    }

    checks.update(expectations)
    for name, passed in checks.items():
        if not passed:
            failures.append(name)

    payload = {
        "skill": str(skill_path),
        "passed": not failures,
        "checks": checks,
        "failures": failures,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
