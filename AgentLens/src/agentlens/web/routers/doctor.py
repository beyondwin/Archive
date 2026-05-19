"""/api/v1/doctor."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from agentlens.commands.doctor import collect_doctor_report

router = APIRouter(prefix="/api/v1", tags=["doctor"])


@router.get("/doctor")
def doctor() -> JSONResponse:
    return JSONResponse(collect_doctor_report("all"))


__all__ = ["router"]
