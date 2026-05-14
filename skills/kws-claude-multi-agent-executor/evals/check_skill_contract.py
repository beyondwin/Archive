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
    # reviewer-prompt.md intentionally inlines the requesting-code-review
    # checklist rather than invoking the skill (the orchestrator already
    # performed the meta-dispatch the skill describes — this Reviewer IS
    # the dispatched sub-agent). See "Review Checklist (inlined" section
    # in references/reviewer-prompt.md and the dedicated checks below.
    "references/verifier-prompt.md": 'Skill("superpowers:verification-before-completion")',
}

SUBAGENT_PROMPTS = [
    "references/implementer-prompt.md",
    "references/plan-reviewer-prompt.md",
    "references/reviewer-prompt.md",
    "references/verifier-prompt.md",
    "references/docs-updater-prompts.md",
]

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
    "context_health",
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

    # v2.8.1 enforcement: Step 7.5 must use MANDATORY framing + emit a
    # LEARNING_LOG_INIT marker that the eval harness can detect.
    record(
        "skill_md_v281_mandatory_framing",
        all(token in skill_text for token in [
            "MANDATORY",
            "DO NOT SKIP THIS STEP",
            "LEARNING_LOG_INIT:",
        ]),
        "SKILL.md Step 7.5 must use MANDATORY framing and emit LEARNING_LOG_INIT marker (v2.8.1)",
    )

    record(
        "skill_md_tdd_not_size_gated",
        "SMALL skips TDD" not in skill_text
        and "skip TDD" not in skill_text
        and "TDD recommended" not in skill_text
        and "Task size is not a TDD skip condition" in skill_text,
        "SKILL.md must not describe task-size TDD skipping; task size is not a TDD skip condition",
    )

    # ---- learning-log.md content ----
    if learning_log_md.is_file():
        record(
            "learning_log_event_types",
            all(t in learning_log_text for t in EVENT_TYPES),
            f"learning-log.md must mention all 11 event types ({', '.join(EVENT_TYPES)})",
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
    for rel_path in SUBAGENT_PROMPTS:
        full = skill_dir / rel_path
        if not full.is_file():
            record(
                f"using_superpowers_in_{rel_path.replace('/', '_')}",
                False,
                f"{rel_path} must exist",
            )
            continue
        body = full.read_text(encoding="utf-8")
        record(
            f"using_superpowers_in_{rel_path.replace('/', '_')}",
            'Skill("superpowers:using-superpowers")' in body
            and "does not waive" in body,
            f"{rel_path} must bootstrap Skill(\"superpowers:using-superpowers\") without waiving role-specific skills",
        )

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

    implementer_prompt = skill_dir / "references" / "implementer-prompt.md"
    if implementer_prompt.is_file():
        body = implementer_prompt.read_text(encoding="utf-8")
        record(
            "implementer_tdd_not_size_gated",
            'Skill("superpowers:test-driven-development")' in body
            and "MEDIUM or LARGE" not in body
            and "SMALL tasks may skip TDD" not in body
            and "SMALL, MEDIUM, and LARGE" in body
            and "RED command" in body,
            "Implementer prompt must require TDD for executable implementation work across SMALL, MEDIUM, and LARGE tasks and require RED evidence",
        )

    reviewer_prompt = skill_dir / "references" / "reviewer-prompt.md"
    if reviewer_prompt.is_file():
        body = reviewer_prompt.read_text(encoding="utf-8")
        record(
            "reviewer_checklist_inlined",
            "Review Checklist (inlined" in body
            and 'Skill("superpowers:requesting-code-review")' not in body,
            "reviewer-prompt.md must inline the review checklist and not invoke requesting-code-review (the orchestrator already performed that meta-dispatch)",
        )
        record(
            "reviewer_systematic_debugging_fallback",
            'Skill("superpowers:systematic-debugging")' in body,
            "reviewer-prompt.md must offer systematic-debugging as a fallback when the diff is insufficient to judge behavior",
        )

    implementer_prompt_v2 = skill_dir / "references" / "implementer-prompt.md"
    if implementer_prompt_v2.is_file():
        body = implementer_prompt_v2.read_text(encoding="utf-8")
        record(
            "implementer_receiving_review_on_verifier_fail",
            "Combined Reviewer FAIL OR Verifier FAIL" in body,
            "implementer-prompt.md must apply receiving-code-review after both Combined Reviewer FAIL and Verifier FAIL re-dispatches",
        )

    hook_template = skill_dir / "references" / "hooks" / "check-implementer-output.sh.template"
    if hook_template.is_file():
        body = hook_template.read_text(encoding="utf-8")
        record(
            "implementer_hook_validates_tdd_evidence",
            "TDD_EVIDENCE" in body
            and "not[[:space:]]+applicable" in body
            and "FILES_TEST_CHANGED" in body
            and "RED:" in body
            and "GREEN:" in body,
            "check-implementer-output.sh.template must validate TDD_EVIDENCE presence + cross-check RED/GREEN against FILES_TEST_CHANGED",
        )
        # v2.11: hook must also enforce METHOD_AUDIT block on STATUS=DONE
        record(
            "implementer_hook_validates_method_audit",
            "METHOD_AUDIT" in body
            and "tdd applied" in body
            and "tdd waived" in body,
            "check-implementer-output.sh.template must enforce METHOD_AUDIT block (v2.11)",
        )

    docs_prompt = skill_dir / "references" / "docs-updater-prompts.md"
    if docs_prompt.is_file():
        body = docs_prompt.read_text(encoding="utf-8")
        record(
            "docs_updater_verification_skill_call",
            body.count('Skill("superpowers:verification-before-completion")') >= 2,
            "Both Docs Updater prompts must invoke verification-before-completion before reporting DONE",
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

    # ---- v2.11 mandatory-wording checks ----
    # Each tuple: (section_anchor, required_substring).
    # Section-scoped: locate anchor in skill_text, then search forward ~4000 chars
    # for the required_substring. Avoids false positives from distant sections.
    # Anchors are verbatim substrings that appear at or near the section's heading
    # in SKILL.md — use actual heading text rather than descriptive phase labels.
    REQUIRED_WORDING = [
        # v2.11 additions — (anchor_in_skill_text, required_substring)
        # Phase 1 Step 4 = "### Step 4: Agent Cleanup" — method_audit in schema block
        ("Step 4: Agent Cleanup", "method_audit"),
        # Phase 2 Step 1.5 = "### Step 1.5: Method Audit Validation"
        ("Step 1.5: Method Audit Validation", "method_audit"),
        # Phase 0 Step 4.7 heading itself contains "Local-env preflight"
        ("Step 4.7: Local-env preflight", "Local-env preflight"),
        # Phase 0 Step 6 resource_key partition rule — "v2.11 — `resource_key`"
        ("resource_key` partition rule", "resource_key"),
        # Guardrails table — these rows must appear within the Guardrails section
        ("## Guardrails", "Method audit must pass before Phase 2 close-run"),
        ("## Guardrails", "Resource-key collisions force serialization in same wave"),
    ]
    SECTION_WINDOW = 15000  # chars to scan forward from anchor (Guardrails table spans >12k chars)

    for anchor, substring in REQUIRED_WORDING:
        check_key = f"wording_v211_{anchor[:20].lower().replace(' ', '_').replace('`', '').replace(':', '').replace('#', '').strip()}_{substring[:15].lower().replace(' ', '_').replace('-', '_')}"
        idx = skill_text.find(anchor)
        if idx == -1:
            record(check_key, False,
                   f"SKILL.md: section anchor '{anchor}' not found (needed to verify '{substring}')")
            continue
        window = skill_text[idx: idx + SECTION_WINDOW]
        record(
            check_key,
            substring in window,
            f"SKILL.md: '{substring}' not found within {SECTION_WINDOW} chars after '{anchor}'",
        )

    payload = {"passed": not failures, "checks": checks, "failures": failures}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
