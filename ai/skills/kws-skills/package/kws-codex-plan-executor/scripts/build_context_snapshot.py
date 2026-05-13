#!/usr/bin/env python3
"""Build a per-run context snapshot for kws-codex-plan-executor."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


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


def build_snapshot(repo_root: Path, run_id: str, plan: str, spec: str | None, docs: list[str]) -> dict:
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
    return {
        "schema_version": "1",
        "run_id": run_id,
        "workspace": str(repo_root),
        "sources": sources,
        "basis_hash": hashlib.sha256(basis_input.encode("utf-8")).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--spec")
    parser.add_argument("--docs", default="")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    repo_root = Path(args.repo_root).expanduser().resolve()
    if not repo_root.is_dir():
        die(f"repo root is not a directory: {repo_root}")
    docs = [item.strip() for item in args.docs.split(",") if item.strip()]
    snapshot = build_snapshot(repo_root, args.run_id, args.plan, args.spec, docs)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(snapshot["basis_hash"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
