#!/usr/bin/env python3
"""Extract executable tasks from a Markdown implementation plan."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


TASK_RE = re.compile(r"(?m)^(#{2,4})\s+Task\s+(\d+)\s*:\s*(.+?)\s*$")
FILES_HEADING_RE = re.compile(r"(?mi)^\s*\*\*Files:\*\*\s*$|^\s*Files:\s*$")
AC_RE = re.compile(r"(?mi)^\s*(#{2,5}\s*)?(Acceptance Criteria|Verification|검증)\b")
FILE_LINE_RE = re.compile(r"^\s*-\s+(?:(?:Create|Modify|Read|Delete|Move|Update):\s*)?`?([^`\n]+?)`?\s*$")
EXECUTION_MODES = {"interactive", "headless"}


def _die(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def _repo_relative(path_text: str, repo_root: Path) -> str:
    candidate = path_text.strip()
    if not candidate:
        _die("empty file path in Files block")
    if " -> " in candidate:
        candidate = candidate.split(" -> ", 1)[-1].strip()
    if "#" in candidate:
        candidate = candidate.split("#", 1)[0].strip()

    path = Path(candidate)
    if path.is_absolute():
        resolved = path.resolve(strict=False)
    else:
        resolved = (repo_root / path).resolve(strict=False)

    try:
        rel = resolved.relative_to(repo_root)
    except ValueError:
        _die(f"out-of-repo path in Files block: {path_text}")
    if any(part == ".." for part in rel.parts):
        _die(f"out-of-repo path in Files block: {path_text}")
    return rel.as_posix()


def _extract_files(body: str, repo_root: Path) -> tuple[list[str], bool]:
    match = FILES_HEADING_RE.search(body)
    if not match:
        return [], False

    files: list[str] = []
    for line in body[match.end() :].splitlines():
        stripped = line.strip()
        if not stripped:
            if files:
                break
            continue
        if stripped.startswith("#") or (stripped.startswith("**") and stripped.endswith("**")):
            break
        item = FILE_LINE_RE.match(line)
        if not item:
            if files:
                break
            continue
        value = item.group(1).strip()
        if value.lower() in {"n/a", "none"}:
            continue
        files.append(_repo_relative(value, repo_root))

    return sorted(dict.fromkeys(files)), True


def parse_plan(plan_path: Path, repo_root: Path, mode: str) -> dict:
    markdown = plan_path.read_text(encoding="utf-8")
    matches = list(TASK_RE.finditer(markdown))
    if not matches:
        _die("plan has no Task N headings")

    tasks = []
    for index, match in enumerate(matches):
        body_start = match.end()
        body_end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        body = markdown[body_start:body_end].strip()
        files, has_files = _extract_files(body, repo_root)
        if mode in EXECUTION_MODES and not has_files:
            _die(f"task_{match.group(2)} has no Files block")
        tasks.append(
            {
                "id": f"task_{match.group(2)}",
                "number": int(match.group(2)),
                "title": match.group(3).strip(),
                "body": body,
                "files": files,
                "has_acceptance_criteria": bool(AC_RE.search(body)),
            }
        )

    return {
        "plan": str(plan_path),
        "mode": mode,
        "tasks": tasks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, help="Markdown implementation plan")
    parser.add_argument("--repo-root", required=True, help="Repository root used to validate paths")
    parser.add_argument("--mode", choices=["interactive", "headless", "prompt", "handoff"], default="interactive")
    parser.add_argument("--output", help="Write parsed JSON to this path")
    args = parser.parse_args()

    plan_path = Path(args.plan).expanduser().resolve()
    repo_root = Path(args.repo_root).expanduser().resolve()
    if not plan_path.is_file():
        _die(f"plan is not readable: {plan_path}")
    if not repo_root.is_dir():
        _die(f"repo root is not a directory: {repo_root}")

    payload = parse_plan(plan_path, repo_root, args.mode)
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
