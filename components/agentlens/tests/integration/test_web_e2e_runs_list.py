"""Tests for /api/v1/runs."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agentlens.web.app import create_app
from agentlens.web.settings import ServeSettings
from tests.helpers import copy_fixture_as_run_id

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture()
def populated_home(monkeypatch, tmp_path):
    for name in ("minimal_run", "failed_command_run", "residual_risk_run"):
        copy_fixture_as_run_id(FIXTURES, name, tmp_path / "runs")
    monkeypatch.setenv("AGENTLENS_HOME", str(tmp_path))
    return tmp_path


def test_runs_list_returns_items(populated_home):
    r = TestClient(create_app(ServeSettings())).get("/api/v1/runs?since_days=36500")
    body = r.json()
    assert r.status_code == 200
    assert isinstance(body["items"], list)
    assert len(body["items"]) == 3
    assert body["next_cursor"] is None


def test_runs_list_pagination(populated_home):
    c = TestClient(create_app(ServeSettings()))
    r = c.get("/api/v1/runs?limit=2&since_days=36500")
    body = r.json()
    assert len(body["items"]) == 2
    assert body["next_cursor"] is not None
    r2 = c.get(f"/api/v1/runs?cursor={body['next_cursor']}&limit=2&since_days=36500")
    body2 = r2.json()
    assert len(body2["items"]) == 1
    assert body2["next_cursor"] is None


def test_runs_list_filter_eval_status(populated_home):
    r = TestClient(create_app(ServeSettings())).get(
        "/api/v1/runs?eval_status=failed&since_days=36500"
    )
    body = r.json()
    assert body["items"]
    for item in body["items"]:
        assert item["eval_status"] == "failed"


def test_runs_list_includes_numeric_failures_count(populated_home):
    r = TestClient(create_app(ServeSettings())).get("/api/v1/runs?since_days=36500")
    body = r.json()

    failed_run = next(
        item
        for item in body["items"]
        if item["run_id"] == "run_20260101_000001_bbbbbb"
    )
    assert failed_run["eval_status"] == "failed"
    assert failed_run["failures_count"] == 1


def test_runs_list_includes_import_projection_keys_and_no_source_path(
    populated_home,
):
    """task_18: each item carries display_title/usage/import_state and the
    payload never exposes the importer artifact's ``source_path`` field."""
    r = TestClient(create_app(ServeSettings())).get("/api/v1/runs?since_days=36500")
    body = r.json()
    assert r.status_code == 200
    assert body["items"]
    for item in body["items"]:
        assert "display_title" in item
        assert "usage" in item
        assert "import_state" in item
        # Container fixtures have no importer artifacts → all three are null.
        assert item["display_title"] is None
        assert item["usage"] is None
        assert item["import_state"] is None
    # Web layer must NEVER expose importer artifact's source_path.
    import json as _json
    assert "source_path" not in _json.dumps(body)
