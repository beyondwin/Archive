"""``agentlens run-close`` — finalize a container run (spec §4.2.2, S1.5.1).

Writes ``final.json`` for the run pointed to by ``--run`` and updates the
SQLite index best-effort. Unknown run ids are non-blocking: the command
emits a warning to stderr and exits 0 so orchestrators (CME, wrappers) can
call ``run-close`` defensively without aborting their own teardown.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer

from agentlens.constants import (
    AGENT_OUTCOMES,
    SCHEMA_EVENT_V1,
    SCHEMA_FINAL_V1,
)
from agentlens.ids import make_event_id
from agentlens.store.paths import runs_root
from agentlens.store.writer import append_event, write_final
from agentlens.time import utc_now_iso


def _find_run_dir(run_id: str) -> Optional[Path]:
    """Scan ``<runs_root>/*/<run_id>/`` and return the first match."""
    root = runs_root()
    if not root.is_dir():
        return None
    for ws_dir in root.iterdir():
        if not ws_dir.is_dir():
            continue
        candidate = ws_dir / run_id
        if candidate.is_dir() and (candidate / "run.json").is_file():
            return candidate
    return None


def _best_effort_index(run_dir: Path) -> None:
    """Update the SQLite index for *run_dir*; swallow all errors per §7.3."""
    try:
        from agentlens.store import sqlite_index
        from agentlens.store.paths import agentlens_home

        conn = sqlite_index.open_db(agentlens_home() / "index.db")
        try:
            sqlite_index.init_schema(conn)
            sqlite_index.index_run(conn, run_dir)
        finally:
            conn.close()
    except Exception:  # pragma: no cover - defensive swallow
        pass


def run_close(
    run: str = typer.Option(
        ...,
        "--run",
        help="run_id of the container run to finalize",
    ),
    outcome: str = typer.Option(
        "unknown",
        "--outcome",
        help=f"agent outcome; one of {sorted(AGENT_OUTCOMES)}",
    ),
    summary: str = typer.Option(
        "",
        "--summary",
        help="optional human-readable summary",
    ),
) -> None:
    """Close a container run; non-blocking on unknown run id."""
    if outcome not in AGENT_OUTCOMES:
        raise typer.BadParameter(
            f"invalid outcome {outcome!r}; expected one of {sorted(AGENT_OUTCOMES)}"
        )

    run_dir = _find_run_dir(run)
    if run_dir is None:
        typer.echo(
            f"warning: unknown run id {run!r}; nothing to close",
            err=True,
        )
        # Spec §4.2.2: non-blocking — exit 0 so orchestrators can call
        # run-close defensively without aborting teardown.
        return

    run_doc_path = run_dir / "run.json"
    try:
        run_doc = json.loads(run_doc_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        typer.echo(
            f"warning: cannot read {run_doc_path}: {exc}", err=True
        )
        return
    run_id_str = run_doc.get("run_id", run)

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

    _best_effort_index(run_dir)


__all__ = ["run_close"]
