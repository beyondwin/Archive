"""Tests for per-run failures/risks/artifacts endpoints."""
from __future__ import annotations

import json
import hashlib
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
    monkeypatch.setenv("AGENTLENS_HOME", str(tmp_path))
    return tmp_path


def test_per_run_failures(home):
    run_id = json.loads((FIXTURES / "failed_command_run" / "run.json").read_text())[
        "run_id"
    ]
    r = TestClient(create_app(ServeSettings())).get(f"/api/v1/runs/{run_id}/failures")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_per_run_risks(home):
    run_id = json.loads((FIXTURES / "failed_command_run" / "run.json").read_text())[
        "run_id"
    ]
    r = TestClient(create_app(ServeSettings())).get(f"/api/v1/runs/{run_id}/risks")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_per_run_artifacts(home):
    run_id = json.loads((FIXTURES / "failed_command_run" / "run.json").read_text())[
        "run_id"
    ]
    r = TestClient(create_app(ServeSettings())).get(f"/api/v1/runs/{run_id}/artifacts")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_artifact_download_redacted_header(monkeypatch, tmp_path):
    runs = tmp_path / "runs" / "ws_demo" / "art_run"
    runs.mkdir(parents=True)
    digest = "sha256:" + "0" * 64
    (runs / "manifest.json").write_text(
        json.dumps({"files": [{"path": "artifacts/out.txt", "sha256": digest}]}),
        encoding="utf-8",
    )
    (runs / "run.json").write_text(
        json.dumps(
            {
                "schema": "agentlens.run.v1",
                "run_id": "art_run",
                "workspace_id": "ws_demo",
                "started_at": "2026-01-01T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    artifacts_dir = runs / "artifacts"
    artifacts_dir.mkdir()
    (artifacts_dir / "out.txt").write_bytes(b"hello")
    monkeypatch.setenv("AGENTLENS_HOME", str(tmp_path))

    r = TestClient(create_app(ServeSettings())).get(
        "/api/v1/runs/art_run/artifacts/" + digest
    )
    assert r.status_code == 200
    assert r.content == b"hello"
    assert r.headers.get("x-agentlens-redacted") == "true"


def test_artifact_paths_cannot_escape_artifacts_dir(monkeypatch, tmp_path):
    runs = tmp_path / "runs" / "ws_demo" / "art_run"
    runs.mkdir(parents=True)
    run_json = json.dumps(
        {
            "schema": "agentlens.run.v1",
            "run_id": "art_run",
            "workspace_id": "ws_demo",
            "started_at": "2026-01-01T00:00:00Z",
        }
    )
    digest = "sha256:" + hashlib.sha256(run_json.encode()).hexdigest()
    (runs / "run.json").write_text(run_json, encoding="utf-8")
    (runs / "manifest.json").write_text(
        json.dumps({"files": [{"path": "artifacts/../run.json", "sha256": digest}]}),
        encoding="utf-8",
    )
    (runs / "artifacts").mkdir()
    monkeypatch.setenv("AGENTLENS_HOME", str(tmp_path))

    client = TestClient(create_app(ServeSettings()))
    list_response = client.get("/api/v1/runs/art_run/artifacts")
    assert list_response.status_code == 200
    assert list_response.json()[0]["downloadable"] is False

    download_response = client.get("/api/v1/runs/art_run/artifacts/" + digest)
    assert download_response.status_code == 404
