#!/usr/bin/env python3
"""Deterministic checks for check_run_diffs.py."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


RUN_ID = "diff-policy-20260519-143022"


def base_state(repo: Path, task_id: str = "task_0") -> dict:
    run_dir = repo / ".codex-test" / "orchestrator" / RUN_ID
    return {
        "schema_version": "1",
        "run_id": RUN_ID,
        "mode": "interactive",
        "workspace": str(repo),
        "plan": str(repo / "plan.md"),
        "branch": f"codex/{RUN_ID}",
        "worktree": str(repo / ".codex" / "worktrees" / RUN_ID),
        "run_dir": str(run_dir),
        "state_path": str(run_dir / "state.json"),
        "current_task": task_id,
        "current_phase": "task_loop",
        "tasks": {
            task_id: {
                "status": "in_progress",
                "risk": "low",
                "files_declared": ["docs/allowed.md"],
                "contract": {
                    "scope": "Update allowed docs.",
                    "files_to_inspect": ["docs/allowed.md"],
                    "allowed_edits": ["docs/allowed.md"],
                    "forbidden_edits": ["docs/forbidden.md"],
                    "acceptance_command_or_honest_substitute": "python3 scripts/check_run_diffs.py",
                },
                "unit_manifest": {
                    "unit_type": "execute-task",
                    "context_mode": "focused",
                    "required_skills": ["using-superpowers", "test-driven-development"],
                    "tool_policy": "implementation",
                    "allowed_write_globs": ["docs/allowed.md"],
                    "forbidden_write_globs": ["docs/forbidden.md"],
                    "artifact_policy": "inline-summary",
                    "max_context_chars": 60000,
                },
                "review_retries": 0,
                "verifier_retries": 0,
            }
        },
        "timestamps": {
            "started_at": "2026-05-16T00:00:00Z",
            "updated_at": "2026-05-16T00:00:00Z",
            "completed_at": None,
        },
    }


def run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def init_repo(repo: Path) -> None:
    (repo / "docs").mkdir(parents=True)
    (repo / "docs" / "allowed.md").write_text("allowed\n", encoding="utf-8")
    (repo / "docs" / "forbidden.md").write_text("forbidden\n", encoding="utf-8")
    (repo / "scripts").mkdir()
    (repo / "plan.md").write_text("### Task 0\n\n**Files:**\n- docs/allowed.md\n", encoding="utf-8")
    run(["git", "init", "-q"], repo).check_returncode()
    run(["git", "config", "user.email", "eval@example.com"], repo).check_returncode()
    run(["git", "config", "user.name", "Eval"], repo).check_returncode()
    run(["git", "add", "-A"], repo).check_returncode()
    run(["git", "commit", "-q", "-m", "bootstrap"], repo).check_returncode()


def write_state(repo: Path, state: dict) -> Path:
    state_path = repo / state["state_path"]
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return state_path


def run_checker(script: Path, repo: Path, state_path: Path, task_id: str = "task_0") -> subprocess.CompletedProcess[str]:
    return run(
        [
            sys.executable,
            str(script),
            "--repo-root",
            str(repo),
            "--state",
            str(state_path),
            "--task",
            task_id,
            "--json",
        ],
        repo,
    )


def json_payload(result: subprocess.CompletedProcess[str]) -> dict:
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}


def case(script: Path, name: str, mutate_state, mutate_repo, expect_pass: bool) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory(prefix=f"codex-diff-policy-{name}-") as temp:
        repo = Path(temp)
        init_repo(repo)
        state = base_state(repo)
        mutate_state(state)
        state_path = write_state(repo, state)
        run(["git", "add", str(state_path.relative_to(repo))], repo).check_returncode()
        run(["git", "commit", "-q", "-m", "state"], repo).check_returncode()
        mutate_repo(repo)
        result = run_checker(script, repo, state_path)
        payload = json_payload(result)
        passed = result.returncode == 0 and payload.get("passed") is True
        failed = result.returncode != 0 and payload.get("passed") is False and payload.get("violations")
        if expect_pass and passed:
            return True, ""
        if not expect_pass and failed:
            return True, ""
        return False, f"{name}: rc={result.returncode} stdout={result.stdout!r} stderr={result.stderr!r}"


def main() -> int:
    script = Path(__file__).resolve().parents[1] / "scripts" / "check_run_diffs.py"
    checks: dict[str, bool] = {}
    failures: list[str] = []

    cases = [
        (
            "allowed_change_passes",
            lambda state: None,
            lambda repo: (repo / "docs" / "allowed.md").write_text("allowed changed\n", encoding="utf-8"),
            True,
        ),
        (
            "outside_allowed_fails",
            lambda state: None,
            lambda repo: (repo / "docs" / "outside.md").write_text("outside\n", encoding="utf-8"),
            False,
        ),
        (
            "forbidden_change_fails",
            lambda state: None,
            lambda repo: (repo / "docs" / "forbidden.md").write_text("forbidden changed\n", encoding="utf-8"),
            False,
        ),
        (
            "read_only_no_changes_passes",
            lambda state: (
                state["tasks"]["task_0"]["unit_manifest"].update(
                    {"tool_policy": "read-only", "allowed_write_globs": []}
                ),
                state["tasks"]["task_0"]["contract"].update({"allowed_edits": []}),
            ),
            lambda repo: None,
            True,
        ),
        (
            "docs_policy_docs_change_passes",
            lambda state: (
                state["tasks"]["task_0"]["unit_manifest"].update(
                    {"tool_policy": "docs", "allowed_write_globs": ["docs/**"]}
                ),
                state["tasks"]["task_0"]["contract"].update({"allowed_edits": []}),
            ),
            lambda repo: (repo / "docs" / "new.md").write_text("new\n", encoding="utf-8"),
            True,
        ),
    ]

    for name, mutate_state, mutate_repo, expect_pass in cases:
        ok, failure = case(script, name, mutate_state, mutate_repo, expect_pass)
        checks[name] = ok
        if not ok:
            failures.append(failure)

    payload = {"passed": not failures, "checks": checks, "failures": failures}
    print(json.dumps(payload, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
