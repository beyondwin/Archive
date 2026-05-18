"""``agentlens status`` — list runs including in-progress (spec §S1.11.1).

Identical row shape to ``latest`` but returns the full set so in-progress
runs (no ``final.json`` yet, ``eval_status='needs_eval'``) are visible.
"""
from __future__ import annotations

import json

import typer

from agentlens.store import query
from agentlens.store.paths import agentlens_home

from ._format import project_run_row
from ._query_format import render_one_line


def status(
    format: str = typer.Option(
        "text", "--format", help="output format: 'text' (default) or 'json'"
    ),
) -> None:
    """List all runs (including in-progress) as one line each."""
    if format not in {"text", "json"}:
        raise typer.BadParameter(
            f"unknown --format {format!r}; expected 'text' or 'json'"
        )
    rows = query.full_scan_runs(agentlens_home())
    # Deterministic ordering: newest first by started_at, falling back to
    # run_id for stability when timestamps tie or are missing.
    rows.sort(
        key=lambda r: (r.get("started_at") or "", r.get("run_id") or ""),
        reverse=True,
    )
    if format == "json":
        projected = [project_run_row(r) for r in rows]
        typer.echo(json.dumps(projected, sort_keys=True))
        return
    if not rows:
        typer.echo("(no runs)")
        return
    for row in rows:
        typer.echo(render_one_line(row))


__all__ = ["status"]
