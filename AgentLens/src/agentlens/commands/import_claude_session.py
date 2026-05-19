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

from agentlens.commands.import_common import (
    finalize_imported_run,
    resolve_byte_cap,
    validate_byte_cap,
)
from agentlens.constants import (
    DEFAULT_MODE,
    SCHEMA_EVENT_V1,
    SCHEMA_RUN_V1,
)
from agentlens.ids import compute_workspace_id, make_event_id, make_run_id
from agentlens.importers.artifacts import write_artifact_json
from agentlens.importers.title import extract_display_title
from agentlens.importers.usage import extract_usage
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


def _peek_session_id(source: Path) -> str:
    """Return the session id implied by *source* without parsing it.

    The session id is the filename stem (matches what
    ``parse_session`` records on ``ParsedSession.session_id``). Used for the
    pre-parse duplicate-import check so a re-import is a true no-op (no parse,
    no transcript copy, no artifact writes — E9).
    """
    return Path(source).stem


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
    byte_cap: int,
    byte_cap_source: str,
    deep_parse_only: bool,
) -> Optional[Path]:
    """Import a single session JSONL; returns the run dir or ``None`` on no-op.

    Idempotent: if a run already carries ``input.import_key`` matching this
    session, the existing run dir is returned without further writes.
    Duplicate detection runs BEFORE the (potentially expensive) parse and
    BEFORE any writes so a re-import never disturbs the prior run tree (E9).
    """
    # E9: short-circuit before any work — the session id is the filename stem,
    # so we can compute the import key without parsing.
    pre_session_id = _peek_session_id(source)
    pre_import_key = f"claude-session:{pre_session_id}"
    existing = _existing_run_for_import_key(pre_import_key)
    if existing is not None:
        return existing

    parsed, report = parse_session(
        source, byte_cap=byte_cap, deep_parse_only=deep_parse_only
    )
    # parse_session pins byte_cap_source="default"; override with the real
    # provenance the CLI resolved (flag / env / default).
    report.byte_cap_source = byte_cap_source  # type: ignore[assignment]

    # Belt-and-braces: re-check in case the stem heuristic disagreed (e.g.,
    # the filename was renamed on disk). parse_session is the source of truth
    # for the canonical session id.
    import_key = f"claude-session:{parsed.session_id}"
    existing = _existing_run_for_import_key(import_key)
    if existing is not None:
        return existing

    workspace_id, basis, ws_meta = compute_workspace_id(workspace_root)
    new_run_id = make_run_id()
    target_dir = build_run_dir(workspace_id, new_run_id)
    target_dir.mkdir(parents=True, exist_ok=True)

    # Copy the transcript before writing run.json so the manifest writer
    # observes the artifact when seal(pre_eval) runs in finalize.
    transcript_dir = target_dir / "artifacts" / "transcripts"
    transcript_dir.mkdir(parents=True, exist_ok=True)
    transcript_rel = Path("artifacts") / "transcripts" / f"{parsed.session_id}.jsonl"
    transcript_dst = target_dir / transcript_rel
    shutil.copyfile(source, transcript_dst)
    try:
        transcript_bytes = transcript_dst.stat().st_size
    except OSError:
        transcript_bytes = 0
    report.set_transcript_artifact(transcript_rel.as_posix(), transcript_bytes)

    # Derive display title from the first user message (heuristic in
    # importers.title — pure, redaction-safe).
    display_title = extract_display_title(
        explicit=None, first_user_message=parsed.first_user_message_text
    )
    report.set_display_title(
        display_title, "first_user_message" if display_title else "null"
    )

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

    # Event ordering: run.started → command.started → claude.* → command.finished.
    append_event(
        target_dir,
        {
            "schema": SCHEMA_EVENT_V1,
            "event_id": make_event_id(),
            "run_id": new_run_id,
            "ts": started_at,
            "type": "run.started",
            "payload": {
                "agent": "claude_code",
                "mode": "code",
                "label": "claude-code-session-import",
            },
        },
    )

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

    # Opaque claude.* events from the session (preserves source order).
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
                "analysis_state": report.analysis_state,
            },
        },
    )

    # Compute usage summary from billable assistant records (extract_usage is
    # pure; no I/O). Desktop sessions with no usage still get a deterministic
    # all-zero record so query-layer projections are stable.
    usage = extract_usage("claude-session", parsed.usage_records)

    # Persist artifacts BEFORE finalize_imported_run so seal(pre_eval) covers
    # them in manifest.json.
    artifacts_dir = target_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    write_artifact_json(artifacts_dir / "import_report.json", report.to_dict())
    write_artifact_json(artifacts_dir / "usage.json", usage.to_dict())

    write_workspace_pointer(workspace_root, new_run_id, target_dir)

    finalize_imported_run(
        target_dir, new_run_id, analysis_state=report.analysis_state
    )
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
    byte_cap: Optional[int] = typer.Option(
        None,
        "--byte-cap",
        help=(
            "deep-parse byte cap (1 MiB–1 GiB). Defaults to 64 MiB; "
            "AGENTLENS_IMPORT_BYTE_CAP env var overrides default."
        ),
        callback=validate_byte_cap,
    ),
    deep_parse_only: bool = typer.Option(
        False,
        "--deep-parse-only/--no-deep-parse-only",
        help=(
            "skip the deep parse entirely when the source exceeds --byte-cap; "
            "transcript is still copied and the run is sealed (analysis_state=skipped)."
        ),
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

    effective_cap, cap_source = resolve_byte_cap(byte_cap)

    workspace_root = Path.cwd().resolve()
    for src in sources:
        try:
            _import_one(
                src,
                workspace_root=workspace_root,
                parent=parent,
                byte_cap=effective_cap,
                byte_cap_source=cap_source,
                deep_parse_only=deep_parse_only,
            )
        except Exception as exc:  # pragma: no cover - defensive
            typer.echo(
                f"warning: failed to import {src.name}: {exc}", err=True
            )


__all__ = ["claude_session", "import_app"]
