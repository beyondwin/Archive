"""``agentlens doctor`` — inspect integrations and paths (spec §S1.6.18, §S1.8.4).

The command reports two scoped views:

* ``integrations`` — for each known agent runtime, the v0 integration level
  (``none`` or ``shim``; spec leaves ``watcher-only|full|native-experimental``
  reserved) and the shim-lockfile integrity (``ok`` / ``drift_warning``).
* ``paths`` — resolved ``AGENTLENS_HOME``, workspace id (with id basis), and
  the shim directory.

The default scope is ``all`` (both sections). Output is either human-readable
text or deterministic JSON (``--format json``).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import typer

from ..adapters.shims import verify_shim_integrity
from ..ids import compute_workspace_id
from ..store.paths import agentlens_home

# v0 agents tracked by `doctor integrations`. Spec §S1.6.18 enumerates the
# integration-level allow-list; for v0 only `none` and `shim` are realised.
_KNOWN_AGENTS: tuple[str, ...] = ("claude", "codex")


def _shim_dir() -> Path:
    return Path.home() / ".agentlens" / "shims"


def _integrations_block() -> dict:
    out: dict = {}
    for name in _KNOWN_AGENTS:
        integrity = verify_shim_integrity(name)
        if integrity == "missing":
            out[name] = {"integration_level": "none"}
        else:
            out[name] = {
                "integration_level": "shim",
                "shim_integrity": integrity,
            }
    return out


def _paths_block() -> dict:
    home = agentlens_home()
    workspace_id, basis, _metadata = compute_workspace_id(Path.cwd())
    shim_dir = _shim_dir()
    return {
        "AGENTLENS_HOME": {
            "path": str(home),
            "exists": home.exists(),
        },
        "workspace_id": {
            "id": workspace_id,
            "id_basis": basis,
        },
        "shim_dir": {
            "path": str(shim_dir),
            "exists": shim_dir.exists(),
        },
    }


def _format_text_integrations(integrations: dict) -> str:
    lines = ["Integrations:"]
    for name in sorted(integrations):
        info = integrations[name]
        level = info.get("integration_level", "none")
        if "shim_integrity" in info:
            lines.append(
                f"  {name}: integration_level={level} "
                f"shim_integrity={info['shim_integrity']}"
            )
        else:
            lines.append(f"  {name}: integration_level={level}")
    return "\n".join(lines)


def _format_text_paths(paths: dict) -> str:
    home = paths["AGENTLENS_HOME"]
    ws = paths["workspace_id"]
    shim = paths["shim_dir"]
    return "\n".join(
        [
            "Paths:",
            f"  AGENTLENS_HOME: {home['path']} "
            f"({'exists' if home['exists'] else 'missing'})",
            f"  workspace_id: {ws['id']} ({ws['id_basis']} basis)",
            f"  shim_dir: {shim['path']} "
            f"({'exists' if shim['exists'] else 'missing'})",
        ]
    )


def doctor(
    scope: str = typer.Argument(
        "all", help="What to inspect: integrations | paths | all."
    ),
    fmt: str = typer.Option(
        "text", "--format", help="Output format: text | json."
    ),
) -> None:
    """Inspect AgentLens integrations and paths."""
    if scope not in {"integrations", "paths", "all"}:
        raise typer.BadParameter(
            f"invalid scope {scope!r}; expected integrations | paths | all"
        )
    if fmt not in {"text", "json"}:
        raise typer.BadParameter(
            f"invalid --format {fmt!r}; expected text | json"
        )

    doc: dict = {}
    if scope in {"integrations", "all"}:
        doc["integrations"] = _integrations_block()
    if scope in {"paths", "all"}:
        doc["paths"] = _paths_block()

    if fmt == "json":
        typer.echo(json.dumps(doc, sort_keys=True))
        return

    parts: list[str] = []
    if "integrations" in doc:
        parts.append(_format_text_integrations(doc["integrations"]))
    if "paths" in doc:
        parts.append(_format_text_paths(doc["paths"]))
    typer.echo("\n".join(parts))


__all__ = ["doctor"]
