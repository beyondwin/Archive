#!/usr/bin/env python3
"""Check spec and implementation docs for the KWS doc quality contract."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


SPEC_SECTIONS = [
    "Overview",
    "Goals",
    "Non-goals",
    "Requirements",
    "User Experience",
    "Architecture",
    "Data",
    "Traceability Matrix",
    "Verification Plan",
    "Risks",
    "Open Questions",
]

IMPLEMENTATION_SECTIONS = [
    "Overview",
    "Files",
    "Implementation Plan",
    "Traceability Matrix",
    "Verification Plan",
    "Rollback Plan",
    "Risks",
    "Done When",
]

PLACEHOLDERS = re.compile(r"\b(TODO|TBD|FIXME|placeholder|later)\b|<[^>\n]+>", re.I)
COMMAND_PATTERN = re.compile(r"`[^`\n]+`|\b(?:npm|pnpm|bun|yarn|python3?|pytest|cargo|go|git|rg|make)\s+[-\w./:@=]+")
REQ_ID_PATTERN = re.compile(r"\bR\d+\b")


def read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise SystemExit(f"missing file: {path}") from None


def headings(text: str) -> set[str]:
    found: set[str] = set()
    for line in text.splitlines():
        match = re.match(r"^#{2,6}\s+(.+?)\s*$", line)
        if match:
            found.add(match.group(1).strip().rstrip("#").strip())
    return found


def section_text(text: str, heading: str) -> str:
    pattern = re.compile(rf"^#{{2,6}}\s+{re.escape(heading)}\s*$", re.M)
    match = pattern.search(text)
    if not match:
        return ""
    next_heading = re.search(r"^#{2,6}\s+", text[match.end() :], re.M)
    end = match.end() + next_heading.start() if next_heading else len(text)
    return text[match.end() : end].strip()


def check_required_sections(label: str, text: str, required: list[str]) -> list[str]:
    present = headings(text)
    return [f"{label}: missing section '{name}'" for name in required if name not in present]


def check_traceability(label: str, text: str) -> list[str]:
    trace = section_text(text, "Traceability Matrix")
    problems: list[str] = []
    for token in ("Requirement", "Implementation", "Verification"):
        if token not in trace:
            problems.append(f"{label}: Traceability Matrix missing '{token}' column/content")
    if not REQ_ID_PATTERN.search(trace):
        problems.append(f"{label}: Traceability Matrix must include stable requirement IDs such as R1")
    return problems


def check_verification(label: str, text: str) -> list[str]:
    verification = section_text(text, "Verification Plan")
    problems: list[str] = []
    if not COMMAND_PATTERN.search(verification):
        problems.append(f"{label}: Verification Plan must include at least one concrete command")
    if not re.search(r"\b(manual smoke|browser smoke|smoke|inspect|open)\b", verification, re.I):
        problems.append(f"{label}: Verification Plan must include a manual or smoke check")
    return problems


def check_requirement_alignment(spec: str, implementation: str) -> list[str]:
    spec_ids = set(REQ_ID_PATTERN.findall(section_text(spec, "Requirements")))
    impl_trace_ids = set(REQ_ID_PATTERN.findall(section_text(implementation, "Traceability Matrix")))
    missing = sorted(spec_ids - impl_trace_ids)
    if missing:
        return [f"implementation: missing requirement IDs from spec traceability: {', '.join(missing)}"]
    if not spec_ids:
        return ["spec: Requirements must include stable IDs such as R1"]
    return []


def check_doc(label: str, text: str, required: list[str]) -> list[str]:
    problems = check_required_sections(label, text, required)
    if PLACEHOLDERS.search(text):
        problems.append(f"{label}: contains placeholder text")
    problems.extend(check_traceability(label, text))
    problems.extend(check_verification(label, text))
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True, help="Spec document path")
    parser.add_argument("--implementation", required=True, help="Implementation document path")
    parser.add_argument("--repo-root", default=".", help="Repository root for path context")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    args = parser.parse_args()

    spec_path = Path(args.spec)
    implementation_path = Path(args.implementation)
    repo_root = Path(args.repo_root)

    spec = read(spec_path)
    implementation = read(implementation_path)

    problems: list[str] = []
    if not repo_root.exists():
        problems.append(f"repo root does not exist: {repo_root}")
    problems.extend(check_doc("spec", spec, SPEC_SECTIONS))
    problems.extend(check_doc("implementation", implementation, IMPLEMENTATION_SECTIONS))
    problems.extend(check_requirement_alignment(spec, implementation))

    result = {
        "passed": not problems,
        "spec": str(spec_path),
        "implementation": str(implementation_path),
        "problems": problems,
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif problems:
        for problem in problems:
            print(problem, file=sys.stderr)
    else:
        print("doc quality ok")
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
