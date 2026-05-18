"""``agentlens failures`` — list evaluator failures (spec §S1.11.1, §S1.11.2).

Returns sealed-run evaluator failures from the last ``--since-days`` window
(default 30). Reads only via :mod:`agentlens.store.query`. No absolute paths.
"""
from __future__ import annotations

import json

import typer

from agentlens.store import query
from agentlens.store.paths import agentlens_home

from ._format import project_failure
from ._query_format import workspace_short


def failures(
    since_days: int = typer.Option(
        30, "--since-days", help="only include runs whose started_at is within N days"
    ),
    format: str = typer.Option(
        "text", "--format", help="output format: 'text' (default) or 'json'"
    ),
) -> None:
    """Print evaluator failures (one per line, or JSON list)."""
    if format not in {"text", "json"}:
        raise typer.BadParameter(
            f"unknown --format {format!r}; expected 'text' or 'json'"
        )
    items = query.failures(agentlens_home(), since_days=since_days)
    if format == "json":
        projected = [project_failure(f) for f in items]
        typer.echo(json.dumps(projected, sort_keys=True))
        return
    if not items:
        typer.echo("(no failures)")
        return
    for f in items:
        run_id = f.get("run_id") or "-"
        wid = workspace_short(f.get("workspace_id"))
        category = f.get("category") or "-"
        severity = f.get("severity") or "-"
        summary = f.get("summary") or ""
        typer.echo(f"{run_id}  {wid}  {category}  {severity}  {summary}")


__all__ = ["failures"]
