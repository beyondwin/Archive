"""``agentlens show`` — full summary of a recorded run (spec §S1.11.1).

Resolves a run via :mod:`agentlens.store.query` (the read facade) and
prints the legacy six fields (run_id, agent, started_at, agent_outcome,
eval_status, sealed_phase) plus task_11 additions (workspace_short,
failures, risks). No absolute paths in default text output.
"""
from __future__ import annotations

import json
from typing import Any, Optional

import typer

from agentlens.store import query
from agentlens.store.paths import agentlens_home

from ._format import project_show
from ._query_format import workspace_short


def _resolve_row(run_id: Optional[str], use_latest: bool) -> dict[str, Any] | None:
    home = agentlens_home()
    if use_latest:
        return query.latest(home)
    assert run_id is not None  # validated by caller
    return query.get_run(home, run_id)


def _failures_for_run(run_id: str) -> list[dict[str, Any]]:
    home = agentlens_home()
    # The query facade applies a 30-day window by default; here we want all
    # failures for a single run so we pass a very large window.
    all_failures = query.failures(home, since_days=36500)
    return [f for f in all_failures if f.get("run_id") == run_id]


def _risks_for_run(run_id: str) -> list[dict[str, Any]]:
    home = agentlens_home()
    all_risks = query.risks(home, since_days=36500)
    return [r for r in all_risks if r.get("run_id") == run_id]


def _build_summary(row: dict[str, Any]) -> dict[str, Any]:
    run_id = row.get("run_id") or ""
    # ``query.latest`` returns canonical keys (agent_name); ``query.get_run``
    # returns a merged dict (run.json keeps ``agent: {name, mode}``). Handle
    # both so the legacy contract holds.
    agent_name = row.get("agent_name")
    if not agent_name:
        agent_block = row.get("agent")
        if isinstance(agent_block, dict):
            agent_name = agent_block.get("name")
    summary: dict[str, Any] = {
        "run_id": run_id,
        "agent": agent_name or "unknown",
        "started_at": row.get("started_at") or "",
        "agent_outcome": row.get("agent_outcome") or "unknown",
        "eval_status": row.get("eval_status") or "needs_eval",
        "sealed_phase": row.get("sealed_phase") or "",
        "workspace_id": row.get("workspace_id") or "",
        "workspace_short": workspace_short(row.get("workspace_id")),
        # task_18: importer-artifact projections passed through to project_show.
        # Container runs legitimately have ``None`` for all three.
        "display_title": row.get("display_title"),
        "usage": row.get("usage"),
        "import_state": row.get("import_state"),
        "trust_report": row.get("trust_report"),
        "failures": _failures_for_run(run_id) if run_id else [],
        "risks": _risks_for_run(run_id) if run_id else [],
    }
    return summary


def show(
    run_id: Optional[str] = typer.Argument(
        None, help="run_id to show; omit when using --latest"
    ),
    latest: bool = typer.Option(
        False, "--latest", help="show the most-recent run for this workspace"
    ),
    format: str = typer.Option(
        "text", "--format", help="output format: 'text' (default) or 'json'"
    ),
) -> None:
    """Print a full run summary (failures + risks included)."""
    if run_id is None and not latest:
        raise typer.BadParameter("provide a run_id or pass --latest")
    if run_id is not None and latest:
        raise typer.BadParameter("--latest and a positional run_id are mutually exclusive")
    if format not in {"text", "json"}:
        raise typer.BadParameter(
            f"unknown --format {format!r}; expected 'text' or 'json'"
        )

    row = _resolve_row(run_id, latest)
    if row is None:
        if format == "json":
            typer.echo("null")
            return
        typer.echo("(no matching run)")
        return

    summary = _build_summary(row)

    if format == "json":
        projected = project_show(
            summary,
            summary["failures"],
            summary["risks"],
        )
        typer.echo(json.dumps(projected, sort_keys=True))
        return

    trust_report = summary.get("trust_report")
    if isinstance(trust_report, dict):
        typer.echo(f"trust_verdict: {trust_report.get('trust_verdict', '-')}")
        typer.echo(f"evidence_strength: {trust_report.get('evidence_strength', '-')}")

    for key in (
        "run_id",
        "agent",
        "started_at",
        "agent_outcome",
        "eval_status",
        "sealed_phase",
        "workspace_short",
    ):
        typer.echo(f"{key}: {summary[key]}")

    failures_list = summary["failures"]
    typer.echo(f"failures: {len(failures_list)}")
    for f in failures_list:
        typer.echo(
            f"  - {f.get('category', '-')}  {f.get('severity', '-')}  "
            f"{f.get('summary', '')}"
        )

    risks_list = summary["risks"]
    typer.echo(f"risks: {len(risks_list)}")
    for r in risks_list:
        typer.echo(
            f"  - {r.get('category', '-')}  {r.get('source', '-')}  "
            f"{r.get('summary', '')}"
        )


__all__ = ["show"]
