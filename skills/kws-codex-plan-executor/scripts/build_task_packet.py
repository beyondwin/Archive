#!/usr/bin/env python3
"""Build one canonical CPE v3 task-packet draft."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from cpe_runtime.packets import PacketDraft, build_packet as build_runtime_packet, export_packet


def die(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        die(f"JSON file is not readable or valid: {path}: {exc}")


def _find_task(plan: dict, task_id: str) -> dict:
    tasks = plan.get("tasks")
    if not isinstance(tasks, list):
        raise ValueError("plan_tasks_invalid")
    matches = [task for task in tasks if isinstance(task, dict) and task.get("id") == task_id]
    if len(matches) != 1:
        raise ValueError(f"unknown_task_id:{task_id}")
    return matches[0]


def _compiled_task(plan: dict, task_id: str, manifest: dict) -> dict:
    raw = _find_task(plan, task_id)
    refs = [str(item) for item in raw.get("spec_refs", []) if str(item).strip()]
    if not refs:
        raise ValueError("missing_explicit_spec_mapping")
    files = [str(item) for item in raw.get("files", []) if str(item).strip()]
    if not files:
        raise ValueError("files_missing")
    acceptance = str(raw.get("acceptance_command") or "").strip()
    if not acceptance:
        raise ValueError("acceptance_command_missing")
    sections = manifest.get("sections") if isinstance(manifest, dict) else None
    if not isinstance(sections, dict):
        raise ValueError("spec_manifest_invalid")
    unknown = [ref for ref in refs if ref not in sections]
    if unknown:
        raise ValueError(f"unknown_spec_ref:{unknown[0]}")
    plan_path = Path(str(plan.get("plan") or "")).expanduser()
    if not plan_path.is_file():
        raise ValueError("plan_snapshot_missing")
    return {
        "id": task_id,
        "title": str(raw.get("title") or task_id),
        "dependencies": [str(item) for item in raw.get("depends_on", [])],
        "file_claims": files,
        "spec_refs": refs,
        "acceptance_command": acceptance,
        "plan_line": raw.get("line"),
        "prompt": str(raw.get("body") or task_id),
        "execution_contract": {
            "allowed_paths": files,
            "forbidden_paths": ["run_manifest.json", "events.jsonl", "state.json"],
            "acceptance_command": acceptance,
        },
        "source_hashes": {
            "plan": hashlib.sha256(plan_path.read_bytes()).hexdigest(),
            "spec_sections": {ref: str(sections[ref].get("sha256") or "") for ref in refs},
        },
    }


def build_packet(
    plan: dict,
    task_id: str,
    spec_path: Path,
    manifest: dict,
    decisions: list[dict] | None = None,
    max_chars: int = 60000,
    context_threshold: float = 0.70,
    fallback_policy: str = "halt_on_blocker",
) -> PacketDraft:
    del decisions, max_chars, context_threshold, fallback_policy
    task = _compiled_task(plan, task_id, manifest)
    spec_path = spec_path.expanduser()
    content = spec_path.read_bytes()
    compiled = SimpleNamespace(
        tasks=(task,),
        spec_manifest=manifest,
        sources=(SimpleNamespace(role="spec", content=content, sha256=hashlib.sha256(content).hexdigest()),),
    )
    return build_runtime_packet(compiled, task)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan-json", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--spec-manifest", required=True)
    parser.add_argument("--decisions")
    parser.add_argument("--max-chars", type=int, default=60000)
    parser.add_argument("--context-threshold", type=float, default=0.70)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    plan = load_json(Path(args.plan_json).expanduser())
    manifest = load_json(Path(args.spec_manifest).expanduser())
    if not isinstance(plan, dict) or not isinstance(manifest, dict):
        die("plan and spec manifest must be JSON objects")
    try:
        draft = build_packet(plan, args.task_id, Path(args.spec), manifest)
    except (OSError, ValueError) as exc:
        die(str(exc))
    output = Path(args.output).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        export_packet(output, draft)
    except OSError as exc:
        die(f"output is not an unused regular path: {output}: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
