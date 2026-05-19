"""Unit tests for ``agentlens.store.codex_session`` (spec §4.2.6).

Pure parser/locator over Codex rollout JSONL files stored under
``~/.codex/sessions/YYYY/MM/DD/rollout-<ISO>-<UUIDv7>.jsonl`` (live) and
``~/.codex/archived_sessions/rollout-<ISO>-<UUIDv7>.jsonl`` (archived).

The parser:

* Locates rollouts by id (across both trees) or enumerates them.
* Reads the first JSONL line as ``session_meta`` to extract the session
  id (UUIDv7), originator, cli_version, model_provider, cwd, and the
  ``source`` field which may be a bare string (e.g. ``"vscode"``) OR an
  object carrying ``subagent.thread_spawn.parent_thread_id``.
* Derives session boundaries from the first line's
  ``payload.timestamp`` and the last parseable line's ``timestamp``.
* Emits opaque ``codex.*`` events for assistant messages, tool uses,
  tool results, and reasoning lines (one event per rollout line).
* Skips malformed JSONL lines without raising.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from agentlens.store.codex_session import (
    ParsedCodexSession,
    find_rollout,
    list_rollouts,
    parse_rollout,
)


def _meta_line(
    session_id: str,
    *,
    originator: str = "Codex CLI",
    cli_version: str = "0.1.0",
    cwd: str = "/work",
    model_provider: str = "openai",
    source: object = "vscode",
    timestamp: str = "2026-05-19T10:00:00.000Z",
) -> dict:
    return {
        "type": "session_meta",
        "payload": {
            "id": session_id,
            "timestamp": timestamp,
            "cwd": cwd,
            "originator": originator,
            "cli_version": cli_version,
            "model_provider": model_provider,
            "source": source,
        },
    }


SAMPLE_BODY = [
    {
        "type": "message",
        "role": "user",
        "content": "hi",
        "timestamp": "2026-05-19T10:00:01.000Z",
    },
    {
        "type": "tool_use",
        "name": "shell",
        "id": "call_1",
        "input": {"cmd": "ls"},
        "timestamp": "2026-05-19T10:00:02.500Z",
    },
    {
        "type": "tool_result",
        "tool_use_id": "call_1",
        "output": "f1\nf2",
        "timestamp": "2026-05-19T10:00:03.000Z",
    },
    {
        "type": "reasoning",
        "summary": "think",
        "timestamp": "2026-05-19T10:00:04.000Z",
    },
]


def _write_rollout(path: Path, lines: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for ln in lines:
            f.write(json.dumps(ln) + "\n")


def _rollout_filename(session_id: str, iso: str = "2026-05-19T10-00-00") -> str:
    return f"rollout-{iso}-{session_id}.jsonl"


def test_parse_rollout_extracts_session_meta(tmp_path: Path) -> None:
    sid = "01923456-7abc-7def-8123-456789abcdef"
    p = tmp_path / _rollout_filename(sid)
    _write_rollout(p, [_meta_line(sid), *SAMPLE_BODY])

    parsed = parse_rollout(p)
    assert isinstance(parsed, ParsedCodexSession)
    assert parsed.session_id == sid
    assert parsed.originator == "Codex CLI"
    assert parsed.cli_version == "0.1.0"
    assert parsed.cwd == "/work"
    assert parsed.model_provider == "openai"
    assert parsed.source == "vscode"
    assert parsed.parent_thread_id is None


def test_parse_rollout_detects_subagent_parent(tmp_path: Path) -> None:
    sid = "01923456-7abc-7def-8123-aaaaaaaaaaaa"
    parent_id = "01923456-7abc-7def-8123-bbbbbbbbbbbb"
    source = {
        "subagent": {
            "thread_spawn": {
                "parent_thread_id": parent_id,
                "depth": 1,
                "agent_role": "reviewer",
            }
        }
    }
    p = tmp_path / _rollout_filename(sid)
    _write_rollout(p, [_meta_line(sid, source=source), *SAMPLE_BODY])

    parsed = parse_rollout(p)
    assert parsed.parent_thread_id == parent_id
    assert isinstance(parsed.source, dict)


def test_parse_rollout_derives_boundaries(tmp_path: Path) -> None:
    sid = "01923456-7abc-7def-8123-cccccccccccc"
    p = tmp_path / _rollout_filename(sid)
    _write_rollout(p, [_meta_line(sid), *SAMPLE_BODY])

    parsed = parse_rollout(p)
    # started_at is the session_meta timestamp
    assert parsed.started_at == "2026-05-19T10:00:00.000Z"
    # ended_at is the last line's timestamp
    assert parsed.ended_at == "2026-05-19T10:00:04.000Z"


def test_parse_rollout_emits_codex_events(tmp_path: Path) -> None:
    sid = "01923456-7abc-7def-8123-dddddddddddd"
    p = tmp_path / _rollout_filename(sid)
    _write_rollout(p, [_meta_line(sid), *SAMPLE_BODY])

    parsed = parse_rollout(p)
    types = [e["type"] for e in parsed.events]
    assert "codex.message" in types
    assert "codex.tool_use" in types
    assert "codex.tool_result" in types
    assert "codex.reasoning" in types
    # session_meta should NOT be re-emitted as a codex.* event.
    assert "codex.session_meta" not in types


def test_parse_rollout_skips_malformed_lines(tmp_path: Path) -> None:
    sid = "01923456-7abc-7def-8123-eeeeeeeeeeee"
    p = tmp_path / _rollout_filename(sid)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        f.write(json.dumps(_meta_line(sid)) + "\n")
        f.write("not-json\n")
        f.write(json.dumps(SAMPLE_BODY[-1]) + "\n")

    parsed = parse_rollout(p)
    # session_meta still parsed; last good body line still ended boundary.
    assert parsed.session_id == sid
    assert parsed.ended_at == "2026-05-19T10:00:04.000Z"


def test_find_rollout_active_tree(tmp_path: Path) -> None:
    home = tmp_path / "home"
    sid = "01923456-7abc-7def-8123-111111111111"
    p = home / ".codex" / "sessions" / "2026" / "05" / "19" / _rollout_filename(sid)
    _write_rollout(p, [_meta_line(sid)])

    found = find_rollout(home, sid)
    assert found is not None
    assert found.name.endswith(f"{sid}.jsonl")
    assert "sessions" in found.parts


def test_find_rollout_archived_only_when_flag(tmp_path: Path) -> None:
    home = tmp_path / "home"
    sid = "01923456-7abc-7def-8123-222222222222"
    archived = home / ".codex" / "archived_sessions" / _rollout_filename(sid)
    _write_rollout(archived, [_meta_line(sid)])

    # Without --include-archived (default False), the archive tree is ignored.
    assert find_rollout(home, sid, include_archived=False) is None
    # Opting in finds it.
    found = find_rollout(home, sid, include_archived=True)
    assert found is not None
    assert "archived_sessions" in found.parts


def test_find_rollout_prefers_active_when_both_trees_have_same_id(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    sid = "01923456-7abc-7def-8123-333333333333"
    active = (
        home / ".codex" / "sessions" / "2026" / "05" / "19"
        / _rollout_filename(sid)
    )
    archived = home / ".codex" / "archived_sessions" / _rollout_filename(sid)
    _write_rollout(active, [_meta_line(sid)])
    _write_rollout(archived, [_meta_line(sid)])

    found = find_rollout(home, sid, include_archived=True)
    assert found is not None
    # Active wins.
    assert "sessions" in found.parts and "archived_sessions" not in found.parts


def test_list_rollouts_latest_picks_newest_by_mtime(tmp_path: Path) -> None:
    home = tmp_path / "home"
    older_id = "01923456-7abc-7def-8123-444444444444"
    newer_id = "01923456-7abc-7def-8123-555555555555"
    older = (
        home / ".codex" / "sessions" / "2026" / "05" / "18"
        / _rollout_filename(older_id, iso="2026-05-18T10-00-00")
    )
    newer = (
        home / ".codex" / "sessions" / "2026" / "05" / "19"
        / _rollout_filename(newer_id)
    )
    _write_rollout(older, [_meta_line(older_id)])
    _write_rollout(newer, [_meta_line(newer_id)])
    old_t = time.time() - 100
    new_t = time.time()
    os.utime(older, (old_t, old_t))
    os.utime(newer, (new_t, new_t))

    listed = list_rollouts(home, latest_only=True)
    assert len(listed) == 1
    assert listed[0].name.endswith(f"{newer_id}.jsonl")


def test_list_rollouts_since_filters_by_mtime(tmp_path: Path) -> None:
    home = tmp_path / "home"
    old_id = "01923456-7abc-7def-8123-666666666666"
    new_id = "01923456-7abc-7def-8123-777777777777"
    old = (
        home / ".codex" / "sessions" / "2026" / "05" / "18"
        / _rollout_filename(old_id, iso="2026-05-18T10-00-00")
    )
    new = (
        home / ".codex" / "sessions" / "2026" / "05" / "19"
        / _rollout_filename(new_id)
    )
    _write_rollout(old, [_meta_line(old_id)])
    _write_rollout(new, [_meta_line(new_id)])
    old_t = time.time() - 86400
    new_t = time.time()
    os.utime(old, (old_t, old_t))
    os.utime(new, (new_t, new_t))

    cutoff = time.time() - 3600  # 1h ago
    listed = list_rollouts(home, since_epoch=cutoff)
    names = [p.name for p in listed]
    assert any(new_id in n for n in names)
    assert all(old_id not in n for n in names)


def test_list_rollouts_includes_archived_when_flag(tmp_path: Path) -> None:
    home = tmp_path / "home"
    active_id = "01923456-7abc-7def-8123-888888888888"
    archived_id = "01923456-7abc-7def-8123-999999999999"
    active = (
        home / ".codex" / "sessions" / "2026" / "05" / "19"
        / _rollout_filename(active_id)
    )
    archived = (
        home / ".codex" / "archived_sessions" / _rollout_filename(archived_id)
    )
    _write_rollout(active, [_meta_line(active_id)])
    _write_rollout(archived, [_meta_line(archived_id)])

    only_active = list_rollouts(home, include_archived=False)
    names = [p.name for p in only_active]
    assert any(active_id in n for n in names)
    assert all(archived_id not in n for n in names)

    both = list_rollouts(home, include_archived=True)
    names = [p.name for p in both]
    assert any(active_id in n for n in names)
    assert any(archived_id in n for n in names)
