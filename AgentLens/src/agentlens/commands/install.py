"""``agentlens install`` — install a shim for an agent binary (spec §S1.6.18, §S1.9.3).

Places ``~/.agentlens/shims/<agent>`` and a sibling ``<agent>.real`` lockfile.
This command never edits the user's shell rc; instead it prints a PATH export
hint, and requires explicit consent (or ``--yes``) before writing files.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional

import typer

from ..adapters.shims import install_shim


def install(
    agent: str = typer.Argument(..., help="Agent name (e.g. claude or codex)."),
    real_path: Optional[Path] = typer.Option(
        None,
        "--real",
        help="Real binary path; auto-detected via `shutil.which(agent)` if omitted.",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        help="Skip the consent prompt (CI/automation only).",
    ),
) -> None:
    """Install an AgentLens shim for ``agent``.

    Workflow:

    1. Resolve the real binary (``--real`` or ``shutil.which``).
    2. Ask the user for consent (unless ``--yes``).
    3. Write the shim + lockfile.
    4. Print a PATH export hint — the user must update their shell rc manually.
    """
    if real_path is None:
        detected = shutil.which(agent)
        if not detected:
            raise typer.BadParameter(
                f"no real binary found in PATH for {agent!r}; pass --real <path>"
            )
        real_path = Path(detected)

    if not yes:
        confirmed = typer.confirm(
            f"Install shim for {agent}? This places a shim in "
            f"~/.agentlens/shims/. You will need to add this dir to PATH manually.",
            default=False,
        )
        if not confirmed:
            typer.echo("aborted — no files written")
            return

    install_shim(agent, real_path)
    typer.echo(f"installed shim for {agent} -> {real_path}")
    typer.echo("")
    typer.echo("Add to your shell rc:")
    typer.echo('  export PATH="$HOME/.agentlens/shims:$PATH"')


__all__ = ["install"]
