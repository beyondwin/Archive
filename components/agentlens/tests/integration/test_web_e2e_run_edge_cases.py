"""Edge cases: partial runs, schema mismatch, corrupt manifest."""
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
    (tmp_path / "runs" / "ws_demo").mkdir(parents=True)
    monkeypatch.setenv("AGENTLENS_HOME", str(tmp_path))
    return tmp_path


def test_partial_run_returns_200_with_marker(home):
    run_id = copy_fixture_as_run_id(FIXTURES, "missing_final_run", home / "runs")[1]
    r = TestClient(create_app(ServeSettings())).get(f"/api/v1/runs/{run_id}")
    assert r.status_code == 200
    assert r.json().get("partial") is True


def test_unknown_schema_version_returns_412(home):
    rd = home / "runs" / "ws_demo" / "future_run"
    rd.mkdir(parents=True)
    (rd / "run.json").write_text(
        json.dumps(
            {
                "schema": "agentlens.run.v2",
                "run_id": "future_run",
                "workspace_id": "ws_demo",
                "started_at": "2026-01-01T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    (rd / "events.jsonl").write_text("", encoding="utf-8")
    r = TestClient(create_app(ServeSettings())).get("/api/v1/runs/future_run")
    assert r.status_code == 412
    assert r.json()["title"] == "Precondition Failed"


def test_non_agentlens_v1_schema_returns_412(home):
    rd = home / "runs" / "ws_demo" / "foreign_run"
    rd.mkdir(parents=True)
    (rd / "run.json").write_text(
        json.dumps(
            {
                "schema": "other.run.v1",
                "run_id": "foreign_run",
                "workspace_id": "ws_demo",
                "started_at": "2026-01-01T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    (rd / "events.jsonl").write_text("", encoding="utf-8")
    r = TestClient(create_app(ServeSettings())).get("/api/v1/runs/foreign_run")
    assert r.status_code == 412
    assert r.json()["title"] == "Precondition Failed"


@pytest.mark.parametrize("schema", ["agentlens.run.v2", "other.run.v1"])
def test_unsupported_schema_returns_412_for_all_run_scoped_endpoints(home, schema):
    rd = home / "runs" / "ws_demo" / "future_run"
    rd.mkdir(parents=True)
    digest = "sha256:" + "1" * 64
    (rd / "run.json").write_text(
        json.dumps(
            {
                "schema": schema,
                "run_id": "future_run",
                "workspace_id": "ws_demo",
                "started_at": "2026-01-01T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    (rd / "events.jsonl").write_text("{}\n", encoding="utf-8")
    (rd / "manifest.json").write_text(
        json.dumps({"files": [{"path": "artifacts/out.txt", "sha256": digest}]}),
        encoding="utf-8",
    )
    (rd / "artifacts").mkdir()
    (rd / "artifacts" / "out.txt").write_text("artifact", encoding="utf-8")

    client = TestClient(create_app(ServeSettings()))
    paths = [
        "/api/v1/runs/future_run",
        "/api/v1/runs/future_run/events",
        "/api/v1/runs/future_run/failures",
        "/api/v1/runs/future_run/risks",
        "/api/v1/runs/future_run/artifacts",
        f"/api/v1/runs/future_run/artifacts/{digest}",
        "/api/v1/runs/future_run/verify",
    ]

    for path in paths:
        r = client.get(path)
        assert r.status_code == 412, path
        assert r.json()["title"] == "Precondition Failed"


def test_corrupt_manifest_flagged_but_200(home):
    run_id = copy_fixture_as_run_id(FIXTURES, "corrupt_manifest_run", home / "runs")[1]
    r = TestClient(create_app(ServeSettings())).get(f"/api/v1/runs/{run_id}")
    assert r.status_code == 200
    seal = r.json().get("manifest_seal") or {}
    assert seal.get("integrity") == "broken"
