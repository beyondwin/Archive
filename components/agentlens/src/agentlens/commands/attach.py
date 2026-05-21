"""``agentlens attach`` — record an artifact.attached event.

For v0 the file is not copied into the run tree; the event simply records
that an artifact of the given kind was produced at the given path. Real
artifact promotion lands with a later task.
"""
from __future__ import annotations

import json
from pathlib import Path

import typer

from agentlens.constants import SCHEMA_EVENT_V1
from agentlens.ids import make_event_id
from agentlens.store.paths import safe_label_path
from agentlens.store.writer import append_event
from agentlens.time import utc_now_iso

from ._run_resolve import latest_run_dir


def attach(
    kind: str = typer.Option(..., "--kind", help="artifact kind label"),
    path: Path = typer.Option(
        ..., "--path", help="path to the artifact (recorded only as a label)"
    ),
) -> None:
    """Append an ``artifact.attached`` event referencing *path*."""
    workspace_root = Path.cwd()
    run_dir = latest_run_dir(workspace_root)
    run_id_str = json.loads(
        (run_dir / "run.json").read_text(encoding="utf-8")
    )["run_id"]

    label = safe_label_path(Path(path), workspace_root)
    event = {
        "schema": SCHEMA_EVENT_V1,
        "event_id": make_event_id(),
        "run_id": run_id_str,
        "ts": utc_now_iso(),
        "type": "artifact.attached",
        "payload": {"kind": kind, "path_label": label},
    }
    append_event(run_dir, event)


__all__ = ["attach"]
