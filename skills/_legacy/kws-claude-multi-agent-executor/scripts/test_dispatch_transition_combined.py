"""Tests for dispatch_transition_combined — combined Transition T1.2 dispatch helper.

Covers the parse step that splits a sub-agent's two-tool output into
``{verify, docs}`` and the writer that persists the combined result to
``<orch_dir>/transition_results/<plan_idx>_<compaction_idx>.json``.
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dispatch_transition_combined import (  # noqa: E402
    parse_combined_result,
    transition_result_path,
    write_transition_result,
)

# Fixture: a sub-agent turn that issued BOTH tool calls in one dispatch.
FIXTURE_SUBAGENT_OUTPUT = {
    "tool_calls": [
        {
            "name": "verify_low_batch",
            "result": {
                "status": "PASS",
                "commands_run": ["python3 -m pytest tests/"],
                "exit_codes": [0],
            },
        },
        {
            "name": "update_phase_docs",
            "result": {
                "status": "DONE",
                "files_updated": [{"path": "README.md", "change": "Documented feature."}],
                "commit": "abc1234",
            },
        },
    ]
}


class ParseCombinedResultTests(unittest.TestCase):
    def test_parse_splits_both_tools_into_verify_and_docs(self):
        combined = parse_combined_result(FIXTURE_SUBAGENT_OUTPUT)
        self.assertIn("verify", combined)
        self.assertIn("docs", combined)

    def test_parse_preserves_verify_tool_payload(self):
        combined = parse_combined_result(FIXTURE_SUBAGENT_OUTPUT)
        self.assertEqual(combined["verify"]["status"], "PASS")
        self.assertEqual(combined["verify"]["exit_codes"], [0])

    def test_parse_preserves_docs_tool_payload(self):
        combined = parse_combined_result(FIXTURE_SUBAGENT_OUTPUT)
        self.assertEqual(combined["docs"]["status"], "DONE")
        self.assertEqual(combined["docs"]["commit"], "abc1234")

    def test_parse_raises_when_a_tool_is_missing(self):
        only_verify = {"tool_calls": [FIXTURE_SUBAGENT_OUTPUT["tool_calls"][0]]}
        with self.assertRaises(ValueError):
            parse_combined_result(only_verify)


class TransitionResultPathTests(unittest.TestCase):
    def test_path_includes_plan_and_compaction_index(self):
        path = transition_result_path("/tmp/orch", 2, 5)
        self.assertEqual(
            path,
            os.path.join("/tmp/orch", "transition_results", "2_5.json"),
        )


class WriteTransitionResultTests(unittest.TestCase):
    def test_writer_creates_file_at_expected_path(self):
        combined = parse_combined_result(FIXTURE_SUBAGENT_OUTPUT)
        with tempfile.TemporaryDirectory() as orch_dir:
            path = write_transition_result(orch_dir, 0, 3, combined)
            expected = os.path.join(orch_dir, "transition_results", "0_3.json")
            self.assertEqual(path, expected)
            self.assertTrue(os.path.exists(expected))

    def test_writer_persists_combined_shape(self):
        combined = parse_combined_result(FIXTURE_SUBAGENT_OUTPUT)
        with tempfile.TemporaryDirectory() as orch_dir:
            path = write_transition_result(orch_dir, 1, 2, combined)
            with open(path, encoding="utf-8") as fh:
                loaded = json.load(fh)
            self.assertEqual(loaded["verify"]["status"], "PASS")
            self.assertEqual(loaded["docs"]["status"], "DONE")

    def test_writer_creates_transition_results_dir_when_absent(self):
        combined = parse_combined_result(FIXTURE_SUBAGENT_OUTPUT)
        with tempfile.TemporaryDirectory() as orch_dir:
            self.assertFalse(os.path.isdir(os.path.join(orch_dir, "transition_results")))
            write_transition_result(orch_dir, 0, 0, combined)
            self.assertTrue(os.path.isdir(os.path.join(orch_dir, "transition_results")))


if __name__ == "__main__":
    unittest.main()
