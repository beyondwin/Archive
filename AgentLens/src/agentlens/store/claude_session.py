"""Claude Code session JSONL locator + parser (spec §4.2.5).

Claude Code records each interactive session under
``~/.claude/projects/<encoded-project>/<session-id>.jsonl`` where each line
is one JSON event. This module is pure: it locates the source files and
parses them into a :class:`ParsedSession` describing session boundaries
and a list of opaque ``claude.*`` events ready for the importer to write
through :func:`agentlens.store.writer.append_event`.

Defensive parsing: malformed JSONL lines are skipped (a stderr warning is
emitted by callers if desired); the parser itself never raises on bad
input. The session id is taken from the filename, not the line payloads,
to match how Claude Code names the file.

Public API:
    ParsedSession                       (dataclass)
    parse_session(path) -> ParsedSession
    find_session(home, session_id, project=None) -> Path | None
    list_sessions(home, project=None, latest_only=False) -> list[Path]
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class ParsedSession:
    """The minimal session view the importer needs.

    Attributes:
        session_id: filename-stem session identifier.
        path: absolute path to the source JSONL.
        started_at: ISO8601 timestamp of the first parseable line.
        ended_at: ISO8601 timestamp of the last parseable line.
        events: opaque ``claude.*`` event dicts (sans schema/event_id/run_id;
            the importer fills those in).
        line_count: number of *parseable* JSONL lines.
    """

    session_id: str
    path: Path
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


def _extract_tool_use(line: dict[str, Any]) -> list[dict[str, Any]]:
    """Return one ``claude.tool_use`` event per tool_use block in *line*.

    The Claude session line shape is::

        {"type":"assistant",
         "message":{"content":[{"type":"tool_use","name":...,"input":{...}}]},
         "timestamp":"..."}

    We are deliberately defensive: a missing or non-list ``content`` short-
    circuits to an empty result so malformed lines never crash the importer.
    """
    if line.get("type") != "assistant":
        return []
    message = line.get("message")
    if not isinstance(message, dict):
        return []
    content = message.get("content")
    if not isinstance(content, list):
        return []
    ts = line.get("timestamp")
    if not isinstance(ts, str):
        return []
    out: list[dict[str, Any]] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") != "tool_use":
            continue
        name = block.get("name") or ""
        tool_use_id = block.get("id") or ""
        tool_input = block.get("input")
        payload: dict[str, Any] = {
            "name": str(name),
            "tool_use_id": str(tool_use_id),
        }
        if isinstance(tool_input, dict):
            # Keep keys but values opaque; the importer is responsible for
            # any redaction.
            payload["input_keys"] = sorted(tool_input.keys())
        out.append({"type": "claude.tool_use", "ts": ts, "payload": payload})
    return out


def parse_session(path: Path) -> ParsedSession:
    """Parse a Claude Code session JSONL into a :class:`ParsedSession`.

    The session id is the filename stem. Boundaries come from the first
    and last lines with a string ``timestamp`` field; malformed lines are
    skipped silently (warning on stderr).
    """
    p = Path(path)
    session_id = p.stem
    first_ts: str | None = None
    last_ts: str | None = None
    events: list[dict[str, Any]] = []
    line_count = 0

    for line in _iter_jsonl(p):
        line_count += 1
        ts = line.get("timestamp")
        if isinstance(ts, str):
            if first_ts is None:
                first_ts = ts
            last_ts = ts
        events.extend(_extract_tool_use(line))

    return ParsedSession(
        session_id=session_id,
        path=p,
        started_at=first_ts,
        ended_at=last_ts,
        events=events,
        line_count=line_count,
    )


def _projects_root(home: Path) -> Path:
    """Return ``<home>/.claude/projects`` (the source-of-truth directory)."""
    return Path(home) / ".claude" / "projects"


def find_session(
    home: Path, session_id: str, project: str | None = None
) -> Path | None:
    """Locate ``<session_id>.jsonl`` under ``<home>/.claude/projects/``.

    If *project* is provided, only that encoded project directory is
    searched; otherwise every project directory is scanned and the first
    match is returned.
    """
    root = _projects_root(home)
    if not root.is_dir():
        return None

    if project is not None:
        candidate = root / project / f"{session_id}.jsonl"
        return candidate if candidate.is_file() else None

    for proj_dir in sorted(root.iterdir()):
        if not proj_dir.is_dir():
            continue
        candidate = proj_dir / f"{session_id}.jsonl"
        if candidate.is_file():
            return candidate
    return None


def list_sessions(
    home: Path,
    project: str | None = None,
    latest_only: bool = False,
) -> list[Path]:
    """Return all session JSONL paths under ``<home>/.claude/projects/``.

    Args:
        home: typically the user's ``$HOME``; tests pass a tmp path.
        project: optional encoded project filter.
        latest_only: if True, returns a list containing just the most
            recently modified session (by ``mtime``). Returns ``[]`` when
            no sessions exist.
    """
    root = _projects_root(home)
    if not root.is_dir():
        return []

    if project is not None:
        proj_dirs = [root / project]
    else:
        proj_dirs = [d for d in sorted(root.iterdir()) if d.is_dir()]

    sessions: list[Path] = []
    for proj in proj_dirs:
        if not proj.is_dir():
            continue
        for entry in sorted(proj.iterdir()):
            if entry.is_file() and entry.suffix == ".jsonl":
                sessions.append(entry)

    if not latest_only:
        return sessions

    if not sessions:
        return []
    newest = max(sessions, key=lambda p: p.stat().st_mtime)
    return [newest]


__all__ = [
    "ParsedSession",
    "find_session",
    "list_sessions",
    "parse_session",
]
