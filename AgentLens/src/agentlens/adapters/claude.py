"""Claude adapter — probe + settings injection (spec §5.18, §S1.6.19, §S1.10.1).

The Claude adapter is the bridge between AgentLens and Anthropic's Claude
CLI. It exposes three operations on a single ``ClaudeAdapter`` instance:

* ``detect()`` probes the ``claude`` binary with ``--version`` and ``--help``
  and classifies its level (``full``/``shim-only``/``unavailable``) based on
  which flags the help text advertises (``--include-hook-events``,
  ``--output-format <stream-json>``, ``--bare``).
* ``install(consent=...)`` backs up ``~/.claude/settings.json`` and injects a
  managed ``"agentlens"`` block (only that key). On ``--bare`` builds the
  install gracefully degrades to ``shim-only`` and does NOT touch settings.
* ``uninstall()`` restores the backup byte-equal if present, otherwise removes
  only the ``"agentlens"`` key from the settings file.

The adapter never executes the real Claude CLI from tests: ``binary_path``
and ``settings_path`` are injectable so unit tests can point them at fake
binaries / scratch directories.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

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


# Managed-block schema (spec §S1.6.19): deterministic minimal payload that
# lets the doctor command verify the AgentLens-owned subset of settings.json.
_MANAGED_BLOCK: dict = {
    "managed_by": "agentlens",
    "version": 1,
    "hooks": {"include_hook_events": True},
    "output_format": "stream-json",
}


def _default_settings_path() -> Path:
    return Path.home() / ".claude" / "settings.json"


def _backup_path_for(settings_path: Path) -> Path:
    """Return the per-settings backup path (e.g. ``settings.json.agentlens.bak``)."""
    return settings_path.with_suffix(settings_path.suffix + ".agentlens.bak")


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


class ClaudeAdapter:
    """Claude adapter implementing the spec §5.18 ``Adapter`` protocol."""

    name = "claude"

    def __init__(
        self,
        *,
        binary_path: Path | None = None,
        settings_path: Path | None = None,
    ) -> None:
        # Resolve the binary path lazily — ``None`` means "look up ``claude``
        # on PATH". Tests inject a concrete path to a fake script.
        if binary_path is None:
            resolved = shutil.which("claude")
            self._binary_path: Path | None = Path(resolved) if resolved else None
        else:
            self._binary_path = Path(binary_path)
        self._settings_path = (
            Path(settings_path) if settings_path is not None else _default_settings_path()
        )

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
        help_rc, help_out = _run_capture([str(binary), "--help"])

        version_token = self._parse_version(version_out) if version_rc == 0 else None
        has_hook_events = "--include-hook-events" in help_out
        has_stream_json = "--output-format" in help_out and "stream-json" in help_out
        has_bare = "--bare" in help_out

        notes: list[str] = [
            f"version={version_token or 'unknown'}",
            f"hook_events={'yes' if has_hook_events else 'no'}",
            f"stream_json={'yes' if has_stream_json else 'no'}",
            f"bare={'yes' if has_bare else 'no'}",
        ]

        if has_bare:
            # `--bare` builds are minimal/headless: degrade to shim-only
            # regardless of the other markers.
            return DetectResult(
                available=True, level="shim-only", notes=tuple(notes)
            )
        if has_hook_events and has_stream_json:
            return DetectResult(available=True, level="full", notes=tuple(notes))
        return DetectResult(available=True, level="shim-only", notes=tuple(notes))

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
        # Defensive check — the CLI install command also gates on consent,
        # but adapters must not modify the filesystem without it (spec §S1.10.1).
        if not consent:
            return InstallResult(level_installed="unavailable", files_modified=())

        probe = self.detect()
        if probe.level == "unavailable":
            return InstallResult(level_installed="unavailable", files_modified=())
        if probe.level == "shim-only":
            # `--bare` / missing-flag builds: do not touch settings.json.
            return InstallResult(level_installed="shim-only", files_modified=())

        settings_path = self._settings_path
        settings_path.parent.mkdir(parents=True, exist_ok=True)

        files_modified: list[Path] = []
        if settings_path.exists():
            backup = _backup_path_for(settings_path)
            shutil.copyfile(settings_path, backup)
            current = json.loads(settings_path.read_text(encoding="utf-8"))
            if not isinstance(current, dict):
                # Settings file is non-object JSON — replace wholesale but
                # still keep the backup so uninstall can restore it.
                current = {}
            files_modified.append(backup)
        else:
            current = {}

        current["agentlens"] = dict(_MANAGED_BLOCK)
        settings_path.write_text(
            json.dumps(current, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        files_modified.append(settings_path)

        return InstallResult(
            level_installed=probe.level,
            files_modified=tuple(files_modified),
        )

    # ------------------------------------------------------------------
    # Uninstall
    # ------------------------------------------------------------------

    def uninstall(self) -> None:
        settings_path = self._settings_path
        if not settings_path.exists():
            return
        try:
            current = json.loads(settings_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(current, dict) or "agentlens" not in current:
            return

        backup = _backup_path_for(settings_path)
        if backup.exists():
            # Spec §S1.6.19: restore backup byte-equal, then drop the
            # backup file so re-install can take a fresh snapshot.
            shutil.copyfile(backup, settings_path)
            backup.unlink()
            return

        # No backup → strip only the AgentLens-owned key, keep the rest.
        current.pop("agentlens", None)
        settings_path.write_text(
            json.dumps(current, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )


__all__ = [
    "ClaudeAdapter",
    "DetectResult",
    "InstallResult",
]
