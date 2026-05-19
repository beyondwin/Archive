#!/usr/bin/env python3
"""Build compact per-task context packets from a parsed plan and spec manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path


FALLBACK_POLICIES = {"full_spec_on_blocker", "halt_on_blocker"}
DEFAULT_FORBIDDEN_GLOBS = [".git/**", "graphify-out/**"]


def die(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        die(f"JSON file is not readable: {path}: {exc}")
    except json.JSONDecodeError as exc:
        die(f"JSON file is invalid: {path}: {exc}")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def find_task(plan: dict, task_id: str) -> dict:
    for task in plan.get("tasks", []):
        if task.get("id") == task_id:
            return task
    die(f"unknown task id: {task_id}")


def section_text(spec_text: str, section: dict) -> str:
    lines = spec_text.splitlines(keepends=True)
    start = int(section.get("line_start", 1))
    end = int(section.get("line_end", start))
    return "".join(lines[start - 1 : end])


def tokenize(value: str) -> set[str]:
    return {token for token in re.split(r"[^a-z0-9]+", value.lower()) if token}


def path_tokens(files: list[str]) -> set[str]:
    tokens: set[str] = set()
    for file_path in files:
        tokens.update(tokenize(file_path))
        path = Path(file_path)
        tokens.update(tokenize(path.stem))
        tokens.update(tokenize(" ".join(path.parts)))
    return tokens


def heuristic_sections(task: dict, manifest: dict) -> list[str]:
    tokens = path_tokens([item for item in task.get("files", []) if isinstance(item, str)])
    if not tokens:
        return []
    matched: list[str] = []
    sections = manifest.get("sections", {})
    for section_id in manifest.get("section_order", []):
        section = sections.get(section_id, {})
        title_tokens = tokenize(str(section.get("title", "")))
        if title_tokens and title_tokens.issubset(tokens):
            matched.append(section_id)
    return matched


def resolve_sections(task: dict, manifest: dict, fallback_policy: str) -> tuple[list[str], bool]:
    sections = manifest.get("sections", {})
    explicit = [item for item in task.get("spec_refs", []) if isinstance(item, str) and item.strip()]
    if explicit:
        for section_id in explicit:
            if section_id not in sections:
                die(f"unknown spec ref for {task.get('id')}: {section_id}")
        return explicit, False

    matched = heuristic_sections(task, manifest)
    if matched:
        return matched, False

    if fallback_policy == "halt_on_blocker":
        die(f"no spec section mapping for {task.get('id')}")
    return ["*"], True


def spec_context(spec_path: Path, manifest: dict, section_ids: list[str], fallback_used: bool) -> tuple[str, str, str]:
    try:
        spec_text = spec_path.read_text(encoding="utf-8")
    except OSError as exc:
        die(f"spec is not readable: {spec_path}: {exc}")

    if fallback_used:
        return "full", "*", "## Spec context (full spec fallback)\n\n" + spec_text

    sections = manifest.get("sections", {})
    bodies = [section_text(spec_text, sections[section_id]) for section_id in section_ids]
    label = ", ".join(section_ids)
    return "slice", label, f"## Spec context (sections: {label})\n\n" + "\n".join(bodies)


def load_decisions(path: Path | None) -> list[dict]:
    if path is None or not path.exists():
        return []
    payload = load_json(path)
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("decisions_register"), list):
        return payload["decisions_register"]
    if isinstance(payload, dict) and isinstance(payload.get("decisions"), list):
        return payload["decisions"]
    die(f"decisions file must contain a list: {path}")


def budget_status(estimated_chars: int, max_chars: int, threshold: float) -> str:
    if estimated_chars > max_chars:
        return "red"
    if estimated_chars > int(max_chars * threshold):
        return "yellow"
    return "green"


def build_packet(
    plan: dict,
    task_id: str,
    spec_path: Path,
    manifest: dict,
    decisions: list[dict],
    max_chars: int,
    context_threshold: float,
    fallback_policy: str,
) -> dict:
    if fallback_policy not in FALLBACK_POLICIES:
        die(f"invalid manifest fallback: {fallback_policy}")
    if max_chars <= 0:
        die("--max-chars must be a positive integer")
    if not 0 < context_threshold <= 1:
        die("--context-threshold must be > 0 and <= 1")

    task = find_task(plan, task_id)
    section_ids, fallback_used = resolve_sections(task, manifest, fallback_policy)
    spec_mode, section_label, spec_text = spec_context(spec_path, manifest, section_ids, fallback_used)
    files = [item for item in task.get("files", []) if isinstance(item, str)]
    packet_base = {
        "schema_version": "1",
        "task_id": task_id,
        "task_title": task.get("title", ""),
        "task_body": task.get("body", ""),
        "files": files,
        "depends_on": task.get("depends_on", []),
        "acceptance": {
            "has_acceptance_criteria": bool(task.get("has_acceptance_criteria")),
            "command": None,
        },
        "spec": {
            "mode": spec_mode,
            "section_ids": section_ids,
            "section_label": section_label,
            "fallback_used": fallback_used,
            "text": spec_text,
        },
        "decisions_register": decisions,
        "write_policy": {
            "allowed_write_globs": files,
            "forbidden_write_globs": DEFAULT_FORBIDDEN_GLOBS,
        },
    }
    estimated_chars = len(json.dumps(packet_base, ensure_ascii=False, sort_keys=True))
    packet_base["context_budget"] = {
        "estimated_chars": estimated_chars,
        "max_chars": max_chars,
        "status": budget_status(estimated_chars, max_chars, context_threshold),
    }
    packet_base["sha256"] = sha256_text(json.dumps(packet_base, ensure_ascii=False, sort_keys=True))
    return packet_base


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan-json", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--spec-manifest", required=True)
    parser.add_argument("--decisions")
    parser.add_argument("--max-chars", type=int, default=60000)
    parser.add_argument("--context-threshold", type=float, default=0.70)
    parser.add_argument("--manifest-fallback", default="full_spec_on_blocker")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    plan = load_json(Path(args.plan_json).expanduser())
    manifest = load_json(Path(args.spec_manifest).expanduser())
    if not isinstance(plan, dict):
        die("plan JSON must be an object")
    if not isinstance(manifest, dict):
        die("spec manifest must be an object")
    decisions = load_decisions(Path(args.decisions).expanduser() if args.decisions else None)
    packet = build_packet(
        plan,
        args.task_id,
        Path(args.spec).expanduser(),
        manifest,
        decisions,
        args.max_chars,
        args.context_threshold,
        args.manifest_fallback,
    )
    output = Path(args.output).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(packet, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
