"""Integration tests for ``agentlens run-open`` / ``agentlens run-close``.

Container runs (spec §4.2.1, §4.2.2, S1.5.1) record orchestrator activity
that has no transcript. ``run-open`` writes a schema-valid ``run.json`` +
``run.started`` event; ``run-close`` writes ``final.json`` and indexes
best-effort. Both must avoid the v0 legacy ``meta.json`` and any
root-level ``transcript.jsonl``.
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
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "agentlens_home"
    home.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("AGENTLENS_HOME", str(home))
    monkeypatch.chdir(workspace)
    return workspace


def _resolve_run_dir(workspace: Path, run_id: str) -> Path:
    marker = workspace / ".agentlens" / "current-runs" / run_id / "run_dir"
    return Path(marker.read_text(encoding="utf-8").strip())


def test_run_open_writes_container_run(runner: CliRunner, workspace: Path) -> None:
    result = runner.invoke(
        app,
        [
            "run-open",
            "--agent",
            "waygent",
            "--workspace",
            str(workspace),
        ],
    )
    assert result.exit_code == 0, result.stderr

    out_lines = result.stdout.strip().splitlines()
    assert len(out_lines) == 1, f"expected single-line run_id stdout, got: {result.stdout!r}"
    run_id = out_lines[0]
    assert run_id.startswith("run_"), run_id

    run_dir = _resolve_run_dir(workspace, run_id)
    assert run_dir.is_dir()
    run_doc = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert run_doc["run_kind"] == "container"
    assert run_doc["agent"]["name"] == "generic"
    assert run_doc["agent"]["mode"] == "unknown"
    assert run_doc["agent"]["label"] == "waygent"
    assert run_doc["recording"]["adapter"] == "agentlens_container"
    assert run_doc["recording"]["has_transcript"] is False
    assert run_doc["recording"]["transcript_source"] == "none"

    # events.jsonl: exactly one run.started entry
    events_path = run_dir / "events.jsonl"
    assert events_path.is_file()
    lines = events_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    evt = json.loads(lines[0])
    assert evt["type"] == "run.started"
    assert evt["run_id"] == run_id

    # final.json absent until run-close
    assert not (run_dir / "final.json").exists()

    # No legacy meta.json, no root-level transcript.jsonl
    assert not (run_dir / "meta.json").exists()
    assert not (run_dir / "transcript.jsonl").exists()


def test_run_open_with_parent_and_meta(runner: CliRunner, workspace: Path) -> None:
    parent_id = "run_20260101_000000_aaaaaa"
    result = runner.invoke(
        app,
        [
            "run-open",
            "--agent",
            "child-agent",
            "--parent",
            parent_id,
            "--meta",
            "spawned_by=opus",
            "--meta",
            "task_id=task_3",
        ],
    )
    assert result.exit_code == 0, result.stderr
    run_id = result.stdout.strip()
    run_dir = _resolve_run_dir(workspace, run_id)
    run_doc = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert run_doc["parent_run_id"] == parent_id
    assert run_doc["agent"]["label"] == "child-agent"


def test_run_close_writes_final(runner: CliRunner, workspace: Path) -> None:
    result = runner.invoke(
        app, ["run-open", "--agent", "waygent"]
    )
    assert result.exit_code == 0, result.stderr
    run_id = result.stdout.strip()
    run_dir = _resolve_run_dir(workspace, run_id)
    assert not (run_dir / "final.json").exists()

    result = runner.invoke(
        app,
        ["run-close", "--run", run_id, "--outcome", "success"],
    )
    assert result.exit_code == 0, result.stderr
    assert (run_dir / "final.json").is_file()
    final_doc = json.loads((run_dir / "final.json").read_text(encoding="utf-8"))
    assert final_doc["agent_outcome"] == "success"
    assert final_doc["run_id"] == run_id


def test_run_close_unknown_run_id_warns_and_exits_zero(
    runner: CliRunner, workspace: Path
) -> None:
    bogus = "run_20990101_000000_zzzzzz"
    result = runner.invoke(
        app, ["run-close", "--run", bogus, "--outcome", "success"]
    )
    assert result.exit_code == 0, (
        f"run-close must be non-blocking on unknown run id; got {result.exit_code}, stderr={result.stderr!r}"
    )
    assert bogus in result.stderr or "unknown" in result.stderr.lower()
