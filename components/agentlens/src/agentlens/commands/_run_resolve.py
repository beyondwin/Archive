"""Helpers for resolving the active run from a workspace marker.

The workspace-local marker dir (``<workspace>/.agentlens/current-runs``)
holds one subdirectory per concurrent run. Each subdir's name is the
``run_id`` and contains a ``run_dir`` text file with the absolute path of
the durable run tree under ``$AGENTLENS_HOME``.
"""
from __future__ import annotations

from pathlib import Path

import typer

from agentlens.ids import compute_workspace_id
from agentlens.store.paths import run_dir as build_run_dir, workspace_local


def _markers(workspace_root: Path) -> list[Path]:
    marker_dir = workspace_local(workspace_root) / "current-runs"
    if not marker_dir.is_dir():
        return []
    return [p for p in marker_dir.iterdir() if p.is_dir()]


def latest_marker(workspace_root: Path) -> Path:
    """Return the most-recently-modified current-run marker directory.

    Raises ``typer.BadParameter`` if no run is registered.
    """
    markers = _markers(workspace_root)
    if not markers:
        raise typer.BadParameter(
            "no current run; call `agentlens start` first",
        )
    markers.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return markers[0]


def latest_run_dir(workspace_root: Path) -> Path:
    """Return the absolute run-tree path for the latest current-run marker."""
    marker = latest_marker(workspace_root)
    pointer = marker / "run_dir"
    if pointer.is_file():
        return Path(pointer.read_text(encoding="utf-8").strip())
    # Fallback: derive from marker name + recomputed workspace_id.
    run_id = marker.name
    workspace_id, _, _ = compute_workspace_id(workspace_root)
    return build_run_dir(workspace_id, run_id)


def resolve_run_dir(workspace_root: Path, run_id: str | None) -> Path:
    """Resolve a specific run_id (looking up the marker) or fall back to latest."""
    if run_id is None:
        return latest_run_dir(workspace_root)
    marker = workspace_local(workspace_root) / "current-runs" / run_id
    pointer = marker / "run_dir"
    if pointer.is_file():
        return Path(pointer.read_text(encoding="utf-8").strip())
    workspace_id, _, _ = compute_workspace_id(workspace_root)
    return build_run_dir(workspace_id, run_id)


__all__ = ["latest_marker", "latest_run_dir", "resolve_run_dir"]
