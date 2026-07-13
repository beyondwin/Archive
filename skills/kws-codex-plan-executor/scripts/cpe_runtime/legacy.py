"""Bounded read-only inspection for historical schema-3 CPE runs."""

from __future__ import annotations

import json
from pathlib import Path


_MAX_JSON_BYTES = 1024 * 1024
_MAX_TEXT = 2000
_MAX_LIST = 100


def _read_object(path: Path, name: str) -> dict[str, object]:
    try:
        size = path.stat().st_size
        if size < 1 or size > _MAX_JSON_BYTES:
            raise ValueError(f"legacy {name} is outside the bounded size")
        value = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"legacy {name} is unreadable") from exc
    if not isinstance(value, dict):
        raise ValueError(f"legacy {name} must be an object")
    return value


def _text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > _MAX_TEXT:
        raise ValueError("legacy summary contains an invalid bounded string")
    return value


def inspect_legacy_run(*, codex_home: Path, run_id: str) -> dict[str, object]:
    """Return a small schema-3 summary without opening any mutation surface."""

    if not isinstance(run_id, str) or not run_id or "/" in run_id or "\\" in run_id:
        raise ValueError("run_id must be one bounded path component")
    root = codex_home.expanduser() / "orchestrator" / run_id
    manifest = _read_object(root / "run_manifest.json", "manifest")
    if manifest.get("schema_version") not in {3, "3"}:
        raise ValueError("run is not schema 3")
    state = _read_object(root / "state.json", "state")
    tasks = state.get("tasks", [])
    if not isinstance(tasks, (list, dict)) or len(tasks) > _MAX_LIST:
        raise ValueError("legacy task summary exceeds the bounded limit")
    status = _text(state.get("status") or state.get("lifecycle") or "interrupted")
    current_task = _text(state.get("current_task"))
    worktree = _text(
        manifest.get("execution_worktree")
        or manifest.get("execution_worktree_ref")
        or manifest.get("worktree")
    )
    return {
        "schema_version": 3,
        "run_id": run_id,
        "status": status,
        "current_task": current_task,
        "worktree": worktree,
        "resume_supported": False,
        "failure_code": "legacy_run_requires_historical_cpe",
    }
