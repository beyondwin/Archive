"""Integration tests for the cmux chain install + doctor drift checks
(spec §4.6 cmux auto-detection at install).

The cmux chain is the deliberate exception to the v1 ``install_shim`` refusal
of ``.app``-bundled binaries (Task 6). When a user explicitly opts in via
``--cmux`` (or via interactive consent) the install routine:

  1. Backs up ``cmux.app/Contents/Resources/bin/claude`` →
     ``claude.cmux-original`` (preserving file mode).
  2. Writes the AgentLens shim at the cmux ``claude`` path with
     ``REAL_PATH = .../claude.cmux-original`` so the runtime chain becomes
     ``shim → cmux wrapper → real claude``.
  3. Records install metadata in ``~/.agentlens/cmux-install.json`` so that
     ``agentlens doctor`` can detect drift (missing backup, sha mismatch,
     binary mtime/version drift, permission failures).

These tests stand up a synthetic ``cmux.app`` tree under ``tmp_path`` and
inject it via the new ``--cmux-app`` flag so we never touch
``/Applications/...`` during tests.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agentlens.cli import app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture()
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)
    return tmp_path / "home"


def _make_fake_cmux_app(
    root: Path,
    *,
    claude_body: bytes = b"#!/bin/sh\n# cmux wrapper\nexec /usr/bin/true \"$@\"\n",
    mode: int = 0o755,
    info_plist_version: str | None = "1.5.0",
) -> Path:
    """Build a fake ``cmux.app`` bundle layout under *root*.

    Returns the path to the synthetic ``cmux.app`` directory.
    """
    app_dir = root / "cmux.app"
    bin_dir = app_dir / "Contents" / "Resources" / "bin"
    bin_dir.mkdir(parents=True)
    binary = bin_dir / "claude"
    binary.write_bytes(claude_body)
    os.chmod(binary, mode)
    if info_plist_version is not None:
        info_plist = app_dir / "Contents" / "Info.plist"
        info_plist.write_text(
            "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
            "<plist version=\"1.0\"><dict>\n"
            "  <key>CFBundleShortVersionString</key>\n"
            f"  <string>{info_plist_version}</string>\n"
            "</dict></plist>\n",
            encoding="utf-8",
        )
    return app_dir


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Install: cmux chain (consent + non-interactive paths)
# ---------------------------------------------------------------------------


class TestCmuxInstall:
    def test_install_cmux_with_yes_backs_up_and_writes_shim_chain(
        self, runner: CliRunner, home: Path, tmp_path: Path
    ) -> None:
        cmux_app = _make_fake_cmux_app(tmp_path)
        binary = cmux_app / "Contents" / "Resources" / "bin" / "claude"
        original_sha = _sha256(binary)
        original_mode = stat.S_IMODE(binary.stat().st_mode)

        result = runner.invoke(
            app,
            [
                "install",
                "claude",
                "--cmux",
                "--cmux-app",
                str(cmux_app),
                "--yes",
            ],
        )
        assert result.exit_code == 0, result.output

        backup = cmux_app / "Contents" / "Resources" / "bin" / "claude.cmux-original"
        shim = binary
        # Backup exists, preserves the original sha and mode.
        assert backup.is_file(), "backup file must exist"
        assert _sha256(backup) == original_sha
        assert stat.S_IMODE(backup.stat().st_mode) == original_mode

        # Shim now lives at the cmux claude path and points at the backup.
        shim_text = shim.read_text(encoding="utf-8")
        assert "AgentLens shim" in shim_text
        # Real-path lockfile must be co-located and target the backup.
        # Lockfile name encodes the chain so doctor can find it.
        cmux_lockfile = (
            cmux_app / "Contents" / "Resources" / "bin" / "claude.cmux-lockfile"
        )
        assert cmux_lockfile.is_file()
        lockfile_text = cmux_lockfile.read_text(encoding="utf-8")
        assert f"path={backup}" in lockfile_text
        assert "sha256=" in lockfile_text

        # Metadata file recorded under ~/.agentlens/cmux-install.json.
        meta_path = home / ".agentlens" / "cmux-install.json"
        assert meta_path.is_file(), "metadata file must be recorded"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        assert meta["cmux_app_path"] == str(cmux_app)
        assert meta["cmux_binary_path"] == str(binary)
        assert meta["cmux_backup_path"] == str(backup)
        assert meta["cmux_backup_sha256"] == original_sha
        assert meta["cmux_app_version"] == "1.5.0"
        assert isinstance(meta["cmux_binary_mtime"], (int, float))
        assert "installed_at" in meta

    def test_install_cmux_without_yes_and_no_tty_errors(
        self, runner: CliRunner, home: Path, tmp_path: Path
    ) -> None:
        """Non-interactive (no TTY) without ``--yes`` must error out — we
        refuse to silently modify a system .app bundle without consent.
        """
        cmux_app = _make_fake_cmux_app(tmp_path)
        binary = cmux_app / "Contents" / "Resources" / "bin" / "claude"
        original_sha = _sha256(binary)

        # CliRunner.invoke supplies no stdin TTY; without --yes we abort.
        result = runner.invoke(
            app,
            ["install", "claude", "--cmux", "--cmux-app", str(cmux_app)],
        )
        assert result.exit_code != 0, result.output
        assert "consent" in result.output.lower() or "--yes" in result.output

        # The binary must not have been touched.
        assert _sha256(binary) == original_sha
        backup = cmux_app / "Contents" / "Resources" / "bin" / "claude.cmux-original"
        assert not backup.exists()

    def test_install_without_cmux_flag_does_not_touch_app(
        self,
        runner: CliRunner,
        home: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Regression guard: without --cmux and with no auto-detect of
        ``/Applications/cmux.app``, the plain install path is unchanged.
        """
        cmux_app = _make_fake_cmux_app(tmp_path)
        # Provide a regular non-.app binary via --real so the plain install
        # path can still complete; the cmux app must NOT be touched.
        bindir = tmp_path / "stdbin"
        bindir.mkdir()
        plain = bindir / "claude"
        plain.write_bytes(b"#!/bin/sh\nexit 0\n")
        plain.chmod(0o755)

        # Make sure /Applications/cmux.app/... auto-detect is disabled by
        # the install command (we are not using --cmux-app here).
        result = runner.invoke(
            app,
            ["install", "claude", "--real", str(plain), "--yes"],
        )
        assert result.exit_code == 0, result.output

        binary = cmux_app / "Contents" / "Resources" / "bin" / "claude"
        backup = cmux_app / "Contents" / "Resources" / "bin" / "claude.cmux-original"
        # The cmux app must not have been touched.
        assert not backup.exists()
        # Plain shim path is the standard one.
        std_shim = home / ".agentlens" / "shims" / "claude"
        assert std_shim.is_file()


# ---------------------------------------------------------------------------
# Doctor: cmux chain drift checks
# ---------------------------------------------------------------------------


class TestCmuxDoctor:
    def test_doctor_reports_ok_after_clean_install(
        self, runner: CliRunner, home: Path, tmp_path: Path
    ) -> None:
        cmux_app = _make_fake_cmux_app(tmp_path)
        result = runner.invoke(
            app,
            [
                "install",
                "claude",
                "--cmux",
                "--cmux-app",
                str(cmux_app),
                "--yes",
            ],
        )
        assert result.exit_code == 0, result.output

        doc_result = runner.invoke(app, ["doctor", "all", "--format", "json"])
        assert doc_result.exit_code == 0, doc_result.output
        doc = json.loads(doc_result.output)
        assert "cmux" in doc, doc
        cmux = doc["cmux"]
        assert cmux["status"] == "ok", cmux
        assert cmux["backup_present"] is True
        assert cmux["backup_sha_match"] is True

    def test_doctor_reports_sha_drift_when_backup_changed(
        self, runner: CliRunner, home: Path, tmp_path: Path
    ) -> None:
        cmux_app = _make_fake_cmux_app(tmp_path)
        runner.invoke(
            app,
            [
                "install",
                "claude",
                "--cmux",
                "--cmux-app",
                str(cmux_app),
                "--yes",
            ],
        )
        # Mutate the backup binary's contents → sha drift.
        backup = cmux_app / "Contents" / "Resources" / "bin" / "claude.cmux-original"
        backup.write_bytes(b"#!/bin/sh\n# tampered\nexit 1\n")

        doc_result = runner.invoke(app, ["doctor", "all", "--format", "json"])
        assert doc_result.exit_code == 0, doc_result.output
        doc = json.loads(doc_result.output)
        cmux = doc["cmux"]
        assert cmux["status"] == "drift", cmux
        assert cmux["backup_present"] is True
        assert cmux["backup_sha_match"] is False

    def test_doctor_reports_missing_backup(
        self, runner: CliRunner, home: Path, tmp_path: Path
    ) -> None:
        cmux_app = _make_fake_cmux_app(tmp_path)
        runner.invoke(
            app,
            [
                "install",
                "claude",
                "--cmux",
                "--cmux-app",
                str(cmux_app),
                "--yes",
            ],
        )
        backup = cmux_app / "Contents" / "Resources" / "bin" / "claude.cmux-original"
        backup.unlink()

        doc_result = runner.invoke(app, ["doctor", "all", "--format", "json"])
        assert doc_result.exit_code == 0, doc_result.output
        doc = json.loads(doc_result.output)
        cmux = doc["cmux"]
        assert cmux["status"] == "missing_backup", cmux
        assert cmux["backup_present"] is False

    def test_doctor_reports_no_cmux_install_block_when_not_installed(
        self, runner: CliRunner, home: Path
    ) -> None:
        """When no cmux install metadata exists, doctor must still succeed
        and either omit the ``cmux`` block or mark it ``not_installed``.
        """
        doc_result = runner.invoke(app, ["doctor", "all", "--format", "json"])
        assert doc_result.exit_code == 0, doc_result.output
        doc = json.loads(doc_result.output)
        if "cmux" in doc:
            assert doc["cmux"]["status"] == "not_installed", doc["cmux"]


__all__: list[str] = []
