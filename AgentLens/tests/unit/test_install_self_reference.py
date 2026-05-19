"""Unit tests for install_shim self-reference guard (spec §S1.4.2).

The guard refuses to bake a binary that already lives inside the AgentLens
shim directory as the ``.real`` target. This catches the common re-install
accident where ``shutil.which`` returns the already-installed shim.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from agentlens.adapters.shims import install_shim


@pytest.fixture()
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect HOME so Path.home() == tmp_path during the test."""
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def _make_executable(path: Path, content: bytes = b"#!/bin/sh\nexit 0\n") -> Path:
    path.write_bytes(content)
    path.chmod(0o755)
    return path


def test_install_refuses_real_equal_to_shim_in_shim_dir(home: Path) -> None:
    """real == <shim_dir>/claude must raise ValueError with the spec message."""
    shim_dir = home / ".agentlens" / "shims"
    shim_dir.mkdir(parents=True, mode=0o700)
    fake_shim = _make_executable(shim_dir / "claude")

    with pytest.raises(ValueError) as exc_info:
        install_shim("claude", fake_shim)

    msg = str(exc_info.value)
    assert "refusing to bake" in msg
    assert "AgentLens shim directory" in msg
    assert "Pass --real <ultimate binary>" in msg


def test_install_refuses_real_same_dir_different_name(home: Path) -> None:
    """real == <shim_dir>/codex while installing 'claude' must also raise.

    The guard checks the parent directory, not the filename — installing
    one agent while pointing at another shim in the same dir is equally
    nonsensical.
    """
    shim_dir = home / ".agentlens" / "shims"
    shim_dir.mkdir(parents=True, mode=0o700)
    other_shim = _make_executable(shim_dir / "codex")

    with pytest.raises(ValueError) as exc_info:
        install_shim("claude", other_shim)

    assert "AgentLens shim directory" in str(exc_info.value)


def test_install_allows_real_outside_shim_dir(home: Path, tmp_path: Path) -> None:
    """real in a tmpdir outside the shim dir must NOT raise the guard."""
    outside_dir = tmp_path / "elsewhere"
    outside_dir.mkdir()
    binary = _make_executable(outside_dir / "claude")

    # Must not raise; lockfile and shim are written.
    install_shim("claude", binary)
    lockfile = home / ".agentlens" / "shims" / "claude.real"
    assert lockfile.is_file()


def test_install_refuses_symlink_into_shim_dir(home: Path, tmp_path: Path) -> None:
    """A symlink in tmpdir whose target lives in shim_dir must raise.

    The guard uses ``.resolve()`` so symlink-indirection cannot bypass it.
    """
    shim_dir = home / ".agentlens" / "shims"
    shim_dir.mkdir(parents=True, mode=0o700)
    real_in_shim_dir = _make_executable(shim_dir / "claude")

    link_dir = tmp_path / "linkdir"
    link_dir.mkdir()
    symlink = link_dir / "claude"
    symlink.symlink_to(real_in_shim_dir)

    with pytest.raises(ValueError) as exc_info:
        install_shim("claude", symlink)

    assert "AgentLens shim directory" in str(exc_info.value)
