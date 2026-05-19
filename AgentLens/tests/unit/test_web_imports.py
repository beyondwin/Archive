"""Smoke test: web backend modules import without error."""
from __future__ import annotations


def test_web_package_importable():
    import agentlens.web  # noqa: F401


def test_fastapi_installed():
    import fastapi  # noqa: F401


def test_uvicorn_installed():
    import uvicorn  # noqa: F401


def test_pydantic_settings_installed():
    import pydantic_settings  # noqa: F401
