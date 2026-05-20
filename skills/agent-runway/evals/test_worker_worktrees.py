from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agentrunway.file_claims import DiffScopeError, validate_changed_files
from agentrunway.git_ops import Git, changed_files_between, commits_between
from agentrunway.worktrees import create_worker_worktree


def _commit(repo: Path, path: str, text: str, message: str) -> str:
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    subprocess.run(["git", "add", path], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", message], cwd=repo, check=True, capture_output=True, text=True)
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def test_create_worker_worktree_from_main_branch(git_repo: Path, tmp_path: Path) -> None:
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=git_repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    main = tmp_path / "main"
    Git(git_repo).run("worktree", "add", "-b", "agentrunway/run-1/main", str(main), base)

    worker = create_worker_worktree(
        Git(git_repo),
        target=tmp_path / "worker",
        branch="agentrunway/run-1/task_001-implementer-001",
        base_ref="agentrunway/run-1/main",
    )

    assert worker.exists()
    assert (worker / ".git").exists()


def test_commits_and_changed_files_between_refs(git_repo: Path) -> None:
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=git_repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    commit = _commit(git_repo, "src/a.py", "A = 1\n", "add a")

    assert commits_between(Git(git_repo), base, "HEAD") == (commit,)
    assert changed_files_between(Git(git_repo), base, "HEAD") == ("src/a.py",)


def test_validate_changed_files_rejects_out_of_scope() -> None:
    validate_changed_files(("src/a.py",), ("src/*.py",))
    with pytest.raises(DiffScopeError, match="outside allowed write scope"):
        validate_changed_files(("README.md",), ("src/*.py",))
