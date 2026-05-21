"""Tests for /api/v1/runs/{id}/events (NDJSON)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agentlens.web.app import create_app
from agentlens.web.settings import ServeSettings
from tests.helpers import copy_fixture_as_run_id

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture()
def home(monkeypatch, tmp_path):
    copy_fixture_as_run_id(FIXTURES, "minimal_run", tmp_path / "runs")
    monkeypatch.setenv("AGENTLENS_HOME", str(tmp_path))
    return tmp_path


def test_events_returns_ndjson(home):
    run_id = json.loads((FIXTURES / "minimal_run" / "run.json").read_text())["run_id"]
    r = TestClient(create_app(ServeSettings())).get(f"/api/v1/runs/{run_id}/events")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/x-ndjson")
    lines = [ln for ln in r.text.splitlines() if ln.strip()]
    for line in lines:
        assert isinstance(json.loads(line), dict)


def test_events_malformed_line_becomes_error_marker(monkeypatch, tmp_path):
    runs = tmp_path / "runs" / "ws_demo" / "broken_run"
    runs.mkdir(parents=True)
    (runs / "events.jsonl").write_text(
        '{"type":"start"}\nNOT JSON HERE\n{"type":"final"}\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENTLENS_HOME", str(tmp_path))
    r = TestClient(create_app(ServeSettings())).get("/api/v1/runs/broken_run/events")
    lines = [json.loads(ln) for ln in r.text.splitlines() if ln.strip()]
    assert lines[0]["type"] == "start"
    assert lines[1].get("_error") == "parse"
    assert lines[1]["line"] == 2
    assert lines[2]["type"] == "final"
