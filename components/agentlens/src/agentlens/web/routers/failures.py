"""/api/v1/failures and /api/v1/risks."""
from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from agentlens.commands._format import project_failure, project_risk
from agentlens.store import query as store_query
from agentlens.web.deps import resolve_home

router = APIRouter(prefix="/api/v1", tags=["failures-risks"])


@router.get("/failures")
def list_failures(
    workspace_id: str | None = Query(None),
    since_days: int = Query(30, ge=1, le=36500),
) -> JSONResponse:
    rows = store_query.failures(resolve_home(), since_days=since_days)
    if workspace_id is not None:
        rows = [r for r in rows if r.get("workspace_id") == workspace_id]
    return JSONResponse([project_failure(r) for r in rows])


@router.get("/risks")
def list_risks(
    workspace_id: str | None = Query(None),
    since_days: int = Query(30, ge=1, le=36500),
) -> JSONResponse:
    rows = store_query.risks(resolve_home(), since_days=since_days)
    if workspace_id is not None:
        rows = [r for r in rows if r.get("workspace_id") == workspace_id]
    return JSONResponse([project_risk(r) for r in rows])


__all__ = ["router"]
