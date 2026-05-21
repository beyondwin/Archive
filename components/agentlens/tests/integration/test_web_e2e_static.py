"""Static SPA serving behavior."""
from __future__ import annotations

from fastapi.testclient import TestClient

from agentlens.web.app import create_app
from agentlens.web.settings import ServeSettings


def test_spa_deep_link_falls_back_to_index(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTLENS_HOME", str(tmp_path))
    index = tmp_path / "index.html"
    index.write_text("<!doctype html><div id=\"root\"></div>", encoding="utf-8")
    app = create_app(ServeSettings())
    app.state.spa_index = index

    r = TestClient(app).get("/runs/run_123")

    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert '<div id="root"></div>' in r.text


def test_unknown_api_route_stays_problem_json(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTLENS_HOME", str(tmp_path))
    index = tmp_path / "index.html"
    index.write_text("<!doctype html><div id=\"root\"></div>", encoding="utf-8")
    app = create_app(ServeSettings())
    app.state.spa_index = index

    r = TestClient(app).get("/api/v1/nope")

    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/problem+json")
