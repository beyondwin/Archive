"""Claude Code session JSONL locator + parser (spec §4.2.5).

Claude Code records each interactive session under
``~/.claude/projects/<encoded-project>/<session-id>.jsonl`` where each line
is one JSON event. This module is pure: it locates the source files and
parses them into a :class:`ParsedSession` describing session boundaries
and a list of opaque ``claude.*`` events ready for the importer to write
through :func:`agentlens.store.writer.append_event`.

Defensive parsing: malformed JSONL lines, oversized lines, and lines past
the byte cap are tracked on the returned :class:`ImportReport` rather than
raised. The session id is taken from the filename, not the line payloads,
to match how Claude Code names the file.

Streaming model: the parser opens the source in ``"rb"`` mode and iterates
line-by-line. We never call ``path.read_text()`` — large sessions must not
balloon to whole-file allocations.

Public API:
    ParsedSession                       (dataclass, frozen)
    parse_session(path, *, byte_cap=64MiB, deep_parse_only=False)
        -> tuple[ParsedSession, ImportReport]
    find_session(home, session_id, project=None) -> Path | None
    list_sessions(home, project=None, latest_only=False) -> list[Path]
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from ..importers.report import ImportReport


# Per-line cap (2 MiB). Lines longer than this are skipped without
# attempting json.loads — pathological vendor lines must not OOM the parser.
_LINE_CAP_BYTES = 2 * 1024 * 1024

# Default whole-file cap (64 MiB). Matches the spec §4.1 default; callers
# may pass a smaller cap via ``--byte-cap`` / ``AGENTLENS_IMPORT_BYTE_CAP``.
_DEFAULT_BYTE_CAP = 64 * 1024 * 1024

# Vendor allowlist — only record `unsupported_type:<x>` for lines outside
# this set. Adding a type here means "the parser understands this shape".
_KNOWN_CLAUDE_TYPES: frozenset[str] = frozenset(
    {"user", "assistant", "system", "tool_result", "summary", "file-history-snapshot"}
)


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
        first_user_message_text: concatenated text from the first user
            message in the session (``None`` if no user message seen).
        usage_records: raw line dicts for every billable assistant message,
            preserved verbatim so :func:`extract_usage` can aggregate.
    """

    session_id: str
    path: Path
    started_at: str | None
    ended_at: str | None
    events: list[dict[str, Any]] = field(default_factory=list)
    line_count: int = 0
    first_user_message_text: str | None = None
    usage_records: list[dict[str, Any]] = field(default_factory=list)


def _iter_raw_lines(
    path: Path, byte_cap: int, report: ImportReport
) -> Iterator[tuple[int, int, bytes]]:
    """Yield ``(line_number, byte_offset, raw_bytes)`` until byte cap or EOF.

    ``byte_offset`` is the offset where this line *started* in the file.
    When the next line would push the running cursor past ``byte_cap``, the
    iterator stops *without* yielding that line and marks ``report``'s
    byte-cap-hit flag.
    """
    try:
        fh = path.open("rb")
    except OSError:
        return
    with fh:
        running_offset = 0
        line_number = 0
        for raw in fh:
            line_number += 1
            line_start = running_offset
            line_len = len(raw)
            # If this line would push us over the byte cap, stop *before*
            # processing it. We keep prior lines and mark the report.
            if line_start + line_len > byte_cap:
                report.record_byte_cap_hit()
                return
            running_offset += line_len
            # Strip trailing newline bytes (\r\n or \n) so downstream
            # length checks and json.loads see only the payload.
            stripped = raw.rstrip(b"\r\n")
            if not stripped:
                # Blank line; do not count toward parsed/skip counters.
                continue
            yield line_number, line_start, stripped


def _extract_tool_use(line: dict[str, Any]) -> list[dict[str, Any]]:
    """Return one ``claude.tool_use`` event per tool_use block in *line*."""
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
            payload["input_keys"] = sorted(tool_input.keys())
        out.append({"type": "claude.tool_use", "ts": ts, "payload": payload})
    return out


def _extract_first_user_text(line: dict[str, Any]) -> str | None:
    """Return concatenated text from a Claude user-message line, or ``None``.

    Accepts both the wrapper shape (``{"message": {"role": "user", ...}}``)
    and the bare shape (``{"role": "user", ...}``). Content may be a string
    or a list of content blocks; only ``type=="text"`` blocks contribute.
    """
    msg = line.get("message")
    if not isinstance(msg, dict):
        msg = line
    if msg.get("role") != "user":
        return None
    content = msg.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") != "text":
                continue
            text = block.get("text")
            if isinstance(text, str):
                parts.append(text)
        return "\n".join(parts) if parts else None
    return None


def _is_billable_assistant(line: dict[str, Any]) -> bool:
    """A line counts as billable iff ``type=="assistant"`` and message is dict.

    We deliberately accept records that lack ``message.usage`` or
    ``message.model`` — :func:`extract_usage` knows how to treat missing
    fields, and tracking "we *saw* an assistant turn but it had no usage"
    is what makes the confidence heuristic meaningful.
    """
    if line.get("type") != "assistant":
        return False
    return isinstance(line.get("message"), dict)


def parse_session(
    path: Path,
    *,
    byte_cap: int = _DEFAULT_BYTE_CAP,
    deep_parse_only: bool = False,
) -> tuple[ParsedSession, ImportReport]:
    """Parse a Claude Code session JSONL with full import-report accounting.

    Args:
        path: source ``<session-id>.jsonl``.
        byte_cap: maximum bytes to deep-parse. Lines past the cap are
            dropped and ``report.byte_cap_hit`` is set.
        deep_parse_only: when True, files whose total size already exceeds
            ``byte_cap`` are short-circuited — a stub ParsedSession (no
            events, no boundaries) is returned and
            ``report.deep_parse_only_skipped`` is set so callers can route
            the import to a metadata-only path.

    Returns:
        ``(parsed, report)`` — `parsed` carries the parsed events the
        importer must turn into ``claude.*`` events; `report` carries the
        spec §4.1 accounting (skips, byte-cap status, parsed total).
    """
    p = Path(path)
    session_id = p.stem
    start_ns = time.perf_counter_ns()

    report = ImportReport(source="claude-session", source_session_id=session_id)
    report.set_source_path(p)
    report.byte_cap_bytes = byte_cap
    # The CLI overrides byte_cap_source with the real provenance (flag/env);
    # default suits in-process callers and tests.
    report.byte_cap_source = "default"

    try:
        source_bytes = p.stat().st_size
    except OSError:
        source_bytes = 0
    report.source_bytes = source_bytes

    # Short-circuit: source larger than cap AND caller asked for deep-only.
    if source_bytes > byte_cap and deep_parse_only:
        report.deep_parse_only_skipped = True
        duration_ms = (time.perf_counter_ns() - start_ns) // 1_000_000
        report.finalize(int(duration_ms))
        stub = ParsedSession(
            session_id=session_id,
            path=p,
            started_at=None,
            ended_at=None,
        )
        return stub, report

    first_ts: str | None = None
    last_ts: str | None = None
    events: list[dict[str, Any]] = []
    line_count = 0
    first_user_text: str | None = None
    usage_records: list[dict[str, Any]] = []

    for line_number, byte_offset, raw_bytes in _iter_raw_lines(
        p, byte_cap, report
    ):
        # Per-line oversized guard *before* json.loads, so a 200 MiB line
        # never enters the JSON parser.
        if len(raw_bytes) > _LINE_CAP_BYTES:
            report.record_skip("line_too_large", line_number, byte_offset)
            continue

        try:
            obj = json.loads(raw_bytes)
        except json.JSONDecodeError:
            report.record_skip("json_decode", line_number, byte_offset)
            continue

        if not isinstance(obj, dict):
            # Non-object top-levels (lists, strings, …) aren't a Claude
            # event shape — treat as unsupported with the value's JSON type.
            type_label = type(obj).__name__
            report.record_skip(
                f"unsupported_type:{type_label}", line_number, byte_offset
            )
            continue

        line_type = obj.get("type")
        if isinstance(line_type, str) and line_type not in _KNOWN_CLAUDE_TYPES:
            report.record_skip(
                f"unsupported_type:{line_type}", line_number, byte_offset
            )
            continue

        # Supported line — record success and harvest fields.
        report.record_parsed()
        line_count += 1

        ts = obj.get("timestamp")
        if isinstance(ts, str):
            if first_ts is None:
                first_ts = ts
            last_ts = ts

        events.extend(_extract_tool_use(obj))

        if first_user_text is None:
            candidate = _extract_first_user_text(obj)
            if candidate is not None:
                first_user_text = candidate

        if _is_billable_assistant(obj):
            usage_records.append(obj)

    duration_ms = (time.perf_counter_ns() - start_ns) // 1_000_000
    report.finalize(int(duration_ms))

    parsed = ParsedSession(
        session_id=session_id,
        path=p,
        started_at=first_ts,
        ended_at=last_ts,
        events=events,
        line_count=line_count,
        first_user_message_text=first_user_text,
        usage_records=usage_records,
    )
    return parsed, report


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
