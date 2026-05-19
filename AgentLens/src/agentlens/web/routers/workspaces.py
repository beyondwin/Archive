"""/api/v1/workspaces."""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from agentlens.commands._format import project_run_row
from agentlens.store import query as store_query
from agentlens.web.deps import resolve_home

router = APIRouter(prefix="/api/v1/workspaces", tags=["workspaces"])


def _workspace_dirs(home: Path) -> list[Path]:
    runs_root = Path(home) / "runs"
    if not runs_root.exists():
        return []
    return sorted(p for p in runs_root.iterdir() if p.is_dir())


def _runs_for_workspace(home: Path, workspace_id: str) -> list[dict]:
    rows = store_query.list_runs(home, filters={"workspace_id": workspace_id})
    return sorted(rows, key=lambda r: r.get("started_at") or "", reverse=True)


@router.get("")
def list_workspaces() -> JSONResponse:
    home = resolve_home()
    items = []
    for ws_dir in _workspace_dirs(home):
        workspace_id = ws_dir.name
        rows = _runs_for_workspace(home, workspace_id)
        latest = max((r.get("started_at") or "" for r in rows), default=None)
        items.append(
            {
                "workspace_id": workspace_id,
                "workspace_short": workspace_id[:11],
                "id_basis": "git" if workspace_id.startswith("ws_") else "path",
                "run_count": len(rows),
                "latest_started_at": latest,
            }
        )
    return JSONResponse(items)


@router.get("/{workspace_id}")
def get_workspace(
    workspace_id: str,
    recent_limit: int = Query(20, ge=1, le=200),
) -> JSONResponse:
    home = resolve_home()
    rows = _runs_for_workspace(home, workspace_id)
    if not rows:
        raise HTTPException(status_code=404, detail=f"workspace not found: {workspace_id}")

    passed = sum(1 for row in rows if row.get("eval_status") == "passed")
    evaluated = sum(
        1 for row in rows if row.get("eval_status") in {"passed", "failed"}
    )
    agents = Counter(row.get("agent_name") for row in rows if row.get("agent_name"))
    return JSONResponse(
        {
            "workspace_id": workspace_id,
            "workspace_short": workspace_id[:11],
            "id_basis": "git" if workspace_id.startswith("ws_") else "path",
            "run_count": len(rows),
            "recent_runs": [project_run_row(r) for r in rows[:recent_limit]],
            "eval_pass_rate_30d": (passed / evaluated) if evaluated else None,
            "agent_breakdown": dict(agents),
        }
    )


__all__ = ["router"]
