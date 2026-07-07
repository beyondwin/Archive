#!/usr/bin/env python3
"""TDD tests for ledger.py — CME v3.0 T8.

Test cases:
(a) result/usage envelope → payload dict + usage dict
(b) structured_output key variant → payload
(c) neither present → LedgerParseError
(d) record() → totals.dispatches==1 and by_task key format
"""

from __future__ import annotations
import json
import sys
import traceback
from pathlib import Path

# Add kernel dir to path so ledger is importable directly
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ledger


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_state(plan: str = "my_plan") -> dict:
    return {
        "plan": plan,
        "active_plan": plan,
        "cost_ledger": {
            "by_task": {},
            "totals": {
                "input_tokens": 0,
                "output_tokens": 0,
                "cached_read_tokens": 0,
                "cached_write_tokens": 0,
                "cache_read_tokens": 0,
                "cache_creation_tokens": 0,
                "cost_usd": 0.0,
                "dispatches": 0,
            },
        },
    }


# ── test functions ─────────────────────────────────────────────────────────────

def test_extract_payload_result_key():
    """(a) result key with string JSON → payload dict + usage dict."""
    inner = {"status": "DONE", "summary": "all good"}
    envelope = json.dumps({
        "result": json.dumps(inner),
        "usage": {"input_tokens": 100, "output_tokens": 50},
        "total_cost_usd": 0.01,
    })
    payload, usage = ledger.extract_payload(envelope)
    assert isinstance(payload, dict), f"Expected dict payload, got {type(payload)}"
    assert payload.get("status") == "DONE", f"payload.status wrong: {payload}"
    assert usage.get("input_tokens") == 100, f"input_tokens wrong: {usage}"
    assert usage.get("output_tokens") == 50, f"output_tokens wrong: {usage}"
    assert usage.get("total_cost_usd") == 0.01, f"total_cost_usd not folded in: {usage}"
    print("  [PASS] test_extract_payload_result_key")


def test_extract_payload_structured_output_key():
    """(b) structured_output key (preferred) → payload."""
    inner = {"status": "DONE", "spec_score": 0.9}
    envelope = json.dumps({
        "structured_output": inner,
        "result": "should be ignored when structured_output present",
        "usage": {"input_tokens": 200, "output_tokens": 80},
        "total_cost_usd": 0.05,
    })
    payload, usage = ledger.extract_payload(envelope)
    assert payload.get("spec_score") == 0.9, f"structured_output not preferred: {payload}"
    assert usage.get("total_cost_usd") == 0.05, f"total_cost_usd not folded: {usage}"
    print("  [PASS] test_extract_payload_structured_output_key")


def test_extract_payload_missing_both_raises():
    """(c) neither structured_output nor result → LedgerParseError."""
    envelope = json.dumps({
        "type": "result",
        "some_other_key": "value",
        # no usage either
    })
    try:
        ledger.extract_payload(envelope)
        assert False, "Should have raised LedgerParseError"
    except ledger.LedgerParseError:
        pass
    print("  [PASS] test_extract_payload_missing_both_raises")


def test_extract_payload_invalid_json_raises():
    """Non-JSON envelope raises LedgerParseError, not raw JSONDecodeError."""
    try:
        ledger.extract_payload("not valid json {{")
        assert False, "Should have raised LedgerParseError"
    except ledger.LedgerParseError:
        pass
    print("  [PASS] test_extract_payload_invalid_json_raises")


def test_record_totals_dispatches_and_by_task_key():
    """(d) After record(), totals.dispatches==1 and by_task key has plan::task::role format."""
    state = _make_state(plan="my_plan")
    usage = {
        "input_tokens": 100,
        "output_tokens": 50,
        "total_cost_usd": 0.01,
    }
    new_state = ledger.record(state, "task_3", "implementer", usage)

    # Totals check
    totals = new_state["cost_ledger"]["totals"]
    assert totals["dispatches"] == 1, f"dispatches wrong: {totals['dispatches']}"
    assert totals["input_tokens"] == 100, f"input_tokens wrong: {totals}"
    assert totals["output_tokens"] == 50, f"output_tokens wrong: {totals}"
    assert totals["cost_usd"] == 0.01, f"cost_usd wrong: {totals}"

    # by_task key format
    by_task = new_state["cost_ledger"]["by_task"]
    assert len(by_task) == 1, f"Expected 1 by_task entry, got {by_task}"
    key = list(by_task.keys())[0]
    parts = key.split("::")
    assert len(parts) == 3, f"Key should be plan::task::role, got {key!r}"
    assert parts[1] == "task_3", f"task_id part wrong: {key!r}"
    assert parts[2] == "implementer", f"role part wrong: {key!r}"
    print(f"  [PASS] test_record_totals_dispatches_and_by_task_key (key={key!r})")


def test_record_does_not_mutate_input():
    """record() must not mutate the input state (immutable pattern from transitions)."""
    state = _make_state()
    original_dispatches = state["cost_ledger"]["totals"]["dispatches"]
    usage = {"input_tokens": 10, "output_tokens": 5, "total_cost_usd": 0.001}
    _ = ledger.record(state, "task_1", "reviewer", usage)
    assert state["cost_ledger"]["totals"]["dispatches"] == original_dispatches, \
        "record() mutated input state"
    print("  [PASS] test_record_does_not_mutate_input")


def test_record_retry_overwrites_by_task_but_increments_totals():
    """Same plan::task::role called twice: by_task entry overwrites; totals increment."""
    state = _make_state(plan="p1")
    usage = {"input_tokens": 100, "output_tokens": 50, "total_cost_usd": 0.01}
    s1 = ledger.record(state, "task_1", "implementer", usage)
    s2 = ledger.record(s1, "task_1", "implementer", usage)

    by_task = s2["cost_ledger"]["by_task"]
    assert len(by_task) == 1, f"Retry should overwrite, not add: {list(by_task.keys())}"

    totals = s2["cost_ledger"]["totals"]
    assert totals["dispatches"] == 2, f"Totals should increment: {totals['dispatches']}"
    assert abs(totals["cost_usd"] - 0.02) < 1e-9, \
        f"Totals cost_usd should accumulate: {totals['cost_usd']}"
    print("  [PASS] test_record_retry_overwrites_by_task_but_increments_totals")


def test_record_plan_chain_state():
    """record() with plan_chain state resolves active plan key from plan_chain."""
    state = {
        "plan_chain": ["plan_a", "plan_b"],
        "active_plan": 1,  # integer index → resolves to "1"
        "cost_ledger": {
            "by_task": {},
            "totals": {
                "input_tokens": 0, "output_tokens": 0,
                "cached_read_tokens": 0, "cached_write_tokens": 0,
                "cache_read_tokens": 0, "cache_creation_tokens": 0,
                "cost_usd": 0.0, "dispatches": 0,
            },
        },
    }
    usage = {"input_tokens": 10, "output_tokens": 5, "total_cost_usd": 0.001}
    new_state = ledger.record(state, "task_x", "verifier", usage)
    keys = list(new_state["cost_ledger"]["by_task"].keys())
    assert len(keys) == 1
    # When plan_chain present, active_plan is the integer index → str(index)
    assert keys[0].startswith("1::"), f"plan_chain: key should start with index str, got {keys[0]!r}"
    print(f"  [PASS] test_record_plan_chain_state (key={keys[0]!r})")


# ── runner ────────────────────────────────────────────────────────────────────

ALL_TESTS = [
    test_extract_payload_result_key,
    test_extract_payload_structured_output_key,
    test_extract_payload_missing_both_raises,
    test_extract_payload_invalid_json_raises,
    test_record_totals_dispatches_and_by_task_key,
    test_record_does_not_mutate_input,
    test_record_retry_overwrites_by_task_but_increments_totals,
    test_record_plan_chain_state,
]


if __name__ == "__main__":
    print(f"test_ledger.py: {len(ALL_TESTS)} defined / {len(ALL_TESTS)} invoked")
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
