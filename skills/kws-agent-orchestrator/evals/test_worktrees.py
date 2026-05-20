from __future__ import annotations

import subprocess
from pathlib import Path

from kao.git_ops import Git, dirty_files
from kao.worktrees import branch_exists, create_main_worktree, next_available_run_id, workspace_id


def test_workspace_id_is_stable_from_linked_worktree(git_repo: Path, tmp_path: Path) -> None:
    linked = tmp_path / "linked"
    subprocess.run(["git", "worktree", "add", str(linked), "HEAD"], cwd=git_repo, check=True, capture_output=True)
    assert workspace_id(git_repo) == workspace_id(linked)


def test_create_main_worktree_records_branch(git_repo: Path, tmp_path: Path) -> None:
    git = Git(git_repo)
    target = tmp_path / "wt" / "main"
    create_main_worktree(git, target, "run-123", git.rev_parse("HEAD"))
    assert (target / ".git").exists()
    assert branch_exists(git_repo, "kao/run-123/main")


def test_next_available_run_id_skips_existing_branch(git_repo: Path) -> None:
    subprocess.run(["git", "branch", "kao/demo-20260520-000000-a/main"], cwd=git_repo, check=True)
    assert next_available_run_id(git_repo, "demo-20260520-000000-a") == "demo-20260520-000000-b"


def test_dirty_files_reports_staged_and_unstaged(git_repo: Path) -> None:
    (git_repo / "README.md").write_text("# Repo\nchanged\n", encoding="utf-8")
    assert dirty_files(git_repo) == ["README.md"]
