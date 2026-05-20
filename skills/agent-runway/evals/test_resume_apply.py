from __future__ import annotations

from pathlib import Path

import pytest

from agentrunway.apply import ApplyError, apply_commits_to_source
from agentrunway.runner import resume


def test_resume_missing_run_is_idempotent(isolated_home: Path) -> None:
    assert resume("missing-run") == {"run_id": "missing-run", "status": "missing"}
    assert resume("missing-run") == {"run_id": "missing-run", "status": "missing"}


def test_apply_refuses_dirty_source(git_repo: Path) -> None:
    (git_repo / "dirty.txt").write_text("dirty\n", encoding="utf-8")
    with pytest.raises(ApplyError, match="dirty source checkout"):
        apply_commits_to_source(git_repo, ("abc123",), strategy="cherry-pick")
