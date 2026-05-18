"""AgentLens CLI entrypoint (spec §10.1).

This Typer app registers the v0 subcommands implemented under
``agentlens.commands``. Additional verbs (latest, status, failures, risks,
run, install, doctor) are added by later tasks.
"""
from __future__ import annotations

import typer

from .commands import attach as attach_cmd
from .commands import eval as eval_cmd
from .commands import final as final_cmd
from .commands import mark as mark_cmd
from .commands import seal as seal_cmd
from .commands import show as show_cmd
from .commands import start as start_cmd

app = typer.Typer(
    name="agentlens",
    no_args_is_help=True,
    add_completion=False,
    help="AgentLens v0 — agent-agnostic recording/evaluation contract.",
)

app.command(name="start")(start_cmd.start)
app.command(name="mark")(mark_cmd.mark)
app.command(name="attach")(attach_cmd.attach)
app.command(name="final")(final_cmd.final)
app.command(name="seal")(seal_cmd.seal)
app.command(name="eval")(eval_cmd.eval_cmd)
app.command(name="show")(show_cmd.show)


def main() -> None:
    """Console-script entrypoint."""
    app()


if __name__ == "__main__":
    main()


__all__ = ["app", "main"]
