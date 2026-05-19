#!/usr/bin/env python3
"""Build a per-run context snapshot for kws-codex-plan-executor."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path


HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)


def die(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def repo_relative(path_text: str, repo_root: Path) -> str:
    path = Path(path_text).expanduser()
    resolved = path.resolve(strict=False) if path.is_absolute() else (repo_root / path).resolve(strict=False)
    try:
        rel = resolved.relative_to(repo_root)
    except ValueError:
        die(f"source is outside repo: {path_text}")
    if any(part == ".." for part in rel.parts):
        die(f"source is outside repo: {path_text}")
    if not resolved.is_file():
        die(f"source is not readable: {path_text}")
    return rel.as_posix()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def markdown_sections(text: str) -> list[tuple[str, str]]:
    matches = list(HEADING_RE.finditer(text))
    if not matches:
        return [("document", text)]
    sections: list[tuple[str, str]] = []
    if matches[0].start() > 0:
        sections.append(("preamble", text[: matches[0].start()]))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections.append((match.group(2).strip(), text[match.start():end]))
    return sections


def budget_status(estimated: int, max_chars: int) -> str:
    if estimated > max_chars:
        return "red"
    if estimated > int(max_chars * 0.7):
        return "yellow"
    return "green"


def build_context_budget(repo_root: Path, sources: list[dict], max_chars: int) -> dict:
    included_sections: list[dict] = []
    omitted_sections: list[dict] = []
    estimated_chars = 0
    included_chars = 0

    for source in sources:
        path = source["path"]
        text = (repo_root / path).read_text(encoding="utf-8")
        for section, body in markdown_sections(text):
            record = {
                "role": source["role"],
                "path": path,
                "section": section,
                "estimated_chars": len(body),
                "sha256": sha256_text(body),
            }
            estimated_chars += record["estimated_chars"]
            if included_chars + record["estimated_chars"] <= max_chars:
                included_sections.append(record)
                included_chars += record["estimated_chars"]
            else:
                omitted_sections.append(record)

    status = budget_status(estimated_chars, max_chars)
    if omitted_sections:
        status = "red"
    return {
        "active_strategy": "source_snapshot",
        "packet_count": 0,
        "status": status,
        "max_chars": max_chars,
        "estimated_chars": estimated_chars,
        "included_sections": included_sections,
        "omitted_sections": omitted_sections,
    }


def load_spec_manifest_summary(path_text: str | None) -> dict | None:
    if not path_text:
        return None
    path = Path(path_text).expanduser().resolve()
    if not path.is_file():
        die(f"spec manifest is not readable: {path_text}")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        die(f"spec manifest is invalid JSON: {path_text}: {exc}")
    sections = manifest.get("sections") if isinstance(manifest, dict) else {}
    section_order = manifest.get("section_order") if isinstance(manifest, dict) else []
    return {
        "path": str(path),
        "sha256": sha256_file(path),
        "section_count": len(sections) if isinstance(sections, dict) else 0,
        "section_order": section_order if isinstance(section_order, list) else [],
    }


def build_task_packet_index(path_text: str | None) -> list[dict]:
    if not path_text:
        return []
    packet_dir = Path(path_text).expanduser().resolve()
    if not packet_dir.is_dir():
        die(f"task packet dir is not readable: {path_text}")
    records: list[dict] = []
    for packet_path in sorted(packet_dir.glob("task_*.json")):
        try:
            packet = json.loads(packet_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            die(f"task packet is invalid JSON: {packet_path}: {exc}")
        budget = packet.get("context_budget") if isinstance(packet, dict) else {}
        records.append(
            {
                "task_id": packet.get("task_id") if isinstance(packet, dict) else packet_path.stem,
                "path": str(packet_path),
                "sha256": sha256_file(packet_path),
                "estimated_chars": budget.get("estimated_chars") if isinstance(budget, dict) else None,
            }
        )
    return records


def build_snapshot(
    repo_root: Path,
    run_id: str,
    plan: str,
    spec: str | None,
    docs: list[str],
    max_chars: int,
    spec_manifest: str | None = None,
    task_packet_dir: str | None = None,
) -> dict:
    sources = []
    for role, raw_path in [("plan", plan), ("spec", spec)]:
        if not raw_path:
            continue
        rel = repo_relative(raw_path, repo_root)
        abs_path = repo_root / rel
        sources.append({"role": role, "path": rel, "sha256": sha256_file(abs_path)})
    for raw_path in docs:
        rel = repo_relative(raw_path, repo_root)
        abs_path = repo_root / rel
        sources.append({"role": "doc", "path": rel, "sha256": sha256_file(abs_path)})
    spec_manifest_summary = load_spec_manifest_summary(spec_manifest)
    task_packet_index = build_task_packet_index(task_packet_dir)

    basis_input = json.dumps(
        {
            "sources": sources,
            "spec_manifest": spec_manifest_summary,
            "task_packet_index": task_packet_index,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    snapshot = {
        "schema_version": "1",
        "run_id": run_id,
        "workspace": str(repo_root),
        "sources": sources,
        "basis_hash": hashlib.sha256(basis_input.encode("utf-8")).hexdigest(),
    }
    snapshot["context_budget"] = build_context_budget(repo_root, sources, max_chars)
    if spec_manifest_summary is not None:
        snapshot["spec_manifest"] = spec_manifest_summary
    if task_packet_index:
        snapshot["task_packet_index"] = task_packet_index
        snapshot["context_budget"]["active_strategy"] = "task_packet"
        snapshot["context_budget"]["packet_count"] = len(task_packet_index)
    return snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--spec")
    parser.add_argument("--docs", default="")
    parser.add_argument("--max-chars", type=int, default=120000)
    parser.add_argument("--spec-manifest")
    parser.add_argument("--task-packet-dir")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    repo_root = Path(args.repo_root).expanduser().resolve()
    if not repo_root.is_dir():
        die(f"repo root is not a directory: {repo_root}")
    docs = [item.strip() for item in args.docs.split(",") if item.strip()]
    if args.max_chars <= 0:
        die("--max-chars must be a positive integer")
    snapshot = build_snapshot(
        repo_root,
        args.run_id,
        args.plan,
        args.spec,
        docs,
        args.max_chars,
        args.spec_manifest,
        args.task_packet_dir,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(snapshot["basis_hash"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
