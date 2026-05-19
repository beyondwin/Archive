#!/usr/bin/env python3
"""Build a stable Markdown section manifest for a specification file."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path


FALLBACK_POLICIES = {"full_spec_on_blocker", "halt_on_blocker"}
HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
FENCE_RE = re.compile(r"^(?: {0,3})(?P<marker>`{3,}|~{3,})(?P<suffix>[^\r\n]*)$")
FENCE_CLOSE_SUFFIX_RE = re.compile(r"^[ \t]*$")
COMMENT_OPEN = "<!--"
COMMENT_CLOSE = "-->"
COMMENT_LINE_RE = re.compile(r"^(?: {0,3})<!--")
INDENTED_CODE_RE = re.compile(r"^(?: {4,}|\t)")


def die(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read_fence_marker(line: str) -> tuple[str, int, str] | None:
    match = FENCE_RE.match(line)
    if not match:
        return None
    marker = match.group("marker")
    return marker[0], len(marker), match.group("suffix") or ""


def _advance_comment_depth(depth: int, line: str) -> int:
    if depth == 0 and not COMMENT_LINE_RE.match(line):
        return 0

    index = 0
    active = depth
    while index < len(line):
        next_open = line.find(COMMENT_OPEN, index)
        next_close = line.find(COMMENT_CLOSE, index)
        if next_open == -1 and next_close == -1:
            break
        if next_open != -1 and (next_close == -1 or next_open < next_close):
            active += 1
            index = next_open + len(COMMENT_OPEN)
            continue
        if active > 0:
            active -= 1
        index = next_close + len(COMMENT_CLOSE)
    return active


def visible_heading_lines(lines: list[str]) -> list[tuple[int, int, str]]:
    headings: list[tuple[int, int, str]] = []
    fence: tuple[str, int] | None = None
    comment_depth = 0

    for index, line in enumerate(lines, start=1):
        body = line[:-1] if line.endswith("\n") else line
        if fence is not None:
            marker = _read_fence_marker(body)
            if (
                marker
                and marker[0] == fence[0]
                and marker[1] >= fence[1]
                and FENCE_CLOSE_SUFFIX_RE.match(marker[2])
            ):
                fence = None
            continue

        if comment_depth > 0 or COMMENT_LINE_RE.match(body):
            comment_depth = _advance_comment_depth(comment_depth, body)
            continue

        if INDENTED_CODE_RE.match(body):
            continue

        marker = _read_fence_marker(body)
        if marker:
            fence = (marker[0], marker[1])
            continue

        match = HEADING_RE.match(body)
        if match:
            headings.append((index, len(match.group(1)), match.group(2).strip()))

    return headings


def assign_section_ids(headings: list[tuple[int, int, str]]) -> list[tuple[str, int, int, str]]:
    stack: list[tuple[int, int]] = []
    child_counts: dict[tuple[int, ...], int] = {}
    assigned: list[tuple[str, int, int, str]] = []

    for line, level, title in headings:
        while stack and stack[-1][0] >= level:
            stack.pop()
        parent_key = tuple(number for _, number in stack)
        next_number = child_counts.get(parent_key, 0) + 1
        child_counts[parent_key] = next_number
        stack.append((level, next_number))
        section_id = "S" + ".".join(str(number) for _, number in stack)
        assigned.append((section_id, line, level, title))

    return assigned


def section_end_line(index: int, sections: list[tuple[str, int, int, str]], total_lines: int) -> int:
    _, line_start, level, _ = sections[index]
    for _, next_start, next_level, _ in sections[index + 1 :]:
        if next_level <= level:
            return next_start - 1
    return total_lines if total_lines else line_start


def build_manifest(spec_path: Path, fallback_policy: str) -> dict:
    if fallback_policy not in FALLBACK_POLICIES:
        die(f"invalid fallback policy: {fallback_policy}")
    try:
        text = spec_path.read_text(encoding="utf-8")
    except OSError:
        die(f"spec is not readable: {spec_path}")

    lines = text.splitlines(keepends=True)
    total_lines = len(lines)
    headings = visible_heading_lines(lines)
    sections: dict[str, dict] = {}
    section_order: list[str] = []

    if not headings:
        section_text = text
        sections["S0"] = {
            "id": "S0",
            "title": "document",
            "level": 0,
            "line_start": 1,
            "line_end": total_lines if total_lines else 1,
            "chars": len(section_text),
            "sha256": sha256_text(section_text),
        }
        section_order.append("S0")
    else:
        assigned = assign_section_ids(headings)
        for index, (section_id, line_start, level, title) in enumerate(assigned):
            line_end = section_end_line(index, assigned, total_lines)
            section_text = "".join(lines[line_start - 1 : line_end])
            sections[section_id] = {
                "id": section_id,
                "title": title,
                "level": level,
                "line_start": line_start,
                "line_end": line_end,
                "chars": len(section_text),
                "sha256": sha256_text(section_text),
            }
            section_order.append(section_id)

    return {
        "schema_version": "1",
        "spec_path": str(spec_path),
        "spec_sha256": sha256_text(text),
        "spec_total_chars": len(text),
        "fallback_policy": fallback_policy,
        "sections": sections,
        "section_order": section_order,
        "task_to_sections": {},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec_path")
    parser.add_argument("--output")
    parser.add_argument("--fallback-policy", default="full_spec_on_blocker")
    args = parser.parse_args()

    spec_path = Path(args.spec_path).expanduser().resolve()
    manifest = build_manifest(spec_path, args.fallback_policy)
    text = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        output = Path(args.output).expanduser()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
        print(output)
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
