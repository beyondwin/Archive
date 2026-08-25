#!/usr/bin/env python3
"""Unit evals for clpe.py pure functions."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import clpe


class SchemaFileTest(unittest.TestCase):
    def test_schema_is_valid_json_with_status_enum(self):
        schema = json.loads(clpe.SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            schema["properties"]["status"]["enum"],
            ["completed", "blocked", "failed"],
        )
        self.assertEqual(
            sorted(schema["required"]),
            ["head_commit", "open_findings", "status", "summary"],
        )


class ResultShapeTest(unittest.TestCase):
    def completed(self):
        return {
            "status": "completed",
            "head_commit": "a" * 40,
            "summary": "done",
            "open_findings": [],
        }

    def test_completed_shape_passes(self):
        self.assertEqual(clpe.validate_result_shape(self.completed()), [])

    def test_non_dict_rejected(self):
        self.assertTrue(clpe.validate_result_shape(["x"]))
        self.assertTrue(clpe.validate_result_shape(None))

    def test_missing_fields_reported(self):
        errors = clpe.validate_result_shape({"status": "completed"})
        self.assertTrue(any("head_commit" in e for e in errors))
        self.assertTrue(any("summary" in e for e in errors))
        self.assertTrue(any("open_findings" in e for e in errors))

    def test_bad_status_and_sha_rejected(self):
        record = self.completed()
        record["status"] = "done"
        record["head_commit"] = "not-a-sha"
        errors = clpe.validate_result_shape(record)
        self.assertTrue(any("status" in e for e in errors))
        self.assertTrue(any("head_commit" in e for e in errors))

    def test_blocked_requires_blocker(self):
        record = self.completed()
        record["status"] = "blocked"
        errors = clpe.validate_result_shape(record)
        self.assertTrue(any("blocker" in e for e in errors))
        record["blocker"] = {"kind": "env", "detail": "docker missing"}
        self.assertEqual(clpe.validate_result_shape(record), [])


class ParseStreamTest(unittest.TestCase):
    def write_stream(self, lines):
        handle = tempfile.NamedTemporaryFile(
            "w", suffix=".jsonl", delete=False, encoding="utf-8"
        )
        handle.write("\n".join(lines) + "\n")
        handle.close()
        self.addCleanup(Path(handle.name).unlink)
        return Path(handle.name)

    def test_extracts_session_result_and_categories(self):
        """Structural: drives the NEW inferred shape (rate_limit_event, not
        system/error). Verifies parse_stream harvests a non-"allowed"
        rate_limit_event as a 'rate_limit' category; does NOT assert the
        status string is a verified real-CLI block value."""
        path = self.write_stream([
            json.dumps({"type": "system", "subtype": "init", "session_id": "s1"}),
            "not json at all",
            json.dumps({"type": "rate_limit_event", "session_id": "s1",
                        "rate_limit_info": {"status": "rejected"}}),
            json.dumps({"type": "result", "subtype": "success",
                        "session_id": "s1", "total_cost_usd": 0.01}),
        ])
        session_id, result_event, categories = clpe.parse_stream(path)
        self.assertEqual(session_id, "s1")
        self.assertEqual(result_event["subtype"], "success")
        self.assertEqual(categories, ["rate_limit"])

    def test_api_error_status_harvested_as_category(self):
        """Structural: a non-null result.api_error_status (INFERRED shape) yields
        an 'api_error' category. Does NOT assert this is a verified real value."""
        path = self.write_stream([
            json.dumps({"type": "result", "subtype": "error_during_execution",
                        "session_id": "s1", "api_error_status": "Overloaded"}),
        ])
        _, _, categories = clpe.parse_stream(path)
        self.assertIn("api_error", categories)

    def test_allowed_rate_limit_event_not_harvested(self):
        """A healthy rate_limit_event (status 'allowed') must NOT be harvested,
        even though overageStatus is 'rejected' — we key on status, not overage."""
        path = self.write_stream([
            json.dumps({"type": "rate_limit_event", "session_id": "s1",
                        "rate_limit_info": {"status": "allowed",
                                            "overageStatus": "rejected"}}),
            json.dumps({"type": "result", "subtype": "success", "session_id": "s1"}),
        ])
        _, _, categories = clpe.parse_stream(path)
        self.assertEqual(categories, [])

    def test_missing_file_and_garbage_yield_nothing(self):
        session_id, result_event, categories = clpe.parse_stream(
            Path("/nonexistent/stream.jsonl")
        )
        self.assertIsNone(session_id)
        self.assertIsNone(result_event)
        self.assertEqual(categories, [])
        path = self.write_stream(["garbage", "[1,2]"])
        session_id, result_event, categories = clpe.parse_stream(path)
        self.assertIsNone(session_id)
        self.assertIsNone(result_event)


class ClassifyTest(unittest.TestCase):
    def observe(self, **overrides):
        base = dict(
            launch_kind="exited",
            result_event={"type": "result", "subtype": "success",
                          "structured_output": {"status": "completed"}},
            session_id="s1",
            error_categories=[],
            gate_failures=[],
            shape_errors=[],
        )
        base.update(overrides)
        return clpe.Observation(**base)

    def test_spawn_failed(self):
        verdict = clpe.classify(self.observe(launch_kind="spawn_failed",
                                             result_event=None, session_id=None))
        self.assertEqual((verdict.status, verdict.exit_code),
                         ("failed", clpe.EXIT_FAILED))

    def test_timed_out_with_session_is_resumable(self):
        verdict = clpe.classify(self.observe(launch_kind="timed_out",
                                             result_event=None))
        self.assertEqual((verdict.status, verdict.exit_code, verdict.resumable),
                         ("resumable", clpe.EXIT_RESUMABLE, True))

    def test_timed_out_without_session_fails(self):
        verdict = clpe.classify(self.observe(launch_kind="timed_out",
                                             result_event=None, session_id=None))
        self.assertEqual((verdict.status, verdict.exit_code),
                         ("failed", clpe.EXIT_FAILED))

    def test_no_result_event_is_invalid(self):
        verdict = clpe.classify(self.observe(result_event=None))
        self.assertEqual(verdict.status, "failed")
        self.assertIn("result_invalid", verdict.detail)

    def test_provider_category_beats_missing_result(self):
        verdict = clpe.classify(self.observe(result_event=None,
                                             error_categories=["rate_limit"]))
        self.assertEqual((verdict.status, verdict.exit_code),
                         ("blocked", clpe.EXIT_BLOCKED))
        self.assertEqual(verdict.detail, "provider_usage_blocked")

    def test_auth_category_on_error_subtype(self):
        event = {"type": "result", "subtype": "error_during_execution"}
        verdict = clpe.classify(self.observe(result_event=event,
                                             error_categories=["authentication_failed"]))
        self.assertEqual(verdict.detail, "provider_auth_blocked")
        self.assertEqual(verdict.exit_code, clpe.EXIT_BLOCKED)

    def test_max_turns_and_budget_are_resumable(self):
        for subtype in ("error_max_turns", "error_max_budget_usd"):
            event = {"type": "result", "subtype": subtype}
            verdict = clpe.classify(self.observe(result_event=event))
            self.assertEqual((verdict.status, verdict.exit_code),
                             ("resumable", clpe.EXIT_RESUMABLE), subtype)

    def test_success_without_structured_output_fails(self):
        event = {"type": "result", "subtype": "success"}
        verdict = clpe.classify(self.observe(result_event=event))
        self.assertEqual(verdict.status, "failed")
        self.assertIn("without structured_output", verdict.detail)

    def test_shape_errors_fail(self):
        verdict = clpe.classify(self.observe(shape_errors=["missing field: summary"]))
        self.assertEqual(verdict.status, "failed")

    def test_child_reported_failed(self):
        event = {"type": "result", "subtype": "success",
                 "structured_output": {"status": "failed"}}
        verdict = clpe.classify(self.observe(result_event=event))
        self.assertEqual((verdict.status, verdict.exit_code),
                         ("failed", clpe.EXIT_FAILED))

    def test_child_blocked_carries_blocker_kind(self):
        event = {"type": "result", "subtype": "success",
                 "structured_output": {"status": "blocked",
                                       "blocker": {"kind": "env_missing_tool",
                                                   "detail": "x"}}}
        verdict = clpe.classify(self.observe(result_event=event))
        self.assertEqual((verdict.status, verdict.exit_code, verdict.detail),
                         ("blocked", clpe.EXIT_BLOCKED, "env_missing_tool"))

    def test_gate_failures_block_completion(self):
        verdict = clpe.classify(self.observe(gate_failures=["worktree not clean"]))
        self.assertEqual(verdict.status, "failed")
        self.assertIn("completion_gate_failed", verdict.detail)

    def test_clean_completion(self):
        verdict = clpe.classify(self.observe())
        self.assertEqual((verdict.status, verdict.exit_code),
                         ("completed", clpe.EXIT_COMPLETED))


class ScrubEnvTest(unittest.TestCase):
    def test_scrubs_nesting_and_secrets_keeps_anthropic_and_path(self):
        env = {
            "CLAUDECODE": "1",
            "CLAUDE_CODE_CHILD_SESSION": "1",
            "CLAUDE_CODE_ENTRYPOINT": "cli",
            "GITHUB_API_KEY": "x",
            "MY_TOKEN": "x",
            "DB_SECRET": "x",
            "ANTHROPIC_API_KEY": "keep-me",
            "PATH": "/usr/bin",
            "HOME": "/home/u",
        }
        clean = clpe.scrub_env(env)
        for gone in ("CLAUDECODE", "CLAUDE_CODE_CHILD_SESSION",
                     "CLAUDE_CODE_ENTRYPOINT", "GITHUB_API_KEY",
                     "MY_TOKEN", "DB_SECRET"):
            self.assertNotIn(gone, clean)
        self.assertEqual(clean["ANTHROPIC_API_KEY"], "keep-me")
        self.assertEqual(clean["PATH"], "/usr/bin")
        self.assertEqual(clean["HOME"], "/home/u")


class PromptTest(unittest.TestCase):
    def test_prompt_contains_facts_delegation_and_prohibitions(self):
        prompt = clpe.build_prompt(
            worktree="/wt", plan_snapshot="/state/inputs/plan-p.md",
            spec_snapshots=["/state/inputs/spec-0-s.md"],
            starting_commit="a" * 40, branch="clpe/run-1",
        )
        for token in (
            "WORKTREE: /wt",
            "PLAN: /state/inputs/plan-p.md",
            "- /state/inputs/spec-0-s.md",
            f"STARTING_COMMIT: {'a' * 40}",
            "BRANCH: clpe/run-1",
            "superpowers:executing-plans",
            "superpowers:subagent-driven-development",
            "Do not merge, push, deploy",
            "Do not ask the user questions",
        ):
            self.assertIn(token, prompt)

    def test_resume_prompt_repeats_schema_contract_and_prohibitions(self):
        self.assertIn("Continue executing the plan", clpe.RESUME_PROMPT)
        self.assertIn("Do not merge, push, deploy", clpe.RESUME_PROMPT)


class ArgvTest(unittest.TestCase):
    def test_base_argv_contract(self):
        argv = clpe.build_argv("PROMPT")
        self.assertEqual(argv[0], "claude")
        self.assertEqual(argv[1:3], ["-p", "PROMPT"])
        self.assertNotIn("--bare", argv)
        self.assertIn("stream-json", argv)
        self.assertIn("--verbose", argv)
        self.assertIn("--json-schema", argv)
        schema_content = clpe.SCHEMA_PATH.read_text(encoding="utf-8")
        self.assertIn(schema_content, argv)            # inline JSON content, not a path
        self.assertNotIn(str(clpe.SCHEMA_PATH), argv)  # the path must NOT be an argv element
        self.assertEqual(argv.count("--disallowedTools"), 1)  # single variadic flag
        deny_at = argv.index("--disallowedTools")
        self.assertEqual(
            tuple(argv[deny_at + 1:deny_at + 1 + len(clpe.DENY_TOOLS)]),
            tuple(clpe.DENY_TOOLS),
        )
        self.assertIn("bypassPermissions", argv)
        for rule in clpe.DENY_TOOLS:
            self.assertIn(rule, argv)
        self.assertNotIn("--resume", argv)
        self.assertNotIn("--model", argv)
        self.assertNotIn("--max-turns", argv)

    def test_optional_flags(self):
        argv = clpe.build_argv("P", model="opus",
                               resume_session="sess-1")
        self.assertIn("--model", argv)
        self.assertIn("opus", argv)
        self.assertNotIn("--max-turns", argv)
        self.assertEqual(argv[argv.index("--resume") + 1], "sess-1")


import os


class StateStoreTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="clpe-state-")
        self.addCleanup(self.temp.cleanup)
        self.old_home = os.environ.get("CLPE_HOME")
        os.environ["CLPE_HOME"] = self.temp.name
        def restore():
            if self.old_home is None:
                os.environ.pop("CLPE_HOME", None)
            else:
                os.environ["CLPE_HOME"] = self.old_home
        self.addCleanup(restore)

    def test_paths_derive_from_clpe_home(self):
        self.assertEqual(clpe.state_home(), Path(self.temp.name))
        self.assertEqual(clpe.run_dir("r1"),
                         Path(self.temp.name) / "clpe" / "r1")
        self.assertEqual(clpe.worktree_dir("r1"),
                         Path(self.temp.name) / "worktrees" / "r1")

    def test_derive_run_id_slugs_plan_name(self):
        run_id = clpe.derive_run_id(Path("/tmp/My Plan v2.md"))
        self.assertRegex(run_id, r"^my-plan-v2-\d{8}-\d{6}$")

    def test_save_and_load_round_trip(self):
        record = {"run_id": "r1", "status": "running", "launches": 0}
        clpe.run_dir("r1").mkdir(parents=True)
        clpe.save_run(record)
        self.assertEqual(clpe.load_run("r1"), record)
        self.assertIsNone(clpe.load_run("missing"))

    def test_snapshot_inputs_copies_plan_and_specs(self):
        base = Path(self.temp.name)
        plan = base / "plan.md"
        plan.write_text("# p\n", encoding="utf-8")
        spec = base / "spec.md"
        spec.write_text("# s\n", encoding="utf-8")
        rdir = clpe.run_dir("r2")
        rdir.mkdir(parents=True)
        plan_copy, spec_copies = clpe.snapshot_inputs(rdir, plan, [spec])
        self.assertEqual(plan_copy, rdir / "inputs" / "plan-plan.md")
        self.assertEqual(spec_copies, [rdir / "inputs" / "spec-0-spec.md"])
        self.assertEqual(plan_copy.read_text(encoding="utf-8"), "# p\n")


class LaunchTest(unittest.TestCase):
    def stream_path(self):
        handle = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False)
        handle.close()
        self.addCleanup(Path(handle.name).unlink)
        return Path(handle.name)

    def test_exited_captures_stdout(self):
        path = self.stream_path()
        outcome = clpe.launch(
            [sys.executable, "-c", "print('{\"type\":\"result\"}')"],
            cwd=".", env=dict(os.environ), timeout_seconds=30, stream_path=path,
        )
        self.assertEqual((outcome.kind, outcome.exit_code), ("exited", 0))
        self.assertIn('"result"', path.read_text(encoding="utf-8"))

    def test_timeout_kills_process_group(self):
        path = self.stream_path()
        outcome = clpe.launch(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            cwd=".", env=dict(os.environ), timeout_seconds=1, stream_path=path,
        )
        self.assertEqual(outcome.kind, "timed_out")

    def test_spawn_failure(self):
        outcome = clpe.launch(
            ["/nonexistent/claude-binary"],
            cwd=".", env=dict(os.environ), timeout_seconds=5,
            stream_path=self.stream_path(),
        )
        self.assertEqual(outcome.kind, "spawn_failed")


if __name__ == "__main__":
    unittest.main(verbosity=2)
