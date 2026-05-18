"""``agentlens risks`` — aggregate residual risks (spec §S1.11.1, §5.8a).

Merges ``final.residual_risks``, ``eval.failures``, and synthetic
``RECORDING_INCOMPLETE`` markers from ``manifest.sealed_phase`` via the
read facade. No absolute paths in default text output.
"""
from __future__ import annotations

import json

import typer

from agentlens.store import query
from agentlens.store.paths import agentlens_home

from ._format import project_risk
from ._query_format import workspace_short


def risks(
    since_days: int = typer.Option(
        30, "--since-days", help="only include runs whose started_at is within N days"
    ),
    format: str = typer.Option(
        "text", "--format", help="output format: 'text' (default) or 'json'"
    ),
) -> None:
    """Print residual-risk indicators (one per line, or JSON list)."""
    if format not in {"text", "json"}:
        raise typer.BadParameter(
            f"unknown --format {format!r}; expected 'text' or 'json'"
        )
    items = query.risks(agentlens_home(), since_days=since_days)
    if format == "json":
        projected = [project_risk(r) for r in items]
        typer.echo(json.dumps(projected, sort_keys=True))
        return
    if not items:
        typer.echo("(no risks)")
        return
    for r in items:
        run_id = r.get("run_id") or "-"
        wid = workspace_short(r.get("workspace_id"))
        category = r.get("category") or "-"
        source = r.get("source") or "-"
        summary = r.get("summary") or ""
        typer.echo(f"{run_id}  {wid}  {category}  {source}  {summary}")


__all__ = ["risks"]
