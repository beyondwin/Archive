"""Integration tests for ``agentlens import claude-session`` (spec §4.2.5).

The importer locates a Claude Code session JSONL under
``~/.claude/projects/<encoded>/<session-id>.jsonl``, materialises a
``capture`` run with the transcript copied into
``artifacts/transcripts/<session-id>.jsonl``, and tags the run.json with
``input.import_key="claude-session:<session-id>"`` for idempotency.

The tests drive the Typer CLI end-to-end against a tmp ``HOME`` and a
tmp ``AGENTLENS_HOME``.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agentlens.cli import app


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture()
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    home = tmp_path / "fake_home"
    home.mkdir()
    al_home = tmp_path / "agentlens_home"
    al_home.mkdir()
    ws = tmp_path / "workspace"
    ws.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("AGENTLENS_HOME", str(al_home))
    monkeypatch.chdir(ws)
    return {"home": home, "agentlens_home": al_home, "workspace": ws}


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
                    "content": "file1",
                }
            ],
        },
        "timestamp": "2026-05-19T10:00:10.000Z",
    },
]


def _seed_session(
    home: Path, session_id: str, project: str = "-Users-foo-bar"
) -> Path:
    p = home / ".claude" / "projects" / project / f"{session_id}.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        for ln in SAMPLE_LINES:
            f.write(json.dumps(ln) + "\n")
    return p


def _find_capture_run_dir(al_home: Path, session_id: str) -> Path:
    """Scan ``<AGENTLENS_HOME>/runs/*/`` for the run whose run.json's
    ``input.import_key`` matches the session.
    """
    runs_root = al_home / "runs"
    for ws_dir in runs_root.iterdir():
        if not ws_dir.is_dir():
            continue
        for run_dir in ws_dir.iterdir():
            run_json = run_dir / "run.json"
            if not run_json.is_file():
                continue
            doc = json.loads(run_json.read_text(encoding="utf-8"))
            if (
                doc.get("input", {}).get("import_key")
                == f"claude-session:{session_id}"
            ):
                return run_dir
    raise AssertionError(
        f"no run.json found with import_key claude-session:{session_id}"
    )


def _all_run_dirs(al_home: Path) -> list[Path]:
    runs_root = al_home / "runs"
    if not runs_root.is_dir():
        return []
    out: list[Path] = []
    for ws_dir in runs_root.iterdir():
        if not ws_dir.is_dir():
            continue
        for run_dir in ws_dir.iterdir():
            if (run_dir / "run.json").is_file():
                out.append(run_dir)
    return out


def test_import_by_id_writes_capture_run(runner: CliRunner, env) -> None:
    sid = "abc-1234"
    src = _seed_session(env["home"], sid)

    result = runner.invoke(app, ["import", "claude-session", "--id", sid])
    assert result.exit_code == 0, (result.stdout, result.stderr)

    run_dir = _find_capture_run_dir(env["agentlens_home"], sid)
    doc = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert doc["run_kind"] == "capture"
    assert doc["agent"]["name"] == "claude_code"
    assert doc["recording"]["has_transcript"] is True
    assert doc["recording"]["transcript_source"] == "claude-session-jsonl"
    assert doc["input"]["import_key"] == f"claude-session:{sid}"

    transcript = run_dir / "artifacts" / "transcripts" / f"{sid}.jsonl"
    assert transcript.is_file()
    assert transcript.read_bytes() == src.read_bytes()

    # No root-level transcript.jsonl
    assert not (run_dir / "transcript.jsonl").exists()


def test_import_emits_command_and_tool_use_events(
    runner: CliRunner, env
) -> None:
    sid = "session-events"
    _seed_session(env["home"], sid)

    result = runner.invoke(app, ["import", "claude-session", "--id", sid])
    assert result.exit_code == 0, (result.stdout, result.stderr)

    run_dir = _find_capture_run_dir(env["agentlens_home"], sid)
    events_path = run_dir / "events.jsonl"
    assert events_path.is_file()
    events = [
        json.loads(ln)
        for ln in events_path.read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    types = [e["type"] for e in events]
    assert "command.started" in types
    assert "command.finished" in types
    assert any(t == "claude.tool_use" for t in types)


def test_import_is_idempotent_by_import_key(runner: CliRunner, env) -> None:
    sid = "idempotent-id"
    _seed_session(env["home"], sid)

    first = runner.invoke(app, ["import", "claude-session", "--id", sid])
    assert first.exit_code == 0, (first.stdout, first.stderr)
    runs_after_first = _all_run_dirs(env["agentlens_home"])
    assert len(runs_after_first) == 1

    second = runner.invoke(app, ["import", "claude-session", "--id", sid])
    assert second.exit_code == 0, (second.stdout, second.stderr)
    runs_after_second = _all_run_dirs(env["agentlens_home"])
    assert len(runs_after_second) == 1
    assert runs_after_first[0] == runs_after_second[0]


def test_import_latest_picks_newest_by_mtime(runner: CliRunner, env) -> None:
    older = _seed_session(env["home"], "older-sid", project="proj-a")
    newer = _seed_session(env["home"], "newer-sid", project="proj-b")
    old_t = time.time() - 100
    new_t = time.time()
    os.utime(older, (old_t, old_t))
    os.utime(newer, (new_t, new_t))

    result = runner.invoke(app, ["import", "claude-session", "--latest"])
    assert result.exit_code == 0, (result.stdout, result.stderr)

    runs = _all_run_dirs(env["agentlens_home"])
    assert len(runs) == 1
    doc = json.loads((runs[0] / "run.json").read_text(encoding="utf-8"))
    assert doc["input"]["import_key"] == "claude-session:newer-sid"


def test_import_with_parent_run_id(runner: CliRunner, env) -> None:
    sid = "with-parent"
    _seed_session(env["home"], sid)
    parent = "run_20260101_000000_aaaaaa"

    result = runner.invoke(
        app,
        ["import", "claude-session", "--id", sid, "--parent", parent],
    )
    assert result.exit_code == 0, (result.stdout, result.stderr)

    run_dir = _find_capture_run_dir(env["agentlens_home"], sid)
    doc = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert doc["parent_run_id"] == parent


def test_import_unknown_session_id_warns_and_no_run_created(
    runner: CliRunner, env
) -> None:
    # Seed a different session so the command itself wires up; the asked-for
    # id is missing and the importer must refuse cleanly without creating a
    # run tree.
    _seed_session(env["home"], "existing-sid")
    result = runner.invoke(
        app, ["import", "claude-session", "--id", "no-such-session"]
    )
    # Non-blocking by convention (cf. run-close on unknown id).
    assert result.exit_code == 0
    # No run created.
    runs = _all_run_dirs(env["agentlens_home"])
    assert runs == []
