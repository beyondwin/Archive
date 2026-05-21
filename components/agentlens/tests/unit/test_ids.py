"""Tests for agentlens.ids — run_id, event_id, workspace_id (S1.6.3, S1.7.1)."""
from __future__ import annotations

import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agentlens.ids import (
    compute_workspace_id,
    make_event_id,
    make_run_id,
    run_id,
)


RUN_ID_RE = re.compile(r"^run_\d{8}_\d{6}_[a-z0-9]{6}$")
EVENT_ID_RE = re.compile(r"^evt_[a-z0-9]{12}$")
WORKSPACE_ID_RE = re.compile(r"^ws_[a-f0-9]{16}$")


def test_make_run_id_matches_schema_pattern():
    rid = make_run_id()
    assert RUN_ID_RE.match(rid), rid


def test_run_id_alias_matches_schema_pattern():
    # acceptance criteria uses run_id alias
    rid = run_id()
    assert RUN_ID_RE.match(rid), rid


def test_make_run_id_uses_provided_now():
    now = datetime(2025, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    rid = make_run_id(now=now)
    assert rid.startswith("run_20250102_030405_")
    assert RUN_ID_RE.match(rid), rid


def test_make_run_id_is_unique():
    ids = {make_run_id() for _ in range(50)}
    # extremely likely all unique given the random suffix
    assert len(ids) == 50


def test_make_event_id_matches_schema_pattern():
    eid = make_event_id()
    assert EVENT_ID_RE.match(eid), eid


def test_make_event_id_is_unique():
    ids = {make_event_id() for _ in range(50)}
    assert len(ids) == 50


def _git(cwd: Path, *args: str) -> str:
    res = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=True,
    )
    return res.stdout.strip()


def _init_git_repo(root: Path, remote: str = "https://example.com/org/repo.git") -> None:
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    _git(root, "config", "commit.gpgsign", "false")
    _git(root, "remote", "add", "origin", remote)
    (root / "README.md").write_text("hello\n")
    _git(root, "add", "README.md")
    _git(root, "commit", "-q", "-m", "initial")


def test_compute_workspace_id_git_main(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _init_git_repo(root)

    wid, basis, metadata = compute_workspace_id(root)
    assert WORKSPACE_ID_RE.match(wid), wid
    assert basis == "git"
    assert metadata.get("git_remote_hash", "").startswith("sha256:")
    # The hex portion should be lowercase 64-char hex.
    hex_part = metadata["git_remote_hash"].split(":", 1)[1]
    assert re.match(r"^[a-f0-9]{64}$", hex_part)


def test_compute_workspace_id_path_basis(tmp_path):
    # no git
    root = tmp_path / "plain"
    root.mkdir()
    wid, basis, _ = compute_workspace_id(root)
    assert basis == "path"
    assert WORKSPACE_ID_RE.match(wid), wid


def test_compute_workspace_id_persisted_returns_persisted(tmp_path):
    root = tmp_path / "plain"
    root.mkdir()
    cfg_dir = root / ".agentlens"
    cfg_dir.mkdir()
    (cfg_dir / "config.yaml").write_text(
        "workspace_id: ws_0123456789abcdef\nid_basis: git\n"
    )
    wid, basis, _ = compute_workspace_id(root)
    assert wid == "ws_0123456789abcdef"


def test_compute_workspace_id_worktree_differs_from_main(tmp_path):
    main = tmp_path / "main"
    main.mkdir()
    _init_git_repo(main)
    worktree_path = tmp_path / "wt"
    _git(main, "worktree", "add", "-q", "-b", "feature", str(worktree_path))

    main_wid, main_basis, _ = compute_workspace_id(main)
    wt_wid, wt_basis, _ = compute_workspace_id(worktree_path)

    assert main_basis == "git"
    assert wt_basis == "git"
    assert main_wid != wt_wid, (main_wid, wt_wid)


def test_compute_workspace_id_persisted_stable_after_move(tmp_path):
    root_a = tmp_path / "a"
    root_a.mkdir()
    _init_git_repo(root_a)
    wid_first, _, _ = compute_workspace_id(root_a)
    # config should be persisted
    cfg = root_a / ".agentlens" / "config.yaml"
    assert cfg.exists()

    # Simulate moving the workspace (copy .agentlens with config to new dir).
    root_b = tmp_path / "b"
    shutil.copytree(root_a, root_b)
    wid_second, _, _ = compute_workspace_id(root_b)
    assert wid_first == wid_second


def test_compute_workspace_id_persists_on_first_call(tmp_path):
    root = tmp_path / "plain2"
    root.mkdir()
    assert not (root / ".agentlens" / "config.yaml").exists()
    wid, basis, _ = compute_workspace_id(root)
    cfg = root / ".agentlens" / "config.yaml"
    assert cfg.exists()
    content = cfg.read_text()
    assert wid in content
