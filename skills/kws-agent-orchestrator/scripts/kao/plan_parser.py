from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from .models import FileClaim, TaskSpec


BLOCK_RE = re.compile(r"```yaml kao-task\n(.*?)\n```", re.DOTALL)
TASK_HEADING_RE = re.compile(r"^(#{2,6})\s+Task\s+\d+:\s+(.+?)\s*$", re.MULTILINE)
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)


class PlanParseError(ValueError):
    pass


def _canonical_text(path: Path) -> str:
    lines = path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return "\n".join(line.rstrip() for line in lines).rstrip() + "\n"


def canonical_hash(path: Path) -> str:
    return "sha256:" + hashlib.sha256(_canonical_text(path).encode("utf-8")).hexdigest()


def _parse_inline_value(value: str) -> Any:
    value = value.strip()
    if value in {"true", "false"}:
        return value == "true"
    if value == "[]":
        return []
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        return [] if not inner else [item.strip().strip("'\"") for item in inner.split(",")]
    if value.startswith("{") and value.endswith("}"):
        data: dict[str, str] = {}
        inner = value[1:-1].strip()
        if inner:
            for part in inner.split(","):
                key, item = part.split(":", 1)
                data[key.strip()] = item.strip().strip("'\"")
        return data
    return value.strip("'\"")


def _parse_yamlish(block: str) -> dict[str, Any]:
    data: dict[str, Any] = {}
    lines = block.splitlines()
    index = 0
    while index < len(lines):
        raw = lines[index]
        if not raw.strip():
            index += 1
            continue
        if raw.startswith(" ") or ":" not in raw:
            raise PlanParseError(f"cannot parse kao-task line: {raw}")
        key, value = raw.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value:
            data[key] = _parse_inline_value(value)
            index += 1
            continue
        items: list[Any] = []
        index += 1
        while index < len(lines):
            item_line = lines[index]
            stripped = item_line.strip()
            if not stripped:
                index += 1
                continue
            if not item_line.startswith(" "):
                break
            if stripped.startswith("- "):
                items.append(_parse_inline_value(stripped[2:]))
            index += 1
        data[key] = items
    return data


def _task_objective(section: str, block_match: re.Match[str]) -> str:
    objective = section[block_match.end() :].strip()
    return objective


def _build_task(data: dict[str, Any], objective: str, line: int) -> TaskSpec:
    required = ("task_id", "title", "risk", "phase", "dependencies", "spec_refs", "file_claims", "acceptance_commands")
    missing = [key for key in required if key not in data]
    if missing:
        raise PlanParseError(f"missing required kao-task fields: {', '.join(missing)}")
    claims = tuple(FileClaim(str(item["path"]), str(item["mode"])) for item in data.get("file_claims", []))
    return TaskSpec(
        task_id=str(data["task_id"]),
        title=str(data["title"]),
        risk=str(data["risk"]),  # type: ignore[arg-type]
        phase=str(data["phase"]),
        dependencies=tuple(str(item) for item in data.get("dependencies", [])),
        spec_refs=tuple(str(item) for item in data.get("spec_refs", [])),
        file_claims=claims,
        acceptance_commands=tuple(str(item) for item in data.get("acceptance_commands", [])),
        resource_keys=tuple(str(item) for item in data.get("resource_keys", [])),
        required_skills=tuple(str(item) for item in data.get("required_skills", [])),
        serial=bool(data.get("serial", False)),
        objective=objective,
        line=line,
    )


def parse_plan(path: Path) -> list[TaskSpec]:
    text = path.read_text(encoding="utf-8")
    headings = list(TASK_HEADING_RE.finditer(text))
    if not headings:
        if "Task" in text:
            raise PlanParseError("missing kao-task block")
        blocks = list(BLOCK_RE.finditer(text))
        return [_build_task(_parse_yamlish(block.group(1)), _task_objective(text, block), text[: block.start()].count("\n") + 1) for block in blocks]
    tasks: list[TaskSpec] = []
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        section = text[heading.end() : end]
        block = BLOCK_RE.search(section)
        if block is None:
            raise PlanParseError(f"missing kao-task block under {heading.group(2)}")
        line = text[: heading.start()].count("\n") + 1
        tasks.append(_build_task(_parse_yamlish(block.group(1)), _task_objective(section, block), line))
    return tasks


def parse_spec_manifest(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    headings = [(m.start(), m.end(), len(m.group(1)), m.group(2).strip(), text[: m.start()].count("\n") + 1) for m in HEADING_RE.finditer(text)]
    sections: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    stack: list[tuple[int, int]] = []
    counts: dict[tuple[int, ...], int] = {}
    for idx, (_, _, level, title, line_start) in enumerate(headings):
        while stack and stack[-1][0] >= level:
            stack.pop()
        key = tuple(number for _, number in stack)
        number = counts.get(key, 0) + 1
        counts[key] = number
        stack.append((level, number))
        section_id = "S" + ".".join(str(n) for _, n in stack)
        next_start = len(lines)
        for _, _, next_level, _, next_line in headings[idx + 1 :]:
            if next_level <= level:
                next_start = next_line - 1
                break
        body = "".join(lines[line_start - 1 : next_start])
        sections[section_id] = {
            "id": section_id,
            "title": title,
            "level": level,
            "line_start": line_start,
            "line_end": next_start,
            "text": body,
            "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        }
        order.append(section_id)
    return {"sections": sections, "section_order": order, "spec_hash": canonical_hash(path)}
