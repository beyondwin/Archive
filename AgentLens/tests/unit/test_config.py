"""Tests for agentlens.config (spec §S1.4, §S1.10.2 test row).

Covers the priority chain:

  AGENTLENS_DISABLE > env vars (AGENTLENS_*) > workspace config >
  user config > defaults

and validation of the ``mode`` value.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from agentlens.config import ConfigError, load_config


def _clear_agentlens_env(monkeypatch):
    """Remove any AGENTLENS_* env vars that might leak from the host shell."""
    import os

    for key in list(os.environ):
        if key.startswith("AGENTLENS_"):
            monkeypatch.delenv(key, raising=False)


def _write_yaml(path: Path, mapping: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    import yaml

    path.write_text(yaml.safe_dump(mapping), encoding="utf-8")


def test_defaults_when_no_sources(tmp_path, monkeypatch):
    _clear_agentlens_env(monkeypatch)
    monkeypatch.setenv("AGENTLENS_HOME", str(tmp_path / "home"))
    cfg = load_config(workspace_root=tmp_path / "ws")
    assert cfg["mode"] == "minimal"


def test_disable_env_wins_over_everything(tmp_path, monkeypatch):
    _clear_agentlens_env(monkeypatch)
    monkeypatch.setenv("AGENTLENS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AGENTLENS_DISABLE", "1")
    monkeypatch.setenv("AGENTLENS_MODE", "full")

    # Also write workspace + user configs that say "full".
    ws = tmp_path / "ws"
    _write_yaml(ws / ".agentlens" / "config.yaml", {"mode": "full"})
    _write_yaml(tmp_path / "home" / "config.yaml", {"mode": "full"})

    cfg = load_config(workspace_root=ws)
    assert cfg["mode"] == "disabled"


def test_env_var_overrides_workspace(tmp_path, monkeypatch):
    _clear_agentlens_env(monkeypatch)
    monkeypatch.setenv("AGENTLENS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AGENTLENS_MODE", "full")

    ws = tmp_path / "ws"
    _write_yaml(ws / ".agentlens" / "config.yaml", {"mode": "minimal"})

    cfg = load_config(workspace_root=ws)
    assert cfg["mode"] == "full"


def test_workspace_overrides_user(tmp_path, monkeypatch):
    _clear_agentlens_env(monkeypatch)
    monkeypatch.setenv("AGENTLENS_HOME", str(tmp_path / "home"))

    _write_yaml(tmp_path / "home" / "config.yaml", {"mode": "minimal"})
    ws = tmp_path / "ws"
    _write_yaml(ws / ".agentlens" / "config.yaml", {"mode": "full"})

    cfg = load_config(workspace_root=ws)
    assert cfg["mode"] == "full"


def test_user_config_used_when_no_workspace(tmp_path, monkeypatch):
    _clear_agentlens_env(monkeypatch)
    monkeypatch.setenv("AGENTLENS_HOME", str(tmp_path / "home"))
    _write_yaml(tmp_path / "home" / "config.yaml", {"mode": "full"})

    cfg = load_config(workspace_root=None)
    assert cfg["mode"] == "full"


def test_invalid_mode_value_raises(tmp_path, monkeypatch):
    _clear_agentlens_env(monkeypatch)
    monkeypatch.setenv("AGENTLENS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AGENTLENS_MODE", "bogus")
    with pytest.raises(ConfigError):
        load_config(workspace_root=tmp_path / "ws")


def test_invalid_mode_in_workspace_yaml_raises(tmp_path, monkeypatch):
    _clear_agentlens_env(monkeypatch)
    monkeypatch.setenv("AGENTLENS_HOME", str(tmp_path / "home"))
    ws = tmp_path / "ws"
    _write_yaml(ws / ".agentlens" / "config.yaml", {"mode": "weird"})
    with pytest.raises(ConfigError):
        load_config(workspace_root=ws)


def test_disable_zero_does_not_disable(tmp_path, monkeypatch):
    """AGENTLENS_DISABLE only flips on for truthy values like '1'/'true'."""
    _clear_agentlens_env(monkeypatch)
    monkeypatch.setenv("AGENTLENS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AGENTLENS_DISABLE", "0")
    monkeypatch.setenv("AGENTLENS_MODE", "full")
    cfg = load_config(workspace_root=tmp_path / "ws")
    assert cfg["mode"] == "full"
