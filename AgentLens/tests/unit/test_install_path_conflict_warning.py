"""Unit tests for Layer-3 PATH-conflict warning (spec §S1.4.3).

`agentlens install <agent>` captures `shutil.which(agent)` BEFORE writing
any files. After `install_shim` succeeds, the captured path is inspected
to decide whether a PATH-conflict warning is emitted to stderr:

- None → no warning
- same as resolved real_path → no warning
- non-shell-script (no `#!` prefix) → no warning
- otherwise → warning to stderr (non-blocking)
"""
from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from agentlens.cli import app


@pytest.fixture()
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect HOME so Path.home() == tmp_path during the test."""
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def _write_script(path: Path, body: str = '#!/bin/bash\nexit 0\n') -> Path:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)
    return path


def _write_bytes(path: Path, blob: bytes) -> Path:
    path.write_bytes(blob)
    path.chmod(0o755)
    return path


def _install_invoke(real_path: Path) -> "object":
    runner = CliRunner()
    return runner.invoke(
        app,
        [
            "install",
            "claude",
            "--real",
            str(real_path),
            "--yes",
            "--skip-selftest",
            "--no-wrapper-detect",
        ],
    )


class TestPathConflictWarning:
    def test_wrapper_script_pre_install_emits_warning(
        self,
        home: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """If `shutil.which('claude')` (captured pre-install) is a shell
        wrapper at a path != real_path, the install must warn to stderr."""
        wrapper = _write_script(
            tmp_path / "wrapper-claude",
            "#!/bin/bash\nexec /usr/local/bin/real-claude \"$@\"\n",
        )
        real_bin = _write_bytes(
            tmp_path / "real-claude",
            b"\xcf\xfa\xed\xfe" + b"\x00" * 32,
        )

        # Patch shutil.which globally — since monkeypatching
        # `agentlens.commands.install.shutil.which` mutates the actual stdlib
        # `shutil.which`, route by name. Only claude lookups are forced to
        # return the wrapper; other lookups (e.g. for "agentlens" CLI by
        # install_shim) delegate to the real shutil.which.
        import shutil as _real_shutil

        real_which = _real_shutil.which
        calls = {"claude_n": 0}

        def fake_which(name: str, *args, **kwargs):
            if name == "claude":
                calls["claude_n"] += 1
                if calls["claude_n"] == 1:
                    return str(wrapper)
                # subsequent lookups (e.g. post-install) would resolve to the
                # shim — return that so a non-pre_install_resolution-using
                # implementation would *not* trigger the warning, ensuring the
                # test only passes if the captured pre-install path is used.
                return str(home / ".agentlens" / "shims" / "claude")
            return real_which(name, *args, **kwargs)

        monkeypatch.setattr(
            "agentlens.commands.install.shutil.which", fake_which
        )

        result = _install_invoke(real_bin)
        assert result.exit_code == 0, (result.stdout, result.stderr)
        stderr = result.stderr or ""
        assert "warning: your shell currently resolves" in stderr, stderr
        assert str(wrapper) in stderr
        assert str(real_bin) in stderr
        assert "wrapper script" in stderr
        assert "--no-wrapper-detect" in stderr
        assert "--cmux" in stderr

    def test_same_path_emits_no_warning(
        self,
        home: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """If pre-install resolution resolves to the same path as real_path
        (the install is a no-op-from-PATH perspective), no warning."""
        # Use a binary Mach-O so Layer-1 wrapper scan would also pass
        # (we still --no-wrapper-detect for safety).
        real_bin = _write_bytes(
            tmp_path / "claude",
            b"\xcf\xfa\xed\xfe" + b"\x00" * 32,
        )

        import shutil as _real_shutil

        real_which = _real_shutil.which

        def fake_which(name: str, *args, **kwargs):
            if name == "claude":
                return str(real_bin)
            return real_which(name, *args, **kwargs)

        monkeypatch.setattr(
            "agentlens.commands.install.shutil.which", fake_which
        )

        result = _install_invoke(real_bin)
        assert result.exit_code == 0, (result.stdout, result.stderr)
        stderr = result.stderr or ""
        assert "warning: your shell currently resolves" not in stderr, stderr

    def test_macho_pre_install_emits_no_warning(
        self,
        home: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """If pre-install resolution is a Mach-O binary (no `#!` prefix),
        no warning — binary-vs-binary is normal homebrew/cask state."""
        macho_other = _write_bytes(
            tmp_path / "other-claude",
            b"\xcf\xfa\xed\xfe" + b"\x00" * 64,
        )
        real_bin = _write_bytes(
            tmp_path / "real-claude",
            b"\xcf\xfa\xed\xfe" + b"\x00" * 32,
        )

        import shutil as _real_shutil

        real_which = _real_shutil.which

        def fake_which(name: str, *args, **kwargs):
            if name == "claude":
                return str(macho_other)
            return real_which(name, *args, **kwargs)

        monkeypatch.setattr(
            "agentlens.commands.install.shutil.which", fake_which
        )

        result = _install_invoke(real_bin)
        assert result.exit_code == 0, (result.stdout, result.stderr)
        stderr = result.stderr or ""
        assert "warning: your shell currently resolves" not in stderr, stderr

    def test_none_pre_install_emits_no_warning(
        self,
        home: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """If `shutil.which('claude')` returns None pre-install, no warning."""
        real_bin = _write_bytes(
            tmp_path / "real-claude",
            b"\xcf\xfa\xed\xfe" + b"\x00" * 32,
        )

        import shutil as _real_shutil

        real_which = _real_shutil.which

        def fake_which(name: str, *args, **kwargs):
            if name == "claude":
                return None
            return real_which(name, *args, **kwargs)

        monkeypatch.setattr(
            "agentlens.commands.install.shutil.which", fake_which
        )

        result = _install_invoke(real_bin)
        assert result.exit_code == 0, (result.stdout, result.stderr)
        stderr = result.stderr or ""
        assert "warning: your shell currently resolves" not in stderr, stderr
