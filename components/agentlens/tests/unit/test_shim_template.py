"""Tests for SHIM_TEMPLATE selftest branch (spec §S1.4.4).

The shim template gains a Layer-4 post-install selftest branch that fires
only when ``AGENTLENS_INSTALL_SELFTEST=1`` and the first positional arg is
exactly ``--version``. The branch must be inserted AFTER the lockfile is
read and ``REAL_PATH`` is set, but BEFORE the sha-drift / TTY / nested /
admin / ``agentlens run`` branches so the recursion guard runs early.
"""
from __future__ import annotations

from agentlens.adapters.shims import CMUX_SHIM_TEMPLATE, SHIM_TEMPLATE


def _render_shim() -> str:
    return SHIM_TEMPLATE.format(
        name="claude",
        agent_name="claude_code",
        agentlens_bin="/usr/local/bin/agentlens",
    )


def _render_cmux() -> str:
    return CMUX_SHIM_TEMPLATE.format(
        agentlens_bin="/usr/local/bin/agentlens",
        backup_path="/Applications/cmux.app/Contents/Resources/bin/claude.cmux-original",
    )


def test_shim_template_renders_without_format_errors() -> None:
    """Brace escaping bug guard: both templates render with sample args."""
    assert _render_shim()
    assert _render_cmux()


def test_shim_template_contains_selftest_branch() -> None:
    rendered = _render_shim()
    assert "AGENTLENS_INSTALL_SELFTEST" in rendered
    assert "agentlens_selftest_reentry" in rendered
    # Branch must appear after REAL_PATH is set and before the TTY block.
    real_path_idx = rendered.index('REAL_PATH="$(awk')
    selftest_idx = rendered.index("AGENTLENS_INSTALL_SELFTEST")
    tty_idx = rendered.index("if [ -t 0 ]; then")
    assert real_path_idx < selftest_idx < tty_idx


def test_cmux_shim_template_contains_selftest_branch() -> None:
    rendered = _render_cmux()
    assert "AGENTLENS_INSTALL_SELFTEST" in rendered
    assert "agentlens_selftest_reentry" in rendered
    # Branch must appear after REAL_PATH= and before TTY block.
    real_path_idx = rendered.index('REAL_PATH="')
    selftest_idx = rendered.index("AGENTLENS_INSTALL_SELFTEST")
    tty_idx = rendered.index("if [ -t 0 ]; then")
    assert real_path_idx < selftest_idx < tty_idx


def test_shim_template_selftest_block_falls_through_for_non_version_argv() -> None:
    """The selftest branch must be gated by BOTH env=1 AND $1 == --version."""
    rendered = _render_shim()
    assert '[ "${AGENTLENS_INSTALL_SELFTEST:-}" = "1" ]' in rendered
    assert '[ "${1:-}" = "--version" ]' in rendered


def test_cmux_shim_template_selftest_block_falls_through_for_non_version_argv() -> None:
    rendered = _render_cmux()
    assert '[ "${AGENTLENS_INSTALL_SELFTEST:-}" = "1" ]' in rendered
    assert '[ "${1:-}" = "--version" ]' in rendered
