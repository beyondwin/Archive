"""Integration tests for ``agentlens event append`` + ``agentlens events`` (spec §4.2.3, §4.2.4)."""
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
    ws = tmp_path / "workspace"
    ws.mkdir()
    monkeypatch.setenv("AGENTLENS_HOME", str(home))
    monkeypatch.chdir(ws)
    return ws


def _resolve_run_dir(workspace: Path, run_id: str) -> Path:
    return Path(
        (workspace / ".agentlens" / "current-runs" / run_id / "run_dir").read_text(
            encoding="utf-8"
        ).strip()
    )


def _open_run(runner: CliRunner, agent: str = "kws-cme-orchestrator", parent: str | None = None) -> str:
    args = ["run-open", "--agent", agent]
    if parent:
        args += ["--parent", parent]
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.stderr
    return result.stdout.strip()


def _read_events(run_dir: Path) -> list[dict]:
    p = run_dir / "events.jsonl"
    if not p.is_file():
        return []
    return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]


# ---------------------------------------------------------------------------
# event append
# ---------------------------------------------------------------------------

def test_event_append_payload_json(runner: CliRunner, workspace: Path) -> None:
    run_id = _open_run(runner)
    run_dir = _resolve_run_dir(workspace, run_id)

    result = runner.invoke(
        app,
        [
            "event",
            "append",
            "--run",
            run_id,
            "--type",
            "kws-cme.task_started",
            "--payload-json",
            '{"task_id":"task_1"}',
        ],
    )
    assert result.exit_code == 0, result.stderr

    events = _read_events(run_dir)
    # First event is the run.started from run-open. The new one is appended.
    assert events[-1]["schema"] == "agentlens.event.v1"
    assert events[-1]["type"] == "kws-cme.task_started"
    assert events[-1]["run_id"] == run_id
    assert events[-1]["payload"] == {"task_id": "task_1"}
    assert events[-1]["event_id"].startswith("evt_")
    assert events[-1]["ts"].endswith("Z")


def test_event_append_payload_file(runner: CliRunner, workspace: Path, tmp_path: Path) -> None:
    run_id = _open_run(runner)
    run_dir = _resolve_run_dir(workspace, run_id)

    payload_file = tmp_path / "payload.json"
    payload_file.write_text(json.dumps({"task_id": "task_2"}), encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "event",
            "append",
            "--run",
            run_id,
            "--type",
            "kws-cme.task_finished",
            "--payload-file",
            str(payload_file),
        ],
    )
    assert result.exit_code == 0, result.stderr
    events = _read_events(run_dir)
    assert events[-1]["type"] == "kws-cme.task_finished"
    assert events[-1]["payload"] == {"task_id": "task_2"}


def test_event_append_payload_stdin(runner: CliRunner, workspace: Path) -> None:
    run_id = _open_run(runner)
    run_dir = _resolve_run_dir(workspace, run_id)

    result = runner.invoke(
        app,
        [
            "event",
            "append",
            "--run",
            run_id,
            "--type",
            "kws-cme.note",
            "--payload-stdin",
        ],
        input='{"note":"hello"}',
    )
    assert result.exit_code == 0, result.stderr
    events = _read_events(run_dir)
    assert events[-1]["type"] == "kws-cme.note"
    assert events[-1]["payload"] == {"note": "hello"}


def test_event_append_requires_exactly_one_payload_source(
    runner: CliRunner, workspace: Path
) -> None:
    run_id = _open_run(runner)
    # No source.
    result = runner.invoke(
        app,
        ["event", "append", "--run", run_id, "--type", "kws-cme.task_started"],
    )
    assert result.exit_code != 0

    # Two sources.
    result = runner.invoke(
        app,
        [
            "event",
            "append",
            "--run",
            run_id,
            "--type",
            "kws-cme.task_started",
            "--payload-json",
            "{}",
            "--payload-stdin",
        ],
        input="{}",
    )
    assert result.exit_code != 0


def test_event_append_filesystem_resolution_when_sqlite_missing(
    runner: CliRunner, workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = _open_run(runner)
    run_dir = _resolve_run_dir(workspace, run_id)
    # Ensure no index.db exists.
    import os

    home = Path(os.environ["AGENTLENS_HOME"])
    idx = home / "index.db"
    if idx.exists():
        idx.unlink()

    result = runner.invoke(
        app,
        [
            "event",
            "append",
            "--run",
            run_id,
            "--type",
            "kws-cme.task_started",
            "--payload-json",
            '{"task_id":"task_x"}',
        ],
    )
    assert result.exit_code == 0, result.stderr
    events = _read_events(run_dir)
    assert events[-1]["type"] == "kws-cme.task_started"


# ---------------------------------------------------------------------------
# events query
# ---------------------------------------------------------------------------

def test_events_query_by_type_glob(runner: CliRunner, workspace: Path) -> None:
    run_id = _open_run(runner)
    runner.invoke(
        app,
        [
            "event",
            "append",
            "--run",
            run_id,
            "--type",
            "kws-cme.task_started",
            "--payload-json",
            '{"task_id":"task_1"}',
        ],
    )
    runner.invoke(
        app,
        [
            "event",
            "append",
            "--run",
            run_id,
            "--type",
            "kws-cme.task_finished",
            "--payload-json",
            '{"task_id":"task_1"}',
        ],
    )

    result = runner.invoke(
        app, ["events", "--run", run_id, "--type", "kws-cme.*"]
    )
    assert result.exit_code == 0, result.stderr
    lines = [ln for ln in result.stdout.strip().splitlines() if ln.strip()]
    assert len(lines) == 2
    for line in lines:
        evt = json.loads(line)
        assert evt["type"].startswith("kws-cme.")
        assert evt["run_id"] == run_id


def test_events_query_tree_includes_descendants_ordered(
    runner: CliRunner, workspace: Path
) -> None:
    parent_id = _open_run(runner, agent="parent")
    child_id = _open_run(runner, agent="child", parent=parent_id)

    runner.invoke(
        app,
        [
            "event",
            "append",
            "--run",
            child_id,
            "--type",
            "kws-cme.task_started",
            "--payload-json",
            '{"task_id":"task_c"}',
        ],
    )
    runner.invoke(
        app,
        [
            "event",
            "append",
            "--run",
            parent_id,
            "--type",
            "kws-cme.note",
            "--payload-json",
            '{"note":"hi"}',
        ],
    )

    result = runner.invoke(
        app,
        ["events", "--run", parent_id, "--tree"],
    )
    assert result.exit_code == 0, result.stderr
    events = [json.loads(ln) for ln in result.stdout.strip().splitlines() if ln.strip()]
    run_ids = {e["run_id"] for e in events}
    assert parent_id in run_ids
    assert child_id in run_ids

    # Order must be (ts, run_id) ascending.
    keys = [(e["ts"], e["run_id"]) for e in events]
    assert keys == sorted(keys)
