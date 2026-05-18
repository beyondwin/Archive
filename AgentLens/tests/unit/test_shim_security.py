"""Unit tests for shim install/security (spec §S1.6.18, §S1.9.3)."""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from agentlens.adapters.shims import (
    install_shim,
    verify_shim_integrity,
)


@pytest.fixture()
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect HOME so Path.home() == tmp_path during the test."""
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def _make_fake_binary(dirpath: Path, name: str, content: bytes = b"#!/bin/sh\nexit 0\n") -> Path:
    binary = dirpath / name
    binary.write_bytes(content)
    binary.chmod(0o755)
    return binary


def test_shim_install_creates_directory_with_0700_perms(home: Path, tmp_path: Path) -> None:
    binary = _make_fake_binary(tmp_path, "claude")
    install_shim("claude", binary)
    shim_dir = home / ".agentlens" / "shims"
    assert shim_dir.is_dir()
    assert (shim_dir.stat().st_mode & 0o777) == 0o700


def test_shim_install_writes_lockfile_with_path_and_sha(home: Path, tmp_path: Path) -> None:
    binary = _make_fake_binary(tmp_path, "claude", b"hello world\n")
    install_shim("claude", binary)
    lockfile = home / ".agentlens" / "shims" / "claude.real"
    text = lockfile.read_text(encoding="utf-8")
    lines = text.splitlines()
    # First two lines are path=... and sha256=...
    keys = {line.split("=", 1)[0]: line.split("=", 1)[1] for line in lines if "=" in line}
    assert keys["path"] == str(binary.resolve())
    # sha256 of b"hello world\n"
    import hashlib
    assert keys["sha256"] == hashlib.sha256(b"hello world\n").hexdigest()
    # Trailing newline preserved
    assert text.endswith("\n")


def test_shim_install_chmods_script_0755(home: Path, tmp_path: Path) -> None:
    binary = _make_fake_binary(tmp_path, "claude")
    install_shim("claude", binary)
    shim = home / ".agentlens" / "shims" / "claude"
    assert shim.is_file()
    assert (shim.stat().st_mode & 0o777) == 0o755


def test_shim_install_owner_mismatch_raises(home: Path, tmp_path: Path) -> None:
    binary = _make_fake_binary(tmp_path, "claude")
    # Pre-create shim_dir; then mock os.getuid to a fake uid not matching st_uid.
    shim_dir = home / ".agentlens" / "shims"
    shim_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    actual_uid = shim_dir.stat().st_uid
    fake_uid = actual_uid + 1234  # not the real owner
    with patch("agentlens.adapters.shims.os.getuid", return_value=fake_uid):
        with pytest.raises(PermissionError):
            install_shim("claude", binary)


def test_shim_template_uses_real_path_lockfile(home: Path, tmp_path: Path) -> None:
    """Shim script must reference lockfile + delegate via `agentlens run`."""
    binary = _make_fake_binary(tmp_path, "claude")
    install_shim("claude", binary)
    shim = (home / ".agentlens" / "shims" / "claude").read_text(encoding="utf-8")
    assert "REAL_LOCKFILE=\"$HOME/.agentlens/shims/claude.real\"" in shim
    # Shim delegates to the canonical adapter name (claude → claude_code).
    assert "run --agent claude_code" in shim
    # CLI lookup falls back to passthrough when agentlens isn't on PATH,
    # per the §S1.6.17 non-blocking invariant.
    assert "command -v agentlens" in shim
    assert 'exec "$REAL_PATH"' in shim
    # Curly braces correctly de-escaped by .format
    assert "${REAL_LOCKFILE}" not in shim  # spec template does not use this form
    assert "{name}" not in shim  # no unsubstituted placeholders
    assert "{agent_name}" not in shim


def test_shim_bakes_install_time_agentlens_path(home: Path, tmp_path: Path) -> None:
    """The shim must record the absolute path to the agentlens CLI at
    install time so a venv-only install still self-records when the user
    types ``claude`` from a non-activated shell.
    """
    import shutil as _shutil
    import sys as _sys

    binary = _make_fake_binary(tmp_path, "claude")

    # Simulate a venv install: argv[0] points at .venv/bin/agentlens.
    fake_cli = tmp_path / "bin" / "agentlens"
    fake_cli.parent.mkdir()
    fake_cli.write_text("#!/usr/bin/env bash\nexit 0\n")
    os.chmod(fake_cli, 0o755)

    saved_argv0 = _sys.argv[0]
    _sys.argv[0] = str(fake_cli)
    try:
        install_shim("claude", binary)
    finally:
        _sys.argv[0] = saved_argv0

    shim = (home / ".agentlens/shims/claude").read_text()
    expected_path = str(fake_cli.resolve())
    assert f'INSTALLED_AGENTLENS_BIN="{expected_path}"' in shim
    # Falls back to PATH lookup if baked path is missing/non-executable.
    assert 'command -v agentlens' in shim
    # And finally to passthrough.
    assert 'exec "$REAL_PATH"' in shim
    del _shutil  # silence unused import marker


def test_shim_binary_name_maps_to_canonical_agent(home: Path, tmp_path: Path) -> None:
    """Binary names users type (`claude`, `codex`) must map to the canonical
    adapter names that `agentlens run --agent` accepts.
    """
    bin_claude = _make_fake_binary(tmp_path, "claude")
    bin_codex = _make_fake_binary(tmp_path, "codex")
    bin_other = _make_fake_binary(tmp_path, "weird-tool")

    install_shim("claude", bin_claude)
    install_shim("codex", bin_codex)
    install_shim("weird-tool", bin_other)

    shim_claude = (home / ".agentlens/shims/claude").read_text()
    shim_codex = (home / ".agentlens/shims/codex").read_text()
    shim_other = (home / ".agentlens/shims/weird-tool").read_text()

    assert "run --agent claude_code" in shim_claude
    assert "run --agent codex_cli" in shim_codex
    # Unmapped names fall back to 'generic' (still in the _AGENT_NAMES allowlist).
    assert "run --agent generic" in shim_other


def test_verify_shim_integrity_missing(home: Path) -> None:
    assert verify_shim_integrity("claude") == "missing"


def test_verify_shim_integrity_ok(home: Path, tmp_path: Path) -> None:
    binary = _make_fake_binary(tmp_path, "claude", b"v1\n")
    install_shim("claude", binary)
    assert verify_shim_integrity("claude") == "ok"


def test_verify_shim_integrity_drift(home: Path, tmp_path: Path) -> None:
    binary = _make_fake_binary(tmp_path, "claude", b"v1\n")
    install_shim("claude", binary)
    # Rewrite binary content; sha256 no longer matches lockfile.
    binary.write_bytes(b"v2 different\n")
    assert verify_shim_integrity("claude") == "drift_warning"


def test_verify_shim_integrity_real_path_deleted(home: Path, tmp_path: Path) -> None:
    binary = _make_fake_binary(tmp_path, "claude")
    install_shim("claude", binary)
    binary.unlink()
    assert verify_shim_integrity("claude") == "missing"


def test_install_shim_rejects_nonexistent_real_path(home: Path, tmp_path: Path) -> None:
    bogus = tmp_path / "does_not_exist"
    with pytest.raises(FileNotFoundError):
        install_shim("claude", bogus)
