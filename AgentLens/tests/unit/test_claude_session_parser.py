"""Unit tests for ``agentlens.store.claude_session`` (spec §4.2.5).

The parser is a pure locator/parser over Claude Code session JSONL files
that live under ``~/.claude/projects/<encoded>/<session-id>.jsonl``. The
parser:

* Locates sessions by id, by --latest, or enumerates them.
* Derives session boundaries (first/last line timestamp) for the
  ``command.started`` / ``command.finished`` events the importer emits.
* Extracts opaque ``claude.tool_use`` events from assistant tool_use blocks.
* Skips malformed JSONL lines without raising.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from agentlens.store.claude_session import (
    ParsedSession,
    find_session,
    list_sessions,
    parse_session,
)


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


def test_parse_session_returns_boundaries_from_first_and_last(tmp_path: Path) -> None:
    sid = "abc-123"
    p = tmp_path / f"{sid}.jsonl"
    _write_jsonl(p, SAMPLE_LINES)

    parsed = parse_session(p)
    assert isinstance(parsed, ParsedSession)
    assert parsed.session_id == sid
    assert parsed.started_at == "2026-05-19T10:00:00.000Z"
    assert parsed.ended_at == "2026-05-19T10:00:10.000Z"


def test_parse_session_extracts_tool_use_events(tmp_path: Path) -> None:
    sid = "session-1"
    p = tmp_path / f"{sid}.jsonl"
    _write_jsonl(p, SAMPLE_LINES)

    parsed = parse_session(p)
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

    parsed = parse_session(p)
    # First and last good lines define boundaries.
    assert parsed.started_at == "2026-05-19T10:00:00.000Z"
    assert parsed.ended_at == "2026-05-19T10:00:10.000Z"
    # No exceptions raised, no tool_use events since assistant line was bad.
    assert all(e["type"] != "claude.tool_use" for e in parsed.events)


def test_find_session_resolves_id_under_home(tmp_path: Path) -> None:
    home = tmp_path / "home"
    sid = "deadbeef-1234"
    proj_a = home / ".claude" / "projects" / "-Users-foo-bar"
    _write_jsonl(proj_a / f"{sid}.jsonl", SAMPLE_LINES)
    # An unrelated session in another project.
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
    # Force mtime difference deterministically.
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
