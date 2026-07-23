from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import time
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from plan_runner.helper import HelperDescriptor  # noqa: E402
from plan_runner.provider import (  # noqa: E402
    ClaudeAdapter,
    ProviderOutcome,
    ProviderRequest,
)
from plan_runner.recovery import ActivityLease  # noqa: E402


SESSION_ID = "00000000-0000-4000-8000-000000000001"
DENY_TOOLS = (
    "AskUserQuestion",
    "EnterPlanMode",
    "ExitPlanMode",
    "Bash(git push*)",
    "Bash(git merge*)",
    "Bash(gh pr create*)",
    "Bash(glab mr create*)",
    "Bash(rm -rf /*)",
    "Bash(git reset --hard origin*)",
)


class RecordingLease(ActivityLease):
    def __init__(self, stall_seconds=2):
        super().__init__(stall_seconds, time.monotonic())
        self.observed = []

    def observe_provider_event(self, kind, unique_key, now):
        accepted = super().observe_provider_event(kind, unique_key, now)
        self.observed.append((kind, unique_key, accepted))
        return accepted


class ClaudeProviderTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.worktree = self.root / "worktree"
        self.worktree.mkdir()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.log = self.root / "launches.jsonl"
        fake = SKILL_ROOT / "evals" / "fake_claude.py"
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        (self.bin / "claude").symlink_to(fake)
        self.helper = HelperDescriptor(
            1,
            self.worktree / ".kws-plan-runner.sock",
            "a" * 64,
            (str(Path(sys.executable).resolve()), str(fake.resolve())),
        )

    def tearDown(self):
        self.temporary.cleanup()

    def request(self, *, resume=False, model="opus-test", session_id=SESSION_ID):
        return ProviderRequest(
            worktree=self.worktree,
            prompt="execute the current plan",
            output_schema={
                "type": "object",
                "required": ["status"],
                "properties": {"status": {"type": "string"}},
            },
            model=model,
            session_id=session_id,
            resume=resume,
        )

    def adapter(self, scenario="success", **overrides):
        source_env = {
            "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
            "LANG": "C.UTF-8",
            "FAKE_CLAUDE_SCENARIO": scenario,
            "FAKE_CLAUDE_LOG": str(self.log),
            "ANTHROPIC_API_KEY": "provider-secret",
            "CLAUDECODE": "1",
            "CLAUDE_CODE_CHILD_SESSION": "nested",
            "CLAUDE_CODE_ENTRYPOINT": "codex",
            "GH_TOKEN": "git-host-secret",
            "GITHUB_PAT": "github-pat",
            "BITBUCKET_APP_PASSWORD": "bitbucket-password",
            "SSH_AUTH_SOCK": "/tmp/agent.sock",
            "AWS_ACCESS_KEY_ID": "cloud-id",
            "AWS_SECRET_ACCESS_KEY": "cloud-secret",
            "AWS_SHARED_CREDENTIALS_FILE": "/tmp/aws-credentials",
            "AWS_PROFILE": "production",
            "GOOGLE_APPLICATION_CREDENTIALS": "/tmp/gcp.json",
            "CLOUDSDK_CONFIG": "/tmp/gcloud",
            "AZURE_CONFIG_DIR": "/tmp/azure",
            "DOCKER_CONFIG": "/tmp/docker",
            "KUBECONFIG": "/tmp/kubeconfig",
            "NETRC": "/tmp/netrc",
        }
        values = {
            "source_env": source_env,
            "remotes": ("origin",),
            "run_id": "run-claude-1",
            "helper": self.helper,
            "poll_seconds": 0.01,
        }
        values.update(overrides)
        return ClaudeAdapter(**values)

    def launch(self, scenario="success", *, request=None, lease=None, **overrides):
        return self.adapter(scenario, **overrides).launch(
            request or self.request(),
            lease or RecordingLease(),
        )

    def record(self):
        return json.loads(self.log.read_text(encoding="utf-8").splitlines()[-1])

    def test_builds_exact_initial_argv_with_one_variadic_deny_flag(self):
        request = self.request()
        schema = json.dumps(
            {
                "type": "object",
                "required": ["status"],
                "properties": {"status": {"type": "string"}},
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        self.assertEqual(
            self.adapter().build_argv(request),
            [
                "claude",
                "-p",
                "execute the current plan",
                "--output-format",
                "stream-json",
                "--verbose",
                "--json-schema",
                schema,
                "--permission-mode",
                "bypassPermissions",
                "--disallowedTools",
                *DENY_TOOLS,
                "--session-id",
                SESSION_ID,
                "--model",
                "opus-test",
            ],
        )
        argv = self.adapter().build_argv(request)
        self.assertEqual(argv.count("--disallowedTools"), 1)
        for forbidden in ("--bare", "--safe-mode", "--continue", "--max-budget-usd"):
            self.assertNotIn(forbidden, argv)

    def test_resume_uses_only_explicit_resume_and_rejects_noncanonical_uuid(self):
        argv = self.adapter().build_argv(self.request(resume=True, model=None))
        self.assertEqual(argv[-2:], ["--resume", SESSION_ID])
        self.assertNotIn("--session-id", argv)
        self.assertNotIn("--continue", argv)
        for invalid in (
            "not-a-uuid",
            "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA",
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ValueError, "UUID"):
                    self.adapter().build_argv(self.request(session_id=invalid))

    def test_model_and_resume_are_optional_request_controls(self):
        request = ProviderRequest(
            worktree=self.worktree,
            prompt="use provider defaults",
            output_schema={"type": "object"},
            session_id=SESSION_ID,
        )
        argv = self.adapter().build_argv(request)
        self.assertNotIn("--model", argv)
        self.assertIn("--session-id", argv)
        self.assertNotIn("--resume", argv)

    def test_request_and_outcome_snapshot_mutable_json_inputs(self):
        schema = {
            "type": "object",
            "required": ["status"],
            "properties": {"status": {"enum": ["implemented"]}},
        }
        request = ProviderRequest(
            worktree=self.worktree,
            prompt="immutable",
            output_schema=schema,
            session_id=SESSION_ID,
        )
        schema["required"].append("mutated")
        schema["properties"]["status"]["enum"][0] = "failed"
        argv = self.adapter().build_argv(request)
        encoded = argv[argv.index("--json-schema") + 1]
        self.assertNotIn("mutated", encoded)
        self.assertIn("implemented", encoded)
        with self.assertRaises(TypeError):
            request.output_schema["type"] = "array"
        with self.assertRaises(FrozenInstanceError):
            request.resume = True

        result = {"status": "implemented", "nested": {"items": ["one"]}}
        usage = {"input_tokens": 1}
        outcome = ProviderOutcome(
            "implemented", 0, SESSION_ID, result, None, usage, (), ""
        )
        result["nested"]["items"].append("two")
        usage["input_tokens"] = 99
        self.assertEqual(outcome.result["nested"]["items"], ("one",))
        self.assertEqual(outcome.usage["input_tokens"], 1)
        with self.assertRaises(TypeError):
            outcome.result["status"] = "failed"

    def test_launch_captures_session_result_usage_and_distinct_activity(self):
        lease = RecordingLease()
        outcome = self.launch(lease=lease)
        self.assertEqual(outcome.kind, "implemented")
        self.assertEqual(outcome.return_code, 0)
        self.assertEqual(outcome.session_id, SESSION_ID)
        self.assertEqual(outcome.result["status"], "implemented")
        self.assertEqual(outcome.usage, {"input_tokens": 17, "output_tokens": 9})
        self.assertEqual(
            outcome.activity_keys,
            (
                f"lifecycle_advanced:system.init:{SESSION_ID}",
                "lifecycle_advanced:assistant:message-1",
                "tool_started:tool-1",
                "tool_finished:tool-1",
            ),
        )

    def test_session_callback_runs_before_invalid_result_is_rejected(self):
        captured = []
        outcome = self.adapter("callback-then-invalid").launch(
            self.request(), RecordingLease(), on_session_id=captured.append
        )
        self.assertEqual(captured, [SESSION_ID])
        self.assertEqual(outcome.kind, "failed")

    def test_resume_and_sanitized_environment_are_observable_by_child(self):
        outcome = self.launch(
            "explicit-resume", request=self.request(resume=True, model=None)
        )
        self.assertEqual(outcome.kind, "implemented")
        record = self.record()
        self.assertTrue(record["resume"])
        self.assertEqual(Path(record["cwd"]).resolve(), self.worktree.resolve())
        self.assertEqual(record["credentials"], {"ANTHROPIC_API_KEY": "provider-secret"})
        self.assertFalse(any(record["nesting_markers"].values()))
        self.assertEqual(record["git_terminal_prompt"], "0")
        self.assertEqual(record["git_config_count"], "1")
        self.assertEqual(
            record["git_pushurl"],
            "disabled://plan-runner/run-claude-1/origin",
        )
        self.assertEqual(record["helper_socket"], str(self.helper.socket_path))

    def test_repeated_chunks_and_logs_do_not_refresh_lease(self):
        lease = RecordingLease()
        outcome = self.launch("repeated", lease=lease)
        self.assertEqual(outcome.kind, "implemented")
        self.assertEqual(len(lease.observed), 4)
        self.assertTrue(all(accepted for _kind, _key, accepted in lease.observed))

    def test_duplicate_output_cannot_keep_a_stalled_process_alive(self):
        started = time.monotonic()
        outcome = self.launch("stall", lease=RecordingLease(0.12))
        self.assertEqual(outcome.kind, "stalled")
        self.assertEqual(outcome.provider_code, "stall_expired")
        self.assertLess(time.monotonic() - started, 2)

    def test_rate_limit_and_provider_api_errors_classify_fail_closed(self):
        rate = self.launch("rate-limit")
        self.assertEqual((rate.kind, rate.provider_code), ("blocked", "provider_usage_blocked"))
        unavailable = self.launch("api-error")
        self.assertEqual(
            (unavailable.kind, unavailable.provider_code),
            ("transport_failed", "provider_unavailable"),
        )
        auth = self.launch("auth-error")
        self.assertEqual((auth.kind, auth.provider_code), ("blocked", "provider_auth_blocked"))
        self.assertEqual(self.launch("allowed-rate-limit").kind, "implemented")

    def test_interruption_resume_context_and_missing_session_are_distinct(self):
        cases = {
            "interrupted": ("interrupted", "controller_transport_failed"),
            "resume-failed": ("resume_failed", "session_resume_failed"),
            "context-damaged": ("context_overflow", "session_invalid"),
            "session-missing": ("session_missing", "session_invalid"),
        }
        for scenario, expected in cases.items():
            with self.subTest(scenario=scenario):
                request = self.request(resume=scenario == "resume-failed")
                outcome = self.launch(scenario, request=request)
                self.assertEqual((outcome.kind, outcome.provider_code), expected)

    def test_success_without_structured_output_and_malformed_stream_fail_closed(self):
        missing = self.launch("success-no-structured")
        self.assertEqual((missing.kind, missing.provider_code), ("failed", "controller_transport_failed"))
        for scenario in ("malformed", "oversized"):
            with self.subTest(scenario=scenario):
                outcome = self.launch(scenario)
                self.assertEqual((outcome.kind, outcome.provider_code), ("failed", "controller_transport_failed"))

    def test_stderr_is_bounded_and_secrets_are_scrubbed(self):
        outcome = self.launch("stderr-secret", lease=RecordingLease(10))
        self.assertLessEqual(len(outcome.stderr_tail.encode()), 1_048_576)
        self.assertNotIn("super-secret", outcome.stderr_tail)
        self.assertNotIn("hunter2", outcome.stderr_tail)
        self.assertIn("[REDACTED]", outcome.stderr_tail)

    def test_stderr_boundary_never_exposes_secret_after_key_or_equals_cut(self):
        for scenario, secret in (
            ("stderr-boundary-key", "middle-secret"),
            ("stderr-boundary-equals", "equals-secret"),
        ):
            with self.subTest(scenario=scenario):
                outcome = self.launch(scenario, lease=RecordingLease(10))
                self.assertEqual(outcome.kind, "implemented")
                self.assertNotIn(secret, outcome.stderr_tail)
                self.assertLessEqual(len(outcome.stderr_tail.encode()), 1_048_576)


if __name__ == "__main__":
    unittest.main()
