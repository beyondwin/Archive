"""``agentlens event append`` — opaque event ingest (spec §4.2.3, S1.5.1).

Exposes the ``event`` Typer sub-group. ``append`` accepts exactly one
payload source (``--payload-json | --payload-file | --payload-stdin``)
and routes through :func:`agentlens.store.writer.append_event` so the
locking / redaction / schema-validation contract stays centralised.

Run resolution is filesystem-first via the ``runs_root()`` scan used by
:mod:`agentlens.commands.run_close`. The SQLite index is acceleration-only
and is updated best-effort after a successful append; failure to touch
the index never blocks the write.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import typer

from agentlens.constants import SCHEMA_EVENT_V1
from agentlens.ids import make_event_id
from agentlens.store.paths import runs_root
from agentlens.store.writer import append_event
from agentlens.time import utc_now_iso, validate_iso8601_utc

event_app = typer.Typer(
    name="event",
    no_args_is_help=True,
    add_completion=False,
    help="Opaque event ingest (spec §4.2.3).",
)


def _find_run_dir(run_id: str) -> Optional[Path]:
    """Scan ``<runs_root>/*/<run_id>/`` and return the first match.

    Mirrors :func:`agentlens.commands.run_close._find_run_dir`; we keep
    a sibling copy rather than importing to avoid a circular dependency
    if either module gains shared imports later.
    """
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
    """Refresh the optional SQLite index; swallow all errors (spec §7.3)."""
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


def _resolve_payload(
    payload_json: Optional[str],
    payload_file: Optional[Path],
    payload_stdin: bool,
) -> dict:
    """Return the parsed payload from exactly one source; halt otherwise."""
    provided = [
        ("--payload-json", payload_json is not None),
        ("--payload-file", payload_file is not None),
        ("--payload-stdin", payload_stdin),
    ]
    chosen = [name for name, present in provided if present]
    if len(chosen) == 0:
        raise typer.BadParameter(
            "exactly one of --payload-json, --payload-file, --payload-stdin is required"
        )
    if len(chosen) > 1:
        raise typer.BadParameter(
            f"choose exactly one payload source; got {', '.join(chosen)}"
        )

    if payload_json is not None:
        raw = payload_json
    elif payload_file is not None:
        raw = Path(payload_file).read_text(encoding="utf-8")
    else:
        raw = sys.stdin.read()

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(f"payload is not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise typer.BadParameter("payload must be a JSON object")
    return parsed


def _raw_v2_event(payload: dict, *, run: str, type_: str) -> dict | None:
    if payload.get("schema") != "agentlens.event.v2":
        return None
    event_type = payload.get("event_type")
    if event_type != type_:
        raise typer.BadParameter(
            f"raw v2 event_type {event_type!r} does not match --type {type_!r}"
        )
    event_run = payload.get("run_id")
    if event_run != run:
        raise typer.BadParameter(
            f"raw v2 run_id {event_run!r} does not match --run {run!r}"
        )
    return payload


@event_app.command("append")
def append(
    run: str = typer.Option(..., "--run", help="run_id receiving the event"),
    type_: str = typer.Option(
        ..., "--type", help="event type (e.g. runway.worker_result)"
    ),
    payload_json: Optional[str] = typer.Option(
        None, "--payload-json", help="inline JSON object payload"
    ),
    payload_file: Optional[Path] = typer.Option(
        None,
        "--payload-file",
        help="path to a JSON file containing the payload",
    ),
    payload_stdin: bool = typer.Option(
        False, "--payload-stdin", help="read JSON payload from stdin"
    ),
    ts: Optional[str] = typer.Option(
        None,
        "--ts",
        help="override timestamp (UTC ISO8601 with trailing Z)",
    ),
) -> None:
    """Append a schema-valid event line to ``events.jsonl``.

    On any unexpected error: stderr warning + exit 0 (non-blocking, per
    spec §4.2.3). ``typer.BadParameter`` from argument validation is
    *not* caught — those are user errors and should exit non-zero.
    """
    payload = _resolve_payload(payload_json, payload_file, payload_stdin)

    if ts is not None and not validate_iso8601_utc(ts):
        raise typer.BadParameter(
            f"--ts must be UTC ISO8601 with trailing Z; got {ts!r}"
        )

    try:
        run_dir = _find_run_dir(run)
        if run_dir is None:
            typer.echo(
                f"warning: unknown run id {run!r}; event not appended",
                err=True,
            )
            return

        event = _raw_v2_event(payload, run=run, type_=type_) or {
            "schema": SCHEMA_EVENT_V1,
            "event_id": make_event_id(),
            "run_id": run,
            "ts": ts or utc_now_iso(),
            "type": type_,
            "payload": payload,
        }
        append_event(run_dir, event)
        _best_effort_index(run_dir)
    except typer.BadParameter:
        raise
    except Exception as exc:  # pragma: no cover - defensive swallow
        typer.echo(f"warning: event append failed: {exc}", err=True)
        return


__all__ = ["event_app", "append"]
