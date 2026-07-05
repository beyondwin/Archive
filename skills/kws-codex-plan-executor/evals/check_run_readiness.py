#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import check_state_schema


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "audit_run_readiness.py"


def init_repo(repo: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "eval@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "eval"], cwd=repo, check=True)
    (repo / "docs").mkdir()
    (repo / "docs/example.md").write_text("base\n", encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src/app.py").write_text("print('base')\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)


def write_packet(
    path: Path,
    task_id: str,
    files: list[str],
    *,
    command: str | None,
    fallback_used: bool = False,
    fallback_mapping: dict | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1",
        "task_id": task_id,
        "task_title": task_id,
        "files": files,
        "depends_on": [],
        "acceptance": {
            "has_acceptance_criteria": command is not None,
            "command": command,
            "source": "plan.acceptance_section" if command else "missing",
            "honest_substitute_allowed": command is None,
        },
        "spec": {"fallback_used": fallback_used, "mapping": fallback_mapping or {}},
        "context_budget": {"status": "green", "estimated_chars": 1000, "max_chars": 60000},
        "write_policy": {
            "allowed_write_globs": files,
            "forbidden_write_globs": [".git/**", "graphify-out/**"],
        },
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_audit(repo: Path, state_path: Path, packet_dir: Path) -> tuple[subprocess.CompletedProcess[str], dict]:
    output = repo / "run_readiness.json"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--state",
            str(state_path),
            "--task-packet-dir",
            str(packet_dir),
            "--repo-root",
            str(repo),
            "--output",
            str(output),
            "--requested-subagents",
            "on",
            "--requested-source",
            "explicit",
            "--spawn-policy",
            "available",
            "--explicit-delegation-requested",
            "true",
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

    with tempfile.TemporaryDirectory(prefix="cpe-readiness-") as temp:
        repo = Path(temp) / "repo"
        repo.mkdir()
        init_repo(repo)
        state = check_state_schema.v220_state()
        state_path = repo / "state.json"
        state_path.write_text(json.dumps(state), encoding="utf-8")
        packet_dir = repo / "task_packets"
        write_packet(
            packet_dir / "task_1.json",
            "task_1",
            ["docs/example.md"],
            command=None,
            fallback_used=True,
            fallback_mapping={
                "fallback_reason": "missing_spec_refs",
                "suggested_spec_refs": ["problem", "goals"],
                "suggested_plan_patch": 'spec_refs: ["problem", "goals"]',
                "next_action": "Add explicit spec_refs to the plan task using one of: problem, goals",
                "operator_reviewed": False,
            },
        )
        write_packet(packet_dir / "task_2.json", "task_2", ["src/app.py"], command="python3 -m pytest")
        result, data = run_audit(repo, state_path, packet_dir)
        issue_kinds = {issue.get("kind") for issue in data.get("issues", [])}
        checks["missing_acceptance_is_fixable"] = (
            result.returncode == 1
            and data.get("passed") is False
            and "acceptance_command_missing" in issue_kinds
            and data.get("summary", {}).get("fixable_issue_count", 0) >= 1
        )
        if not checks["missing_acceptance_is_fixable"]:
            failures.append("readiness audit should report missing acceptance as fixable")
        checks["full_spec_fallback_is_reported"] = "full_spec_fallback" in issue_kinds
        if not checks["full_spec_fallback_is_reported"]:
            failures.append("readiness audit should report full spec fallback")
        fallback_issue = next(item for item in data.get("issues", []) if item.get("kind") == "full_spec_fallback")
        checks["full_spec_fallback_has_reason"] = (
            fallback_issue.get("fallback_reason") == "missing_spec_refs"
            and fallback_issue.get("suggested_spec_refs") == ["problem", "goals"]
            and fallback_issue.get("suggested_plan_patch") == 'spec_refs: ["problem", "goals"]'
            and fallback_issue.get("next_action") == "Add explicit spec_refs to the plan task using one of: problem, goals"
        )
        if not checks["full_spec_fallback_has_reason"]:
            failures.append("readiness audit should include full-spec fallback reason and suggestions")

    with tempfile.TemporaryDirectory(prefix="cpe-readiness-clean-") as temp:
        repo = Path(temp) / "repo"
        repo.mkdir()
        init_repo(repo)
        state = check_state_schema.v220_state()
        state_path = repo / "state.json"
        state_path.write_text(json.dumps(state), encoding="utf-8")
        packet_dir = repo / "task_packets"
        write_packet(packet_dir / "task_1.json", "task_1", ["docs/example.md"], command="python3 evals/check_docs.py")
        result, data = run_audit(repo, state_path, packet_dir)
        checks["clean_packet_passes"] = (
            result.returncode == 0
            and data.get("passed") is True
            and data.get("summary", {}).get("task_count") == 1
        )
        if not checks["clean_packet_passes"]:
            failures.append("clean readiness audit should pass")

    with tempfile.TemporaryDirectory(prefix="cpe-readiness-scope-") as temp:
        repo = Path(temp) / "repo"
        repo.mkdir()
        init_repo(repo)
        state = check_state_schema.v220_state()
        state_path = repo / "state.json"
        state_path.write_text(json.dumps(state), encoding="utf-8")
        packet_dir = repo / "task_packets"
        write_packet(
            packet_dir / "task_1.json",
            "task_1",
            ["docs/example.md,src/app.py"],
            command="python3 -m pytest",
        )
        result, data = run_audit(repo, state_path, packet_dir)
        issue = next(
            (item for item in data.get("issues", []) if item.get("kind") == "write_scope_format_invalid"),
            {},
        )
        checks["comma_joined_scope_includes_normalized_fix"] = (
            result.returncode == 1
            and issue.get("severity") == "fixable"
            and issue.get("suggested_write_scopes") == ["docs/example.md", "src/app.py"]
            and data.get("tasks", [{}])[0].get("normalized_write_globs") == ["docs/example.md", "src/app.py"]
        )
        if not checks["comma_joined_scope_includes_normalized_fix"]:
            failures.append("comma-joined write scope should include deterministic normalized write scopes")

    with tempfile.TemporaryDirectory(prefix="cpe-readiness-newline-scope-") as temp:
        repo = Path(temp) / "repo"
        repo.mkdir()
        init_repo(repo)
        state = check_state_schema.v220_state()
        state_path = repo / "state.json"
        state_path.write_text(json.dumps(state), encoding="utf-8")
        packet_dir = repo / "task_packets"
        write_packet(
            packet_dir / "task_1.json",
            "task_1",
            ["src/a.py\nsrc/b.py"],
            command="python3 -m pytest",
        )
        result, data = run_audit(repo, state_path, packet_dir)
        issue = next(
            (item for item in data.get("issues", []) if item.get("kind") == "write_scope_format_invalid"),
            {},
        )
        checks["newline_joined_scope_includes_normalized_fix"] = (
            result.returncode == 1
            and issue.get("severity") == "fixable"
            and issue.get("suggested_write_scopes") == ["src/a.py", "src/b.py"]
            and data.get("tasks", [{}])[0].get("normalized_write_globs") == ["src/a.py", "src/b.py"]
        )
        if not checks["newline_joined_scope_includes_normalized_fix"]:
            failures.append("newline-joined write scope should include deterministic normalized write scopes")

    payload = {"passed": not failures, "checks": checks, "failures": failures}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
