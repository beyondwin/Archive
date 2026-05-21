"""Integration tests for Layer-4 post-install selftest probe (spec §S1.4.4).

After `install_shim` writes the shim + lockfile, it must run a guarded
`--version` re-entry probe against the freshly-installed shim. On any
failure (timeout / malformed output / depth mismatch / re-entry marker /
reserved exit code), it deletes the just-written files and restores any
prior snapshot, then raises `RuntimeError`.

A `skip_selftest=True` keyword bypasses the probe entirely (used by
unit-test fixtures that are not real executables).
"""
from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agentlens.adapters.shims import install_shim
from agentlens.cli import app


@pytest.fixture()
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect HOME so Path.home() == tmp_path during the test."""
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def _write_executable(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)
    return path


def _benign_versioner(dirpath: Path, name: str = "fake-agent") -> Path:
    """Build a script that handles `--version` cleanly and exits 0."""
    binary = dirpath / name
    return _write_executable(
        binary,
        "#!/bin/bash\n"
        'if [ "${1:-}" = "--version" ]; then\n'
        '  echo "fake 1.0"\n'
        "  exit 0\n"
        "fi\n"
        "exit 0\n",
    )


def _reentry_simulator(dirpath: Path, name: str = "loop-agent") -> Path:
    """Build a script that, when invoked at depth=1, prints the AgentLens
    re-entry marker and exits with the reserved 70 status — simulating a
    wrapper whose `--version` resolves back to an AgentLens shim.

    The shim template (depth=0) execs REAL --version with DEPTH=1; that
    invocation here directly emits ``agentlens_selftest_reentry=1`` and
    exits 70, which the shim's grep matches and propagates as failure.
    """
    binary = dirpath / name
    return _write_executable(
        binary,
        "#!/bin/bash\n"
        "printf 'agentlens_selftest_reentry=1\\n'\n"
        "exit 70\n",
    )


class TestSelftestProbe:
    def test_benign_install_succeeds(
        self, home: Path, tmp_path: Path
    ) -> None:
        """A real executable that handles `--version` cleanly installs OK."""
        bindir = tmp_path / "bin"
        bindir.mkdir()
        binary = _benign_versioner(bindir)
        # allow_wrapper=True so the shebang script bypasses Layer-1 scan;
        # the focus here is the Layer-4 probe path.
        install_shim("fake-agent", binary, allow_wrapper=True)
        assert (home / ".agentlens" / "shims" / "fake-agent").is_file()
        assert (home / ".agentlens" / "shims" / "fake-agent.real").is_file()

    def test_reentry_install_fails_and_leaves_no_files(
        self, home: Path, tmp_path: Path
    ) -> None:
        """Re-entry detection: shim+lockfile must be removed; RuntimeError raised."""
        bindir = tmp_path / "bin"
        bindir.mkdir()
        loop = _reentry_simulator(bindir)
        with pytest.raises(RuntimeError) as exc_info:
            install_shim("loop-agent", loop, allow_wrapper=True)
        assert "loop-agent" in str(exc_info.value) or "selftest" in str(
            exc_info.value
        )
        # Rollback: no shim, no lockfile.
        assert not (home / ".agentlens" / "shims" / "loop-agent").exists()
        assert not (home / ".agentlens" / "shims" / "loop-agent.real").exists()

    def test_skip_selftest_true_bypasses_probe_for_nonexecutable(
        self, home: Path, tmp_path: Path
    ) -> None:
        """`skip_selftest=True` allows pure-byte fixtures used in unit tests."""
        bindir = tmp_path / "bin"
        bindir.mkdir()
        # Non-executable byte file — invocation would fail, but we never invoke.
        binary = bindir / "bytes-agent"
        binary.write_bytes(b"\x7fELF not really an elf\n")
        install_shim(
            "bytes-agent",
            binary,
            allow_wrapper=True,
            skip_selftest=True,
        )
        assert (home / ".agentlens" / "shims" / "bytes-agent").is_file()
        assert (home / ".agentlens" / "shims" / "bytes-agent.real").is_file()

    def test_reinstall_failure_restores_prior_snapshot(
        self, home: Path, tmp_path: Path
    ) -> None:
        """When a re-install fails the selftest, the prior shim+lockfile bytes
        must be restored so the user is never left with no shim."""
        bindir = tmp_path / "bin"
        bindir.mkdir()
        good = _benign_versioner(bindir, "agent-x")
        # First install with skip_selftest so we plant snapshot baselines.
        install_shim("agent-x", good, allow_wrapper=True, skip_selftest=True)
        shim_path = home / ".agentlens" / "shims" / "agent-x"
        lock_path = home / ".agentlens" / "shims" / "agent-x.real"
        prior_shim = shim_path.read_bytes()
        prior_lock = lock_path.read_bytes()
        assert prior_shim and prior_lock

        # Now re-install with a re-entry simulator; selftest must fail and
        # rollback to the prior bytes.
        loop = _reentry_simulator(bindir, "agent-x-loop")
        with pytest.raises(RuntimeError):
            install_shim("agent-x", loop, allow_wrapper=True)
        assert shim_path.is_file()
        assert lock_path.is_file()
        assert shim_path.read_bytes() == prior_shim
        assert lock_path.read_bytes() == prior_lock
        # And the restored shim must remain executable.
        mode = stat.S_IMODE(shim_path.stat().st_mode)
        assert mode & 0o100, oct(mode)


class TestSkipSelftestCli:
    def test_cli_skip_selftest_flag_passes_through(
        self, home: Path, tmp_path: Path
    ) -> None:
        """`agentlens install --skip-selftest` bypasses the probe and warns."""
        runner = CliRunner()
        bindir = tmp_path / "bin"
        bindir.mkdir()
        # Use a non-executable byte file; without --skip-selftest the probe
        # would fail, but with it the install completes.
        binary = bindir / "claude"
        binary.write_bytes(b"\x7fELF not really an elf\n")
        result = runner.invoke(
            app,
            [
                "install",
                "claude",
                "--real",
                str(binary),
                "--yes",
                "--skip-selftest",
                "--no-wrapper-detect",
            ],
        )
        assert result.exit_code == 0, (result.stdout, result.stderr)
        combined = (result.stdout or "") + (result.stderr or "")
        assert "selftest skipped" in combined.lower(), combined
        assert (home / ".agentlens" / "shims" / "claude").is_file()

    def test_cli_install_failure_from_selftest_exits_nonzero(
        self, home: Path, tmp_path: Path
    ) -> None:
        runner = CliRunner()
        bindir = tmp_path / "bin"
        bindir.mkdir()
        loop = _write_executable(
            bindir / "claude",
            "#!/bin/bash\nprintf 'agentlens_selftest_reentry=1\\n'\nexit 70\n",
        )
        result = runner.invoke(
            app,
            [
                "install",
                "claude",
                "--real",
                str(loop),
                "--yes",
                "--no-wrapper-detect",
            ],
        )
        assert result.exit_code != 0, (result.stdout, result.stderr)
        combined = (result.stdout or "") + (result.stderr or "")
        assert "install failed" in combined.lower(), combined
        # Rollback: no files left behind.
        assert not (home / ".agentlens" / "shims" / "claude").exists()
        assert not (home / ".agentlens" / "shims" / "claude.real").exists()
