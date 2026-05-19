"""Integration tests: Claude-session importer + report/usage finalization (Task 16).

Drives the full Typer surface end-to-end to verify:

* a malformed source produces ``analysis_state="partial"`` with manifest
  coverage of the new ``artifacts/import_report.json`` / ``artifacts/usage.json``;
* ``run.started`` is the first event in the run's events.jsonl;
* ``eval.json`` exists (finalize ran);
* ``agentlens show <id> --format json`` returns the locked projection;
* re-import is a no-op for the run row AND existing report/usage files (E9).
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


# A session with one valid user line, one valid assistant tool_use line, and one
# malformed (non-JSON) line — drives analysis_state="partial".
def _seed_malformed(home: Path, session_id: str) -> Path:
    p = home / ".claude" / "projects" / "-Users-foo-bar" / f"{session_id}.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps(
            {
                "type": "user",
                "message": {"role": "user", "content": "Hello AgentLens"},
                "timestamp": "2026-05-19T10:00:00.000Z",
            }
        ),
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "model": "claude-3-7-sonnet-20250219",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_x",
                            "name": "Bash",
                            "input": {"command": "ls"},
                        }
                    ],
                    "usage": {
                        "input_tokens": 12,
                        "output_tokens": 3,
                        "cache_creation_input_tokens": 0,
                        "cache_read_input_tokens": 0,
                    },
                },
                "timestamp": "2026-05-19T10:00:05.500Z",
            }
        ),
        "this is not valid json {",
    ]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def _find_run_dir(al_home: Path, session_id: str) -> Path:
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
    raise AssertionError(f"no run for claude-session:{session_id}")


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


def test_malformed_source_partial_analysis_with_manifest_coverage(
    runner: CliRunner, env
) -> None:
    sid = "malformed-sid"
    _seed_malformed(env["home"], sid)

    result = runner.invoke(app, ["import", "claude-session", "--id", sid])
    assert result.exit_code == 0, (result.stdout, result.stderr)

    run_dir = _find_run_dir(env["agentlens_home"], sid)

    # import_report.json — partial analysis, redacted source path, non-empty hash.
    report_path = run_dir / "artifacts" / "import_report.json"
    assert report_path.is_file()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["analysis_state"] == "partial"
    assert report["source_path"] == f"claude-session:{sid}"
    assert report["source_path_hash"].startswith("sha256:")
    # Raw absolute path of source must never appear in the serialized report.
    assert str(env["home"]) not in report_path.read_text(encoding="utf-8")
    assert report["lines"]["skipped_malformed"] >= 1
    assert report["first_error"] is not None
    assert report["derived"]["display_title"] == "Hello AgentLens"
    assert report["byte_cap_source"] == "default"

    # usage.json — always written.
    usage_path = run_dir / "artifacts" / "usage.json"
    assert usage_path.is_file()
    usage = json.loads(usage_path.read_text(encoding="utf-8"))
    assert usage["source"] == "claude-session"
    assert usage["input_tokens"] == 12
    assert usage["output_tokens"] == 3

    # events.jsonl — run.started must be first.
    events = [
        json.loads(ln)
        for ln in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    assert events[0]["type"] == "run.started"
    types = [e["type"] for e in events]
    assert "command.started" in types
    assert "command.finished" in types
    # command.finished payload carries analysis_state.
    fin = next(e for e in events if e["type"] == "command.finished")
    assert fin["payload"]["analysis_state"] == "partial"

    # final.json — agent_outcome reflects partial.
    final = json.loads((run_dir / "final.json").read_text(encoding="utf-8"))
    assert final["agent_outcome"] == "partial"

    # eval.json — finalize ran.
    assert (run_dir / "eval.json").is_file()

    # manifest.json — covers transcript + import_report.json + usage.json.
    manifest = json.loads(
        (run_dir / "manifest.json").read_text(encoding="utf-8")
    )
    manifest_paths = {item["path"] for item in manifest["files"]}
    assert f"artifacts/transcripts/{sid}.jsonl" in manifest_paths
    assert "artifacts/import_report.json" in manifest_paths
    assert "artifacts/usage.json" in manifest_paths
    assert manifest["sealed_phase"] == "final"

    # `agentlens show <id> --format json` returns locked projection.
    run_id = json.loads(
        (run_dir / "run.json").read_text(encoding="utf-8")
    )["run_id"]
    show = runner.invoke(app, ["show", run_id, "--format", "json"])
    assert show.exit_code == 0, (show.stdout, show.stderr)
    payload = json.loads(show.stdout)
    # The v1 projection always emits these 10 keys + the three task_18
    # importer-artifact projections (display_title / usage / import_state).
    for k in (
        "run_id",
        "agent",
        "started_at",
        "agent_outcome",
        "eval_status",
        "sealed_phase",
        "workspace_id",
        "workspace_short",
        "failures",
        "risks",
        "display_title",
        "usage",
        "import_state",
    ):
        assert k in payload
    assert payload["run_id"] == run_id
    assert payload["agent_outcome"] == "partial"
    assert payload["sealed_phase"] == "final"
    # task_18 projection passthrough: ``show`` MUST surface the same keys
    # ``latest`` / ``status`` do. Container-run fallback would be ``None`` for
    # all three; a non-null trio confirms the import-report path resolved.
    assert payload["display_title"] == "Hello AgentLens"
    assert payload["import_state"] == "partial"
    assert payload["usage"] is not None
    assert payload["usage"]["input_tokens"] == 12
    # ``eval_status`` MUST come from eval.json (status field), not default to
    # ``needs_eval`` because of merge-key drift in ``query.get_run``.
    assert payload["eval_status"] != "needs_eval"


def test_duplicate_import_is_no_op_for_report_and_usage(
    runner: CliRunner, env
) -> None:
    sid = "dup-sid"
    _seed_malformed(env["home"], sid)

    first = runner.invoke(app, ["import", "claude-session", "--id", sid])
    assert first.exit_code == 0, (first.stdout, first.stderr)

    runs_after_first = _all_run_dirs(env["agentlens_home"])
    assert len(runs_after_first) == 1
    run_dir = runs_after_first[0]

    report_path = run_dir / "artifacts" / "import_report.json"
    usage_path = run_dir / "artifacts" / "usage.json"
    report_first = report_path.read_bytes()
    usage_first = usage_path.read_bytes()
    report_mtime = report_path.stat().st_mtime_ns
    usage_mtime = usage_path.stat().st_mtime_ns

    second = runner.invoke(app, ["import", "claude-session", "--id", sid])
    assert second.exit_code == 0, (second.stdout, second.stderr)

    runs_after_second = _all_run_dirs(env["agentlens_home"])
    assert runs_after_second == runs_after_first

    # Bytes and mtime preserved — the dup-import path must short-circuit
    # before any writes touch the existing artifacts.
    assert report_path.read_bytes() == report_first
    assert usage_path.read_bytes() == usage_first
    assert report_path.stat().st_mtime_ns == report_mtime
    assert usage_path.stat().st_mtime_ns == usage_mtime
