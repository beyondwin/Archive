"""Integration tests: ``--byte-cap`` / ``--deep-parse-only`` semantics (Task 16/17).

Covers the Claude half of the byte-cap surface today; the Codex half is added
by Task 17 to this same file once the Codex importer wires the flags through.

Behaviour expectations (spec §4.1):

* Source exceeds the configured byte cap (default or flag), deep parse is
  permitted → ``analysis_state="partial"`` AND ``byte_cap_hit=True``.
* ``--deep-parse-only`` flag + oversize source → ``analysis_state="skipped"``,
  no ``claude.*`` events make it into the run log, but the run-bracket events
  (``run.started`` / ``command.started`` / ``command.finished``) and the
  transcript copy are still present.
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


# Per-line payload bytes — kept generous so a handful of lines clear a
# 1 MiB cap deterministically.
_LINE_PADDING = "x" * 200_000  # ~200 KB per line; six lines > 1 MiB.


def _seed_oversize(home: Path, session_id: str) -> Path:
    p = home / ".claude" / "projects" / "-Users-foo-bar" / f"{session_id}.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    # First line carries the first-user-message text for display title.
    lines.append(
        json.dumps(
            {
                "type": "user",
                "message": {"role": "user", "content": "Hello AgentLens"},
                "timestamp": "2026-05-19T10:00:00.000Z",
            }
        )
    )
    for i in range(7):
        lines.append(
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "role": "assistant",
                        "model": "claude-3-7-sonnet-20250219",
                        "content": [
                            {
                                "type": "tool_use",
                                "id": f"toolu_{i}",
                                "name": "Bash",
                                "input": {"command": _LINE_PADDING},
                            }
                        ],
                        "usage": {
                            "input_tokens": 1,
                            "output_tokens": 1,
                            "cache_creation_input_tokens": 0,
                            "cache_read_input_tokens": 0,
                        },
                    },
                    "timestamp": "2026-05-19T10:00:0%d.000Z" % i,
                }
            )
        )
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


def test_default_overcap_partial_byte_cap_hit(
    runner: CliRunner, env
) -> None:
    sid = "overcap-sid"
    src = _seed_oversize(env["home"], sid)
    # Sanity: the source must exceed the byte cap we're about to set.
    cap = 1 * 1024 * 1024  # 1 MiB (the minimum)
    assert src.stat().st_size > cap

    result = runner.invoke(
        app,
        ["import", "claude-session", "--id", sid, "--byte-cap", str(cap)],
    )
    assert result.exit_code == 0, (result.stdout, result.stderr)

    run_dir = _find_run_dir(env["agentlens_home"], sid)
    report = json.loads(
        (run_dir / "artifacts" / "import_report.json").read_text(
            encoding="utf-8"
        )
    )
    assert report["analysis_state"] == "partial"
    assert report["byte_cap_hit"] is True
    assert report["byte_cap_source"] == "flag:--byte-cap"
    assert report["byte_cap_bytes"] == cap

    # final.json reflects partial outcome.
    final = json.loads((run_dir / "final.json").read_text(encoding="utf-8"))
    assert final["agent_outcome"] == "partial"


def test_deep_parse_only_skipped_state(runner: CliRunner, env) -> None:
    sid = "skipped-sid"
    src = _seed_oversize(env["home"], sid)
    cap = 1 * 1024 * 1024
    assert src.stat().st_size > cap

    result = runner.invoke(
        app,
        [
            "import",
            "claude-session",
            "--id",
            sid,
            "--byte-cap",
            str(cap),
            "--deep-parse-only",
        ],
    )
    assert result.exit_code == 0, (result.stdout, result.stderr)

    run_dir = _find_run_dir(env["agentlens_home"], sid)
    report = json.loads(
        (run_dir / "artifacts" / "import_report.json").read_text(
            encoding="utf-8"
        )
    )
    assert report["analysis_state"] == "skipped"

    # No claude.* events; run-bracket events still present.
    events = [
        json.loads(ln)
        for ln in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    types = [e["type"] for e in events]
    assert types[0] == "run.started"
    assert "command.started" in types
    assert "command.finished" in types
    assert not any(t.startswith("claude.") for t in types)

    # Transcript is still copied verbatim under deep-parse-only.
    transcript = run_dir / "artifacts" / "transcripts" / f"{sid}.jsonl"
    assert transcript.is_file()
    assert transcript.read_bytes() == src.read_bytes()


def test_byte_cap_flag_out_of_range_errors(runner: CliRunner, env) -> None:
    sid = "range-sid"
    _seed_oversize(env["home"], sid)
    # 500 bytes is below the 1 MiB minimum.
    result = runner.invoke(
        app,
        ["import", "claude-session", "--id", sid, "--byte-cap", "500"],
    )
    assert result.exit_code != 0
    combined = (result.stdout or "") + (result.stderr or "")
    assert "byte-cap" in combined.lower() or "byte_cap" in combined.lower()


def test_byte_cap_env_var_provenance(
    runner: CliRunner, env, monkeypatch: pytest.MonkeyPatch
) -> None:
    sid = "env-sid"
    src = _seed_oversize(env["home"], sid)
    cap = 1 * 1024 * 1024
    assert src.stat().st_size > cap
    monkeypatch.setenv("AGENTLENS_IMPORT_BYTE_CAP", str(cap))

    result = runner.invoke(app, ["import", "claude-session", "--id", sid])
    assert result.exit_code == 0, (result.stdout, result.stderr)

    run_dir = _find_run_dir(env["agentlens_home"], sid)
    report = json.loads(
        (run_dir / "artifacts" / "import_report.json").read_text(
            encoding="utf-8"
        )
    )
    assert report["byte_cap_source"] == "env:AGENTLENS_IMPORT_BYTE_CAP"
    assert report["byte_cap_bytes"] == cap
