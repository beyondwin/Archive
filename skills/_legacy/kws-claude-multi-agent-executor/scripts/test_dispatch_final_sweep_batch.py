#!/usr/bin/env python3
"""Stdlib-unittest coverage for ``dispatch_final_sweep_batch`` (v2.22 §2.C1).

Three deterministic paths, all driven by a fake ``client`` (no SDK), a fake
``sleep`` (no real waiting) and a fake ``clock`` (no real time dependence):

  * submit          — one batch request per LOW task (custom_ids + count).
  * poll-success    — retrieve flips to ``ended`` after N polls → batch PASS.
  * poll-timeout    — retrieve never ends → TIMEOUT → per-task API fallback,
                      ``kws-cme.batch_timeout`` emitted, ``mode=api_fallback``.

Run: ``python3 scripts/test_dispatch_final_sweep_batch.py``.
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dispatch_final_sweep_batch as dfsb  # noqa: E402


# --------------------------------------------------------------------------
# Fake Anthropic Message Batches client (no SDK import).
# --------------------------------------------------------------------------
class _FakeResult:
    """One ``client.messages.batches.results`` row (succeeded outcome)."""

    def __init__(self, custom_id, tool_input):
        self.custom_id = custom_id
        block = type("B", (), {"type": "tool_use", "name": "report_verifier",
                               "input": tool_input})()
        message = type("M", (), {"content": [block]})()
        self.result = type("R", (), {"type": "succeeded", "message": message})()


class _FakeBatch:
    def __init__(self, batch_id, statuses, result_rows):
        self.id = batch_id
        self._statuses = list(statuses)
        self._result_rows = result_rows
        self.processing_status = self._statuses[0] if self._statuses else "ended"


class _FakeBatches:
    def __init__(self, statuses, result_rows):
        self._statuses = list(statuses)
        self._result_rows = result_rows
        self.create_calls = []
        self.retrieve_count = 0
        self._batch = None

    def create(self, requests):
        self.create_calls.append(list(requests))
        self._batch = _FakeBatch("batch_abc", self._statuses, self._result_rows)
        return self._batch

    def retrieve(self, batch_id):
        # Advance the status tape one step per retrieve.
        idx = min(self.retrieve_count, len(self._statuses) - 1)
        self._batch.processing_status = self._statuses[idx]
        self.retrieve_count += 1
        return self._batch

    def results(self, batch_id):
        return list(self._result_rows)


class _FakeMessages:
    def __init__(self, batches):
        self.batches = batches


class _FakeClient:
    def __init__(self, statuses, result_rows):
        self.messages = _FakeMessages(_FakeBatches(statuses, result_rows))


def _low_tasks():
    return [
        {"task_id": "T07", "task_summary": "low task 7"},
        {"task_id": "T09", "task_summary": "low task 9"},
    ]


class _NoSleep:
    def __init__(self):
        self.calls = []

    def __call__(self, seconds):
        self.calls.append(seconds)


class _Clock:
    """Monotonic-ish fake: each call advances by ``step`` seconds."""

    def __init__(self, step=0.0, start=0.0):
        self.t = start
        self.step = step

    def __call__(self):
        v = self.t
        self.t += self.step
        return v


class SubmitTest(unittest.TestCase):
    def test_one_request_per_low_task(self):
        rows = [
            _FakeResult("T07", {"status": "PASS"}),
            _FakeResult("T09", {"status": "PASS"}),
        ]
        client = _FakeClient(statuses=["ended"], result_rows=rows)
        dfsb.dispatch_final_sweep_batch(
            _low_tasks(), model="claude-x", orch_dir="/tmp/orch",
            sk_root="/tmp/sk", client=client,
            sleep=_NoSleep(), clock=_Clock(step=0.0),
        )
        calls = client.messages.batches.create_calls
        self.assertEqual(len(calls), 1, "batches.create called exactly once")
        requests = calls[0]
        self.assertEqual(len(requests), 2, "one request per LOW task")
        self.assertEqual(
            [r["custom_id"] for r in requests], ["T07", "T09"])
        for r in requests:
            self.assertIn("params", r)
            self.assertIn("model", r["params"])


class PollSuccessTest(unittest.TestCase):
    def test_poll_until_ended_returns_batch_pass(self):
        rows = [
            _FakeResult("T07", {"status": "PASS"}),
            _FakeResult("T09", {"status": "PASS"}),
        ]
        # in_progress for two polls, then ended.
        client = _FakeClient(
            statuses=["in_progress", "in_progress", "ended"], result_rows=rows)
        sleep = _NoSleep()
        summary = dfsb.dispatch_final_sweep_batch(
            _low_tasks(), model="claude-x", orch_dir="/tmp/orch",
            sk_root="/tmp/sk", client=client,
            timeout_seconds=1800, poll_interval=30,
            sleep=sleep, clock=_Clock(step=0.0),
        )
        self.assertEqual(summary["mode"], "batch")
        self.assertEqual(summary["status"], "PASS")
        self.assertEqual(summary["batch_id"], "batch_abc")
        self.assertEqual(len(summary["results"]), 2)
        # Slept between polls at least once (did not return on first retrieve).
        self.assertTrue(sleep.calls, "sleep was called between polls")
        self.assertTrue(all(s == 30 for s in sleep.calls))


class PollTimeoutFallbackTest(unittest.TestCase):
    def test_timeout_falls_back_to_per_task_api(self):
        # Never ends; timeout_seconds=0 makes the deadline fire immediately.
        client = _FakeClient(
            statuses=["in_progress"], result_rows=[])

        emitted = []

        def fake_emit(fields):
            emitted.append(fields)

        fallback_calls = []

        class _FakeDispatchViaApi:
            def dispatch(self, **kwargs):
                fallback_calls.append(kwargs)
                return {"status": "PASS", "role": kwargs.get("role")}

        # Inject the fallback module + capture the emit shim.
        orig_emit = dfsb._emit_agentlens
        orig_loader = dfsb._load_dispatch_via_api
        dfsb._emit_agentlens = fake_emit
        dfsb._load_dispatch_via_api = lambda: _FakeDispatchViaApi()
        try:
            summary = dfsb.dispatch_final_sweep_batch(
                _low_tasks(), model="claude-x", orch_dir="/tmp/orch",
                sk_root="/tmp/sk", client=client,
                timeout_seconds=0, poll_interval=30,
                sleep=_NoSleep(), clock=_Clock(step=0.0),
            )
        finally:
            dfsb._emit_agentlens = orig_emit
            dfsb._load_dispatch_via_api = orig_loader

        self.assertEqual(summary["mode"], "api_fallback")
        self.assertEqual(summary["fallback_reason"], "batch_timeout")
        self.assertEqual(len(fallback_calls), 2, "per-task fallback for each LOW task")
        for call in fallback_calls:
            self.assertEqual(call["role"], "verifier")
        # batch_timeout event emitted.
        self.assertTrue(
            any(e.get("event") == "kws-cme.batch_timeout" for e in emitted),
            "kws-cme.batch_timeout emitted on timeout")


if __name__ == "__main__":
    unittest.main()
