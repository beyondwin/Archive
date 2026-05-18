"""SQLite index over the run tree (spec §5.8, §7.3, §S1.6.8, §S1.8.3).

This module is the *single writer* of the index database. It exposes a
small primitive surface — schema/open/upsert/rebuild — and intentionally
contains no query helpers; query consumers (CLI ``query`` command, dashboards)
read the DB directly with their own read-only connections.

The DB is treated as a derived cache: every column is reconstructible from
the canonical JSON artifacts under ``<home>/runs/<workspace_id>/<run_id>/``
(``run.json``, ``final.json``, ``eval.json``, ``manifest.json``). Per §7.3
writes are *best-effort* — parse / IO errors on a single run are logged and
swallowed so a corrupt run cannot break indexing for healthy ones. Hard
failures during ``open_db`` / ``init_schema`` still raise.

Public API:
    open_db(path=None) -> sqlite3.Connection
    init_schema(conn) -> None
    index_run(conn, run_dir) -> None
    rebuild_index(home) -> int
    init_db(home) -> sqlite3.Connection      # plan-aliased thin wrapper
"""
from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

from .paths import agentlens_home

logger = logging.getLogger(__name__)


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    parent_run_id TEXT,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    agent_name TEXT NOT NULL,
    agent_mode TEXT NOT NULL,
    recording_mode TEXT NOT NULL,
    agent_outcome TEXT,
    eval_status TEXT,
    sealed_phase TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_workspace ON runs(workspace_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_runs_eval_status ON runs(eval_status);

CREATE TABLE IF NOT EXISTS checks (
    run_id TEXT,
    name TEXT,
    status TEXT,
    message TEXT,
    PRIMARY KEY (run_id, name)
);

CREATE TABLE IF NOT EXISTS failures (
    run_id TEXT,
    category TEXT,
    severity TEXT,
    source TEXT,
    blame_scope TEXT,
    summary TEXT,
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

CREATE TABLE IF NOT EXISTS artifacts (
    run_id TEXT,
    path TEXT,
    sha256 TEXT,
    PRIMARY KEY (run_id, path)
);
"""

_INDEX_TABLES = ("runs", "checks", "failures", "artifacts")


def open_db(path: Path | None = None) -> sqlite3.Connection:
    """Open (or create) the SQLite index database.

    Args:
        path: explicit DB file path; when ``None``, defaults to
            ``<agentlens_home>/index.db``. The parent directory is created
            on demand.
    """
    if path is None:
        path = agentlens_home() / "index.db"
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """Create all index tables and indexes. Idempotent."""
    conn.executescript(_SCHEMA_SQL)
    conn.commit()


def init_db(home: Path) -> sqlite3.Connection:
    """Plan-aliased convenience: ``open_db(home/index.db)`` + ``init_schema``."""
    conn = open_db(Path(home) / "index.db")
    init_schema(conn)
    return conn


def _read_json(path: Path) -> dict[str, Any] | None:
    """Read+parse a JSON file; return ``None`` on missing/parse error."""
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("sqlite_index: failed to read %s: %s", path, exc)
        return None


def index_run(conn: sqlite3.Connection, run_dir: Path) -> None:
    """Upsert a single run's row set from its canonical JSON artifacts.

    Reads ``run.json`` (required), ``final.json``, ``eval.json``,
    ``manifest.json`` (each optional after ``run.json``) and replaces all
    rows for that ``run_id`` in the four tables. Per §7.3 errors are
    swallowed: a malformed run.json simply leaves the index untouched.
    """
    run_dir = Path(run_dir)
    try:
        run_doc = _read_json(run_dir / "run.json")
        if not run_doc:
            return

        run_id = run_doc.get("run_id")
        workspace_id = run_doc.get("workspace_id")
        started_at = run_doc.get("started_at")
        agent = run_doc.get("agent") or {}
        recording = run_doc.get("recording") or {}
        agent_name = agent.get("name")
        agent_mode = agent.get("mode")
        recording_mode = recording.get("mode")
        parent_run_id = run_doc.get("parent_run_id")

        if not (run_id and workspace_id and started_at and agent_name and agent_mode and recording_mode):
            logger.warning("sqlite_index: %s missing required run.json fields", run_dir)
            return

        final_doc = _read_json(run_dir / "final.json") or {}
        eval_doc = _read_json(run_dir / "eval.json") or {}
        manifest_doc = _read_json(run_dir / "manifest.json") or {}

        ended_at = final_doc.get("ended_at")
        agent_outcome = final_doc.get("agent_outcome")
        eval_status = eval_doc.get("status")
        sealed_phase = manifest_doc.get("sealed_phase")

        conn.execute(
            """
            INSERT OR REPLACE INTO runs (
                run_id, workspace_id, parent_run_id, started_at, ended_at,
                agent_name, agent_mode, recording_mode,
                agent_outcome, eval_status, sealed_phase
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id, workspace_id, parent_run_id, started_at, ended_at,
                agent_name, agent_mode, recording_mode,
                agent_outcome, eval_status, sealed_phase,
            ),
        )

        # Replace dependent rows for deterministic upsert.
        conn.execute("DELETE FROM checks WHERE run_id = ?", (run_id,))
        conn.execute("DELETE FROM failures WHERE run_id = ?", (run_id,))
        conn.execute("DELETE FROM artifacts WHERE run_id = ?", (run_id,))

        for check in eval_doc.get("checks") or []:
            name = check.get("name")
            status = check.get("status")
            if not name or not status:
                continue
            conn.execute(
                "INSERT OR REPLACE INTO checks (run_id, name, status, message) VALUES (?, ?, ?, ?)",
                (run_id, name, status, check.get("message")),
            )

        for failure in eval_doc.get("failures") or []:
            conn.execute(
                """
                INSERT INTO failures (run_id, category, severity, source, blame_scope, summary)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    failure.get("category"),
                    failure.get("severity"),
                    failure.get("source"),
                    failure.get("blame_scope"),
                    failure.get("summary"),
                ),
            )

        for entry in manifest_doc.get("files") or []:
            path = entry.get("path")
            sha = entry.get("sha256")
            if not path or not sha:
                continue
            conn.execute(
                "INSERT OR REPLACE INTO artifacts (run_id, path, sha256) VALUES (?, ?, ?)",
                (run_id, path, sha),
            )

        conn.commit()
    except sqlite3.Error as exc:  # pragma: no cover - defensive swallow per §7.3
        logger.warning("sqlite_index: sqlite error indexing %s: %s", run_dir, exc)
        try:
            conn.rollback()
        except sqlite3.Error:
            pass
    except (OSError, ValueError, KeyError, TypeError) as exc:  # pragma: no cover
        logger.warning("sqlite_index: failed to index %s: %s", run_dir, exc)


def rebuild_index(home: Path) -> int:
    """Drop+recreate the index DB and re-scan every run under ``home/runs``.

    Returns the count of runs successfully indexed (i.e. those whose
    ``run.json`` parsed and contained the required fields).
    """
    home = Path(home)
    conn = open_db(home / "index.db")
    try:
        # Disable FK enforcement during the drop sweep. `failures` has a FK
        # to `runs(run_id)`; dropping `runs` first while `failures` still
        # contains rows fails with `FOREIGN KEY constraint failed` even
        # though both tables are about to disappear. The pragma is per-
        # connection so re-enabling on the same conn after init_schema
        # restores the production invariant for the subsequent index_run
        # inserts.
        conn.execute("PRAGMA foreign_keys = OFF")
        for tbl in _INDEX_TABLES:
            conn.execute(f"DROP TABLE IF EXISTS {tbl}")
        conn.commit()
        init_schema(conn)
        conn.execute("PRAGMA foreign_keys = ON")

        runs_root = home / "runs"
        if not runs_root.is_dir():
            return 0

        before_count = 0
        indexed = 0
        for workspace_dir in sorted(p for p in runs_root.iterdir() if p.is_dir()):
            for run_dir in sorted(p for p in workspace_dir.iterdir() if p.is_dir()):
                before_count = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
                index_run(conn, run_dir)
                after_count = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
                if after_count > before_count:
                    indexed += 1
        return indexed
    finally:
        conn.close()


__all__ = [
    "index_run",
    "init_db",
    "init_schema",
    "open_db",
    "rebuild_index",
]
