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
    text = skill_path.read_text(encoding="utf-8")
    invocation = section(text, "## Invocation", "## Hard Boundary")
    checks: dict[str, bool] = {}
    failures: list[str] = []

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
