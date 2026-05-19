"""Test that /api/v1/doctor mirrors the CLI doctor JSON output."""
from __future__ import annotations

from fastapi.testclient import TestClient

from agentlens.web.app import create_app
from agentlens.web.settings import ServeSettings


def test_doctor_returns_structured_payload(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTLENS_HOME", str(tmp_path))
    r = TestClient(create_app(ServeSettings())).get("/api/v1/doctor")
    assert r.status_code == 200
    body = r.json()
    for key in ("integrations", "paths", "warnings"):
        assert key in body
