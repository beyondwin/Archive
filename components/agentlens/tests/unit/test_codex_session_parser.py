"""Unit tests for ``agentlens.store.codex_session`` (spec §4.2.6 + §4.1).

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
* Streams the source byte-by-byte (never read_text) and accounts every
  line into an :class:`ImportReport` — malformed/oversized/unsupported.
* Captures the first user-message text + every billable Codex record
  (records with ``payload.info``) so task_17's importer can populate
  ``derived.display_title`` and the usage block on ``run.json``.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from agentlens.importers.report import ImportReport
from agentlens.store.codex_session import (
    ParsedCodexSession,
    find_rollout,
    list_rollouts,
    parse_rollout,
)


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


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


# ---------------------------------------------------------------------------
# Existing behaviour (session-meta + tool events + boundaries + malformed)
# ---------------------------------------------------------------------------


def test_parse_rollout_extracts_session_meta(tmp_path: Path) -> None:
    sid = "01923456-7abc-7def-8123-456789abcdef"
    p = tmp_path / _rollout_filename(sid)
    _write_rollout(p, [_meta_line(sid), *SAMPLE_BODY])

    parsed, _report = parse_rollout(p)
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

    parsed, _report = parse_rollout(p)
    assert parsed.parent_thread_id == parent_id
    assert isinstance(parsed.source, dict)


def test_parse_rollout_derives_boundaries(tmp_path: Path) -> None:
    sid = "01923456-7abc-7def-8123-cccccccccccc"
    p = tmp_path / _rollout_filename(sid)
    _write_rollout(p, [_meta_line(sid), *SAMPLE_BODY])

    parsed, _report = parse_rollout(p)
    # started_at is the session_meta timestamp
    assert parsed.started_at == "2026-05-19T10:00:00.000Z"
    # ended_at is the last line's timestamp
    assert parsed.ended_at == "2026-05-19T10:00:04.000Z"


def test_parse_rollout_emits_codex_events(tmp_path: Path) -> None:
    sid = "01923456-7abc-7def-8123-dddddddddddd"
    p = tmp_path / _rollout_filename(sid)
    _write_rollout(p, [_meta_line(sid), *SAMPLE_BODY])

    parsed, _report = parse_rollout(p)
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

    parsed, report = parse_rollout(p)
    assert parsed.session_id == sid
    assert parsed.ended_at == "2026-05-19T10:00:04.000Z"
    assert report.skipped_malformed == 1
    assert report.first_error is not None
    assert report.first_error.reason == "json_decode"


# ---------------------------------------------------------------------------
# Locator (find_rollout / list_rollouts) — unchanged
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# task_15 — tuple return + ImportReport plumbing
# ---------------------------------------------------------------------------


def test_parse_returns_tuple_with_report(tmp_path: Path) -> None:
    sid = "01923456-7abc-7def-8123-0a0a0a0a0a0a"
    p = tmp_path / _rollout_filename(sid)
    _write_rollout(p, [_meta_line(sid), *SAMPLE_BODY])

    result = parse_rollout(p)
    assert isinstance(result, tuple) and len(result) == 2
    parsed, report = result
    assert isinstance(parsed, ParsedCodexSession)
    assert isinstance(report, ImportReport)
    assert report.source == "codex-rollout"
    assert report.source_session_id == sid
    # 1 session_meta + 4 body lines all parseable.
    assert report.parsed == 5
    assert report.total_scanned == 5
    assert report.analysis_state == "full"


def test_byte_cap_hit_stops_streaming(tmp_path: Path) -> None:
    """File with N+1 small lines + byte_cap < total triggers byte_cap_hit
    after exactly N lines."""
    sid = "01923456-7abc-7def-8123-0b0b0b0b0b0b"
    p = tmp_path / _rollout_filename(sid)
    p.parent.mkdir(parents=True, exist_ok=True)
    # Make each line a `turn_context` so it's in the allowlist.
    line = (
        json.dumps(
            {
                "type": "turn_context",
                "timestamp": "2026-05-19T10:00:00.000Z",
                "payload": {"info": {"model": "gpt-5"}},
            }
        )
        + "\n"
    )
    line_bytes = len(line.encode("utf-8"))
    n = 4
    with p.open("wb") as f:
        for _ in range(n + 1):
            f.write(line.encode("utf-8"))
    cap = line_bytes * n + (line_bytes // 2)  # < line_bytes*(n+1)
    parsed, report = parse_rollout(p, byte_cap=cap)
    assert report.byte_cap_hit is True
    assert report.parsed == n
    assert parsed.line_count == n
    assert report.analysis_state == "partial"


def test_oversized_line_skipped(tmp_path: Path) -> None:
    """A single line larger than 2 MiB is recorded as ``line_too_large``
    without invoking json.loads — fixture exercises the same code path."""
    parsed, report = parse_rollout(
        FIXTURES / "codex-oversized-line.jsonl",
        byte_cap=10 * 1024 * 1024,
    )
    assert report.skipped_oversized == 1
    assert report.skipped_malformed == 0
    # 1 session_meta + 1 trailing user message survived; the middle line is
    # the oversized one.
    assert report.parsed == 2
    assert parsed.line_count == 2


def test_malformed_line_records_first_error(tmp_path: Path) -> None:
    sid = "01923456-7abc-7def-8123-0c0c0c0c0c0c"
    p = tmp_path / _rollout_filename(sid)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        f.write(json.dumps(_meta_line(sid)) + "\n")
        f.write("this-is-not-json\n")
        f.write(json.dumps(SAMPLE_BODY[0]) + "\n")

    parsed, report = parse_rollout(p)
    assert report.skipped_malformed == 1
    assert report.first_error is not None
    assert report.first_error.reason == "json_decode"
    # 1 meta + 1 valid body line.
    assert report.parsed == 2
    assert parsed.line_count == 2


def test_unsupported_type_recorded(tmp_path: Path) -> None:
    sid = "01923456-7abc-7def-8123-0d0d0d0d0d0d"
    p = tmp_path / _rollout_filename(sid)
    _write_rollout(
        p,
        [
            _meta_line(sid),
            {
                "type": "from_the_future",
                "payload": {"foo": 1},
                "timestamp": "2026-05-19T10:00:05.000Z",
            },
        ],
    )
    parsed, report = parse_rollout(p)
    assert report.skipped_unsupported_type == 1
    # 1 meta parsed.
    assert report.parsed == 1
    assert parsed.line_count == 1
    assert report.first_error is not None
    assert report.first_error.reason == "unsupported_type:from_the_future"


def test_known_user_assistant_lines_are_not_unsupported(tmp_path: Path) -> None:
    """Per E11: normal vendor lines must NOT inflate `skipped_unsupported_type`."""
    sid = "01923456-7abc-7def-8123-0e0e0e0e0e0e"
    p = tmp_path / _rollout_filename(sid)
    _write_rollout(p, [_meta_line(sid), *SAMPLE_BODY])
    _parsed, report = parse_rollout(p)
    assert report.skipped_unsupported_type == 0


def test_deep_parse_only_skipped_when_oversized(tmp_path: Path) -> None:
    sid = "01923456-7abc-7def-8123-0f0f0f0f0f0f"
    p = tmp_path / _rollout_filename(sid)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x" * 256)
    parsed, report = parse_rollout(p, byte_cap=64, deep_parse_only=True)
    assert parsed.events == []
    assert parsed.line_count == 0
    assert report.deep_parse_only_skipped is True
    assert report.analysis_state == "skipped"


# ---------------------------------------------------------------------------
# task_15 — first user message + usage records
# ---------------------------------------------------------------------------


def test_first_user_message_top_level_shape(tmp_path: Path) -> None:
    sid = "01923456-7abc-7def-8123-101010101010"
    p = tmp_path / _rollout_filename(sid)
    _write_rollout(
        p,
        [
            _meta_line(sid),
            {
                "type": "message",
                "role": "user",
                "content": "first prompt",
                "timestamp": "2026-05-19T10:00:01.000Z",
            },
            {
                "type": "message",
                "role": "user",
                "content": "second prompt — must NOT overwrite",
                "timestamp": "2026-05-19T10:00:02.000Z",
            },
        ],
    )
    parsed, _report = parse_rollout(p)
    assert parsed.first_user_message_text == "first prompt"


def test_first_user_message_payload_shape(tmp_path: Path) -> None:
    """Codex sometimes nests message fields under ``payload``."""
    sid = "01923456-7abc-7def-8123-111011101110"
    p = tmp_path / _rollout_filename(sid)
    _write_rollout(
        p,
        [
            _meta_line(sid),
            {
                "type": "message",
                "payload": {"role": "user", "content": "nested prompt"},
                "timestamp": "2026-05-19T10:00:01.000Z",
            },
        ],
    )
    parsed, _report = parse_rollout(p)
    assert parsed.first_user_message_text == "nested prompt"


def test_first_user_message_concatenates_text_blocks(tmp_path: Path) -> None:
    sid = "01923456-7abc-7def-8123-121212121212"
    p = tmp_path / _rollout_filename(sid)
    _write_rollout(
        p,
        [
            _meta_line(sid),
            {
                "type": "message",
                "role": "user",
                "content": [
                    {"type": "text", "text": "part-one"},
                    {"type": "input_text", "text": "part-two"},
                ],
                "timestamp": "2026-05-19T10:00:01.000Z",
            },
        ],
    )
    parsed, _report = parse_rollout(p)
    assert parsed.first_user_message_text == "part-one\npart-two"


def test_first_user_message_ignores_assistant_role(tmp_path: Path) -> None:
    sid = "01923456-7abc-7def-8123-131313131313"
    p = tmp_path / _rollout_filename(sid)
    _write_rollout(
        p,
        [
            _meta_line(sid),
            {
                "type": "message",
                "role": "assistant",
                "content": "assistant first turn",
                "timestamp": "2026-05-19T10:00:01.000Z",
            },
            {
                "type": "message",
                "role": "user",
                "content": "real first user",
                "timestamp": "2026-05-19T10:00:02.000Z",
            },
        ],
    )
    parsed, _report = parse_rollout(p)
    assert parsed.first_user_message_text == "real first user"


def test_usage_records_include_missing_tokens(tmp_path: Path) -> None:
    """Billable records lacking ``payload.info.tokens`` are still captured."""
    sid = "01923456-7abc-7def-8123-141414141414"
    p = tmp_path / _rollout_filename(sid)
    _write_rollout(
        p,
        [
            _meta_line(sid),
            # With tokens.
            {
                "type": "turn_context",
                "payload": {
                    "info": {
                        "model": "gpt-5",
                        "tokens": {
                            "input_tokens": 100,
                            "output_tokens": 50,
                            "cache_creation_tokens": 0,
                            "cache_read_tokens": 10,
                            "reasoning_tokens": 5,
                        },
                    }
                },
                "timestamp": "2026-05-19T10:00:01.000Z",
            },
            # Without tokens — still billable, must still be captured.
            {
                "type": "turn_context",
                "payload": {"info": {"model": "gpt-5"}},
                "timestamp": "2026-05-19T10:00:02.000Z",
            },
        ],
    )
    parsed, _report = parse_rollout(p)
    assert len(parsed.usage_records) == 2
    # Raw dicts are preserved verbatim.
    assert parsed.usage_records[0]["payload"]["info"]["tokens"]["input_tokens"] == 100
    assert "tokens" not in parsed.usage_records[1]["payload"]["info"]


def test_usage_records_do_not_include_non_billable_lines(tmp_path: Path) -> None:
    """Plain ``message``/``tool_use`` lines without ``payload.info`` are not
    swept into ``usage_records`` (they have no token data)."""
    sid = "01923456-7abc-7def-8123-151515151515"
    p = tmp_path / _rollout_filename(sid)
    _write_rollout(p, [_meta_line(sid), *SAMPLE_BODY])
    parsed, _report = parse_rollout(p)
    assert parsed.usage_records == []
