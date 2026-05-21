"""Tests for /api/v1/failures and /api/v1/risks (global)."""
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
    copy_fixture_as_run_id(FIXTURES, "failed_command_run", tmp_path / "runs")
    copy_fixture_as_run_id(FIXTURES, "residual_risk_run", tmp_path / "runs")
    monkeypatch.setenv("AGENTLENS_HOME", str(tmp_path))
    return tmp_path


def test_global_failures(home):
    r = TestClient(create_app(ServeSettings())).get("/api/v1/failures?since_days=36500")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_global_risks(home):
    r = TestClient(create_app(ServeSettings())).get("/api/v1/risks?since_days=36500")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_global_failures_filter(home):
    r = TestClient(create_app(ServeSettings())).get(
        "/api/v1/failures?workspace_id=ws_0000000000000002&since_days=36500"
    )
    assert r.status_code == 200
