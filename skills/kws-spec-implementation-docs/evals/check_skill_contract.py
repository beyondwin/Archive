#!/usr/bin/env python3
"""Deterministic contract checks for kws-spec-implementation-docs."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill", required=True, help="Path to SKILL.md")
    args = parser.parse_args()

    skill = Path(args.skill)
    root = skill.resolve().parent
    text = skill.read_text(encoding="utf-8")
    contract = (root / "references" / "doc-quality-contract.md").read_text(encoding="utf-8")
    checker = (root / "scripts" / "check_doc_quality.py").read_text(encoding="utf-8")
    metadata = re.search(r"\A---\n(.*?)\n---", text, re.S)
    body = text[metadata.end() :] if metadata else text

    checks = {
        "frontmatter_name": "name: kws-spec-implementation-docs" in text,
        "frontmatter_description_trigger_only": "Use when" in text
        and "spec" in text.lower()
        and "implementation" in text.lower()
        and "TODO" not in (metadata.group(1) if metadata else ""),
        "no_template_todos": "TODO" not in text and "[TODO" not in text,
        "body_names_quality_checker": "scripts/check_doc_quality.py" in body,
        "body_links_contract": "references/doc-quality-contract.md" in body,
        "requires_repo_grounding": all(token in body for token in ("repo instructions", "git status", "existing docs")),
        "requires_two_docs": all(token in body for token in ("spec document", "implementation document")),
        "requires_traceability": all(token in body + contract for token in ("Traceability Matrix", "Requirement", "Implementation")),
        "requires_verification_plan": all(token in body + contract for token in ("Verification Plan", "command", "manual smoke")),
        "requires_risk_closure": all(token in body + contract for token in ("Risks", "Open Questions", "Non-goals")),
        "requires_approval_boundary": "approval" in body.lower() and "do not implement code" in body.lower(),
        "checker_has_required_sections": all(
            token in checker
            for token in (
                "Overview",
                "Goals",
                "Non-goals",
                "Requirements",
                "User Experience",
                "Architecture",
                "Data",
                "Implementation Plan",
                "Verification Plan",
                "Risks",
            )
        ),
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        for name in failed:
            print(f"FAIL {name}")
        return 1
    print("skill contract ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
