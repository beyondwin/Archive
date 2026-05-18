"""``agentlens final`` — write final.json and emit run.finalized event."""
from __future__ import annotations

import json
from pathlib import Path

import typer

from agentlens.constants import (
    AGENT_OUTCOMES,
    SCHEMA_EVENT_V1,
    SCHEMA_FINAL_V1,
)
from agentlens.ids import make_event_id
from agentlens.store.writer import append_event, write_final
from agentlens.time import utc_now_iso

from ._run_resolve import latest_run_dir


def final(
    outcome: str = typer.Option(
        ...,
        "--outcome",
        help=f"agent outcome; one of {sorted(AGENT_OUTCOMES)}",
    ),
    summary: str = typer.Option(
        "", "--summary", help="optional human-readable summary"
    ),
) -> None:
    """Record the run's final outcome."""
    if outcome not in AGENT_OUTCOMES:
        raise typer.BadParameter(
            f"invalid outcome {outcome!r}; expected one of {sorted(AGENT_OUTCOMES)}"
        )

    run_dir = latest_run_dir(Path.cwd())
    run_id_str = json.loads(
        (run_dir / "run.json").read_text(encoding="utf-8")
    )["run_id"]

    final_doc = {
        "schema": SCHEMA_FINAL_V1,
        "run_id": run_id_str,
        "ended_at": utc_now_iso(),
        "agent_outcome": outcome,
        "summary": summary,
        "changed_files": [],
        "verification": [],
        "residual_risks": [],
    }
    write_final(run_dir, final_doc)

    event = {
        "schema": SCHEMA_EVENT_V1,
        "event_id": make_event_id(),
        "run_id": run_id_str,
        "ts": utc_now_iso(),
        "type": "run.finalized",
        "payload": {"agent_outcome": outcome},
    }
    append_event(run_dir, event)


__all__ = ["final"]
