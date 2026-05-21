"""Tests for agentlens.web.deps."""
from __future__ import annotations

from agentlens.web.deps import resolve_home, store_exists


def test_resolve_home_uses_env(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTLENS_HOME", str(tmp_path))
    assert resolve_home() == tmp_path


def test_store_exists_false_when_dir_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTLENS_HOME", str(tmp_path / "does-not-exist"))
    assert store_exists() is False


def test_store_exists_true_when_runs_dir_present(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTLENS_HOME", str(tmp_path))
    (tmp_path / "runs").mkdir()
    assert store_exists() is True
