"""Retention policy and garbage collection (spec §5.9, §8.4).

The garbage collector walks the run tree under ``$AGENTLENS_HOME/runs`` and
decides which files are eligible for deletion based on a small set of
conservative defaults:

* **sealed_runs_days** — non-final runs older than this are wholly eligible
  (entire run dir flagged).
* **large_artifacts_days** — any file under ``artifacts/`` older than this is
  flagged regardless of run age.
* **max_artifact_mb_per_run** — any single artifact larger than this is
  flagged regardless of age.
* **max_total_store_gb** — when the cumulative store size exceeds this quota,
  oldest sealed-final runs are walked oldest-first and their bulk artifacts
  (``events.jsonl`` and everything under ``artifacts/``) are flagged. Summary
  files (``eval.json`` / ``final.json`` / ``manifest.json`` / ``run.json``)
  are preserved whenever ``keep_eval_summaries=True`` (default).

The implementation is intentionally SQLite-independent: it scans the
filesystem only. This is the safety-net path for stores where the index is
missing or stale.

Public API:
    class RetentionPolicy
    class GcReport
    def gc(home, policy, *, dry_run) -> GcReport
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

# Files that must NEVER be deleted when keep_eval_summaries=True.
_SUMMARY_NAMES: frozenset[str] = frozenset(
    {"eval.json", "final.json", "manifest.json", "run.json"}
)


@dataclass(frozen=True)
class RetentionPolicy:
    """Retention thresholds (spec §5.9)."""

    sealed_runs_days: int = 30
    large_artifacts_days: int = 7
    max_artifact_mb_per_run: int = 50
    max_total_store_gb: int = 5
    keep_eval_summaries: bool = True


@dataclass(frozen=True)
class GcReport:
    """Result of a single :func:`gc` invocation."""

    deleted_paths: tuple[Path, ...]
    freed_bytes: int
    kept_summaries: tuple[Path, ...]
    dry_run: bool


@dataclass
class _RunInfo:
    """Lightweight per-run record used during scanning."""

    run_dir: Path
    started_at: datetime
    sealed_phase: str | None
    # Lazily computed total run size (sum of all regular files).
    total_size: int = 0
    # All regular files under run_dir.
    files: tuple[Path, ...] = field(default_factory=tuple)


def _parse_iso(ts: str | None) -> datetime | None:
    if not isinstance(ts, str):
        return None
    s = ts.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _safe_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _safe_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _list_run_dirs(home: Path) -> list[Path]:
    """Return every ``<home>/runs/<workspace>/<run>`` directory found."""
    root = home / "runs"
    if not root.is_dir():
        return []
    runs: list[Path] = []
    for ws in sorted(p for p in root.iterdir() if p.is_dir()):
        for rd in sorted(p for p in ws.iterdir() if p.is_dir()):
            runs.append(rd)
    return runs


def _collect_run(run_dir: Path) -> _RunInfo:
    """Read manifest + run.json (best-effort) and gather file list/sizes."""
    manifest = _read_json(run_dir / "manifest.json") or {}
    run_doc = _read_json(run_dir / "run.json") or {}

    sealed_phase: str | None = manifest.get("sealed_phase") if manifest else None
    started = _parse_iso(run_doc.get("started_at")) if run_doc else None
    if started is None:
        # Fall back to directory mtime so a manifest-less run still sorts.
        started = datetime.fromtimestamp(_safe_mtime(run_dir), tz=timezone.utc)

    files: list[Path] = []
    total = 0
    for p in run_dir.rglob("*"):
        if not p.is_file():
            continue
        files.append(p)
        total += _safe_size(p)

    return _RunInfo(
        run_dir=run_dir,
        started_at=started,
        sealed_phase=sealed_phase,
        total_size=total,
        files=tuple(files),
    )


def _is_summary(path: Path, run_dir: Path) -> bool:
    """Return True if *path* is a top-level summary file in *run_dir*."""
    if path.parent != run_dir:
        return False
    return path.name in _SUMMARY_NAMES


def _under_artifacts(path: Path, run_dir: Path) -> bool:
    try:
        rel = path.relative_to(run_dir)
    except ValueError:
        return False
    return len(rel.parts) >= 1 and rel.parts[0] == "artifacts"


def _is_events_jsonl(path: Path, run_dir: Path) -> bool:
    return path.parent == run_dir and path.name == "events.jsonl"


def _age_days(now: float, mtime: float) -> float:
    return max(0.0, (now - mtime) / 86400.0)


def gc(home: Path, policy: RetentionPolicy, *, dry_run: bool) -> GcReport:
    """Run garbage collection against *home* per *policy*.

    Steps (spec §5.9):
      1. Enumerate all run directories under ``<home>/runs``.
      2. Read each run's manifest + run.json to derive ``started_at`` and
         ``sealed_phase`` (with mtime fallback).
      3. Sort runs by ``started_at`` ascending.
      4. For each run, flag:
         - the whole run if ``sealed_phase != "final"`` and age >
           ``sealed_runs_days``;
         - any file under ``artifacts/`` older than
           ``large_artifacts_days``;
         - any artifact larger than ``max_artifact_mb_per_run``.
      5. If cumulative store size exceeds ``max_total_store_gb``, walk oldest
         sealed-final runs first and flag their ``events.jsonl`` and
         ``artifacts/`` files until the quota is met. Summary files
         (eval/final/manifest/run.json) are preserved when
         ``keep_eval_summaries=True``.
      6. If ``dry_run`` is False, actually unlink each flagged path and sum
         the freed bytes.

    Returns a :class:`GcReport`.
    """
    home = Path(home)
    runs = [_collect_run(rd) for rd in _list_run_dirs(home)]
    runs.sort(key=lambda r: r.started_at)

    now = time.time()
    flagged: dict[Path, int] = {}  # path → size at scan time
    kept_summaries: set[Path] = set()

    max_artifact_bytes = int(policy.max_artifact_mb_per_run) * 1024 * 1024
    max_total_bytes = int(policy.max_total_store_gb) * 1024 * 1024 * 1024

    def _flag(p: Path) -> None:
        if policy.keep_eval_summaries and _is_summary(p, _find_run_dir(p, runs)):
            kept_summaries.add(p)
            return
        # Idempotent
        if p not in flagged:
            flagged[p] = _safe_size(p)

    def _find_run_dir(path: Path, all_runs: list[_RunInfo]) -> Path:
        """Locate the run_dir an absolute path belongs to (heuristic)."""
        for r in all_runs:
            try:
                path.relative_to(r.run_dir)
                return r.run_dir
            except ValueError:
                continue
        return path.parent

    # --- Pass 1: per-run age/size rules -----------------------------------
    for run in runs:
        run_age_days = _age_days(now, run.started_at.timestamp())
        whole_run_flagged = (
            run.sealed_phase != "final"
            and run_age_days > policy.sealed_runs_days
        )

        for file_path in run.files:
            name = file_path.name
            # Preserve summary files when policy says so.
            if policy.keep_eval_summaries and _is_summary(file_path, run.run_dir):
                kept_summaries.add(file_path)
                continue

            if whole_run_flagged:
                flagged.setdefault(file_path, _safe_size(file_path))
                continue

            if _under_artifacts(file_path, run.run_dir):
                age = _age_days(now, _safe_mtime(file_path))
                size = _safe_size(file_path)
                if age > policy.large_artifacts_days:
                    flagged.setdefault(file_path, size)
                    continue
                if size > max_artifact_bytes:
                    flagged.setdefault(file_path, size)
                    continue

    # --- Pass 2: quota-driven oldest-sealed sweep -------------------------
    # Recompute cumulative size after Pass 1 flags (note: in dry_run we still
    # treat flagged bytes as "would-be-freed" for quota math).
    total_after_pass1 = 0
    for run in runs:
        for file_path in run.files:
            if file_path in flagged:
                continue
            total_after_pass1 += _safe_size(file_path)

    if total_after_pass1 > max_total_bytes:
        # Walk OLDEST sealed-final runs first. (Non-final runs were already
        # captured by Pass 1 when applicable.)
        sealed_final_runs = [r for r in runs if r.sealed_phase == "final"]
        for run in sealed_final_runs:
            if total_after_pass1 <= max_total_bytes:
                break
            for file_path in run.files:
                if file_path in flagged:
                    continue
                # Preserve summary files.
                if policy.keep_eval_summaries and _is_summary(
                    file_path, run.run_dir
                ):
                    kept_summaries.add(file_path)
                    continue
                # Only events.jsonl + artifacts/* are eligible.
                if not (
                    _is_events_jsonl(file_path, run.run_dir)
                    or _under_artifacts(file_path, run.run_dir)
                ):
                    continue
                size = _safe_size(file_path)
                flagged[file_path] = size
                total_after_pass1 -= size
                if total_after_pass1 <= max_total_bytes:
                    break

    # --- Deletion (optional) ---------------------------------------------
    freed_bytes = 0
    deleted_paths: list[Path] = []
    # Deterministic order for caller-visible report.
    for path in sorted(flagged):
        size = flagged[path]
        if not dry_run:
            try:
                path.unlink()
            except FileNotFoundError:
                continue
            except OSError:
                # Best-effort: skip files we can't remove and keep going.
                continue
        freed_bytes += size
        deleted_paths.append(path)

    return GcReport(
        deleted_paths=tuple(deleted_paths),
        freed_bytes=freed_bytes,
        kept_summaries=tuple(sorted(kept_summaries)),
        dry_run=dry_run,
    )


__all__ = ["GcReport", "RetentionPolicy", "gc"]
