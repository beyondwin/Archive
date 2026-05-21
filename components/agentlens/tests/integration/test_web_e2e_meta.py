"""Tests for /api/v1/meta."""
from __future__ import annotations

from fastapi.testclient import TestClient

from agentlens.web.app import create_app
from agentlens.web.settings import ServeSettings


def test_meta_empty_store(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTLENS_HOME", str(tmp_path))
    r = TestClient(create_app(ServeSettings())).get("/api/v1/meta")
    assert r.status_code == 200
    body = r.json()
    assert body["agentlens_version"]
    assert body["schema_version"] == "v1"
    assert body["store_path"] == str(tmp_path)
    assert body["store_exists"] is False
    assert body["demo_mode"] is False


def test_meta_existing_store(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTLENS_HOME", str(tmp_path))
    (tmp_path / "runs").mkdir()
    r = TestClient(create_app(ServeSettings(demo=True))).get("/api/v1/meta")
    body = r.json()
    assert body["store_exists"] is True
    assert body["demo_mode"] is True
