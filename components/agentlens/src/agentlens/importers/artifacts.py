"""Atomic JSON artifact writer for importer outputs (spec §4.1).

`write_artifact_json` writes a dict to disk in a way that guarantees a reader
either sees the previous file (or no file) or the fully-written new file —
never a half-written file. Uses the standard same-directory tempfile +
fsync + ``os.replace`` pattern so the target rename is atomic on POSIX.

The JSON encoding is deterministic (``sort_keys=True``, ``indent=2``,
trailing newline) so two runs over the same data produce byte-identical
output, which makes ``git diff`` of imported reports legible.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

__all__ = ["write_artifact_json"]


def write_artifact_json(path: str | Path, data: dict) -> None:
    """Write *data* to *path* atomically as deterministic JSON.

    Algorithm:

    1. Encode ``data`` once with ``json.dumps(sort_keys=True, indent=2)`` plus
       a trailing newline.
    2. Create a sibling tempfile (same directory) so the final ``os.replace``
       is a rename within one filesystem.
    3. Write, ``flush``, ``fsync`` the tempfile.
    4. ``os.replace`` the tempfile over *path*.
    5. On any failure, unlink the tempfile so we never leave debris next to
       the target.

    No schema validation — callers (importers) are responsible for shape.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    text = json.dumps(data, sort_keys=True, indent=2) + "\n"

    fd, tmp_str = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=str(target.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_str, target)
    except BaseException:
        # Best-effort cleanup; preserve the original exception.
        try:
            os.unlink(tmp_str)
        except OSError:
            pass
        raise
