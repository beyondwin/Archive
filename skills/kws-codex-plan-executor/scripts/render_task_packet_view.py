#!/usr/bin/env python3
"""Render a task packet JSON file as a deterministic human-readable markdown view."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


REQUIRED_TOP_LEVEL = {
    "task_id",
    "task_title",
    "task_body",
    "files",
    "acceptance",
    "spec",
    "write_policy",
    "context_budget",
}


def die(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def load_packet(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        die(f"task packet is not readable: {path}: {exc}")
    except json.JSONDecodeError as exc:
        die(f"task packet is invalid JSON: {path}: {exc}")
    if not isinstance(payload, dict):
        die("task packet must be a JSON object")
    missing = sorted(REQUIRED_TOP_LEVEL.difference(payload))
    if missing:
        die(f"task packet missing field(s): {', '.join(missing)}")
    return payload


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def list_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]


def bullet_list(items: list[str], fallback: str) -> str:
    values = items or [fallback]
    return "\n".join(f"- {item}" for item in values)


def acceptance_lines(acceptance: dict[str, Any]) -> tuple[list[str], list[str]]:
    command = acceptance.get("command")
    source = acceptance.get("source", "unknown")
    if isinstance(command, str) and command.strip():
        return [f"source: {source}"], [command.strip()]
    return ["missing acceptance command"], ["honest substitute required"]


def render_packet_view(packet: dict[str, Any]) -> str:
    acceptance = packet.get("acceptance")
    spec = packet.get("spec")
    write_policy = packet.get("write_policy")
    budget = packet.get("context_budget")
    decisions = packet.get("decisions_register") if isinstance(packet.get("decisions_register"), dict) else {}
    unit_manifest = packet.get("unit_manifest") if isinstance(packet.get("unit_manifest"), dict) else {}
    if not isinstance(acceptance, dict):
        die("task packet acceptance must be an object")
    if not isinstance(spec, dict):
        die("task packet spec must be an object")
    if not isinstance(write_policy, dict):
        die("task packet write_policy must be an object")
    if not isinstance(budget, dict):
        die("task packet context_budget must be an object")

    files = list_strings(packet.get("files"))
    forbidden = list_strings(write_policy.get("forbidden_write_globs"))
    for item in list_strings(unit_manifest.get("forbidden_write_globs")):
        if item not in forbidden:
            forbidden.append(item)
    ac_lines, verification_lines = acceptance_lines(acceptance)
    section_ids = list_strings(spec.get("section_ids"))
    fallback_notes = ["- warning: full spec fallback"] if spec.get("fallback_used") is True else ["- warning: none"]
    mapping = spec.get("mapping") if isinstance(spec.get("mapping"), dict) else {}
    suggested_patch = mapping.get("suggested_plan_patch")
    if isinstance(suggested_patch, str) and suggested_patch.strip():
        fallback_notes.append(f"- Suggested plan patch: `{suggested_patch}`")
    included_decisions = decisions.get("included") if isinstance(decisions.get("included"), list) else []

    lines = [
        f"# Task {packet.get('task_id')}: {packet.get('task_title') or '(untitled)'}",
        "",
        "## 읽을 파일",
        bullet_list(files, "no files declared"),
        "",
        "## 작업",
        str(packet.get("task_body") or "").strip() or "missing task body",
        "",
        "## AC",
        bullet_list(ac_lines, "missing acceptance criteria"),
        "",
        "## 검증",
        bullet_list(verification_lines, "honest substitute required"),
        "",
        "## 금지사항",
        bullet_list(forbidden, "no forbidden globs declared"),
        "",
        "## Context Notes",
        f"- spec sections: {', '.join(section_ids) if section_ids else 'missing'}",
        f"- context budget: {budget.get('status', 'unknown')}, {budget.get('estimated_chars', 'unknown')}/{budget.get('max_chars', 'unknown')}",
        f"- decisions included: {len(included_decisions)}",
        *fallback_notes,
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-packet", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    packet = load_packet(Path(args.task_packet).expanduser())
    text = render_packet_view(packet)
    output = Path(args.output).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    print(json.dumps({"path": str(output), "sha256": sha256_text(text)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
