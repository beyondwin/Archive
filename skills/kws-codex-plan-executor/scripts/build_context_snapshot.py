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
        "status": status,
        "max_chars": max_chars,
        "estimated_chars": estimated_chars,
        "included_sections": included_sections,
        "omitted_sections": omitted_sections,
    }


def build_snapshot(repo_root: Path, run_id: str, plan: str, spec: str | None, docs: list[str], max_chars: int) -> dict:
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

    basis_input = json.dumps(sources, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    snapshot = {
        "schema_version": "1",
        "run_id": run_id,
        "workspace": str(repo_root),
        "sources": sources,
        "basis_hash": hashlib.sha256(basis_input.encode("utf-8")).hexdigest(),
    }
    snapshot["context_budget"] = build_context_budget(repo_root, sources, max_chars)
    return snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--spec")
    parser.add_argument("--docs", default="")
    parser.add_argument("--max-chars", type=int, default=120000)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    repo_root = Path(args.repo_root).expanduser().resolve()
    if not repo_root.is_dir():
        die(f"repo root is not a directory: {repo_root}")
    docs = [item.strip() for item in args.docs.split(",") if item.strip()]
    if args.max_chars <= 0:
        die("--max-chars must be a positive integer")
    snapshot = build_snapshot(repo_root, args.run_id, args.plan, args.spec, docs, args.max_chars)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(snapshot["basis_hash"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
