"""Waygent trust report command."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer

from agentlens.schema.validate import SchemaError, validate_doc
from agentlens.store.paths import agentlens_home


def _find_run_dir(run_id: str) -> Optional[Path]:
    root = agentlens_home() / "runs"
    if not root.is_dir():
        return None
    for ws_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        candidate = ws_dir / run_id
        if candidate.is_dir():
            return candidate
    return None


def _load_trust_report(run_id: str) -> dict | None:
    run_dir = _find_run_dir(run_id)
    if run_dir is None:
        return None
    path = run_dir / "artifacts" / "trust_report.json"
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    validate_doc(payload, schema_name="trust_report")
    return payload


def waygent(
    run_id: str = typer.Argument(..., help="run_id to inspect"),
    format: str = typer.Option("text", "--format", help="output format: 'text' or 'json'"),
) -> None:
    """Print the Waygent trust report for a run."""
    if format not in {"text", "json"}:
        raise typer.BadParameter(f"unknown --format {format!r}; expected 'text' or 'json'")
    try:
        report = _load_trust_report(run_id)
    except (OSError, json.JSONDecodeError, SchemaError) as exc:
        if format == "json":
            typer.echo(json.dumps({"run_id": run_id, "trust_report_error": str(exc)}, sort_keys=True))
            return
        typer.echo(f"trust_report_error: {exc}")
        return
    if report is None:
        if format == "json":
            typer.echo("null")
            return
        typer.echo("(no trust report)")
        return
    if format == "json":
        typer.echo(json.dumps(report, sort_keys=True))
        return
    for key in ("run_id", "waygent_run_id", "claimed_outcome", "trust_verdict", "evidence_strength"):
        typer.echo(f"{key}: {report.get(key)}")


__all__ = ["waygent"]
