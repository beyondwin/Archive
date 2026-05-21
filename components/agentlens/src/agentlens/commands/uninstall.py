"""``agentlens uninstall`` — remove a previously-installed shim (spec §S1.6.18)."""
from __future__ import annotations

import typer

from ..adapters.shims import uninstall_shim


def uninstall(
    agent: str = typer.Argument(..., help="Agent name (e.g. claude or codex)."),
) -> None:
    """Remove ``~/.agentlens/shims/<agent>`` and the matching ``.real`` lockfile."""
    uninstall_shim(agent)
    typer.echo(f"removed shim for {agent}")


__all__ = ["uninstall"]
