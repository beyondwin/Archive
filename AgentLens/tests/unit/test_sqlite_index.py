"""Tests for agentlens.store.sqlite_index (spec §5.8, §7.3)."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from agentlens.store.sqlite_index import (
    index_run,
    init_db,
    init_schema,
    open_db,
    rebuild_index,
)


RUN_ID_A = "run_20260101_000000_aaaaaa"
RUN_ID_B = "run_20260102_000000_bbbbbb"
WS_ID = "ws_0000000000000001"


def _write_run_dir(
    home: Path,
    run_id: str,
    *,
    with_final: bool = True,
    with_eval: bool = True,
    with_manifest: bool = True,
    workspace_id: str = WS_ID,
    parent_run_id: str | None = None,
) -> Path:
    run_dir = home / "runs" / workspace_id / run_id
    run_dir.mkdir(parents=True)
    run_doc = {
        "schema": "agentlens.run.v1",
        "run_id": run_id,
        "workspace_id": workspace_id,
        "started_at": "2026-01-01T00:00:00Z",
        "agent": {"name": "generic", "mode": "cli"},
        "workspace": {
            "root_label": "./workspace",
            "root_hash": "sha256:" + "0" * 64,
            "id_basis": "path",
        },
        "recording": {"mode": "minimal", "adapter": "generic"},
    }
    if parent_run_id is not None:
        run_doc["parent_run_id"] = parent_run_id
    (run_dir / "run.json").write_text(json.dumps(run_doc), encoding="utf-8")

    if with_final:
        (run_dir / "final.json").write_text(
            json.dumps(
                {
                    "schema": "agentlens.final.v1",
                    "run_id": run_id,
                    "ended_at": "2026-01-01T00:00:05Z",
                    "agent_outcome": "success",
                }
            ),
            encoding="utf-8",
        )
    if with_eval:
        (run_dir / "eval.json").write_text(
            json.dumps(
                {
                    "schema": "agentlens.eval.v1",
                    "run_id": run_id,
                    "evaluated_at": "1970-01-01T00:00:00Z",
                    "status": "passed",
                    "agent_outcome": "success",
                    "checks": [
                        {"name": "schema_valid", "status": "passed"},
                        {"name": "final_present", "status": "passed", "message": "ok"},
                    ],
                    "failures": [],
                }
            ),
            encoding="utf-8",
        )
    if with_manifest:
        (run_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "schema": "agentlens.manifest.v1",
                    "run_id": run_id,
                    "sealed_at": "2026-01-01T00:00:10Z",
                    "sealed": True,
                    "sealed_phase": "final",
                    "files": [
                        {"path": "run.json", "sha256": "sha256:" + "a" * 64},
                        {"path": "final.json", "sha256": "sha256:" + "b" * 64},
                    ],
                    "redaction": {},
                }
            ),
            encoding="utf-8",
        )
    return run_dir


# ---------------------------------------------------------------------------
# init / schema
# ---------------------------------------------------------------------------


def test_init_schema_creates_all_tables(tmp_path: Path) -> None:
    conn = open_db(tmp_path / "index.db")
    init_schema(conn)
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    names = {r[0] for r in rows}
    assert {"runs", "checks", "failures", "artifacts"} <= names
    conn.close()


def test_init_schema_is_idempotent(tmp_path: Path) -> None:
    conn = open_db(tmp_path / "index.db")
    init_schema(conn)
    init_schema(conn)  # must not raise
    # ensure tables still empty
    for tbl in ("runs", "checks", "failures", "artifacts"):
        count = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        assert count == 0
    conn.close()


def test_init_db_alias(tmp_path: Path) -> None:
    """init_db(home) is a thin wrapper for open_db + init_schema."""
    home = tmp_path
    conn = init_db(home)
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    assert {r[0] for r in rows} >= {"runs", "checks", "failures", "artifacts"}
    conn.close()
    assert (home / "index.db").is_file()


# ---------------------------------------------------------------------------
# index_run
# ---------------------------------------------------------------------------


def test_index_run_inserts_all_rows(tmp_path: Path) -> None:
    run_dir = _write_run_dir(tmp_path, RUN_ID_A)
    conn = open_db(tmp_path / "index.db")
    init_schema(conn)
    index_run(conn, run_dir)

    runs = conn.execute("SELECT run_id, workspace_id, agent_name, agent_mode, recording_mode, started_at, ended_at, agent_outcome, eval_status, sealed_phase FROM runs").fetchall()
    assert runs == [(
        RUN_ID_A,
        WS_ID,
        "generic",
        "cli",
        "minimal",
        "2026-01-01T00:00:00Z",
        "2026-01-01T00:00:05Z",
        "success",
        "passed",
        "final",
    )]

    checks = sorted(conn.execute("SELECT run_id, name, status, message FROM checks").fetchall())
    assert checks == [
        (RUN_ID_A, "final_present", "passed", "ok"),
        (RUN_ID_A, "schema_valid", "passed", None),
    ]

    failures = conn.execute("SELECT * FROM failures").fetchall()
    assert failures == []

    artifacts = sorted(conn.execute("SELECT run_id, path, sha256 FROM artifacts").fetchall())
    assert artifacts == [
        (RUN_ID_A, "final.json", "sha256:" + "b" * 64),
        (RUN_ID_A, "run.json", "sha256:" + "a" * 64),
    ]
    conn.close()


def test_index_run_missing_optional_files_nulls(tmp_path: Path) -> None:
    run_dir = _write_run_dir(
        tmp_path, RUN_ID_A, with_final=False, with_eval=False, with_manifest=False
    )
    conn = open_db(tmp_path / "index.db")
    init_schema(conn)
    index_run(conn, run_dir)

    row = conn.execute(
        "SELECT run_id, workspace_id, ended_at, agent_outcome, eval_status, sealed_phase FROM runs"
    ).fetchone()
    assert row == (RUN_ID_A, WS_ID, None, None, None, None)
    assert conn.execute("SELECT COUNT(*) FROM checks").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM failures").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0] == 0
    conn.close()


def test_index_run_upsert_replaces(tmp_path: Path) -> None:
    run_dir = _write_run_dir(tmp_path, RUN_ID_A)
    conn = open_db(tmp_path / "index.db")
    init_schema(conn)
    index_run(conn, run_dir)
    # Re-index after mutating eval — checks/failures/artifacts must not duplicate.
    index_run(conn, run_dir)

    assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM checks").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0] == 2
    conn.close()


def test_index_run_writes_failures(tmp_path: Path) -> None:
    run_dir = _write_run_dir(tmp_path, RUN_ID_A, with_eval=False)
    # Overwrite eval.json with failures
    (run_dir / "eval.json").write_text(
        json.dumps(
            {
                "schema": "agentlens.eval.v1",
                "run_id": RUN_ID_A,
                "evaluated_at": "1970-01-01T00:00:00Z",
                "status": "failed",
                "agent_outcome": "failed",
                "checks": [],
                "failures": [
                    {
                        "category": "MISSING_FINAL",
                        "severity": "blocker",
                        "source": "evaluator",
                        "blame_scope": "agent",
                        "summary": "no final.json",
                    },
                    {
                        "category": "UNKNOWN",
                        "severity": "minor",
                        "source": "evaluator",
                        "blame_scope": "unknown",
                        "summary": "x",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    conn = open_db(tmp_path / "index.db")
    init_schema(conn)
    index_run(conn, run_dir)
    rows = sorted(
        conn.execute(
            "SELECT run_id, category, severity, source, blame_scope, summary FROM failures"
        ).fetchall()
    )
    assert rows == [
        (RUN_ID_A, "MISSING_FINAL", "blocker", "evaluator", "agent", "no final.json"),
        (RUN_ID_A, "UNKNOWN", "minor", "evaluator", "unknown", "x"),
    ]
    eval_status = conn.execute("SELECT eval_status FROM runs").fetchone()[0]
    assert eval_status == "failed"
    conn.close()


def test_index_run_handles_corrupt_json(tmp_path: Path) -> None:
    """Best-effort: malformed run.json must not raise."""
    run_dir = tmp_path / "runs" / WS_ID / RUN_ID_A
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text("{not-json", encoding="utf-8")
    conn = open_db(tmp_path / "index.db")
    init_schema(conn)
    # Should not raise
    index_run(conn, run_dir)
    assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0
    conn.close()


# ---------------------------------------------------------------------------
# rebuild_index
# ---------------------------------------------------------------------------


def test_rebuild_index_returns_count_and_matches_index_run(tmp_path: Path) -> None:
    home = tmp_path
    _write_run_dir(home, RUN_ID_A)
    _write_run_dir(home, RUN_ID_B)
    count = rebuild_index(home)
    assert count == 2

    conn = open_db(home / "index.db")
    runs = sorted(conn.execute("SELECT run_id FROM runs").fetchall())
    assert runs == sorted([(RUN_ID_A,), (RUN_ID_B,)])
    conn.close()


def test_rebuild_index_byte_equal_after_manual_mutation(tmp_path: Path) -> None:
    home = tmp_path
    _write_run_dir(home, RUN_ID_A)
    _write_run_dir(home, RUN_ID_B)

    # Build baseline via per-run index_run
    baseline_conn = open_db(home / "baseline.db")
    init_schema(baseline_conn)
    for ws_dir in sorted((home / "runs").iterdir()):
        for rd in sorted(ws_dir.iterdir()):
            index_run(baseline_conn, rd)

    def snapshot(conn: sqlite3.Connection) -> dict[str, list[tuple]]:
        out: dict[str, list[tuple]] = {}
        for tbl, cols in (
            ("runs", "run_id, workspace_id, parent_run_id, started_at, ended_at, agent_name, agent_mode, recording_mode, agent_outcome, eval_status, sealed_phase"),
            ("checks", "run_id, name, status, message"),
            ("failures", "run_id, category, severity, source, blame_scope, summary"),
            ("artifacts", "run_id, path, sha256"),
        ):
            rows = conn.execute(f"SELECT {cols} FROM {tbl}").fetchall()
            out[tbl] = sorted(rows)
        return out

    expected = snapshot(baseline_conn)
    baseline_conn.close()

    # Mutate the live index.db with garbage, then rebuild_index should restore.
    conn = open_db(home / "index.db")
    init_schema(conn)
    conn.execute(
        "INSERT INTO runs (run_id, workspace_id, started_at, agent_name, agent_mode, recording_mode) VALUES (?, ?, ?, ?, ?, ?)",
        ("garbage", "ws", "x", "a", "b", "c"),
    )
    conn.execute("INSERT INTO checks (run_id, name, status) VALUES ('garbage','x','passed')")
    conn.commit()
    conn.close()

    count = rebuild_index(home)
    assert count == 2

    live_conn = open_db(home / "index.db")
    actual = snapshot(live_conn)
    live_conn.close()
    assert actual == expected


def test_rebuild_index_empty_home(tmp_path: Path) -> None:
    count = rebuild_index(tmp_path)
    assert count == 0
    # DB still initialized
    conn = open_db(tmp_path / "index.db")
    for tbl in ("runs", "checks", "failures", "artifacts"):
        assert conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0] == 0
    conn.close()


# ---------------------------------------------------------------------------
# open_db default path
# ---------------------------------------------------------------------------


def test_open_db_default_uses_agentlens_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTLENS_HOME", str(tmp_path))
    conn = open_db()
    init_schema(conn)
    conn.close()
    assert (tmp_path / "index.db").is_file()
