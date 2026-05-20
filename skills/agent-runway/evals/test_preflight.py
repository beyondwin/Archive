from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from agentrunway import runner
from agentrunway.preflight import PreflightIssue, run_preflight


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "agentrunway.py"


def _git_repo(path: Path) -> Path:
    path.mkdir()
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "agentrunway@example.invalid"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "AgentRunway Test"], cwd=path, check=True)
    (path / "README.md").write_text("demo\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True, capture_output=True, text=True)
    return path


def test_local_preflight_passes_for_writable_repo_and_run_dir(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path / "repo")
    run_dir = tmp_path / "run"
    worktree_root = tmp_path / "worktrees"

    result = run_preflight(adapter_name="local", repo=repo, run_dir=run_dir, worktree_root=worktree_root)

    assert result.ok is True
    assert result.issues == []
    assert "git_common_dir" in result.checked_surface
    assert result.partial is True


def test_preflight_reports_missing_adapter_binary(tmp_path: Path, monkeypatch) -> None:
    repo = _git_repo(tmp_path / "repo")
    monkeypatch.setenv("PATH", str(tmp_path / "empty-bin"))

    result = run_preflight(adapter_name="codex", repo=repo, run_dir=tmp_path / "run", worktree_root=tmp_path / "worktrees")

    assert result.ok is False
    assert PreflightIssue(code="missing_adapter_binary", detail="codex") in result.issues


def test_preflight_reports_missing_git_identity(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "HOME": str(tmp_path / "home")}

    result = run_preflight(adapter_name="local", repo=repo, run_dir=tmp_path / "run", worktree_root=tmp_path / "worktrees", env=env)

    assert any(issue.code == "git_identity_missing" for issue in result.issues)


def test_preflight_result_reports_partial_surface(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path / "repo")

    result = run_preflight(adapter_name="local", repo=repo, run_dir=tmp_path / "run", worktree_root=tmp_path / "worktrees")

    payload = result.to_dict()
    assert payload["checked_surface"]
    assert payload["partial"] is True
    assert "sandbox_git_worktree_write" in payload["skipped_surface"]


def test_preflight_checks_run_specific_worktree_root(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path / "repo")
    worktree_root = tmp_path / "worktrees" / "run-1"
    worktree_root.parent.mkdir()
    worktree_root.write_text("not a directory\n", encoding="utf-8")

    result = run_preflight(adapter_name="local", repo=repo, run_dir=tmp_path / "run", worktree_root=worktree_root)

    assert result.ok is False
    assert any(issue.code == "path_not_writable" and "worktree_root" in issue.detail for issue in result.issues)


def test_runner_rejects_plan_lint_errors_before_preflight(tmp_path: Path, monkeypatch) -> None:
    repo = _git_repo(tmp_path / "repo")
    spec = repo / "spec.md"
    plan = repo / "plan.md"
    spec.write_text("# Spec\n\n## A\n\nDetails.\n", encoding="utf-8")
    plan.write_text(
        "## Task 1: Bad\n\n"
        "```yaml agentrunway-task\n"
        "task_id: task_001\n"
        "title: Bad\n"
        "risk: low\n"
        "phase: implementation\n"
        "dependencies: []\n"
        "spec_refs: [S1.1]\n"
        "file_claims:\n"
        "  - {path: graphify-out/GRAPH_REPORT.md, mode: owned}\n"
        "acceptance_commands: [python -m pytest]\n"
        "required_skills: [test-driven-development]\n"
        "```\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENTRUNWAY_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(repo)

    payload = runner.run(
        SimpleNamespace(
            adapter="local",
            allow_dirty_source=False,
            apply_to_source=False,
            base_ref="HEAD",
            fake_success=True,
            model_profile=None,
            plan=plan,
            planning_only=False,
            run_id="lint-failure-test",
            spec=spec,
        )
    )

    assert payload["status"] == "plan_lint_failed"
    assert any(issue["code"] == "forbidden_owned_path" for issue in payload["plan_lint"]["errors"])


def test_preflight_failure_status_last_preserves_diagnostics(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path / "repo")
    spec = repo / "spec.md"
    plan = repo / "plan.md"
    spec.write_text("# Spec\n\n## A\n\nDetails.\n", encoding="utf-8")
    plan.write_text(
        "## Task 1: A\n\n"
        "```yaml agentrunway-task\n"
        "task_id: task_001\n"
        "title: A\n"
        "risk: low\n"
        "phase: implementation\n"
        "dependencies: []\n"
        "spec_refs: [S1.1]\n"
        "file_claims:\n"
        "  - {path: src/a.py, mode: owned}\n"
        "acceptance_commands: [python -m pytest]\n"
        "required_skills: [test-driven-development]\n"
        "```\n",
        encoding="utf-8",
    )
    env = {**os.environ, "AGENTRUNWAY_HOME": str(tmp_path / "home")}

    run_result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "run",
            "--plan",
            str(plan),
            "--spec",
            str(spec),
            "--adapter",
            "badapter",
        ],
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    status_result = subprocess.run(
        [sys.executable, str(SCRIPT), "status", "--last", "--json"],
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    run_payload = json.loads(run_result.stdout)
    status_payload = json.loads(status_result.stdout)
    assert run_payload["status"] == "preflight_failed"
    assert status_payload["status"] == "preflight_failed"
    assert any(issue["code"] == "unsupported_adapter" for issue in status_payload["preflight"]["issues"])


def test_runner_returns_preflight_failed_when_run_dir_cannot_be_created(tmp_path: Path, monkeypatch) -> None:
    repo = _git_repo(tmp_path / "repo")
    plan = repo / "plan.md"
    plan.write_text(
        "## Task 1: A\n\n"
        "```yaml agentrunway-task\n"
        "task_id: task_001\n"
        "title: A\n"
        "risk: low\n"
        "phase: implementation\n"
        "dependencies: []\n"
        "spec_refs: [S1.1]\n"
        "file_claims:\n"
        "  - {path: src/a.py, mode: owned}\n"
        "acceptance_commands: [python -m pytest]\n"
        "required_skills: [test-driven-development]\n"
        "```\n",
        encoding="utf-8",
    )
    home = tmp_path / "home"
    home.mkdir()
    (home / "runs").write_text("not a directory\n", encoding="utf-8")
    monkeypatch.setenv("AGENTRUNWAY_HOME", str(home))
    monkeypatch.chdir(repo)

    payload = runner.run(
        SimpleNamespace(
            adapter="local",
            allow_dirty_source=False,
            apply_to_source=False,
            base_ref="HEAD",
            fake_success=True,
            model_profile=None,
            plan=plan,
            planning_only=False,
            run_id="preflight-test",
            spec=None,
        )
    )

    assert payload["status"] == "preflight_failed"
    assert payload["run_id"] == "preflight-test"
    assert any(issue["code"] == "path_not_writable" for issue in payload["preflight"]["issues"])
