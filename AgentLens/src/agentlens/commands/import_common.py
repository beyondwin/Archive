"""Shared finalization helpers for session importers (spec §4.2.5/§4.2.6, plan Task 16).

This module centralises the post-write tail every session importer must run
(``finalize_imported_run``) plus the cross-importer constants for the
``--byte-cap`` flag and its env-var fallback. Both Claude and Codex importers
import from here so the same sealing + evaluation + indexing sequence applies
uniformly and a future invariant (e.g. a new manifest phase) only changes one
file.

Public API:
    DEFAULT_IMPORT_BYTE_CAP
    MIN_IMPORT_BYTE_CAP
    MAX_IMPORT_BYTE_CAP
    BYTE_CAP_ENV_VAR
    validate_byte_cap(value)         — Typer callback
    resolve_byte_cap(flag_value)     — returns (effective, source) per spec §4.1
    finalize_imported_run(run_dir, run_id, analysis_state)
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

import typer

from agentlens.constants import SCHEMA_FINAL_V1
from agentlens.evaluator.engine import evaluate
from agentlens.store import manifest, sqlite_index
from agentlens.store.paths import agentlens_home
from agentlens.store.writer import write_final
from agentlens.time import utc_now_iso

__all__ = [
    "DEFAULT_IMPORT_BYTE_CAP",
    "MIN_IMPORT_BYTE_CAP",
    "MAX_IMPORT_BYTE_CAP",
    "BYTE_CAP_ENV_VAR",
    "validate_byte_cap",
    "resolve_byte_cap",
    "finalize_imported_run",
]

logger = logging.getLogger(__name__)

# Spec §4.1: deep-parse byte cap defaults and bounds.
DEFAULT_IMPORT_BYTE_CAP = 64 * 1024 * 1024  # 64 MiB
MIN_IMPORT_BYTE_CAP = 1 * 1024 * 1024  # 1 MiB
MAX_IMPORT_BYTE_CAP = 1024 * 1024 * 1024  # 1 GiB

BYTE_CAP_ENV_VAR = "AGENTLENS_IMPORT_BYTE_CAP"


def _bad_byte_cap(value: int, *, source_label: str) -> typer.BadParameter:
    return typer.BadParameter(
        f"--byte-cap (from {source_label}) must be between "
        f"{MIN_IMPORT_BYTE_CAP} and {MAX_IMPORT_BYTE_CAP} bytes; got {value}"
    )


def validate_byte_cap(value: Optional[int]) -> Optional[int]:
    """Typer callback that range-checks an explicit ``--byte-cap`` integer.

    Returns the value unchanged when it is None (caller didn't set the flag) or
    within ``[MIN_IMPORT_BYTE_CAP, MAX_IMPORT_BYTE_CAP]``. Raises
    :class:`typer.BadParameter` otherwise so the CLI exits non-zero with a
    usage hint. Env-var range checks live in :func:`resolve_byte_cap`.
    """
    if value is None:
        return None
    if value < MIN_IMPORT_BYTE_CAP or value > MAX_IMPORT_BYTE_CAP:
        raise _bad_byte_cap(value, source_label="flag --byte-cap")
    return value


def resolve_byte_cap(flag_value: Optional[int]) -> tuple[int, str]:
    """Return ``(effective_byte_cap, byte_cap_source)`` per spec §4.1.

    Resolution order: explicit ``--byte-cap`` flag > ``AGENTLENS_IMPORT_BYTE_CAP``
    env var > built-in default. Env-var values that fail to parse or are out
    of range raise :class:`typer.BadParameter` so callers learn at command
    parse time rather than carrying an invalid cap into the importer.
    """
    if flag_value is not None:
        # The Typer callback has already range-checked.
        return flag_value, "flag:--byte-cap"
    raw_env = os.environ.get(BYTE_CAP_ENV_VAR)
    if raw_env is not None and raw_env.strip() != "":
        try:
            parsed = int(raw_env.strip())
        except ValueError as exc:
            raise typer.BadParameter(
                f"{BYTE_CAP_ENV_VAR} must be an integer; got {raw_env!r}"
            ) from exc
        if parsed < MIN_IMPORT_BYTE_CAP or parsed > MAX_IMPORT_BYTE_CAP:
            raise _bad_byte_cap(
                parsed, source_label=f"env {BYTE_CAP_ENV_VAR}"
            )
        return parsed, f"env:{BYTE_CAP_ENV_VAR}"
    return DEFAULT_IMPORT_BYTE_CAP, "default"


def _build_final_doc(run_id: str, agent_outcome: str) -> dict:
    return {
        "schema": SCHEMA_FINAL_V1,
        "run_id": run_id,
        "ended_at": utc_now_iso(),
        "agent_outcome": agent_outcome,
        "summary": "",
        "changed_files": [],
        "verification": [],
        "residual_risks": [],
    }


def finalize_imported_run(
    run_dir: Path, run_id: str, analysis_state: str
) -> None:
    """Wrap an imported run's tail: final.json → seal(pre_eval) → eval → seal(final) → index.

    The sequence mirrors what a recorded container run goes through at
    ``run-close``, with the import-specific twist that ``agent_outcome`` is
    derived from the import's ``analysis_state`` (``"unknown"`` only when the
    deep parse was lossless; ``"partial"`` otherwise).

    Failure handling:

    * If ``seal(pre_eval)`` or ``evaluate()`` raises, we attempt
      ``seal(recording_incomplete)`` so the run tree carries an evidence trail
      and a downstream reader sees a sealed-but-broken phase rather than a
      missing manifest. The original exception is surfaced as a warning to
      stderr but does NOT propagate — the run row exists either way.
    * sqlite indexing errors are logged and absorbed (spec §7.3): the index
      is a derived cache, not a source of truth.
    """
    run_dir = Path(run_dir)
    outcome = "unknown" if analysis_state == "full" else "partial"
    final_doc = _build_final_doc(run_id, outcome)
    write_final(run_dir, final_doc)

    # Phase 1: pre-eval seal + evaluator. A failure here means the run tree
    # is in a known-broken state; mark it recording_incomplete so readers can
    # detect tampering without us silently giving up on a manifest.
    try:
        manifest.seal(run_dir, "pre_eval")
        evaluate(run_dir)
        manifest.seal(run_dir, "final")
    except Exception as exc:  # noqa: BLE001 — surface as warning, never raise
        try:
            manifest.seal(run_dir, "recording_incomplete")
        except Exception as inner:  # noqa: BLE001 — best effort
            logger.warning(
                "finalize_imported_run: recording_incomplete seal failed for %s: %s",
                run_dir,
                inner,
            )
        typer.echo(
            f"warning: finalize failed for {run_dir.name}: {exc}", err=True
        )

    # Phase 2: SQLite index refresh — derived cache, absorb errors.
    try:
        conn = sqlite_index.init_db(agentlens_home())
        try:
            sqlite_index.index_run(conn, run_dir)
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001 — index is derived cache
        logger.warning(
            "finalize_imported_run: sqlite index update failed for %s: %s",
            run_dir,
            exc,
        )
