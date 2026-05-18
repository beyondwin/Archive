"""``agentlens eval`` — run the v0 evaluator stub against the active run."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from agentlens.evaluator import evaluate

from ._run_resolve import resolve_run_dir


def eval_cmd(
    latest: bool = typer.Option(
        False, "--latest", help="evaluate the most-recent run for this workspace"
    ),
    run_id: Optional[str] = typer.Option(
        None, "--run-id", help="evaluate a specific run_id"
    ),
) -> None:
    """Evaluate a run and print its status."""
    if run_id is None and not latest:
        # Default to --latest if neither is supplied.
        latest = True
    if run_id is not None and latest:
        raise typer.BadParameter("--latest and --run-id are mutually exclusive")

    run_dir = resolve_run_dir(Path.cwd(), run_id)
    doc = evaluate(run_dir)
    typer.echo(doc["status"])


__all__ = ["eval_cmd"]
