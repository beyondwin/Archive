"""``agentlens show`` — display a compact summary of a recorded run."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer

from ._run_resolve import resolve_run_dir


def _read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


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
    """Print run_id, agent, started_at, agent_outcome, eval_status (+ sealed_phase)."""
    if run_id is None and not latest:
        raise typer.BadParameter("provide a run_id or pass --latest")
    if run_id is not None and latest:
        raise typer.BadParameter("--latest and a positional run_id are mutually exclusive")

    target = run_id if run_id else None
    run_dir = resolve_run_dir(Path.cwd(), target)

    run = _read_json(run_dir / "run.json")
    final_doc = _read_json(run_dir / "final.json")
    eval_doc = _read_json(run_dir / "eval.json")
    manifest = _read_json(run_dir / "manifest.json")

    agent_block = run.get("agent", {}) if isinstance(run, dict) else {}
    summary = {
        "run_id": run.get("run_id", run_dir.name),
        "agent": agent_block.get("name", "unknown"),
        "started_at": run.get("started_at", ""),
        "agent_outcome": final_doc.get("agent_outcome", "unknown"),
        "eval_status": eval_doc.get("status", "needs_eval"),
        "sealed_phase": manifest.get("sealed_phase", ""),
    }

    if format == "json":
        typer.echo(json.dumps(summary, sort_keys=True))
        return
    if format != "text":
        raise typer.BadParameter(
            f"unknown --format {format!r}; expected 'text' or 'json'"
        )
    for key in (
        "run_id",
        "agent",
        "started_at",
        "agent_outcome",
        "eval_status",
        "sealed_phase",
    ):
        typer.echo(f"{key}: {summary[key]}")


__all__ = ["show"]
