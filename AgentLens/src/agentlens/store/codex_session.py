"""Codex rollout JSONL locator + parser (spec §4.2.6).

Codex CLI and Codex Desktop both write rollout files of the form
``~/.codex/sessions/YYYY/MM/DD/rollout-<ISO>-<UUIDv7>.jsonl`` while a
session is live, and move them to
``~/.codex/archived_sessions/rollout-<ISO>-<UUIDv7>.jsonl`` when the
session ends. The two trees share an identical line schema; only the
``payload.originator`` field of the leading ``session_meta`` event
distinguishes a CLI session from a Desktop one.

This module is pure: it locates source files and parses them into a
:class:`ParsedCodexSession` carrying the session-meta attributes and a
list of opaque ``codex.*`` events ready for the importer. No filesystem
writes happen here.

Tie-break: when the same session-id appears in BOTH the active and the
archived tree (e.g. a stale active copy after archival), :func:`find_rollout`
returns the active path. The importer's ``input.import_key`` scan then
deduplicates if a previous run already exists for that id.

Defensive parsing: malformed JSONL lines are skipped (warning on stderr);
the parser never raises on bad input. The session id comes from the
filename UUID suffix (and is cross-checked against ``payload.id`` for
``session_meta``).

Public API:
    ParsedCodexSession                          (dataclass)
    parse_rollout(path) -> ParsedCodexSession
    find_rollout(home, session_id, include_archived=False) -> Path | None
    list_rollouts(home, latest_only=False, since_epoch=None,
                  include_archived=False) -> list[Path]
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


# Matches ``rollout-<ISO>-<UUIDv7>.jsonl`` and captures the UUIDv7.
# UUID is any 8-4-4-4-12 hex group; we intentionally don't enforce v7 here
# so test fixtures can use simpler synthetic ids if needed.
_ROLLOUT_RE = re.compile(
    r"^rollout-.+-([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\.jsonl$"
)


@dataclass(frozen=True)
class ParsedCodexSession:
    """The minimal Codex rollout view the importer needs.

    Attributes:
        session_id: UUIDv7 from the rollout filename.
        path: absolute path to the source JSONL.
        originator: ``payload.originator`` from ``session_meta`` (e.g.
            ``"Codex CLI"`` or ``"Codex Desktop"``); ``None`` if absent.
        cli_version: ``payload.cli_version``; ``None`` if absent.
        cwd: ``payload.cwd``; ``None`` if absent.
        model_provider: ``payload.model_provider``; ``None`` if absent.
        source: ``payload.source`` (string OR object). Preserved as-is.
        parent_thread_id: extracted from
            ``source.subagent.thread_spawn.parent_thread_id`` when
            ``source`` is an object; ``None`` otherwise.
        started_at: ``session_meta.payload.timestamp`` (the rollout start).
        ended_at: timestamp of the last parseable body line, or
            ``started_at`` if no body line carries one.
        events: opaque ``codex.*`` event dicts (sans schema/event_id/run_id;
            the importer fills those in).
        line_count: number of *parseable* JSONL lines (incl. session_meta).
    """

    session_id: str
    path: Path
    originator: str | None
    cli_version: str | None
    cwd: str | None
    model_provider: str | None
    source: Any
    parent_thread_id: str | None
    started_at: str | None
    ended_at: str | None
    events: list[dict[str, Any]] = field(default_factory=list)
    line_count: int = 0


def _iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    """Yield parsed JSON objects from *path*, skipping malformed lines."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        print(
            f"warning: cannot read {path}: {exc}", file=sys.stderr
        )  # pragma: no cover
        return
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            print(
                f"warning: skipping malformed line in {path.name}",
                file=sys.stderr,
            )
            continue
        if isinstance(obj, dict):
            yield obj


def _session_id_from_filename(path: Path) -> str:
    """Return the UUID suffix of a rollout filename, or the stem if no match."""
    m = _ROLLOUT_RE.match(path.name)
    if m:
        return m.group(1)
    # Fall back to filename stem; the importer treats this as opaque.
    return path.stem


def _extract_parent_thread_id(source: Any) -> str | None:
    """Pull ``source.subagent.thread_spawn.parent_thread_id`` if present."""
    if not isinstance(source, dict):
        return None
    sub = source.get("subagent")
    if not isinstance(sub, dict):
        return None
    spawn = sub.get("thread_spawn")
    if not isinstance(spawn, dict):
        return None
    pid = spawn.get("parent_thread_id")
    return pid if isinstance(pid, str) else None


def _line_to_codex_event(line: dict[str, Any]) -> dict[str, Any] | None:
    """Map a body line to an opaque ``codex.*`` event dict, or ``None``.

    The body shapes vary across Codex versions; we only need a stable
    ``type`` + ``ts`` + opaque payload so the importer can stream them
    through :func:`store.writer.append_event`. Lines without a string
    ``timestamp`` are dropped (the AgentLens event schema requires a
    string ``ts``).
    """
    raw_type = line.get("type")
    if not isinstance(raw_type, str):
        return None
    if raw_type == "session_meta":
        # The importer handles session_meta itself; don't re-emit.
        return None
    ts = line.get("timestamp")
    if not isinstance(ts, str):
        return None

    event_type = f"codex.{raw_type}"
    # Build an opaque payload that strips top-level type/timestamp; the
    # rest is preserved so the dashboard can render whatever the rollout
    # carried.
    payload = {k: v for k, v in line.items() if k not in ("type", "timestamp")}
    return {"type": event_type, "ts": ts, "payload": payload}


def parse_rollout(path: Path) -> ParsedCodexSession:
    """Parse a Codex rollout JSONL into a :class:`ParsedCodexSession`.

    The first line should be a ``session_meta`` event; if it is missing
    the parser still returns a :class:`ParsedCodexSession` with
    ``originator=None`` so the importer can decide how to handle it.
    """
    p = Path(path)
    session_id = _session_id_from_filename(p)

    originator: str | None = None
    cli_version: str | None = None
    cwd: str | None = None
    model_provider: str | None = None
    source: Any = None
    parent_thread_id: str | None = None
    started_at: str | None = None
    ended_at: str | None = None

    events: list[dict[str, Any]] = []
    line_count = 0
    saw_meta = False

    for line in _iter_jsonl(p):
        line_count += 1
        if not saw_meta and line.get("type") == "session_meta":
            saw_meta = True
            payload = line.get("payload")
            if isinstance(payload, dict):
                pid = payload.get("id")
                if isinstance(pid, str) and pid:
                    session_id = pid
                originator = payload.get("originator") if isinstance(
                    payload.get("originator"), str
                ) else None
                cli_version = payload.get("cli_version") if isinstance(
                    payload.get("cli_version"), str
                ) else None
                cwd = payload.get("cwd") if isinstance(
                    payload.get("cwd"), str
                ) else None
                model_provider = payload.get("model_provider") if isinstance(
                    payload.get("model_provider"), str
                ) else None
                source = payload.get("source")
                parent_thread_id = _extract_parent_thread_id(source)
                ts = payload.get("timestamp")
                if isinstance(ts, str):
                    started_at = ts
            continue

        # Body line: maybe emit a codex.* event AND track the latest ts.
        ts = line.get("timestamp")
        if isinstance(ts, str):
            ended_at = ts
        evt = _line_to_codex_event(line)
        if evt is not None:
            events.append(evt)

    if ended_at is None:
        ended_at = started_at

    return ParsedCodexSession(
        session_id=session_id,
        path=p,
        originator=originator,
        cli_version=cli_version,
        cwd=cwd,
        model_provider=model_provider,
        source=source,
        parent_thread_id=parent_thread_id,
        started_at=started_at,
        ended_at=ended_at,
        events=events,
        line_count=line_count,
    )


def _sessions_root(home: Path) -> Path:
    return Path(home) / ".codex" / "sessions"


def _archived_root(home: Path) -> Path:
    return Path(home) / ".codex" / "archived_sessions"


def _iter_rollout_paths(root: Path) -> Iterable[Path]:
    """Yield every ``rollout-*-<UUID>.jsonl`` under *root* (recursive)."""
    if not root.is_dir():
        return
    for entry in sorted(root.rglob("rollout-*.jsonl")):
        if entry.is_file() and _ROLLOUT_RE.match(entry.name):
            yield entry


def find_rollout(
    home: Path,
    session_id: str,
    *,
    include_archived: bool = False,
) -> Path | None:
    """Locate a rollout JSONL for *session_id* under *home*.

    Search order: active tree first (``~/.codex/sessions/``), then the
    archived tree (``~/.codex/archived_sessions/``) when ``include_archived``
    is true. Returns the first match; when the same id appears in both
    trees the active copy wins.
    """
    for candidate in _iter_rollout_paths(_sessions_root(home)):
        if _session_id_from_filename(candidate) == session_id:
            return candidate
    if include_archived:
        for candidate in _iter_rollout_paths(_archived_root(home)):
            if _session_id_from_filename(candidate) == session_id:
                return candidate
    return None


def list_rollouts(
    home: Path,
    *,
    latest_only: bool = False,
    since_epoch: float | None = None,
    include_archived: bool = False,
) -> list[Path]:
    """Return rollout paths under *home* matching the optional filters.

    Args:
        home: typically the user's ``$HOME``; tests pass a tmp path.
        latest_only: if True, returns a list containing just the most
            recently modified rollout across the searched trees.
        since_epoch: optional mtime cutoff (Unix epoch seconds). Only
            rollouts with ``mtime >= since_epoch`` are returned.
        include_archived: also search ``~/.codex/archived_sessions/``.

    When the same ``session_id`` appears in both trees (stale active
    copy after archival), both paths are returned; the importer's
    ``input.import_key`` scan dedupes downstream.
    """
    paths: list[Path] = list(_iter_rollout_paths(_sessions_root(home)))
    if include_archived:
        paths.extend(_iter_rollout_paths(_archived_root(home)))

    if since_epoch is not None:
        paths = [p for p in paths if p.stat().st_mtime >= since_epoch]

    if not latest_only:
        return paths
    if not paths:
        return []
    newest = max(paths, key=lambda p: p.stat().st_mtime)
    return [newest]


__all__ = [
    "ParsedCodexSession",
    "find_rollout",
    "list_rollouts",
    "parse_rollout",
]
