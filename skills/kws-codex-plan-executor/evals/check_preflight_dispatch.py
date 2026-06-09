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


def write_packet(
    path: Path,
    files: list[str],
    *,
    allowed_write_globs: list[str] | None = None,
    context_status: str = "green",
    acceptance_command: str | None = "python3 evals/check_preflight_dispatch.py",
    fallback_used: bool = False,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "task_id": "task_0",
                "task_title": "Task",
                "files": files,
                "sha256": "packet-sha",
                "context_budget": {"status": context_status, "estimated_chars": 10, "max_chars": 60000},
                "acceptance": {"has_acceptance_criteria": acceptance_command is not None, "command": acceptance_command},
                "spec": {"fallback_used": fallback_used},
                "write_policy": {
                    "allowed_write_globs": allowed_write_globs or ["docs/example.md"],
                    "forbidden_write_globs": [".git/**", "graphify-out/**"],
                },
            }
        ),
        encoding="utf-8",
    )


def run_dispatch(
    repo: Path, state_path: Path, packet_path: Path, *extra: str
) -> tuple[subprocess.CompletedProcess[str], dict]:
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
            *extra,
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    data = json.loads(output.read_text(encoding="utf-8")) if output.is_file() else {}
    return result, data


def write_state(path: Path, packet_sha: str = "packet-sha") -> None:
    state = check_state_schema.v220_state()
    state["tasks"]["task_0"]["task_packet_sha256"] = packet_sha
    path.write_text(json.dumps(state), encoding="utf-8")


def main() -> int:
    checks: dict[str, bool] = {}
    failures: list[str] = []

    with tempfile.TemporaryDirectory(prefix="cpe-dispatch-") as temp:
        repo = Path(temp) / "repo"
        repo.mkdir()
        init_repo(repo)
        state_path = repo / "state.json"
        packet_path = repo / "task_0.json"
        write_packet(packet_path, ["docs/example.md"])
        write_state(state_path)
        result, data = run_dispatch(repo, state_path, packet_path)
        checks["clean_task_delegates"] = result.returncode == 0 and data.get("decision") == "delegate"
        if not checks["clean_task_delegates"]:
            failures.append("clean task packet should delegate")

    with tempfile.TemporaryDirectory(prefix="cpe-dispatch-") as temp:
        repo = Path(temp) / "repo"
        repo.mkdir()
        init_repo(repo)
        state_path = repo / "state.json"
        packet_path = repo / "task_0.json"
        write_packet(packet_path, ["docs/example.md"])
        write_state(state_path)
        result, data = run_dispatch(
            repo,
            state_path,
            packet_path,
            "--spawn-policy",
            "explicit-request-required",
            "--explicit-delegation-requested",
            "false",
            "--requested-subagents",
            "on",
            "--requested-source",
            "default",
        )
        checks["spawn_policy_requires_explicit_request_local_fallback"] = (
            result.returncode == 0
            and data.get("decision") == "local_fallback"
            and "spawn_policy_requires_explicit_user_request" in data.get("failed_prerequisites", [])
            and data.get("delegation_policy", {}).get("effective_mode") == "local_fallback"
        )
        if not checks["spawn_policy_requires_explicit_request_local_fallback"]:
            failures.append(
                "explicit-request-required spawn policy without explicit delegation intent should local_fallback"
            )

    with tempfile.TemporaryDirectory(prefix="cpe-dispatch-") as temp:
        repo = Path(temp) / "repo"
        repo.mkdir()
        init_repo(repo)
        (repo / "docs/example.md").write_text("dirty\n", encoding="utf-8")
        state_path = repo / "state.json"
        packet_path = repo / "task_0.json"
        write_packet(packet_path, ["docs/example.md"])
        write_state(state_path)
        result, data = run_dispatch(repo, state_path, packet_path)
        checks["dirty_overlap_blocks"] = result.returncode != 0 and data.get("decision") == "block"
        if not checks["dirty_overlap_blocks"]:
            failures.append("dirty overlap should block dispatch")

    with tempfile.TemporaryDirectory(prefix="cpe-dispatch-") as temp:
        repo = Path(temp) / "repo"
        repo.mkdir()
        init_repo(repo)
        state_path = repo / "state.json"
        packet_path = repo / "task_0.json"
        write_packet(packet_path, ["docs/example.md"], context_status="red")
        write_state(state_path)
        result, data = run_dispatch(repo, state_path, packet_path)
        checks["red_context_local_fallback"] = (
            result.returncode == 0
            and data.get("decision") == "local_fallback"
            and "packet_context_budget_red" in data.get("failed_prerequisites", [])
        )
        if not checks["red_context_local_fallback"]:
            failures.append("red context budget should choose local fallback")

    with tempfile.TemporaryDirectory(prefix="cpe-dispatch-") as temp:
        repo = Path(temp) / "repo"
        repo.mkdir()
        init_repo(repo)
        state_path = repo / "state.json"
        packet_path = repo / "task_0.json"
        write_packet(packet_path, ["docs/example.md"], acceptance_command=None)
        write_state(state_path)
        result, data = run_dispatch(repo, state_path, packet_path)
        checks["missing_acceptance_local_fallback"] = (
            result.returncode == 0
            and data.get("decision") == "local_fallback"
            and "acceptance_command_missing" in data.get("failed_prerequisites", [])
        )
        if not checks["missing_acceptance_local_fallback"]:
            failures.append("missing acceptance command should choose local fallback")

    with tempfile.TemporaryDirectory(prefix="cpe-dispatch-") as temp:
        repo = Path(temp) / "repo"
        repo.mkdir()
        init_repo(repo)
        state_path = repo / "state.json"
        packet_path = repo / "task_0.json"
        write_packet(packet_path, ["docs/example.md"], allowed_write_globs=["**"])
        write_state(state_path)
        result, data = run_dispatch(repo, state_path, packet_path)
        checks["broad_scope_blocks"] = (
            result.returncode != 0
            and data.get("decision") == "block"
            and "write_scope_too_broad" in data.get("failed_prerequisites", [])
        )
        if not checks["broad_scope_blocks"]:
            failures.append("repo-wide write scope should block dispatch")

    with tempfile.TemporaryDirectory(prefix="cpe-dispatch-") as temp:
        repo = Path(temp) / "repo"
        repo.mkdir()
        init_repo(repo)
        state_path = repo / "state.json"
        packet_path = repo / "task_0.json"
        write_packet(packet_path, ["docs/example.md"])
        write_state(state_path, packet_sha="different-sha")
        result, data = run_dispatch(repo, state_path, packet_path)
        checks["task_packet_hash_mismatch_blocks"] = (
            result.returncode != 0
            and data.get("decision") == "block"
            and "task_packet_hash_mismatch" in data.get("failed_prerequisites", [])
        )
        if not checks["task_packet_hash_mismatch_blocks"]:
            failures.append("task packet hash mismatch should block dispatch")

    payload = {"passed": not failures, "checks": checks, "failures": failures}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
