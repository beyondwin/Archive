from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from agentrunway.agentlens import AgentLensCliEmitter, AgentLensEmitError, create_agentlens_emitter


ROOT = Path(__file__).resolve().parents[1]
FAKE_BIN = ROOT / "evals" / "fixtures" / "fake-bin"


def test_agentlens_cli_emitter_sends_event_type_and_payload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log = tmp_path / "agentlens.jsonl"
    monkeypatch.setenv("PATH", f"{FAKE_BIN}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("AGENTLENS_FAKE_LOG", str(log))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    emitter = AgentLensCliEmitter(timeout_seconds=5)
    emitter.emit(
        "agentrunway.run_started",
        {
            "agentrunway_run_id": "run-1",
            "path": str(tmp_path / "home" / "repo"),
            "token": "[REDACTED]",
        },
    )

    rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert rows == [
        {
            "event_type": "agentrunway.run_started",
            "payload": {
                "agentrunway_run_id": "run-1",
                "path": str(tmp_path / "home" / "repo"),
                "token": "[REDACTED]",
            },
        }
    ]


def test_agentlens_cli_emitter_targets_v2_envelope_to_agentlens_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = tmp_path / "agentlens.jsonl"
    monkeypatch.setenv("PATH", f"{FAKE_BIN}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("AGENTLENS_FAKE_LOG", str(log))

    emitter = AgentLensCliEmitter(timeout_seconds=5, agentlens_run_id="agentlens-run-1")
    emitter.emit(
        "agentrunway.run_finished",
        {
            "schema": "agentlens.event.v2",
            "event_id": "evt_000001",
            "run_id": "agentrunway-run-1",
            "event_type": "agentrunway.run_finished",
            "producer": {"name": "agentrunway", "version": "0.1.0"},
            "occurred_at": "2026-05-21T00:00:00Z",
            "sequence": 1,
            "phase": "finish",
            "outcome": "success",
            "severity": "info",
            "trust_impact": "supports_success",
            "summary": "finished",
            "payload": {"run_id": "agentrunway-run-1"},
        },
    )

    rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    emitted = rows[0]["payload"]
    assert emitted["schema"] == "agentlens.event.v2"
    assert emitted["run_id"] == "agentlens-run-1"
    assert emitted["payload"]["run_id"] == "agentrunway-run-1"


def test_create_agentlens_emitter_returns_none_when_cli_missing() -> None:
    assert create_agentlens_emitter(cli="definitely-missing-agentlens-cli") is None


def test_create_agentlens_emitter_opens_agentrunway_container_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log = tmp_path / "agentlens.jsonl"
    monkeypatch.setenv("PATH", f"{FAKE_BIN}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("AGENTRUNWAY_FAKE_AGENTLENS_LOG", str(log))

    emitter = create_agentlens_emitter(agentrunway_run_id="run-1", workspace=tmp_path)

    assert emitter is not None
    rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["command"] == "run-open"
    assert rows[0]["argv"][rows[0]["argv"].index("--agent") + 1] == "agentrunway"


def test_agentlens_cli_emitter_raises_concise_error_on_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", f"{FAKE_BIN}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("AGENTLENS_FAKE_FAIL", "offline")

    emitter = AgentLensCliEmitter(timeout_seconds=5)

    with pytest.raises(AgentLensEmitError, match="offline"):
        emitter.emit("agentrunway.run_started", {"agentrunway_run_id": "run-1"})


def test_fake_agentlens_passthroughs_unsupported_commands(tmp_path: Path) -> None:
    import subprocess
    import sys

    log = tmp_path / "agentlens.jsonl"
    env = os.environ.copy()
    env["AGENTLENS_FAKE_LOG"] = str(log)

    result = subprocess.run(
        [sys.executable, str(FAKE_BIN / "agentlens"), "event", "append-batch"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert rows == [{"argv": ["event", "append-batch"], "command": "unsupported"}]
