"""Filesystem layout helpers (spec §S1.6.4, §5.4).

Two pointer locations coexist:

* The **durable** home under ``$AGENTLENS_HOME`` (default ``~/.agentlens``)
  holds the recorded run trees and the workspace-scoped ``current-runs``
  marker directory keyed by ``workspace_id``.
* The **workspace-local** pointer under ``<workspace_root>/.agentlens``
  stores workspace config and a workspace-scoped ``current-runs`` marker
  keyed by ``workspace_root``. This lives alongside the source tree and is
  what tooling consults to discover an active run from inside a workspace.
"""
from __future__ import annotations

import os
from hashlib import sha256
from pathlib import Path


def agentlens_home() -> Path:
    """Return ``$AGENTLENS_HOME`` (if set) or ``~/.agentlens``.

    The directory is **not** created here; callers materialise it on demand.
    """
    env = os.environ.get("AGENTLENS_HOME")
    if env:
        return Path(env)
    return Path.home() / ".agentlens"


def runs_root() -> Path:
    """Return ``<agentlens_home>/runs``."""
    return agentlens_home() / "runs"


def workspace_dir(workspace_id: str) -> Path:
    """Return ``<runs_root>/<workspace_id>`` (durable per-workspace runs dir)."""
    return runs_root() / workspace_id


def run_dir(workspace_id: str, run_id: str) -> Path:
    """Return ``<runs_root>/<workspace_id>/<run_id>``."""
    return runs_root() / workspace_id / run_id


def current_runs_dir(workspace_id: str) -> Path:
    """Return the durable, workspace-scoped ``current-runs`` directory.

    Multiple concurrent runs may coexist as sibling marker entries.
    """
    return workspace_dir(workspace_id) / "current-runs"


def workspace_local(root: Path) -> Path:
    """Return ``<root>/.agentlens`` (workspace-local pointer dir)."""
    return Path(root) / ".agentlens"


def current_run_marker(root: Path, run_id: str) -> Path:
    """Return ``<root>/.agentlens/current-runs/<run_id>``.

    The marker is itself a directory so multiple concurrent runs may register
    against the same workspace.
    """
    return workspace_local(root) / "current-runs" / run_id


def safe_label_path(absolute_path: Path, workspace_root: Path) -> str:
    """Return a workspace-relative label for *absolute_path*.

    If *absolute_path* lies outside *workspace_root* (after resolving both),
    return ``EXTERNAL:<sha256-hex>`` to avoid leaking absolute filesystem
    structure while still providing a stable identifier.
    """
    abs_p = Path(absolute_path).resolve()
    ws = Path(workspace_root).resolve()
    try:
        rel = abs_p.relative_to(ws)
    except ValueError:
        digest = sha256(str(abs_p).encode("utf-8")).hexdigest()
        return f"EXTERNAL:{digest}"
    return rel.as_posix()


__all__ = [
    "agentlens_home",
    "current_run_marker",
    "current_runs_dir",
    "run_dir",
    "runs_root",
    "safe_label_path",
    "workspace_dir",
    "workspace_local",
]
