#!/usr/bin/env python3
"""Skill contract checks for kws-claude-multi-agent-executor.

Verifies that SKILL.md + references + scripts collectively wire the v2.8
learning-log behavior and the review-side superpowers Skill invocations.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REVIEW_SIDE_SKILL_CALLS = {
    "references/plan-reviewer-prompt.md": 'Skill("superpowers:writing-plans")',
    "references/reviewer-prompt.md": 'Skill("superpowers:requesting-code-review")',
    "references/verifier-prompt.md": 'Skill("superpowers:verification-before-completion")',
}

EVENT_TYPES = [
    "blocker",
    "error",
    "verification_failure",
    "reviewer_warn_or_fail",
    "escalation",
    "recurring_issue",
    "user_correction",
    "parallel_dispatch_failure",
    "successful_workaround",
    "completion_learning",
]

PRIVACY_PHRASES = [
    "Do not store secrets",
    "Do not store full conversation transcripts",
    "absolute home path",
    "absolute worktree path",
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skill", required=True, help="Path to SKILL.md")
    args = parser.parse_args()

    skill_path = Path(args.skill).expanduser().resolve()
    if not skill_path.is_file():
        print(json.dumps({"passed": False, "error": f"SKILL.md not found at {skill_path}"}))
        return 1
    skill_dir = skill_path.parent

    skill_text = skill_path.read_text(encoding="utf-8")

    learning_log_md = skill_dir / "references" / "learning-log.md"
    learning_log_text = learning_log_md.read_text(encoding="utf-8") if learning_log_md.is_file() else ""

    helper = skill_dir / "scripts" / "append_learning_event.py"

    checks: dict[str, bool] = {}
    failures: list[str] = []

    def record(name: str, ok: bool, msg: str) -> None:
        checks[name] = ok
        if not ok:
            failures.append(msg)

    # ---- learning-log artifact existence ----
    record("learning_log_reference_exists", learning_log_md.is_file(),
           "references/learning-log.md must exist")
    record("learning_log_helper_exists", helper.is_file(),
           "scripts/append_learning_event.py must exist")

    # ---- SKILL.md mentions execution-only learning-log behavior ----
    record(
        "skill_md_mentions_learning_log",
        all(token in skill_text for token in [
            "MAE_LEARNING_RUN_ID",
            "init-run",
            "append",
            "close-run",
            "references/learning-log.md",
        ]),
        "SKILL.md must reference MAE_LEARNING_RUN_ID + init-run/append/close-run + learning-log.md",
    )

    record(
        "skill_md_describes_exit_paths",
        all(token in skill_text for token in [
            "outcome=success",
            "outcome=blocked",
            "outcome=aborted",
        ]),
        "SKILL.md must describe close-run on success/blocked/aborted exit paths",
    )

    record(
        "skill_md_describes_resume_chain_handoff",
        all(token in skill_text for token in [
            "append-session-id",
            "Resume Chain",
        ]),
        "SKILL.md must describe append-session-id in Resume Chain handoff",
    )

    # ---- learning-log.md content ----
    if learning_log_md.is_file():
        record(
            "learning_log_event_types",
            all(t in learning_log_text for t in EVENT_TYPES),
            f"learning-log.md must mention all 10 event types ({', '.join(EVENT_TYPES)})",
        )
        record(
            "learning_log_privacy_guard",
            all(p in learning_log_text for p in PRIVACY_PHRASES),
            "learning-log.md must include privacy phrases: " + ", ".join(PRIVACY_PHRASES),
        )
        record(
            "learning_log_per_run_path",
            "~/.claude/learning/kws-claude-multi-agent-executor/runs/" in learning_log_text,
            "learning-log.md must document the per-run path",
        )
        record(
            "learning_log_helper_subcommands",
            all(t in learning_log_text for t in ["init-run", "append", "close-run", "append-session-id"]),
            "learning-log.md must mention all 4 helper subcommands",
        )
        record(
            "learning_log_candidate_file_contract",
            "<worktree>/.orchestrator/learning_events/" in learning_log_text
            and ("single-writer" in learning_log_text.lower() or "single writer" in learning_log_text.lower()),
            "learning-log.md must describe candidate-file path + single-writer contract",
        )

    # ---- review-side superpowers Skill invocations ----
    for rel_path, expected_call in REVIEW_SIDE_SKILL_CALLS.items():
        full = skill_dir / rel_path
        if not full.is_file():
            record(
                f"skill_call_in_{rel_path.replace('/', '_')}",
                False,
                f"{rel_path} must exist",
            )
            continue
        body = full.read_text(encoding="utf-8")
        record(
            f"skill_call_in_{rel_path.replace('/', '_')}",
            expected_call in body,
            f"{rel_path} must invoke {expected_call}",
        )

    # ---- sub-agent prompts describe candidate-file contract (no direct helper calls) ----
    for rel_path in ["references/implementer-prompt.md",
                     "references/reviewer-prompt.md",
                     "references/verifier-prompt.md"]:
        full = skill_dir / rel_path
        if not full.is_file():
            record(
                f"candidate_file_contract_in_{rel_path.replace('/', '_')}",
                False,
                f"{rel_path} must exist",
            )
            continue
        body = full.read_text(encoding="utf-8")
        record(
            f"candidate_file_contract_in_{rel_path.replace('/', '_')}",
            ".orchestrator/learning_events/" in body and "Do not call the helper" in body,
            f"{rel_path} must describe candidate-file emission and forbid direct helper calls",
        )

    payload = {"passed": not failures, "checks": checks, "failures": failures}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
