from __future__ import annotations

import importlib.util
import json
import os
import signal
import stat
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
HARNESS_PATH = SCRIPT_DIR / "plan-runner-live-canary.py"


def load_harness():
    spec = importlib.util.spec_from_file_location("plan_runner_live_canary", HARNESS_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load canary harness")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


canary = load_harness()


class LauncherTests(unittest.TestCase):
    def test_root_launcher_is_self_locating_and_uses_exact_find_contract(self):
        launcher = SCRIPT_DIR / "plan-runner-live-canary"
        text = launcher.read_text(encoding="utf-8")
        self.assertIn('SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)', text)
        expected = (
            "uv python find --managed-python --no-python-downloads \\\n"
            "  --no-project --no-config --resolve-links 3.13"
        )
        self.assertIn(expected, text)
        self.assertIn('exec "$PYTHON_BIN" "$SCRIPT_DIR/plan-runner-live-canary.py" "$@"', text)
        for forbidden in ("uv run", "uv python install", "python3"):
            self.assertNotIn(forbidden, text)
        self.assertTrue(launcher.stat().st_mode & stat.S_IXUSR)

    def test_provider_launchers_resolve_from_unrelated_cwd(self):
        for provider in ("codex", "claude"):
            launcher = (
                REPO_ROOT
                / f"skills/kws-{provider}-plan-runner/scripts/runner"
            )
            with self.subTest(provider=provider):
                text = launcher.read_text(encoding="utf-8")
                self.assertIn(
                    'SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)',
                    text,
                )
                self.assertIn('exec "$PYTHON_BIN" "$SCRIPT_DIR/runner.py" "$@"', text)
                for forbidden in ("uv run", "uv python install", "python3"):
                    self.assertNotIn(forbidden, text)


class CommandConstructionTests(unittest.TestCase):
    def test_codex_initial_uses_json_schema_disposable_cd_and_persistence(self):
        root = Path("/private/tmp/disposable")
        schema = root / "nonce.schema.json"
        output = root / "last.json"
        argv = canary.codex_session_argv(
            root=root, schema_path=schema, output_path=output, session_id=None
        )
        self.assertEqual(argv[:3], ["codex", "exec", "--ignore-user-config"])
        self.assertIn("--json", argv)
        self.assertEqual(argv[argv.index("--output-schema") + 1], str(schema))
        self.assertEqual(argv[argv.index("--cd") + 1], str(root))
        self.assertNotIn("--ephemeral", argv)
        self.assertEqual(argv[-1], "-")

    def test_codex_resume_uses_exact_id_and_never_last(self):
        session_id = str(uuid.uuid4())
        argv = canary.codex_session_argv(
            root=Path("/tmp/repo"),
            schema_path=Path("/tmp/schema"),
            output_path=Path("/tmp/output"),
            session_id=session_id,
        )
        self.assertEqual(argv[-3:], ["resume", session_id, "-"])
        self.assertNotIn("--last", argv)

    def test_codex_schema_and_result_are_outside_observed_repository(self):
        root = Path("/private/tmp/canary/repository")
        schema, output = canary.codex_probe_paths(root)
        self.assertEqual(schema.parent, root.parent)
        self.assertEqual(output.parent, root.parent)
        self.assertNotEqual(schema.parent, root)
        self.assertNotEqual(output.parent, root)

    def test_claude_initial_uses_generated_explicit_uuid(self):
        session_id = str(uuid.uuid4())
        argv = canary.claude_session_argv(
            prompt="bounded prompt", session_id=session_id, resume=False
        )
        self.assertEqual(argv[:2], ["claude", "-p"])
        self.assertIn("--output-format", argv)
        self.assertEqual(argv[argv.index("--output-format") + 1], "stream-json")
        self.assertIn("--verbose", argv)
        self.assertEqual(argv[argv.index("--session-id") + 1], session_id)
        self.assertNotIn("--resume", argv)

    def test_claude_resume_uses_exact_uuid_and_never_continue(self):
        session_id = str(uuid.uuid4())
        argv = canary.claude_session_argv(
            prompt="bounded prompt", session_id=session_id, resume=True
        )
        self.assertEqual(argv[argv.index("--resume") + 1], session_id)
        self.assertNotIn("--continue", argv)
        self.assertNotIn("--session-id", argv)


class ProcessAndParserTests(unittest.TestCase):
    def test_deadline_sends_term_then_bounded_kill_to_process_group(self):
        process = mock.Mock()
        process.pid = 321
        process.communicate.side_effect = [
            subprocess.TimeoutExpired(["provider"], 0.01),
            subprocess.TimeoutExpired(["provider"], 0.25),
            ("", ""),
        ]
        process.returncode = -signal.SIGKILL
        with (
            mock.patch.object(canary.subprocess, "Popen", return_value=process),
            mock.patch.object(canary.os, "killpg") as killpg,
        ):
            result = canary.run_bounded(
                ["provider"], cwd=Path("/tmp"), timeout=0.01
            )
        self.assertTrue(result.timed_out)
        self.assertEqual(
            killpg.call_args_list,
            [
                mock.call(321, signal.SIGTERM),
                mock.call(321, signal.SIGKILL),
            ],
        )
        self.assertLessEqual(canary.TERM_GRACE_SECONDS, 2.0)

    def test_codex_parser_returns_only_bounded_normalized_fields(self):
        session_id = str(uuid.uuid4())
        raw = "\n".join(
            [
                json.dumps({"type": "thread.started", "thread_id": session_id}),
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "agent_message",
                            "text": "SECRET PROMPT credential=TOKEN",
                        },
                    }
                ),
            ]
        )
        parsed = canary.parse_codex_stream(raw)
        self.assertEqual(parsed.session_id, session_id)
        serialized = json.dumps(parsed.normalized, sort_keys=True)
        for forbidden in ("SECRET PROMPT", "TOKEN", "credential", "raw"):
            self.assertNotIn(forbidden, serialized)
        self.assertLessEqual(len(serialized), canary.RESULT_LIMIT)

    def test_claude_parser_rejects_discontinuous_session(self):
        requested = str(uuid.uuid4())
        wrong = str(uuid.uuid4())
        raw = "\n".join(
            [
                json.dumps(
                    {"type": "system", "subtype": "init", "session_id": requested}
                ),
                json.dumps(
                    {
                        "type": "result",
                        "subtype": "success",
                        "session_id": wrong,
                        "structured_output": {"nonce": "abc"},
                    }
                ),
            ]
        )
        parsed = canary.parse_claude_stream(raw, expected_session_id=requested)
        self.assertEqual(parsed.status, "failed")
        self.assertEqual(parsed.reason_code, "session_discontinuous")

    def test_malformed_stream_is_failed_not_blocked(self):
        parsed = canary.parse_codex_stream("{not-json}\n")
        outcome = canary.classify_provider_result(
            canary.CommandResult(0, "{not-json}\n", "", False), parsed
        )
        self.assertEqual(outcome, ("failed", "stream_malformed"))

    def test_authentication_unavailable_is_blocked_without_leaking_text(self):
        secret = "sk-secret-value"
        parsed = canary.parse_codex_stream(
            json.dumps(
                {
                    "type": "error",
                    "error": {
                        "code": "authentication_error",
                        "message": f"invalid token {secret}",
                    },
                }
            )
            + "\n"
        )
        outcome = canary.classify_provider_result(
            canary.CommandResult(1, "", f"credential {secret}", False), parsed
        )
        self.assertEqual(outcome, ("blocked", "provider_auth_blocked"))
        self.assertNotIn(secret, json.dumps(parsed.normalized))


class SessionAndRunnerOutcomeTests(unittest.TestCase):
    def test_fake_session_success_requires_exact_nonce_id_and_clean_head(self):
        session_id = str(uuid.uuid4())
        fake = canary.SessionEvidence(
            initial_session_id=session_id,
            resumed_session_id=session_id,
            initial_nonce="nonce-1",
            resumed_nonce="nonce-1",
            head_before="a" * 40,
            head_after="a" * 40,
            porcelain="",
        )
        self.assertEqual(canary.validate_session_evidence(fake), (True, None))

    def test_fake_session_discontinuity_is_failed(self):
        fake = canary.SessionEvidence(
            initial_session_id=str(uuid.uuid4()),
            resumed_session_id=str(uuid.uuid4()),
            initial_nonce="nonce-1",
            resumed_nonce="nonce-1",
            head_before="a" * 40,
            head_after="a" * 40,
            porcelain="",
        )
        self.assertEqual(
            canary.validate_session_evidence(fake),
            (False, "session_discontinuous"),
        )

    def test_runner_state_requires_two_plans_distinct_and_final_session(self):
        state = {
            "status": "ready_for_integration",
            "integration": "not_observed",
            "repository": {"worktree": "/tmp/worktree"},
            "plans": [{"status": "implemented"}, {"status": "implemented"}],
            "sessions": [
                {"mode": "implementation", "plan_index": 0, "session_id": "a"},
                {"mode": "implementation", "plan_index": 1, "session_id": "b"},
                {"mode": "finalization", "session_id": "c"},
            ],
            "finalization": {
                "candidate_head": "f" * 40,
                "review_head": "f" * 40,
                "verification_commands": [
                    {"status": "passed", "candidate_head": "f" * 40}
                ],
                "review": {"status": "approved", "candidate_head": "f" * 40},
            },
        }
        valid, reason, head = canary.validate_runner_state(
            state, observed_head="f" * 40, porcelain=""
        )
        self.assertTrue(valid, reason)
        self.assertEqual(head, "f" * 40)

    def test_runner_state_rejects_same_plan_session(self):
        state = {
            "status": "ready_for_integration",
            "integration": "not_observed",
            "plans": [{"status": "implemented"}, {"status": "implemented"}],
            "sessions": [
                {"mode": "implementation", "plan_index": 0, "session_id": "a"},
                {"mode": "implementation", "plan_index": 1, "session_id": "a"},
                {"mode": "finalization", "session_id": "c"},
            ],
            "finalization": {"candidate_head": "f" * 40},
        }
        valid, reason, _head = canary.validate_runner_state(
            state, observed_head="f" * 40, porcelain=""
        )
        self.assertFalse(valid)
        self.assertEqual(reason, "plan_session_not_distinct")

    def test_real_receipt_shape_requires_success_at_final_head(self):
        candidate = "f" * 40
        receipt = {
            "identity": {"candidate_head": candidate},
            "outcome": "success",
            "exit_code": 0,
        }
        self.assertTrue(canary.valid_receipt_payload(receipt, candidate))
        self.assertFalse(
            canary.valid_receipt_payload(
                {**receipt, "outcome": "failed"}, candidate
            )
        )

    def test_normalized_result_has_public_bounded_shape(self):
        result = canary.normalized_result(
            provider="codex",
            mode="runner",
            status="passed",
            provider_version="codex-cli 1.2.3 " + "x" * 1000,
            session_action="fresh_then_resume",
            final_head="f" * 40,
            elapsed=1.23456,
        )
        self.assertEqual(
            set(result),
            {
                "provider",
                "mode",
                "status",
                "provider_version",
                "session_action",
                "final_head",
                "elapsed_seconds",
            },
        )
        text = json.dumps(result)
        self.assertLessEqual(len(text), canary.RESULT_LIMIT)


class MainTests(unittest.TestCase):
    def test_invalid_invocation_returns_64(self):
        self.assertEqual(canary.main(["--provider", "bogus"]), 64)


if __name__ == "__main__":
    unittest.main()
