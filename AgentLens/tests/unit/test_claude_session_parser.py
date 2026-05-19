"""Unit tests for ``agentlens.store.claude_session`` (spec §4.2.5 + §4.1).

The parser is a pure locator/parser over Claude Code session JSONL files
that live under ``~/.claude/projects/<encoded>/<session-id>.jsonl``. The
parser:

* Locates sessions by id, by --latest, or enumerates them.
* Derives session boundaries (first/last line timestamp) for the
  ``command.started`` / ``command.finished`` events the importer emits.
* Extracts opaque ``claude.tool_use`` events from assistant tool_use blocks.
* Streams the source byte-by-byte (never read_text) and accounts every
  line into an :class:`ImportReport` — malformed/oversized/unsupported.
* Captures the first user-message text + every billable assistant record
  so task_16's importer can populate ``derived.display_title`` and the
  usage block on ``run.json``.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from agentlens.importers.report import ImportReport
from agentlens.store.claude_session import (
    ParsedSession,
    find_session,
    list_sessions,
    parse_session,
)


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _write_jsonl(path: Path, lines: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for ln in lines:
            f.write(json.dumps(ln) + "\n")


SAMPLE_LINES = [
    {
        "type": "user",
        "message": {"role": "user", "content": "hello"},
        "timestamp": "2026-05-19T10:00:00.000Z",
    },
    {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_abc",
                    "name": "Bash",
                    "input": {"command": "ls"},
                }
            ],
        },
        "timestamp": "2026-05-19T10:00:05.500Z",
    },
    {
        "type": "user",
        "message": {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "toolu_abc",
                    "content": "file1\nfile2",
                }
            ],
        },
        "timestamp": "2026-05-19T10:00:10.000Z",
    },
]


# ---------------------------------------------------------------------------
# Existing behaviour (boundaries, tool_use, malformed-line tolerance)
# ---------------------------------------------------------------------------


def test_parse_session_returns_boundaries_from_first_and_last(tmp_path: Path) -> None:
    sid = "abc-123"
    p = tmp_path / f"{sid}.jsonl"
    _write_jsonl(p, SAMPLE_LINES)

    parsed, _report = parse_session(p)
    assert isinstance(parsed, ParsedSession)
    assert parsed.session_id == sid
    assert parsed.started_at == "2026-05-19T10:00:00.000Z"
    assert parsed.ended_at == "2026-05-19T10:00:10.000Z"


def test_parse_session_extracts_tool_use_events(tmp_path: Path) -> None:
    sid = "session-1"
    p = tmp_path / f"{sid}.jsonl"
    _write_jsonl(p, SAMPLE_LINES)

    parsed, _report = parse_session(p)
    tool_events = [e for e in parsed.events if e["type"] == "claude.tool_use"]
    assert len(tool_events) == 1
    evt = tool_events[0]
    assert evt["payload"]["name"] == "Bash"
    assert evt["ts"] == "2026-05-19T10:00:05.500Z"


def test_parse_session_skips_malformed_lines(tmp_path: Path) -> None:
    sid = "session-bad"
    p = tmp_path / f"{sid}.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        f.write(json.dumps(SAMPLE_LINES[0]) + "\n")
        f.write("this-is-not-json\n")
        f.write(json.dumps(SAMPLE_LINES[2]) + "\n")

    parsed, report = parse_session(p)
    assert parsed.started_at == "2026-05-19T10:00:00.000Z"
    assert parsed.ended_at == "2026-05-19T10:00:10.000Z"
    assert all(e["type"] != "claude.tool_use" for e in parsed.events)
    assert report.skipped_malformed == 1
    assert report.first_error is not None
    assert report.first_error.reason == "json_decode"


# ---------------------------------------------------------------------------
# Locator (find_session / list_sessions) — unchanged
# ---------------------------------------------------------------------------


def test_find_session_resolves_id_under_home(tmp_path: Path) -> None:
    home = tmp_path / "home"
    sid = "deadbeef-1234"
    proj_a = home / ".claude" / "projects" / "-Users-foo-bar"
    _write_jsonl(proj_a / f"{sid}.jsonl", SAMPLE_LINES)
    proj_b = home / ".claude" / "projects" / "-Users-baz-qux"
    _write_jsonl(proj_b / "another-id.jsonl", SAMPLE_LINES)

    found = find_session(home, sid)
    assert found is not None
    assert found.name == f"{sid}.jsonl"
    assert found.parent.name == "-Users-foo-bar"


def test_find_session_returns_none_for_missing(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / ".claude" / "projects").mkdir(parents=True, exist_ok=True)
    assert find_session(home, "does-not-exist") is None


def test_list_sessions_enumerates_all_projects(tmp_path: Path) -> None:
    home = tmp_path / "home"
    proj_a = home / ".claude" / "projects" / "proj-a"
    proj_b = home / ".claude" / "projects" / "proj-b"
    _write_jsonl(proj_a / "s1.jsonl", SAMPLE_LINES)
    _write_jsonl(proj_a / "s2.jsonl", SAMPLE_LINES)
    _write_jsonl(proj_b / "s3.jsonl", SAMPLE_LINES)

    listed = list_sessions(home)
    names = sorted(p.name for p in listed)
    assert names == ["s1.jsonl", "s2.jsonl", "s3.jsonl"]


def test_list_sessions_latest_only_returns_newest_by_mtime(tmp_path: Path) -> None:
    home = tmp_path / "home"
    proj = home / ".claude" / "projects" / "proj-a"
    older = proj / "old.jsonl"
    newer = proj / "new.jsonl"
    _write_jsonl(older, SAMPLE_LINES)
    _write_jsonl(newer, SAMPLE_LINES)
    old_t = time.time() - 100
    new_t = time.time()
    os.utime(older, (old_t, old_t))
    os.utime(newer, (new_t, new_t))

    listed = list_sessions(home, latest_only=True)
    assert len(listed) == 1
    assert listed[0].name == "new.jsonl"


def test_list_sessions_filtered_by_project(tmp_path: Path) -> None:
    home = tmp_path / "home"
    proj_a = home / ".claude" / "projects" / "proj-a"
    proj_b = home / ".claude" / "projects" / "proj-b"
    _write_jsonl(proj_a / "sa.jsonl", SAMPLE_LINES)
    _write_jsonl(proj_b / "sb.jsonl", SAMPLE_LINES)

    listed = list_sessions(home, project="proj-a")
    names = [p.name for p in listed]
    assert names == ["sa.jsonl"]


# ---------------------------------------------------------------------------
# task_14 — tuple return + ImportReport plumbing
# ---------------------------------------------------------------------------


def test_parse_returns_tuple_with_report(tmp_path: Path) -> None:
    sid = "report-tuple"
    p = tmp_path / f"{sid}.jsonl"
    _write_jsonl(p, SAMPLE_LINES)

    result = parse_session(p)
    assert isinstance(result, tuple) and len(result) == 2
    parsed, report = result
    assert isinstance(parsed, ParsedSession)
    assert isinstance(report, ImportReport)
    assert report.source == "claude-session"
    assert report.source_session_id == sid
    assert report.parsed == 3
    assert report.total_scanned == 3
    assert report.analysis_state == "full"


def test_byte_cap_hit_stops_streaming(tmp_path: Path) -> None:
    """File with N+1 small lines + byte_cap < total triggers byte_cap_hit
    after exactly N lines."""
    sid = "bcap"
    p = tmp_path / f"{sid}.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    line = (
        json.dumps(
            {
                "type": "system",
                "timestamp": "2026-05-19T10:00:00.000Z",
                "payload": "x",
            }
        )
        + "\n"
    )
    line_bytes = len(line.encode("utf-8"))
    n = 4  # we want to keep N=4, then the 5th pushes over
    with p.open("wb") as f:
        for _ in range(n + 1):
            f.write(line.encode("utf-8"))
    # Cap exactly admits N lines, the (N+1)th pushes over.
    cap = line_bytes * n + (line_bytes // 2)  # < line_bytes*(n+1)
    parsed, report = parse_session(p, byte_cap=cap)
    assert report.byte_cap_hit is True
    assert report.parsed == n
    assert parsed.line_count == n
    assert report.analysis_state == "partial"


def test_oversized_line_skipped(tmp_path: Path) -> None:
    """A single line larger than 2 MiB is recorded as ``line_too_large``
    without invoking json.loads."""
    sid = "oversized"
    p = tmp_path / f"{sid}.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    # Small good line, then one ~3 MiB invalid line. The big line must NOT
    # be valid JSON either — but if line_too_large is checked first we never
    # call json.loads, so the counter must say "oversized" not "malformed".
    good = json.dumps(SAMPLE_LINES[0]) + "\n"
    huge = ("x" * (3 * 1024 * 1024)) + "\n"
    with p.open("wb") as f:
        f.write(good.encode("utf-8"))
        f.write(huge.encode("utf-8"))
    # Cap large enough to admit the oversized line for skip-classification.
    parsed, report = parse_session(p, byte_cap=10 * 1024 * 1024)
    assert report.skipped_oversized == 1
    assert report.skipped_malformed == 0
    assert report.parsed == 1
    assert parsed.line_count == 1


def test_malformed_line_skipped(tmp_path: Path) -> None:
    parsed, report = parse_session(FIXTURES / "claude-malformed-line.jsonl")
    assert report.skipped_malformed == 1
    assert report.first_error is not None
    assert report.first_error.reason == "json_decode"
    # 2 valid lines (user + assistant).
    assert report.parsed == 2
    assert parsed.line_count == 2


def test_first_user_message_extracted(tmp_path: Path) -> None:
    sid = "title"
    p = tmp_path / f"{sid}.jsonl"
    lines = [
        # System line first (must NOT win as user).
        {
            "type": "system",
            "timestamp": "2026-05-19T10:00:00.000Z",
            "subtype": "init",
        },
        # First user message.
        {
            "type": "user",
            "message": {"role": "user", "content": "hello world"},
            "timestamp": "2026-05-19T10:00:01.000Z",
        },
        # Subsequent user message — must NOT overwrite.
        {
            "type": "user",
            "message": {"role": "user", "content": "second"},
            "timestamp": "2026-05-19T10:00:02.000Z",
        },
    ]
    _write_jsonl(p, lines)
    parsed, _report = parse_session(p)
    assert parsed.first_user_message_text == "hello world"


def test_first_user_message_concatenates_text_blocks(tmp_path: Path) -> None:
    sid = "title-blocks"
    p = tmp_path / f"{sid}.jsonl"
    lines = [
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": [
                    {"type": "text", "text": "part-one"},
                    {"type": "text", "text": "part-two"},
                ],
            },
            "timestamp": "2026-05-19T10:00:00.000Z",
        },
    ]
    _write_jsonl(p, lines)
    parsed, _report = parse_session(p)
    assert parsed.first_user_message_text == "part-one\npart-two"


def test_usage_records_include_missing_usage(tmp_path: Path) -> None:
    sid = "usage"
    p = tmp_path / f"{sid}.jsonl"
    lines = [
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "a"}],
                "model": "claude-x",
                "usage": {"input_tokens": 10, "output_tokens": 5},
            },
            "timestamp": "2026-05-19T10:00:00.000Z",
        },
        {
            # Same shape but NO usage / NO model — still billable, must be
            # captured so confidence dilution is observable.
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "b"}],
            },
            "timestamp": "2026-05-19T10:00:01.000Z",
        },
    ]
    _write_jsonl(p, lines)
    parsed, _report = parse_session(p)
    assert len(parsed.usage_records) == 2


def test_deep_parse_only_skipped_when_oversized(tmp_path: Path) -> None:
    sid = "deep-skip"
    p = tmp_path / f"{sid}.jsonl"
    # Write any file with size > 64 bytes.
    p.write_bytes(b"x" * 256)
    parsed, report = parse_session(p, byte_cap=64, deep_parse_only=True)
    assert parsed.events == []
    assert parsed.line_count == 0
    assert report.deep_parse_only_skipped is True
    assert report.analysis_state == "skipped"


def test_unsupported_type_recorded(tmp_path: Path) -> None:
    sid = "unsupported"
    p = tmp_path / f"{sid}.jsonl"
    lines = [
        {"type": "user", "message": {"role": "user", "content": "k"}},
        {"type": "from_the_future", "payload": {"foo": 1}},
    ]
    _write_jsonl(p, lines)
    parsed, report = parse_session(p)
    assert report.skipped_unsupported_type == 1
    assert report.parsed == 1
    assert report.first_error is not None
    assert report.first_error.reason == "unsupported_type:from_the_future"
    assert parsed.line_count == 1
