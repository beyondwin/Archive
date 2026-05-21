"""Integration tests for `agentlens install` cmux-launcher detection (spec §S1.4.1).

Task 3: wire wrapper-signature detection into ``install_shim`` and the
``commands/install.py`` Typer command via ``--no-wrapper-detect``.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from agentlens.cli import app


@pytest.fixture()
def runner() -> CliRunner:
    # Click 8.4+ keeps stderr separate from stdout by default.
    return CliRunner()


@pytest.fixture()
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def _fake_cmux_launcher(dirpath: Path, name: str = "fake-agent") -> Path:
    """Write a shebang script containing a cmux launcher signature."""
    binary = dirpath / name
    binary.write_text(
        "#!/bin/bash\n"
        "find_real_claude() {\n"
        "  echo /usr/local/bin/claude\n"
        "}\n"
        'exec "$(find_real_claude)" "$@"\n',
        encoding="utf-8",
    )
    binary.chmod(0o755)
    return binary


class TestInstallCmuxDetection:
    def test_install_refuses_cmux_launcher_by_default(
        self, runner: CliRunner, home: Path, tmp_path: Path
    ) -> None:
        bindir = tmp_path / "bin"
        bindir.mkdir()
        launcher = _fake_cmux_launcher(bindir)

        result = runner.invoke(
            app,
            ["install", "fake-agent", "--real", str(launcher), "--yes"],
        )

        assert result.exit_code != 0, (result.stdout, result.stderr)
        combined = (result.stdout or "") + (result.stderr or "")
        assert "cmux" in combined.lower(), combined
        # No shim or lockfile written.
        assert not (home / ".agentlens" / "shims" / "fake-agent").exists()
        assert not (home / ".agentlens" / "shims" / "fake-agent.real").exists()

    def test_install_allows_cmux_launcher_with_bypass_flag(
        self, runner: CliRunner, home: Path, tmp_path: Path
    ) -> None:
        bindir = tmp_path / "bin"
        bindir.mkdir()
        launcher = _fake_cmux_launcher(bindir)

        result = runner.invoke(
            app,
            [
                "install",
                "fake-agent",
                "--real",
                str(launcher),
                "--no-wrapper-detect",
                "--yes",
            ],
        )

        assert result.exit_code == 0, (result.stdout, result.stderr)
        combined = (result.stdout or "") + (result.stderr or "")
        assert "wrapper detection bypassed" in combined.lower(), combined
        # Shim + lockfile present.
        assert (home / ".agentlens" / "shims" / "fake-agent").is_file()
        assert (home / ".agentlens" / "shims" / "fake-agent.real").is_file()

    def test_no_wrapper_detect_without_yes_is_typer_error(
        self, runner: CliRunner, home: Path, tmp_path: Path
    ) -> None:
        bindir = tmp_path / "bin"
        bindir.mkdir()
        launcher = _fake_cmux_launcher(bindir)

        result = runner.invoke(
            app,
            [
                "install",
                "fake-agent",
                "--real",
                str(launcher),
                "--no-wrapper-detect",
            ],
        )

        # Typer BadParameter exits non-zero (typically 2).
        assert result.exit_code != 0, (result.stdout, result.stderr)
        # No I/O performed.
        assert not (home / ".agentlens" / "shims" / "fake-agent").exists()
        assert not (home / ".agentlens" / "shims" / "fake-agent.real").exists()
