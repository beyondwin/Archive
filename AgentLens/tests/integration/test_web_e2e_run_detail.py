"""Tests for /api/v1/runs/{id} and /api/v1/runs/{id}/verify."""
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
def home_with_minimal(monkeypatch, tmp_path):
    copy_fixture_as_run_id(FIXTURES, "minimal_run", tmp_path / "runs")
    monkeypatch.setenv("AGENTLENS_HOME", str(tmp_path))
    return tmp_path


def test_run_detail_present(home_with_minimal):
    run_id = json.loads((FIXTURES / "minimal_run" / "run.json").read_text())["run_id"]
    r = TestClient(create_app(ServeSettings())).get(f"/api/v1/runs/{run_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["run_id"] == run_id
    assert "agent_outcome" in body
    assert "eval_status" in body
    assert "manifest_seal" in body


def test_run_detail_404(home_with_minimal):
    r = TestClient(create_app(ServeSettings())).get("/api/v1/runs/nope")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/problem+json")


def test_run_verify(home_with_minimal):
    run_id = json.loads((FIXTURES / "minimal_run" / "run.json").read_text())["run_id"]
    r = TestClient(create_app(ServeSettings())).get(f"/api/v1/runs/{run_id}/verify")
    body = r.json()
    assert r.status_code == 200
    assert "ok" in body
    assert "mismatches" in body


def test_run_detail_includes_import_projection_keys_and_no_source_path(
    home_with_minimal,
):
    """task_18: detail payload carries display_title/usage/import_state and
    must not expose the importer artifact's ``source_path`` field."""
    run_id = json.loads((FIXTURES / "minimal_run" / "run.json").read_text())["run_id"]
    r = TestClient(create_app(ServeSettings())).get(f"/api/v1/runs/{run_id}")
    assert r.status_code == 200
    body = r.json()
    assert "display_title" in body
    assert "usage" in body
    assert "import_state" in body
    # minimal_run is a container run with no importer artifacts.
    assert body["display_title"] is None
    assert body["usage"] is None
    assert body["import_state"] is None
    assert "source_path" not in json.dumps(body)
