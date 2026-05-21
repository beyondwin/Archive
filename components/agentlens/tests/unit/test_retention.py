"""Tests for agentlens.store.retention (spec §5.9, §8.4)."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agentlens.store.retention import GcReport, RetentionPolicy, gc


def _iso(dt: datetime) -> str:
    s = dt.astimezone(timezone.utc).isoformat(timespec="microseconds")
    if s.endswith("+00:00"):
        s = s[: -len("+00:00")] + "Z"
    return s


def _make_run(
    home: Path,
    workspace_id: str,
    run_id: str,
    *,
    started_at: datetime,
    sealed_phase: str | None = "pre_eval",
    artifacts: dict[str, int] | None = None,
    events_size: int = 1024,
    with_eval: bool = False,
    with_final: bool = False,
) -> Path:
    """Create a synthetic run directory under home.

    artifacts maps relative names under artifacts/ to byte sizes.
    """
    run_dir = home / "runs" / workspace_id / run_id
    (run_dir / "artifacts").mkdir(parents=True, exist_ok=True)

    started_iso = _iso(started_at)
    run_doc = {
        "schema": "agentlens.run.v1",
        "run_id": run_id,
        "workspace_id": workspace_id,
        "started_at": started_iso,
        "agent": {"name": "claude", "mode": "observed"},
        "recording": {"mode": "process_wrapper"},
    }
    (run_dir / "run.json").write_text(json.dumps(run_doc), encoding="utf-8")

    if sealed_phase is not None:
        manifest_doc = {
            "schema": "agentlens.manifest.v1",
            "run_id": run_id,
            "sealed_at": started_iso,
            "sealed": True,
            "sealed_phase": sealed_phase,
            "files": [],
            "redaction": {},
        }
        (run_dir / "manifest.json").write_text(
            json.dumps(manifest_doc), encoding="utf-8"
        )

    if with_final:
        (run_dir / "final.json").write_text(
            json.dumps({"ended_at": started_iso, "agent_outcome": "ok"}),
            encoding="utf-8",
        )
    if with_eval:
        (run_dir / "eval.json").write_text(
            json.dumps({"status": "pass"}), encoding="utf-8"
        )

    events_path = run_dir / "events.jsonl"
    events_path.write_bytes(b"x" * events_size)

    for name, size in (artifacts or {}).items():
        p = run_dir / "artifacts" / name
        p.write_bytes(b"a" * size)

    # Set mtime on the run directory and all files to match started_at
    epoch = started_at.timestamp()
    for p in run_dir.rglob("*"):
        os.utime(p, (epoch, epoch))
    os.utime(run_dir, (epoch, epoch))
    return run_dir


def test_empty_home_returns_empty_report(tmp_path):
    policy = RetentionPolicy()
    report = gc(tmp_path, policy, dry_run=True)
    assert isinstance(report, GcReport)
    assert report.deleted_paths == ()
    assert report.freed_bytes == 0
    assert report.dry_run is True


def test_empty_runs_dir_returns_empty_report(tmp_path):
    (tmp_path / "runs").mkdir()
    policy = RetentionPolicy()
    report = gc(tmp_path, policy, dry_run=True)
    assert report.deleted_paths == ()
    assert report.freed_bytes == 0


def test_old_non_final_run_flagged(tmp_path):
    """A run sealed pre_eval whose age exceeds sealed_runs_days is flagged."""
    now = datetime.now(timezone.utc)
    _make_run(
        tmp_path,
        "ws_test",
        "run_old_pre_eval",
        started_at=now - timedelta(days=31),
        sealed_phase="pre_eval",
    )
    policy = RetentionPolicy()
    report = gc(tmp_path, policy, dry_run=True)
    paths_str = {str(p) for p in report.deleted_paths}
    # The whole run dir (or its files) should be flagged.
    assert any("run_old_pre_eval" in s for s in paths_str)


def test_recent_non_final_run_not_flagged(tmp_path):
    now = datetime.now(timezone.utc)
    _make_run(
        tmp_path,
        "ws_test",
        "run_recent_pre_eval",
        started_at=now - timedelta(days=5),
        sealed_phase="pre_eval",
    )
    policy = RetentionPolicy()
    report = gc(tmp_path, policy, dry_run=True)
    paths_str = {str(p) for p in report.deleted_paths}
    assert not any("run_recent_pre_eval" in s for s in paths_str)


def test_old_final_run_not_flagged_by_sealed_policy(tmp_path):
    """Sealed_phase=final runs are NOT flagged by sealed_runs_days."""
    now = datetime.now(timezone.utc)
    _make_run(
        tmp_path,
        "ws_test",
        "run_old_final",
        started_at=now - timedelta(days=31),
        sealed_phase="final",
        with_eval=True,
        with_final=True,
    )
    policy = RetentionPolicy()
    report = gc(tmp_path, policy, dry_run=True)
    # The run dir itself should not be flagged for deletion by sealed_runs_days.
    paths_str = {str(p) for p in report.deleted_paths}
    # Summary files preserved.
    summary_files = {"eval.json", "final.json", "manifest.json", "run.json"}
    for s in paths_str:
        # If anything for run_old_final shows up, it must not be summary files.
        if "run_old_final" in s:
            assert not any(s.endswith(name) for name in summary_files)


def test_oversize_artifact_flagged(tmp_path):
    """Artifact larger than max_artifact_mb_per_run is flagged."""
    now = datetime.now(timezone.utc)
    # 2 MB artifact, policy threshold 1 MB
    _make_run(
        tmp_path,
        "ws_test",
        "run_with_big_art",
        started_at=now - timedelta(hours=1),
        sealed_phase="pre_eval",
        artifacts={"big.bin": 2 * 1024 * 1024, "small.bin": 1024},
    )
    policy = RetentionPolicy(max_artifact_mb_per_run=1)
    report = gc(tmp_path, policy, dry_run=True)
    paths_str = {str(p) for p in report.deleted_paths}
    assert any("big.bin" in s for s in paths_str)
    assert not any("small.bin" in s for s in paths_str)


def test_old_artifact_flagged(tmp_path):
    """Artifact older than large_artifacts_days is flagged."""
    now = datetime.now(timezone.utc)
    _make_run(
        tmp_path,
        "ws_test",
        "run_old_art",
        started_at=now - timedelta(days=10),
        sealed_phase="final",
        with_eval=True,
        with_final=True,
        artifacts={"old.bin": 1024},
    )
    policy = RetentionPolicy(large_artifacts_days=7)
    report = gc(tmp_path, policy, dry_run=True)
    paths_str = {str(p) for p in report.deleted_paths}
    assert any("old.bin" in s for s in paths_str)


def test_dry_run_does_not_delete(tmp_path):
    now = datetime.now(timezone.utc)
    run = _make_run(
        tmp_path,
        "ws_test",
        "run_old_pre_eval",
        started_at=now - timedelta(days=60),
        sealed_phase="pre_eval",
        artifacts={"a.bin": 1024},
    )
    policy = RetentionPolicy()
    report = gc(tmp_path, policy, dry_run=True)
    assert report.dry_run is True
    # Files still present
    assert (run / "events.jsonl").exists()
    assert (run / "artifacts" / "a.bin").exists()


def test_real_run_deletes_files(tmp_path):
    now = datetime.now(timezone.utc)
    run = _make_run(
        tmp_path,
        "ws_test",
        "run_old_pre_eval",
        started_at=now - timedelta(days=60),
        sealed_phase="pre_eval",
        artifacts={"a.bin": 1024},
    )
    policy = RetentionPolicy()
    report = gc(tmp_path, policy, dry_run=False)
    assert report.dry_run is False
    assert report.freed_bytes > 0
    # events.jsonl + artifact deleted
    assert not (run / "events.jsonl").exists()
    assert not (run / "artifacts" / "a.bin").exists()


def test_quota_overflow_targets_oldest_sealed_runs(tmp_path):
    """When total store > max_total_store_gb, oldest sealed final runs lose
    events.jsonl + artifacts but keep summary files (eval/final/manifest/run)."""
    now = datetime.now(timezone.utc)
    # Two sealed-final runs, one older. We'll set a very small quota
    # (effectively 0 GB → any data overflows) so cumulative-size kicks in.
    older = _make_run(
        tmp_path,
        "ws_test",
        "run_old_final",
        started_at=now - timedelta(days=2),
        sealed_phase="final",
        with_eval=True,
        with_final=True,
        events_size=2048,
        artifacts={"a.bin": 4096},
    )
    newer = _make_run(
        tmp_path,
        "ws_test",
        "run_new_final",
        started_at=now - timedelta(hours=1),
        sealed_phase="final",
        with_eval=True,
        with_final=True,
        events_size=2048,
        artifacts={"b.bin": 4096},
    )
    # Effectively 0 GB quota → ALWAYS over. But to test only-oldest-trimmed,
    # set quota such that older alone overflows; trimming older should be
    # enough.
    policy = RetentionPolicy(
        sealed_runs_days=365,  # disable the age-based sweep
        large_artifacts_days=365,
        max_artifact_mb_per_run=999,
        max_total_store_gb=0,  # any byte > 0 GB triggers
    )
    report = gc(tmp_path, policy, dry_run=True)
    paths_str = {str(p) for p in report.deleted_paths}

    # Older run's events.jsonl and artifact ARE flagged.
    assert any(
        s.endswith("events.jsonl") and "run_old_final" in s for s in paths_str
    )
    assert any("a.bin" in s for s in paths_str)

    # Summary files are NEVER flagged.
    summary_names = ("eval.json", "final.json", "manifest.json", "run.json")
    for s in paths_str:
        for name in summary_names:
            assert not s.endswith(name), (
                f"Summary file flagged but keep_eval_summaries=True: {s}"
            )

    # Kept summaries reported.
    kept_str = {str(p) for p in report.kept_summaries}
    assert any("eval.json" in s for s in kept_str)


def test_works_without_sqlite_index(tmp_path):
    """gc operates via filesystem scan only, even with no SQLite index."""
    now = datetime.now(timezone.utc)
    _make_run(
        tmp_path,
        "ws_test",
        "run_x",
        started_at=now - timedelta(days=40),
        sealed_phase="pre_eval",
    )
    # No 'index.sqlite' file is created anywhere.
    assert not (tmp_path / "index.sqlite").exists()
    policy = RetentionPolicy()
    report = gc(tmp_path, policy, dry_run=True)
    # Sanity: something was flagged from the 40-day-old pre_eval run.
    assert len(report.deleted_paths) > 0


def test_run_without_manifest_falls_back_to_mtime(tmp_path):
    """Runs missing manifest.json use directory mtime + treat as non-final."""
    now = datetime.now(timezone.utc)
    run = _make_run(
        tmp_path,
        "ws_test",
        "run_no_manifest",
        started_at=now - timedelta(days=40),
        sealed_phase=None,  # no manifest
    )
    assert not (run / "manifest.json").exists()
    policy = RetentionPolicy()
    report = gc(tmp_path, policy, dry_run=True)
    paths_str = {str(p) for p in report.deleted_paths}
    assert any("run_no_manifest" in s for s in paths_str)
