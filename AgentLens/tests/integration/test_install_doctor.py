"""Integration tests for `agentlens install` / `uninstall` / `doctor` and
the M6 nested-invocation policy (spec §S1.6.18, §S1.7.4, §S1.8.4, §S1.9.3).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agentlens.adapters.process import wrap_command
from agentlens.adapters.shims import install_shim
from agentlens.cli import app


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture()
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def _fake_binary(dirpath: Path, name: str) -> Path:
    binary = dirpath / name
    binary.write_bytes(b"#!/bin/sh\nexit 0\n")
    binary.chmod(0o755)
    return binary


class TestInstallCommand:
    def test_install_command_with_yes_creates_shim(
        self, runner: CliRunner, home: Path, tmp_path: Path
    ) -> None:
        binary = _fake_binary(tmp_path, "claude")
        result = runner.invoke(
            app, ["install", "claude", "--real", str(binary), "--yes"]
        )
        assert result.exit_code == 0, result.output
        shim = home / ".agentlens" / "shims" / "claude"
        lockfile = home / ".agentlens" / "shims" / "claude.real"
        assert shim.is_file()
        assert lockfile.is_file()

    def test_install_command_denies_without_consent(
        self, runner: CliRunner, home: Path, tmp_path: Path
    ) -> None:
        binary = _fake_binary(tmp_path, "claude")
        result = runner.invoke(
            app,
            ["install", "claude", "--real", str(binary)],
            input="n\n",
        )
        assert result.exit_code == 0, result.output
        shim = home / ".agentlens" / "shims" / "claude"
        assert not shim.exists()

    def test_install_command_emits_path_export_hint(
        self, runner: CliRunner, home: Path, tmp_path: Path
    ) -> None:
        binary = _fake_binary(tmp_path, "claude")
        result = runner.invoke(
            app, ["install", "claude", "--real", str(binary), "--yes"]
        )
        assert result.exit_code == 0, result.output
        assert 'export PATH="$HOME/.agentlens/shims:$PATH"' in result.output

    def test_install_command_autodetects_real_path(
        self,
        runner: CliRunner,
        home: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Place fake "claude" in a dir on PATH so shutil.which finds it.
        bindir = tmp_path / "bin"
        bindir.mkdir()
        binary = _fake_binary(bindir, "claude")
        monkeypatch.setenv("PATH", str(bindir))
        result = runner.invoke(app, ["install", "claude", "--yes"])
        assert result.exit_code == 0, result.output
        shim = home / ".agentlens" / "shims" / "claude"
        assert shim.is_file()
        lockfile_text = (home / ".agentlens" / "shims" / "claude.real").read_text()
        assert str(binary.resolve()) in lockfile_text

    def test_install_command_errors_when_no_real_binary(
        self, runner: CliRunner, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Empty PATH so shutil.which finds nothing.
        monkeypatch.setenv("PATH", "")
        result = runner.invoke(app, ["install", "claude", "--yes"])
        assert result.exit_code != 0


class TestUninstallShim:
    def test_uninstall_shim_removes_files(
        self, runner: CliRunner, home: Path, tmp_path: Path
    ) -> None:
        binary = _fake_binary(tmp_path, "claude")
        runner.invoke(app, ["install", "claude", "--real", str(binary), "--yes"])
        shim = home / ".agentlens" / "shims" / "claude"
        lockfile = home / ".agentlens" / "shims" / "claude.real"
        assert shim.exists() and lockfile.exists()
        result = runner.invoke(app, ["uninstall", "claude"])
        assert result.exit_code == 0, result.output
        assert not shim.exists()
        assert not lockfile.exists()

    def test_uninstall_shim_idempotent(
        self, runner: CliRunner, home: Path
    ) -> None:
        result = runner.invoke(app, ["uninstall", "claude"])
        assert result.exit_code == 0, result.output


# ---------------------------------------------------------------------------
# Doctor command — spec §S1.6.18
# ---------------------------------------------------------------------------


class TestDoctor:
    def test_doctor_integrations_text_output(
        self, runner: CliRunner, home: Path
    ) -> None:
        result = runner.invoke(app, ["doctor", "integrations"])
        assert result.exit_code == 0, result.output
        # The integrations section must list both known agents.
        assert "claude" in result.output
        assert "codex" in result.output
        assert "integration_level=" in result.output

    def test_doctor_paths_text_output(
        self, runner: CliRunner, home: Path
    ) -> None:
        result = runner.invoke(app, ["doctor", "paths"])
        assert result.exit_code == 0, result.output
        assert "AGENTLENS_HOME" in result.output
        assert "shim_dir" in result.output

    def test_doctor_all_format_json(
        self, runner: CliRunner, home: Path
    ) -> None:
        result = runner.invoke(
            app, ["doctor", "all", "--format", "json"]
        )
        assert result.exit_code == 0, result.output
        doc = json.loads(result.output)
        assert "integrations" in doc
        assert "paths" in doc

    def test_doctor_after_install_reports_shim_integrity_ok(
        self, runner: CliRunner, home: Path, tmp_path: Path
    ) -> None:
        binary = _fake_binary(tmp_path, "claude")
        install_shim("claude", binary)
        result = runner.invoke(
            app, ["doctor", "integrations", "--format", "json"]
        )
        assert result.exit_code == 0, result.output
        doc = json.loads(result.output)
        claude = doc["integrations"]["claude"]
        assert claude["integration_level"] == "shim"
        assert claude["shim_integrity"] == "ok"


# ---------------------------------------------------------------------------
# Nested-invocation policy — spec §S1.7.4, §S1.8.4
# ---------------------------------------------------------------------------


class TestNestedInvocation:
    def test_nested_passthrough_default_skips_recording(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Pretend we are inside an existing AgentLens run.
        monkeypatch.setenv("AGENTLENS_RUN_ID", "run_parent")
        monkeypatch.setenv("AGENTLENS_RUN_DIR", str(tmp_path))
        monkeypatch.setenv("AGENTLENS_HOME", str(tmp_path / "home"))
        monkeypatch.chdir(tmp_path)
        # Ensure default policy applies (no NESTED_POLICY set).
        monkeypatch.delenv("AGENTLENS_NESTED_POLICY", raising=False)

        result = wrap_command(
            [sys.executable, "-c", "print('hi')"],
            agent_name="claude_code",
            agent_mode="cli",
            mode="minimal",
        )
        assert result.run_id is None  # No recording in passthrough.
        assert result.exit_code == 0

    def test_nested_explicit_nested_creates_new_run_with_parent_id(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("AGENTLENS_RUN_ID", "run_parent")
        monkeypatch.setenv("AGENTLENS_NESTED_POLICY", "nested")
        monkeypatch.setenv("AGENTLENS_HOME", str(tmp_path / "home"))
        # Isolate cwd so workspace config writes go into tmp_path.
        ws = tmp_path / "ws"
        ws.mkdir()
        monkeypatch.chdir(ws)

        result = wrap_command(
            [sys.executable, "-c", "print('child')"],
            agent_name="claude_code",
            agent_mode="cli",
            mode="minimal",
        )
        assert result.run_id is not None  # A new run was created.

        # Locate the new run's run.json and assert parent_run_id.
        run_dirs = list((tmp_path / "home" / "runs").glob("*/*"))
        run_dirs = [d for d in run_dirs if d.is_dir() and (d / "run.json").is_file()]
        assert run_dirs, "expected at least one run directory under home/runs"
        # Find the directory matching this run_id.
        match = [d for d in run_dirs if d.name == result.run_id]
        assert match, f"no run dir matched {result.run_id}"
        run_doc = json.loads((match[0] / "run.json").read_text())
        assert run_doc.get("parent_run_id") == "run_parent"

    def test_nested_child_env_has_pid_stamp(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Verify the recording-path child receives PID-stamped env vars.

        End-to-end: run a small child that echoes the AGENTLENS_RUN_PID_STAMP
        env it received, then read that value out of the recorded
        ``events.jsonl`` (it shows up in the ``run.started``/``command.*``
        chain — we just need the wrapper to spawn and exit 0).
        """
        import os as _os

        monkeypatch.setenv("AGENTLENS_HOME", str(tmp_path / "home"))
        ws = tmp_path / "ws"
        ws.mkdir()
        monkeypatch.chdir(ws)
        monkeypatch.delenv("AGENTLENS_RUN_ID", raising=False)
        monkeypatch.delenv("AGENTLENS_NESTED_POLICY", raising=False)

        # The child writes its received env value to a file we own, so we
        # don't depend on wrapper-captured stdout (drain discards it).
        marker = tmp_path / "marker.txt"
        script = (
            "import os; "
            f"open({str(marker)!r}, 'w').write("
            "os.environ.get('AGENTLENS_RUN_PID_STAMP',''))"
        )

        result = wrap_command(
            [sys.executable, "-c", script],
            agent_name="claude_code",
            agent_mode="cli",
            mode="minimal",
        )

        assert result.exit_code == 0
        assert result.run_id is not None
        assert marker.is_file(), "child never ran (no marker)"
        stamp = marker.read_text()
        # The stamp must encode this wrapper process's PID followed by the
        # run_id we got back (spec §S1.7.4 PID stamp pattern).
        assert stamp.startswith(f"{_os.getpid()}:"), stamp
        assert stamp.endswith(result.run_id), stamp
