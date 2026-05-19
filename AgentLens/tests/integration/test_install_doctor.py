"""Integration tests for `agentlens install` / `uninstall` / `doctor` and
the M6 nested-invocation policy (spec §S1.6.18, §S1.7.4, §S1.8.4, §S1.9.3).

NOTE for future tasks (task_20, task_21): each adapter test suite belongs in
its own class (``TestClaudeAdapter``, ``TestCodexCliAdapter``, etc.) so that
shared-file additions remain conflict-free.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agentlens.adapters.claude import ClaudeAdapter
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
        # Preserve /usr/bin:/bin in PATH so the Layer-4 selftest probe can
        # still resolve the shim's `#!/usr/bin/env bash` shebang.
        bindir = tmp_path / "bin"
        bindir.mkdir()
        binary = _fake_binary(bindir, "claude")
        monkeypatch.setenv("PATH", f"{bindir}:/usr/bin:/bin")
        # The fake binary doesn't gracefully handle `--version` but exits 0;
        # the selftest's depth-1 invocation will succeed and produce no
        # re-entry marker, so the probe passes. Pass --skip-selftest to keep
        # this test focused on PATH auto-detection only.
        result = runner.invoke(
            app, ["install", "claude", "--yes", "--skip-selftest"]
        )
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


# ---------------------------------------------------------------------------
# Claude adapter — spec §S1.6.19, §S1.10.1 (task_19)
# ---------------------------------------------------------------------------


def _fake_claude(
    dirpath: Path,
    *,
    version: str = "1.2.3",
    has_hook_events: bool = True,
    has_stream_json: bool = True,
    has_bare: bool = False,
) -> Path:
    """Write a deterministic fake ``claude`` binary that mimics the flags.

    The shim emits a fake ``--version`` line and a ``--help`` text that
    optionally advertises ``--include-hook-events``, ``--output-format
    stream-json`` and ``--bare`` so that ``ClaudeAdapter.probe`` can
    classify it without needing a real Claude CLI.
    """
    help_lines = ["Usage: claude [options]"]
    if has_hook_events:
        help_lines.append("  --include-hook-events   include hook events")
    if has_stream_json:
        help_lines.append("  --output-format <fmt>   text|stream-json")
    if has_bare:
        help_lines.append("  --bare                  minimal/headless build")
    help_blob = "\n".join(help_lines)

    binary = dirpath / "claude"
    binary.write_text(
        "#!/bin/sh\n"
        f'if [ "$1" = "--version" ]; then echo "claude {version}"; exit 0; fi\n'
        f'if [ "$1" = "--help" ]; then cat <<\'EOF\'\n{help_blob}\nEOF\nexit 0; fi\n'
        "exit 0\n",
        encoding="utf-8",
    )
    binary.chmod(0o755)
    return binary


class TestClaudeAdapter:
    # ----- probe() ----------------------------------------------------

    def test_probe_unavailable_when_binary_missing(self, tmp_path: Path) -> None:
        adapter = ClaudeAdapter(binary_path=tmp_path / "nope")
        result = adapter.detect()
        assert result.available is False
        assert result.level == "unavailable"

    def test_probe_full_when_all_flags_present(self, tmp_path: Path) -> None:
        binary = _fake_claude(tmp_path, has_hook_events=True, has_stream_json=True)
        adapter = ClaudeAdapter(binary_path=binary)
        result = adapter.detect()
        assert result.available is True
        assert result.level == "full"
        assert any("version=" in n for n in result.notes)

    def test_probe_shim_only_when_missing_flag(self, tmp_path: Path) -> None:
        binary = _fake_claude(tmp_path, has_hook_events=False, has_stream_json=True)
        adapter = ClaudeAdapter(binary_path=binary)
        result = adapter.detect()
        assert result.available is True
        assert result.level == "shim-only"

    def test_probe_bare_environment_degrades_to_shim_only(
        self, tmp_path: Path
    ) -> None:
        binary = _fake_claude(
            tmp_path, has_hook_events=True, has_stream_json=True, has_bare=True
        )
        adapter = ClaudeAdapter(binary_path=binary)
        result = adapter.detect()
        assert result.level == "shim-only"
        assert any("bare=yes" in n for n in result.notes)

    # ----- install() --------------------------------------------------

    def test_install_without_consent_does_not_modify_settings(
        self, tmp_path: Path, home: Path
    ) -> None:
        binary = _fake_claude(tmp_path)
        settings_path = home / ".claude" / "settings.json"
        adapter = ClaudeAdapter(binary_path=binary, settings_path=settings_path)
        result = adapter.install(consent=False)
        assert result.level_installed == "unavailable"
        assert result.files_modified == ()
        assert not settings_path.exists()

    def test_install_creates_settings_when_none_exists(
        self, tmp_path: Path, home: Path
    ) -> None:
        binary = _fake_claude(tmp_path)
        settings_path = home / ".claude" / "settings.json"
        adapter = ClaudeAdapter(binary_path=binary, settings_path=settings_path)
        result = adapter.install(consent=True)
        assert result.level_installed == "full"
        assert settings_path in result.files_modified
        # Brand-new file → no backup path recorded.
        backup_path = settings_path.with_suffix(".json.agentlens.bak")
        assert backup_path not in result.files_modified
        doc = json.loads(settings_path.read_text())
        assert "agentlens" in doc
        assert doc["agentlens"]["managed_by"] == "agentlens"

    def test_install_backs_up_and_preserves_existing_keys(
        self, tmp_path: Path, home: Path
    ) -> None:
        settings_path = home / ".claude" / "settings.json"
        settings_path.parent.mkdir(parents=True)
        original = {"theme": "dark", "user": {"name": "alice"}}
        settings_path.write_text(json.dumps(original, sort_keys=True, indent=2))
        binary = _fake_claude(tmp_path)
        adapter = ClaudeAdapter(binary_path=binary, settings_path=settings_path)
        result = adapter.install(consent=True)
        backup_path = settings_path.with_suffix(".json.agentlens.bak")
        assert backup_path.exists()
        assert backup_path in result.files_modified
        # Backup is byte-equal to original.
        assert json.loads(backup_path.read_text()) == original
        # New settings preserve original keys AND add agentlens block.
        new_doc = json.loads(settings_path.read_text())
        assert new_doc["theme"] == "dark"
        assert new_doc["user"] == {"name": "alice"}
        assert new_doc["agentlens"]["managed_by"] == "agentlens"

    def test_install_degrades_to_shim_only_on_bare_binary(
        self, tmp_path: Path, home: Path
    ) -> None:
        binary = _fake_claude(tmp_path, has_bare=True)
        settings_path = home / ".claude" / "settings.json"
        adapter = ClaudeAdapter(binary_path=binary, settings_path=settings_path)
        result = adapter.install(consent=True)
        assert result.level_installed == "shim-only"
        # Bare/shim-only still must not inject managed block.
        assert not settings_path.exists()
        assert result.files_modified == ()

    # ----- uninstall() ------------------------------------------------

    def test_uninstall_restores_backup_when_present(
        self, tmp_path: Path, home: Path
    ) -> None:
        binary = _fake_claude(tmp_path)
        settings_path = home / ".claude" / "settings.json"
        settings_path.parent.mkdir(parents=True)
        original = {"theme": "dark"}
        settings_path.write_text(json.dumps(original, sort_keys=True, indent=2))
        adapter = ClaudeAdapter(binary_path=binary, settings_path=settings_path)
        adapter.install(consent=True)
        # After install: agentlens key present, backup exists.
        adapter.uninstall()
        # Settings restored byte-equal to original; no agentlens key.
        restored = json.loads(settings_path.read_text())
        assert restored == original
        assert "agentlens" not in restored

    def test_uninstall_removes_only_agentlens_key_when_no_backup(
        self, tmp_path: Path, home: Path
    ) -> None:
        binary = _fake_claude(tmp_path)
        settings_path = home / ".claude" / "settings.json"
        settings_path.parent.mkdir(parents=True)
        # Hand-craft a settings file with agentlens key but no backup file.
        doc = {
            "theme": "dark",
            "agentlens": {"managed_by": "agentlens", "version": 1},
        }
        settings_path.write_text(json.dumps(doc, sort_keys=True, indent=2))
        adapter = ClaudeAdapter(binary_path=binary, settings_path=settings_path)
        adapter.uninstall()
        after = json.loads(settings_path.read_text())
        assert "agentlens" not in after
        assert after["theme"] == "dark"

    def test_uninstall_is_noop_when_nothing_to_remove(
        self, tmp_path: Path, home: Path
    ) -> None:
        binary = _fake_claude(tmp_path)
        settings_path = home / ".claude" / "settings.json"
        adapter = ClaudeAdapter(binary_path=binary, settings_path=settings_path)
        # No settings file, no agentlens key, no backup → must not raise.
        adapter.uninstall()
        assert not settings_path.exists()


# ---------------------------------------------------------------------------
# Codex CLI adapter — spec §5.18 (task_20)
# ---------------------------------------------------------------------------


def _fake_codex(
    dirpath: Path,
    *,
    version: str = "0.4.2",
    has_exec: bool = True,
    has_plugin: bool = True,
    has_mcp: bool = True,
    has_app_server: bool = True,
) -> Path:
    """Write a deterministic fake ``codex`` binary that mimics subcommands.

    The shim emits a fake ``--version`` line and dispatches on the first
    argument so that ``CodexCliAdapter.detect`` can probe ``exec --help``,
    ``plugin --help``, ``mcp --help``, and ``app-server --help`` without
    needing a real Codex CLI.
    """
    binary = dirpath / "codex"
    lines: list[str] = ["#!/bin/sh"]
    lines.append(f'if [ "$1" = "--version" ]; then echo "codex {version}"; exit 0; fi')
    # codex exec --help
    if has_exec:
        lines.append(
            'if [ "$1" = "exec" ] && [ "$2" = "--help" ]; then '
            'echo "Usage: codex exec [options] -- <cmd>"; exit 0; fi'
        )
    else:
        lines.append(
            'if [ "$1" = "exec" ]; then echo "unknown subcommand" >&2; exit 2; fi'
        )
    if has_plugin:
        lines.append(
            'if [ "$1" = "plugin" ] && [ "$2" = "--help" ]; then '
            'echo "Usage: codex plugin"; exit 0; fi'
        )
    else:
        lines.append(
            'if [ "$1" = "plugin" ]; then echo "unknown subcommand" >&2; exit 2; fi'
        )
    if has_mcp:
        lines.append(
            'if [ "$1" = "mcp" ] && [ "$2" = "--help" ]; then '
            'echo "Usage: codex mcp"; exit 0; fi'
        )
    else:
        lines.append(
            'if [ "$1" = "mcp" ]; then echo "unknown subcommand" >&2; exit 2; fi'
        )
    if has_app_server:
        lines.append(
            'if [ "$1" = "app-server" ] && [ "$2" = "--help" ]; then '
            'echo "Usage: codex app-server"; exit 0; fi'
        )
    else:
        lines.append(
            'if [ "$1" = "app-server" ]; then echo "unknown subcommand" >&2; exit 2; fi'
        )
    lines.append("exit 0")
    binary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    binary.chmod(0o755)
    return binary


class TestCodexCliAdapter:
    # ----- detect() ---------------------------------------------------

    def test_codex_cli_detect_unavailable_when_binary_missing(
        self, tmp_path: Path
    ) -> None:
        from agentlens.adapters.codex_cli import CodexCliAdapter

        adapter = CodexCliAdapter(binary_path=tmp_path / "nope")
        result = adapter.detect()
        assert result.available is False
        assert result.level == "unavailable"

    def test_codex_cli_detect_full_when_exec_supported(
        self, tmp_path: Path
    ) -> None:
        from agentlens.adapters.codex_cli import CodexCliAdapter

        binary = _fake_codex(tmp_path, has_exec=True)
        adapter = CodexCliAdapter(binary_path=binary)
        result = adapter.detect()
        assert result.available is True
        assert result.level == "full"
        assert any("version=" in n for n in result.notes)
        assert any("exec=yes" in n for n in result.notes)

    def test_codex_cli_detect_full_even_without_mcp_plugin(
        self, tmp_path: Path
    ) -> None:
        from agentlens.adapters.codex_cli import CodexCliAdapter

        # mcp / plugin / app-server are bonus — their absence must NOT
        # downgrade from ``full`` when ``exec`` is supported.
        binary = _fake_codex(
            tmp_path,
            has_exec=True,
            has_plugin=False,
            has_mcp=False,
            has_app_server=False,
        )
        adapter = CodexCliAdapter(binary_path=binary)
        result = adapter.detect()
        assert result.level == "full"

    def test_codex_cli_detect_shim_only_when_exec_missing(
        self, tmp_path: Path
    ) -> None:
        from agentlens.adapters.codex_cli import CodexCliAdapter

        binary = _fake_codex(tmp_path, has_exec=False)
        adapter = CodexCliAdapter(binary_path=binary)
        result = adapter.detect()
        assert result.available is True
        assert result.level == "shim-only"
        assert any("exec=no" in n for n in result.notes)

    # ----- install() / uninstall() ------------------------------------

    def test_codex_cli_install_creates_shim_and_lockfile(
        self, tmp_path: Path, home: Path
    ) -> None:
        from agentlens.adapters.codex_cli import CodexCliAdapter

        binary = _fake_codex(tmp_path)
        adapter = CodexCliAdapter(binary_path=binary)
        result = adapter.install(consent=True)
        shim = home / ".agentlens" / "shims" / "codex"
        lockfile = home / ".agentlens" / "shims" / "codex.real"
        assert shim.is_file()
        assert lockfile.is_file()
        assert result.level_installed == "full"
        assert shim in result.files_modified
        assert lockfile in result.files_modified

    def test_codex_cli_install_without_consent_is_noop(
        self, tmp_path: Path, home: Path
    ) -> None:
        from agentlens.adapters.codex_cli import CodexCliAdapter

        binary = _fake_codex(tmp_path)
        adapter = CodexCliAdapter(binary_path=binary)
        result = adapter.install(consent=False)
        assert result.level_installed == "unavailable"
        assert result.files_modified == ()
        assert not (home / ".agentlens" / "shims" / "codex").exists()

    def test_codex_cli_install_unavailable_when_no_binary(
        self, tmp_path: Path, home: Path
    ) -> None:
        from agentlens.adapters.codex_cli import CodexCliAdapter

        adapter = CodexCliAdapter(binary_path=tmp_path / "missing")
        result = adapter.install(consent=True)
        assert result.level_installed == "unavailable"
        assert result.files_modified == ()
        assert not (home / ".agentlens" / "shims" / "codex").exists()

    def test_codex_cli_uninstall_removes_shim_and_lockfile(
        self, tmp_path: Path, home: Path
    ) -> None:
        from agentlens.adapters.codex_cli import CodexCliAdapter

        binary = _fake_codex(tmp_path)
        adapter = CodexCliAdapter(binary_path=binary)
        adapter.install(consent=True)
        shim = home / ".agentlens" / "shims" / "codex"
        lockfile = home / ".agentlens" / "shims" / "codex.real"
        assert shim.exists() and lockfile.exists()
        adapter.uninstall()
        assert not shim.exists()
        assert not lockfile.exists()

    def test_codex_cli_uninstall_idempotent(
        self, tmp_path: Path, home: Path
    ) -> None:
        from agentlens.adapters.codex_cli import CodexCliAdapter

        adapter = CodexCliAdapter(binary_path=tmp_path / "missing")
        # Two consecutive uninstalls must be no-ops.
        adapter.uninstall()
        adapter.uninstall()
        assert not (home / ".agentlens" / "shims" / "codex").exists()


# ---------------------------------------------------------------------------
# Codex App adapter — spec §5.18 (task_21)
# ---------------------------------------------------------------------------


# Path to the pinned Codex 0.129.0 session-JSONL fixture. The adapter's
# session-format-version probe is asserted against this file so that any
# upstream change to the on-disk shape forces a fixture refresh.
PINNED_CODEX_APP_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "codex_app_sessions"
    / "0.129.0"
    / "sample_session.jsonl"
)


def _fake_codex_app_server(
    dirpath: Path,
    *,
    version: str = "0.129.0",
    has_app_server: bool = True,
    experimental_marker: bool = True,
) -> Path:
    """Write a deterministic fake ``codex`` binary that mimics ``app-server``.

    When ``has_app_server`` is true, ``codex app-server --help`` exits 0
    and includes the literal ``[experimental]`` marker in its output
    (gated by ``experimental_marker``). ``codex --version`` always works.
    Other subcommands exit non-zero so the adapter's detect() can rely on
    the ``app-server --help`` signal alone.
    """
    binary = dirpath / "codex"
    lines: list[str] = ["#!/bin/sh"]
    lines.append(f'if [ "$1" = "--version" ]; then echo "codex {version}"; exit 0; fi')
    if has_app_server:
        marker = "[experimental]" if experimental_marker else ""
        lines.append(
            'if [ "$1" = "app-server" ] && [ "$2" = "--help" ]; then '
            f'echo "Usage: codex app-server {marker}"; exit 0; fi'
        )
    else:
        lines.append(
            'if [ "$1" = "app-server" ]; then echo "unknown subcommand" >&2; exit 2; fi'
        )
    lines.append("exit 0")
    binary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    binary.chmod(0o755)
    return binary


class TestCodexAppAdapter:
    # ----- detect() ---------------------------------------------------

    def test_codex_app_detect_unavailable_when_no_sessions_and_no_binary(
        self, tmp_path: Path, home: Path
    ) -> None:
        from agentlens.adapters.codex_app import CodexAppAdapter

        # No ~/.codex/sessions, no codex binary on PATH.
        adapter = CodexAppAdapter(
            home_dir=home, codex_binary=tmp_path / "nope"
        )
        result = adapter.detect()
        assert result.available is False
        assert result.level == "unavailable"

    def test_codex_app_detect_watcher_only_when_sessions_exist(
        self, tmp_path: Path, home: Path
    ) -> None:
        from agentlens.adapters.codex_app import CodexAppAdapter

        sessions = home / ".codex" / "sessions"
        sessions.mkdir(parents=True)
        adapter = CodexAppAdapter(
            home_dir=home, codex_binary=tmp_path / "nope"
        )
        result = adapter.detect()
        assert result.available is True
        assert result.level == "watcher-only"

    def test_codex_app_detect_watcher_only_with_archived_sessions(
        self, tmp_path: Path, home: Path
    ) -> None:
        from agentlens.adapters.codex_app import CodexAppAdapter

        archived = home / ".codex" / "archived_sessions"
        archived.mkdir(parents=True)
        adapter = CodexAppAdapter(
            home_dir=home, codex_binary=tmp_path / "nope"
        )
        result = adapter.detect()
        assert result.available is True
        assert result.level == "watcher-only"

    def test_codex_app_detect_native_experimental_when_app_server_marked(
        self, tmp_path: Path, home: Path
    ) -> None:
        from agentlens.adapters.codex_app import CodexAppAdapter

        binary = _fake_codex_app_server(
            tmp_path, has_app_server=True, experimental_marker=True
        )
        # Create the sessions dir as well so we know app-server wins.
        (home / ".codex" / "sessions").mkdir(parents=True)
        adapter = CodexAppAdapter(home_dir=home, codex_binary=binary)
        result = adapter.detect()
        assert result.available is True
        assert result.level == "native-experimental"
        assert any("app_server=yes" in n for n in result.notes)
        assert any("experimental=yes" in n for n in result.notes)

    def test_codex_app_detect_falls_back_to_watcher_when_no_experimental_marker(
        self, tmp_path: Path, home: Path
    ) -> None:
        from agentlens.adapters.codex_app import CodexAppAdapter

        # app-server --help succeeds but does NOT advertise [experimental].
        binary = _fake_codex_app_server(
            tmp_path, has_app_server=True, experimental_marker=False
        )
        (home / ".codex" / "sessions").mkdir(parents=True)
        adapter = CodexAppAdapter(home_dir=home, codex_binary=binary)
        result = adapter.detect()
        # Per R1: never `full` — at most native-experimental, here watcher-only.
        assert result.level == "watcher-only"

    def test_codex_app_detect_never_reports_full(
        self, tmp_path: Path, home: Path
    ) -> None:
        """R1 policy: Codex App adapter MUST NEVER classify as `full`."""
        from agentlens.adapters.codex_app import CodexAppAdapter

        cases: list[tuple[str, "CodexAppAdapter"]] = []
        # 1) No sessions, no binary
        cases.append(
            (
                "no-signal",
                CodexAppAdapter(home_dir=home, codex_binary=tmp_path / "missing"),
            )
        )
        # 2) Sessions present, no binary
        sessions = home / ".codex" / "sessions"
        sessions.mkdir(parents=True, exist_ok=True)
        cases.append(
            (
                "watcher",
                CodexAppAdapter(home_dir=home, codex_binary=tmp_path / "missing"),
            )
        )
        # 3) app-server with experimental marker
        binary = _fake_codex_app_server(
            tmp_path, has_app_server=True, experimental_marker=True
        )
        cases.append(
            ("native", CodexAppAdapter(home_dir=home, codex_binary=binary))
        )
        for label, adapter in cases:
            assert adapter.detect().level != "full", label

    # ----- install() / uninstall() ------------------------------------

    def test_codex_app_install_creates_marker_file(
        self, tmp_path: Path, home: Path
    ) -> None:
        from agentlens.adapters.codex_app import CodexAppAdapter

        (home / ".codex" / "sessions").mkdir(parents=True)
        adapter = CodexAppAdapter(
            home_dir=home, codex_binary=tmp_path / "missing"
        )
        result = adapter.install(consent=True)
        assert result.level_installed == "watcher-only"
        marker = home / ".agentlens" / "integrations" / "codex_app" / "enabled"
        assert marker.is_file()
        assert marker in result.files_modified
        body = marker.read_text(encoding="utf-8")
        assert "watcher-only" in body

    def test_codex_app_install_without_consent_is_noop(
        self, tmp_path: Path, home: Path
    ) -> None:
        from agentlens.adapters.codex_app import CodexAppAdapter

        (home / ".codex" / "sessions").mkdir(parents=True)
        adapter = CodexAppAdapter(
            home_dir=home, codex_binary=tmp_path / "missing"
        )
        result = adapter.install(consent=False)
        assert result.level_installed == "unavailable"
        assert result.files_modified == ()
        assert not (
            home / ".agentlens" / "integrations" / "codex_app" / "enabled"
        ).exists()

    def test_codex_app_install_unavailable_does_not_create_marker(
        self, tmp_path: Path, home: Path
    ) -> None:
        from agentlens.adapters.codex_app import CodexAppAdapter

        # No sessions, no binary → unavailable, no marker.
        adapter = CodexAppAdapter(
            home_dir=home, codex_binary=tmp_path / "missing"
        )
        result = adapter.install(consent=True)
        assert result.level_installed == "unavailable"
        assert result.files_modified == ()
        assert not (
            home / ".agentlens" / "integrations" / "codex_app" / "enabled"
        ).exists()

    def test_codex_app_uninstall_removes_marker_and_is_idempotent(
        self, tmp_path: Path, home: Path
    ) -> None:
        from agentlens.adapters.codex_app import CodexAppAdapter

        (home / ".codex" / "sessions").mkdir(parents=True)
        adapter = CodexAppAdapter(
            home_dir=home, codex_binary=tmp_path / "missing"
        )
        adapter.install(consent=True)
        marker = home / ".agentlens" / "integrations" / "codex_app" / "enabled"
        assert marker.exists()
        adapter.uninstall()
        assert not marker.exists()
        # Second uninstall must not raise.
        adapter.uninstall()
        assert not marker.exists()

    # ----- iter_sessions / version detection --------------------------

    def test_codex_app_iter_sessions_yields_jsonl_files(
        self, tmp_path: Path, home: Path
    ) -> None:
        from agentlens.adapters.codex_app import iter_sessions

        sessions = home / ".codex" / "sessions"
        sessions.mkdir(parents=True)
        s1 = sessions / "a.jsonl"
        s1.write_text("{}\n", encoding="utf-8")
        # Non-jsonl files must be ignored.
        (sessions / "notes.txt").write_text("ignore me", encoding="utf-8")
        results = list(iter_sessions(home))
        assert s1 in results
        assert all(p.suffix == ".jsonl" for p in results)

    def test_codex_app_detect_session_format_version_from_pinned_fixture(
        self,
    ) -> None:
        from agentlens.adapters.codex_app import (
            PINNED_CODEX_APP_VERSION,
            detect_session_format_version,
        )

        assert PINNED_CODEX_APP_FIXTURE.is_file(), "fixture missing"
        version = detect_session_format_version(PINNED_CODEX_APP_FIXTURE)
        assert version == PINNED_CODEX_APP_VERSION == "0.129.0"

    def test_codex_app_detect_session_format_version_none_for_missing(
        self, tmp_path: Path
    ) -> None:
        from agentlens.adapters.codex_app import detect_session_format_version

        assert detect_session_format_version(tmp_path / "nope.jsonl") is None

    def test_codex_app_detect_fixture_mismatch_warning(
        self, tmp_path: Path, home: Path
    ) -> None:
        from agentlens.adapters.codex_app import CodexAppAdapter

        sessions = home / ".codex" / "sessions"
        sessions.mkdir(parents=True)
        future = sessions / "future.jsonl"
        future.write_text(
            '{"session_id": "ses_zzz", "version": "0.130.0", '
            '"kind": "session.started"}\n',
            encoding="utf-8",
        )
        adapter = CodexAppAdapter(
            home_dir=home, codex_binary=tmp_path / "missing"
        )
        result = adapter.detect()
        # Doctor consumes this note to warn about pinning drift.
        assert any(
            "fixture update required" in n and "0.130.0" in n and "0.129.0" in n
            for n in result.notes
        ), result.notes
