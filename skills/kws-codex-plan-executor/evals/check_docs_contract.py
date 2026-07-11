#!/usr/bin/env python3
"""Reject stale v2 paths and release claims from active CPE v3 docs."""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import unquote


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
    "references/headless-result-schema.md",
    "references/prompt-export-checklist.md",
    "references/drift-reconciliation.md",
    "references/subagent-run-store.md",
    "references/verifier-prompt.md",
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
    "static_execution_runner.py",
    "static_prompt_runner.py",
)

SEVEN_RUNTIME_OWNERS = (
    "PlanCompiler",
    "PacketStore",
    "AttemptController",
    "RunKernel",
    "CanonicalValidator",
    "RecoveryEngine",
    "PublicCLI",
)

SAFE_REPAIR_ACTIONS = (
    "rebuild_snapshot",
    "regenerate_derived_reports",
    "mark_stale_attempt_interrupted",
    "reconnect_existing_evidence",
    "resolve_blocker",
    "schedule_retry",
)

REQUIRED_COMMANDS = (
    "python3 scripts/cpe.py run --plan PLAN [--spec SPEC] --workspace REPO --mode interactive",
    "python3 scripts/cpe.py resume --run-id RUN_ID",
    "python3 scripts/cpe.py export --plan PLAN --workspace REPO --mode prompt",
    "python3 scripts/cpe.py export --plan PLAN --workspace REPO --mode handoff",
    "python3 scripts/reconcile_state.py --run-dir RUN_DIR --check",
    "python3 scripts/repair_runs.py --run-dir RUN_DIR --dry-run",
)

MARKDOWN_LINK_RE = re.compile(r"\[[^\]\n]+\]\(([^)\n]*)\)")
FENCED_CODE_RE = re.compile(r"```.*?```|~~~.*?~~~", re.DOTALL)
INLINE_CODE_RE = re.compile(r"`+[^`\n]*`+")


def _markdown_relative_link_failures(root: Path, texts: dict[str, str]) -> list[str]:
    """Return broken or unsafe relative Markdown links from active docs."""
    root = root.resolve()
    failures: list[str] = []
    for relative, original in texts.items():
        text = INLINE_CODE_RE.sub("", FENCED_CODE_RE.sub("", original))
        source = (root / relative).resolve()
        for match in MARKDOWN_LINK_RE.finditer(text):
            raw = match.group(1).strip()
            if not raw:
                failures.append(f"{relative}: malformed empty Markdown link")
                continue
            if raw.startswith("<"):
                closing = raw.find(">")
                if closing < 0:
                    failures.append(f"{relative}: malformed Markdown link: {raw}")
                    continue
                target = raw[1:closing]
                suffix = raw[closing + 1 :].strip()
            else:
                parts = raw.split(maxsplit=1)
                target = parts[0]
                suffix = parts[1].strip() if len(parts) == 2 else ""
            if suffix and re.fullmatch(r'(?:"[^"]*"|\'[^\']*\')', suffix) is None:
                failures.append(f"{relative}: malformed Markdown link: {raw}")
                continue
            lowered = target.lower()
            if lowered.startswith(("http://", "https://", "mailto:")) or target.startswith("#"):
                continue
            if re.match(r"^[a-z][a-z0-9+.-]*:", lowered):
                failures.append(f"{relative}: unsupported Markdown link scheme: {target}")
                continue
            target = unquote(target.split("#", 1)[0].split("?", 1)[0])
            if not target or "\x00" in target or "\\" in target:
                failures.append(f"{relative}: malformed Markdown link: {raw}")
                continue
            candidate = (source.parent / target).resolve()
            try:
                candidate.relative_to(root)
            except ValueError:
                failures.append(f"{relative}: Markdown link escapes skill root: {target}")
                continue
            if not candidate.exists():
                failures.append(f"{relative}: missing Markdown link target: {target}")
    return failures


def _link_validator_self_test(root: Path, texts: dict[str, str]) -> str | None:
    injected = dict(texts)
    injected["README.md"] = injected.get("README.md", "") + (
        "\n[broken](missing-contract-target.md)\n"
        "`[ignored-code](missing-code-target.md)`\n"
        "[ignored-anchor](#local-section)\n"
    )
    failures = _markdown_relative_link_failures(root, injected)
    if not any("README.md: missing Markdown link target: missing-contract-target.md" in item for item in failures):
        return "Markdown link validator self-test did not reject an injected broken README link"
    if any("missing-code-target.md" in item or "#local-section" in item for item in failures):
        return "Markdown link validator self-test did not ignore code spans or pure anchors"
    return None


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

    active_text = "\n".join(texts.values())
    for command in REQUIRED_COMMANDS:
        if command not in active_text:
            failures.append(f"active docs missing exact public command: {command}")

    failures.extend(_markdown_relative_link_failures(root, texts))
    if self_test_failure := _link_validator_self_test(root, texts):
        failures.append(self_test_failure)

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
    stale_release_claims = (
        r"(?:3\.0\.0|release status|현재 3\.0\.0).{0,100}`?deterministic-ready; paid-live-pending`?",
        r"`?deterministic-ready; paid-live-pending`?.{0,100}(?:3\.0\.0|current release|현재)",
    )
    for relative in (
        "SKILL.md",
        "README.md",
        "docs/evals-and-verification.md",
        "docs/mental-model.ko.md",
        "docs/risks-limitations-deferrals.md",
        "docs/release-process.md",
    ):
        text = texts.get(relative, "")
        if any(re.search(pattern, text, re.IGNORECASE | re.DOTALL) for pattern in stale_release_claims):
            failures.append(f"{relative}: 3.0.0 must not claim deterministic-ready")

    architecture = texts.get("ARCHITECTURE.md", "")
    for owner in SEVEN_RUNTIME_OWNERS:
        if owner not in architecture:
            failures.append(f"ARCHITECTURE.md missing runtime owner: {owner}")
    architecture_terms = (
        "internal input snapshot",
        "packet_sha256",
        "worktree_revision",
        "validate_integrity",
        "validate_completion",
        "repository_check",
        "final_review",
    )
    for term in architecture_terms:
        if term not in architecture:
            failures.append(f"ARCHITECTURE.md missing integrity contract term: {term}")

    execution_docs = "\n".join(
        texts.get(name, "")
        for name in ("SKILL.md", "references/execution-cycle.md", "references/mode-contracts.md")
    )
    for role in ("scout", "implementation", "task_review", "verification", "repair", "final_review"):
        if role not in execution_docs:
            failures.append(f"execution docs missing packet-consuming role: {role}")
    for term in ("acceptance", "repository_check", "worktree_patch_sha256"):
        if term not in execution_docs:
            failures.append(f"execution docs missing phase or revision term: {term}")

    repair_docs = "\n".join(
        texts.get(name, "")
        for name in ("references/drift-reconciliation.md", "docs/user-guide.ko.md")
    )
    for action in SAFE_REPAIR_ACTIONS:
        if action not in repair_docs:
            failures.append(f"repair docs missing exact safe action: {action}")
    for term in ("applied=false", "--expected-projection-delta", "--apply"):
        if term not in repair_docs:
            failures.append(f"repair docs missing apply contract: {term}")

    public_docs = "\n".join(
        texts.get(name, "")
        for name in ("README.md", "docs/how-it-works.md", "docs/human-readable-harness-flow.ko.md")
    )
    for term in ("PublicResult", "success=0", "blocked=1", "failed=2"):
        if term not in public_docs:
            failures.append(f"public docs missing result contract: {term}")
    for term in ("maintained eval inventory", "public CLI", "isolated oracle"):
        if term not in public_docs:
            failures.append(f"harness docs missing behavior-test contract: {term}")

    release_process = texts.get("docs/release-process.md", "")
    if "release_gate.passed=true" not in release_process or "explicit cost approval" not in release_process:
        failures.append("release process must define the paid live closeout evidence")

    payload = {"passed": not failures, "checked": list(ACTIVE_DOCS), "failures": failures}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
