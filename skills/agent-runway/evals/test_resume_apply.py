from __future__ import annotations

from pathlib import Path

import pytest
import subprocess

from agentrunway.apply import ApplyError, apply_commits_to_source
from agentrunway.runner import resume


def test_resume_missing_run_is_idempotent(isolated_home: Path) -> None:
    assert resume("missing-run") == {"run_id": "missing-run", "status": "missing"}
    assert resume("missing-run") == {"run_id": "missing-run", "status": "missing"}


def test_apply_refuses_dirty_source(git_repo: Path) -> None:
    (git_repo / "dirty.txt").write_text("dirty\n", encoding="utf-8")
    with pytest.raises(ApplyError, match="dirty source checkout"):
        apply_commits_to_source(git_repo, ("abc123",), strategy="cherry-pick")


def test_apply_conflict_error_names_failing_commit(git_repo: Path) -> None:
    readme = git_repo / "README.md"
    subprocess.run(["git", "checkout", "-b", "worker"], cwd=git_repo, check=True, capture_output=True)
    readme.write_text("# Worker\n", encoding="utf-8")
    subprocess.run(["git", "commit", "-am", "worker change"], cwd=git_repo, check=True, capture_output=True)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=git_repo, text=True, capture_output=True, check=True).stdout.strip()
    subprocess.run(["git", "checkout", "main"], cwd=git_repo, check=True, capture_output=True)
    readme.write_text("# Main\n", encoding="utf-8")
    subprocess.run(["git", "commit", "-am", "main change"], cwd=git_repo, check=True, capture_output=True)

    with pytest.raises(ApplyError) as exc_info:
        apply_commits_to_source(git_repo, (commit,), strategy="cherry-pick")

    message = str(exc_info.value)
    assert commit in message
    assert "cherry-pick conflict" in message
