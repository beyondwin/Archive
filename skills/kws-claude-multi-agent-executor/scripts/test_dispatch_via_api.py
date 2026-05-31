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


class FakeMultiToolResponse:
    """A response carrying several tool_use blocks (combined transition)."""

    def __init__(self, tool_calls, usage=None):
        # tool_calls: iterable of (name, input) tuples.
        self.content = [FakeToolUse(name, inp) for name, inp in tool_calls]
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

    def test_agentlens_emit_called_on_failed_after_retry_env_blocker(self):
        # The failed-after-retry (ENV_BLOCKER) path must ALSO emit the
        # kws-cme.dispatch_via_api event so observability stays uniform with the
        # success path. Inject a client that always raises a retryable error so
        # retries are exhausted and the ENV_BLOCKER branch is taken.
        orch = _tmp_orch()
        out = Path(orch) / "result.json"
        captured = {}

        def fake_emit(fields):
            captured.update(fields)
        orig = dva._emit_agentlens
        dva._emit_agentlens = fake_emit
        try:
            msgs = FakeMessages(raise_seq=[FakeAPIError(429)] * 6)
            client = FakeClient(messages=msgs)
            res = dva.dispatch("plan_reviewer", _task_ctx(),
                               "claude-haiku-4-5-20251001", orch, SK_ROOT,
                               str(out), client=client, max_retries=3)
        finally:
            dva._emit_agentlens = orig
        self.assertEqual(res["status"], "ESCALATE")
        self.assertEqual(res["type"], "ENV_BLOCKER")
        self.assertEqual(captured["event"], "kws-cme.dispatch_via_api")
        self.assertEqual(captured["role"], "plan_reviewer")
        self.assertEqual(captured["retries"], res["retries"])

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


# --------------------------------------------------------------------------- #
# Verifier per-task (T8) — MID/HIGH gate `verifier_per_task == "api"`.
# Reuses the SAME `verifier` role/scaffold/tool as the batch path (T6); the
# distinction is the dispatch_config gate, not the role token. These methods are
# named *verifier_per_task* so `-k verifier_per_task` selects exactly them.
# --------------------------------------------------------------------------- #
def _verifier_per_task_ctx():
    # A per-task (MID/HIGH) verifier context — single task, not a LOW batch.
    return {
        "test_command": "python3 -m unittest",
        "acceptance_criteria": "python3 scripts/test_foo.py passes",
        "result_json_path": "/tmp/verifier_task_7.json",
    }


class VerifierPerTaskTests(unittest.TestCase):
    def test_verifier_per_task_loads_shared_verifier_scaffold(self):
        scaffold, payload = dva.load_prompt("verifier", SK_ROOT)
        self.assertNotIn("{", scaffold)
        self.assertIn("Verifier sub-agent", scaffold)
        self.assertIn("{test_command}", payload)
        self.assertIn("acceptance_criteria", payload)
        self.assertIn("## Acceptance Criteria", payload)

    def test_verifier_per_task_build_request_forces_report_verifier_and_caches(self):
        scaffold, payload = dva.load_prompt("verifier", SK_ROOT)
        schema = dva.load_schema("verifier", SK_ROOT)
        req = dva.build_request(
            scaffold, payload, schema, "verifier", "claude-sonnet-4-5-20250929",
            _verifier_per_task_ctx())
        # tool_choice forced to the shared report_verifier tool
        self.assertEqual(req["tool_choice"],
                         {"type": "tool", "name": "report_verifier"})
        self.assertEqual(req["tools"][0]["name"], "report_verifier")
        self.assertIn("input_schema", req["tools"][0])
        # cache_control ephemeral on the scaffold block
        self.assertTrue(any(
            isinstance(b, dict) and b.get("cache_control") == {"type": "ephemeral"}
            for b in req["system"]))

    def test_verifier_per_task_dispatch_writes_result_to_output_path(self):
        orch = _tmp_orch()
        out = Path(orch) / "verifier_results" / "task_7.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        msgs = FakeMessages(response=FakeResponse(
            "report_verifier",
            {"status": "PASS", "commands_run": ["python3 -m unittest"],
             "exit_codes": [0]}))
        client = FakeClient(messages=msgs)
        res = dva.dispatch("verifier", _verifier_per_task_ctx(),
                           "claude-sonnet-4-5-20250929", orch, SK_ROOT, str(out),
                           client=client, max_retries=3)
        self.assertEqual(res["status"], "PASS")
        self.assertTrue(out.is_file())
        written = json.loads(out.read_text())
        self.assertEqual(written["status"], "PASS")
        self.assertEqual(written["commands_run"], ["python3 -m unittest"])


# --------------------------------------------------------------------------- #
# Combined Transition (T1.2) — role "transition_combined", TWO tools per turn
# --------------------------------------------------------------------------- #
def _transition_ctx():
    return {
        "test_command": "python3 -m unittest",
        "result_json_path": "/tmp/transition_out.json",
    }


def _transition_response():
    return FakeMultiToolResponse([
        ("verify_low_batch",
         {"status": "PASS", "commands_run": ["python3 -m unittest"],
          "exit_codes": [0]}),
        ("update_phase_docs",
         {"status": "DONE", "summary": "docs updated",
          "files_updated": [{"path": "README.md", "change": "noted phase"}],
          "commit": "abc123"}),
    ])


class TransitionCombinedTests(unittest.TestCase):
    def test_transition_combined_scaffold_payload_split_loads(self):
        scaffold, payload = dva.load_prompt("transition_combined", SK_ROOT)
        self.assertNotIn("{", scaffold)
        self.assertIn("Combined Transition sub-agent", scaffold)
        self.assertIn("{test_command}", payload)

    def test_transition_combined_build_request_emits_two_tools_and_any_choice(self):
        scaffold, payload = dva.load_prompt("transition_combined", SK_ROOT)
        schema = dva.load_schema("transition_combined", SK_ROOT)
        req = dva.build_request(
            scaffold, payload, schema, "transition_combined",
            "claude-sonnet-4-5-20250929", _transition_ctx())
        self.assertEqual(len(req["tools"]), 2)
        names = {t["name"] for t in req["tools"]}
        self.assertEqual(names, {"verify_low_batch", "update_phase_docs"})
        self.assertEqual(req["tool_choice"], {"type": "any"})

    def test_transition_combined_cache_control_on_scaffold_block(self):
        scaffold, payload = dva.load_prompt("transition_combined", SK_ROOT)
        schema = dva.load_schema("transition_combined", SK_ROOT)
        req = dva.build_request(
            scaffold, payload, schema, "transition_combined",
            "claude-sonnet-4-5-20250929", _transition_ctx())
        self.assertTrue(any(
            isinstance(b, dict) and b.get("cache_control") == {"type": "ephemeral"}
            for b in req["system"]))

    def test_transition_combined_extract_combined_returns_verify_and_docs(self):
        combined = dva._extract_combined(_transition_response())
        self.assertEqual(combined["verify"]["status"], "PASS")
        self.assertEqual(combined["docs"]["status"], "DONE")
        self.assertEqual(combined["docs"]["commit"], "abc123")

    def test_transition_combined_extract_combined_missing_tool_raises(self):
        only_verify = FakeMultiToolResponse([
            ("verify_low_batch", {"status": "PASS"})])
        with self.assertRaises(ValueError):
            dva._extract_combined(only_verify)

    def test_transition_combined_dispatch_writes_combined_result(self):
        orch = _tmp_orch()
        out = Path(orch) / "transition_result.json"
        msgs = FakeMessages(response=_transition_response())
        client = FakeClient(messages=msgs)
        res = dva.dispatch("transition_combined", _transition_ctx(),
                           "claude-sonnet-4-5-20250929", orch, SK_ROOT, str(out),
                           client=client, max_retries=3)
        self.assertIn("verify", res)
        self.assertIn("docs", res)
        self.assertEqual(res["verify"]["status"], "PASS")
        self.assertEqual(res["docs"]["status"], "DONE")
        self.assertTrue(out.is_file())
        written = json.loads(out.read_text())
        self.assertEqual(written["verify"]["status"], "PASS")
        self.assertEqual(written["docs"]["commit"], "abc123")


# --------------------------------------------------------------------------- #
# Docs Updater (T9) — role token "docs_updater" (singular). The Phase and Final
# call sites BOTH reuse this single role; the distinction is the dispatch_config
# gate (docs_updater_phase / docs_updater_final), not the role token. The prompt
# file is `docs-updater-prompts.md` (plural), resolved via PROMPT_FILE_OVERRIDE.
# Methods are named *docs_updater* so `-k docs_updater` selects exactly them.
# --------------------------------------------------------------------------- #
def _docs_updater_ctx():
    return {
        "files_changed": "src/foo.py, src/bar.py",
        "docs_scope": "README.md, CHANGELOG.md",
        "result_json_path": "/tmp/docs_updater_out.json",
    }


class DocsUpdaterTests(unittest.TestCase):
    def test_docs_updater_loads_prompt_via_override_split_succeeds(self):
        scaffold, payload = dva.load_prompt("docs_updater", SK_ROOT)
        self.assertNotIn("{", scaffold)
        self.assertIn("Phase Docs Updater sub-agent", scaffold)
        self.assertIn("## Required Skills", scaffold)
        self.assertIn("## Files Changed in This Phase", payload)

    def test_docs_updater_build_request_forces_report_docs_updater_and_caches(self):
        scaffold, payload = dva.load_prompt("docs_updater", SK_ROOT)
        schema = dva.load_schema("docs_updater", SK_ROOT)
        req = dva.build_request(
            scaffold, payload, schema, "docs_updater",
            "claude-sonnet-4-5-20250929", _docs_updater_ctx())
        # Single tool forced — NOT routed through the transition two-tool branch.
        self.assertEqual(req["tool_choice"],
                         {"type": "tool", "name": "report_docs_updater"})
        self.assertEqual(len(req["tools"]), 1)
        self.assertEqual(req["tools"][0]["name"], "report_docs_updater")
        self.assertIn("input_schema", req["tools"][0])
        # cache_control ephemeral on the scaffold block
        self.assertTrue(any(
            isinstance(b, dict) and b.get("cache_control") == {"type": "ephemeral"}
            for b in req["system"]))

    def test_docs_updater_dispatch_writes_tool_result_to_output(self):
        orch = _tmp_orch()
        out = Path(orch) / "docs_results" / "phase_1.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        msgs = FakeMessages(response=FakeResponse(
            "report_docs_updater",
            {"status": "DONE", "summary": "docs updated",
             "files_updated": [{"path": "README.md", "change": "noted phase"}],
             "commit": "abc123"}))
        client = FakeClient(messages=msgs)
        res = dva.dispatch("docs_updater", _docs_updater_ctx(),
                           "claude-sonnet-4-5-20250929", orch, SK_ROOT, str(out),
                           client=client, max_retries=3)
        self.assertEqual(res["status"], "DONE")
        self.assertTrue(out.is_file())
        written = json.loads(out.read_text())
        self.assertEqual(written["status"], "DONE")
        self.assertEqual(written["commit"], "abc123")


class CliTests(unittest.TestCase):
    def test_parser_exposes_role(self):
        parser = dva.build_arg_parser()
        ns = parser.parse_args([
            "--role", "plan_reviewer", "--task-context", "/t.json",
            "--output", "/o.json", "--model", "claude-haiku-4-5-20251001",
            "--orch-dir", "/orch"])
        self.assertEqual(ns.role, "plan_reviewer")

    def test_parser_accepts_docs_updater_role(self):
        parser = dva.build_arg_parser()
        ns = parser.parse_args([
            "--role", "docs_updater", "--task-context", "/t.json",
            "--output", "/o.json", "--model", "claude-sonnet-4-5-20250929",
            "--orch-dir", "/orch"])
        self.assertEqual(ns.role, "docs_updater")


if __name__ == "__main__":
    unittest.main()
