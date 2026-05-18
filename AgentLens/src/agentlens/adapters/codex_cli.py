"""Codex CLI adapter — probe + shim install (spec §5.18).

The Codex CLI adapter is the bridge between AgentLens and OpenAI's Codex
CLI. Unlike the Claude adapter (which injects a managed settings block),
Codex integration is shim-driven: the adapter installs a shim onto the
user's PATH via :mod:`agentlens.adapters.shims` and lets the wrapper
record sessions through ``agentlens run``.

Probe semantics (spec §5.18):

* ``codex --version``, ``codex exec --help``, ``codex plugin --help``,
  ``codex mcp --help``, ``codex app-server --help``.
* ``exec`` support is the load-bearing capability — when it succeeds the
  level is ``full`` even if ``plugin`` / ``mcp`` / ``app-server`` are
  absent (those are bonus capabilities, not gating).
* When the binary is present but ``exec`` is missing, the adapter
  degrades to ``shim-only`` so the wrapper can still record passthrough
  invocations.
* When the binary is missing entirely, the level is ``unavailable``.

Install/uninstall delegate to :func:`agentlens.adapters.shims.install_shim`
and :func:`agentlens.adapters.shims.uninstall_shim` for ``name="codex"``.
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from agentlens.adapters.shims import install_shim, uninstall_shim

DetectLevel = Literal[
    "full",
    "native-experimental",
    "shim-only",
    "watcher-only",
    "unavailable",
]


@dataclass(frozen=True)
class DetectResult:
    """Outcome of an adapter's probe (spec §5.18)."""

    available: bool
    level: DetectLevel
    notes: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class InstallResult:
    """Outcome of an adapter install (spec §5.18)."""

    level_installed: str
    files_modified: tuple[Path, ...] = field(default_factory=tuple)


def _run_capture(cmd: list[str], timeout: float = 5.0) -> tuple[int, str]:
    """Run ``cmd`` and return ``(returncode, combined_stdout_stderr)``.

    Returns ``(-1, "")`` if the command cannot be executed at all (e.g.
    ``FileNotFoundError``, ``PermissionError``, timeout). Probe callers
    treat that as "no signal" rather than raising.
    """
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (FileNotFoundError, PermissionError, subprocess.TimeoutExpired, OSError):
        return -1, ""
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _shim_paths() -> tuple[Path, Path]:
    """Return ``(shim_path, lockfile_path)`` under ``$HOME/.agentlens/shims``."""
    shim_dir = Path.home() / ".agentlens" / "shims"
    return shim_dir / "codex", shim_dir / "codex.real"


class CodexCliAdapter:
    """Codex CLI adapter implementing the spec §5.18 ``Adapter`` protocol."""

    name = "codex"

    def __init__(
        self,
        *,
        binary_path: Path | None = None,
    ) -> None:
        # Resolve the binary path lazily — ``None`` means "look up ``codex``
        # on PATH". Tests inject a concrete path to a fake script.
        if binary_path is None:
            resolved = shutil.which("codex")
            self._binary_path: Path | None = Path(resolved) if resolved else None
        else:
            self._binary_path = Path(binary_path)

    # ------------------------------------------------------------------
    # Probe
    # ------------------------------------------------------------------

    def detect(self) -> DetectResult:
        binary = self._binary_path
        if binary is None or not binary.exists():
            return DetectResult(
                available=False,
                level="unavailable",
                notes=("binary=missing",),
            )

        version_rc, version_out = _run_capture([str(binary), "--version"])
        exec_rc, _ = _run_capture([str(binary), "exec", "--help"])
        plugin_rc, _ = _run_capture([str(binary), "plugin", "--help"])
        mcp_rc, _ = _run_capture([str(binary), "mcp", "--help"])
        app_server_rc, _ = _run_capture([str(binary), "app-server", "--help"])

        version_token = self._parse_version(version_out) if version_rc == 0 else None
        has_exec = exec_rc == 0
        has_plugin = plugin_rc == 0
        has_mcp = mcp_rc == 0
        has_app_server = app_server_rc == 0

        notes: tuple[str, ...] = (
            f"version={version_token or 'unknown'}",
            f"exec={'yes' if has_exec else 'no'}",
            f"plugin={'yes' if has_plugin else 'no'}",
            f"mcp={'yes' if has_mcp else 'no'}",
            f"app_server={'yes' if has_app_server else 'no'}",
        )

        # `exec` is load-bearing — bonus subcommands (plugin/mcp/app-server)
        # don't gate the `full` classification (spec §5.18).
        if has_exec:
            return DetectResult(available=True, level="full", notes=notes)
        return DetectResult(available=True, level="shim-only", notes=notes)

    @staticmethod
    def _parse_version(stdout: str) -> str | None:
        """Extract a ``MAJOR.MINOR.PATCH``-ish token from ``--version`` output."""
        for token in stdout.replace("\n", " ").split():
            stripped = token.strip().strip("v").rstrip(".,;:")
            if stripped and stripped[0].isdigit() and "." in stripped:
                return stripped
        return None

    # ------------------------------------------------------------------
    # Install
    # ------------------------------------------------------------------

    def install(self, *, consent: bool) -> InstallResult:
        # Spec §S1.10.1: adapters must not modify the filesystem without consent.
        if not consent:
            return InstallResult(level_installed="unavailable", files_modified=())

        probe = self.detect()
        if probe.level == "unavailable":
            return InstallResult(level_installed="unavailable", files_modified=())

        # Primary integration for Codex is the PATH shim (spec §5.18).
        assert self._binary_path is not None  # guarded by probe.level check
        install_shim("codex", self._binary_path)
        shim_path, lockfile_path = _shim_paths()
        return InstallResult(
            level_installed=probe.level,
            files_modified=(shim_path, lockfile_path),
        )

    # ------------------------------------------------------------------
    # Uninstall
    # ------------------------------------------------------------------

    def uninstall(self) -> None:
        # Idempotent: ``uninstall_shim`` uses ``unlink(missing_ok=True)``.
        uninstall_shim("codex")


__all__ = [
    "CodexCliAdapter",
    "DetectResult",
    "InstallResult",
]
