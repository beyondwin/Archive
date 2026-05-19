"""Boot the FastAPI app via TestClient and hit /healthz."""
from __future__ import annotations

from fastapi.testclient import TestClient

from agentlens.web.app import create_app
from agentlens.web.settings import ServeSettings


def test_healthz_returns_ok():
    app = create_app(ServeSettings())
    with TestClient(app) as client:
        r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
