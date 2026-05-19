"""/api/v1/meta."""
from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from agentlens.web.deps import resolve_home, store_exists

router = APIRouter(prefix="/api/v1", tags=["meta"])
SCHEMA_VERSION = "v1"


def _agentlens_version() -> str:
    try:
        return version("agentlens")
    except PackageNotFoundError:
        return "0.0.0+dev"


@router.get("/meta")
def meta(request: Request) -> JSONResponse:
    settings = request.app.state.settings
    return JSONResponse(
        {
            "agentlens_version": _agentlens_version(),
            "schema_version": SCHEMA_VERSION,
            "store_path": str(resolve_home()),
            "store_exists": store_exists(),
            "demo_mode": bool(settings.demo),
        }
    )


__all__ = ["router"]
