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

Defensive parsing: malformed/oversized lines and lines past the byte cap
are tracked on the returned :class:`ImportReport` rather than raised. The
session id comes from the filename UUID suffix (and is cross-checked
against ``payload.id`` for ``session_meta``).

Streaming model: the parser opens the source in ``"rb"`` mode and iterates
line-by-line. We never call ``path.read_text()`` — large rollouts must not
balloon to whole-file allocations.

Public API:
    ParsedCodexSession                                       (dataclass)
    parse_rollout(path, *, byte_cap=64MiB, deep_parse_only=False)
        -> tuple[ParsedCodexSession, ImportReport]
    find_rollout(home, session_id, include_archived=False) -> Path | None
    list_rollouts(home, latest_only=False, since_epoch=None,
                  include_archived=False) -> list[Path]
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator

from ..importers.report import ImportReport


# Matches ``rollout-<ISO>-<UUIDv7>.jsonl`` and captures the UUIDv7.
# UUID is any 8-4-4-4-12 hex group; we intentionally don't enforce v7 here
# so test fixtures can use simpler synthetic ids if needed.
_ROLLOUT_RE = re.compile(
    r"^rollout-.+-([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\.jsonl$"
)


# Per-line cap (2 MiB). Lines longer than this are skipped without
# attempting json.loads — pathological vendor lines must not OOM the parser.
_LINE_CAP_BYTES = 2 * 1024 * 1024

# Default whole-file cap (64 MiB). Matches the spec §4.1 default; callers
# may pass a smaller cap via ``--byte-cap`` / ``AGENTLENS_IMPORT_BYTE_CAP``.
_DEFAULT_BYTE_CAP = 64 * 1024 * 1024

# Vendor allowlist — only record `unsupported_type:<x>` for lines outside
# this set. Adding a type here means "the parser understands this shape".
# We include both ``tool_use`` (used by older rollouts and fixtures) and
# ``tool_call`` (newer name) defensively so neither inflates the unsupported
# counter on real-world data.
_KNOWN_CODEX_TYPES: frozenset[str] = frozenset(
    {
        "session_meta",
        "message",
        "tool_use",
        "tool_call",
        "tool_result",
        "reasoning",
        "turn_context",
        "event_msg",
        "response_item",
        "session_end",
    }
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
        first_user_message_text: text from the first user message in the
            rollout (``None`` if no user message seen).
        usage_records: raw line dicts for every billable Codex record
            (``turn_context``/``event_msg``/``response_item`` carrying
            ``payload.info``), preserved verbatim so :func:`extract_usage`
            can aggregate.
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
            if line_start + line_len > byte_cap:
                report.record_byte_cap_hit()
                return
            running_offset += line_len
            stripped = raw.rstrip(b"\r\n")
            if not stripped:
                continue
            yield line_number, line_start, stripped


def _session_id_from_filename(path: Path) -> str:
    """Return the UUID suffix of a rollout filename, or the stem if no match."""
    m = _ROLLOUT_RE.match(path.name)
    if m:
        return m.group(1)
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
    string ``ts``) — but they still count as ``parsed`` for the report.
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
    payload = {k: v for k, v in line.items() if k not in ("type", "timestamp")}
    return {"type": event_type, "ts": ts, "payload": payload}


def _extract_first_user_text(line: dict[str, Any]) -> str | None:
    """Return text from a Codex user-message line, or ``None``.

    Codex messages may appear in two shapes:
      * Top-level: ``{"type":"message","role":"user","content":...}``
      * Nested: ``{"type":"message","payload":{"role":"user","content":...}}``

    ``content`` may be a string OR a list of content blocks; only blocks
    with ``type=="text"`` (or ``type=="input_text"``) contribute, mirroring
    the Claude analog. Returns ``None`` if the line isn't a user message
    or no text content is present.
    """
    if line.get("type") != "message":
        return None
    # Prefer top-level role/content; fall back to payload.* for newer rollouts.
    role = line.get("role")
    content: Any = line.get("content")
    if role is None or content is None:
        payload = line.get("payload")
        if isinstance(payload, dict):
            if role is None:
                role = payload.get("role")
            if content is None:
                content = payload.get("content")
    if role != "user":
        return None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype not in ("text", "input_text"):
                continue
            text = block.get("text")
            if isinstance(text, str):
                parts.append(text)
        return "\n".join(parts) if parts else None
    return None


def _is_billable_codex(line: dict[str, Any]) -> bool:
    """A line counts as billable iff it carries ``payload.info`` shape.

    Codex stores token usage on records whose ``payload.info`` is a dict
    (e.g. ``turn_context``, ``event_msg``, ``response_item``). We deliberately
    accept records whose ``payload.info.tokens`` is missing — the
    confidence heuristic in :func:`extract_usage` depends on seeing
    "billable record without tokens" cases.
    """
    payload = line.get("payload")
    if not isinstance(payload, dict):
        return False
    return isinstance(payload.get("info"), dict)


def parse_rollout(
    path: Path,
    *,
    byte_cap: int = _DEFAULT_BYTE_CAP,
    deep_parse_only: bool = False,
) -> tuple[ParsedCodexSession, ImportReport]:
    """Parse a Codex rollout JSONL into ``(parsed, report)``.

    Args:
        path: source ``rollout-<ISO>-<UUIDv7>.jsonl``.
        byte_cap: maximum bytes to deep-parse. Lines past the cap are
            dropped and ``report.byte_cap_hit`` is set.
        deep_parse_only: when True, files whose total size already exceeds
            ``byte_cap`` are short-circuited — a stub ParsedCodexSession
            (no events, no boundaries) is returned and
            ``report.deep_parse_only_skipped`` is set so callers can route
            the import to a metadata-only path.

    Returns:
        ``(parsed, report)`` — `parsed` carries the events the importer
        must turn into ``codex.*`` events; `report` carries the spec §4.1
        accounting (skips, byte-cap status, parsed total).
    """
    p = Path(path)
    session_id = _session_id_from_filename(p)
    start_ns = time.perf_counter_ns()

    report = ImportReport(source="codex-rollout", source_session_id=session_id)
    report.set_source_path(p)
    report.byte_cap_bytes = byte_cap
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
        stub = ParsedCodexSession(
            session_id=session_id,
            path=p,
            originator=None,
            cli_version=None,
            cwd=None,
            model_provider=None,
            source=None,
            parent_thread_id=None,
            started_at=None,
            ended_at=None,
        )
        return stub, report

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
    first_user_text: str | None = None
    usage_records: list[dict[str, Any]] = []

    for line_number, byte_offset, raw_bytes in _iter_raw_lines(
        p, byte_cap, report
    ):
        # Per-line oversized guard *before* json.loads.
        if len(raw_bytes) > _LINE_CAP_BYTES:
            report.record_skip("line_too_large", line_number, byte_offset)
            continue

        try:
            obj = json.loads(raw_bytes)
        except json.JSONDecodeError:
            report.record_skip("json_decode", line_number, byte_offset)
            continue

        if not isinstance(obj, dict):
            type_label = type(obj).__name__
            report.record_skip(
                f"unsupported_type:{type_label}", line_number, byte_offset
            )
            continue

        raw_type = obj.get("type")
        if isinstance(raw_type, str) and raw_type not in _KNOWN_CODEX_TYPES:
            report.record_skip(
                f"unsupported_type:{raw_type}", line_number, byte_offset
            )
            continue

        # Supported line — count it before any per-shape handling, so even
        # known-type lines without ``timestamp`` (which yield no event)
        # still inflate ``parsed`` rather than disappear from accounting.
        report.record_parsed()
        line_count += 1

        # Session meta handling — preserve existing behaviour: pull
        # originator/cli_version/cwd/model_provider/source plus boundary
        # start. Do NOT re-emit as a codex.session_meta event.
        if not saw_meta and raw_type == "session_meta":
            saw_meta = True
            payload = obj.get("payload")
            if isinstance(payload, dict):
                pid = payload.get("id")
                if isinstance(pid, str) and pid:
                    session_id = pid
                    # Sync the report's session id label too.
                    report.source_session_id = pid
                    report.set_source_path(p)
                orig_raw = payload.get("originator")
                originator = orig_raw if isinstance(orig_raw, str) else None
                cli_raw = payload.get("cli_version")
                cli_version = cli_raw if isinstance(cli_raw, str) else None
                cwd_raw = payload.get("cwd")
                cwd = cwd_raw if isinstance(cwd_raw, str) else None
                mp_raw = payload.get("model_provider")
                model_provider = mp_raw if isinstance(mp_raw, str) else None
                source = payload.get("source")
                parent_thread_id = _extract_parent_thread_id(source)
                ts = payload.get("timestamp")
                if isinstance(ts, str):
                    started_at = ts
            continue

        # Body line — track latest timestamp + maybe emit codex.* event.
        ts = obj.get("timestamp")
        if isinstance(ts, str):
            ended_at = ts
        evt = _line_to_codex_event(obj)
        if evt is not None:
            events.append(evt)

        # First user message extraction.
        if first_user_text is None:
            candidate = _extract_first_user_text(obj)
            if candidate is not None:
                first_user_text = candidate

        # Usage record capture.
        if _is_billable_codex(obj):
            usage_records.append(obj)

    if ended_at is None:
        ended_at = started_at

    duration_ms = (time.perf_counter_ns() - start_ns) // 1_000_000
    report.finalize(int(duration_ms))

    parsed = ParsedCodexSession(
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
        first_user_message_text=first_user_text,
        usage_records=usage_records,
    )
    return parsed, report


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
