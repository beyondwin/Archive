"""Read facade over the run store (spec §S1.6.9, §5.8a).

This module is the *single read entry-point* for run/eval/risk metadata. It
prefers the SQLite index for performance but transparently falls back to a
filesystem full-scan when the index is absent, corrupt, or otherwise
unavailable, so query results remain correct even if the cache is degraded.

Per the task_9 decision: the query facade is the only read consumer; it must
*not* import :mod:`agentlens.store.sqlite_index` (writer module). The DB is
opened directly via ``sqlite3.connect("file:.../index.db?mode=ro", uri=True)``.

Public API (spec-canonical):
    latest(home, workspace_id=None) -> dict | None
    failures(home, *, since_days=30) -> list[dict]
    risks(home, *, since_days=30) -> list[dict]
    full_scan_runs(home) -> list[dict]

Plan-aliased convenience wrappers (per task_2 decision):
    latest_run        = latest
    list_failures     = failures
    list_risks        = risks
    list_runs(home, filters=None) -> list[dict]
    get_run(home, run_id)         -> dict | None
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Columns we expose in the canonical "run row" shape (parity between the
# SQLite-backed path and the full-scan fallback).
_RUN_ROW_COLUMNS = (
    "run_id",
    "workspace_id",
    "parent_run_id",
    "started_at",
    "ended_at",
    "agent_name",
    "agent_mode",
    "recording_mode",
    "agent_outcome",
    "eval_status",
    "sealed_phase",
)

_REQUIRED_RUN_FIELDS = ("run_id", "workspace_id", "started_at")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _index_db_path(home: Path) -> Path:
    return Path(home) / "index.db"


def _runs_root(home: Path) -> Path:
    return Path(home) / "runs"


def _open_index_readonly(home: Path) -> sqlite3.Connection | None:
    """Open ``<home>/index.db`` read-only or return ``None``.

    NOTE: we do *not* import :mod:`agentlens.store.sqlite_index` (per
    task_9: that module is the writer; query consumers connect directly).
    Missing file → return None silently. Open errors → log warning + None.
    """
    db_path = _index_db_path(home)
    if not db_path.is_file():
        return None
    try:
        # ``mode=ro`` ensures we cannot mutate the writer's database.
        return sqlite3.connect(
            f"file:{db_path}?mode=ro", uri=True, isolation_level=None
        )
    except sqlite3.Error as exc:
        logger.warning("store.query: cannot open index.db (%s); using full-scan", exc)
        return None


def _read_json(path: Path) -> dict[str, Any] | None:
    """Read JSON, returning ``None`` on missing/parse error."""
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("store.query: failed to read %s: %s", path, exc)
        return None


def _row_from_run_dir(run_dir: Path) -> dict[str, Any] | None:
    """Build a canonical run-row dict from a run directory.

    Returns ``None`` when ``run.json`` is missing/unparseable or lacks
    required fields. Callers may treat that as a schema-invalid signal.
    """
    run_doc = _read_json(run_dir / "run.json")
    if not run_doc:
        return None
    for field in _REQUIRED_RUN_FIELDS:
        if not run_doc.get(field):
            return None
    agent = run_doc.get("agent") or {}
    recording = run_doc.get("recording") or {}
    if not agent.get("name") or not agent.get("mode") or not recording.get("mode"):
        return None

    final_doc = _read_json(run_dir / "final.json") or {}
    eval_doc = _read_json(run_dir / "eval.json") or {}
    manifest_doc = _read_json(run_dir / "manifest.json") or {}

    row: dict[str, Any] = {
        "run_id": run_doc.get("run_id"),
        "workspace_id": run_doc.get("workspace_id"),
        "parent_run_id": run_doc.get("parent_run_id"),
        "started_at": run_doc.get("started_at"),
        "ended_at": final_doc.get("ended_at"),
        "agent_name": agent.get("name"),
        "agent_mode": agent.get("mode"),
        "recording_mode": recording.get("mode"),
        "agent_outcome": final_doc.get("agent_outcome"),
        "eval_status": eval_doc.get("status"),
        "sealed_phase": manifest_doc.get("sealed_phase"),
    }
    # Merge eval-doc top-level "status" for callers that look at the raw key.
    if eval_doc.get("status") is not None:
        row.setdefault("status", eval_doc.get("status"))
    if final_doc.get("residual_risks") is not None:
        row["residual_risks"] = final_doc.get("residual_risks")
    return row


def _iter_run_dirs(home: Path, workspace_id: str | None = None):
    """Yield run directories under ``<home>/runs`` in deterministic order."""
    root = _runs_root(home)
    if not root.is_dir():
        return
    if workspace_id is not None:
        ws_dirs = [root / workspace_id]
    else:
        ws_dirs = sorted(p for p in root.iterdir() if p.is_dir())
    for ws_dir in ws_dirs:
        if not ws_dir.is_dir():
            continue
        for run_dir in sorted(p for p in ws_dir.iterdir() if p.is_dir()):
            yield run_dir


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    s = ts.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _since_cutoff(since_days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=since_days)


def _is_recent(row_started_at: str | None, cutoff: datetime) -> bool:
    """Return True if ``row_started_at`` is on/after cutoff. Missing → True
    (we prefer to surface a record than to silently drop it)."""
    dt = _parse_iso(row_started_at)
    if dt is None:
        return True
    return dt >= cutoff


# ---------------------------------------------------------------------------
# latest()
# ---------------------------------------------------------------------------


def _latest_via_sqlite(
    conn: sqlite3.Connection, workspace_id: str | None
) -> dict[str, Any] | None:
    try:
        if workspace_id is None:
            cur = conn.execute(
                "SELECT run_id, workspace_id, parent_run_id, started_at, ended_at, "
                "agent_name, agent_mode, recording_mode, agent_outcome, eval_status, "
                "sealed_phase FROM runs ORDER BY started_at DESC LIMIT 1"
            )
        else:
            cur = conn.execute(
                "SELECT run_id, workspace_id, parent_run_id, started_at, ended_at, "
                "agent_name, agent_mode, recording_mode, agent_outcome, eval_status, "
                "sealed_phase FROM runs WHERE workspace_id = ? "
                "ORDER BY started_at DESC LIMIT 1",
                (workspace_id,),
            )
        row = cur.fetchone()
    except sqlite3.Error as exc:
        logger.warning("store.query: index query failed (%s); using full-scan", exc)
        return None
    if row is None:
        return None
    return dict(zip(_RUN_ROW_COLUMNS, row))


def _latest_via_full_scan(
    home: Path, workspace_id: str | None
) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    for run_dir in _iter_run_dirs(home, workspace_id):
        row = _row_from_run_dir(run_dir)
        if row is None:
            continue
        if best is None or (row.get("started_at") or "") > (best.get("started_at") or ""):
            best = row
    return best


def latest(home: Path, workspace_id: str | None = None) -> dict[str, Any] | None:
    """Return the newest run row (or ``None``).

    Uses the SQLite index when available and healthy; falls back to a
    deterministic filesystem scan when the index is missing, corrupt, or
    its query errors.
    """
    home = Path(home)
    conn = _open_index_readonly(home)
    if conn is not None:
        try:
            row = _latest_via_sqlite(conn, workspace_id)
        finally:
            try:
                conn.close()
            except sqlite3.Error:
                pass
        if row is not None:
            return row
        # SQLite returned no row OR query errored → cross-check via full-scan
        # before declaring "no runs"; the index may simply be empty (we still
        # want the canonical answer) or have been corrupted between connect()
        # and query.
        return _latest_via_full_scan(home, workspace_id)
    return _latest_via_full_scan(home, workspace_id)


# ---------------------------------------------------------------------------
# failures()
# ---------------------------------------------------------------------------


def failures(home: Path, *, since_days: int = 30) -> list[dict[str, Any]]:
    """Return all eval failures from the durable store within ``since_days``.

    Spec: "eval.json failures를 durable store 기준으로 반환. SQLite는 cache."
    We always read failure detail dicts from ``eval.json`` on disk; SQLite is
    only ever consulted for run-id discovery. On any SQLite error we fall
    back to the filesystem walk.
    """
    home = Path(home)
    cutoff = _since_cutoff(since_days)
    out: list[dict[str, Any]] = []
    for run_dir in _iter_run_dirs(home):
        run_doc = _read_json(run_dir / "run.json")
        if not run_doc:
            continue
        started_at = run_doc.get("started_at")
        if not _is_recent(started_at, cutoff):
            continue
        eval_doc = _read_json(run_dir / "eval.json")
        if not eval_doc:
            continue
        for failure in eval_doc.get("failures") or []:
            out.append(
                {
                    **failure,
                    "run_id": run_doc.get("run_id"),
                    "workspace_id": run_doc.get("workspace_id"),
                }
            )
    # Deterministic sort: run_id, then category.
    out.sort(key=lambda f: (f.get("run_id") or "", f.get("category") or ""))
    return out


# ---------------------------------------------------------------------------
# risks()
# ---------------------------------------------------------------------------


def risks(home: Path, *, since_days: int = 30) -> list[dict[str, Any]]:
    """Aggregate residual-risk indicators across three sources (spec §5.8a).

    - ``final.residual_risks[]``        → source = ``final.residual_risks``
    - ``eval.failures[]``               → source = ``eval.failures``
    - manifests with ``sealed_phase ==  "recording_incomplete"`` →
        synthetic ``{"category": "RECORDING_INCOMPLETE",
                     "source": "manifest.sealed_phase"}``
    - schema-invalid ``run.json`` (from :func:`full_scan_runs`) →
        synthetic ``{"category": "SCHEMA_INVALID",
                     "source": "store.full_scan"}``
    """
    home = Path(home)
    cutoff = _since_cutoff(since_days)
    out: list[dict[str, Any]] = []

    for run_dir in _iter_run_dirs(home):
        run_doc = _read_json(run_dir / "run.json")
        if not run_doc:
            # Schema-invalid: surface via SCHEMA_INVALID. Derive run_id from
            # directory name; workspace_id from parent dir name.
            out.append(
                {
                    "category": "SCHEMA_INVALID",
                    "source": "store.full_scan",
                    "run_id": run_dir.name,
                    "workspace_id": run_dir.parent.name,
                }
            )
            continue
        started_at = run_doc.get("started_at")
        if not _is_recent(started_at, cutoff):
            continue
        run_id = run_doc.get("run_id")
        workspace_id = run_doc.get("workspace_id")

        final_doc = _read_json(run_dir / "final.json") or {}
        for residual in final_doc.get("residual_risks") or []:
            out.append(
                {
                    **(residual if isinstance(residual, dict) else {"summary": residual}),
                    "run_id": run_id,
                    "workspace_id": workspace_id,
                    "source": "final.residual_risks",
                }
            )

        eval_doc = _read_json(run_dir / "eval.json") or {}
        for failure in eval_doc.get("failures") or []:
            out.append(
                {
                    **failure,
                    "run_id": run_id,
                    "workspace_id": workspace_id,
                    "source": "eval.failures",
                }
            )

        manifest_doc = _read_json(run_dir / "manifest.json") or {}
        if manifest_doc.get("sealed_phase") == "recording_incomplete":
            out.append(
                {
                    "category": "RECORDING_INCOMPLETE",
                    "run_id": run_id,
                    "workspace_id": workspace_id,
                    "source": "manifest.sealed_phase",
                }
            )

    out.sort(
        key=lambda r: (
            r.get("run_id") or "",
            r.get("source") or "",
            r.get("category") or "",
        )
    )
    return out


# ---------------------------------------------------------------------------
# full_scan_runs()
# ---------------------------------------------------------------------------


def full_scan_runs(home: Path) -> list[dict[str, Any]]:
    """Scan ``home/runs/**/run.json`` deterministically.

    Healthy runs are returned as merged dicts (parity with the SQLite row
    shape). Schema-invalid runs are surfaced as a risk indicator
    ``{"schema_invalid": True, ...}`` rather than dropped.
    """
    home = Path(home)
    out: list[dict[str, Any]] = []
    for run_dir in _iter_run_dirs(home):
        row = _row_from_run_dir(run_dir)
        if row is None:
            out.append(
                {
                    "run_id": run_dir.name,
                    "workspace_id": run_dir.parent.name,
                    "schema_invalid": True,
                    "_source_dir": str(run_dir),
                }
            )
        else:
            out.append(row)
    return out


# ---------------------------------------------------------------------------
# list_runs() / get_run() — plan-aliased helpers
# ---------------------------------------------------------------------------


_FILTERABLE_KEYS = ("workspace_id", "agent_outcome", "eval_status")


def list_runs(
    home: Path, filters: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Return runs (full-scan rows), optionally filtered.

    Supported filter keys (v0): ``workspace_id``, ``agent_outcome``,
    ``eval_status``. Unknown keys are silently ignored (forward-compatible).
    Schema-invalid rows are kept in the result so callers can choose how to
    surface them.
    """
    rows = full_scan_runs(home)
    if not filters:
        return rows

    def _matches(row: dict[str, Any]) -> bool:
        if row.get("schema_invalid"):
            # Schema-invalid rows lack the indexed fields; drop them when any
            # positive filter is applied.
            return False
        for key in _FILTERABLE_KEYS:
            if key in filters and row.get(key) != filters[key]:
                return False
        return True

    return [r for r in rows if _matches(r)]


def get_run(home: Path, run_id: str) -> dict[str, Any] | None:
    """Return a merged dict for a single run, or ``None`` if not found.

    Merge order (last writer wins on key conflicts):
      run.json → final.json → eval.json → manifest.json
    """
    home = Path(home)
    root = _runs_root(home)
    if not root.is_dir():
        return None
    target: Path | None = None
    for ws_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        candidate = ws_dir / run_id
        if candidate.is_dir():
            target = candidate
            break
    if target is None:
        return None
    run_doc = _read_json(target / "run.json") or {}
    final_doc = _read_json(target / "final.json") or {}
    eval_doc = _read_json(target / "eval.json") or {}
    manifest_doc = _read_json(target / "manifest.json") or {}
    merged: dict[str, Any] = {}
    merged.update(run_doc)
    merged.update(final_doc)
    merged.update(eval_doc)
    merged.update(manifest_doc)
    return merged


# ---------------------------------------------------------------------------
# Plan aliases (per task_2 decision)
# ---------------------------------------------------------------------------

latest_run = latest
list_failures = failures
list_risks = risks


__all__ = [
    "failures",
    "full_scan_runs",
    "get_run",
    "latest",
    "latest_run",
    "list_failures",
    "list_risks",
    "list_runs",
    "risks",
]
