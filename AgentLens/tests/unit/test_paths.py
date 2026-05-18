"""Tests for agentlens.store.paths (S1.6.4)."""
from __future__ import annotations

from pathlib import Path

import pytest

from agentlens.store.paths import (
    agentlens_home,
    current_run_marker,
    current_runs_dir,
    run_dir,
    runs_root,
    safe_label_path,
    workspace_dir,
    workspace_local,
)


def test_agentlens_home_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTLENS_HOME", str(tmp_path))
    assert agentlens_home() == tmp_path


def test_agentlens_home_default(monkeypatch):
    monkeypatch.delenv("AGENTLENS_HOME", raising=False)
    home = agentlens_home()
    assert home == Path.home() / ".agentlens"


def test_runs_root(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTLENS_HOME", str(tmp_path))
    assert runs_root() == tmp_path / "runs"


def test_run_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTLENS_HOME", str(tmp_path))
    wid = "ws_0123456789abcdef"
    rid = "run_20250101_000000_aaaaaa"
    d = run_dir(wid, rid)
    assert d == tmp_path / "runs" / wid / rid


def test_workspace_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTLENS_HOME", str(tmp_path))
    wid = "ws_0123456789abcdef"
    assert workspace_dir(wid) == tmp_path / "runs" / wid


def test_current_runs_dir_durable(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTLENS_HOME", str(tmp_path))
    wid = "ws_0123456789abcdef"
    assert current_runs_dir(wid) == tmp_path / "runs" / wid / "current-runs"


def test_workspace_local(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    assert workspace_local(root) == root / ".agentlens"


def test_current_run_marker_workspace_local(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    rid = "run_20250101_000000_abcdef"
    marker = current_run_marker(root, rid)
    assert marker == root / ".agentlens" / "current-runs" / rid


def test_safe_label_path_inside_workspace(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "sub").mkdir()
    target = ws / "sub" / "file.txt"
    target.write_text("x")
    label = safe_label_path(target, ws)
    assert label == "sub/file.txt"


def test_safe_label_path_outside_workspace(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    outside = tmp_path / "other" / "file.txt"
    outside.parent.mkdir()
    outside.write_text("x")
    label = safe_label_path(outside, ws)
    assert label.startswith("EXTERNAL:")
    # The hash should be a sha256 hex digest (lowercase).
    suffix = label[len("EXTERNAL:") :]
    assert all(c in "0123456789abcdef" for c in suffix)
    assert len(suffix) >= 16  # at least a useful prefix
