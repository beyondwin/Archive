"""Phase-1 end-to-end smoke test for AgentLens v1 (Task 9).

Exercises the full Phase-1 surface in one flow:

1. ``run-open``                   — container run for the orchestrator.
2. ``event append --type platform.run_started``.
3. Wrapping a fake child process with ``AGENTLENS_PARENT_RUN_ID`` set to
   the orchestrator's run_id → records a linked child run.
4. ``event append --type runway.run_finished``.
5. ``run-close``                  — finalizes the container.
6. ``import claude-session``      — synthetic Claude JSONL → capture run
   with ``transcript_source = "claude-session-jsonl"`` and
   ``input.import_key == "claude-session:<sid>"``.
7. ``import codex-session``       — synthetic Codex rollout JSONL →
   capture run with ``transcript_source = "codex-rollout-jsonl"`` and
   ``input.import_key == "codex-rollout:<uuidv7>"``.
8. ``events --run <orchestrator_id> --tree`` — parent + descendant
   events present and ordered by (ts, run_id).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agentlens.adapters.process import wrap_command
from agentlens.cli import app


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture()
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """Unified fixture: fake HOME (for importer source roots), tmp
    AGENTLENS_HOME, and a workspace cwd. Clears env vars that would
    confuse the wrapper."""
    home = tmp_path / "fake_home"
    home.mkdir()
    al_home = tmp_path / "agentlens_home"
    al_home.mkdir()
    ws = tmp_path / "workspace"
    ws.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("AGENTLENS_HOME", str(al_home))
    monkeypatch.chdir(ws)
    # Ensure no stray inherited wrapper state.
    monkeypatch.delenv("AGENTLENS_RUN_ID", raising=False)
    monkeypatch.delenv("AGENTLENS_RUN_DIR", raising=False)
    monkeypatch.delenv("AGENTLENS_PARENT_RUN_ID", raising=False)
    monkeypatch.delenv("AGENTLENS_NESTED_POLICY", raising=False)
    return {"home": home, "agentlens_home": al_home, "workspace": ws}


# ---------------------------------------------------------------------------
# Helpers (mirror the reference tests).
# ---------------------------------------------------------------------------

def _resolve_run_dir(workspace: Path, run_id: str) -> Path:
    marker = workspace / ".agentlens" / "current-runs" / run_id / "run_dir"
    return Path(marker.read_text(encoding="utf-8").strip())


def _read_run_json_in_home(home: Path, run_id: str) -> dict:
    """Locate the run.json for ``run_id`` under ``home/runs/<workspace>/``."""
    candidates = list((home / "runs").glob("*/*"))
    candidates = [d for d in candidates if d.is_dir() and (d / "run.json").is_file()]
    match = [d for d in candidates if d.name == run_id]
    assert match, f"no run dir matched {run_id} under {home}"
    return json.loads((match[0] / "run.json").read_text(encoding="utf-8"))


def _find_capture_run_dir(al_home: Path, import_key: str) -> Path:
    runs_root = al_home / "runs"
    for ws_dir in runs_root.iterdir():
        if not ws_dir.is_dir():
            continue
        for run_dir in ws_dir.iterdir():
            run_json = run_dir / "run.json"
            if not run_json.is_file():
                continue
            doc = json.loads(run_json.read_text(encoding="utf-8"))
            if doc.get("input", {}).get("import_key") == import_key:
                return run_dir
    raise AssertionError(f"no run.json found with import_key {import_key}")


_CLAUDE_LINES = [
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
                    "id": "toolu_smoke",
                    "name": "Bash",
                    "input": {"command": "ls"},
                }
            ],
        },
        "timestamp": "2026-05-19T10:00:01.000Z",
    },
]


def _seed_claude_session(home: Path, sid: str) -> Path:
    p = home / ".claude" / "projects" / "-Users-foo-bar" / f"{sid}.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        for ln in _CLAUDE_LINES:
            f.write(json.dumps(ln) + "\n")
    return p


def _seed_codex_rollout(
    home: Path, session_id: str, iso: str = "2026-05-19T10-00-00"
) -> Path:
    p = (
        home / ".codex" / "sessions" / "2026" / "05" / "19"
        / f"rollout-{iso}-{session_id}.jsonl"
    )
    p.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        "type": "session_meta",
        "payload": {
            "id": session_id,
            "timestamp": "2026-05-19T10:00:00.000Z",
            "cwd": "/work",
            "originator": "Codex CLI",
            "cli_version": "0.1.0",
            "model_provider": "openai",
            "source": "vscode",
        },
    }
    body = [
        {
            "type": "message",
            "role": "user",
            "content": "hi",
            "timestamp": "2026-05-19T10:00:01.000Z",
        },
        {
            "type": "tool_use",
            "name": "shell",
            "id": "call_smoke",
            "input": {"cmd": "ls"},
            "timestamp": "2026-05-19T10:00:02.000Z",
        },
    ]
    with p.open("w", encoding="utf-8") as f:
        f.write(json.dumps(meta) + "\n")
        for ln in body:
            f.write(json.dumps(ln) + "\n")
    return p


# ---------------------------------------------------------------------------
# The smoke test.
# ---------------------------------------------------------------------------

def test_phase1_end_to_end_smoke(
    runner: CliRunner,
    env: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = env["workspace"]
    al_home = env["agentlens_home"]

    # ---- 1. run-open: container run for the orchestrator. ----
    r = runner.invoke(
        app,
        ["run-open", "--agent", "waygent", "--workspace", str(workspace)],
    )
    assert r.exit_code == 0, r.stderr
    orchestrator_run_id = r.stdout.strip().splitlines()[-1]
    assert orchestrator_run_id.startswith("run_"), orchestrator_run_id
    orch_run_dir = _resolve_run_dir(workspace, orchestrator_run_id)
    orch_doc = json.loads((orch_run_dir / "run.json").read_text(encoding="utf-8"))
    assert orch_doc["run_kind"] == "container"

    # ---- 2. event append: platform.run_started ----
    r = runner.invoke(
        app,
        [
            "event",
            "append",
            "--run",
            orchestrator_run_id,
            "--type",
            "platform.run_started",
            "--payload-json",
            "{}",
        ],
    )
    assert r.exit_code == 0, r.stderr

    # ---- 3. Spawn a fake child under AGENTLENS_PARENT_RUN_ID. ----
    monkeypatch.setenv("AGENTLENS_PARENT_RUN_ID", orchestrator_run_id)
    monkeypatch.delenv("AGENTLENS_RUN_ID", raising=False)
    monkeypatch.delenv("AGENTLENS_RUN_DIR", raising=False)
    child_result = wrap_command(
        [sys.executable, "-c", "print('child')"],
        agent_name="claude_code",
        agent_mode="cli",
        mode="minimal",
    )
    assert child_result.exit_code == 0
    assert child_result.run_id is not None
    child_run_id = child_result.run_id
    # Child must be linked to the orchestrator.
    child_doc = _read_run_json_in_home(al_home, child_run_id)
    assert child_doc.get("parent_run_id") == orchestrator_run_id

    # Clear explicit parent before subsequent CLI invocations so they don't
    # accidentally inherit the explicit-parent contract.
    monkeypatch.delenv("AGENTLENS_PARENT_RUN_ID", raising=False)

    # ---- 4. event append: runway.run_finished ----
    r = runner.invoke(
        app,
        [
            "event",
            "append",
            "--run",
            orchestrator_run_id,
            "--type",
            "runway.run_finished",
            "--payload-json",
            "{}",
        ],
    )
    assert r.exit_code == 0, r.stderr

    # ---- 5. run-close ----
    r = runner.invoke(
        app,
        ["run-close", "--run", orchestrator_run_id, "--outcome", "success"],
    )
    assert r.exit_code == 0, r.stderr
    assert (orch_run_dir / "final.json").is_file()

    # ---- 6. import claude-session ----
    sid_claude = "smoke-claude-001"
    src_claude = _seed_claude_session(env["home"], sid_claude)
    r = runner.invoke(app, ["import", "claude-session", "--id", sid_claude])
    assert r.exit_code == 0, (r.stdout, r.stderr)
    claude_run_dir = _find_capture_run_dir(
        al_home, f"claude-session:{sid_claude}"
    )
    claude_doc = json.loads((claude_run_dir / "run.json").read_text(encoding="utf-8"))
    assert claude_doc["run_kind"] == "capture"
    assert claude_doc["recording"]["transcript_source"] == "claude-session-jsonl"
    assert claude_doc["input"]["import_key"] == f"claude-session:{sid_claude}"
    transcript_claude = (
        claude_run_dir / "artifacts" / "transcripts" / f"{sid_claude}.jsonl"
    )
    assert transcript_claude.is_file()
    assert transcript_claude.read_bytes() == src_claude.read_bytes()

    # ---- 7. import codex-session ----
    # 8-4-4-4-12 hex (uuidv7-shaped); see _ROLLOUT_RE in
    # agentlens.store.codex_session — must match this pattern.
    sid_codex = "01923456-7abc-7def-8123-aaaa0000bbbb"
    src_codex = _seed_codex_rollout(env["home"], sid_codex)
    r = runner.invoke(app, ["import", "codex-session", "--id", sid_codex])
    assert r.exit_code == 0, (r.stdout, r.stderr)
    codex_run_dir = _find_capture_run_dir(
        al_home, f"codex-rollout:{sid_codex}"
    )
    codex_doc = json.loads((codex_run_dir / "run.json").read_text(encoding="utf-8"))
    assert codex_doc["run_kind"] == "capture"
    assert codex_doc["recording"]["transcript_source"] == "codex-rollout-jsonl"
    assert codex_doc["input"]["import_key"] == f"codex-rollout:{sid_codex}"
    transcript_codex = (
        codex_run_dir / "artifacts" / "transcripts" / f"{sid_codex}.jsonl"
    )
    assert transcript_codex.is_file()
    assert transcript_codex.read_bytes() == src_codex.read_bytes()

    # ---- 8. events --tree on the orchestrator run. ----
    r = runner.invoke(
        app, ["events", "--run", orchestrator_run_id, "--tree"]
    )
    assert r.exit_code == 0, r.stderr
    events = [
        json.loads(ln) for ln in r.stdout.strip().splitlines() if ln.strip()
    ]
    types = [e["type"] for e in events]
    assert "platform.run_started" in types
    assert "runway.run_finished" in types
    # Orchestrator + child events both reachable.
    run_ids = {e["run_id"] for e in events}
    assert orchestrator_run_id in run_ids
    assert child_run_id in run_ids
    # Order must be (ts, run_id) ascending.
    keys = [(e["ts"], e["run_id"]) for e in events]
    assert keys == sorted(keys), (
        f"events not ordered by (ts, run_id): {keys}"
    )
