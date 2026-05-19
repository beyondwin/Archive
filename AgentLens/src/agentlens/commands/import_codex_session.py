"""``agentlens import codex-session`` — Codex rollout JSONL importer (spec §4.2.6).

Materialises a ``run_kind="capture"`` run from a Codex rollout JSONL
under ``~/.codex/sessions/YYYY/MM/DD/`` (and optionally
``~/.codex/archived_sessions/``).

Each imported rollout becomes one capture run with:

* ``agent.name="codex_cli"`` (locked enum value covers both CLI and
  Desktop; ``agent.label`` and ``agent.mode`` distinguish them);
* ``recording.adapter="agentlens_session_import"``;
* ``recording.has_transcript=true`` /
  ``recording.transcript_source="codex-rollout-jsonl"``;
* ``input.import_key="codex-rollout:<session-id>"`` (UUIDv7) for
  idempotent re-import (scanning existing runs short-circuits duplicate
  writes — see :func:`_existing_run_for_import_key`).

The transcript is COPIED (not symlinked) into
``artifacts/transcripts/<session-id>.jsonl`` so the run tree is
self-contained when the source ``~/.codex/`` directory rotates.

Subagent linkage (``payload.source.subagent.thread_spawn``):
    On every import we check whether a previously imported run carries
    ``input.import_key="codex-rollout:<parent_thread_id>"``. If so, the
    new run's ``parent_run_id`` is set immediately. Otherwise
    ``meta.pending_parent_thread_id`` is recorded and every subsequent
    import scans all existing runs for matching pending fields and
    backfills ``parent_run_id`` when the parent is finally imported.

This module registers its sub-command on the existing ``import`` Typer
group exposed by ``import_claude_session.import_app`` (Task 7 wired the
group on the root CLI).
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
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
from agentlens.store.codex_session import (
    ParsedCodexSession,
    find_rollout,
    list_rollouts,
    parse_rollout,
)
from agentlens.store.paths import run_dir as build_run_dir
from agentlens.store.paths import runs_root
from agentlens.store.writer import (
    append_event,
    write_run_meta,
    write_workspace_pointer,
)
from agentlens.time import utc_now_iso

# Reuse the import Typer group registered by Task 7's command module so
# we land as a sibling sub-command of ``import claude-session``.
from agentlens.commands.import_claude_session import import_app


def _root_hash(workspace_root: Path) -> str:
    return "sha256:" + sha256(
        str(workspace_root.resolve()).encode("utf-8")
    ).hexdigest()


def _existing_run_for_import_key(import_key: str) -> Optional[Path]:
    """Return the run dir already tagged with *import_key*, or ``None``."""
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


def _iter_all_run_dirs() -> list[Path]:
    """Return every ``<runs_root>/<ws>/<run>/`` directory with a run.json."""
    root = runs_root()
    out: list[Path] = []
    if not root.is_dir():
        return out
    for ws_dir in root.iterdir():
        if not ws_dir.is_dir():
            continue
        for candidate in ws_dir.iterdir():
            if (candidate / "run.json").is_file():
                out.append(candidate)
    return out


def _backfill_pending_parents(imported_session_id: str, imported_run_id: str) -> None:
    """Rewrite any pending children to point at the just-imported parent.

    For every recorded run whose ``meta.pending_parent_thread_id`` equals
    *imported_session_id*, set ``parent_run_id=<imported_run_id>`` and
    drop the pending field, then atomically rewrite the run.json (which
    validates against the schema again on the way out).
    """
    for candidate in _iter_all_run_dirs():
        run_json = candidate / "run.json"
        try:
            doc = json.loads(run_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        meta = doc.get("meta")
        if not isinstance(meta, dict):
            continue
        if meta.get("pending_parent_thread_id") != imported_session_id:
            continue
        # Backfill.
        doc["parent_run_id"] = imported_run_id
        new_meta = {k: v for k, v in meta.items() if k != "pending_parent_thread_id"}
        if new_meta:
            doc["meta"] = new_meta
        else:
            doc.pop("meta", None)
        write_run_meta(candidate, doc)


def _agent_label_and_mode(originator: Optional[str]) -> tuple[str, str]:
    """Return ``(label, mode)`` for ``run.agent`` based on *originator*.

    The locked ``agent.name`` enum (`codex_cli`/`codex_app`/...) is too
    coarse to carry "CLI vs Desktop"; we encode that in ``agent.label``
    and use the locked ``agent.mode`` enum (``cli``/``app``).
    """
    if originator == "Codex Desktop":
        return ("codex-desktop", "app")
    return ("codex-cli", "cli")


def _build_meta(parsed: ParsedCodexSession) -> dict:
    """Build the ``run.meta`` dict from a parsed rollout.

    Only known string fields are preserved; ``codex_source`` accepts
    either a bare string or an object (the rollout's raw ``source``).
    """
    meta: dict = {}
    if parsed.originator:
        meta["originator"] = parsed.originator
    if parsed.cli_version:
        meta["codex_cli_version"] = parsed.cli_version
    if parsed.source is not None:
        meta["codex_source"] = parsed.source
    return meta


def _resolve_sources(
    *,
    latest: bool,
    session_id: Optional[str],
    all_flag: bool,
    since: Optional[str],
    include_archived: bool,
) -> list[Path]:
    """Return the source rollout paths matching the selector.

    Exactly one of ``--latest``, ``--id``, ``--all``, ``--since`` must be
    supplied. ``--include-archived`` is a modifier accepted on top of any
    selector; for ``--id`` it broadens the search across both trees.
    """
    chosen = [
        name for name, flag in (
            ("--latest", latest),
            ("--id", session_id is not None),
            ("--all", all_flag),
            ("--since", since is not None),
        ) if flag
    ]
    if len(chosen) == 0:
        raise typer.BadParameter(
            "exactly one of --latest, --id, --all, or --since is required"
        )
    if len(chosen) > 1:
        raise typer.BadParameter(
            f"choose exactly one of --latest/--id/--all/--since; got {', '.join(chosen)}"
        )

    home = Path.home()
    if session_id is not None:
        found = find_rollout(home, session_id, include_archived=include_archived)
        return [found] if found is not None else []
    if latest:
        return list_rollouts(
            home, latest_only=True, include_archived=include_archived
        )
    if since is not None:
        try:
            # Accept ISO8601; allow trailing Z.
            iso = since.replace("Z", "+00:00")
            dt = datetime.fromisoformat(iso)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            cutoff = dt.timestamp()
        except ValueError as exc:
            raise typer.BadParameter(
                f"--since must be ISO8601: {since!r} ({exc})"
            ) from exc
        return list_rollouts(
            home, since_epoch=cutoff, include_archived=include_archived
        )
    # --all
    return list_rollouts(home, include_archived=include_archived)


def _import_one(source: Path, *, workspace_root: Path) -> Optional[Path]:
    """Import a single rollout JSONL; returns the run dir or ``None`` on no-op."""
    # task_15 introduced a tuple return for parse_rollout; task_17 will
    # plumb the ImportReport into artifacts/import_report.json.
    parsed, _report = parse_rollout(source)
    import_key = f"codex-rollout:{parsed.session_id}"

    existing = _existing_run_for_import_key(import_key)
    if existing is not None:
        return existing

    workspace_id, basis, ws_meta = compute_workspace_id(workspace_root)
    new_run_id = make_run_id()
    target_dir = build_run_dir(workspace_id, new_run_id)
    target_dir.mkdir(parents=True, exist_ok=True)

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
    label, mode = _agent_label_and_mode(parsed.originator)

    run_doc: dict = {
        "schema": SCHEMA_RUN_V1,
        "run_id": new_run_id,
        "workspace_id": workspace_id,
        "started_at": started_at,
        "run_kind": "capture",
        "agent": {
            "name": "codex_cli",
            "mode": mode,
            "label": label,
        },
        "workspace": workspace_block,
        "recording": {
            "mode": DEFAULT_MODE,
            "adapter": "agentlens_session_import",
            "has_transcript": True,
            "transcript_source": "codex-rollout-jsonl",
        },
        "input": {
            "kind": "codex-rollout",
            "import_key": import_key,
        },
    }

    meta = _build_meta(parsed)

    # Subagent linkage.
    if parsed.parent_thread_id:
        parent_dir = _existing_run_for_import_key(
            f"codex-rollout:{parsed.parent_thread_id}"
        )
        if parent_dir is not None:
            try:
                parent_doc = json.loads(
                    (parent_dir / "run.json").read_text(encoding="utf-8")
                )
                parent_run_id = parent_doc.get("run_id")
                if isinstance(parent_run_id, str):
                    run_doc["parent_run_id"] = parent_run_id
            except (OSError, json.JSONDecodeError):
                pass
        if "parent_run_id" not in run_doc:
            # Parent not imported yet — record pending linkage so a later
            # import can backfill.
            meta["pending_parent_thread_id"] = parsed.parent_thread_id

    if meta:
        run_doc["meta"] = meta

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
                "source": "codex-rollout-jsonl",
                "session_id": parsed.session_id,
            },
        },
    )

    # Opaque codex.* events.
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
                "source": "codex-rollout-jsonl",
                "session_id": parsed.session_id,
                "line_count": parsed.line_count,
            },
        },
    )

    write_workspace_pointer(workspace_root, new_run_id, target_dir)

    # Backfill any previously imported children that were waiting on
    # this session-id as their parent.
    _backfill_pending_parents(parsed.session_id, new_run_id)
    return target_dir


@import_app.command("codex-session")
def codex_session(
    latest: bool = typer.Option(
        False, "--latest", help="import the most recently modified rollout"
    ),
    id_: Optional[str] = typer.Option(
        None, "--id", help="explicit Codex rollout UUIDv7 session id"
    ),
    all_: bool = typer.Option(
        False, "--all", help="import every rollout under ~/.codex/sessions/"
    ),
    since: Optional[str] = typer.Option(
        None, "--since", help="import rollouts whose mtime is >= ISO8601 cutoff"
    ),
    include_archived: bool = typer.Option(
        False,
        "--include-archived",
        help="also search ~/.codex/archived_sessions/",
    ),
) -> None:
    """Import one or more Codex rollout JSONL files as capture runs.

    Non-blocking on missing/unknown ids (warning to stderr + exit 0).
    Re-importing the same session is a no-op for both the run row AND
    the transcript artifact. Subagent linkage is resolved at import time;
    children imported before their parent get backfilled when the parent
    is later imported.
    """
    sources = _resolve_sources(
        latest=latest,
        session_id=id_,
        all_flag=all_,
        since=since,
        include_archived=include_archived,
    )
    if not sources:
        typer.echo(
            "warning: no codex rollout matched the selector; nothing imported",
            err=True,
        )
        return

    workspace_root = Path.cwd().resolve()
    for src in sources:
        try:
            _import_one(src, workspace_root=workspace_root)
        except Exception as exc:  # pragma: no cover - defensive
            typer.echo(
                f"warning: failed to import {src.name}: {exc}", err=True
            )


__all__ = ["codex_session"]
