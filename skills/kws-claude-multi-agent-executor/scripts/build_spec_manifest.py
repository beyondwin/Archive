#!/usr/bin/env python3
"""Build a spec manifest (sections shape) from a Markdown spec file.

Stdlib-only. Emits JSON to stdout matching `spec_manifest.sections`:
    {section_id: {title, range, chars, anchor, level}, ...}

Algorithm (see spec.md §C1.2 + plan.md Task 0):
  1. Detect fenced code block ranges (``` or ~~~) — headings inside ignored.
  2. Detect HTML comment ranges (<!-- ... -->, possibly multi-line) —
     headings inside ignored.
  3. Walk headings outside those ranges (^#{1,6}\\s+).
  4. Hierarchical section IDs via a level-stack; a new heading at depth d
     truncates the stack to length d-1 then increments/appends counter d.
  5. A section's range closes when the next heading at SAME OR HIGHER
     level appears (i.e. depth <= current). Children at deeper depth are
     contained within the parent's range.
  6. chars = sum of len(line) including newlines (preserved via splitlines
     with keepends=True).
  7. anchor: lowercase, non-alphanumerics -> '-', collapse runs, strip
     leading/trailing '-'.

Edge cases:
  * Empty file:   {"S0": {title "(empty)", range [1,1], chars 0,
                         anchor "empty", level 0}}
  * No headings:  single "S0" covering whole file, title "(no-headings)",
                  anchor "no-headings", level 0.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
FENCE_RE = re.compile(r"^(\s{0,3})(`{3,}|~{3,})")
ANCHOR_NONALNUM_RE = re.compile(r"[^a-z0-9]+")


def _compute_code_block_lines(lines: list[str]) -> set[int]:
    """Return set of 0-indexed line numbers that fall inside fenced code blocks.

    Lines containing the opening/closing fence themselves are also included
    (so headings on those lines — though they wouldn't match anyway — are
    treated as inside).
    """
    inside: set[int] = set()
    open_marker: str | None = None  # the fence char repeated, e.g. "```"
    for i, line in enumerate(lines):
        if open_marker is None:
            m = FENCE_RE.match(line)
            if m:
                open_marker = m.group(2)[0]  # ` or ~
                inside.add(i)
        else:
            inside.add(i)
            m = FENCE_RE.match(line)
            if m and m.group(2)[0] == open_marker:
                open_marker = None
    return inside


def _compute_html_comment_lines(text: str, lines: list[str]) -> set[int]:
    """Return set of 0-indexed line numbers covered by <!-- ... --> comments.

    A line is considered "covered" if any character on it lies between an
    opening `<!--` and its closing `-->` (inclusive of the marker lines).
    Uses character offsets so multi-line comments are handled correctly.
    Unclosed `<!--` covers through EOF.
    """
    covered: set[int] = set()
    if "<!--" not in text:
        return covered

    # Pre-compute, for each character offset, the line it belongs to.
    line_starts: list[int] = []
    off = 0
    for ln in lines:
        line_starts.append(off)
        off += len(ln)
    total_len = off

    def line_of(pos: int) -> int:
        # Binary search would be faster, but file sizes here are small.
        lo, hi = 0, len(line_starts) - 1
        while lo <= hi:
            mid = (lo + hi) // 2
            if line_starts[mid] <= pos:
                lo = mid + 1
            else:
                hi = mid - 1
        return hi  # largest index with line_starts[idx] <= pos

    i = 0
    while True:
        start = text.find("<!--", i)
        if start == -1:
            break
        end = text.find("-->", start + 4)
        if end == -1:
            end_pos = total_len - 1 if total_len > 0 else start
            i = total_len  # exit after this
        else:
            end_pos = end + 2  # last char of '-->'
            i = end_pos + 1
        s_line = line_of(start)
        e_line = line_of(end_pos)
        for ln in range(s_line, e_line + 1):
            covered.add(ln)
        if end == -1:
            break
    return covered


def _anchor(text: str) -> str:
    a = ANCHOR_NONALNUM_RE.sub("-", text.lower())
    return a.strip("-")


def build_manifest(text: str) -> dict[str, dict]:
    """Return the sections manifest dict for the given file text."""
    if text == "":
        return {
            "S0": {
                "title": "(empty)",
                "range": [1, 1],
                "chars": 0,
                "anchor": "empty",
                "level": 0,
            }
        }

    lines = text.splitlines(keepends=True)
    total_lines = len(lines)
    total_chars = sum(len(ln) for ln in lines)

    code_lines = _compute_code_block_lines(lines)
    comment_lines = _compute_html_comment_lines(text, lines)
    skip = code_lines | comment_lines

    # Collect headings: list of (line_idx_0based, depth, title)
    headings: list[tuple[int, int, str]] = []
    for i, line in enumerate(lines):
        if i in skip:
            continue
        m = HEADING_RE.match(line)
        if not m:
            continue
        depth = len(m.group(1))
        title = m.group(2).strip()
        headings.append((i, depth, title))

    if not headings:
        return {
            "S0": {
                "title": "(no-headings)",
                "range": [1, total_lines],
                "chars": total_chars,
                "anchor": "no-headings",
                "level": 0,
            }
        }

    # Assign hierarchical IDs via a level-stack.
    # stack[i] is the current counter at level (i+1).
    stack: list[int] = []
    ids: list[str] = []
    for _line_idx, depth, _title in headings:
        if len(stack) >= depth:
            # Sibling or shallower: truncate to depth, then bump counter.
            stack = stack[:depth]
            stack[-1] += 1
        else:
            # Deeper than current: pad missing intermediate levels with 1,
            # then start counter at 1 for the new depth.
            while len(stack) < depth - 1:
                stack.append(1)
            stack.append(1)
        ids.append("S" + ".".join(str(n) for n in stack))

    # Compute ranges: a section closes when the next heading with depth <=
    # current depth appears.
    result: dict[str, dict] = {}
    n = len(headings)
    for idx in range(n):
        line_idx, depth, title = headings[idx]
        end_line_idx = total_lines - 1  # 0-based inclusive
        for jdx in range(idx + 1, n):
            n_line, n_depth, _ = headings[jdx]
            if n_depth <= depth:
                end_line_idx = n_line - 1
                break
        chars = sum(len(lines[k]) for k in range(line_idx, end_line_idx + 1))
        result[ids[idx]] = {
            "title": title,
            "range": [line_idx + 1, end_line_idx + 1],
            "chars": chars,
            "anchor": _anchor(title),
            "level": depth,
        }

    return _sorted_natural(result)


def _sorted_natural(d: dict[str, dict]) -> dict[str, dict]:
    """Sort sections by hierarchical path (numeric tuple from 'S1.2.3')."""
    def key(sid: str) -> tuple[int, ...]:
        body = sid[1:] if sid.startswith("S") else sid
        if not body:
            return ()
        try:
            return tuple(int(p) for p in body.split("."))
        except ValueError:
            return ()

    return {k: d[k] for k in sorted(d, key=key)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build a spec sections manifest as JSON on stdout."
    )
    parser.add_argument("spec_path", help="Path to the Markdown spec file.")
    args = parser.parse_args(argv)

    path = Path(args.spec_path)
    if not path.exists():
        print(f"error: spec file not found: {path}", file=sys.stderr)
        return 2
    text = path.read_text(encoding="utf-8")
    manifest = build_manifest(text)
    json.dump(manifest, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
