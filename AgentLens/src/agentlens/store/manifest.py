"""Run-tree manifest with two-phase seal (spec §5.7, §6.2; schema §S1.6.7).

The manifest is the run-tree's tamper-evidence record: a list of every
durable file under ``run_dir`` with its sha256 digest, sealed in one of
three phases:

  * ``pre_eval``           — frozen before the evaluator runs.
  * ``final``              — frozen after ``eval.json`` is written; overwrites
                             the pre_eval manifest.
  * ``recording_incomplete`` — best-effort seal on IO failure.

The manifest references every file in the run tree EXCEPT itself; tempfiles
(``.tmp_*``) and lock files (``*.lock``) are also excluded. ``eval.json`` is
included only when ``include_eval=True`` (i.e. during the ``final`` seal).

Public API:
    seal(run_dir, phase)
    collect_files(run_dir, *, include_eval) -> list[ManifestEntry]
    verify(run_dir) -> list[ManifestEntry]
    init_manifest(run_dir)
    seal_pre_eval(run_dir)
    seal_final(run_dir)
    mark_recording_incomplete(run_dir, reason)
    class ManifestEntry
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from ..constants import SCHEMA_MANIFEST_V1, SEAL_PHASES
from ..time import utc_now_iso
from .writer import atomic_write_json

SealPhase = Literal["pre_eval", "final", "recording_incomplete"]

_EXCLUDED_FILES: frozenset[str] = frozenset({"manifest.json"})
_HASH_CHUNK = 64 * 1024


@dataclass(frozen=True)
class ManifestEntry:
    """One manifest row: run_dir-relative POSIX path + sha256 digest.

    The ``sha256`` field is formatted as ``"sha256:<64 hex>"`` per the
    schema's ``^sha256:[a-f0-9]{64}$`` pattern.
    """

    path: str
    sha256: str


def _current_redaction_policy() -> dict[str, str]:
    """Return the default redaction policy block.

    Until the redaction module (task_22) lands, the policy is the v1 default.
    """
    return {
        "absolute_paths": "masked",
        "secret_like_values": "masked",
        "full_prompts": "not_stored",
        "full_command_output": "excerpted",
    }


def _hash_file(path: Path) -> str:
    """Return ``"sha256:<hex>"`` for *path*, streaming in 64 KiB chunks."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(_HASH_CHUNK)
            if not chunk:
                break
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def _is_excluded(rel_path: str, name: str) -> bool:
    """Return True if *rel_path* / *name* should not appear in the manifest."""
    if name in _EXCLUDED_FILES:
        return True
    if name.startswith(".tmp_"):
        return True
    if name.endswith(".lock"):
        return True
    return False


def collect_files(run_dir: Path, *, include_eval: bool) -> list[ManifestEntry]:
    """Walk *run_dir* and return one :class:`ManifestEntry` per durable file.

    Args:
        run_dir: the run tree root.
        include_eval: include ``eval.json`` when present (``final`` phase).

    Behaviour:
      * Excludes ``manifest.json`` (self), ``.tmp_*`` tempfiles, ``*.lock``
        files. When ``include_eval`` is False, ``eval.json`` is also excluded.
      * Files missing on disk are silently skipped (``recording_incomplete``
        path).
      * Result is sorted alphabetically by relative POSIX path.
    """
    run_dir = Path(run_dir)
    entries: list[ManifestEntry] = []
    if not run_dir.is_dir():
        return entries

    for path in run_dir.rglob("*"):
        if not path.is_file():
            continue
        try:
            rel = path.relative_to(run_dir).as_posix()
        except ValueError:
            continue
        name = path.name
        if _is_excluded(rel, name):
            continue
        if not include_eval and rel == "eval.json":
            continue
        try:
            digest = _hash_file(path)
        except OSError:
            # Best-effort: a vanished/unreadable file is treated as missing.
            continue
        entries.append(ManifestEntry(path=rel, sha256=digest))

    entries.sort(key=lambda e: e.path)
    return entries


def _build_manifest_doc(
    run_id: str,
    phase: SealPhase,
    entries: list[ManifestEntry],
) -> dict[str, Any]:
    return {
        "schema": SCHEMA_MANIFEST_V1,
        "run_id": run_id,
        "sealed_at": utc_now_iso(),
        "sealed": True,
        "sealed_phase": phase,
        "files": [{"path": e.path, "sha256": e.sha256} for e in entries],
        "redaction": _current_redaction_policy(),
    }


def seal(run_dir: Path, phase: SealPhase) -> None:
    """Seal *run_dir* with manifest at *phase*.

    Steps:
      1. ``collect_files(run_dir, include_eval=(phase == "final"))``.
      2. Build the manifest doc with ``run_id = run_dir.name``.
      3. ``atomic_write_json(run_dir/"manifest.json", doc, redact=False)``.

    The manifest itself is not subject to redaction (spec §5.7).

    Raises:
        ValueError: if *phase* is not a valid seal phase.
        WriteError: from :func:`atomic_write_json` on validation/IO failure.
    """
    if phase not in SEAL_PHASES:
        raise ValueError(
            f"invalid seal phase: {phase!r}; expected one of {sorted(SEAL_PHASES)}"
        )
    run_dir = Path(run_dir)
    entries = collect_files(run_dir, include_eval=(phase == "final"))
    doc = _build_manifest_doc(run_dir.name, phase, entries)
    atomic_write_json(run_dir / "manifest.json", doc, redact=False)


def verify(run_dir: Path) -> list[ManifestEntry]:
    """Recompute sha256s and return entries whose digest no longer matches.

    The returned list contains the *current on-disk* :class:`ManifestEntry`
    rows that disagree with the sealed manifest. If a file listed in the
    manifest no longer exists, it is reported with an empty sha256.
    """
    run_dir = Path(run_dir)
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.is_file():
        return []
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected: dict[str, str] = {
        item["path"]: item["sha256"] for item in manifest.get("files", [])
    }

    mismatches: list[ManifestEntry] = []
    for rel, expected_digest in expected.items():
        candidate = run_dir / rel
        if not candidate.is_file():
            mismatches.append(ManifestEntry(path=rel, sha256=""))
            continue
        actual_digest = _hash_file(candidate)
        if actual_digest != expected_digest:
            mismatches.append(ManifestEntry(path=rel, sha256=actual_digest))
    return mismatches


# ---- plan-alias wrappers --------------------------------------------------


def init_manifest(run_dir: Path) -> None:
    """Plan alias for :func:`seal` with phase ``pre_eval``."""
    seal(run_dir, "pre_eval")


def seal_pre_eval(run_dir: Path) -> None:
    """Plan alias for :func:`seal` with phase ``pre_eval``."""
    seal(run_dir, "pre_eval")


def seal_final(run_dir: Path) -> None:
    """Plan alias for :func:`seal` with phase ``final``."""
    seal(run_dir, "final")


def mark_recording_incomplete(run_dir: Path, reason: str | None = None) -> None:
    """Plan alias for :func:`seal` with phase ``recording_incomplete``.

    ``reason`` is accepted for API compatibility with the plan but is NOT
    written into the manifest: ``manifest.schema.json`` v1 has
    ``additionalProperties: false`` and does not define a
    ``recording_incomplete_reason`` field. A future v2 schema bump could
    carry it; for v0 the reason is discarded.
    """
    del reason  # intentionally unused; see docstring.
    seal(run_dir, "recording_incomplete")


__all__ = [
    "ManifestEntry",
    "SealPhase",
    "collect_files",
    "init_manifest",
    "mark_recording_incomplete",
    "seal",
    "seal_final",
    "seal_pre_eval",
    "verify",
]
