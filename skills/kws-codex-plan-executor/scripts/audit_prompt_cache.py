#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path


START = "<!-- CPE_CACHE_STABLE_PREFIX_START -->"
END = "<!-- CPE_CACHE_STABLE_PREFIX_END -->"
HOT = "<!-- CPE_CACHE_HOT_TAIL_START -->"
CHECKED_FILES = (
    "templates/fresh-session-prompt.txt",
    "references/verifier-prompt.md",
)
ALLOWLISTED_PLACEHOLDERS = {"{{STATIC_SKILL_NAME}}", "{{STATIC_OUTPUT_SCHEMA_NAME}}"}
DYNAMIC_PATTERNS = (
    re.compile(r"\{\{[^}]+\}\}"),
    re.compile(r"\bSTATE_PATH\b|\bRUN_ID\b|\bTASK_PACKET\b|\bGIT_STATUS\b"),
    re.compile(r"~?/\.codex/(?:orchestrator|worktrees)/"),
    re.compile(r"\bgit status\b|\bgit diff\b|\bgraphify update\b"),
)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def stable_prefix(path: Path) -> tuple[str | None, list[dict]]:
    text = path.read_text(encoding="utf-8")
    violations: list[dict] = []
    if text.count(START) != 1:
        violations.append({"file": str(path), "kind": "marker_count", "marker": START, "count": text.count(START)})
    if text.count(END) != 1:
        violations.append({"file": str(path), "kind": "marker_count", "marker": END, "count": text.count(END)})
    if text.count(HOT) != 1:
        violations.append({"file": str(path), "kind": "marker_count", "marker": HOT, "count": text.count(HOT)})
    if violations:
        return None, violations
    start = text.index(START) + len(START)
    end = text.index(END)
    hot = text.index(HOT)
    if not start <= end < hot:
        violations.append({"file": str(path), "kind": "marker_order", "detail": "stable prefix must end before hot tail"})
        return None, violations
    prefix = text[start:end]
    for pattern in DYNAMIC_PATTERNS:
        for match in pattern.finditer(prefix):
            token = match.group(0)
            if token in ALLOWLISTED_PLACEHOLDERS:
                continue
            violations.append({"file": str(path), "kind": "dynamic_marker", "token": token})
    return prefix, violations


def audit(skill_root: Path) -> dict:
    stable_prefix_hashes: dict[str, str] = {}
    stable_prefix_bytes: dict[str, int] = {}
    dynamic_marker_violations: list[dict] = []
    missing_files: list[str] = []
    for relative in CHECKED_FILES:
        path = skill_root / relative
        if not path.is_file():
            missing_files.append(relative)
            continue
        prefix, violations = stable_prefix(path)
        dynamic_marker_violations.extend({**item, "file": relative} for item in violations)
        if prefix is not None:
            encoded = prefix.encode("utf-8")
            stable_prefix_hashes[relative] = hashlib.sha256(encoded).hexdigest()
            stable_prefix_bytes[relative] = len(encoded)
    passed = not dynamic_marker_violations and not missing_files
    return {
        "schema_version": "1",
        "checked_at": now_iso(),
        "passed": passed,
        "stable_prefix_hashes": stable_prefix_hashes,
        "stable_prefix_bytes": stable_prefix_bytes,
        "dynamic_marker_violations": dynamic_marker_violations,
        "missing_files": missing_files,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit CPE prompt cache boundaries.")
    parser.add_argument("--skill-root", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()
    report = audit(Path(args.skill_root).resolve())
    text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
