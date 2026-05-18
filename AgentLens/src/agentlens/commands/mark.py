"""``agentlens mark`` — append a checkpoint event to the active run."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer

from agentlens.constants import EVENT_TYPES, SCHEMA_EVENT_V1
from agentlens.ids import make_event_id
from agentlens.store.writer import append_event
from agentlens.time import utc_now_iso

from ._run_resolve import latest_run_dir


def _read_run_id(run_dir: Path) -> str:
    run_json = run_dir / "run.json"
    if run_json.is_file():
        return json.loads(run_json.read_text(encoding="utf-8"))["run_id"]
    return run_dir.name


def mark(
    event_type: str = typer.Argument(
        ..., help=f"event type; one of {sorted(EVENT_TYPES)}"
    ),
    task_id: Optional[str] = typer.Option(None, "--task-id"),
    name: Optional[str] = typer.Option(None, "--name"),
) -> None:
    """Append an event to the active run's ``events.jsonl``."""
    if event_type not in EVENT_TYPES:
        raise typer.BadParameter(
            f"unknown event type {event_type!r}; expected one of {sorted(EVENT_TYPES)}"
        )

    run_dir = latest_run_dir(Path.cwd())
    payload: dict = {}
    if task_id is not None:
        payload["task_id"] = task_id
    if name is not None:
        payload["name"] = name

    event = {
        "schema": SCHEMA_EVENT_V1,
        "event_id": make_event_id(),
        "run_id": _read_run_id(run_dir),
        "ts": utc_now_iso(),
        "type": event_type,
        "payload": payload,
    }
    append_event(run_dir, event)


__all__ = ["mark"]
