#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path


CASE_DIR = Path(__file__).resolve().parent / "golden-cases"
REQUIRED_SECTIONS = ["Scenario", "Input", "Must", "Must Not", "Expected Decision", "Expected Risk"]
EXPECTED_CASES = {
    "dirty-related-block.md": ("block", "dirty_related_worktree"),
    "resume-ambiguous-block.md": ("block", "resume_ambiguity"),
    "unsafe-verification-block.md": ("block", "unsafe_verification"),
    "subagent-local-fallback.md": ("local_fallback", "subagent_policy_fallback"),
    "task-packet-human-view.md": ("render", "human_view_parity"),
}


def parse_sections(text: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            sections[current] = []
            continue
        if current is not None:
            sections[current].append(line)
    return {key: "\n".join(value).strip() for key, value in sections.items()}


def main() -> int:
    failures: list[str] = []
    checks: dict[str, bool] = {}

    for filename, expected in EXPECTED_CASES.items():
        path = CASE_DIR / filename
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
        sections = parse_sections(text)
        missing = [section for section in REQUIRED_SECTIONS if not sections.get(section)]
        key = filename.removesuffix(".md")
        checks[f"{key}_sections_present"] = not missing
        if missing:
            failures.append(f"{filename} missing section(s): {', '.join(missing)}")
            continue
        decision, risk = expected
        checks[f"{key}_expected_decision"] = sections["Expected Decision"].strip() == decision
        checks[f"{key}_expected_risk"] = sections["Expected Risk"].strip() == risk
        if not checks[f"{key}_expected_decision"]:
            failures.append(f"{filename} expected decision should be {decision}")
        if not checks[f"{key}_expected_risk"]:
            failures.append(f"{filename} expected risk should be {risk}")
        for section_name in ("Must", "Must Not"):
            bullet_count = sum(1 for line in sections[section_name].splitlines() if line.strip().startswith("- "))
            checks[f"{key}_{section_name.lower().replace(' ', '_')}_has_bullets"] = bullet_count >= 2
            if bullet_count < 2:
                failures.append(f"{filename} {section_name} should contain at least two bullets")

    print(json.dumps({"passed": not failures, "checks": checks, "failures": failures}, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
