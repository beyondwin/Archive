"""``agentlens import claude-session`` — JSONL importer (spec §4.2.5).

Materialises a ``run_kind="capture"`` run from a Claude Code session
JSONL stored under ``~/.claude/projects/<encoded>/<session-id>.jsonl``.

Each imported session becomes one capture run with:

* ``agent.name="claude_code"`` / ``agent.mode="code"``;
* ``recording.has_transcript=true`` and
  ``recording.transcript_source="claude-session-jsonl"``;
* ``input.import_key="claude-session:<session-id>"`` for idempotent
  re-import (scanning existing runs short-circuits duplicate writes).

The transcript is COPIED (not symlinked) into
``artifacts/transcripts/<session-id>.jsonl`` so the run tree is
self-contained when the source ``~/.claude/`` directory is rotated.

The Typer sub-app is registered on the root CLI as ``import``; this
module exposes :data:`import_app` for that wire-up.
"""
from __future__ import annotations

import json
import shutil
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
from agentlens.store.claude_session import (
    find_session,
    list_sessions,
    parse_session,
)
from agentlens.store.paths import run_dir as build_run_dir
from agentlens.store.paths import runs_root
from agentlens.store.writer import (
    append_event,
    write_run_meta,
    write_workspace_pointer,
)
from agentlens.time import utc_now_iso

import_app = typer.Typer(
    name="import",
    no_args_is_help=True,
    add_completion=False,
    help="Import external session/transcript material into AgentLens runs.",
)


def _root_hash(workspace_root: Path) -> str:
    return "sha256:" + sha256(
        str(workspace_root.resolve()).encode("utf-8")
    ).hexdigest()


def _existing_run_for_import_key(import_key: str) -> Optional[Path]:
    """Return the run dir already tagged with *import_key*, or ``None``.

    Idempotency rests on scanning every recorded run.json under
    ``<runs_root>/*/<run_id>/`` for a matching ``input.import_key``.
    The scan is intentionally simple and bounded by recorded-run count;
    a future optimisation could maintain an explicit import index.
    """
    root = runs_root()
    if not root.is_dir():
        return None
    for ws_dir in root.iterdir():
        if not ws_dir.is_dir():
            continue
        for candidate in ws_dir.iterdir():
            run_json = candidate / "run.json"
            if not run_json.is_file():
                continue
            try:
                doc = json.loads(run_json.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if doc.get("input", {}).get("import_key") == import_key:
                return candidate
    return None


def _resolve_source(
    latest: bool,
    session_id: Optional[str],
    all_flag: bool,
    project: Optional[str],
) -> list[Path]:
    """Return the list of source JSONLs the command should import.

    Exactly one selector must be provided: ``--latest``, ``--id``, or
    ``--all``. Validation errors are raised as :class:`typer.BadParameter`
    so the CLI exits non-zero with a usage hint.
    """
    chosen = [name for name, flag in (
        ("--latest", latest),
        ("--id", session_id is not None),
        ("--all", all_flag),
    ) if flag]
    if len(chosen) == 0:
        raise typer.BadParameter(
            "exactly one of --latest, --id, or --all is required"
        )
    if len(chosen) > 1:
        raise typer.BadParameter(
            f"choose exactly one of --latest/--id/--all; got {', '.join(chosen)}"
        )

    home = Path.home()
    if session_id is not None:
        found = find_session(home, session_id, project=project)
        if found is None:
            return []
        return [found]
    if latest:
        return list_sessions(home, project=project, latest_only=True)
    # --all
    return list_sessions(home, project=project, latest_only=False)


def _import_one(
    source: Path,
    *,
    workspace_root: Path,
    parent: Optional[str],
) -> Optional[Path]:
    """Import a single session JSONL; returns the run dir or ``None`` on no-op.

    Idempotent: if a run already carries ``input.import_key`` matching this
    session, the existing run dir is returned without further writes.
    """
    parsed = parse_session(source)
    import_key = f"claude-session:{parsed.session_id}"

    existing = _existing_run_for_import_key(import_key)
    if existing is not None:
        return existing

    workspace_id, basis, ws_meta = compute_workspace_id(workspace_root)
    new_run_id = make_run_id()
    target_dir = build_run_dir(workspace_id, new_run_id)
    target_dir.mkdir(parents=True, exist_ok=True)

    # Copy the transcript before writing run.json so the manifest writer
    # (Task ≥ 5) can observe the artifact when it ultimately runs.
    transcript_dir = target_dir / "artifacts" / "transcripts"
    transcript_dir.mkdir(parents=True, exist_ok=True)
    transcript_dst = transcript_dir / f"{parsed.session_id}.jsonl"
    shutil.copyfile(source, transcript_dst)

    workspace_block: dict = {
        "root_label": "<workspace>",
        "root_hash": _root_hash(workspace_root),
        "id_basis": basis,
    }
    if "git_remote_hash" in ws_meta:
        workspace_block["git_remote_hash"] = ws_meta["git_remote_hash"]
    if "git_branch" in ws_meta:
        workspace_block["git_branch"] = ws_meta["git_branch"]

    started_at = parsed.started_at or utc_now_iso()
    ended_at = parsed.ended_at or started_at

    run_doc: dict = {
        "schema": SCHEMA_RUN_V1,
        "run_id": new_run_id,
        "workspace_id": workspace_id,
        "started_at": started_at,
        "run_kind": "capture",
        "agent": {
            "name": "claude_code",
            "mode": "code",
            "label": "claude-code-session-import",
        },
        "workspace": workspace_block,
        "recording": {
            "mode": DEFAULT_MODE,
            "adapter": "claude_session_importer",
            "has_transcript": True,
            "transcript_source": "claude-session-jsonl",
        },
        "input": {
            "kind": "claude-session",
            "import_key": import_key,
        },
    }
    if parent:
        run_doc["parent_run_id"] = parent

    write_run_meta(target_dir, run_doc)

    # command.started
    append_event(
        target_dir,
        {
            "schema": SCHEMA_EVENT_V1,
            "event_id": make_event_id(),
            "run_id": new_run_id,
            "ts": started_at,
            "type": "command.started",
            "payload": {
                "source": "claude-session-jsonl",
                "session_id": parsed.session_id,
            },
        },
    )

    # Opaque claude.* events from the session.
    for evt in parsed.events:
        append_event(
            target_dir,
            {
                "schema": SCHEMA_EVENT_V1,
                "event_id": make_event_id(),
                "run_id": new_run_id,
                "ts": evt["ts"],
                "type": evt["type"],
                "payload": evt["payload"],
            },
        )

    # command.finished
    append_event(
        target_dir,
        {
            "schema": SCHEMA_EVENT_V1,
            "event_id": make_event_id(),
            "run_id": new_run_id,
            "ts": ended_at,
            "type": "command.finished",
            "payload": {
                "source": "claude-session-jsonl",
                "session_id": parsed.session_id,
                "line_count": parsed.line_count,
            },
        },
    )

    write_workspace_pointer(workspace_root, new_run_id, target_dir)
    return target_dir


@import_app.command("claude-session")
def claude_session(
    latest: bool = typer.Option(
        False, "--latest", help="import the most recently modified session"
    ),
    id_: Optional[str] = typer.Option(
        None, "--id", help="explicit Claude Code session id"
    ),
    all_: bool = typer.Option(
        False, "--all", help="import every session under ~/.claude/projects/"
    ),
    project: Optional[str] = typer.Option(
        None,
        "--project",
        help="filter to one encoded project directory under ~/.claude/projects/",
    ),
    parent: Optional[str] = typer.Option(
        None,
        "--parent",
        help="parent run_id for explicit linkage in the recorded run.json",
    ),
) -> None:
    """Import one or more Claude Code session JSONLs as capture runs.

    Non-blocking on missing/unknown ids (warning to stderr + exit 0), in
    line with ``run-close`` / ``event append``. Re-importing a session is
    a no-op for the run row AND the transcript artifact.
    """
    sources = _resolve_source(latest, id_, all_, project)
    if not sources:
        typer.echo(
            "warning: no claude-session JSONL matched the selector; nothing imported",
            err=True,
        )
        return

    workspace_root = Path.cwd().resolve()
    for src in sources:
        try:
            _import_one(src, workspace_root=workspace_root, parent=parent)
        except Exception as exc:  # pragma: no cover - defensive
            typer.echo(
                f"warning: failed to import {src.name}: {exc}", err=True
            )


__all__ = ["claude_session", "import_app"]
