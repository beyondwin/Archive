"""``agentlens start`` — create a new run tree (spec §10.1)."""
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

_AGENT_NAMES = {"claude_code", "codex_cli", "codex_app", "generic"}
_AGENT_MODES = {"cli", "app", "code", "unknown"}
_ADAPTER_FOR_AGENT = {
    "claude_code": "claude_code_shim",
    "codex_cli": "codex_cli_shim",
    "codex_app": "codex_app_shim",
    "generic": "generic_shim",
}


def _root_hash(workspace_root: Path) -> str:
    return "sha256:" + sha256(
        str(workspace_root.resolve()).encode("utf-8")
    ).hexdigest()


def start(
    agent: str = typer.Option(
        ...,
        "--agent",
        help="agent identifier (claude_code|codex_cli|codex_app|generic)",
    ),
    mode: str = typer.Option(
        ..., "--mode", help="agent runtime mode (cli|app|code|unknown)"
    ),
    parent: Optional[str] = typer.Option(
        None, "--parent", help="parent run_id, if this run was spawned by another"
    ),
) -> None:
    """Start a new run; prints the new run_id to stdout."""
    if agent not in _AGENT_NAMES:
        raise typer.BadParameter(
            f"invalid agent {agent!r}; expected one of {sorted(_AGENT_NAMES)}"
        )
    if mode not in _AGENT_MODES:
        raise typer.BadParameter(
            f"invalid mode {mode!r}; expected one of {sorted(_AGENT_MODES)}"
        )

    workspace_root = Path.cwd()
    workspace_id, basis, metadata = compute_workspace_id(workspace_root)
    new_run_id = make_run_id()
    target_dir = build_run_dir(workspace_id, new_run_id)
    target_dir.mkdir(parents=True, exist_ok=True)

    workspace_block: dict = {
        "root_label": "<workspace>",
        "root_hash": _root_hash(workspace_root),
        "id_basis": basis,
    }
    if "git_remote_hash" in metadata:
        workspace_block["git_remote_hash"] = metadata["git_remote_hash"]
    if "git_branch" in metadata:
        workspace_block["git_branch"] = metadata["git_branch"]

    run_doc: dict = {
        "schema": SCHEMA_RUN_V1,
        "run_id": new_run_id,
        "workspace_id": workspace_id,
        "started_at": utc_now_iso(),
        "agent": {"name": agent, "mode": mode},
        "workspace": workspace_block,
        "recording": {
            "mode": DEFAULT_MODE,
            "adapter": _ADAPTER_FOR_AGENT.get(agent, "generic_shim"),
        },
    }
    if parent:
        run_doc["parent_run_id"] = parent

    write_run_meta(target_dir, run_doc)

    event = {
        "schema": SCHEMA_EVENT_V1,
        "event_id": make_event_id(),
        "run_id": new_run_id,
        "ts": utc_now_iso(),
        "type": "run.started",
        "payload": {"agent": agent, "mode": mode},
    }
    append_event(target_dir, event)

    write_workspace_pointer(workspace_root, new_run_id, target_dir)

    typer.echo(new_run_id)


__all__ = ["start"]
