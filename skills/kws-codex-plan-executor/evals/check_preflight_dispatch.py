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
    estimated_chars: int = 10,
    max_chars: int = 60000,
    dependencies: list[str] | None = None,
    risk_markers: list[str] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "task_id": "task_0",
                "task_title": "Task",
                "files": files,
                "dependencies": dependencies or [],
                "risk_markers": risk_markers or [],
                "sha256": "packet-sha",
                "context_budget": {
                    "status": context_status,
                    "estimated_chars": estimated_chars,
                    "max_chars": max_chars,
                },
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
    repo: Path,
    state_path: Path,
    packet_path: Path,
    *extra: str,
    write_scope: list[str] | None = None,
) -> tuple[subprocess.CompletedProcess[str], dict]:
    output = repo / "dispatch.json"
    scope_args: list[str] = []
    for scope in write_scope or ["docs/example.md"]:
        scope_args.extend(["--write-scope", scope])
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
            *scope_args,
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
        checks["clean_small_task_uses_local_fast_path"] = (
            result.returncode == 0
            and data.get("decision") == "local_fallback"
            and data.get("reason") == "adaptive_policy_local_fast_path_docs_only"
            and data.get("delegation_policy", {}).get("policy_kind") == "adaptive"
            and data.get("delegation_policy", {}).get("value_gate") == "local_fast_path"
            and data.get("state_updates", {}).get("subagent_strategy", {}).get("mode") == "local_fallback"
        )
        if not checks["clean_small_task_uses_local_fast_path"]:
            failures.append("clean small docs task should use adaptive local fast path")

    with tempfile.TemporaryDirectory(prefix="cpe-dispatch-") as temp:
        repo = Path(temp) / "repo"
        repo.mkdir()
        init_repo(repo)
        (repo / "scripts").mkdir()
        (repo / "evals").mkdir()
        (repo / "scripts/tool.py").write_text("print('base')\n", encoding="utf-8")
        (repo / "evals/check_tool.py").write_text("print('base')\n", encoding="utf-8")
        subprocess.run(["git", "add", "scripts/tool.py", "evals/check_tool.py"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "add tool"], cwd=repo, check=True)
        state_path = repo / "state.json"
        packet_path = repo / "task_0.json"
        write_packet(
            packet_path,
            ["scripts/tool.py", "evals/check_tool.py"],
            allowed_write_globs=["scripts/*.py", "evals/*.py"],
            estimated_chars=18000,
            dependencies=[],
        )
        write_state(state_path)
        result, data = run_dispatch(
            repo,
            state_path,
            packet_path,
            "--spawn-policy",
            "available",
            "--requested-subagents",
            "on",
            "--requested-source",
            "default",
            write_scope=["scripts/*.py", "evals/*.py"],
        )
        checks["multi_file_independent_task_delegates"] = (
            result.returncode == 0
            and data.get("decision") == "delegate"
            and data.get("delegation_policy", {}).get("value_gate") == "delegate"
        )
        if not checks["multi_file_independent_task_delegates"]:
            failures.append("multi-file independent task should delegate when spawn policy is available")

    with tempfile.TemporaryDirectory(prefix="cpe-dispatch-") as temp:
        repo = Path(temp) / "repo"
        repo.mkdir()
        init_repo(repo)
        (repo / "bun.lock").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "add", "bun.lock"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "add lockfile"], cwd=repo, check=True)
        state_path = repo / "state.json"
        packet_path = repo / "task_0.json"
        write_packet(
            packet_path,
            ["bun.lock"],
            allowed_write_globs=["bun.lock"],
            risk_markers=["lockfile"],
        )
        write_state(state_path)
        result, data = run_dispatch(
            repo,
            state_path,
            packet_path,
            "--spawn-policy",
            "available",
            write_scope=["bun.lock"],
        )
        checks["risky_lockfile_task_blocks"] = (
            result.returncode != 0
            and data.get("decision") == "block"
            and "risk_marker_requires_operator_review" in data.get("failed_prerequisites", [])
        )
        if not checks["risky_lockfile_task_blocks"]:
            failures.append("lockfile risk marker should block adaptive dispatch")

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
