"""``agentlens install`` — install a shim for an agent binary (spec §S1.6.18, §S1.9.3).

Places ``~/.agentlens/shims/<agent>`` and a sibling ``<agent>.real`` lockfile.
This command never edits the user's shell rc; instead it prints a PATH export
hint, and requires explicit consent (or ``--yes``) before writing files.

When invoked as ``agentlens install claude --cmux`` (spec §4.6), the command
takes the cmux-chain path: it backs up the cmux-bundled ``claude`` wrapper
and installs the AgentLens shim at the cmux path, chaining
``shim → cmux wrapper → real claude``. The ``--cmux`` flag is the deliberate
exception to ``install_shim``'s ``.app``-bundle refusal (Task 6).
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Optional

import typer

from ..adapters.shims import install_cmux_chain, install_shim

DEFAULT_CMUX_APP = Path("/Applications/cmux.app")


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
    cmux: bool = typer.Option(
        False,
        "--cmux",
        help=(
            "Install the cmux chain: back up the cmux-bundled claude wrapper "
            "and shim at the cmux path so the chain becomes "
            "shim → cmux wrapper → real claude. Only valid for `claude`. "
            "Requires `--yes` for non-interactive runs."
        ),
    ),
    cmux_app: Optional[Path] = typer.Option(
        None,
        "--cmux-app",
        help=(
            "Path to the cmux.app bundle (defaults to /Applications/cmux.app). "
            "Used for testing; in production the default is correct."
        ),
    ),
) -> None:
    """Install an AgentLens shim for ``agent``.

    Workflow (plain mode):

    1. Resolve the real binary (``--real`` or ``shutil.which``).
    2. Ask the user for consent (unless ``--yes``).
    3. Write the shim + lockfile.
    4. Print a PATH export hint — the user must update their shell rc manually.

    Workflow (cmux-chain mode, ``--cmux``):

    1. Locate ``<cmux_app>/Contents/Resources/bin/claude``.
    2. Require explicit consent (``--yes`` if non-TTY).
    3. Back up the cmux wrapper → ``claude.cmux-original`` (preserved mode).
    4. Install the cmux-chain shim at the cmux ``claude`` path.
    5. Record install metadata in ``~/.agentlens/cmux-install.json``.
    """
    if cmux:
        if agent != "claude":
            raise typer.BadParameter(
                f"--cmux is only valid for agent 'claude' (got {agent!r})"
            )
        _install_cmux_chain_command(cmux_app=cmux_app, yes=yes)
        return

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


def _install_cmux_chain_command(
    *, cmux_app: Optional[Path], yes: bool
) -> None:
    """Implement ``agentlens install claude --cmux``.

    Refuses non-interactive runs without ``--yes`` (we won't silently modify
    an .app bundle). For interactive TTY runs, an explicit confirmation
    prompt is shown describing exactly what will be modified.
    """
    app_path = Path(cmux_app) if cmux_app is not None else DEFAULT_CMUX_APP
    binary = app_path / "Contents" / "Resources" / "bin" / "claude"

    if not binary.is_file():
        # Distinguish missing-app from missing-binary in messages.
        if not app_path.exists():
            raise typer.BadParameter(
                f"cmux app not found at {app_path}; pass --cmux-app <path> "
                f"or install cmux from https://cmux.io"
            )
        raise typer.BadParameter(
            f"cmux claude wrapper missing at {binary}; the cmux.app layout "
            f"may have changed — file an issue with the AgentLens project"
        )

    # Require explicit consent. For non-TTY (e.g. CI) we *only* accept --yes;
    # silently modifying /Applications/cmux.app is never acceptable.
    if not yes:
        is_tty = sys.stdin.isatty()
        if not is_tty:
            typer.echo(
                "agentlens: explicit consent required to modify "
                f"{app_path}; re-run with `--yes` for non-interactive use.",
                err=True,
            )
            raise typer.Exit(code=2)
        confirmed = typer.confirm(
            f"This will modify {binary} (back it up to "
            f"claude.cmux-original and install an AgentLens shim). "
            f"Proceed?",
            default=False,
        )
        if not confirmed:
            typer.echo("aborted — no files written")
            return

    meta = install_cmux_chain(app_path)
    typer.echo(f"installed cmux chain shim at {meta['cmux_binary_path']}")
    typer.echo(f"  backup: {meta['cmux_backup_path']}")
    typer.echo(f"  cmux.app version: {meta['cmux_app_version'] or 'unknown'}")
    typer.echo("")
    typer.echo("Run `agentlens doctor` to verify the chain.")


__all__ = ["install"]
