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
    "SHIM_TEMPLATE",
    "install_shim",
    "uninstall_shim",
    "verify_shim_integrity",
]
