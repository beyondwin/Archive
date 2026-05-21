"""Tests for /api/v1/workspaces[/{id}]."""
from __future__ import annotations

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
    copy_fixture_as_run_id(FIXTURES, "failed_command_run", tmp_path / "runs")
    monkeypatch.setenv("AGENTLENS_HOME", str(tmp_path))
    return tmp_path


def test_workspaces_list(home):
    r = TestClient(create_app(ServeSettings())).get("/api/v1/workspaces")
    assert r.status_code == 200
    ids = {w["workspace_id"] for w in r.json()}
    assert ids == {"ws_0000000000000001", "ws_0000000000000002"}


def test_workspace_detail(home):
    r = TestClient(create_app(ServeSettings())).get(
        "/api/v1/workspaces/ws_0000000000000001"
    )
    body = r.json()
    assert body["workspace_id"] == "ws_0000000000000001"
    assert "run_count" in body
    assert "recent_runs" in body
    assert "eval_pass_rate_30d" in body


def test_workspace_detail_404(home):
    r = TestClient(create_app(ServeSettings())).get("/api/v1/workspaces/ws_missing")
    assert r.status_code == 404
