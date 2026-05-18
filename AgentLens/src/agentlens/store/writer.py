"""Atomic, schema-validated writers for the run tree (spec §5.6, §S1.6.6).

All structured writes go through ``atomic_write_json``: validate → tempfile
+ ``fsync`` → ``os.rename`` → cleanup-on-error. The events log uses
``append_event`` with a sibling lock (see :mod:`agentlens.store.lock`).

Schema validation runs **after** any redaction pass to ensure the on-disk
payload matches the v1 contract. Redaction is wired in via task_22
(``agentlens.redaction.redact.apply_to_doc``); until that module exists,
``_maybe_redact`` is an identity function — the lazy import returns input
unchanged on ``ImportError``.

Public API:
    atomic_write_json(path, data, *, redact=True)
    append_event(run_dir, event)
    write_run_meta(run_dir, run)
    write_final(run_dir, final)
    write_workspace_pointer(workspace_root, run_id, run_dir)
    class WriteError(Exception)
"""
from __future__ import annotations

import contextlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from agentlens.constants import MAX_EXCERPT_CHARS
from agentlens.schema.validate import SchemaError, validate_doc

from .lock import file_lock
from .paths import current_run_marker


class WriteError(Exception):
    """Raised for non-schema write failures (oversize excerpt, IO, etc.)."""


def _maybe_redact(data: dict[str, Any]) -> dict[str, Any]:
    """Apply redaction if the module is available, else return unchanged.

    The redaction module (task_22) is not yet present. When it lands it must
    expose ``agentlens.redaction.redact.apply_to_doc(data) -> dict``.
    """
    try:
        from agentlens.redaction.redact import apply_to_doc  # type: ignore[import-not-found]
    except ImportError:
        return data
    return apply_to_doc(data)


def _check_event_excerpt_size(event: dict[str, Any]) -> None:
    """Raise ``WriteError`` if ``event.payload.excerpt.text`` is too long.

    Only the top-level ``payload.excerpt.text`` is inspected for v0; deeper
    nesting is not part of the spec's excerpt contract.
    """
    payload = event.get("payload")
    if not isinstance(payload, dict):
        return
    excerpt = payload.get("excerpt")
    if not isinstance(excerpt, dict):
        return
    text = excerpt.get("text")
    if isinstance(text, str) and len(text) > MAX_EXCERPT_CHARS:
        raise WriteError(
            f"excerpt.text length {len(text)} exceeds MAX_EXCERPT_CHARS={MAX_EXCERPT_CHARS}"
        )


def _validate_or_write_error(doc: dict[str, Any], *, schema_name: str | None = None) -> None:
    try:
        validate_doc(doc, schema_name=schema_name)
    except SchemaError as exc:
        raise WriteError(f"schema validation failed: {exc}") from exc


def atomic_write_json(path: Path, data: dict[str, Any], *, redact: bool = True) -> None:
    """Atomically write *data* as JSON to *path* after schema validation.

    Steps:
        1. Confirm *data* is a dict containing a ``schema`` field.
        2. Optionally redact (no-op until task_22 lands).
        3. Validate against the inferred schema.
        4. Write to a sibling tempfile, ``fsync``, ``os.rename`` over *path*.
        5. On any failure, remove the tempfile and propagate ``WriteError``.

    Raises:
        WriteError: on shape/validation/IO failure.
    """
    path = Path(path)
    if not isinstance(data, dict):
        raise WriteError("atomic_write_json requires a dict")
    if "schema" not in data:
        raise WriteError("document missing required 'schema' field")

    payload = _maybe_redact(data) if redact else data
    _validate_or_write_error(payload)

    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_name = tempfile.mkstemp(dir=str(parent), prefix=".tmp_", suffix=path.suffix or ".json")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.rename(tmp_name, str(path))
    except Exception as exc:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_name)
        if isinstance(exc, WriteError):
            raise
        raise WriteError(f"failed to write {path}: {exc}") from exc
    finally:
        # Defensive: if rename succeeded the tmp is gone; if not, try to
        # ensure no stray tempfile remains.
        if tmp_path.exists():
            with contextlib.suppress(FileNotFoundError):
                os.unlink(tmp_name)


def append_event(run_dir: Path, event: dict[str, Any]) -> None:
    """Append a single validated event line to ``run_dir/events.jsonl``.

    Holds an exclusive ``file_lock`` over ``events.jsonl.lock`` while
    appending. The line is newline-terminated JSON with sorted keys.

    Raises:
        WriteError: on shape failure, oversize excerpt, or schema failure.
    """
    if not isinstance(event, dict):
        raise WriteError("append_event requires a dict")
    if "schema" not in event:
        raise WriteError("event missing required 'schema' field")

    payload = _maybe_redact(event)
    _check_event_excerpt_size(payload)
    _validate_or_write_error(payload, schema_name="event")

    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    events_path = run_dir / "events.jsonl"
    lock_path = run_dir / "events.jsonl.lock"

    line = json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"
    encoded = line.encode("utf-8")

    with file_lock(lock_path, mode="exclusive"):
        try:
            with open(events_path, "ab", buffering=0) as f:
                f.write(encoded)
                os.fsync(f.fileno())
        except OSError as exc:
            raise WriteError(f"failed to append event to {events_path}: {exc}") from exc


def write_run_meta(run_dir: Path, run: dict[str, Any]) -> None:
    """Write ``run_dir/run.json`` via ``atomic_write_json``."""
    atomic_write_json(Path(run_dir) / "run.json", run)


def write_final(run_dir: Path, final: dict[str, Any]) -> None:
    """Write ``run_dir/final.json`` via ``atomic_write_json``."""
    atomic_write_json(Path(run_dir) / "final.json", final)


def write_workspace_pointer(workspace_root: Path, run_id: str, run_dir: Path) -> None:
    """Create the workspace-local current-run marker for *run_id*.

    The marker is itself a directory; it contains a ``run_dir`` text file
    whose contents are the absolute path of the recorded run tree.
    """
    marker = current_run_marker(Path(workspace_root), run_id)
    marker.mkdir(parents=True, exist_ok=True)
    pointer = marker / "run_dir"
    pointer.write_text(str(Path(run_dir).resolve()), encoding="utf-8")


__all__ = [
    "WriteError",
    "append_event",
    "atomic_write_json",
    "write_final",
    "write_run_meta",
    "write_workspace_pointer",
]
