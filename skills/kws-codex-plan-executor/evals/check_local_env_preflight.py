#!/usr/bin/env python3
"""Deterministic checks for local environment preflight warnings."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def run_preflight(repo: Path) -> tuple[subprocess.CompletedProcess[str], dict]:
    script = Path(__file__).resolve().parents[1] / "scripts" / "preflight_local_env.py"
    output = repo / "warnings.json"
    result = subprocess.run(
        [sys.executable, str(script), "--repo-root", str(repo), "--output", str(output)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    data = json.loads(output.read_text(encoding="utf-8")) if output.is_file() else {}
    return result, data


def init_repo(repo: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "eval@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "eval"], cwd=repo, check=True)


def touch(path: Path, offset: int = 0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(path.name + "\n", encoding="utf-8")
    when = time.time() + offset
    os.utime(path, (when, when))


def main() -> int:
    failures: list[str] = []
    checks: dict[str, bool] = {}

    with tempfile.TemporaryDirectory(prefix="codex-preflight-") as temp:
        repo = Path(temp) / "missing-config"
        repo.mkdir()
        init_repo(repo)
        (repo / ".gitignore").write_text(".env\n", encoding="utf-8")
        (repo / ".env.example").write_text("TOKEN=\n", encoding="utf-8")
        result, data = run_preflight(repo)
        warnings = data.get("warnings", [])
        checks["missing_ignored_local_config"] = (
            result.returncode == 0
            and any(item.get("kind") == "missing_local_config" and item.get("file") == ".env" for item in warnings)
        )
        if not checks["missing_ignored_local_config"]:
            failures.append("/.env.example plus ignored missing /.env should emit missing_local_config")

    with tempfile.TemporaryDirectory(prefix="codex-preflight-") as temp:
        repo = Path(temp) / "stale-node"
        repo.mkdir()
        init_repo(repo)
        touch(repo / "package.json", -20)
        touch(repo / "package-lock.json", 20)
        touch(repo / "node_modules/.package-lock.json", -20)
        result, data = run_preflight(repo)
        warnings = data.get("warnings", [])
        checks["stale_node_dependencies"] = (
            result.returncode == 0
            and any(item.get("kind") == "dependencies_likely_stale" and item.get("lockfile") == "package-lock.json" for item in warnings)
        )
        if not checks["stale_node_dependencies"]:
            failures.append("package-lock newer than node_modules marker should emit dependencies_likely_stale")

    with tempfile.TemporaryDirectory(prefix="codex-preflight-") as temp:
        repo = Path(temp) / "clean"
        repo.mkdir()
        init_repo(repo)
        (repo / ".gitignore").write_text(".env\n", encoding="utf-8")
        (repo / ".env.example").write_text("TOKEN=\n", encoding="utf-8")
        (repo / ".env").write_text("TOKEN=local\n", encoding="utf-8")
        touch(repo / "package.json", -20)
        touch(repo / "package-lock.json", -20)
        touch(repo / "node_modules/.package-lock.json", 20)
        result, data = run_preflight(repo)
        checks["clean_repo_empty_warnings"] = result.returncode == 0 and data.get("warnings") == []
        if not checks["clean_repo_empty_warnings"]:
            failures.append("clean repo should emit [] warnings")

    payload = {"passed": not failures, "checks": checks, "failures": failures}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
