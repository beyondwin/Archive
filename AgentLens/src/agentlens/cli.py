"""AgentLens CLI entrypoint (spec §10.1).

This Typer app registers the v0 subcommands implemented under
``agentlens.commands``. Additional verbs (latest, status, failures, risks,
run, install, doctor) are added by later tasks.
"""
from __future__ import annotations

import typer

from .commands import attach as attach_cmd
from .commands import doctor as doctor_cmd
from .commands import eval as eval_cmd
from .commands import failures as failures_cmd
from .commands import final as final_cmd
from .commands import gc as gc_cmd
from .commands import install as install_cmd
from .commands import latest as latest_cmd
from .commands import mark as mark_cmd
from .commands import mode as mode_cmd
from .commands import risks as risks_cmd
from .commands import run as run_cmd
from .commands import seal as seal_cmd
from .commands import serve as serve_cmd
from .commands import show as show_cmd
from .commands import start as start_cmd
from .commands import status as status_cmd
from .commands import uninstall as uninstall_cmd

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
app.command(name="serve")(serve_cmd.serve)
app.command(name="show")(show_cmd.show)
app.command(name="latest")(latest_cmd.latest)
app.command(name="status")(status_cmd.status)
app.command(name="failures")(failures_cmd.failures)
app.command(name="risks")(risks_cmd.risks)
app.command(
    name="run",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)(run_cmd.run)
app.command(name="install")(install_cmd.install)
app.command(name="uninstall")(uninstall_cmd.uninstall)
app.command(name="doctor")(doctor_cmd.doctor)
app.command(name="gc")(gc_cmd.gc)
app.add_typer(mode_cmd.app, name="mode")


def main() -> None:
    """Console-script entrypoint."""
    app()


if __name__ == "__main__":
    main()


__all__ = ["app", "main"]
