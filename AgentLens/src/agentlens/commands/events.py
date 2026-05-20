"""``agentlens events`` — query/listing command (spec §4.2.4).

JSON-first: reads ``events.jsonl`` directly. SQLite is never queried for
the event body. ``--tree`` walks the parent_run_id graph by reading
``run.json`` files under ``$AGENTLENS_HOME/runs``.

Filters compose: ``--type`` is an fnmatch glob, ``--since`` is an inclusive
UTC ISO8601 lower bound. ``--follow`` is a thin tail loop and is opt-in;
the default does a one-shot scan suitable for scripted use.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Iterable, Optional

import typer

from agentlens.store.event_query import (
    filter_since,
    glob_type_match,
    merge_events_by_ts_run,
)
from agentlens.store.paths import runs_root


def _find_run_dir(run_id: str) -> Optional[Path]:
    """Filesystem-first lookup for a single run_id under ``runs_root()``."""
    root = runs_root()
    if not root.is_dir():
        return None
    for ws_dir in root.iterdir():
        if not ws_dir.is_dir():
            continue
        candidate = ws_dir / run_id
        if candidate.is_dir() and (candidate / "run.json").is_file():
            return candidate
    return None


def _all_run_dirs() -> list[Path]:
    """Return every run directory under ``runs_root()`` (best-effort)."""
    root = runs_root()
    if not root.is_dir():
        return []
    dirs: list[Path] = []
    for ws_dir in root.iterdir():
        if not ws_dir.is_dir():
            continue
        for run_dir in ws_dir.iterdir():
            if run_dir.is_dir() and (run_dir / "run.json").is_file():
                dirs.append(run_dir)
    return dirs


def _read_events(run_dir: Path) -> list[dict]:
    """Return parsed events from ``run_dir/events.jsonl`` (missing → [])."""
    p = run_dir / "events.jsonl"
    if not p.is_file():
        return []
    out: list[dict] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _descendants(root_run_id: str) -> list[Path]:
    """Return run_dirs for *root_run_id* and every transitive descendant.

    Builds the parent → children map once by reading ``run.json`` across
    all workspaces, then DFS-walks from *root_run_id*.
    """
    children: dict[str, list[Path]] = {}
    dir_by_id: dict[str, Path] = {}
    for run_dir in _all_run_dirs():
        try:
            doc = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        rid = doc.get("run_id")
        if not isinstance(rid, str):
            continue
        dir_by_id[rid] = run_dir
        parent = doc.get("parent_run_id")
        if isinstance(parent, str):
            children.setdefault(parent, []).append(run_dir)

    out: list[Path] = []
    seen: set[str] = set()
    stack: list[str] = [root_run_id]
    while stack:
        rid = stack.pop()
        if rid in seen:
            continue
        seen.add(rid)
        if rid in dir_by_id:
            out.append(dir_by_id[rid])
        for child_dir in children.get(rid, []):
            child_id = child_dir.name
            if child_id not in seen:
                stack.append(child_id)
    return out


def _emit(events: Iterable[dict]) -> None:
    for evt in events:
        typer.echo(json.dumps(evt, ensure_ascii=False, sort_keys=True))


def events(
    run: Optional[str] = typer.Option(
        None, "--run", help="run_id to query (omit to query all runs)"
    ),
    type_: Optional[str] = typer.Option(
        None, "--type", help="fnmatch glob over event types (e.g. agentrunway.*)"
    ),
    since: Optional[str] = typer.Option(
        None, "--since", help="inclusive UTC ISO8601 lower bound on ts"
    ),
    tree: bool = typer.Option(
        False, "--tree", help="include descendants by parent_run_id"
    ),
    follow: bool = typer.Option(
        False, "--follow", help="tail events.jsonl indefinitely",
    ),
) -> None:
    """Stream matching events as JSONL on stdout."""
    if run is None and tree:
        raise typer.BadParameter("--tree requires --run")

    # Resolve the set of run_dirs in scope.
    if run is None:
        run_dirs = _all_run_dirs()
    elif tree:
        run_dirs = _descendants(run)
        if not run_dirs:
            # Unknown run id with --tree: emit nothing, exit 0.
            return
    else:
        rd = _find_run_dir(run)
        run_dirs = [rd] if rd is not None else []

    streams = [_read_events(rd) for rd in run_dirs]
    merged = merge_events_by_ts_run(streams)
    merged = filter_since(merged, since)
    merged = [e for e in merged if glob_type_match(type_, e.get("type", ""))]
    _emit(merged)

    if not follow:
        return

    # Basic tail: remember byte offsets per file, poll for new lines.
    offsets: dict[Path, int] = {}
    for rd in run_dirs:
        p = rd / "events.jsonl"
        offsets[p] = p.stat().st_size if p.is_file() else 0
    try:
        while True:
            time.sleep(0.5)
            for p, off in list(offsets.items()):
                if not p.is_file():
                    continue
                size = p.stat().st_size
                if size <= off:
                    continue
                with open(p, "rb") as f:
                    f.seek(off)
                    chunk = f.read().decode("utf-8", errors="replace")
                offsets[p] = size
                new_events: list[dict] = []
                for line in chunk.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        evt = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if since is not None:
                        if not filter_since([evt], since):
                            continue
                    if not glob_type_match(type_, evt.get("type", "")):
                        continue
                    new_events.append(evt)
                _emit(new_events)
    except KeyboardInterrupt:  # pragma: no cover
        return


__all__ = ["events"]
