"""--dev-proxy smoke test."""
from __future__ import annotations

from fastapi.testclient import TestClient

from agentlens.web.app import create_app
from agentlens.web.settings import ServeSettings


def test_dev_proxy_does_not_fail_to_mount(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTLENS_HOME", str(tmp_path))
    s = ServeSettings(dev_proxy="http://127.0.0.1:5173")
    app = create_app(s)
    r = TestClient(app).get("/api/v1/meta")
    assert r.status_code == 200


def test_dev_proxy_unknown_api_route_stays_404_problem(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTLENS_HOME", str(tmp_path))
    s = ServeSettings(dev_proxy="http://127.0.0.1:5173")
    r = TestClient(create_app(s)).get("/api/v1/missing")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/problem+json")
