"""Codex App adapter — session-JSONL watcher + ``app-server`` probe (spec §5.18).

The Codex *App* is OpenAI's experimental desktop client. Unlike the Codex
CLI it does not expose a stable command-line surface — its primary
observable is the session log JSONL written into ``~/.codex/sessions``
(and ``~/.codex/archived_sessions``). v0 ships a *probe* and a *marker*
file; the continuous watcher subprocess itself is deferred to v1+
(:func:`iter_sessions` is the seam future code will hook into).

Classification (spec §5.18, R1):

* ``unavailable`` — no ``~/.codex/sessions``, no ``~/.codex/archived_sessions``,
  and no ``codex`` binary on PATH.
* ``watcher-only`` — at least one of the session dirs exists, but
  ``codex app-server --help`` either fails or does not advertise the
  literal ``[experimental]`` marker.
* ``native-experimental`` — ``codex app-server --help`` succeeds AND its
  output contains the literal ``[experimental]`` token.
* ``full`` — **NEVER** returned. Codex App is gated behind R1 as
  experimental; the adapter's max classification is
  ``native-experimental``. Tests assert this explicitly.

The session-JSONL format is pinned to Codex
:data:`PINNED_CODEX_APP_VERSION`. ``detect()`` compares the ``version``
field of the most recent session JSONL on disk against the pin and
appends a ``fixture update required`` note when they disagree; the
``doctor`` command surfaces that note so maintainers can refresh the
fixture in lockstep with upstream.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator, Literal

DetectLevel = Literal[
    "full",
    "native-experimental",
    "shim-only",
    "watcher-only",
    "unavailable",
]


# Pinned Codex App session-JSONL format version. Bumping this constant
# is the deliberate signal that the on-disk shape has changed and the
# fixture under ``tests/fixtures/codex_app_sessions/<version>/`` has
# been refreshed.
PINNED_CODEX_APP_VERSION = "0.129.0"


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


def iter_sessions(home_dir: Path) -> Iterator[Path]:
    """Yield every ``*.jsonl`` session log under the Codex session dirs.

    This is the v0 seam for the future continuous watcher subprocess:
    callers iterate session paths and the implementation is responsible
    for ordering / dedup. v0 simply walks ``~/.codex/sessions`` and
    ``~/.codex/archived_sessions`` and yields ``*.jsonl`` files.
    """
    for sub in (".codex/sessions", ".codex/archived_sessions"):
        root = home_dir / sub
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.jsonl")):
            if path.is_file():
                yield path


def detect_session_format_version(jsonl_path: Path) -> str | None:
    """Return the ``version`` field of the first JSONL record, or ``None``.

    The Codex App session log stamps each record with a ``version``
    token matching the Codex release; reading the first line is enough
    to classify the format. Returns ``None`` when the file is missing,
    empty, or the first line is not valid JSON / lacks a ``version``.
    """
    try:
        with jsonl_path.open("r", encoding="utf-8") as fh:
            first = fh.readline()
    except (OSError, ValueError):
        return None
    first = first.strip()
    if not first:
        return None
    try:
        record = json.loads(first)
    except (ValueError, TypeError):
        return None
    if not isinstance(record, dict):
        return None
    version = record.get("version")
    if isinstance(version, str) and version:
        return version
    return None


def _marker_path(home_dir: Path) -> Path:
    """Path of the adapter's "enabled" marker under ``~/.agentlens``."""
    return home_dir / ".agentlens" / "integrations" / "codex_app" / "enabled"


class CodexAppAdapter:
    """Codex App adapter implementing the spec §5.18 ``Adapter`` protocol.

    R1 policy: ``detect()`` MUST NEVER classify Codex App as ``full``
    — the experimental status of the desktop app caps it at
    ``native-experimental``. Enforcement lives both in the branch
    structure here and in the test suite
    (:class:`TestCodexAppAdapter.test_codex_app_detect_never_reports_full`).
    """

    name = "codex_app"

    def __init__(
        self,
        *,
        home_dir: Path | None = None,
        codex_binary: Path | str | None = None,
    ) -> None:
        self._home_dir = Path(home_dir) if home_dir is not None else Path.home()
        if codex_binary is None:
            resolved = shutil.which("codex")
            self._codex_binary: Path | None = Path(resolved) if resolved else None
        else:
            self._codex_binary = Path(codex_binary)

    # ------------------------------------------------------------------
    # Probe
    # ------------------------------------------------------------------

    def detect(self) -> DetectResult:
        home = self._home_dir
        sessions_dir = home / ".codex" / "sessions"
        archived_dir = home / ".codex" / "archived_sessions"
        sessions_present = sessions_dir.is_dir()
        archived_present = archived_dir.is_dir()
        any_session_dir = sessions_present or archived_present

        binary = self._codex_binary
        binary_present = binary is not None and binary.exists()

        # `app-server --help` probe (only meaningful when the binary exists).
        has_app_server = False
        has_experimental = False
        if binary_present:
            assert binary is not None  # for mypy
            rc, out = _run_capture([str(binary), "app-server", "--help"])
            has_app_server = rc == 0
            if has_app_server and "[experimental]" in out:
                has_experimental = True

        notes: list[str] = [
            f"sessions_dir={'yes' if sessions_present else 'no'}",
            f"archived_sessions_dir={'yes' if archived_present else 'no'}",
            f"binary={'yes' if binary_present else 'no'}",
            f"app_server={'yes' if has_app_server else 'no'}",
            f"experimental={'yes' if has_experimental else 'no'}",
        ]

        # Fixture-version drift check: scan the first session JSONL we
        # find and compare against the pin. Doctor surfaces this note.
        sample = next(iter_sessions(home), None)
        if sample is not None:
            sample_version = detect_session_format_version(sample)
            if sample_version and sample_version != PINNED_CODEX_APP_VERSION:
                notes.append(
                    "fixture update required: session format "
                    f"v{sample_version} != pinned {PINNED_CODEX_APP_VERSION}"
                )

        # ----- classification (R1: never `full`) -----
        if not any_session_dir and not binary_present:
            return DetectResult(
                available=False, level="unavailable", notes=tuple(notes)
            )
        if has_app_server and has_experimental:
            return DetectResult(
                available=True, level="native-experimental", notes=tuple(notes)
            )
        if any_session_dir:
            return DetectResult(
                available=True, level="watcher-only", notes=tuple(notes)
            )
        return DetectResult(
            available=False, level="unavailable", notes=tuple(notes)
        )

    # ------------------------------------------------------------------
    # Install / Uninstall
    # ------------------------------------------------------------------

    def install(self, *, consent: bool) -> InstallResult:
        # Spec §S1.10.1: adapters must not modify the filesystem without consent.
        if not consent:
            return InstallResult(level_installed="unavailable", files_modified=())

        probe = self.detect()
        if probe.level == "unavailable":
            return InstallResult(level_installed="unavailable", files_modified=())

        marker = _marker_path(self._home_dir)
        marker.parent.mkdir(parents=True, exist_ok=True)
        # Marker payload is deterministic and includes the detected level
        # plus the pinned session-format version so doctor can read it.
        payload = (
            f"level={probe.level}\n"
            f"pinned_version={PINNED_CODEX_APP_VERSION}\n"
        )
        marker.write_text(payload, encoding="utf-8")
        return InstallResult(
            level_installed=probe.level,
            files_modified=(marker,),
        )

    def uninstall(self) -> None:
        # Idempotent: unlink with missing_ok so consecutive calls are no-ops.
        _marker_path(self._home_dir).unlink(missing_ok=True)


__all__ = [
    "CodexAppAdapter",
    "DetectResult",
    "InstallResult",
    "PINNED_CODEX_APP_VERSION",
    "detect_session_format_version",
    "iter_sessions",
]
