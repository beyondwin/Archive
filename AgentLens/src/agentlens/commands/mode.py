"""``agentlens mode`` — inspect and update the runtime mode (spec §S1.4).

Provides two sub-commands:

* ``agentlens mode show`` — print the resolved ``mode`` (one of
  ``disabled``, ``minimal``, ``full``) according to the config priority
  chain. The output is a single token on its own line so callers can
  pipe it through ``grep -q``.
* ``agentlens mode set <value>`` — persist ``value`` to the workspace
  config file (``<cwd>/.agentlens/config.yaml``). Idempotent.
"""
from __future__ import annotations

from pathlib import Path

import typer

from ..config import VALID_MODES, ConfigError, load_config, write_workspace_mode

app = typer.Typer(
    name="mode",
    help="Inspect or update the AgentLens runtime mode.",
    no_args_is_help=True,
    add_completion=False,
)


@app.command("show")
def show() -> None:
    """Print the currently-resolved mode (one token, one line)."""
    cfg = load_config(workspace_root=Path.cwd())
    typer.echo(cfg["mode"])


@app.command("set")
def set_(
    value: str = typer.Argument(
        ..., help="New mode: 'disabled', 'minimal', or 'full'."
    ),
) -> None:
    """Persist ``value`` to ``<cwd>/.agentlens/config.yaml``."""
    if value not in VALID_MODES:
        raise typer.BadParameter(
            f"unknown mode {value!r}; expected one of {sorted(VALID_MODES)}"
        )
    try:
        path = write_workspace_mode(Path.cwd(), value)
    except ConfigError as exc:  # defensive — VALID_MODES already checked.
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(f"mode={value} written to {path}")


__all__ = ["app"]
