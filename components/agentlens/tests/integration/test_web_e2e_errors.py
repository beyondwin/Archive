"""ProblemDetails error mapping."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.testclient import TestClient

from agentlens.web.app import create_app
from agentlens.web.settings import ServeSettings


def _client(settings: ServeSettings) -> TestClient:
    app = create_app(settings)
    router = APIRouter()

    @router.get("/boom")
    def boom():
        raise RuntimeError("intentional")

    @router.get("/notfound")
    def notfound():
        raise HTTPException(status_code=404, detail="missing thing")

    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


def test_unhandled_500_is_problem_json_without_traceback():
    r = _client(ServeSettings(debug=False)).get("/boom")
    assert r.status_code == 500
    assert r.headers["content-type"].startswith("application/problem+json")
    body = r.json()
    assert body["status"] == 500
    assert body["title"] == "Internal Server Error"
    assert "correlation_id" in body
    assert "intentional" not in body.get("detail", "")


def test_debug_mode_includes_detail():
    r = _client(ServeSettings(debug=True)).get("/boom")
    assert r.status_code == 500
    assert "intentional" in r.json()["detail"]


def test_httpexception_is_mapped():
    r = _client(ServeSettings()).get("/notfound")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["title"] == "Not Found"
