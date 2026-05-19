"""Shim install/integrity helpers (spec §S1.6.18, §S1.9.3, §S1.7.4).

The shim is a small bash script placed under ``~/.agentlens/shims/<name>``.
It reads a sibling lockfile ``<name>.real`` containing the real binary's
absolute path and sha256, verifies integrity, and delegates execution to
``agentlens run --agent <name> --mode auto -- <real_binary> "$@"``.

On sha256 drift, the shim falls back to direct passthrough (no recording).
On lockfile-missing, the shim attempts to find a non-shim binary and
exec's it directly; if none is found, exit 127.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import stat
import sys
from pathlib import Path
from typing import Literal

SHIM_TEMPLATE = r"""#!/usr/bin/env bash
# AgentLens shim for {name} — managed file, do not edit.
# agentlens CLI baked at install time (preferred over PATH lookup).
INSTALLED_AGENTLENS_BIN="{agentlens_bin}"
set -euo pipefail
REAL_LOCKFILE="$HOME/.agentlens/shims/{name}.real"
if [ ! -f "$REAL_LOCKFILE" ]; then
  echo "agentlens: real binary lockfile missing — passthrough" >&2
  mapfile -t CANDIDATES < <(type -P -a {name} 2>/dev/null | grep -F -v "$HOME/.agentlens/shims/" || true)
  if [ "${{#CANDIDATES[@]}}" -eq 0 ]; then
    echo "agentlens: no real {name} binary found" >&2
    exit 127
  fi
  exec "${{CANDIDATES[0]}}" "$@"
fi
REAL_PATH="$(awk -F= '$1=="path"{{print $2}}' "$REAL_LOCKFILE")"
REAL_SHA="$(awk -F= '$1=="sha256"{{print $2}}' "$REAL_LOCKFILE")"
CUR_SHA="$(shasum -a 256 "$REAL_PATH" | awk '{{print $1}}')"
if [ "$REAL_SHA" != "$CUR_SHA" ]; then
  echo "agentlens: real binary sha256 drift — passthrough only" >&2
  exec "$REAL_PATH" "$@"
fi
# v1 §4.5 TTY-aware passthrough.
# When invoked interactively (stdin is a TTY) and the requested mode is the
# agent's TUI, we cannot safely wrap with subprocess.Popen+PIPE. Pass
# through to the real binary; the rollout/JSONL importer captures the
# transcript post-hoc.
if [ -t 0 ]; then
  case "{name}" in
    claude)
      case "${{1:-}}" in
        -p|--print|--output-format) ;;  # non-TTY print mode → wrap
        *) exec "$REAL_PATH" "$@" ;;     # interactive TUI → passthrough
      esac
      ;;
    codex)
      case "${{1:-}}" in
        exec|e) ;;  # non-interactive by design → wrap
        *) exec "$REAL_PATH" "$@" ;;     # bare/resume/fork/review/apply/login/mcp/app → passthrough
      esac
      ;;
  esac
fi
# Nested invocation handling
if [ -n "${{AGENTLENS_RUN_ID:-}}" ]; then
  policy="${{AGENTLENS_NESTED_POLICY:-passthrough}}"
  if [ "$policy" = "passthrough" ]; then exec "$REAL_PATH" "$@"; fi
  # else fall through to recording with parent_run_id
fi
# Admin/auth subcommands pass-through (per integration adapter rules)
case "${{1:-}}" in
  auth|login|update|plugin|mcp) exec "$REAL_PATH" "$@" ;;
esac
# Locate the agentlens CLI. Prefer the install-time baked path so a shim
# created from a venv works even when the venv isn't activated; fall back
# to PATH lookup; finally passthrough so the §S1.6.17 non-blocking
# invariant (AgentLens-internal lookup failures never alter child exit
# code) is preserved.
if [ -n "$INSTALLED_AGENTLENS_BIN" ] && [ -x "$INSTALLED_AGENTLENS_BIN" ]; then
  exec "$INSTALLED_AGENTLENS_BIN" run --agent {agent_name} -- "$REAL_PATH" "$@"
fi
if AGENTLENS_BIN="$(command -v agentlens 2>/dev/null)" && [ -x "$AGENTLENS_BIN" ]; then
  exec "$AGENTLENS_BIN" run --agent {agent_name} -- "$REAL_PATH" "$@"
fi
echo "agentlens: CLI not on PATH and install-time path missing — passthrough (no recording)" >&2
exec "$REAL_PATH" "$@"
"""


def _shim_dir() -> Path:
    return Path.home() / ".agentlens" / "shims"


def _ensure_shim_dir() -> Path:
    """Create ``~/.agentlens/shims`` with 0700 perms and verify ownership.

    Raises ``PermissionError`` if the directory exists but is not owned by
    the current uid.
    """
    shim_dir = _shim_dir()
    shim_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    # mkdir mode is filtered through umask; re-apply explicitly.
    os.chmod(shim_dir, 0o700)
    st = shim_dir.stat()
    cur_uid = os.getuid()
    if st.st_uid != cur_uid:
        raise PermissionError(
            f"shim_dir owner mismatch: {st.st_uid} != {cur_uid}"
        )
    return shim_dir


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# Binary name → canonical agent name (must match `run.py:_AGENT_NAMES`).
# Users install with the binary they type (`claude`, `codex`), but the
# `agentlens run --agent` flag only accepts the canonical adapter names.
_BIN_TO_AGENT_NAME = {
    "claude": "claude_code",
    "codex": "codex_cli",
}


def _resolve_agentlens_cli() -> str:
    """Best-effort absolute path to the currently-installed ``agentlens`` CLI.

    Tried in order:
    1. ``sys.argv[0]`` if it resolves to an executable file named ``agentlens``
       (catches venv installs invoked as ``./.venv/bin/agentlens install ...``).
    2. ``shutil.which("agentlens")`` (catches system / pipx installs on PATH).
    3. Empty string — the shim then falls back to runtime PATH lookup, and
       finally to passthrough, per the §S1.6.17 non-blocking invariant.
    """
    argv0 = Path(sys.argv[0]) if sys.argv and sys.argv[0] else None
    if argv0 is not None:
        try:
            resolved = argv0.resolve(strict=True)
        except (OSError, RuntimeError):
            resolved = None
        if (
            resolved is not None
            and resolved.name == "agentlens"
            and os.access(resolved, os.X_OK)
        ):
            return str(resolved)
    on_path = shutil.which("agentlens")
    if on_path:
        return str(Path(on_path).resolve())
    return ""


def install_shim(name: str, real_path: Path) -> None:
    """Install a shim for ``name`` pointing at ``real_path``.

    Algorithm (spec §S1.6.18):

    1. Create ``~/.agentlens/shims`` (0700, owner-verified).
    2. Resolve ``real_path`` to an absolute, existing path.
    3. Compute real binary sha256.
    4. Write ``<name>.real`` lockfile (path=..., sha256=...).
    5. Write ``<name>`` shim script (0755) from ``SHIM_TEMPLATE``.
    """
    shim_dir = _ensure_shim_dir()
    real = Path(real_path).resolve(strict=True)
    # v1 regression guard: refuse to operate on a binary inside a macOS
    # .app bundle (e.g. Codex Desktop's bundled `codex`). Replacing such a
    # binary would break the code-signed bundle, and Desktop transcript
    # capture is import-only via the rollout JSONL importer. Callers
    # wanting a Desktop install must take an explicit, separate path.
    if any(part.endswith(".app") for part in real.parts):
        raise ValueError(
            f"refusing to shim binary inside .app bundle: {real} "
            "(Desktop transcripts are captured via the rollout importer)"
        )
    digest = _sha256_file(real)

    lockfile = shim_dir / f"{name}.real"
    lockfile.write_text(
        f"path={real}\nsha256={digest}\n",
        encoding="utf-8",
    )

    shim = shim_dir / name
    agent_name = _BIN_TO_AGENT_NAME.get(name, "generic")
    agentlens_bin = _resolve_agentlens_cli()
    shim.write_text(
        SHIM_TEMPLATE.format(
            name=name, agent_name=agent_name, agentlens_bin=agentlens_bin
        ),
        encoding="utf-8",
    )
    os.chmod(shim, 0o755)


# ---------------------------------------------------------------------------
# cmux chain shim — spec §4.6 cmux auto-detection at install.
#
# The cmux chain is the deliberate exception to ``install_shim``'s
# ``.app``-bundle refusal (Task 6). When the user explicitly opts in via
# ``agentlens install claude --cmux`` (or interactive consent), we:
#
#   1. Back up the cmux wrapper at ``<cmux.app>/.../bin/claude`` to a sibling
#      ``claude.cmux-original`` (preserving file mode).
#   2. Install an AgentLens shim at the cmux ``claude`` path that exec's
#      ``agentlens run --agent claude_code -- <backup> "$@"`` — so the
#      runtime chain is ``shim → cmux wrapper → real claude``.
#   3. Write a co-located ``claude.cmux-lockfile`` recording the backup
#      path + sha256; ``agentlens doctor`` reads this to detect drift.
#
# We intentionally use a separate template here (rather than reusing
# SHIM_TEMPLATE) because:
#   - The lockfile lives next to the binary, not under ~/.agentlens/shims/.
#   - The chain target is the BACKUP (cmux wrapper), not the underlying
#     Claude binary — so cmux's own session-id injection still happens.
#   - We must bypass install_shim's .app refusal — but only for this opt-in
#     path. install_shim itself keeps refusing .app bundles in the general
#     case.
# ---------------------------------------------------------------------------

CMUX_SHIM_TEMPLATE = r"""#!/usr/bin/env bash
# AgentLens shim for cmux-bundled claude — managed file, do not edit.
# Installed by `agentlens install claude --cmux`.
set -euo pipefail
INSTALLED_AGENTLENS_BIN="{agentlens_bin}"
REAL_PATH="{backup_path}"
if [ ! -x "$REAL_PATH" ]; then
  echo "agentlens: cmux backup missing at $REAL_PATH — re-run \`agentlens install claude --cmux\`" >&2
  exit 127
fi
# v1 §4.5 TTY-aware passthrough — for the cmux chain we always wrap because
# cmux only ships the non-interactive print/exec wrapper.
if [ -t 0 ]; then
  case "${{1:-}}" in
    -p|--print|--output-format) ;;  # non-TTY print mode → wrap
    *) exec "$REAL_PATH" "$@" ;;     # interactive TUI → passthrough to cmux wrapper
  esac
fi
# Nested-invocation handling.
if [ -n "${{AGENTLENS_RUN_ID:-}}" ]; then
  policy="${{AGENTLENS_NESTED_POLICY:-passthrough}}"
  if [ "$policy" = "passthrough" ]; then exec "$REAL_PATH" "$@"; fi
fi
# Admin/auth subcommands pass-through.
case "${{1:-}}" in
  auth|login|update|plugin|mcp) exec "$REAL_PATH" "$@" ;;
esac
if [ -n "$INSTALLED_AGENTLENS_BIN" ] && [ -x "$INSTALLED_AGENTLENS_BIN" ]; then
  exec "$INSTALLED_AGENTLENS_BIN" run --agent claude_code -- "$REAL_PATH" "$@"
fi
if AGENTLENS_BIN="$(command -v agentlens 2>/dev/null)" && [ -x "$AGENTLENS_BIN" ]; then
  exec "$AGENTLENS_BIN" run --agent claude_code -- "$REAL_PATH" "$@"
fi
echo "agentlens: CLI not on PATH and install-time path missing — passthrough (no recording)" >&2
exec "$REAL_PATH" "$@"
"""


def install_cmux_chain(cmux_app: Path) -> dict:
    """Install the AgentLens cmux chain shim at *cmux_app*.

    *cmux_app* is the path to a ``cmux.app`` directory; the cmux-bundled
    ``claude`` binary is expected at ``<cmux_app>/Contents/Resources/bin/claude``.

    Side effects:
      1. Backs up ``.../bin/claude`` → ``.../bin/claude.cmux-original``
         (preserving file mode). If the backup already exists, it is left
         in place and treated as the source of truth — this lets the user
         re-run the install command without re-shimming the shim.
      2. Writes the cmux-chain shim at ``.../bin/claude`` (0755).
      3. Writes a co-located lockfile ``.../bin/claude.cmux-lockfile``
         with ``path=...`` and ``sha256=...`` of the backup.
      4. Records metadata in ``~/.agentlens/cmux-install.json``.

    Returns the metadata dict that was written (also written to disk).

    Raises ``FileNotFoundError`` if the cmux ``claude`` binary is missing,
    or ``PermissionError`` if the install cannot proceed.
    """
    import json as _json
    from datetime import datetime, timezone

    cmux_app = Path(cmux_app)
    binary = cmux_app / "Contents" / "Resources" / "bin" / "claude"
    if not binary.is_file():
        raise FileNotFoundError(
            f"cmux claude binary not found at {binary}; is cmux.app installed?"
        )
    backup = binary.with_name("claude.cmux-original")

    # Step 1: back up — only if a backup does not already exist or it is no
    # longer the original cmux wrapper (i.e. someone already shimmed). To
    # decide, we treat the BACKUP as the source of truth if it exists.
    if not backup.exists():
        # Preserve mode by reading the current binary's stat first.
        original_mode = stat.S_IMODE(binary.stat().st_mode)
        backup.write_bytes(binary.read_bytes())
        os.chmod(backup, original_mode)
    backup_sha = _sha256_file(backup)
    backup_mtime = backup.stat().st_mtime

    # Step 2: write shim at the cmux path.
    agentlens_bin = _resolve_agentlens_cli()
    shim_text = CMUX_SHIM_TEMPLATE.format(
        agentlens_bin=agentlens_bin,
        backup_path=str(backup),
    )
    binary.write_text(shim_text, encoding="utf-8")
    os.chmod(binary, 0o755)

    # Step 3: lockfile co-located with the binary.
    lockfile = binary.with_name("claude.cmux-lockfile")
    lockfile.write_text(
        f"path={backup}\nsha256={backup_sha}\n",
        encoding="utf-8",
    )

    # Step 4: metadata.
    version = _read_cmux_app_version(cmux_app)
    meta = {
        "cmux_app_path": str(cmux_app),
        "cmux_binary_path": str(binary),
        "cmux_backup_path": str(backup),
        "cmux_backup_sha256": backup_sha,
        "cmux_app_version": version,
        "cmux_binary_mtime": backup_mtime,
        "installed_at": datetime.now(timezone.utc).isoformat(),
    }
    meta_path = Path.home() / ".agentlens" / "cmux-install.json"
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(_json.dumps(meta, sort_keys=True, indent=2), encoding="utf-8")
    return meta


def _read_cmux_app_version(cmux_app: Path) -> str | None:
    """Best-effort read of ``CFBundleShortVersionString`` from Info.plist.

    Uses a minimal XML scan to avoid a dependency on ``plistlib`` quirks
    across Python versions. Returns ``None`` if the file is missing or the
    key cannot be located.
    """
    info_plist = cmux_app / "Contents" / "Info.plist"
    if not info_plist.is_file():
        return None
    try:
        text = info_plist.read_text(encoding="utf-8")
    except OSError:
        return None
    # Locate <key>CFBundleShortVersionString</key> then the next <string>...</string>.
    key = "<key>CFBundleShortVersionString</key>"
    idx = text.find(key)
    if idx == -1:
        return None
    s_open = text.find("<string>", idx)
    s_close = text.find("</string>", s_open)
    if s_open == -1 or s_close == -1:
        return None
    return text[s_open + len("<string>") : s_close].strip()


def read_cmux_install_metadata() -> dict | None:
    """Return the recorded cmux install metadata, or ``None`` if missing."""
    import json as _json

    meta_path = Path.home() / ".agentlens" / "cmux-install.json"
    if not meta_path.is_file():
        return None
    try:
        return _json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def verify_cmux_chain() -> dict:
    """Inspect the cmux chain install for drift; used by ``agentlens doctor``.

    Returns a dict with shape::

        {
          "status": "ok" | "drift" | "missing_backup" | "missing_shim" |
                    "permission_error" | "version_drift" | "not_installed",
          "backup_present": bool,
          "backup_sha_match": bool,
          "shim_installed": bool,
          "cmux_app_version_recorded": str | None,
          "cmux_app_version_current": str | None,
          "cmux_binary_mtime_recorded": float | None,
          "cmux_binary_mtime_current": float | None,
          "message": str,
        }
    """
    meta = read_cmux_install_metadata()
    if meta is None:
        return {
            "status": "not_installed",
            "backup_present": False,
            "backup_sha_match": False,
            "shim_installed": False,
            "cmux_app_version_recorded": None,
            "cmux_app_version_current": None,
            "cmux_binary_mtime_recorded": None,
            "cmux_binary_mtime_current": None,
            "message": "no cmux chain install recorded",
        }
    backup_path = Path(meta["cmux_backup_path"])
    binary_path = Path(meta["cmux_binary_path"])
    cmux_app = Path(meta["cmux_app_path"])

    shim_installed = binary_path.is_file()
    backup_present = backup_path.is_file()

    if not backup_present:
        return {
            "status": "missing_backup",
            "backup_present": False,
            "backup_sha_match": False,
            "shim_installed": shim_installed,
            "cmux_app_version_recorded": meta.get("cmux_app_version"),
            "cmux_app_version_current": _read_cmux_app_version(cmux_app),
            "cmux_binary_mtime_recorded": meta.get("cmux_binary_mtime"),
            "cmux_binary_mtime_current": None,
            "message": (
                f"backup missing at {backup_path}; "
                f"re-run `agentlens install claude --cmux`"
            ),
        }

    try:
        backup_sha = _sha256_file(backup_path)
    except PermissionError as exc:
        return {
            "status": "permission_error",
            "backup_present": True,
            "backup_sha_match": False,
            "shim_installed": shim_installed,
            "cmux_app_version_recorded": meta.get("cmux_app_version"),
            "cmux_app_version_current": _read_cmux_app_version(cmux_app),
            "cmux_binary_mtime_recorded": meta.get("cmux_binary_mtime"),
            "cmux_binary_mtime_current": None,
            "message": f"cannot read backup ({exc}); check file permissions",
        }

    sha_match = backup_sha == meta.get("cmux_backup_sha256")
    cur_version = _read_cmux_app_version(cmux_app)
    rec_version = meta.get("cmux_app_version")
    cur_mtime = backup_path.stat().st_mtime
    rec_mtime = meta.get("cmux_binary_mtime")

    if not shim_installed:
        return {
            "status": "missing_shim",
            "backup_present": True,
            "backup_sha_match": sha_match,
            "shim_installed": False,
            "cmux_app_version_recorded": rec_version,
            "cmux_app_version_current": cur_version,
            "cmux_binary_mtime_recorded": rec_mtime,
            "cmux_binary_mtime_current": cur_mtime,
            "message": (
                f"shim missing at {binary_path}; "
                f"re-run `agentlens install claude --cmux`"
            ),
        }

    if not sha_match:
        return {
            "status": "drift",
            "backup_present": True,
            "backup_sha_match": False,
            "shim_installed": True,
            "cmux_app_version_recorded": rec_version,
            "cmux_app_version_current": cur_version,
            "cmux_binary_mtime_recorded": rec_mtime,
            "cmux_binary_mtime_current": cur_mtime,
            "message": (
                f"backup sha256 drift at {backup_path}; "
                f"re-run `agentlens install claude --cmux`"
            ),
        }

    if cur_version is not None and rec_version is not None and cur_version != rec_version:
        return {
            "status": "version_drift",
            "backup_present": True,
            "backup_sha_match": True,
            "shim_installed": True,
            "cmux_app_version_recorded": rec_version,
            "cmux_app_version_current": cur_version,
            "cmux_binary_mtime_recorded": rec_mtime,
            "cmux_binary_mtime_current": cur_mtime,
            "message": (
                f"cmux.app version changed from {rec_version} to {cur_version}; "
                f"re-run `agentlens install claude --cmux`"
            ),
        }

    return {
        "status": "ok",
        "backup_present": True,
        "backup_sha_match": True,
        "shim_installed": True,
        "cmux_app_version_recorded": rec_version,
        "cmux_app_version_current": cur_version,
        "cmux_binary_mtime_recorded": rec_mtime,
        "cmux_binary_mtime_current": cur_mtime,
        "message": "cmux chain install ok",
    }


def uninstall_shim(name: str) -> None:
    """Remove the shim script and lockfile for ``name``. Idempotent."""
    shim_dir = _shim_dir()
    (shim_dir / name).unlink(missing_ok=True)
    (shim_dir / f"{name}.real").unlink(missing_ok=True)


def _parse_lockfile(lockfile: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in lockfile.read_text(encoding="utf-8").splitlines():
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key] = value
    return out


def verify_shim_integrity(name: str) -> Literal["ok", "drift_warning", "missing"]:
    """Compare the lockfile's recorded sha256 to the real binary's current sha256.

    Returns:
        ``"ok"`` if the sha matches.
        ``"drift_warning"`` if the real binary's sha differs from the lockfile.
        ``"missing"`` if the lockfile or the real binary is missing.
    """
    lockfile = _shim_dir() / f"{name}.real"
    if not lockfile.is_file():
        return "missing"
    fields = _parse_lockfile(lockfile)
    real_path_str = fields.get("path")
    recorded_sha = fields.get("sha256")
    if not real_path_str or not recorded_sha:
        return "missing"
    real = Path(real_path_str)
    if not real.is_file():
        return "missing"
    current_sha = _sha256_file(real)
    return "ok" if current_sha == recorded_sha else "drift_warning"


__all__ = [
    "CMUX_SHIM_TEMPLATE",
    "SHIM_TEMPLATE",
    "install_cmux_chain",
    "install_shim",
    "read_cmux_install_metadata",
    "uninstall_shim",
    "verify_cmux_chain",
    "verify_shim_integrity",
]
