"""``agentlens run-open`` — create a container run (spec §4.2.1, S1.5.1).

A *container* run records orchestrator-level activity (e.g. a CME spawn,
a wrapper supervisor) that does not own a transcript itself. The container
``run.json`` is schema-valid v1 with ``run_kind="container"`` and
``recording.has_transcript=false``; ``final.json`` is written only when the
matching :mod:`agentlens.commands.run_close` is invoked.

Output contract: prints exactly one line to stdout — the ``run_id``. All
other diagnostics (if any) go to stderr.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Optional

import typer

from agentlens.constants import (
    DEFAULT_MODE,
    SCHEMA_EVENT_V1,
    SCHEMA_RUN_V1,
)
from agentlens.ids import compute_workspace_id, make_event_id, make_run_id
from agentlens.store.paths import run_dir as build_run_dir
from agentlens.store.writer import (
    append_event,
    write_run_meta,
    write_workspace_pointer,
)
from agentlens.time import utc_now_iso


def _root_hash(workspace_root: Path) -> str:
    return "sha256:" + sha256(
        str(workspace_root.resolve()).encode("utf-8")
    ).hexdigest()


def run_open(
    agent: str = typer.Option(
        ...,
        "--agent",
        help="container agent label (e.g. kws-cme-orchestrator)",
    ),
    workspace: Optional[Path] = typer.Option(
        None,
        "--workspace",
        help="workspace root (defaults to cwd)",
    ),
    parent: Optional[str] = typer.Option(
        None,
        "--parent",
        help="parent run_id, if this container was spawned by another run",
    ),
    meta: list[str] = typer.Option(
        None,
        "--meta",
        help="repeatable k=v metadata; emitted on the run.started event payload",
    ),
) -> None:
    """Open a container run; prints the new run_id to stdout."""
    workspace_root = (workspace or Path.cwd()).resolve()
    workspace_id, basis, ws_meta = compute_workspace_id(workspace_root)
    new_run_id = make_run_id()
    target_dir = build_run_dir(workspace_id, new_run_id)
    target_dir.mkdir(parents=True, exist_ok=True)

    workspace_block: dict = {
        "root_label": "<workspace>",
        "root_hash": _root_hash(workspace_root),
        "id_basis": basis,
    }
    if "git_remote_hash" in ws_meta:
        workspace_block["git_remote_hash"] = ws_meta["git_remote_hash"]
    if "git_branch" in ws_meta:
        workspace_block["git_branch"] = ws_meta["git_branch"]

    run_doc: dict = {
        "schema": SCHEMA_RUN_V1,
        "run_id": new_run_id,
        "workspace_id": workspace_id,
        "started_at": utc_now_iso(),
        "run_kind": "container",
        "agent": {
            "name": "generic",
            "mode": "unknown",
            "label": agent,
        },
        "workspace": workspace_block,
        "recording": {
            "mode": DEFAULT_MODE,
            "adapter": "agentlens_container",
            "has_transcript": False,
            "transcript_source": "none",
        },
    }
    if parent:
        run_doc["parent_run_id"] = parent

    write_run_meta(target_dir, run_doc)

    meta_dict: dict[str, str] = {}
    for item in meta or []:
        if "=" not in item:
            continue
        k, _, v = item.partition("=")
        k = k.strip()
        if k:
            meta_dict[k] = v.strip()

    event_payload: dict = {"agent": "generic", "mode": "unknown", "label": agent}
    if meta_dict:
        event_payload["meta"] = meta_dict
    event = {
        "schema": SCHEMA_EVENT_V1,
        "event_id": make_event_id(),
        "run_id": new_run_id,
        "ts": utc_now_iso(),
        "type": "run.started",
        "payload": event_payload,
    }
    append_event(target_dir, event)

    write_workspace_pointer(workspace_root, new_run_id, target_dir)

    typer.echo(new_run_id)


__all__ = ["run_open"]
