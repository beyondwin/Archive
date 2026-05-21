"""Integration tests for ``agentlens import codex-session`` (spec §4.2.6).

The importer locates rollout JSONL files under
``~/.codex/sessions/YYYY/MM/DD/`` (and optionally
``~/.codex/archived_sessions/``), materialises a ``capture`` run with
the transcript copied into ``artifacts/transcripts/<session-id>.jsonl``,
and tags the run.json with ``input.import_key="codex-rollout:<id>"`` so
re-imports are idempotent.

The tests drive the Typer CLI end-to-end against a tmp ``HOME`` and a
tmp ``AGENTLENS_HOME``.
"""
from __future__ import annotations

import json
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


_BODY = [
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


def _rollout_filename(session_id: str, iso: str = "2026-05-19T10-00-00") -> str:
    return f"rollout-{iso}-{session_id}.jsonl"


def _seed_active(
    home: Path,
    session_id: str,
    *,
    originator: str = "Codex CLI",
    source: object = "vscode",
    extra_body: list[dict] | None = None,
    iso: str = "2026-05-19T10-00-00",
) -> Path:
    p = (
        home / ".codex" / "sessions" / "2026" / "05" / "19"
        / _rollout_filename(session_id, iso=iso)
    )
    p.parent.mkdir(parents=True, exist_ok=True)
    body = extra_body if extra_body is not None else _BODY
    with p.open("w", encoding="utf-8") as f:
        f.write(
            json.dumps(_meta_line(session_id, originator=originator, source=source))
            + "\n"
        )
        for ln in body:
            f.write(json.dumps(ln) + "\n")
    return p


def _seed_archived(
    home: Path,
    session_id: str,
    *,
    originator: str = "Codex CLI",
    source: object = "vscode",
    iso: str = "2026-05-19T10-00-00",
) -> Path:
    p = home / ".codex" / "archived_sessions" / _rollout_filename(session_id, iso=iso)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        f.write(
            json.dumps(_meta_line(session_id, originator=originator, source=source))
            + "\n"
        )
        for ln in _BODY:
            f.write(json.dumps(ln) + "\n")
    return p


def _find_capture_run_dir(al_home: Path, session_id: str) -> Path:
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
                == f"codex-rollout:{session_id}"
            ):
                return run_dir
    raise AssertionError(
        f"no run.json found with import_key codex-rollout:{session_id}"
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


SID_A = "01923456-7abc-7def-8123-aaaaaaaaaaaa"
SID_B = "01923456-7abc-7def-8123-bbbbbbbbbbbb"
SID_C_PARENT = "01923456-7abc-7def-8123-cccccccccccc"
SID_C_CHILD = "01923456-7abc-7def-8123-ccccccccdddd"
SID_D_PARENT = "01923456-7abc-7def-8123-dddddddddddd"
SID_D_CHILD = "01923456-7abc-7def-8123-ddddddddeeee"
SID_E = "01923456-7abc-7def-8123-eeeeeeeeeeee"


# ---------------------------------------------------------------------------
# Scenario (a): Codex CLI rollout with source="vscode".
# ---------------------------------------------------------------------------
def test_a_codex_cli_vscode_source(runner: CliRunner, env) -> None:
    src = _seed_active(env["home"], SID_A, originator="Codex CLI", source="vscode")

    result = runner.invoke(app, ["import", "codex-session", "--id", SID_A])
    assert result.exit_code == 0, (result.stdout, result.stderr)

    run_dir = _find_capture_run_dir(env["agentlens_home"], SID_A)
    doc = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert doc["run_kind"] == "capture"
    assert doc["agent"]["name"] == "codex_cli"
    assert doc["agent"]["label"] == "codex-cli"
    assert doc["agent"]["mode"] == "cli"
    assert doc["recording"]["adapter"] == "agentlens_session_import"
    assert doc["recording"]["has_transcript"] is True
    assert doc["recording"]["transcript_source"] == "codex-rollout-jsonl"
    assert doc["input"]["import_key"] == f"codex-rollout:{SID_A}"
    assert doc["meta"]["originator"] == "Codex CLI"
    assert doc["meta"]["codex_cli_version"] == "0.1.0"
    assert doc["meta"]["codex_source"] == "vscode"

    transcript = run_dir / "artifacts" / "transcripts" / f"{SID_A}.jsonl"
    assert transcript.is_file()
    assert transcript.read_bytes() == src.read_bytes()


# ---------------------------------------------------------------------------
# Scenario (b): Codex Desktop rollout — agent.label/mode reflect Desktop.
# ---------------------------------------------------------------------------
def test_b_codex_desktop_originator(runner: CliRunner, env) -> None:
    _seed_active(
        env["home"],
        SID_B,
        originator="Codex Desktop",
        source="vscode",
    )

    result = runner.invoke(app, ["import", "codex-session", "--id", SID_B])
    assert result.exit_code == 0, (result.stdout, result.stderr)

    run_dir = _find_capture_run_dir(env["agentlens_home"], SID_B)
    doc = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert doc["agent"]["name"] == "codex_cli"
    assert doc["agent"]["label"] == "codex-desktop"
    assert doc["agent"]["mode"] == "app"
    assert doc["meta"]["originator"] == "Codex Desktop"


# ---------------------------------------------------------------------------
# Scenario (c): subagent rollout with parent already imported.
# ---------------------------------------------------------------------------
def test_c_subagent_with_parent_imported(runner: CliRunner, env) -> None:
    _seed_active(env["home"], SID_C_PARENT)
    # Import parent first.
    parent_result = runner.invoke(
        app, ["import", "codex-session", "--id", SID_C_PARENT]
    )
    assert parent_result.exit_code == 0, (parent_result.stdout, parent_result.stderr)
    parent_run_dir = _find_capture_run_dir(env["agentlens_home"], SID_C_PARENT)
    parent_doc = json.loads((parent_run_dir / "run.json").read_text(encoding="utf-8"))
    parent_run_id = parent_doc["run_id"]

    # Now seed the child with subagent.thread_spawn.parent_thread_id = parent.
    _seed_active(
        env["home"],
        SID_C_CHILD,
        source={
            "subagent": {
                "thread_spawn": {
                    "parent_thread_id": SID_C_PARENT,
                    "depth": 1,
                    "agent_role": "reviewer",
                }
            }
        },
    )

    child_result = runner.invoke(
        app, ["import", "codex-session", "--id", SID_C_CHILD]
    )
    assert child_result.exit_code == 0, (child_result.stdout, child_result.stderr)
    child_run_dir = _find_capture_run_dir(env["agentlens_home"], SID_C_CHILD)
    child_doc = json.loads((child_run_dir / "run.json").read_text(encoding="utf-8"))
    assert child_doc["parent_run_id"] == parent_run_id
    # Pending field should NOT be set when the parent resolved immediately.
    assert "pending_parent_thread_id" not in child_doc.get("meta", {})


# ---------------------------------------------------------------------------
# Scenario (d): subagent rollout imported BEFORE parent — pending linkage,
# backfilled when the parent is later imported.
# ---------------------------------------------------------------------------
def test_d_subagent_pending_then_backfill(runner: CliRunner, env) -> None:
    # Seed the child first; parent rollout file exists on disk but is not
    # imported yet.
    _seed_active(env["home"], SID_D_PARENT)
    _seed_active(
        env["home"],
        SID_D_CHILD,
        source={
            "subagent": {
                "thread_spawn": {
                    "parent_thread_id": SID_D_PARENT,
                    "depth": 1,
                    "agent_role": "reviewer",
                }
            }
        },
    )

    # Import the CHILD first.
    child_first = runner.invoke(
        app, ["import", "codex-session", "--id", SID_D_CHILD]
    )
    assert child_first.exit_code == 0, (child_first.stdout, child_first.stderr)
    child_run_dir = _find_capture_run_dir(env["agentlens_home"], SID_D_CHILD)
    child_doc = json.loads((child_run_dir / "run.json").read_text(encoding="utf-8"))
    # No parent yet — pending field is set, parent_run_id is null/absent.
    assert child_doc.get("parent_run_id") in (None,)
    assert child_doc["meta"]["pending_parent_thread_id"] == SID_D_PARENT

    # Now import the PARENT — the child's parent_run_id is backfilled.
    parent_result = runner.invoke(
        app, ["import", "codex-session", "--id", SID_D_PARENT]
    )
    assert parent_result.exit_code == 0, (parent_result.stdout, parent_result.stderr)
    parent_run_dir = _find_capture_run_dir(env["agentlens_home"], SID_D_PARENT)
    parent_doc = json.loads((parent_run_dir / "run.json").read_text(encoding="utf-8"))
    parent_run_id = parent_doc["run_id"]

    # Re-read child run.json — parent_run_id should now match the parent
    # and pending_parent_thread_id should be cleared.
    child_doc2 = json.loads((child_run_dir / "run.json").read_text(encoding="utf-8"))
    assert child_doc2["parent_run_id"] == parent_run_id
    assert "pending_parent_thread_id" not in child_doc2.get("meta", {})


# ---------------------------------------------------------------------------
# Scenario (e): same session_id in active AND archived — exactly one run.
# ---------------------------------------------------------------------------
def test_e_same_id_in_both_trees_dedupe(runner: CliRunner, env) -> None:
    _seed_active(env["home"], SID_E)
    _seed_archived(env["home"], SID_E)

    # First import: --id finds the active copy.
    first = runner.invoke(app, ["import", "codex-session", "--id", SID_E])
    assert first.exit_code == 0, (first.stdout, first.stderr)
    runs_after_first = _all_run_dirs(env["agentlens_home"])
    assert len(runs_after_first) == 1

    # Second import with --include-archived must NOT create a second run
    # (idempotent via input.import_key).
    second = runner.invoke(
        app,
        ["import", "codex-session", "--id", SID_E, "--include-archived"],
    )
    assert second.exit_code == 0, (second.stdout, second.stderr)
    runs_after_second = _all_run_dirs(env["agentlens_home"])
    assert len(runs_after_second) == 1
    assert runs_after_first[0] == runs_after_second[0]


# ---------------------------------------------------------------------------
# Extra: events.jsonl carries codex.* opaque events.
# ---------------------------------------------------------------------------
def test_import_emits_codex_namespace_events(runner: CliRunner, env) -> None:
    sid = "01923456-7abc-7def-8123-1111aaaabbbb"
    _seed_active(env["home"], sid)

    result = runner.invoke(app, ["import", "codex-session", "--id", sid])
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
    assert any(t == "codex.message" for t in types)
    assert any(t == "codex.tool_use" for t in types)
    assert any(t == "codex.tool_result" for t in types)
    assert any(t == "codex.reasoning" for t in types)


def test_import_unknown_session_id_warns_and_no_run(runner: CliRunner, env) -> None:
    result = runner.invoke(
        app, ["import", "codex-session", "--id", "no-such-session"]
    )
    assert result.exit_code == 0
    runs = _all_run_dirs(env["agentlens_home"])
    assert runs == []
