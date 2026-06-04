#!/usr/bin/env python3
"""Skill contract checks for kws-claude-multi-agent-executor.

Verifies that SKILL.md + references + scripts collectively wire the v2.17
AgentLens event-publishing contract and the review-side superpowers Skill
invocations. Pre-v2.17 runs published to a parallel
`~/.claude/learning/.../events.jsonl`; that helper was removed in Task 11
of the AgentLens v1 cutover and the contract now checks the AgentLens
equivalents (`agentlens run-open`, `agentlens event append`,
`agentlens run-close`, `kws-cme.phase_0_started` boundary marker).
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

    # v2.21 split: phase + cross-cutting prose migrates from SKILL.md into
    # references/phases/ and references/cross-cutting/. The contract verifies
    # that the skill *collectively* wires its invariants (see module docstring),
    # so token-presence and section-anchored wording checks search a corpus of
    # SKILL.md plus those extracted references rather than SKILL.md alone.
    # `corpus_texts` is the ordered list of (label, text); `corpus` is their join.
    corpus_texts: list[tuple[str, str]] = [("SKILL.md", skill_text)]
    for sub in ("phases", "cross-cutting"):
        sub_dir = skill_dir / "references" / sub
        if sub_dir.is_dir():
            for ref in sorted(sub_dir.glob("*.md")):
                corpus_texts.append((f"references/{sub}/{ref.name}",
                                     ref.read_text(encoding="utf-8")))
    corpus = "\n".join(text for _, text in corpus_texts)

    learning_log_md = skill_dir / "references" / "learning-log.md"
    learning_log_text = learning_log_md.read_text(encoding="utf-8") if learning_log_md.is_file() else ""

    checks: dict[str, bool] = {}
    failures: list[str] = []

    def record(name: str, ok: bool, msg: str) -> None:
        checks[name] = ok
        if not ok:
            failures.append(msg)

    # ---- learning-log artifact existence ----
    record("learning_log_reference_exists", learning_log_md.is_file(),
           "references/learning-log.md must exist")

    # ---- SKILL.md wires AgentLens event publishing (v2.17 cutover) ----
    record(
        "skill_md_mentions_agentlens_lifecycle",
        all(token in corpus for token in [
            "ORCH_RUN_ID",
            "agentlens run-open",
            "agentlens event append",
            "agentlens run-close",
            "references/learning-log.md",
        ]),
        "SKILL.md must wire AgentLens lifecycle: ORCH_RUN_ID + run-open/event append/run-close + learning-log.md",
    )

    record(
        "skill_md_describes_exit_paths",
        all(token in corpus for token in [
            "--outcome success",
            "--outcome blocked",
            "--outcome aborted",
        ]),
        "SKILL.md must describe agentlens run-close on success/blocked/aborted exit paths",
    )

    record(
        "skill_md_describes_chained_run_propagation",
        all(token in corpus for token in [
            "AGENTLENS_PARENT_RUN_ID",
            "Resume Chain",
        ]),
        "SKILL.md must describe AGENTLENS_PARENT_RUN_ID propagation in Resume Chain handoff",
    )

    # v2.17 enforcement: the Phase 0 boundary emit step must use MANDATORY
    # framing and reference the kws-cme.phase_0_started event so the eval
    # harness can detect adherence via AgentLens.
    record(
        "skill_md_v217_mandatory_framing",
        all(token in corpus for token in [
            "MANDATORY",
            "DO NOT SKIP THIS STEP",
            "kws-cme.phase_0_started",
        ]),
        "SKILL.md Phase 0 boundary emit step must use MANDATORY framing and emit kws-cme.phase_0_started (v2.17)",
    )

    # ---- v2.21 helper contracts (state_set / phase_boundary / migrate shim) ----
    # The helpers must exist on disk and carry their CLI contract.
    V221_HELPERS = {
        "scripts/state_set.py": ["--field", "--plan-scope", "resolve_active_tree"],
        "scripts/phase_boundary.py": ["task-start", "task-complete", "phase-emit"],
        "scripts/migrate_legacy_state.py": ["plan_chain", "plan2_state", "active_plan"],
    }
    for rel_path, tokens in V221_HELPERS.items():
        full = skill_dir / rel_path
        if not full.is_file():
            record(f"v221_helper_exists_{rel_path.replace('/', '_')}", False,
                   f"{rel_path} must exist (v2.21)")
            continue
        body = full.read_text(encoding="utf-8")
        record(
            f"v221_helper_contract_{rel_path.replace('/', '_')}",
            all(t in body for t in tokens),
            f"{rel_path} must define its CLI contract tokens: {', '.join(tokens)}",
        )

    # ---- v2.21 emit-site wiring (D005 delta 1) ----
    # The SKILL.md split has landed, so the phase references must now invoke the
    # boundary helpers at their mandated emit sites rather than carrying inline
    # state-write / agentlens-append prose. The corpus spans SKILL.md +
    # references/phases/*.md + references/cross-cutting/*.md, so these tokens
    # survive the migration regardless of which file holds the call.
    V221_WIRING = {
        "phase_boundary_task_start_wired": (
            "phase_boundary.py task-start",
            "task-start boundary (pre-sha + timing.started) must be wired via phase_boundary.py",
        ),
        "phase_boundary_task_complete_wired": (
            "phase_boundary.py task-complete",
            "task-complete boundary (result + timing + last_completed + emit) must be wired via phase_boundary.py",
        ),
        "phase_boundary_phase_emit_wired": (
            "phase_boundary.py phase-emit",
            "phase boundary emits must be wired via phase_boundary.py phase-emit",
        ),
        "phase_boundary_phase_0_started_wired": (
            "--type phase_0_started",
            "Phase 0 start boundary must invoke phase-emit --type phase_0_started",
        ),
        "phase_boundary_compaction_wired": (
            "--type compaction",
            "Compaction boundary must invoke phase-emit --type compaction",
        ),
        "phase_boundary_phase_2_complete_wired": (
            "--type phase_2_complete",
            "Phase 2 completion boundary must invoke phase-emit --type phase_2_complete",
        ),
        "state_set_wired": (
            "state_set.py",
            "Anchor/pointer state writes must be wired via state_set.py",
        ),
    }
    for check_id, (token, msg) in V221_WIRING.items():
        record(check_id, token in corpus, msg)

    record(
        "skill_md_wires_legacy_migration_shim",
        "migrate_legacy_state.py" in corpus,
        "SKILL.md Phase 0 Step 0 must wire the v2.21 legacy plan2_state migration shim",
    )
    record(
        "skill_md_records_agentlens_healthy",
        "agentlens_healthy" in corpus,
        "SKILL.md must record the run-level agentlens_healthy health-probe field (v2.21)",
    )

    # ---- v2.26 finalization + schema gate contracts ----
    V226_HELPERS = {
        "scripts/validate_state_schema.py": ["--state", "execution_order_without_plan", "risk_value_invalid"],
        "scripts/finalize_run.py": ["--check", "--fix", "verifier_pending_batch", "completed_at_null"],
    }
    for rel_path, tokens in V226_HELPERS.items():
        full = skill_dir / rel_path
        if not full.is_file():
            record(f"v226_helper_exists_{rel_path.replace('/', '_')}", False,
                   f"{rel_path} must exist (v2.26)")
            continue
        body = full.read_text(encoding="utf-8")
        record(
            f"v226_helper_contract_{rel_path.replace('/', '_')}",
            all(t in body for t in tokens),
            f"{rel_path} must define its CLI/violation-code tokens: {', '.join(tokens)}",
        )

    record(
        "v226_schema_gate_wired",
        "validate_state_schema.py" in corpus,
        "Phase 2 prose must wire validate_state_schema.py (Step 1.5 schema gate)",
    )
    record(
        "v226_finalize_gate_wired",
        "finalize_run.py" in corpus,
        "Phase 2 prose must wire finalize_run.py --fix (Step 2 finalization gate)",
    )
    record(
        "v226_guardrail_row",
        "Finalization gate is mandatory before close-run" in corpus,
        "SKILL.md Guardrails must carry the v2.26 finalization-gate row",
    )

    # ---- v2.26 Stop-hook forcing function (D001) ----
    stop_hook_tmpl = skill_dir / "references/hooks/finalization-stop-gate.sh.template"
    record(
        "v226_stop_hook_template_exists",
        stop_hook_tmpl.is_file(),
        "references/hooks/finalization-stop-gate.sh.template must exist (D001)",
    )
    if stop_hook_tmpl.is_file():
        tmpl_body = stop_hook_tmpl.read_text(encoding="utf-8")
        record(
            "v226_stop_hook_template_contract",
            all(t in tmpl_body for t in
                ["finalize_run.py", "validate_state_schema.py", "exit 0", "exit 2"]),
            "Stop-hook template must invoke both validators and fail-open(0)/closed(2)",
        )
    record(
        "v226_stop_hook_wired",
        "finalization-stop-gate.sh" in corpus and '"Stop"' in corpus,
        "Phase 0 Step 2.5 must materialize + wire finalization-stop-gate.sh as a Stop hook",
    )
    record(
        "v226_stop_hook_guardrail_row",
        "Stop hook forces finalization" in corpus,
        "SKILL.md Guardrails must carry the v2.26 Stop-hook row",
    )

    record(
        "skill_md_tdd_not_size_gated",
        "SMALL skips TDD" not in corpus
        and "skip TDD" not in corpus
        and "TDD recommended" not in corpus
        and "Task size is not a TDD skip condition" in corpus,
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
        # v2.17 cutover banner — learning-log.md must document the AgentLens
        # equivalents instead of the deleted helper subcommands. The banner
        # explicitly lists pre-v2.17 → v2.17+ replacements.
        record(
            "learning_log_v217_cutover_banner",
            all(t in learning_log_text for t in [
                "v2.17 cutover",
                "agentlens run-open",
                "agentlens event append",
                "agentlens run-close",
            ]),
            "learning-log.md must document the v2.17 AgentLens cutover (run-open / event append / run-close replacements)",
        )
        record(
            "learning_log_candidate_file_contract",
            "<orch_dir>/learning_events/" in learning_log_text
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
            "<orch_dir>/learning_events/" in body and "Do not call the helper" in body,
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
    SECTION_WINDOW = 20000  # chars to scan forward from anchor (Guardrails table grew past 15k as new invariants accreted)

    for anchor, substring in REQUIRED_WORDING:
        check_key = f"wording_v211_{anchor[:20].lower().replace(' ', '_').replace('`', '').replace(':', '').replace('#', '').strip()}_{substring[:15].lower().replace(' ', '_').replace('-', '_')}"
        # The anchor and its required wording co-locate within one phase; after
        # the v2.21 split that phase may be SKILL.md or a phases/ reference, so
        # search each corpus file for the anchor and check the window in the
        # first file that contains it.
        found_label = None
        ok = False
        for label, text in corpus_texts:
            idx = text.find(anchor)
            if idx == -1:
                continue
            found_label = label
            ok = substring in text[idx: idx + SECTION_WINDOW]
            break
        if found_label is None:
            record(check_key, False,
                   f"section anchor '{anchor}' not found in SKILL.md or phase references (needed to verify '{substring}')")
            continue
        record(
            check_key,
            ok,
            f"{found_label}: '{substring}' not found within {SECTION_WINDOW} chars after '{anchor}'",
        )

    payload = {"passed": not failures, "checks": checks, "failures": failures}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
