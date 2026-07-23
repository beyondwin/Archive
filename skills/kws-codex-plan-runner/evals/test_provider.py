import json
import os
import stat
import sys
import tempfile
import time
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from plan_runner.helper import HelperDescriptor  # noqa: E402
from plan_runner.provider import CodexAdapter, ProviderRequest  # noqa: E402
from plan_runner.recovery import ActivityLease  # noqa: E402


SESSION_ID = "12345678-1234-4234-8234-123456789abc"


class RecordingLease(ActivityLease):
    def __init__(self, stall_seconds=2):
        super().__init__(stall_seconds, time.monotonic())
        self.observed = []

    def observe_provider_event(self, kind, unique_key, now):
        accepted = super().observe_provider_event(kind, unique_key, now)
        self.observed.append((kind, unique_key, accepted))
        return accepted


class CodexProviderTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.worktree = self.root / "worktree"
        self.worktree.mkdir()
        self.common = self.root / "common"
        self.common.mkdir()
        self.schema = self.root / "result.schema.json"
        self.schema.write_text(
            json.dumps({"type": "object", "required": ["status"]}), encoding="utf-8"
        )
        self.output = self.root / "result.json"
        self.log = self.root / "launches.jsonl"
        self.bin = self.root / "bin"
        self.bin.mkdir()
        fake = SKILL_ROOT / "evals" / "fake_codex.py"
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        (self.bin / "codex").symlink_to(fake)
        self.helper = HelperDescriptor(
            1,
            self.worktree / ".kws-plan-runner.sock",
            "a" * 64,
            (str(Path(sys.executable).resolve()), str(fake.resolve())),
        )

    def tearDown(self):
        self.temporary.cleanup()

    def request(self, *, session_id=None, model="gpt-test"):
        return ProviderRequest(
            worktree=self.worktree,
            git_common_dir=self.common,
            prompt="execute this plan",
            output_schema=self.schema,
            output_path=self.output,
            sandbox="danger-full-access",
            model=model,
            session_id=session_id,
        )

    def adapter(self, scenario="initial", **overrides):
        source_env = {
            "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
            "FAKE_CODEX_SCENARIO": scenario,
            "FAKE_CODEX_LOG": str(self.log),
            "OPENAI_API_KEY": "provider-secret",
            "GH_TOKEN": "must-not-leak",
            "SSH_AUTH_SOCK": "/tmp/agent.sock",
            "LANG": "C.UTF-8",
        }
        values = {
            "source_env": source_env,
            "provider_auth_prefixes": ("OPENAI_", "CODEX_"),
            "remotes": ("origin",),
            "run_id": "run-1234",
            "helper": self.helper,
            "poll_seconds": 0.01,
        }
        values.update(overrides)
        return CodexAdapter(**values)

    def launch(self, scenario="initial", *, request=None, lease=None, **overrides):
        return self.adapter(scenario, **overrides).launch(
            request or self.request(), lease or RecordingLease()
        )

    def record(self):
        return json.loads(self.log.read_text(encoding="utf-8").splitlines()[-1])

    def test_builds_exact_initial_argv_without_implicit_session_flags(self):
        argv = self.adapter().build_argv(self.request())
        self.assertEqual(
            argv,
            [
                "codex",
                "exec",
                "--ignore-user-config",
                "--json",
                "--output-schema",
                str(self.schema),
                "--output-last-message",
                str(self.output),
                "--cd",
                str(self.worktree),
                "--sandbox",
                "danger-full-access",
                "--add-dir",
                str(self.common),
                "--model",
                "gpt-test",
                "-",
            ],
        )
        self.assertNotIn("--ephemeral", argv)
        self.assertNotIn("resume", argv)
        self.assertNotIn("--last", argv)

    def test_builds_resume_argv_with_exec_flags_before_explicit_session(self):
        argv = self.adapter().build_argv(self.request(session_id=SESSION_ID, model=None))
        self.assertEqual(
            argv,
            [
                "codex",
                "exec",
                "--ignore-user-config",
                "--json",
                "--output-schema",
                str(self.schema),
                "--output-last-message",
                str(self.output),
                "--cd",
                str(self.worktree),
                "--sandbox",
                "danger-full-access",
                "--add-dir",
                str(self.common),
                "resume",
                SESSION_ID,
                "-",
            ],
        )
        self.assertNotIn("--last", argv)
        self.assertNotIn("--ephemeral", argv)
        with self.assertRaisesRegex(ValueError, "UUID"):
            self.adapter().build_argv(self.request(session_id="not-a-session"))
        with self.assertRaisesRegex(ValueError, "canonical UUID"):
            self.adapter().build_argv(self.request(session_id=SESSION_ID.upper()))

    def test_launch_captures_explicit_session_and_structured_result(self):
        lease = RecordingLease()
        outcome = self.launch("initial", lease=lease)
        self.assertEqual(outcome.kind, "implemented")
        self.assertEqual(outcome.session_id, SESSION_ID)
        self.assertEqual(outcome.result["status"], "implemented")
        self.assertEqual(outcome.usage, {"input_tokens": 12, "output_tokens": 7})
        self.assertEqual(
            outcome.activity_keys,
            (
                "lifecycle_advanced:turn.started:turn-1",
                "tool_started:tool-1",
                "tool_finished:tool-1",
                "lifecycle_advanced:turn.completed:turn-1",
            ),
        )
        self.assertEqual(self.record()["prompt"], "execute this plan")

    def test_session_callback_fires_before_later_result_validation_fails(self):
        captured = []
        outcome = self.adapter("invalid-output").launch(
            self.request(),
            RecordingLease(),
            on_session_id=captured.append,
        )
        self.assertEqual(captured, [SESSION_ID])
        self.assertEqual(outcome.kind, "failed")

    def test_launch_uses_explicit_resume_and_sanitized_helper_environment(self):
        outcome = self.launch(
            "explicit-resume", request=self.request(session_id=SESSION_ID)
        )
        self.assertEqual(outcome.session_id, SESSION_ID)
        record = self.record()
        self.assertEqual(record["argv"][-3:], ["resume", SESSION_ID, "-"])
        self.assertEqual(Path(record["cwd"]).resolve(), self.worktree.resolve())
        self.assertEqual(record["env"]["OPENAI_API_KEY"], "provider-secret")
        self.assertNotIn("GH_TOKEN", record["env"])
        self.assertNotIn("SSH_AUTH_SOCK", record["env"])
        self.assertEqual(record["env"]["GIT_TERMINAL_PROMPT"], "0")
        self.assertEqual(record["env"]["GIT_CONFIG_COUNT"], "1")
        self.assertEqual(
            record["env"]["GIT_CONFIG_VALUE_0"],
            "disabled://plan-runner/run-1234/origin",
        )
        self.assertEqual(
            record["env"]["KWS_PLAN_RUNNER_HELPER_SOCKET"],
            str(self.helper.socket_path),
        )
        self.assertEqual(
            json.loads(record["env"]["KWS_PLAN_RUNNER_HELPER_CLIENT_ARGV"]),
            list(self.helper.client_argv),
        )

    def test_only_distinct_lifecycle_and_tool_events_refresh_activity(self):
        lease = RecordingLease()
        outcome = self.launch("repeated-log", lease=lease)
        self.assertEqual(outcome.kind, "implemented")
        self.assertTrue(all(accepted for _kind, _key, accepted in lease.observed))
        self.assertEqual(len(lease.observed), 4)

    def test_token_deltas_and_repeated_logs_do_not_prevent_stall(self):
        started = time.monotonic()
        outcome = self.launch("stall", lease=RecordingLease(0.12))
        self.assertEqual(outcome.kind, "stalled")
        self.assertEqual(outcome.provider_code, "stall_expired")
        self.assertLess(time.monotonic() - started, 2)

    def test_classifies_provider_blockers_from_structured_codes_only(self):
        cases = {
            "auth-blocked": "provider_auth_blocked",
            "auth-then-unknown": "provider_auth_blocked",
            "usage-blocked": "provider_usage_blocked",
            "unavailable": "provider_unavailable",
        }
        for scenario, code in cases.items():
            with self.subTest(scenario=scenario):
                outcome = self.launch(scenario)
                self.assertEqual(outcome.kind, "blocked")
                self.assertEqual(outcome.provider_code, code)

    def test_classifies_resume_transport_and_context_outcomes_for_engine(self):
        cases = {
            "resume-failure": ("resume_failed", "session_resume_failed"),
            "transport-failure": ("transport_failed", "controller_transport_failed"),
            "context-overflow": ("context_overflow", "session_invalid"),
        }
        for scenario, expected in cases.items():
            with self.subTest(scenario=scenario):
                request = self.request(session_id=SESSION_ID)
                outcome = self.launch(scenario, request=request)
                self.assertEqual((outcome.kind, outcome.provider_code), expected)

    def test_malformed_stream_and_invalid_structured_output_fail_closed(self):
        for scenario in ("malformed-jsonl", "oversized-jsonl", "invalid-output"):
            with self.subTest(scenario=scenario):
                outcome = self.launch(scenario)
                self.assertEqual(outcome.kind, "failed")
                self.assertEqual(outcome.provider_code, "controller_transport_failed")

    def test_result_statuses_are_preserved_and_only_implemented_commits(self):
        subprocess = __import__("subprocess")
        subprocess.run(["git", "init", "-q"], cwd=self.worktree, check=True)
        before = subprocess.run(
            ["git", "rev-list", "--all", "--count"],
            cwd=self.worktree,
            text=True,
            stdout=subprocess.PIPE,
            check=True,
        ).stdout.strip()
        for scenario in ("blocked", "failed"):
            outcome = self.launch(scenario)
            self.assertEqual(outcome.kind, scenario)
        middle = subprocess.run(
            ["git", "rev-list", "--all", "--count"],
            cwd=self.worktree,
            text=True,
            stdout=subprocess.PIPE,
            check=True,
        ).stdout.strip()
        outcome = self.launch("implemented")
        after = subprocess.run(
            ["git", "rev-list", "--all", "--count"],
            cwd=self.worktree,
            text=True,
            stdout=subprocess.PIPE,
            check=True,
        ).stdout.strip()
        self.assertEqual((before, middle), ("0", "0"))
        self.assertEqual(outcome.kind, "implemented")
        self.assertEqual(after, "1")

    def test_stderr_is_bounded_and_secret_scrubbed(self):
        outcome = self.launch("stderr-secret")
        self.assertLessEqual(len(outcome.stderr_tail.encode("utf-8")), 1_048_576)
        self.assertNotIn("super-secret", outcome.stderr_tail)
        self.assertNotIn("hunter2", outcome.stderr_tail)
        self.assertIn("[REDACTED]", outcome.stderr_tail)


if __name__ == "__main__":
    unittest.main()
