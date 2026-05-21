"""``agentlens latest`` — newest run summary (spec §S1.11.1, §10.1).

Reads only via :mod:`agentlens.store.query` (task constraint).
Default text output is a single line: run_id + workspace_short + outcome
+ eval_status + sealed_phase. ``--format json`` emits the canonical row
dict (or ``null`` when no runs exist). No absolute paths.
"""
from __future__ import annotations

import json

import typer

from agentlens.store import query
from agentlens.store.paths import agentlens_home

from ._format import project_run_row
from ._query_format import render_one_line


def latest(
    format: str = typer.Option(
        "text", "--format", help="output format: 'text' (default) or 'json'"
    ),
) -> None:
    """Print the most-recent run as a one-liner (or JSON)."""
    if format not in {"text", "json"}:
        raise typer.BadParameter(
            f"unknown --format {format!r}; expected 'text' or 'json'"
        )
    row = query.latest(agentlens_home())
    if format == "json":
        projected = project_run_row(row) if row is not None else None
        typer.echo(json.dumps(projected, sort_keys=True))
        return
    if row is None:
        typer.echo("(no runs)")
        return
    typer.echo(render_one_line(row))


__all__ = ["latest"]
