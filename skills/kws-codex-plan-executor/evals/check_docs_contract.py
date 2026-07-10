#!/usr/bin/env python3
"""Reject stale v2 paths and release claims from active CPE v3 docs."""

from __future__ import annotations

import json
import re
from pathlib import Path


ACTIVE_DOCS = (
    "SKILL.md",
    "README.md",
    "ARCHITECTURE.md",
    "agents/openai.yaml",
    "references/state-schema.md",
    "references/event-journal.md",
    "references/execution-cycle.md",
    "references/mode-contracts.md",
    "references/headless-runner.md",
    "references/prompt-export-checklist.md",
    "references/drift-reconciliation.md",
    "references/subagent-run-store.md",
    "references/cache-strategy.md",
    "references/change-protocol.md",
    "references/common-mistakes.md",
    "references/command-observations.md",
    "references/context-budget.md",
    "references/context-intelligence.md",
    "references/learning-log.md",
    "references/local-env-preflight.md",
    "references/pre-dispatch-pipeline.md",
    "references/unit-context-manifest.md",
    "docs/how-it-works.md",
    "docs/doc-update-protocol.md",
    "docs/state-and-logging.md",
    "docs/evals-and-verification.md",
    "docs/eval-coverage-cpe.md",
    "docs/risks-limitations-deferrals.md",
    "docs/future-agent-guide.md",
    "docs/user-guide.ko.md",
    "docs/mental-model.ko.md",
    "docs/release-process.md",
    "docs/decisions.md",
    "docs/human-readable-harness-flow.ko.md",
    "docs/post-merge-verification.md",
)

FORBIDDEN_ACTIVE_TERMS = (
    "full_spec_on_blocker",
    "manifest_fallback",
    "cpe_state_validation",
    "run_quality_debt.py",
    "append_trajectory_event.py",
    "update_progress_ledger.py",
    "update_decisions_register.py",
    "record_cache_observation.py",
    "classify_recovery.py",
    "check_trajectory_projection.py",
    "check_progress_ledger.py",
    "check_cache_observations.py",
    "baselines/v2",
)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    failures: list[str] = []
    texts: dict[str, str] = {}
    for relative in ACTIVE_DOCS:
        path = root / relative
        if not path.is_file():
            failures.append(f"missing active document: {relative}")
            continue
        text = path.read_text(encoding="utf-8")
        texts[relative] = text
        lowered = text.lower()
        for term in FORBIDDEN_ACTIVE_TERMS:
            if term.lower() in lowered:
                failures.append(f"{relative}: stale active term: {term}")
        if re.search(r"state\.json.{0,50}(source of truth|authoritative)", text, re.IGNORECASE | re.DOTALL):
            failures.append(f"{relative}: state.json must be described as a projection, not authority")

    skill = texts.get("SKILL.md", "")
    required_skill_terms = (
        "gpt-5.6-sol",
        "gpt-5.6-terra",
        "events.jsonl",
        "explicit `spec_refs`",
        "paid-live-pending",
        "scripts/cpe.py run",
        "scripts/cpe.py resume",
        "scripts/cpe.py export",
        "scripts/validate_state.py",
        "scripts/reconcile_state.py",
        "scripts/repair_runs.py",
        "scripts/inspect_runs.py",
        "scripts/analyze_recent_runs.py",
    )
    for term in required_skill_terms:
        if term not in skill:
            failures.append(f"SKILL.md missing v3 public contract term: {term}")

    release_docs = "\n".join(
        texts.get(name, "")
        for name in (
            "SKILL.md",
            "README.md",
            "docs/risks-limitations-deferrals.md",
            "docs/release-process.md",
        )
    )
    if "deterministic-ready" not in release_docs or "paid-live-pending" not in release_docs:
        failures.append("release docs must distinguish deterministic-ready from paid-live-pending")
    release_process = texts.get("docs/release-process.md", "")
    if "release_gate.passed=true" not in release_process or "explicit cost approval" not in release_process:
        failures.append("release process must define the paid live closeout evidence")

    payload = {"passed": not failures, "checked": list(ACTIVE_DOCS), "failures": failures}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
