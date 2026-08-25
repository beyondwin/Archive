"""events.py — Event tee to events.jsonl + optional agentlens emit (CME v3.0 T8).

Public API
----------
emit(orch_dir, event_type, payload, agentlens_run_id=None, *, now=None) -> None
    ALWAYS appends one JSON line to <orch_dir>/events.jsonl (the unconditional
    tee).  Each line includes at minimum:
        event_type  — caller-supplied namespace string (e.g. "kws-cme.dispatch.started")
        ts          — ISO 8601 UTC timestamp (real time, or injected via now= for tests)
      plus all keys from payload.

    If agentlens_run_id is provided, ALSO attempts best-effort:
        agentlens emit --run-id <id> --event <type> --payload <json> 2>/dev/null
    Any failure (binary absent, exit error, etc.) is silently swallowed.
    The tee is NEVER affected by agentlens failure.

    now (keyword-only): injectable timestamp string (ISO 8601).  Used by tests
    for deterministic output.  Defaults to utcnow() when absent.
"""

from __future__ import annotations

import datetime
import json
import os
import subprocess


def emit(
    orch_dir: str,
    event_type: str,
    payload: dict,
    agentlens_run_id: str | None = None,
    *,
    now: str | None = None,
) -> None:
    """Append one event line to <orch_dir>/events.jsonl.

    Parameters
    ----------
    orch_dir         : path to the orchestrator working directory
    event_type       : event namespace string, e.g. "kws-cme.dispatch.started"
    payload          : dict of event-specific fields (merged into the record)
    agentlens_run_id : if provided, best-effort agentlens emit (never raises)
    now              : injectable ISO 8601 timestamp (for deterministic tests)
    """
    # -- Timestamp ------------------------------------------------------------
    ts = now if now is not None else _utc_now_iso()

    # -- Build record ---------------------------------------------------------
    record: dict = {"event_type": event_type, "ts": ts}
    record.update(payload)

    # -- Write to tee (unconditional) ----------------------------------------
    os.makedirs(orch_dir, exist_ok=True)
    jsonl_path = os.path.join(orch_dir, "events.jsonl")
    with open(jsonl_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # -- Best-effort agentlens emit (MUST NOT raise) --------------------------
    if agentlens_run_id is not None:
        _agentlens_emit_best_effort(agentlens_run_id, event_type, record)


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _agentlens_emit_best_effort(
    run_id: str,
    event_type: str,
    payload: dict,
) -> None:
    """Attempt agentlens emit; silently swallow ALL failures.

    Semantics: `agentlens emit ... 2>/dev/null || true`
    The tee (events.jsonl) has already been written before this is called.
    """
    try:
        payload_json = json.dumps(payload, ensure_ascii=False)
        subprocess.run(
            [
                "agentlens",
                "emit",
                "--run-id", run_id,
                "--event", event_type,
                "--payload", payload_json,
            ],
            capture_output=True,
            timeout=5,
            check=False,  # do not raise on non-zero exit
        )
    except Exception:
        # Covers: FileNotFoundError (binary absent), TimeoutExpired, OSError, etc.
        pass
