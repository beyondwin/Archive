"""End-to-end CLI lifecycle test (spec §S1.6.16, §S1.11.1, §S1.7.3).

Drives start -> mark -> final -> seal pre_eval -> eval -> seal final -> show
through the Typer CLI and asserts that the resulting run tree, manifest, and
eval document satisfy the v0 contract.
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
    """Isolate AGENTLENS_HOME and chdir into a fresh workspace root."""
    home = tmp_path / "agentlens_home"
    home.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("AGENTLENS_HOME", str(home))
    monkeypatch.chdir(workspace)
    return workspace


def _read_manifest(run_dir: Path) -> dict:
    return json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))


def _read_eval(run_dir: Path) -> dict:
    return json.loads((run_dir / "eval.json").read_text(encoding="utf-8"))


def _resolve_run_dir(workspace: Path, run_id: str) -> Path:
    marker = workspace / ".agentlens" / "current-runs" / run_id / "run_dir"
    return Path(marker.read_text(encoding="utf-8").strip())


def test_full_cli_lifecycle(runner: CliRunner, workspace: Path) -> None:
    # 1. start
    result = runner.invoke(app, ["start", "--agent", "generic", "--mode", "cli"])
    assert result.exit_code == 0, result.stderr
    run_id = result.stdout.strip().splitlines()[-1]
    assert run_id.startswith("run_"), run_id

    run_dir = _resolve_run_dir(workspace, run_id)
    assert run_dir.is_dir()
    assert (run_dir / "run.json").is_file()
    assert (run_dir / "events.jsonl").is_file()

    # 2. mark task.started
    result = runner.invoke(app, ["mark", "task.started", "--name", "demo"])
    assert result.exit_code == 0, result.stderr
    lines = (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2

    # 3. final --outcome success
    result = runner.invoke(app, ["final", "--outcome", "success"])
    assert result.exit_code == 0, result.stderr
    assert (run_dir / "final.json").is_file()

    # 4. seal (default pre_eval)
    result = runner.invoke(app, ["seal"])
    assert result.exit_code == 0, result.stderr
    manifest = _read_manifest(run_dir)
    assert manifest["sealed_phase"] == "pre_eval"
    paths = [item["path"] for item in manifest["files"]]
    assert "eval.json" not in paths

    # 5. eval
    result = runner.invoke(app, ["eval", "--latest"])
    assert result.exit_code == 0, result.stderr
    eval_doc = _read_eval(run_dir)
    assert eval_doc["status"] in {"passed", "failed", "incomplete", "needs_eval"}
    assert eval_doc["agent_outcome"] == "success"
    names = {c["name"] for c in eval_doc["checks"]}
    assert {"schema_valid", "final_present"} <= names

    # 6. seal --final
    result = runner.invoke(app, ["seal", "--final"])
    assert result.exit_code == 0, result.stderr
    manifest = _read_manifest(run_dir)
    assert manifest["sealed_phase"] == "final"
    paths = [item["path"] for item in manifest["files"]]
    assert "eval.json" in paths

    # 7. show --latest --format json — must contain 5 fields + sealed_phase
    result = runner.invoke(
        app, ["show", "--latest", "--format", "json"]
    )
    assert result.exit_code == 0, result.stderr
    data = json.loads(result.stdout)
    for key in (
        "run_id",
        "agent",
        "started_at",
        "agent_outcome",
        "eval_status",
    ):
        assert key in data, f"missing key {key}: {data}"
    assert data["run_id"] == run_id
    assert data["agent_outcome"] == "success"
    assert data["eval_status"] == eval_doc["status"]
    assert data.get("sealed_phase") == "final"


def test_start_emits_run_started_event(runner: CliRunner, workspace: Path) -> None:
    result = runner.invoke(app, ["start", "--agent", "generic", "--mode", "cli"])
    assert result.exit_code == 0, result.stderr
    run_id = result.stdout.strip().splitlines()[-1]

    run_dir = _resolve_run_dir(workspace, run_id)
    lines = (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    evt = json.loads(lines[0])
    assert evt["type"] == "run.started"
    assert evt["run_id"] == run_id


def test_eval_status_incomplete_when_no_final(
    runner: CliRunner, workspace: Path
) -> None:
    runner.invoke(app, ["start", "--agent", "generic", "--mode", "cli"])
    result = runner.invoke(app, ["eval", "--latest"])
    assert result.exit_code == 0, result.stderr
    # find the latest run_dir via marker
    markers = list((workspace / ".agentlens" / "current-runs").iterdir())
    assert markers, "no current-run marker"
    run_dir = Path((markers[0] / "run_dir").read_text(encoding="utf-8").strip())
    eval_doc = _read_eval(run_dir)
    assert eval_doc["status"] == "incomplete"


# ---------------------------------------------------------------------------
# Query commands: latest / status / show / failures / risks (task_11)
# ---------------------------------------------------------------------------


def _start_and_seal(runner: CliRunner) -> str:
    """Helper: start a run, mark, final, seal, eval, seal --final. Returns run_id."""
    result = runner.invoke(app, ["start", "--agent", "generic", "--mode", "cli"])
    assert result.exit_code == 0, result.stderr
    run_id = result.stdout.strip().splitlines()[-1]
    runner.invoke(app, ["mark", "task.started", "--name", "demo"])
    runner.invoke(app, ["final", "--outcome", "success"])
    runner.invoke(app, ["seal"])
    runner.invoke(app, ["eval", "--latest"])
    runner.invoke(app, ["seal", "--final"])
    return run_id


def test_latest_query_command_prints_one_line(
    runner: CliRunner, workspace: Path
) -> None:
    run_id = _start_and_seal(runner)
    result = runner.invoke(app, ["latest"])
    assert result.exit_code == 0, result.stderr
    out = result.stdout.strip()
    # One line containing run_id, a workspace_short, outcome, eval_status, sealed_phase.
    assert "\n" not in out, f"latest must be one line, got: {out!r}"
    assert run_id in out
    assert "success" in out
    assert "final" in out


def test_latest_query_command_json(runner: CliRunner, workspace: Path) -> None:
    run_id = _start_and_seal(runner)
    result = runner.invoke(app, ["latest", "--format", "json"])
    assert result.exit_code == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["run_id"] == run_id
    assert data["agent_outcome"] == "success"
    assert data["sealed_phase"] == "final"
    assert "workspace_id" in data


def test_latest_query_no_runs_returns_zero_with_message(
    runner: CliRunner, workspace: Path
) -> None:
    result = runner.invoke(app, ["latest"])
    assert result.exit_code == 0, result.stderr
    # JSON returns null
    result_json = runner.invoke(app, ["latest", "--format", "json"])
    assert result_json.exit_code == 0
    assert json.loads(result_json.stdout) is None


def test_latest_no_absolute_paths_in_text(
    runner: CliRunner, workspace: Path
) -> None:
    _start_and_seal(runner)
    result = runner.invoke(app, ["latest"])
    assert result.exit_code == 0
    # default text must not leak absolute paths (workspace_id short + relative ok).
    assert "/agentlens_home" not in result.stdout
    assert str(workspace) not in result.stdout


def test_status_query_command_includes_in_progress(
    runner: CliRunner, workspace: Path
) -> None:
    # Start a run but do not finalize/seal — must still appear in status.
    result = runner.invoke(app, ["start", "--agent", "generic", "--mode", "cli"])
    assert result.exit_code == 0, result.stderr
    in_progress_id = result.stdout.strip().splitlines()[-1]
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0, result.stderr
    assert in_progress_id in result.stdout


def test_status_query_command_json(runner: CliRunner, workspace: Path) -> None:
    run_id = _start_and_seal(runner)
    result = runner.invoke(app, ["status", "--format", "json"])
    assert result.exit_code == 0, result.stderr
    rows = json.loads(result.stdout)
    assert isinstance(rows, list)
    assert any(r.get("run_id") == run_id for r in rows)


def test_show_query_includes_failures_and_risks(
    runner: CliRunner, workspace: Path
) -> None:
    run_id = _start_and_seal(runner)
    result = runner.invoke(app, ["show", "--latest", "--format", "json"])
    assert result.exit_code == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["run_id"] == run_id
    # New fields added by task_11 — backwards-compatible (existing keys preserved)
    assert "failures" in data
    assert "risks" in data
    assert isinstance(data["failures"], list)
    assert isinstance(data["risks"], list)
    # Preserve legacy keys (lifecycle test contract)
    for k in (
        "run_id",
        "agent",
        "started_at",
        "agent_outcome",
        "eval_status",
        "sealed_phase",
    ):
        assert k in data


def test_show_query_by_run_id(runner: CliRunner, workspace: Path) -> None:
    run_id = _start_and_seal(runner)
    result = runner.invoke(app, ["show", run_id, "--format", "json"])
    assert result.exit_code == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["run_id"] == run_id


def test_failures_query_command(runner: CliRunner, workspace: Path) -> None:
    _start_and_seal(runner)
    result = runner.invoke(app, ["failures", "--format", "json"])
    assert result.exit_code == 0, result.stderr
    data = json.loads(result.stdout)
    assert isinstance(data, list)
    # success run → typically no failures.


def test_failures_query_text(runner: CliRunner, workspace: Path) -> None:
    _start_and_seal(runner)
    result = runner.invoke(app, ["failures"])
    assert result.exit_code == 0, result.stderr
    # Even empty must succeed; no absolute paths in text output
    assert str(workspace) not in result.stdout


def test_risks_query_command(runner: CliRunner, workspace: Path) -> None:
    _start_and_seal(runner)
    result = runner.invoke(app, ["risks", "--format", "json"])
    assert result.exit_code == 0, result.stderr
    data = json.loads(result.stdout)
    assert isinstance(data, list)


def test_risks_query_includes_recording_incomplete(
    runner: CliRunner, workspace: Path
) -> None:
    # Start a run; manually mark its manifest as recording_incomplete to simulate.
    import os
    runner.invoke(app, ["start", "--agent", "generic", "--mode", "cli"])
    # Locate run_dir via marker
    markers = list((workspace / ".agentlens" / "current-runs").iterdir())
    run_dir = Path((markers[0] / "run_dir").read_text(encoding="utf-8").strip())
    manifest = {
        "schema": "agentlens.manifest.v1",
        "run_id": run_dir.name,
        "sealed_at": "2026-01-01T00:00:10Z",
        "sealed": True,
        "sealed_phase": "recording_incomplete",
        "files": [],
        "redaction": {},
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    result = runner.invoke(app, ["risks", "--format", "json"])
    assert result.exit_code == 0, result.stderr
    data = json.loads(result.stdout)
    cats = {r.get("category") for r in data}
    assert "RECORDING_INCOMPLETE" in cats
