"""Common response headers."""
from __future__ import annotations

from fastapi.testclient import TestClient

from agentlens.web.app import create_app
from agentlens.web.settings import ServeSettings


def _client(settings: ServeSettings) -> TestClient:
    return TestClient(create_app(settings))


def test_security_headers_present_on_healthz():
    r = _client(ServeSettings()).get("/healthz")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert r.headers["cross-origin-opener-policy"] == "same-origin"
    assert r.headers["cache-control"] == "no-store"


def test_warning_header_absent_on_loopback():
    r = _client(ServeSettings(host="127.0.0.1")).get("/healthz")
    assert "x-agentlens-warning" not in r.headers


def test_warning_header_present_on_non_loopback():
    r = _client(ServeSettings(host="0.0.0.0")).get("/healthz")
    assert r.headers.get("x-agentlens-warning") == "bound-to-non-loopback"


def test_cors_absent_by_default():
    r = _client(ServeSettings()).get("/healthz", headers={"Origin": "http://x.test"})
    assert "access-control-allow-origin" not in r.headers


def test_explicit_cors_origin_allowed():
    r = _client(ServeSettings(allow_origin=("http://127.0.0.1:5173",))).get(
        "/healthz", headers={"Origin": "http://127.0.0.1:5173"}
    )
    assert r.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
