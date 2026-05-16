#!/usr/bin/env python3
"""Append one project-local run event and update state sequence metadata."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


VALID_EVENT_TYPES = {
    "run_started",
    "context_snapshot_created",
    "pre_dispatch_checked",
    "dispatch_gate_failed",
    "task_contract_recorded",
    "task_started",
    "task_completed",
    "verification_started",
    "verification_passed",
    "verification_failed",
    "drift_detected",
    "drift_repaired",
    "blocked",
    "failed",
    "finished",
}
SECRET_KEY_RE = re.compile(r"(token|secret|password|api[_-]?key|authorization|cookie|private[_-]?key|session)", re.I)


def redact(value: object) -> object:
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if SECRET_KEY_RE.search(str(key)) else redact(inner)
            for key, inner in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str) and len(value) > 400:
        return value[:397] + "..."
    return value


def expected_journal_path(run_id: str) -> str:
    return f".codex-orchestrator/runs/{run_id}/events.jsonl"


def read_last_seq(journal_path: Path, run_id: str) -> int:
    if not journal_path.is_file():
        return 0
    last_seq = 0
    for line_no, line in enumerate(journal_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        event = json.loads(line)
        if event.get("run_id") != run_id:
            raise ValueError(f"events.jsonl line {line_no} run_id mismatch")
        seq = event.get("seq")
        if not isinstance(seq, int) or seq <= last_seq:
            raise ValueError(f"events.jsonl line {line_no} has non-monotonic seq")
        last_seq = seq
    return last_seq


def append_event(state_path: Path, event_type: str, payload: dict) -> dict:
    state = json.loads(state_path.read_text(encoding="utf-8"))
    run_id = state.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("state.run_id must be a non-empty string")
    if event_type not in VALID_EVENT_TYPES:
        raise ValueError(f"event type must be one of {sorted(VALID_EVENT_TYPES)}")

    payload_run_id = payload.get("run_id")
    if payload_run_id is not None and payload_run_id != run_id:
        raise ValueError("payload run_id does not match state.run_id")

    expected_path = expected_journal_path(run_id)
    existing_path = state.get("event_journal_path")
    if existing_path not in (None, expected_path):
        raise ValueError(f"event_journal_path must be {expected_path}")

    journal_path = state_path.parent / "events.jsonl"
    last_seq = read_last_seq(journal_path, run_id)
    event = {
        "schema_version": "1",
        "run_id": run_id,
        "seq": last_seq + 1,
        "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "type": event_type,
        "payload": redact(payload),
    }

    journal_path.parent.mkdir(parents=True, exist_ok=True)
    with journal_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")

    state["event_journal_path"] = expected_path
    state["last_event_seq"] = event["seq"]
    timestamps = state.get("timestamps")
    if isinstance(timestamps, dict):
        timestamps["updated_at"] = event["timestamp"]
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return event


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True, help="Path to .codex-orchestrator/runs/<run_id>/state.json")
    parser.add_argument("--type", required=True, dest="event_type")
    parser.add_argument("--payload", required=True, help="JSON object payload")
    args = parser.parse_args()

    try:
        payload = json.loads(args.payload)
        if not isinstance(payload, dict):
            raise ValueError("payload must be a JSON object")
        event = append_event(Path(args.state), args.event_type, payload)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(json.dumps({"event": event}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
