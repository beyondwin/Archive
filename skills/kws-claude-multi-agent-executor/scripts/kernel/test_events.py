#!/usr/bin/env python3
"""TDD tests for events.py — CME v3.0 T8.

Test cases:
- emit twice → 2 jsonl lines, each parseable with event_type/ts fields
- agentlens-absent environment raises NO exception
- ts field is a valid ISO datetime string
"""

from __future__ import annotations
import json
import os
import sys
import tempfile
import traceback
from pathlib import Path

# Add kernel dir to path so events is importable directly
sys.path.insert(0, str(Path(__file__).resolve().parent))
import events


# ── helpers ───────────────────────────────────────────────────────────────────

def _parse_jsonl(path: str) -> list[dict]:
    lines = Path(path).read_text(encoding="utf-8").strip().splitlines()
    return [json.loads(ln) for ln in lines if ln.strip()]


def _is_iso_datetime(s: str) -> bool:
    """Check that s looks like an ISO 8601 datetime string."""
    import datetime
    try:
        # Accept both Z and +00:00 suffixes
        s2 = s.replace("Z", "+00:00") if s.endswith("Z") else s
        datetime.datetime.fromisoformat(s2)
        return True
    except ValueError:
        return False


# ── test functions ─────────────────────────────────────────────────────────────

def test_emit_two_lines_jsonl():
    """emit twice → exactly 2 jsonl lines, each parseable."""
    with tempfile.TemporaryDirectory() as tmp:
        events.emit(tmp, "kws-cme.test.started", {"task": "t1"})
        events.emit(tmp, "kws-cme.test.completed", {"task": "t1", "result": "DONE"})

        jsonl_path = os.path.join(tmp, "events.jsonl")
        assert os.path.exists(jsonl_path), "events.jsonl not created"
        records = _parse_jsonl(jsonl_path)
        assert len(records) == 2, f"Expected 2 lines, got {len(records)}"
    print("  [PASS] test_emit_two_lines_jsonl")


def test_emit_required_fields():
    """Each emitted line has event_type and ts fields."""
    with tempfile.TemporaryDirectory() as tmp:
        events.emit(tmp, "kws-cme.dispatch.started", {"role": "implementer"})

        records = _parse_jsonl(os.path.join(tmp, "events.jsonl"))
        assert len(records) == 1
        rec = records[0]
        assert "event_type" in rec, f"Missing event_type: {rec}"
        assert "ts" in rec, f"Missing ts: {rec}"
        assert rec["event_type"] == "kws-cme.dispatch.started", \
            f"Wrong event_type: {rec['event_type']}"
        assert _is_iso_datetime(rec["ts"]), f"ts is not ISO datetime: {rec['ts']!r}"
    print("  [PASS] test_emit_required_fields")


def test_emit_payload_included():
    """Payload fields are included in the emitted line."""
    with tempfile.TemporaryDirectory() as tmp:
        events.emit(tmp, "kws-cme.test.ping", {"key": "value", "count": 42})
        records = _parse_jsonl(os.path.join(tmp, "events.jsonl"))
        rec = records[0]
        assert rec.get("key") == "value", f"Payload key missing: {rec}"
        assert rec.get("count") == 42, f"Payload count missing: {rec}"
    print("  [PASS] test_emit_payload_included")


def test_emit_agentlens_absent_no_exception():
    """agentlens_run_id provided but agentlens binary absent → NO exception."""
    with tempfile.TemporaryDirectory() as tmp:
        # Pass a fake agentlens run id; the binary will not be found
        try:
            events.emit(
                tmp,
                "kws-cme.test.agentlens_absent",
                {"x": 1},
                agentlens_run_id="fake-run-id-12345",
            )
        except Exception as e:
            assert False, f"emit() raised exception with absent agentlens: {e}"

        # The tee should still have written the jsonl line
        records = _parse_jsonl(os.path.join(tmp, "events.jsonl"))
        assert len(records) == 1, f"Expected 1 line even when agentlens absent: {records}"
    print("  [PASS] test_emit_agentlens_absent_no_exception")


def test_emit_creates_orch_dir_if_needed():
    """emit() creates the orch_dir if it doesn't exist yet."""
    with tempfile.TemporaryDirectory() as tmp:
        new_dir = os.path.join(tmp, "new_orch_dir")
        assert not os.path.exists(new_dir)
        events.emit(new_dir, "kws-cme.test.created", {})
        assert os.path.exists(os.path.join(new_dir, "events.jsonl")), \
            "events.jsonl not created in new orch_dir"
    print("  [PASS] test_emit_creates_orch_dir_if_needed")


def test_emit_injectable_timestamp():
    """emit() accepts an injectable now kwarg for deterministic testing."""
    fixed_ts = "2026-07-07T00:00:00Z"
    with tempfile.TemporaryDirectory() as tmp:
        events.emit(tmp, "kws-cme.test.ts", {}, now=fixed_ts)
        records = _parse_jsonl(os.path.join(tmp, "events.jsonl"))
        rec = records[0]
        assert rec["ts"] == fixed_ts, f"Injected ts not used: {rec['ts']!r}"
    print("  [PASS] test_emit_injectable_timestamp")


# ── runner ────────────────────────────────────────────────────────────────────

ALL_TESTS = [
    test_emit_two_lines_jsonl,
    test_emit_required_fields,
    test_emit_payload_included,
    test_emit_agentlens_absent_no_exception,
    test_emit_creates_orch_dir_if_needed,
    test_emit_injectable_timestamp,
]


if __name__ == "__main__":
    print(f"test_events.py: {len(ALL_TESTS)} defined / {len(ALL_TESTS)} invoked")
    failures = []
    for fn in ALL_TESTS:
        try:
            fn()
        except Exception as e:
            failures.append((fn.__name__, e))
            traceback.print_exc()
    if failures:
        print(f"\nFAILED {len(failures)}/{len(ALL_TESTS)}:")
        for name, exc in failures:
            print(f"  {name}: {exc}")
        sys.exit(1)
    print(f"\nOK — {len(ALL_TESTS)}/{len(ALL_TESTS)} passed")
