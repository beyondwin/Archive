"""/api/v1/runs."""
from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterator

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse, Response, StreamingResponse

from agentlens.commands._format import (
    project_failure,
    project_risk,
    project_run_row,
    project_show,
)
from agentlens.commands._query_format import workspace_short
from agentlens.store import manifest as manifest_store
from agentlens.store import query as store_query
from agentlens.web.deps import resolve_home

router = APIRouter(prefix="/api/v1/runs", tags=["runs"])


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(json.dumps({"o": offset}).encode()).decode()


def _decode_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        return int(json.loads(base64.urlsafe_b64decode(cursor.encode()))["o"])
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"invalid cursor: {exc}") from None


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _run_dir_for(home: Path, run_id: str) -> Path | None:
    runs_root = Path(home) / "runs"
    if not runs_root.is_dir():
        return None
    for ws_dir in sorted(p for p in runs_root.iterdir() if p.is_dir()):
        candidate = ws_dir / run_id
        if candidate.is_dir():
            return candidate
    return None


def _load_manifest(run_dir: Path) -> dict[str, Any] | None:
    return _read_json(run_dir / "manifest.json")


def _manifest_digest(run_dir: Path) -> str | None:
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.is_file():
        return None
    return "sha256:" + hashlib.sha256(manifest_path.read_bytes()).hexdigest()


def _detect_schema(run_dir: Path) -> str:
    run_doc = _read_json(run_dir / "run.json") or {}
    return str(run_doc.get("schema") or "agentlens.run.v1")


def _ensure_supported_schema(run_dir: Path) -> None:
    schema = _detect_schema(run_dir)
    if not schema.startswith("agentlens.") or not schema.endswith(".v1"):
        raise HTTPException(
            status_code=412,
            detail=f"unsupported run schema {schema!r}; viewer supports agentlens.*.v1",
        )


def _detect_partial(run_dir: Path) -> bool:
    return not (run_dir / "final.json").is_file() or not (run_dir / "manifest.json").is_file()


def _failure_counts_by_run(home: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    for failure in store_query.failures(home, since_days=36500):
        run_id = failure.get("run_id")
        if isinstance(run_id, str) and run_id:
            counts[run_id] = counts.get(run_id, 0) + 1
    return counts


def _safe_artifact_path(run_dir: Path, raw_path: object) -> Path | None:
    if not isinstance(raw_path, str):
        return None
    rel_path = PurePosixPath(raw_path)
    if rel_path.is_absolute() or len(rel_path.parts) < 2:
        return None
    if rel_path.parts[0] != "artifacts" or any(
        part in {"", ".", ".."} for part in rel_path.parts
    ):
        return None
    root = (run_dir / "artifacts").resolve()
    candidate = (run_dir / Path(*rel_path.parts)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def _manifest_seal(row: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    manifest = _load_manifest(run_dir)
    seal: dict[str, Any] = {"phase": row.get("sealed_phase")}
    if manifest is None:
        seal["integrity"] = "missing"
        seal["mismatches_count"] = 0
        return seal
    mismatches = manifest_store.verify(run_dir)
    seal.update(
        {
            "phase": manifest.get("sealed_phase") or row.get("sealed_phase"),
            "sealed_at": manifest.get("sealed_at"),
            "manifest_digest": _manifest_digest(run_dir),
            "integrity": "ok" if not mismatches else "broken",
            "mismatches_count": len(mismatches),
        }
    )
    return seal


def _detail_payload(home: Path, run_id: str, run_dir: Path) -> dict[str, Any]:
    row = store_query.get_run(home, run_id) or {}
    run_doc = _read_json(run_dir / "run.json") or {}
    final_doc = _read_json(run_dir / "final.json") or {}
    eval_doc = _read_json(run_dir / "eval.json") or {}
    manifest_doc = _read_json(run_dir / "manifest.json") or {}
    agent = run_doc.get("agent") or {}
    workspace_id = run_doc.get("workspace_id") or row.get("workspace_id") or run_dir.parent.name
    summary = {
        "run_id": run_id,
        "agent": agent.get("name") or row.get("agent_name") or "unknown",
        "started_at": run_doc.get("started_at") or row.get("started_at"),
        "agent_outcome": final_doc.get("agent_outcome") or row.get("agent_outcome"),
        "eval_status": eval_doc.get("status") or row.get("eval_status"),
        "sealed_phase": manifest_doc.get("sealed_phase") or row.get("sealed_phase"),
        "workspace_id": workspace_id,
        "workspace_short": workspace_short(workspace_id),
    }
    failures = [
        f for f in store_query.failures(home, since_days=36500) if f.get("run_id") == run_id
    ]
    risks = [
        r for r in store_query.risks(home, since_days=36500) if r.get("run_id") == run_id
    ]
    payload = project_show(summary, failures, risks)
    payload["agent_name"] = summary["agent"]
    payload["agent_mode"] = agent.get("mode") or row.get("agent_mode") or ""
    payload["ended_at"] = final_doc.get("ended_at") or row.get("ended_at") or ""
    payload["summary"] = final_doc.get("summary") or ""
    payload["manifest_seal"] = _manifest_seal({**row, **summary}, run_dir)
    if _detect_partial(run_dir):
        payload["partial"] = True
    return payload


@router.get("")
def list_runs(
    cursor: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    workspace_id: str | None = Query(None),
    agent: str | None = Query(None),
    eval_status: str | None = Query(None),
    agent_outcome: str | None = Query(None),
    since_days: int | None = Query(None, ge=1, le=36500),
) -> JSONResponse:
    home = resolve_home()
    offset = _decode_cursor(cursor)
    filters = {
        k: v
        for k, v in {
            "workspace_id": workspace_id,
            "eval_status": eval_status,
            "agent_outcome": agent_outcome,
        }.items()
        if v is not None
    }
    rows = store_query.list_runs(home, filters=filters)
    if agent is not None:
        rows = [r for r in rows if r.get("agent_name") == agent]
    if since_days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
        rows = [
            r
            for r in rows
            if (dt := _parse_iso(r.get("started_at"))) is None or dt >= cutoff
        ]
    rows = sorted(rows, key=lambda r: r.get("started_at") or "", reverse=True)
    failure_counts = _failure_counts_by_run(home)
    page = []
    for row in rows[offset : offset + limit]:
        projected = project_run_row(row)
        run_id = projected.get("run_id")
        if isinstance(run_id, str) and run_id:
            projected["failures_count"] = failure_counts.get(run_id, 0)
        page.append(projected)
    next_cursor = _encode_cursor(offset + limit) if offset + limit < len(rows) else None
    return JSONResponse({"items": page, "next_cursor": next_cursor})


def _iter_events(path: Path) -> Iterator[str]:
    with path.open(encoding="utf-8") as handle:
        for line_no, raw in enumerate(handle, start=1):
            raw = raw.rstrip("\n")
            if not raw.strip():
                continue
            try:
                json.loads(raw)
            except json.JSONDecodeError:
                yield json.dumps({"_error": "parse", "line": line_no}) + "\n"
            else:
                yield raw + "\n"


@router.get("/{run_id}/events")
def run_events(run_id: str) -> StreamingResponse:
    home = resolve_home()
    run_dir = _run_dir_for(home, run_id)
    events_path = run_dir / "events.jsonl" if run_dir is not None else None
    if run_dir is None or events_path is None or not events_path.is_file():
        raise HTTPException(status_code=404, detail=f"run not found: {run_id}")
    _ensure_supported_schema(run_dir)
    return StreamingResponse(_iter_events(events_path), media_type="application/x-ndjson")


@router.get("/{run_id}/failures")
def run_failures(run_id: str) -> JSONResponse:
    home = resolve_home()
    run_dir = _run_dir_for(home, run_id)
    if run_dir is None:
        raise HTTPException(status_code=404, detail=f"run not found: {run_id}")
    _ensure_supported_schema(run_dir)
    rows = [f for f in store_query.failures(home, since_days=36500) if f.get("run_id") == run_id]
    return JSONResponse([project_failure(f) for f in rows])


@router.get("/{run_id}/risks")
def run_risks(run_id: str) -> JSONResponse:
    home = resolve_home()
    run_dir = _run_dir_for(home, run_id)
    if run_dir is None:
        raise HTTPException(status_code=404, detail=f"run not found: {run_id}")
    _ensure_supported_schema(run_dir)
    rows = [r for r in store_query.risks(home, since_days=36500) if r.get("run_id") == run_id]
    return JSONResponse([project_risk(r) for r in rows])


@router.get("/{run_id}/artifacts")
def run_artifacts(run_id: str) -> JSONResponse:
    home = resolve_home()
    run_dir = _run_dir_for(home, run_id)
    manifest = _load_manifest(run_dir) if run_dir is not None else None
    if run_dir is None or manifest is None:
        raise HTTPException(status_code=404, detail=f"run not found: {run_id}")
    _ensure_supported_schema(run_dir)
    return JSONResponse(
        [
            {
                "path": entry.get("path"),
                "sha256": entry.get("sha256"),
                "downloadable": (
                    candidate is not None and candidate.is_file()
                )
                if (candidate := _safe_artifact_path(run_dir, entry.get("path"))) is not None
                else False,
            }
            for entry in manifest.get("files") or []
        ]
    )


@router.get("/{run_id}/artifacts/{sha256}")
def download_artifact(run_id: str, sha256: str) -> Response:
    home = resolve_home()
    run_dir = _run_dir_for(home, run_id)
    manifest = _load_manifest(run_dir) if run_dir is not None else None
    if run_dir is None or manifest is None:
        raise HTTPException(status_code=404, detail=f"run not found: {run_id}")
    _ensure_supported_schema(run_dir)
    for entry in manifest.get("files") or []:
        rel = str(entry.get("path", ""))
        candidate = _safe_artifact_path(run_dir, entry.get("path"))
        if entry.get("sha256") == sha256 and candidate is not None:
            if candidate.is_file():
                return Response(
                    content=candidate.read_bytes(),
                    media_type="application/octet-stream",
                    headers={
                        "Content-Disposition": f'attachment; filename="{Path(rel).name}"',
                        "X-AgentLens-Redacted": "true",
                    },
                )
    raise HTTPException(status_code=404, detail=f"artifact not found: {sha256}")


@router.get("/{run_id}/verify")
def verify_run(run_id: str) -> JSONResponse:
    home = resolve_home()
    run_dir = _run_dir_for(home, run_id)
    manifest = _load_manifest(run_dir) if run_dir is not None else None
    if run_dir is None or manifest is None:
        raise HTTPException(status_code=404, detail=f"run not found: {run_id}")
    _ensure_supported_schema(run_dir)
    expected = {item["path"]: item["sha256"] for item in manifest.get("files", [])}
    mismatches = [
        {"path": item.path, "expected": expected.get(item.path), "actual": item.sha256 or None}
        for item in manifest_store.verify(run_dir)
    ]
    return JSONResponse({"ok": not mismatches, "mismatches": mismatches})


@router.get("/{run_id}")
def get_run(run_id: str) -> JSONResponse:
    home = resolve_home()
    run_dir = _run_dir_for(home, run_id)
    if run_dir is None:
        raise HTTPException(status_code=404, detail=f"run not found: {run_id}")
    _ensure_supported_schema(run_dir)
    return JSONResponse(_detail_payload(home, run_id, run_dir))


__all__ = ["router"]
