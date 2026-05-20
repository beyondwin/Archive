from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from kao.git_ops import DirtySourceError, assert_clean_source
from kao.worktrees import branch_exists, next_available_run_id


def test_dirty_source_refuses_by_default(git_repo: Path) -> None:
    (git_repo / "README.md").write_text("dirty\n", encoding="utf-8")
    with pytest.raises(DirtySourceError):
        assert_clean_source(git_repo, allow_dirty=False)


def test_allow_dirty_source_records_explicit_policy(git_repo: Path) -> None:
    (git_repo / "README.md").write_text("dirty\n", encoding="utf-8")
    assert_clean_source(git_repo, allow_dirty=True) == ["README.md"]


def test_branch_exists_and_next_run_id(git_repo: Path) -> None:
    subprocess.run(["git", "branch", "kao/example/main"], cwd=git_repo, check=True)
    assert branch_exists(git_repo, "kao/example/main")
    assert next_available_run_id(git_repo, "example") == "example-b"
