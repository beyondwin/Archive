"""``agentlens run -- <cmd args...>`` — spawn a child under the AgentLens
process wrapper (spec §10.1, §5.16).

Task 13 wires the CLI surface to :func:`agentlens.adapters.process.wrap_command`
and exits with the child's exit code. Signal forwarding and the recording
pipeline are layered in by tasks 14/15/18.
"""
from __future__ import annotations

from typing import List

import typer

from agentlens.adapters.process import wrap_command
from agentlens.constants import DEFAULT_MODE

_AGENT_NAMES = {"claude_code", "codex_cli", "codex_app", "generic"}
_AGENT_MODES = {"cli", "app", "code", "unknown"}
_RECORDING_MODES = {"minimal", "full"}


def run(
    ctx: typer.Context,
    argv: List[str] = typer.Argument(
        ...,
        metavar="-- COMMAND [ARGS...]",
        help="Child command and its arguments (place after `--`).",
    ),
    agent: str = typer.Option(
        "generic",
        "--agent",
        help="agent identifier (claude_code|codex_cli|codex_app|generic)",
    ),
    agent_mode: str = typer.Option(
        "cli",
        "--agent-mode",
        help="agent runtime mode (cli|app|code|unknown)",
    ),
    mode: str = typer.Option(
        DEFAULT_MODE,
        "--mode",
        help="recording mode (minimal|full)",
    ),
) -> None:
    """Spawn the given command under the AgentLens wrapper.

    Usage::

        agentlens run -- pytest -x

    The wrapper drains stdout/stderr concurrently to avoid pipe-buffer
    deadlock and propagates the child's real exit code.
    """
    if agent not in _AGENT_NAMES:
        raise typer.BadParameter(
            f"invalid agent {agent!r}; expected one of {sorted(_AGENT_NAMES)}"
        )
    if agent_mode not in _AGENT_MODES:
        raise typer.BadParameter(
            f"invalid --agent-mode {agent_mode!r}; "
            f"expected one of {sorted(_AGENT_MODES)}"
        )
    if mode not in _RECORDING_MODES:
        raise typer.BadParameter(
            f"invalid --mode {mode!r}; expected one of {sorted(_RECORDING_MODES)}"
        )
    if not argv:
        raise typer.BadParameter("no child command given (place command after `--`)")

    result = wrap_command(
        list(argv),
        agent_name=agent,
        agent_mode=agent_mode,
        mode=mode,  # type: ignore[arg-type]
    )
    raise typer.Exit(code=result.exit_code)


__all__ = ["run"]
