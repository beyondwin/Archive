"""Tests for agentlens.store.writer (S1.6.6, S1.6.11)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentlens.schema.validate import SchemaError
from agentlens.store.writer import (
    WriteError,
    append_event,
    atomic_write_json,
    write_final,
    write_run_meta,
    write_workspace_pointer,
)

FIXTURES = (
    Path(__file__).resolve().parents[1] / "fixtures" / "schemas" / "valid"
)


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def test_atomic_write_json_writes_valid_doc(tmp_path: Path) -> None:
    run = _load_fixture("run")
    out = tmp_path / "run.json"
    atomic_write_json(out, run)
    assert out.exists()
    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert loaded == run
    # No leftover tempfile in the directory.
    leftovers = [p for p in tmp_path.iterdir() if p.name.startswith(".tmp_")]
    assert leftovers == []


def test_atomic_write_json_creates_parent_dirs(tmp_path: Path) -> None:
    run = _load_fixture("run")
    out = tmp_path / "deep" / "nested" / "run.json"
    atomic_write_json(out, run)
    assert out.exists()


def test_atomic_write_json_rejects_missing_schema_field(tmp_path: Path) -> None:
    out = tmp_path / "x.json"
    with pytest.raises(WriteError):
        atomic_write_json(out, {"no_schema": True})
    assert not out.exists()


def test_atomic_write_json_rejects_non_dict(tmp_path: Path) -> None:
    out = tmp_path / "x.json"
    with pytest.raises(WriteError):
        atomic_write_json(out, ["not", "a", "dict"])  # type: ignore[arg-type]


def test_atomic_write_json_rejects_invalid_schema(tmp_path: Path) -> None:
    out = tmp_path / "run.json"
    bad = {"schema": "agentlens.run.v1"}  # missing required fields
    with pytest.raises(WriteError):
        atomic_write_json(out, bad)
    assert not out.exists()
    leftovers = [p for p in tmp_path.iterdir() if p.name.startswith(".tmp_")]
    assert leftovers == []


def test_append_event_appends_one_line(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    evt = _load_fixture("event")
    append_event(run_dir, evt)
    events_path = run_dir / "events.jsonl"
    assert events_path.exists()
    lines = events_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == evt


def test_append_event_accumulates_multiple_lines(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    evt = _load_fixture("event")
    append_event(run_dir, evt)
    evt2 = dict(evt)
    evt2["event_id"] = "evt_abc123def457"
    append_event(run_dir, evt2)
    lines = (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2


def test_append_event_rejects_oversized_excerpt(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    evt = _load_fixture("event")
    evt["payload"] = {"excerpt": {"text": "x" * 4097}}
    with pytest.raises(WriteError):
        append_event(run_dir, evt)
    # File should not exist (or should be empty if created).
    events_path = run_dir / "events.jsonl"
    if events_path.exists():
        assert events_path.read_text(encoding="utf-8") == ""


def test_append_event_accepts_excerpt_at_limit(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    evt = _load_fixture("event")
    evt["payload"] = {"excerpt": {"text": "x" * 4096}}
    append_event(run_dir, evt)
    assert (run_dir / "events.jsonl").exists()


def test_append_event_rejects_missing_schema(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    with pytest.raises(WriteError):
        append_event(run_dir, {"event_id": "evt_abc123def456"})


def test_append_event_rejects_invalid_event(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    bad = {"schema": "agentlens.event.v1"}  # missing required fields
    with pytest.raises(WriteError):
        append_event(run_dir, bad)


def test_write_run_meta_writes_run_json(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    run = _load_fixture("run")
    write_run_meta(run_dir, run)
    assert (run_dir / "run.json").exists()


def test_write_final_writes_final_json(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    final = _load_fixture("final")
    write_final(run_dir, final)
    assert (run_dir / "final.json").exists()


def test_write_workspace_pointer_creates_marker(tmp_path: Path) -> None:
    workspace_root = tmp_path / "ws"
    workspace_root.mkdir()
    run_dir = tmp_path / "runs" / "ws_x" / "run_y"
    run_dir.mkdir(parents=True)
    run_id = "run_20260518_211328_abc123"
    write_workspace_pointer(workspace_root, run_id, run_dir)
    marker = workspace_root / ".agentlens" / "current-runs" / run_id
    assert marker.is_dir()
    assert (marker / "run_dir").read_text(encoding="utf-8") == str(run_dir.resolve())


# ---------------------------------------------------------------------------
# v1-unification: writer accepts container/codex runs and namespaced events
# (Task 0; S1.5.1)
# ---------------------------------------------------------------------------


def test_write_run_meta_accepts_container_run(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    run = _load_fixture("run_container")
    write_run_meta(run_dir, run)
    assert (run_dir / "run.json").exists()
    loaded = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert loaded["run_kind"] == "container"
    assert loaded["agent"]["label"] == "agentrunway"
    assert loaded["recording"]["transcript_source"] == "none"


def test_write_run_meta_accepts_codex_capture_run(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    run = _load_fixture("run_codex_capture")
    write_run_meta(run_dir, run)
    loaded = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert loaded["agent"]["name"] == "codex_cli"
    assert loaded["recording"]["transcript_source"] == "codex-rollout-jsonl"
    assert loaded["input"]["import_key"].startswith("codex-rollout:")


@pytest.mark.parametrize(
    "fixture_name",
    [
        "event_agentrunway_run_started",
        "event_agentrunway_verification_result",
        "event_claude_tool_use",
        "event_codex_tool_use",
    ],
)
def test_append_event_accepts_namespaced_event(
    tmp_path: Path, fixture_name: str
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    evt = _load_fixture(fixture_name)
    append_event(run_dir, evt)
    lines = (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["type"] == evt["type"]


def test_append_event_rejects_uppercase_namespace(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    bad = _load_fixture("event")
    bad["type"] = "AgentRunway.task_started"
    with pytest.raises(WriteError):
        append_event(run_dir, bad)


def test_append_event_rejects_reserved_unknown_core_name(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    bad = _load_fixture("event")
    bad["type"] = "run.bogus_event"
    with pytest.raises(WriteError):
        append_event(run_dir, bad)
