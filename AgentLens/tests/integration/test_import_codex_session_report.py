"""Integration tests: Codex-rollout importer + report/usage finalization (Task 17).

Mirrors :mod:`tests.integration.test_import_claude_session_report` for the
Codex importer. Verifies:

* CLI rollout with full token usage → ``analysis_state="full"``,
  ``usage.confidence="exact"``, display_title set from first user message,
  manifest covers transcript + import_report.json + usage.json.
* Desktop rollout with no token info → ``usage.json`` is still written with
  all-zero counters and ``confidence="unknown"``.
* Parent linkage regression: child imported after parent retains
  ``parent_run_id``; child imported before parent is backfilled.
* Re-import is a no-op (E9) for report/usage bytes and mtimes.
* ``agentlens show <id> --format json`` returns the locked projection.
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


SID_CLI = "01923456-7abc-7def-8123-111122223333"
SID_DESKTOP = "01923456-7abc-7def-8123-222233334444"
SID_DUP = "01923456-7abc-7def-8123-333344445555"
SID_PARENT = "01923456-7abc-7def-8123-444455556666"
SID_CHILD = "01923456-7abc-7def-8123-555566667777"


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


def _rollout_filename(session_id: str, iso: str = "2026-05-19T10-00-00") -> str:
    return f"rollout-{iso}-{session_id}.jsonl"


def _seed(
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
    body = extra_body or []
    with p.open("w", encoding="utf-8") as f:
        f.write(
            json.dumps(_meta_line(session_id, originator=originator, source=source))
            + "\n"
        )
        for ln in body:
            f.write(json.dumps(ln) + "\n")
    return p


def _cli_body_with_usage() -> list[dict]:
    """Body with first user message + one event carrying full token info."""
    return [
        {
            "type": "message",
            "role": "user",
            "content": "Make a Codex display title",
            "timestamp": "2026-05-19T10:00:01.000Z",
        },
        {
            "type": "event_msg",
            "timestamp": "2026-05-19T10:00:02.000Z",
            "payload": {
                "info": {
                    "model": "gpt-5-codex",
                    "tokens": {
                        "input_tokens": 11,
                        "output_tokens": 7,
                        "cache_creation_tokens": 0,
                        "cache_read_tokens": 0,
                        "reasoning_tokens": 5,
                    },
                },
            },
        },
    ]


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
                == f"codex-rollout:{session_id}"
            ):
                return run_dir
    raise AssertionError(f"no run for codex-rollout:{session_id}")


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


def test_cli_with_full_usage_writes_exact_summary(
    runner: CliRunner, env
) -> None:
    src = _seed(
        env["home"],
        SID_CLI,
        originator="Codex CLI",
        source="vscode",
        extra_body=_cli_body_with_usage(),
    )

    result = runner.invoke(app, ["import", "codex-session", "--id", SID_CLI])
    assert result.exit_code == 0, (result.stdout, result.stderr)

    run_dir = _find_run_dir(env["agentlens_home"], SID_CLI)

    # import_report.json — full analysis, redacted source path, non-empty hash.
    report_path = run_dir / "artifacts" / "import_report.json"
    assert report_path.is_file()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["analysis_state"] == "full"
    assert report["source"] == "codex-rollout"
    assert report["source_path"] == f"codex-rollout:{SID_CLI}"
    assert report["source_path_hash"].startswith("sha256:")
    # Raw absolute path of source must never appear in the serialized report.
    assert str(env["home"]) not in report_path.read_text(encoding="utf-8")
    assert report["byte_cap_source"] == "default"
    assert report["derived"]["display_title"] == "Make a Codex display title"
    assert report["transcript_artifact"]["path"] == (
        f"artifacts/transcripts/{SID_CLI}.jsonl"
    )

    # usage.json — exact confidence with the populated counts.
    usage_path = run_dir / "artifacts" / "usage.json"
    assert usage_path.is_file()
    usage = json.loads(usage_path.read_text(encoding="utf-8"))
    assert usage["source"] == "codex-rollout"
    assert usage["confidence"] == "exact"
    assert usage["input_tokens"] == 11
    assert usage["output_tokens"] == 7
    assert usage["reasoning_tokens"] == 5
    assert usage["model_breakdown"][0]["model"] == "gpt-5-codex"

    # events.jsonl — run.started must be first, command.finished carries
    # analysis_state.
    events = [
        json.loads(ln)
        for ln in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    assert events[0]["type"] == "run.started"
    types = [e["type"] for e in events]
    assert "command.started" in types
    assert "command.finished" in types
    fin = next(e for e in events if e["type"] == "command.finished")
    assert fin["payload"]["analysis_state"] == "full"

    # final.json — agent_outcome reflects the "full" path (unknown).
    final = json.loads((run_dir / "final.json").read_text(encoding="utf-8"))
    assert final["agent_outcome"] == "unknown"

    # eval.json — finalize ran.
    assert (run_dir / "eval.json").is_file()

    # manifest.json — covers transcript + report + usage.
    manifest = json.loads(
        (run_dir / "manifest.json").read_text(encoding="utf-8")
    )
    manifest_paths = {item["path"] for item in manifest["files"]}
    assert f"artifacts/transcripts/{SID_CLI}.jsonl" in manifest_paths
    assert "artifacts/import_report.json" in manifest_paths
    assert "artifacts/usage.json" in manifest_paths
    assert manifest["sealed_phase"] == "final"

    # Transcript copy byte-for-byte identical to source.
    transcript = run_dir / "artifacts" / "transcripts" / f"{SID_CLI}.jsonl"
    assert transcript.read_bytes() == src.read_bytes()

    # show projection.
    run_id = json.loads(
        (run_dir / "run.json").read_text(encoding="utf-8")
    )["run_id"]
    show = runner.invoke(app, ["show", run_id, "--format", "json"])
    assert show.exit_code == 0, (show.stdout, show.stderr)
    payload = json.loads(show.stdout)
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
    assert payload["agent_outcome"] == "unknown"
    assert payload["sealed_phase"] == "final"
    # task_18 projection passthrough: ``show`` MUST surface
    # display_title / usage / import_state from artifacts/, matching the
    # ``latest`` and ``status`` row contract.
    assert payload["import_state"] is not None
    assert payload["usage"] is not None
    # eval_status MUST be promoted from eval.json status, never silently
    # default to needs_eval because of query.get_run merge-key drift.
    assert payload["eval_status"] != "needs_eval"


def test_desktop_no_tokens_writes_unknown_usage(
    runner: CliRunner, env
) -> None:
    """Codex Desktop with no billable records still gets a deterministic usage.json."""
    _seed(
        env["home"],
        SID_DESKTOP,
        originator="Codex Desktop",
        source="vscode",
        extra_body=[
            {
                "type": "message",
                "role": "user",
                "content": "hi",
                "timestamp": "2026-05-19T10:00:01.000Z",
            },
            {
                "type": "reasoning",
                "summary": "think",
                "timestamp": "2026-05-19T10:00:02.000Z",
            },
        ],
    )

    result = runner.invoke(app, ["import", "codex-session", "--id", SID_DESKTOP])
    assert result.exit_code == 0, (result.stdout, result.stderr)

    run_dir = _find_run_dir(env["agentlens_home"], SID_DESKTOP)

    # Desktop differentiation preserved.
    doc = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert doc["agent"]["label"] == "codex-desktop"
    assert doc["agent"]["mode"] == "app"

    # usage.json is still written with all-zero counters and unknown confidence.
    usage_path = run_dir / "artifacts" / "usage.json"
    assert usage_path.is_file()
    usage = json.loads(usage_path.read_text(encoding="utf-8"))
    assert usage["source"] == "codex-rollout"
    assert usage["confidence"] == "unknown"
    assert usage["input_tokens"] == 0
    assert usage["output_tokens"] == 0
    assert usage["cache_creation_tokens"] == 0
    assert usage["cache_read_tokens"] == 0
    assert usage["reasoning_tokens"] == 0
    assert usage["model_breakdown"] == []

    # Manifest still covers usage.json.
    manifest = json.loads(
        (run_dir / "manifest.json").read_text(encoding="utf-8")
    )
    manifest_paths = {item["path"] for item in manifest["files"]}
    assert "artifacts/usage.json" in manifest_paths
    assert "artifacts/import_report.json" in manifest_paths


def test_duplicate_import_is_no_op_for_report_and_usage(
    runner: CliRunner, env
) -> None:
    _seed(
        env["home"],
        SID_DUP,
        originator="Codex CLI",
        source="vscode",
        extra_body=_cli_body_with_usage(),
    )

    first = runner.invoke(app, ["import", "codex-session", "--id", SID_DUP])
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

    second = runner.invoke(app, ["import", "codex-session", "--id", SID_DUP])
    assert second.exit_code == 0, (second.stdout, second.stderr)

    runs_after_second = _all_run_dirs(env["agentlens_home"])
    assert runs_after_second == runs_after_first

    # Bytes and mtime preserved — dup-import path must short-circuit before
    # any writes touch the existing artifacts.
    assert report_path.read_bytes() == report_first
    assert usage_path.read_bytes() == usage_first
    assert report_path.stat().st_mtime_ns == report_mtime
    assert usage_path.stat().st_mtime_ns == usage_mtime


def test_parent_backfill_after_finalize_regression(
    runner: CliRunner, env
) -> None:
    """Child imported before parent is backfilled after the parent imports.

    Regression guard: the backfill MUST run AFTER ``finalize_imported_run``
    so the run.json the index reads matches the (post-finalize) on-disk state.
    """
    _seed(env["home"], SID_PARENT, originator="Codex CLI", source="vscode")
    _seed(
        env["home"],
        SID_CHILD,
        originator="Codex CLI",
        source={
            "subagent": {
                "thread_spawn": {
                    "parent_thread_id": SID_PARENT,
                    "depth": 1,
                    "agent_role": "reviewer",
                }
            }
        },
    )

    # Import child first → pending linkage, no parent_run_id.
    child_first = runner.invoke(
        app, ["import", "codex-session", "--id", SID_CHILD]
    )
    assert child_first.exit_code == 0, (child_first.stdout, child_first.stderr)
    child_run_dir = _find_run_dir(env["agentlens_home"], SID_CHILD)
    child_doc = json.loads(
        (child_run_dir / "run.json").read_text(encoding="utf-8")
    )
    assert child_doc.get("parent_run_id") is None
    assert child_doc["meta"]["pending_parent_thread_id"] == SID_PARENT
    # Child is still fully finalized as a standalone import (sealed manifest).
    assert (child_run_dir / "manifest.json").is_file()
    assert (child_run_dir / "final.json").is_file()

    # Import parent → child backfilled with parent_run_id; pending cleared.
    parent_result = runner.invoke(
        app, ["import", "codex-session", "--id", SID_PARENT]
    )
    assert parent_result.exit_code == 0, (parent_result.stdout, parent_result.stderr)
    parent_run_dir = _find_run_dir(env["agentlens_home"], SID_PARENT)
    parent_doc = json.loads(
        (parent_run_dir / "run.json").read_text(encoding="utf-8")
    )
    parent_run_id = parent_doc["run_id"]

    child_doc2 = json.loads(
        (child_run_dir / "run.json").read_text(encoding="utf-8")
    )
    assert child_doc2["parent_run_id"] == parent_run_id
    assert "pending_parent_thread_id" not in child_doc2.get("meta", {})
