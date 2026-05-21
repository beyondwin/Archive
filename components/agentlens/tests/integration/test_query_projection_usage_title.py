"""Query projection of import_report + usage artifacts (task_18).

Exercises the contract that ``store.query.latest()``, ``list_runs()`` and
``get_run()`` surface three additive keys derived from importer artifacts:

* ``display_title``  — from ``artifacts/import_report.json::derived.display_title``
* ``usage``          — public subset of ``artifacts/usage.json``
* ``import_state``   — from ``artifacts/import_report.json::analysis_state``

The test seeds three minimal-but-realistic run trees on disk:

1. **Claude imported run** — has both artifacts; usage confidence is
   ``"exact"`` and a display_title is set. All three projected keys are
   populated.

2. **Codex Desktop imported run** — has both artifacts; usage records were
   sparse so confidence is ``"unknown"``; display_title is still set. The
   ``usage`` projection is present (not None) but carries
   ``confidence == "unknown"``.

3. **Container run** (e.g., the waygent lifecycle) — has NO
   ``artifacts/`` directory at all. All three projected keys are ``None``.

Both the SQLite-backed fast path and the full-scan fallback must produce
the same projected values; the test runs both paths.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentlens.store import query as store_query
from agentlens.store import sqlite_index


WS = "ws_taskeighteenproject"
RUN_CLAUDE = "run_20260301_000000_claude"
RUN_CODEX = "run_20260302_000000_codexx"
RUN_CONTAINER = "run_20260303_000000_native"


def _write_run_tree(home: Path, run_id: str, *, started_at: str) -> Path:
    """Write a minimal-but-valid run tree (run/final/eval/manifest)."""
    run_dir = home / "runs" / WS / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "schema": "agentlens.run.v1",
                "run_id": run_id,
                "workspace_id": WS,
                "started_at": started_at,
                "agent": {"name": "generic", "mode": "cli"},
                "recording": {"mode": "minimal"},
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "final.json").write_text(
        json.dumps(
            {
                "ended_at": started_at,
                "agent_outcome": "success",
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "eval.json").write_text(
        json.dumps({"status": "passed", "checks": [], "failures": []}),
        encoding="utf-8",
    )
    (run_dir / "manifest.json").write_text(
        json.dumps({"sealed_phase": "final", "files": []}), encoding="utf-8"
    )
    return run_dir


def _write_artifacts(
    run_dir: Path,
    *,
    import_report: dict,
    usage: dict,
) -> None:
    artifacts = run_dir / "artifacts"
    artifacts.mkdir()
    (artifacts / "import_report.json").write_text(
        json.dumps(import_report), encoding="utf-8"
    )
    (artifacts / "usage.json").write_text(json.dumps(usage), encoding="utf-8")


@pytest.fixture()
def seeded_home(tmp_path: Path) -> Path:
    """Seed three runs: Claude-imported, Codex-imported, container."""
    home = tmp_path / "agentlens_home"

    # Claude imported — analysis full, display_title set, confidence exact.
    claude_dir = _write_run_tree(
        home, RUN_CLAUDE, started_at="2026-03-01T00:00:00Z"
    )
    _write_artifacts(
        claude_dir,
        import_report={
            "schema_version": "1",
            "source": "claude-session",
            "source_path": "claude-session:abc",
            "source_path_hash": "sha256:" + "0" * 64,
            "source_session_id": "abc",
            "analysis_state": "full",
            "source_bytes": 100,
            "byte_cap_bytes": 64 * 1024 * 1024,
            "byte_cap_hit": False,
            "byte_cap_source": "default",
            "lines": {
                "total_scanned": 1,
                "parsed": 1,
                "skipped_malformed": 0,
                "skipped_unsupported_type": 0,
                "skipped_oversized": 0,
            },
            "first_error": None,
            "transcript_artifact": None,
            "derived": {
                "display_title": "Refactor token streaming pipeline",
                "title_source": "first_user_message",
                "title_algorithm": "agentlens.title.v1",
            },
            "duration_ms": 5,
        },
        usage={
            "schema_version": "1",
            "source": "claude-session",
            "input_tokens": 1000,
            "output_tokens": 500,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 0,
            "reasoning_tokens": 0,
            "model_breakdown": [
                {
                    "model": "claude-opus-4-7",
                    "input_tokens": 1000,
                    "output_tokens": 500,
                    "cache_creation_tokens": 0,
                    "cache_read_tokens": 0,
                    "reasoning_tokens": 0,
                }
            ],
            "cost_usd": None,
            "pricing_source": "unknown",
            "confidence": "exact",
            "diagnostics": {
                "events_with_usage": 1,
                "events_missing_usage": 0,
                "model_field_missing_events": 0,
            },
        },
    )

    # Codex Desktop imported — usage extracted but confidence unknown.
    codex_dir = _write_run_tree(
        home, RUN_CODEX, started_at="2026-03-02T00:00:00Z"
    )
    _write_artifacts(
        codex_dir,
        import_report={
            "schema_version": "1",
            "source": "codex-rollout",
            "source_path": "codex-rollout:def",
            "source_path_hash": "sha256:" + "1" * 64,
            "source_session_id": "def",
            "analysis_state": "partial",
            "source_bytes": 100,
            "byte_cap_bytes": 64 * 1024 * 1024,
            "byte_cap_hit": False,
            "byte_cap_source": "default",
            "lines": {
                "total_scanned": 2,
                "parsed": 1,
                "skipped_malformed": 1,
                "skipped_unsupported_type": 0,
                "skipped_oversized": 0,
            },
            "first_error": {
                "line_number": 1,
                "byte_offset": 0,
                "reason": "json_decode",
            },
            "transcript_artifact": None,
            "derived": {
                "display_title": "Investigate sandbox escape path",
                "title_source": "first_user_message",
                "title_algorithm": "agentlens.title.v1",
            },
            "duration_ms": 3,
        },
        usage={
            "schema_version": "1",
            "source": "codex-rollout",
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 0,
            "reasoning_tokens": 0,
            "model_breakdown": [],
            "cost_usd": None,
            "pricing_source": "unknown",
            "confidence": "unknown",
            "diagnostics": {
                "events_with_usage": 0,
                "events_missing_usage": 1,
                "model_field_missing_events": 1,
            },
        },
    )

    # Container run — no artifacts/ at all (waygent lifecycle).
    _write_run_tree(home, RUN_CONTAINER, started_at="2026-03-03T00:00:00Z")

    return home


# ---------------------------------------------------------------------------
# Full-scan path
# ---------------------------------------------------------------------------


def test_list_runs_projects_all_three_keys(seeded_home: Path) -> None:
    rows = {r["run_id"]: r for r in store_query.list_runs(seeded_home)}
    assert set(rows) == {RUN_CLAUDE, RUN_CODEX, RUN_CONTAINER}
    for row in rows.values():
        for key in ("display_title", "usage", "import_state"):
            assert key in row, f"missing {key!r} in {row['run_id']}"


def test_claude_imported_run_full_projection(seeded_home: Path) -> None:
    row = store_query.get_run(seeded_home, RUN_CLAUDE)
    assert row is not None
    assert row["display_title"] == "Refactor token streaming pipeline"
    assert row["import_state"] == "full"
    usage = row["usage"]
    assert usage is not None
    assert usage["input_tokens"] == 1000
    assert usage["output_tokens"] == 500
    assert usage["confidence"] == "exact"
    assert usage["cost_usd"] is None
    assert usage["pricing_source"] == "unknown"
    assert isinstance(usage["model_breakdown"], list)
    assert usage["model_breakdown"][0]["model"] == "claude-opus-4-7"


def test_codex_imported_run_usage_unknown_confidence(seeded_home: Path) -> None:
    row = store_query.get_run(seeded_home, RUN_CODEX)
    assert row is not None
    assert row["display_title"] == "Investigate sandbox escape path"
    assert row["import_state"] == "partial"
    usage = row["usage"]
    assert usage is not None
    assert usage["confidence"] == "unknown"


def test_container_run_all_three_keys_null(seeded_home: Path) -> None:
    row = store_query.get_run(seeded_home, RUN_CONTAINER)
    assert row is not None
    assert row["display_title"] is None
    assert row["usage"] is None
    assert row["import_state"] is None


def test_latest_full_scan_enriches_artifacts(seeded_home: Path) -> None:
    # Newest run is the container one (2026-03-03). Even though it has no
    # artifacts, the three keys must still be present as None.
    row = store_query.latest(seeded_home)
    assert row is not None
    assert row["run_id"] == RUN_CONTAINER
    assert row["display_title"] is None
    assert row["usage"] is None
    assert row["import_state"] is None


# ---------------------------------------------------------------------------
# SQLite-backed path — must produce IDENTICAL projected values
# ---------------------------------------------------------------------------


def _build_index(home: Path) -> None:
    """Build a fresh index.db for *home* by invoking the writer module."""
    sqlite_index.rebuild_index(home)


def test_latest_sqlite_path_rehydrates_artifacts(seeded_home: Path) -> None:
    _build_index(seeded_home)
    row_claude = store_query.latest(seeded_home)
    assert row_claude is not None
    # Index ordering uses started_at DESC; container run wins. Re-check by
    # asking for the Claude workspace's newest (all three runs share WS).
    # All three runs live in the same workspace so latest(workspace_id=WS)
    # returns the newest: RUN_CONTAINER.
    assert row_claude["run_id"] == RUN_CONTAINER
    # Container has no artifacts → all three None.
    assert row_claude["display_title"] is None
    assert row_claude["usage"] is None
    assert row_claude["import_state"] is None


def test_sqlite_rehydrated_claude_matches_full_scan(seeded_home: Path) -> None:
    # First capture full-scan projection.
    fs_row = store_query.get_run(seeded_home, RUN_CLAUDE)
    assert fs_row is not None
    # Build index, then ask for latest(workspace_id=WS) restricting via
    # started_at by purging the newer runs from disk-and-index OR querying
    # the index directly. Cleanest approach: query the SQLite path via a
    # pruned workspace where only the Claude run lives.
    _build_index(seeded_home)
    # Round-trip: call latest() on a workspace that does not exist for the
    # purpose of testing rehydration via the indexed path. Easier: assert
    # parity by issuing the indexed query directly using the public facade.
    # We re-seed a side-workspace with just the Claude run so it is the
    # newest in that workspace and SQLite picks it.
    side_ws = "ws_sideworkspaceforx"
    side_run = "run_20260401_000000_sidexx"
    src = seeded_home / "runs" / WS / RUN_CLAUDE
    dst = seeded_home / "runs" / side_ws / side_run
    dst.parent.mkdir(parents=True)
    import shutil
    shutil.copytree(src, dst)
    # Patch run.json so the run_id and workspace_id match the new layout.
    run_doc = json.loads((dst / "run.json").read_text(encoding="utf-8"))
    run_doc["run_id"] = side_run
    run_doc["workspace_id"] = side_ws
    (dst / "run.json").write_text(json.dumps(run_doc), encoding="utf-8")
    _build_index(seeded_home)
    sqlite_row = store_query.latest(seeded_home, workspace_id=side_ws)
    assert sqlite_row is not None
    assert sqlite_row["run_id"] == side_run
    # Three projected keys must match the original Claude run because the
    # artifacts/ directory was copied alongside.
    assert sqlite_row["display_title"] == fs_row["display_title"]
    assert sqlite_row["import_state"] == fs_row["import_state"]
    assert sqlite_row["usage"] == fs_row["usage"]
