"""Integration tests for v1 TTY-aware shim passthrough (spec §4.5).

When the shim is invoked interactively (stdin is a TTY) and the agent's
interactive mode uses a TUI we cannot safely wrap with subprocess pipes,
the shim must pass through to the real binary. Recording for those
interactive sessions is handled post-hoc by the rollout/JSONL importers.

Non-interactive print modes (claude -p / --print / --output-format,
codex exec / codex e) must still wrap via `agentlens run --`.

Also asserts a regression guard: Codex Desktop's bundled binary
(inside an .app bundle) must not be silently shim-replaced.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from agentlens.adapters.shims import install_shim


@pytest.fixture()
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def _fake_binary(dirpath: Path, name: str) -> Path:
    binary = dirpath / name
    binary.write_bytes(b"#!/bin/sh\nexit 0\n")
    binary.chmod(0o755)
    return binary


def _read_shim(home: Path, name: str) -> str:
    return (home / ".agentlens" / "shims" / name).read_text(encoding="utf-8")


class TestTTYGuardPresence:
    def test_claude_shim_contains_tty_guard(self, home: Path, tmp_path: Path) -> None:
        install_shim("claude", _fake_binary(tmp_path, "claude"))
        shim = _read_shim(home, "claude")
        assert "if [ -t 0 ]; then" in shim, (
            "claude shim must include a stdin-TTY guard for interactive passthrough"
        )

    def test_codex_shim_contains_tty_guard(self, home: Path, tmp_path: Path) -> None:
        install_shim("codex", _fake_binary(tmp_path, "codex"))
        shim = _read_shim(home, "codex")
        assert "if [ -t 0 ]; then" in shim


class TestClaudePrintModeStillWraps:
    """The TTY guard must NOT short-circuit -p / --print / stream-json modes."""

    def test_claude_dash_p_branch_does_not_exec_passthrough(
        self, home: Path, tmp_path: Path
    ) -> None:
        install_shim("claude", _fake_binary(tmp_path, "claude"))
        shim = _read_shim(home, "claude")
        # The TTY block must list -p, --print, --output-format as wrap-cases
        # (empty case bodies that fall through), NOT as exec-passthrough cases.
        # Concretely: the substring matching the print-mode branch must
        # appear, AND it must not exec REAL_PATH inside its body.
        assert "-p|--print|--output-format" in shim, (
            "print-mode flags must be enumerated as wrap-cases inside the TTY guard"
        )
        # Locate the print-mode branch and verify its body does NOT exec.
        idx = shim.index("-p|--print|--output-format")
        # Body runs until ';;'. Grab a slice and inspect.
        branch_end = shim.index(";;", idx)
        branch_body = shim[idx:branch_end]
        assert 'exec "$REAL_PATH"' not in branch_body, (
            "claude -p / --print must continue to wrap, not passthrough"
        )


class TestClaudeInteractivePassthrough:
    def test_bare_claude_passes_through_under_tty(
        self, home: Path, tmp_path: Path
    ) -> None:
        install_shim("claude", _fake_binary(tmp_path, "claude"))
        shim = _read_shim(home, "claude")
        # The default (non-print) case inside the claude branch must
        # exec the real binary directly.
        idx = shim.index("if [ -t 0 ]; then")
        end = shim.index("fi", idx)
        guard_block = shim[idx:end]
        # Must contain a default `*) exec "$REAL_PATH" "$@" ;;` arm.
        assert 'exec "$REAL_PATH" "$@"' in guard_block, (
            "interactive (bare) claude must exec the real binary under a TTY"
        )


class TestCodexExecStillWraps:
    def test_codex_exec_and_e_alias_wrap(self, home: Path, tmp_path: Path) -> None:
        install_shim("codex", _fake_binary(tmp_path, "codex"))
        shim = _read_shim(home, "codex")
        assert "exec|e)" in shim, (
            "codex exec / e alias must be enumerated as wrap-cases inside the TTY guard"
        )
        # The `exec|e` branch body must NOT exec the real binary —
        # it must fall through to the `agentlens run --` invocation.
        idx = shim.index("exec|e)")
        branch_end = shim.index(";;", idx)
        branch_body = shim[idx:branch_end]
        assert 'exec "$REAL_PATH"' not in branch_body


class TestCodexInteractivePassthrough:
    def test_bare_codex_passes_through_under_tty(
        self, home: Path, tmp_path: Path
    ) -> None:
        install_shim("codex", _fake_binary(tmp_path, "codex"))
        shim = _read_shim(home, "codex")
        idx = shim.index("if [ -t 0 ]; then")
        end = shim.index("fi", idx)
        guard_block = shim[idx:end]
        # Default arm for codex (resume, fork, review, apply, login,
        # mcp, app, bare) must passthrough.
        assert 'exec "$REAL_PATH" "$@"' in guard_block


class TestTTYGuardOrdering:
    """The TTY guard must sit AFTER lockfile/SHA checks but BEFORE the
    nested-policy and admin-passthrough blocks, so that:
      - drift / missing lockfile still passes through (v0 invariant),
      - admin subcommands still work uniformly,
      - and the interactive guard applies before the agentlens-CLI lookup.
    """

    def test_tty_guard_after_sha_check_before_nested_block(
        self, home: Path, tmp_path: Path
    ) -> None:
        install_shim("claude", _fake_binary(tmp_path, "claude"))
        shim = _read_shim(home, "claude")
        sha_idx = shim.index("sha256 drift")
        tty_idx = shim.index("if [ -t 0 ]; then")
        nested_idx = shim.index("AGENTLENS_RUN_ID")
        assert sha_idx < tty_idx < nested_idx, (
            "TTY guard must be placed between the SHA-drift check and the "
            "nested-invocation policy block"
        )


class TestCodexDesktopBundledBinaryNotShimmed:
    """Regression guard: ``install_shim`` must NOT silently replace the
    Codex Desktop bundled binary at a path inside an ``.app`` bundle.

    Desktop capture is import-only via the rollout JSONL importer
    (Task 7b). Replacing the .app's bundled binary would break the
    code-signed bundle and is never the right move; callers wanting to
    shim a Desktop install must take an explicit, separate path.
    """

    def test_install_shim_refuses_app_bundle_path(
        self, home: Path, tmp_path: Path
    ) -> None:
        # Simulate a .app-bundled binary layout.
        bundled_dir = (
            tmp_path / "Applications" / "Codex.app" / "Contents" / "Resources" / "bin"
        )
        bundled_dir.mkdir(parents=True)
        bundled = bundled_dir / "codex"
        bundled.write_bytes(b"#!/bin/sh\nexit 0\n")
        bundled.chmod(0o755)

        with pytest.raises(ValueError, match=r"\.app"):
            install_shim("codex", bundled)
