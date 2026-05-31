"""Fixture/mock-driven tests for dispatch_via_api (v2.22 §2.B1).

No live API calls. The `anthropic` SDK is NOT installed in this environment;
these tests must import the module and run with no `anthropic` present. A fake
client is injected via the `client=` kwarg so `import anthropic` is never reached.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dispatch_via_api as dva  # noqa: E402

SK_ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
class FakeToolUse:
    def __init__(self, name, inp):
        self.type = "tool_use"
        self.name = name
        self.input = inp


class FakeUsage:
    def __init__(self, input_tokens=100, output_tokens=20,
                 cache_read_input_tokens=80, cache_creation_input_tokens=0):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cache_read_input_tokens = cache_read_input_tokens
        self.cache_creation_input_tokens = cache_creation_input_tokens


class FakeResponse:
    def __init__(self, tool_name, tool_input, usage=None):
        self.content = [FakeToolUse(tool_name, tool_input)]
        self.usage = usage or FakeUsage()


class FakeAPIError(Exception):
    def __init__(self, status_code, body="boom"):
        super().__init__(body)
        self.status_code = status_code
        self.body = body


class FakeMessages:
    def __init__(self, response=None, raise_seq=None):
        self.response = response or FakeResponse(
            "report_plan_reviewer", {"status": "PASS", "summary": "ok", "issues": []})
        self.raise_seq = list(raise_seq or [])
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.raise_seq:
            exc = self.raise_seq.pop(0)
            if exc is not None:
                raise exc
        return self.response


class FakeClient:
    def __init__(self, messages=None):
        self.messages = messages or FakeMessages()


def _tmp_orch():
    d = tempfile.mkdtemp(prefix="orch_")
    state = {"schema_version": "2", "active_plan": "plan1", "cost_ledger": {
        "by_task": {}, "by_role": {}, "by_model": {},
        "totals": {"input_tokens": 0, "output_tokens": 0,
                   "cached_read_tokens": 0, "cached_write_tokens": 0,
                   "cost_usd": 0.0, "dispatches": 0}}}
    (Path(d) / "state.json").write_text(json.dumps(state), encoding="utf-8")
    return d


def _task_ctx():
    return {"plan_path": "/p/plan.md", "plan_full_text": "PLAN",
            "spec_path": "/p/spec.md", "spec_full_text": "SPEC",
            "risk_levels_yaml": "task_1: low", "spec_manifest_json": "{}",
            "result_json_path": "/tmp/out.json"}


# --------------------------------------------------------------------------- #
# load_prompt / scaffold-payload split
# --------------------------------------------------------------------------- #
class LoadPromptTests(unittest.TestCase):
    def test_split_scaffold_has_no_brace_payload_has_placeholder(self):
        scaffold, payload = dva.load_prompt("plan_reviewer", SK_ROOT)
        self.assertNotIn("{", scaffold)
        self.assertIn("{plan_full_text}", payload)

    def test_reassembly_static_prefix_present(self):
        scaffold, payload = dva.load_prompt("plan_reviewer", SK_ROOT)
        self.assertIn("Plan Reviewer sub-agent", scaffold)
        self.assertIn("## Plan", payload)

    def test_missing_markers_raise(self):
        with tempfile.TemporaryDirectory() as d:
            refs = Path(d) / "references"
            refs.mkdir()
            (refs / "bad-prompt.md").write_text("no markers here", encoding="utf-8")
            with self.assertRaises(Exception):
                dva.load_prompt("bad", Path(d))


# --------------------------------------------------------------------------- #
# build_request: cache_control + tool_choice
# --------------------------------------------------------------------------- #
class BuildRequestTests(unittest.TestCase):
    def setUp(self):
        self.scaffold, self.payload = dva.load_prompt("plan_reviewer", SK_ROOT)
        self.schema = dva.load_schema("plan_reviewer", SK_ROOT)

    def _req(self):
        return dva.build_request(
            self.scaffold, self.payload, self.schema,
            "plan_reviewer", "claude-haiku-4-5-20251001", _task_ctx())

    def test_cache_control_on_scaffold_block(self):
        req = self._req()
        sys_blocks = req["system"]
        self.assertTrue(any(
            isinstance(b, dict) and b.get("cache_control") == {"type": "ephemeral"}
            for b in sys_blocks))

    def test_tool_choice_forces_named_tool(self):
        req = self._req()
        self.assertEqual(req["tool_choice"],
                         {"type": "tool", "name": "report_plan_reviewer"})
        self.assertEqual(req["tools"][0]["name"], "report_plan_reviewer")
        self.assertIn("input_schema", req["tools"][0])

    def test_payload_substituted_into_user_content(self):
        req = self._req()
        blob = json.dumps(req["messages"])
        self.assertIn("PLAN", blob)
        self.assertNotIn("{plan_full_text}", blob)


# --------------------------------------------------------------------------- #
# dispatch: success path, cost, agentlens
# --------------------------------------------------------------------------- #
class DispatchSuccessTests(unittest.TestCase):
    def test_writes_output_and_returns_result(self):
        orch = _tmp_orch()
        out = Path(orch) / "result.json"
        client = FakeClient()
        res = dva.dispatch("plan_reviewer", _task_ctx(),
                           "claude-haiku-4-5-20251001", orch, SK_ROOT, str(out),
                           client=client, max_retries=3)
        self.assertEqual(res["status"], "PASS")
        self.assertTrue(out.is_file())
        self.assertEqual(json.loads(out.read_text())["status"], "PASS")

    def test_cost_ledger_dispatch_increments(self):
        orch = _tmp_orch()
        out = Path(orch) / "result.json"
        dva.dispatch("plan_reviewer", _task_ctx(),
                     "claude-haiku-4-5-20251001", orch, SK_ROOT, str(out),
                     client=FakeClient())
        state = json.loads((Path(orch) / "state.json").read_text())
        self.assertEqual(state["cost_ledger"]["totals"]["dispatches"], 1)

    def test_agentlens_emit_called_with_role_and_cache_hit_ratio(self):
        orch = _tmp_orch()
        out = Path(orch) / "result.json"
        captured = {}

        def fake_emit(fields):
            captured.update(fields)
        orig = dva._emit_agentlens
        dva._emit_agentlens = fake_emit
        try:
            dva.dispatch("plan_reviewer", _task_ctx(),
                         "claude-haiku-4-5-20251001", orch, SK_ROOT, str(out),
                         client=FakeClient())
        finally:
            dva._emit_agentlens = orig
        self.assertEqual(captured.get("role"), "plan_reviewer")
        self.assertIn("cache_hit_ratio", captured)


# --------------------------------------------------------------------------- #
# retry / ENV_BLOCKER
# --------------------------------------------------------------------------- #
class RetryTests(unittest.TestCase):
    def setUp(self):
        # neutralize backoff sleep
        self._orig_sleep = dva.time.sleep
        dva.time.sleep = lambda *_a, **_k: None

    def tearDown(self):
        dva.time.sleep = self._orig_sleep

    def test_is_retryable_status_codes(self):
        for code in (429, 500, 502, 503, 529):
            self.assertTrue(dva._is_retryable(FakeAPIError(code)))
        self.assertFalse(dva._is_retryable(FakeAPIError(400)))

    def test_retries_then_succeeds(self):
        orch = _tmp_orch()
        out = Path(orch) / "result.json"
        msgs = FakeMessages(raise_seq=[FakeAPIError(429), FakeAPIError(503), None])
        client = FakeClient(messages=msgs)
        res = dva.dispatch("plan_reviewer", _task_ctx(),
                           "claude-haiku-4-5-20251001", orch, SK_ROOT, str(out),
                           client=client, max_retries=3)
        self.assertEqual(res["status"], "PASS")
        self.assertEqual(len(msgs.calls), 3)

    def test_persistent_retryable_yields_env_blocker(self):
        orch = _tmp_orch()
        out = Path(orch) / "result.json"
        msgs = FakeMessages(raise_seq=[FakeAPIError(429)] * 6)
        client = FakeClient(messages=msgs)
        res = dva.dispatch("plan_reviewer", _task_ctx(),
                           "claude-haiku-4-5-20251001", orch, SK_ROOT, str(out),
                           client=client, max_retries=3)
        self.assertEqual(res["status"], "ESCALATE")
        self.assertEqual(res["type"], "ENV_BLOCKER")

    def test_non_retryable_immediate_env_blocker(self):
        orch = _tmp_orch()
        out = Path(orch) / "result.json"
        msgs = FakeMessages(raise_seq=[FakeAPIError(400)])
        client = FakeClient(messages=msgs)
        res = dva.dispatch("plan_reviewer", _task_ctx(),
                           "claude-haiku-4-5-20251001", orch, SK_ROOT, str(out),
                           client=client, max_retries=3)
        self.assertEqual(res["status"], "ESCALATE")
        self.assertEqual(res["type"], "ENV_BLOCKER")
        # only one attempt for non-retryable
        self.assertEqual(len(msgs.calls), 1)


# --------------------------------------------------------------------------- #
# Verifier batch (T1) — role token "verifier" (singular), tool report_verifier
# --------------------------------------------------------------------------- #
def _verifier_ctx():
    return {
        "test_command": "python3 -m unittest",
        "acceptance_criteria": "none provided",
        "result_json_path": "/tmp/verifier_out.json",
    }


class VerifierBatchTests(unittest.TestCase):
    def test_verifier_batch_scaffold_payload_split_loads(self):
        scaffold, payload = dva.load_prompt("verifier", SK_ROOT)
        self.assertNotIn("{", scaffold)
        self.assertIn("Verifier sub-agent", scaffold)
        self.assertIn("{test_command}", payload)
        self.assertIn("## Risk Level", payload)

    def test_verifier_batch_cache_control_on_scaffold_block(self):
        scaffold, payload = dva.load_prompt("verifier", SK_ROOT)
        schema = dva.load_schema("verifier", SK_ROOT)
        req = dva.build_request(
            scaffold, payload, schema, "verifier", "claude-sonnet-4-5-20250929",
            _verifier_ctx())
        self.assertTrue(any(
            isinstance(b, dict) and b.get("cache_control") == {"type": "ephemeral"}
            for b in req["system"]))

    def test_verifier_batch_tool_choice_forces_report_verifier(self):
        scaffold, payload = dva.load_prompt("verifier", SK_ROOT)
        schema = dva.load_schema("verifier", SK_ROOT)
        req = dva.build_request(
            scaffold, payload, schema, "verifier", "claude-sonnet-4-5-20250929",
            _verifier_ctx())
        self.assertEqual(req["tool_choice"],
                         {"type": "tool", "name": "report_verifier"})
        self.assertEqual(req["tools"][0]["name"], "report_verifier")
        self.assertIn("input_schema", req["tools"][0])

    def test_verifier_batch_dispatch_writes_tool_input_to_output(self):
        orch = _tmp_orch()
        out = Path(orch) / "verifier_result.json"
        msgs = FakeMessages(response=FakeResponse(
            "report_verifier",
            {"status": "PASS", "commands_run": ["python3 -m unittest"],
             "exit_codes": [0]}))
        client = FakeClient(messages=msgs)
        res = dva.dispatch("verifier", _verifier_ctx(),
                           "claude-sonnet-4-5-20250929", orch, SK_ROOT, str(out),
                           client=client, max_retries=3)
        self.assertEqual(res["status"], "PASS")
        self.assertTrue(out.is_file())
        written = json.loads(out.read_text())
        self.assertEqual(written["status"], "PASS")
        self.assertEqual(written["commands_run"], ["python3 -m unittest"])


class CliTests(unittest.TestCase):
    def test_parser_exposes_role(self):
        parser = dva.build_arg_parser()
        ns = parser.parse_args([
            "--role", "plan_reviewer", "--task-context", "/t.json",
            "--output", "/o.json", "--model", "claude-haiku-4-5-20251001",
            "--orch-dir", "/orch"])
        self.assertEqual(ns.role, "plan_reviewer")


if __name__ == "__main__":
    unittest.main()
