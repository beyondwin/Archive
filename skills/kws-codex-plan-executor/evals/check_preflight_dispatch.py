#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import check_state_schema


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "preflight_dispatch.py"


def init_repo(repo: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "eval@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "eval"], cwd=repo, check=True)
    (repo / "docs").mkdir()
    (repo / "docs/example.md").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "docs/example.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)


def write_packet(path: Path, files: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "task": {"id": "task_0", "files": files},
                "write_policy": {
                    "allowed_write_globs": ["docs/example.md"],
                    "forbidden_write_globs": [".git/**", "graphify-out/**"],
                },
            }
        ),
        encoding="utf-8",
    )


def run_dispatch(repo: Path, state_path: Path, packet_path: Path) -> tuple[subprocess.CompletedProcess[str], dict]:
    output = repo / "dispatch.json"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--state",
            str(state_path),
            "--task-id",
            "task_0",
            "--task-packet",
            str(packet_path),
            "--repo-root",
            str(repo),
            "--write-scope",
            "docs/example.md",
            "--output",
            str(output),
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    data = json.loads(output.read_text(encoding="utf-8")) if output.is_file() else {}
    return result, data


def main() -> int:
    checks: dict[str, bool] = {}
    failures: list[str] = []

    with tempfile.TemporaryDirectory(prefix="cpe-dispatch-") as temp:
        repo = Path(temp) / "repo"
        repo.mkdir()
        init_repo(repo)
        state_path = repo / "state.json"
        state_path.write_text(json.dumps(check_state_schema.v220_state()), encoding="utf-8")
        packet_path = repo / "task_0.json"
        write_packet(packet_path, ["docs/example.md"])
        result, data = run_dispatch(repo, state_path, packet_path)
        checks["clean_task_delegates"] = result.returncode == 0 and data.get("decision") == "delegate"
        if not checks["clean_task_delegates"]:
            failures.append("clean task packet should delegate")

    with tempfile.TemporaryDirectory(prefix="cpe-dispatch-") as temp:
        repo = Path(temp) / "repo"
        repo.mkdir()
        init_repo(repo)
        (repo / "docs/example.md").write_text("dirty\n", encoding="utf-8")
        state_path = repo / "state.json"
        state_path.write_text(json.dumps(check_state_schema.v220_state()), encoding="utf-8")
        packet_path = repo / "task_0.json"
        write_packet(packet_path, ["docs/example.md"])
        result, data = run_dispatch(repo, state_path, packet_path)
        checks["dirty_overlap_blocks"] = result.returncode != 0 and data.get("decision") == "block"
        if not checks["dirty_overlap_blocks"]:
            failures.append("dirty overlap should block dispatch")

    payload = {"passed": not failures, "checks": checks, "failures": failures}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
