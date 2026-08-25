"""ledger.py — Usage transcription into the cost ledger (CME v3.0 T8).

Public API
----------
extract_payload(result_file_text: str) -> tuple[dict, dict]
    Parse the `claude -p --output-format json` envelope.
    Returns (payload, usage) where usage has total_cost_usd folded in.
    Raises LedgerParseError on unparseable input or missing required keys.

record(state: dict, task_id: str, role: str, usage: dict) -> dict
    Accumulate usage into state.cost_ledger (by_task + totals).
    Returns a NEW state dict (input is never mutated — matches transitions.py).
    Preserves accumulate_cost.py semantics:
      by_task[plan::task::role] = latest entry (same-role retries OVERWRITE)
      totals INCREMENT every call (cumulative spend is always correct)

T16 seam
--------
The envelope key names (structured_output / result / usage / total_cost_usd)
are verified against real `claude -p` output in T16.  If the CLI changes its
envelope schema, update _parse_envelope() below — the seam is clearly
labelled inside that function.
"""

from __future__ import annotations

import copy
import datetime
import json
import sys
from pathlib import Path
from typing import Any

# ── price_table import ─────────────────────────────────────────────────────────
# ledger.py lives in scripts/kernel/ → price_table.py is one level up in scripts/
_SCRIPTS_DIR = str(Path(__file__).resolve().parent.parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

try:
    from price_table import compute_cost  # type: ignore
except ImportError as _e:
    raise ImportError(
        f"Cannot import price_table from {_SCRIPTS_DIR}: {_e}"
    ) from _e


# ── constants ─────────────────────────────────────────────────────────────────

USAGE_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cached_read_tokens",
    "cached_write_tokens",
    "cache_read_tokens",
    "cache_creation_tokens",
)


# ── exceptions ────────────────────────────────────────────────────────────────

class LedgerParseError(Exception):
    """Raised when the claude -p result envelope cannot be parsed."""


# ── helpers ───────────────────────────────────────────────────────────────────

def _empty_aggregate() -> dict:
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "cached_read_tokens": 0,
        "cached_write_tokens": 0,
        "cache_read_tokens": 0,
        "cache_creation_tokens": 0,
        "cost_usd": 0.0,
        "dispatches": 0,
    }


def _normalize_usage(raw: dict) -> dict:
    """Normalise token counts; preserve total_cost_usd if present."""
    out = {k: int(raw.get(k, 0) or 0) for k in USAGE_FIELDS}
    if "total_cost_usd" in raw:
        out["total_cost_usd"] = float(raw["total_cost_usd"])
    if "model" in raw:
        out["model"] = raw["model"]
    return out


def _resolve_active_plan_key(state: dict) -> str:
    """Resolve the active plan identifier string.

    Mirrors accumulate_cost.py's _resolve_active_plan_key exactly so that
    by_task keys are consistent with the pre-T8 accumulation path.
    """
    if "plan_chain" in state and state["plan_chain"]:
        return str(state.get("active_plan", 0))
    ap = state.get("active_plan")
    if isinstance(ap, str):
        return ap
    return state.get("plan", "plan1") or "plan1"


def _increment(agg: dict, usage: dict, cost: float) -> None:
    """Increment aggregate counters (totals + any by_* aggregate)."""
    for k in USAGE_FIELDS:
        agg[k] = int(agg.get(k, 0)) + int(usage.get(k, 0))
    agg["cost_usd"] = float(agg.get("cost_usd", 0.0)) + float(cost)
    agg["dispatches"] = int(agg.get("dispatches", 0)) + 1


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── public API ────────────────────────────────────────────────────────────────

def extract_payload(result_file_text: str) -> tuple[dict, dict]:
    """Parse the `claude -p --output-format json` result envelope.

    Envelope parsing rules (T16-verification seam — update keys here if the
    real CLI output differs):
    ┌─────────────────────────────────────────────────────────────────────┐
    │  T16 SEAM: These are the envelope key names expected from           │
    │  `claude -p --output-format json`. Verify against real CLI output.  │
    │                                                                     │
    │  Payload source (in priority order):                                │
    │    1. envelope["structured_output"]  (dict)                         │
    │    2. envelope["result"]  (dict or JSON string → json.loads)        │
    │                                                                     │
    │  Usage source:                                                      │
    │    envelope["usage"]  (dict of token counts)                        │
    │    envelope["total_cost_usd"]  (float, folded into returned usage)  │
    └─────────────────────────────────────────────────────────────────────┘

    Returns
    -------
    (payload, usage) where usage has "total_cost_usd" folded in.

    Raises
    ------
    LedgerParseError — envelope is not valid JSON, or NEITHER a payload source
                       NOR a usage dict is present.
    """
    # T16 SEAM: envelope key names — update _and_ verify this function against
    # real `claude -p --output-format json` output in T16. Keys parsed:
    #   structured_output (preferred payload), result (fallback payload),
    #   usage (token counts), total_cost_usd (folded into returned usage).
    try:
        envelope = json.loads(result_file_text)
    except json.JSONDecodeError as exc:
        raise LedgerParseError(
            f"result envelope is not valid JSON: {exc}"
        ) from exc

    if not isinstance(envelope, dict):
        raise LedgerParseError(
            f"result envelope must be a JSON object, got {type(envelope).__name__}"
        )

    # ── Payload extraction (prefer structured_output over result) ─────────────
    payload: dict | None = None

    if "structured_output" in envelope:
        so = envelope["structured_output"]
        if isinstance(so, dict):
            payload = so
        elif isinstance(so, str):
            try:
                payload = json.loads(so)
            except json.JSONDecodeError:
                pass  # fall through to result key

    if payload is None and "result" in envelope:
        result_val = envelope["result"]
        if isinstance(result_val, dict):
            payload = result_val
        elif isinstance(result_val, str):
            try:
                payload = json.loads(result_val)
            except json.JSONDecodeError:
                pass  # result is a non-JSON string; no usable payload

    # ── Usage extraction ──────────────────────────────────────────────────────
    raw_usage: dict | None = None
    if "usage" in envelope and isinstance(envelope["usage"], dict):
        raw_usage = dict(envelope["usage"])
    else:
        raw_usage = {}

    # Fold top-level total_cost_usd into usage dict
    if "total_cost_usd" in envelope:
        raw_usage["total_cost_usd"] = float(envelope["total_cost_usd"])

    # ── Validation — raise if BOTH payload and usage are absent ───────────────
    if payload is None and not raw_usage:
        raise LedgerParseError(
            "Envelope contains neither a parseable payload "
            "(structured_output / result) nor a usage dict. "
            "Keys found: " + ", ".join(envelope.keys())
        )

    if payload is None:
        # Usage present but no payload — return empty dict so callers don't crash
        payload = {}

    # T16 SEAM: return raw_usage verbatim (preserving all CLI-provided keys such
    # as cache_creation_input_tokens, service_tier, etc.) so T16 can verify the
    # real `claude -p` envelope against this assumption.  Do NOT normalize here —
    # record() pulls only the fields it needs via usage.get(...).
    return payload, raw_usage


def record(state: dict, task_id: str, role: str, usage: dict) -> dict:
    """Accumulate usage into cost_ledger; return a NEW state (input not mutated).

    Semantics (from accumulate_cost.py — preserved exactly):
      by_task[plan::task::role]  = latest entry — same-role retries OVERWRITE
      totals                     = INCREMENT every call (cumulative spend)

    Cost computation:
      If usage["total_cost_usd"] is present: trust it.
      Otherwise: compute via price_table.compute_cost() using usage["model"]
                 (falls back to "unknown" → cost_usd=0.0 if model absent).

    Plan key derivation:
      Mirrors accumulate_cost.py._resolve_active_plan_key():
        - plan_chain present → str(active_plan) index
        - active_plan is a str → use it directly
        - otherwise → state["plan"] or "plan1"
    """
    s = copy.deepcopy(state)

    # Ensure cost_ledger structure exists (brief scopes ledger to by_task + totals)
    ledger = s.setdefault("cost_ledger", {
        "by_task": {}, "totals": _empty_aggregate(),
    })
    ledger.setdefault("by_task", {})
    ledger.setdefault("totals", _empty_aggregate())

    # Normalize usage fields
    norm_usage = {k: int(usage.get(k, 0) or 0) for k in USAGE_FIELDS}

    # Cost resolution
    if "total_cost_usd" in usage and usage["total_cost_usd"] is not None:
        cost = float(usage["total_cost_usd"])
    else:
        model = usage.get("model", "unknown") or "unknown"
        cost = compute_cost(model, norm_usage)

    # Build by_task entry
    active_key = _resolve_active_plan_key(s)
    by_task_key = f"{active_key}::{task_id}::{role}"
    entry: dict[str, Any] = {
        **norm_usage,
        "cost_usd": cost,
        "role": role,
        "recorded_at": _utc_now_iso(),
    }
    if "model" in usage:
        entry["model"] = usage["model"]

    # by_task: OVERWRITE same-role retries (cost-auto-waive regression fix)
    ledger["by_task"][by_task_key] = entry

    # totals: INCREMENT every call (cumulative spend must always be correct)
    _increment(ledger["totals"], norm_usage, cost)

    return s
