#!/usr/bin/env python3
"""Tests for initcmd.run_init — TDD RED phase.

Run:  cd skills/kws-claude-multi-agent-executor && python3 scripts/kernel/test_init_run.py
"""
import sys
import os
import json
import tempfile
import subprocess
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _make_clean_git_repo(base_dir: str) -> str:
    """Create a minimal git repo with one commit; return its path."""
    repo = os.path.join(base_dir, "source_repo")
    os.makedirs(repo, exist_ok=True)
    subprocess.run(["git", "init", repo], check=True, capture_output=True)
    subprocess.run(["git", "-C", repo, "config", "user.email", "test@example.com"],
                   check=True, capture_output=True)
    subprocess.run(["git", "-C", repo, "config", "user.name", "Test User"],
                   check=True, capture_output=True)
    # Create an initial commit so HEAD is valid
    readme = os.path.join(repo, "README.md")
    Path(readme).write_text("# test\n")
    subprocess.run(["git", "-C", repo, "add", "README.md"], check=True, capture_output=True)
    subprocess.run(["git", "-C", repo, "commit", "-m", "init"],
                   check=True, capture_output=True)
    return repo


def test_dry_run_returns_plan():
    """dry_run=True returns paths + run_id without touching the filesystem."""
    import initcmd

    with tempfile.TemporaryDirectory() as tmpdir:
        repo = _make_clean_git_repo(tmpdir)
        home = os.path.join(tmpdir, "home")
        os.makedirs(home, exist_ok=True)

        fixed_now = datetime(2026, 7, 6, 12, 0, 0)
        result = initcmd.run_init(
            raw_args="plan=/plans/my-plan.md spec=/specs/spec.md",
            home=home,
            repo_root=repo,
            dry_run=True,
            now=fixed_now,
        )

        assert "halt" not in result, f"unexpected halt: {result}"
        assert "run_id" in result
        assert "state_path" in result
        assert "echo_line" in result

        run_id = result["run_id"]
        # run_id must include the timestamp suffix
        assert "20260706-120000" in run_id, f"run_id={run_id!r} missing timestamp"

        # Worktree and orch_dir are siblings under home/.claude/
        state_path = result["state_path"]
        worktree = result["worktree"]
        orch_dir = result["orchestrator_dir"]

        expected_wt = os.path.join(home, ".claude", "worktrees", run_id)
        expected_orch = os.path.join(home, ".claude", "orchestrator", run_id)

        assert worktree == expected_wt, f"worktree={worktree!r} != {expected_wt!r}"
        assert orch_dir == expected_orch, f"orch_dir={orch_dir!r} != {expected_orch!r}"
        assert state_path == os.path.join(expected_orch, "state.json")

        # In dry_run, NO filesystem changes should have been made
        assert not os.path.exists(expected_wt), "worktree dir must NOT exist in dry_run"
        assert not os.path.exists(expected_orch), "orch_dir must NOT exist in dry_run"

    print("PASS test_dry_run_returns_plan")


def test_dirty_tree_halt():
    """run_init halts with dirty_worktree when repo has uncommitted changes."""
    import initcmd

    with tempfile.TemporaryDirectory() as tmpdir:
        repo = _make_clean_git_repo(tmpdir)
        home = os.path.join(tmpdir, "home")
        os.makedirs(home, exist_ok=True)

        # Dirty the repo with an untracked file
        dirty_file = os.path.join(repo, "untracked.txt")
        Path(dirty_file).write_text("dirty\n")

        fixed_now = datetime(2026, 7, 6, 12, 0, 0)
        result = initcmd.run_init(
            raw_args="plan=/plans/my-plan.md spec=/specs/spec.md",
            home=home,
            repo_root=repo,
            dry_run=True,
            now=fixed_now,
        )

        assert result.get("halt") == "dirty_worktree", \
            f"expected halt=dirty_worktree, got {result}"

    print("PASS test_dirty_tree_halt")


def test_dirty_tree_halt_non_dry_run():
    """dirty-tree check fires even without dry_run=True."""
    import initcmd

    with tempfile.TemporaryDirectory() as tmpdir:
        repo = _make_clean_git_repo(tmpdir)
        home = os.path.join(tmpdir, "home")
        os.makedirs(home, exist_ok=True)

        # Dirty: staged but uncommitted change
        dirty_file = os.path.join(repo, "modified.txt")
        Path(dirty_file).write_text("new content\n")
        subprocess.run(["git", "-C", repo, "add", "modified.txt"], check=True, capture_output=True)

        fixed_now = datetime(2026, 7, 6, 12, 0, 0)
        result = initcmd.run_init(
            raw_args="plan=/plans/my-plan.md spec=/specs/spec.md",
            home=home,
            repo_root=repo,
            dry_run=False,
            now=fixed_now,
        )

        assert result.get("halt") == "dirty_worktree", \
            f"expected halt=dirty_worktree, got {result}"

    print("PASS test_dirty_tree_halt_non_dry_run")


def test_run_init_creates_state_v3():
    """Non-dry_run creates state.json with v3 schema."""
    import initcmd

    with tempfile.TemporaryDirectory() as tmpdir:
        repo = _make_clean_git_repo(tmpdir)
        home = os.path.join(tmpdir, "home")
        os.makedirs(home, exist_ok=True)

        # Create fake plan and spec files (just need paths to exist for slug derivation)
        plan_path = os.path.join(tmpdir, "my-plan.md")
        spec_path = os.path.join(tmpdir, "spec.md")
        Path(plan_path).write_text("# plan\n")
        Path(spec_path).write_text("# spec\n")

        skill_dir = str(Path(__file__).resolve().parents[2])

        fixed_now = datetime(2026, 7, 6, 15, 30, 0)
        result = initcmd.run_init(
            raw_args=f"plan={plan_path} spec={spec_path}",
            home=home,
            repo_root=repo,
            dry_run=False,
            now=fixed_now,
            skill_dir=skill_dir,
        )

        assert "halt" not in result, f"unexpected halt: {result}"
        assert "state_path" in result

        state_path = result["state_path"]
        assert os.path.isfile(state_path), f"state.json not created at {state_path}"

        with open(state_path) as f:
            state = json.load(f)

        assert state["schema_version"] == 3
        assert state["run_id"] == result["run_id"]
        assert state["status"] == "SETUP"
        assert "timestamps" in state
        assert state["cost_ledger"]["totals"]["dispatches"] == 0

        # Verify orch subdirs were created
        orch_dir = result["orchestrator_dir"]
        for subdir in ("packets", "prompts", "results", "hooks"):
            assert os.path.isdir(os.path.join(orch_dir, subdir)), \
                f"missing subdir: {subdir}"

    print("PASS test_run_init_creates_state_v3")


def test_echo_line_in_result():
    """run_init (dry_run) result includes a non-empty echo_line."""
    import initcmd

    with tempfile.TemporaryDirectory() as tmpdir:
        repo = _make_clean_git_repo(tmpdir)
        home = os.path.join(tmpdir, "home")
        os.makedirs(home, exist_ok=True)

        fixed_now = datetime(2026, 7, 6, 12, 0, 0)
        result = initcmd.run_init(
            raw_args="plan=/plans/plan.md spec=/specs/spec.md",
            home=home,
            repo_root=repo,
            dry_run=True,
            now=fixed_now,
        )

        assert "echo_line" in result
        line = result["echo_line"]
        assert isinstance(line, str) and len(line) > 0
        assert "plan" in line.lower() or "parsed" in line.lower()

    print("PASS test_echo_line_in_result")


if __name__ == "__main__":
    test_dry_run_returns_plan()
    test_dirty_tree_halt()
    test_dirty_tree_halt_non_dry_run()
    test_run_init_creates_state_v3()
    test_echo_line_in_result()
    print("\nAll init_run tests passed.")
