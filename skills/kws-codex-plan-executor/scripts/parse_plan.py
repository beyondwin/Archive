#!/usr/bin/env python3
"""Extract executable tasks from a Markdown implementation plan."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


TASK_RE = re.compile(r"(?m)^(#{2,4})\s+(?:Task|작업)\s+(\d+)\s*(?::|-|–)\s*(.+?)\s*$")
FENCE_RE = re.compile(r"^(?: {0,3})(?P<marker>`{3,}|~{3,})(?P<suffix>[^\r\n]*)$")
FENCE_CLOSE_SUFFIX_RE = re.compile(r"^[ \t]*$")
COMMENT_OPEN = "<!--"
COMMENT_CLOSE = "-->"
COMMENT_LINE_RE = re.compile(r"^(?: {0,3})<!--")
INDENTED_CODE_RE = re.compile(r"^(?: {4,}|\t)")
FILES_HEADING_RE = re.compile(
    r"(?mi)^[ \t]*(?:\*\*)?"
    r"(?:Files|Affected files|Modified files|Changed files|수정 파일|변경 파일|대상 파일|파일)"
    r"[ \t]*:[ \t]*(?:\*\*)?[ \t]*$"
)
AC_RE = re.compile(r"(?mi)^\s*(#{2,5}\s*)?(Acceptance Criteria|Verification|검증)\b")
DEPENDS_RE = re.compile(
    r"(?mi)^[ \t]*(?:\*\*)?"
    r"(?:Depends on|Depends|Dependencies|의존|선행 작업)"
    r"[ \t]*:[ \t]*(?P<value>.+?)[ \t]*(?:\*\*)?[ \t]*$"
)
SPEC_REFS_RE = re.compile(
    r"(?mi)^[ \t]*(?:\*\*)?"
    r"(?:Spec Refs|Spec refs|Spec references|스펙 참조)"
    r"[ \t]*:[ \t]*(?:\*\*)?[ \t]*(?P<value>.+?)[ \t]*(?:\*\*)?[ \t]*$"
)
SPEC_REF_RE = re.compile(r"\bS\d+(?:\.\d+)*\b")
FILE_LINE_RE = re.compile(
    r"^\s*-\s+"
    r"(?:(?:Create|Modify|Read|Delete|Move|Update|생성|수정|읽기|삭제|이동|변경|갱신):\s*)?"
    r"`?([^`\n]+?)`?\s*$"
)
EXECUTION_MODES = {"interactive", "headless"}


def _die(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


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


def _read_fence_marker(line: str) -> tuple[str, int, str] | None:
    match = FENCE_RE.match(line)
    if not match:
        return None
    marker = match.group("marker")
    return marker[0], len(marker), match.group("suffix") or ""


def _visible_markdown(markdown: str) -> str:
    """Blank hidden Markdown regions while preserving line positions."""
    visible: list[str] = []
    fence: tuple[str, int] | None = None
    comment_depth = 0

    for line in markdown.splitlines(keepends=True):
        body = line[:-1] if line.endswith("\n") else line
        newline = "\n" if line.endswith("\n") else ""

        if fence is not None:
            marker = _read_fence_marker(body)
            if (
                marker
                and marker[0] == fence[0]
                and marker[1] >= fence[1]
                and FENCE_CLOSE_SUFFIX_RE.match(marker[2])
            ):
                fence = None
            visible.append(newline)
            continue

        if comment_depth > 0 or COMMENT_LINE_RE.match(body):
            comment_depth = _advance_comment_depth(comment_depth, body)
            visible.append(newline)
            continue

        if INDENTED_CODE_RE.match(body):
            visible.append(newline)
            continue

        marker = _read_fence_marker(body)
        if marker:
            fence = (marker[0], marker[1])
            visible.append(newline)
            continue

        visible.append(line)

    return "".join(visible)


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


def _line_number(markdown: str, offset: int) -> int:
    return markdown.count("\n", 0, offset) + 1


def _extract_files(body: str, repo_root: Path, body_start_line: int) -> tuple[list[str], bool, dict[str, int]]:
    match = FILES_HEADING_RE.search(body)
    if not match:
        return [], False, {}

    files: list[str] = []
    locations: dict[str, int] = {}
    base_line = body_start_line + body.count("\n", 0, match.start())
    for line_offset, line in enumerate(body[match.end() :].splitlines(), start=1):
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
        repo_path = _repo_relative(value, repo_root)
        files.append(repo_path)
        locations.setdefault(repo_path, base_line + line_offset - 1)

    return sorted(dict.fromkeys(files)), True, locations


def _extract_depends_on(body: str) -> list[str]:
    match = DEPENDS_RE.search(body)
    if not match:
        return []
    values = []
    for item in re.split(r"[, ]+", match.group("value").strip()):
        normalized = item.strip().removeprefix("task_")
        if normalized.isdigit():
            values.append(f"task_{normalized}")
    return sorted(dict.fromkeys(values))


def _extract_spec_refs(body: str) -> list[str]:
    match = SPEC_REFS_RE.search(body)
    if not match:
        return []
    return list(dict.fromkeys(SPEC_REF_RE.findall(match.group("value"))))


def _body_line_range(markdown: str, body_start: int, body_end: int) -> tuple[int, int]:
    body = markdown[body_start:body_end]
    base_line = _line_number(markdown, body_start)
    first: int | None = None
    last: int | None = None
    for offset, line in enumerate(body.splitlines()):
        if line.strip():
            if first is None:
                first = base_line + offset
            last = base_line + offset
    if first is None:
        return base_line, base_line
    return first, last if last is not None else first


def _validate_task_dependencies(tasks: list[dict]) -> None:
    ids = {task["id"] for task in tasks}
    for task in tasks:
        for dep in task.get("depends_on", []):
            if dep not in ids:
                _die(f"{task['id']} depends on unknown task: {dep}")

    visiting: set[str] = set()
    visited: set[str] = set()
    by_id = {task["id"]: task for task in tasks}

    def visit(task_id: str) -> None:
        if task_id in visited:
            return
        if task_id in visiting:
            _die(f"cycle detected at task: {task_id}")
        visiting.add(task_id)
        for dep in by_id[task_id].get("depends_on", []):
            visit(dep)
        visiting.remove(task_id)
        visited.add(task_id)

    for task in tasks:
        visit(task["id"])


def parse_plan(plan_path: Path, repo_root: Path, mode: str) -> dict:
    raw_markdown = plan_path.read_text(encoding="utf-8")
    markdown = _visible_markdown(raw_markdown)
    matches = list(TASK_RE.finditer(markdown))
    if not matches:
        _die("plan has no Task N headings")

    tasks = []
    for index, match in enumerate(matches):
        body_start = match.end()
        body_end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        body_raw = markdown[body_start:body_end]
        body = body_raw.strip()
        body_line_start, body_line_end = _body_line_range(markdown, body_start, body_end)
        files, has_files, file_line_numbers = _extract_files(body_raw, repo_root, _line_number(markdown, body_start))
        if mode in EXECUTION_MODES and not has_files:
            _die(f"task_{match.group(2)} has no Files block")
        tasks.append(
            {
                "id": f"task_{match.group(2)}",
                "number": int(match.group(2)),
                "title": match.group(3).strip(),
                "line": _line_number(markdown, match.start()),
                "body": body,
                "body_line_start": body_line_start,
                "body_line_end": body_line_end,
                "files": files,
                "file_line_numbers": file_line_numbers,
                "spec_refs": _extract_spec_refs(body_raw),
                "depends_on": _extract_depends_on(body),
                "has_acceptance_criteria": bool(AC_RE.search(body)),
            }
        )
    _validate_task_dependencies(tasks)

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
