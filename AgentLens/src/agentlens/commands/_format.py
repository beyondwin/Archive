"""JSON output schema (v1) — centralized projectors (spec §10.2, task_12).

This module is the *only* place that decides what keys appear in the
``--format json`` output of query commands. It enforces three contracts:

1. **Schema lock.** Each projector returns a dict with a deterministic key
   set; missing values become documented defaults (never ``None`` for
   user-facing strings). The shapes here are pinned by snapshot tests at
   ``tests/integration/test_format_json_snapshot.py`` and the golden files
   under ``tests/fixtures/format_snapshots/``.

2. **No absolute paths.** ``query.full_scan_runs`` includes ``_source_dir``
   on schema-invalid rows. That field carries an absolute filesystem path
   and MUST be stripped before emission.

3. **Forward compat.** Add a key in a new minor version → bump the
   snapshot files (and document the schema in the projector docstring).

The schema version constant lives in code only — it is not emitted in the
output dict (so existing assertions like ``json.loads(...) is None`` for
the "no runs" case remain valid).
"""
from __future__ import annotations

from typing import Any

__all__ = [
    "JSON_SCHEMA_VERSION",
    "project_failure",
    "project_risk",
    "project_run_row",
    "project_show",
]

# Bump this when the JSON shape changes in a breaking way. Snapshot files
# must be regenerated together with any bump.
JSON_SCHEMA_VERSION = "v1"


# Canonical run-row keys (parity with ``store.query._RUN_ROW_COLUMNS``).
_RUN_ROW_KEYS: tuple[str, ...] = (
    "run_id",
    "workspace_id",
    "parent_run_id",
    "started_at",
    "ended_at",
    "agent_name",
    "agent_mode",
    "recording_mode",
    "agent_outcome",
    "eval_status",
    "sealed_phase",
)

# Optional keys that flow through from query.latest / query.full_scan_runs
# when present (eval doc top-level "status" mirror; final.residual_risks).
_RUN_ROW_OPTIONAL_KEYS: tuple[str, ...] = (
    "status",
    "residual_risks",
)

# task_18: importer-artifact projections. Always emitted (None default) so
# the projected row shape stays stable for both container runs (no artifacts)
# and imported runs.
_IMPORT_PROJECTION_KEYS: tuple[str, ...] = (
    "display_title",
    "usage",
    "import_state",
)

# Failure dict locked keys. Includes evaluator-emitted detail fields
# (confidence, evidence, recoverability) so the snapshot pins the full
# evaluator output surface.
_FAILURE_KEYS: tuple[str, ...] = (
    "run_id",
    "workspace_id",
    "category",
    "severity",
    "source",
    "blame_scope",
    "summary",
    "confidence",
    "recoverability",
    "evidence",
)

_RISK_KEYS: tuple[str, ...] = (
    "run_id",
    "workspace_id",
    "category",
    "source",
    "severity",
    "summary",
)

# Defaults for missing string-valued fields. ``eval_status`` defaults to
# ``"needs_eval"`` per spec §6.3 ("eval.json absent → needs_eval, owned by
# query layer"). Other string fields default to "" (deterministic). Optional
# typed fields default to ``None`` to keep "absence" round-trippable.
_RUN_ROW_STRING_DEFAULTS: dict[str, Any] = {
    "run_id": "",
    "workspace_id": "",
    "parent_run_id": None,
    "started_at": "",
    "ended_at": "",
    "agent_name": "",
    "agent_mode": "",
    "recording_mode": "",
    "agent_outcome": "",
    "eval_status": "needs_eval",
    "sealed_phase": "",
}


def _coalesce(value: Any, default: Any) -> Any:
    """Return *value* when truthy/non-None, else *default*.

    Empty strings are treated as "missing" so the placeholder defaults apply
    consistently (e.g., ``eval_status=""`` → ``"needs_eval"``).
    """
    if value is None or value == "":
        return default
    return value


def project_run_row(row: dict[str, Any]) -> dict[str, Any]:
    """Lock a single run-row to the v1 schema.

    Accepts rows from :func:`agentlens.store.query.latest`,
    :func:`agentlens.store.query.full_scan_runs`, and (with caveats) the
    merged dict returned by :func:`agentlens.store.query.get_run`.

    Always returns the 11 canonical keys. For schema-invalid rows (those
    with ``schema_invalid: True``), emits the canonical keys with defaults
    plus ``schema_invalid: True`` — and **omits ``_source_dir``** so no
    absolute filesystem path is leaked. Optional keys (``status``,
    ``residual_risks``) are included when present in input.
    """
    if row.get("schema_invalid"):
        out: dict[str, Any] = {key: _RUN_ROW_STRING_DEFAULTS[key] for key in _RUN_ROW_KEYS}
        # Carry through the few identity fields we can recover from the
        # broken row (run_id is the directory name; workspace_id is the
        # parent dir name — both safe, no path leak).
        if row.get("run_id"):
            out["run_id"] = str(row.get("run_id"))
        if row.get("workspace_id"):
            out["workspace_id"] = str(row.get("workspace_id"))
        out["parent_run_id"] = None
        # task_18: importer-artifact projections are always emitted, even on
        # schema-invalid rows, so the shape is stable for consumers.
        for key in _IMPORT_PROJECTION_KEYS:
            out[key] = None
        out["schema_invalid"] = True
        return out

    out = {}
    for key in _RUN_ROW_KEYS:
        if key == "parent_run_id":
            # parent_run_id may legitimately be null; preserve None to mean
            # "no parent" rather than collapsing to "".
            out[key] = row.get(key)
            continue
        out[key] = _coalesce(row.get(key), _RUN_ROW_STRING_DEFAULTS[key])
    for key in _RUN_ROW_OPTIONAL_KEYS:
        if key in row and row[key] is not None:
            out[key] = row[key]
    # task_18: always emit the three importer-projection keys (None when the
    # run is a container run without import artifacts).
    for key in _IMPORT_PROJECTION_KEYS:
        out[key] = row.get(key)
    return out


def project_failure(row: dict[str, Any]) -> dict[str, Any]:
    """Lock a single evaluator-failure dict to the v1 schema.

    Always emits every key in :data:`_FAILURE_KEYS`. Missing string fields
    default to ``""``; ``confidence`` defaults to ``None``; ``evidence``
    defaults to ``[]``.
    """
    out: dict[str, Any] = {}
    for key in _FAILURE_KEYS:
        val = row.get(key)
        if key == "evidence":
            out[key] = list(val) if isinstance(val, list) else []
        elif key == "confidence":
            out[key] = val if isinstance(val, (int, float)) else None
        else:
            out[key] = _coalesce(val, "")
    return out


def project_risk(row: dict[str, Any]) -> dict[str, Any]:
    """Lock a single residual-risk dict to the v1 schema.

    Always emits every key in :data:`_RISK_KEYS`. Missing string fields
    default to ``""``. The synthetic ``RECORDING_INCOMPLETE`` /
    ``SCHEMA_INVALID`` rows produced by :func:`agentlens.store.query.risks`
    are accepted as-is (they already carry ``category`` + ``source``).
    """
    out: dict[str, Any] = {}
    for key in _RISK_KEYS:
        out[key] = _coalesce(row.get(key), "")
    return out


def project_show(
    row: dict[str, Any],
    failures: list[dict[str, Any]],
    risks: list[dict[str, Any]],
) -> dict[str, Any]:
    """Lock the ``show`` JSON payload to the v1 schema.

    *row* is the dict produced by ``show._build_summary`` (already flat,
    with ``agent`` as a string). The projector enforces the legacy six
    fields plus task_11 additions (``workspace_id``, ``workspace_short``,
    ``failures``, ``risks``). All ten keys are always present.
    """
    return {
        "run_id": _coalesce(row.get("run_id"), ""),
        "agent": _coalesce(row.get("agent"), "unknown"),
        "started_at": _coalesce(row.get("started_at"), ""),
        "agent_outcome": _coalesce(row.get("agent_outcome"), "unknown"),
        "eval_status": _coalesce(row.get("eval_status"), "needs_eval"),
        "sealed_phase": _coalesce(row.get("sealed_phase"), ""),
        "workspace_id": _coalesce(row.get("workspace_id"), ""),
        "workspace_short": _coalesce(row.get("workspace_short"), "-"),
        # task_18: importer-artifact projections. ``None`` for container runs.
        "display_title": row.get("display_title"),
        "usage": row.get("usage"),
        "import_state": row.get("import_state"),
        "failures": [project_failure(f) for f in failures],
        "risks": [project_risk(r) for r in risks],
    }
