import dataclasses
import json
import os
import stat
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from plan_runner import provider as provider_module  # noqa: E402
from plan_runner.git_ops import GitIdentity  # noqa: E402
from plan_runner.helper import HelperDescriptor  # noqa: E402
from plan_runner.provider import CodexAdapter, ProviderRequest  # noqa: E402
from plan_runner.recovery import ActivityLease  # noqa: E402


SESSION_ID = "12345678-1234-4234-8234-123456789abc"
SDD_RELATIVE_PATHS = (
    Path("skills/subagent-driven-development/SKILL.md"),
    Path("skills/subagent-driven-development/scripts/sdd-workspace"),
    Path("skills/subagent-driven-development/scripts/task-brief"),
    Path("skills/subagent-driven-development/scripts/review-package"),
    Path("skills/subagent-driven-development/implementer-prompt.md"),
    Path("skills/subagent-driven-development/task-reviewer-prompt.md"),
    Path("skills/subagent-driven-development/re-review-prompt.md"),
    Path("skills/requesting-code-review/code-reviewer.md"),
)


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
        self.codex_home = self.root / "operator-codex-home"
        self.make_codex_home(self.codex_home)
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
            git_identity=GitIdentity("Runner Test", "runner@example.test"),
            prompt="execute this plan",
            output_schema=self.schema,
            output_path=self.output,
            sandbox="danger-full-access",
            model=model,
            session_id=session_id,
        )

    def make_codex_home(self, path, *, auth=True, sdd=True):
        path.mkdir()
        if auth:
            (path / "auth.json").write_text(
                json.dumps(
                    {
                        "auth_mode": "apikey",
                        "last_refresh": None,
                        "OPENAI_API_KEY": "fake-file-api-key",
                        "tokens": None,
                    }
                ),
                encoding="utf-8",
            )
        if sdd:
            for relative in SDD_RELATIVE_PATHS:
                target = path / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("fake-sdd-entrypoint\n", encoding="utf-8")

    def environment(self, scenario):
        return {
            "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
            "FAKE_CODEX_SCENARIO": scenario,
            "FAKE_CODEX_LOG": str(self.log),
            "OPENAI_API_KEY": "provider-secret",
            "CODEX_HOME": str(self.codex_home),
            "GH_TOKEN": "must-not-leak",
            "SSH_AUTH_SOCK": "/tmp/agent.sock",
            "HOME": "/Users/operator",
            "XDG_CONFIG_HOME": "/Users/operator/.config",
            "DOCKER_AUTH_CONFIG": '{"auths":{"registry.example":"secret"}}',
            "DATABASE_URL": "postgres://operator:secret@database/app",
            "PGPASSWORD": "database-secret",
            "STRIPE_SECRET_KEY": "sk_live_service_secret",
            "LANG": "C.UTF-8",
        }

    def adapter(self, scenario="initial", **overrides):
        source_env = overrides.pop("source_env", self.environment(scenario))
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
                "--ignore-rules",
                "--strict-config",
                "-c",
                'approval_policy="never"',
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
                "--ignore-rules",
                "--strict-config",
                "-c",
                'approval_policy="never"',
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

    def test_resume_reuses_exact_noninteractive_flags(self):
        expected_prefix = [
            "codex",
            "exec",
            "--ignore-user-config",
            "--ignore-rules",
            "--strict-config",
            "-c",
            'approval_policy="never"',
            "--json",
        ]
        initial = self.adapter().build_argv(self.request())
        resumed = self.adapter().build_argv(
            self.request(session_id=SESSION_ID, model=None)
        )

        self.assertEqual(initial[: len(expected_prefix)], expected_prefix)
        self.assertEqual(resumed[: len(expected_prefix)], expected_prefix)

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

    def test_current_codex_cli_lifecycle_without_turn_ids_is_accepted(self):
        lease = RecordingLease()

        outcome = self.launch("current-cli-lifecycle", lease=lease)

        self.assertEqual(outcome.kind, "implemented")
        self.assertEqual(outcome.session_id, SESSION_ID)
        self.assertEqual(outcome.usage, {"input_tokens": 12, "output_tokens": 7})
        self.assertEqual(
            outcome.activity_keys,
            (
                "lifecycle_advanced:turn.started",
                "tool_started:tool-1",
                "tool_finished:tool-1",
                "lifecycle_advanced:turn.completed",
            ),
        )

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
        self.assertEqual(record["env"]["CODEX_HOME"], str(self.codex_home))
        self.assertNotIn("GH_TOKEN", record["env"])
        self.assertNotIn("SSH_AUTH_SOCK", record["env"])
        for key in (
            "DOCKER_AUTH_CONFIG",
            "DATABASE_URL",
            "PGPASSWORD",
            "STRIPE_SECRET_KEY",
        ):
            self.assertNotIn(key, record["env"])
        isolated_home = self.output.parent / ".codex-child-home"
        self.assertEqual(record["env"]["HOME"], str(isolated_home))
        self.assertEqual(
            record["env"]["XDG_CONFIG_HOME"], str(isolated_home / ".config")
        )
        self.assertEqual(record["env"]["GIT_TERMINAL_PROMPT"], "0")
        self.assertEqual(record["env"]["GIT_CONFIG_COUNT"], "5")
        self.assertEqual(record["env"]["GIT_CONFIG_KEY_0"], "user.name")
        self.assertEqual(record["env"]["GIT_CONFIG_VALUE_0"], "Runner Test")
        self.assertEqual(record["env"]["GIT_CONFIG_KEY_1"], "user.email")
        self.assertEqual(
            record["env"]["GIT_CONFIG_VALUE_1"], "runner@example.test"
        )
        self.assertEqual(
            record["env"]["GIT_CONFIG_VALUE_4"],
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

    def test_initial_and_resumed_requests_use_the_same_sealed_git_identity(self):
        isolated_home = self.output.parent / ".codex-child-home"
        isolated_home.mkdir()
        (isolated_home / ".gitconfig").write_text(
            "[user]\n"
            "\tname = Wrong Home\n"
            "\temail = wrong-home@example.test\n",
            encoding="utf-8",
        )
        request_values = {
            "worktree": self.worktree,
            "git_common_dir": self.common,
            "git_identity": GitIdentity("Runner Test", "runner@example.test"),
            "prompt": "execute this plan",
            "output_schema": self.schema,
            "output_path": self.output,
            "sandbox": "danger-full-access",
            "model": "gpt-test",
        }
        try:
            initial = ProviderRequest(**request_values)
            resumed = ProviderRequest(**request_values, session_id=SESSION_ID)
        except TypeError as error:
            self.fail(f"ProviderRequest does not accept sealed Git identity: {error}")

        self.launch("initial", request=initial)
        self.launch("explicit-resume", request=resumed)
        records = [
            json.loads(line)
            for line in self.log.read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(initial.git_identity, resumed.git_identity)
        for record in records:
            config = {
                record["env"][f"GIT_CONFIG_KEY_{index}"]: record["env"][
                    f"GIT_CONFIG_VALUE_{index}"
                ]
                for index in range(int(record["env"]["GIT_CONFIG_COUNT"]))
            }
            self.assertEqual(config["user.name"], "Runner Test")
            self.assertEqual(config["user.email"], "runner@example.test")

    def test_effective_codex_home_preserves_auth_and_superpowers_discovery(self):
        environment = self.environment("initial")
        environment.pop("OPENAI_API_KEY")

        outcome = self.adapter(source_env=environment).launch(
            self.request(), RecordingLease()
        )

        self.assertEqual(outcome.kind, "implemented")
        record = self.record()
        self.assertEqual(record["env"]["CODEX_HOME"], str(self.codex_home))
        self.assertTrue(record["codex_auth_visible"])
        self.assertTrue(record["sdd_capabilities_visible"])

    def test_environment_token_auth_still_uses_effective_codex_home_for_superpowers(self):
        (self.codex_home / "auth.json").unlink()
        environment = self.environment("initial")
        environment["OPENAI_API_KEY"] = "test-token"

        outcome = self.adapter(source_env=environment).launch(
            self.request(), RecordingLease()
        )

        self.assertEqual(outcome.kind, "implemented")
        record = self.record()
        self.assertFalse(record["codex_auth_visible"])
        self.assertTrue(record["sdd_capabilities_visible"])
        self.assertEqual(record["env"]["CODEX_HOME"], str(self.codex_home))

    def test_missing_auth_or_sdd_capability_fails_before_child_launch(self):
        missing_auth = self.root / "missing-auth-home"
        self.make_codex_home(missing_auth, auth=False)
        auth_environment = self.environment("initial")
        auth_environment["CODEX_HOME"] = str(missing_auth)
        auth_environment.pop("OPENAI_API_KEY")

        missing_sdd = self.root / "missing-sdd-home"
        self.make_codex_home(missing_sdd, sdd=False)
        sdd_environment = self.environment("initial")
        sdd_environment["CODEX_HOME"] = str(missing_sdd)

        cases = (
            (auth_environment, "provider_auth_blocked"),
            (sdd_environment, "provider_capability_blocked"),
        )
        for environment, provider_code in cases:
            with self.subTest(provider_code=provider_code):
                outcome = self.adapter(source_env=environment).launch(
                    self.request(), RecordingLease()
                )
                self.assertEqual(outcome.kind, "blocked")
                self.assertEqual(outcome.provider_code, provider_code)
                self.assertFalse(self.log.exists())

    def test_arbitrary_prefixed_api_key_does_not_satisfy_auth_preflight(self):
        (self.codex_home / "auth.json").unlink()
        environment = self.environment("initial")
        environment.pop("OPENAI_API_KEY")
        environment["OPENAI_UNUSED_API_KEY"] = "not-a-supported-route"

        outcome = self.adapter(source_env=environment).launch(
            self.request(), RecordingLease()
        )

        self.assertEqual(outcome.kind, "blocked")
        self.assertEqual(outcome.provider_code, "provider_auth_blocked")
        self.assertFalse(self.log.exists())

    def test_file_auth_requires_structurally_usable_api_key_or_token(self):
        environment = self.environment("initial")
        environment.pop("OPENAI_API_KEY")
        auth_path = self.codex_home / "auth.json"
        unusable_documents = (
            "not-json",
            json.dumps(
                {
                    "auth_mode": "chatgpt",
                    "last_refresh": None,
                    "OPENAI_API_KEY": "",
                    "tokens": {
                        "access_token": "",
                        "account_id": "account-only-is-not-auth",
                        "id_token": "",
                        "refresh_token": "",
                    },
                }
            ),
        )
        for document in unusable_documents:
            with self.subTest(document=document[:16]):
                auth_path.write_text(document, encoding="utf-8")
                outcome = self.adapter(source_env=environment).launch(
                    self.request(), RecordingLease()
                )
                self.assertEqual(outcome.kind, "blocked")
                self.assertEqual(outcome.provider_code, "provider_auth_blocked")
                self.assertFalse(self.log.exists())

        auth_path.write_text(
            json.dumps(
                {
                    "auth_mode": "chatgpt",
                    "last_refresh": None,
                    "OPENAI_API_KEY": None,
                    "tokens": {
                        "access_token": "fake-access-token",
                        "account_id": "fake-account",
                        "id_token": None,
                        "refresh_token": "fake-refresh-token",
                    },
                }
            ),
            encoding="utf-8",
        )
        outcome = self.adapter(source_env=environment).launch(
            self.request(), RecordingLease()
        )
        self.assertEqual(outcome.kind, "implemented")

    def test_missing_sdd_prompt_or_reviewer_template_blocks_before_launch(self):
        prompt_members = SDD_RELATIVE_PATHS[4:]
        for index, relative in enumerate(prompt_members):
            with self.subTest(relative=str(relative)):
                home = self.root / f"missing-prompt-{index}"
                self.make_codex_home(home)
                (home / relative).unlink()
                environment = self.environment("initial")
                environment["CODEX_HOME"] = str(home)
                outcome = self.adapter(source_env=environment).launch(
                    self.request(), RecordingLease()
                )
                self.assertEqual(outcome.kind, "blocked")
                self.assertEqual(
                    outcome.provider_code, "provider_capability_blocked"
                )
                self.assertFalse(self.log.exists())

    def test_child_does_not_copy_codex_home_into_runner_state(self):
        private_markers = {
            "config.toml": "operator-config-secret",
            "rules/default.rules": "operator-rule-secret",
            "sessions/history.jsonl": "operator-session-secret",
            "log/codex.log": "operator-log-secret",
        }
        for relative, contents in private_markers.items():
            target = self.codex_home / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(contents, encoding="utf-8")
        runner_root = self.root / "runner-state"
        artifacts = runner_root / "artifacts"
        artifacts.mkdir(parents=True)
        request = dataclasses.replace(
            self.request(), output_path=artifacts / "provider-result.json"
        )

        outcome = self.adapter().launch(request, RecordingLease())

        self.assertEqual(outcome.kind, "implemented")
        runner_files = [path for path in runner_root.rglob("*") if path.is_file()]
        self.assertEqual(
            [path.name for path in runner_files],
            ["provider-result.json"],
        )
        retained = b"".join(path.read_bytes() for path in runner_files)
        for contents in private_markers.values():
            self.assertNotIn(contents.encode(), retained)

    def test_full_access_ignores_repo_rules_and_never_requests_approval(self):
        rule = self.worktree / ".codex" / "rules" / "git-prompt.rules"
        rule.parent.mkdir(parents=True)
        rule.write_text(
            'prefix_rule(pattern=["git"], decision="prompt")\n',
            encoding="utf-8",
        )

        outcome = self.launch("initial")

        self.assertEqual(outcome.kind, "implemented")
        record = self.record()
        self.assertIn("--ignore-rules", record["argv"])
        self.assertIn("--strict-config", record["argv"])
        self.assertEqual(
            record["argv"][record["argv"].index("-c") + 1],
            'approval_policy="never"',
        )
        self.assertEqual(
            record["argv"][record["argv"].index("--sandbox") + 1],
            "danger-full-access",
        )
        self.assertEqual(record.get("approval_events", 1), 0)

    def test_unsupported_required_cli_flag_blocks_before_provider_edits(self):
        rejecting_bin = self.root / "rejecting-bin"
        rejecting_bin.mkdir()
        rejecting_codex = rejecting_bin / "codex"
        rejecting_codex.write_bytes(
            (SKILL_ROOT / "evals" / "fake_codex.py").read_bytes()
        )
        rejecting_codex.chmod(rejecting_codex.stat().st_mode | stat.S_IXUSR)
        environment = self.environment("initial")
        environment["PATH"] = (
            f"{rejecting_bin}{os.pathsep}{os.environ['PATH']}"
        )
        environment["FAKE_CODEX_REJECT_REQUIRED_FLAG"] = "--ignore-rules"
        before = sorted(
            str(path.relative_to(self.worktree))
            for path in self.worktree.rglob("*")
        )

        outcome = self.adapter(source_env=environment).launch(
            self.request(), RecordingLease()
        )

        self.assertEqual(outcome.kind, "blocked")
        self.assertEqual(outcome.provider_code, "sandbox_capability_blocked")
        self.assertFalse(self.log.exists())
        self.assertEqual(
            sorted(
                str(path.relative_to(self.worktree))
                for path in self.worktree.rglob("*")
            ),
            before,
        )

    def test_missing_or_unexecutable_cli_is_provider_unavailable(self):
        cases = {}
        missing_environment = self.environment("initial")
        missing_environment["PATH"] = str(self.root / "missing-bin")
        cases["missing"] = missing_environment

        unexecutable_bin = self.root / "unexecutable-bin"
        unexecutable_bin.mkdir()
        unexecutable = unexecutable_bin / "codex"
        unexecutable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        unexecutable.chmod(0o600)
        unexecutable_environment = self.environment("initial")
        unexecutable_environment["PATH"] = str(unexecutable_bin)
        cases["unexecutable"] = unexecutable_environment

        for label, environment in cases.items():
            with self.subTest(label=label):
                outcome = self.adapter(source_env=environment).launch(
                    self.request(), RecordingLease()
                )
                self.assertEqual(outcome.kind, "transport_failed")
                self.assertEqual(outcome.provider_code, "provider_unavailable")
                self.assertFalse(self.log.exists())

    def test_version_and_nonparse_probe_failures_are_transport_outcomes(self):
        cases = (
            (
                "version",
                "FAKE_CODEX_VERSION_FAILURE",
                "provider_unavailable",
            ),
            (
                "probe",
                "FAKE_CODEX_PROBE_TRANSPORT_FAILURE",
                "controller_transport_failed",
            ),
            (
                "unrelated-parse",
                "FAKE_CODEX_UNRELATED_PARSE_FAILURE",
                "controller_transport_failed",
            ),
        )
        for label, environment_key, provider_code in cases:
            with self.subTest(label=label):
                isolated_bin = self.root / f"{label}-failure-bin"
                isolated_bin.mkdir()
                executable = isolated_bin / "codex"
                executable.write_bytes(
                    (SKILL_ROOT / "evals" / "fake_codex.py").read_bytes()
                )
                executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
                environment = self.environment("initial")
                environment["PATH"] = (
                    f"{isolated_bin}{os.pathsep}{os.environ['PATH']}"
                )
                environment[environment_key] = "1"

                outcome = self.adapter(source_env=environment).launch(
                    self.request(), RecordingLease()
                )

                self.assertEqual(outcome.kind, "transport_failed")
                self.assertEqual(outcome.provider_code, provider_code)
                self.assertFalse(self.log.exists())

    def test_workspace_write_helper_denial_is_sandbox_capability_blocked(self):
        outcome = self.launch(
            "sandbox-helper-eperm",
            request=dataclasses.replace(self.request(), sandbox="workspace-write"),
        )

        self.assertEqual(outcome.kind, "blocked")
        self.assertEqual(outcome.provider_code, "sandbox_capability_blocked")

    def test_structured_sandbox_permission_normalization_is_exact(self):
        cases = (
            ({"code": "sandbox_denied"}, "sandbox_capability_blocked"),
            (
                {"code": "EPERM", "capability": "workspace_write"},
                "sandbox_capability_blocked",
            ),
            (
                {"errno": "EACCES", "capability": "helper_socket"},
                "sandbox_capability_blocked",
            ),
            ({"code": "EPERM", "capability": "unrecognized"}, None),
            ({"message": "permission denied while writing workspace"}, None),
        )
        for error, expected in cases:
            with self.subTest(error=error):
                self.assertEqual(
                    provider_module._structured_permission_code(error),
                    expected,
                )

    def test_tcc_or_keychain_denial_is_host_permission_blocked(self):
        for scenario in ("host-tcc-denied", "host-keychain-denied"):
            with self.subTest(scenario=scenario):
                outcome = self.launch(scenario)
                self.assertEqual(outcome.kind, "blocked")
                self.assertEqual(outcome.provider_code, "host_permission_blocked")
                self.assertEqual(self.record().get("approval_events", 1), 0)

    def test_subagent_completion_does_not_replace_root_completion(self):
        outcome = self.launch("subagent-completion-only")

        self.assertEqual(outcome.kind, "transport_failed")
        self.assertEqual(outcome.provider_code, "controller_transport_failed")
        self.assertIsNone(outcome.result)
        self.assertIn("tool_finished:collaboration-1", outcome.activity_keys)

    def test_result_without_completed_root_turn_is_transport_failure(self):
        outcome = self.launch("result-without-root-turn")

        self.assertEqual(outcome.kind, "transport_failed")
        self.assertEqual(outcome.provider_code, "controller_transport_failed")
        self.assertIsNone(outcome.result)

    def test_root_and_collaboration_events_accept_one_root_final_result(self):
        reads = []

        class CountingAdapter(CodexAdapter):
            def _read_result(self, output_path):
                reads.append(output_path)
                return super()._read_result(output_path)

        adapter = CountingAdapter(
            source_env=self.environment("root-and-collaboration"),
            provider_auth_prefixes=("OPENAI_", "CODEX_"),
            remotes=("origin",),
            run_id="run-1234",
            helper=self.helper,
            poll_seconds=0.01,
        )

        outcome = adapter.launch(self.request(), RecordingLease())

        self.assertEqual(outcome.kind, "implemented")
        self.assertEqual(outcome.result["summary"], "root-final-result")
        self.assertEqual(reads, [self.output])
        self.assertIn("tool_started:collaboration-1", outcome.activity_keys)
        self.assertIn("tool_finished:collaboration-1", outcome.activity_keys)

    def test_fake_collaboration_event_uses_current_codex_wire_type(self):
        fake_source = (SKILL_ROOT / "evals" / "fake_codex.py").read_text(
            encoding="utf-8"
        )

        self.assertIn('"collab_tool_call" if collaboration', fake_source)
        self.assertNotIn('"collaboration_tool_call" if collaboration', fake_source)

    def test_only_distinct_lifecycle_and_tool_events_refresh_activity(self):
        lease = RecordingLease()
        outcome = self.launch("repeated-log", lease=lease)
        self.assertEqual(outcome.kind, "implemented")
        self.assertTrue(all(accepted for _kind, _key, accepted in lease.observed))
        self.assertEqual(len(lease.observed), 4)

    def test_process_group_observation_allows_bounded_ps_startup_jitter(self):
        observation_timeouts = []
        anchored_group = provider_module._anchored_group

        def record_observation(process, pgid, *, observation_timeout=0.25):
            observation_timeouts.append(observation_timeout)
            return anchored_group(
                process,
                pgid,
                observation_timeout=observation_timeout,
            )

        with mock.patch.object(
            provider_module,
            "_anchored_group",
            side_effect=record_observation,
        ):
            outcome = self.launch("initial")

        self.assertEqual(outcome.kind, "implemented")
        self.assertTrue(observation_timeouts)
        self.assertGreaterEqual(min(observation_timeouts), 0.25)
        self.assertLessEqual(max(observation_timeouts), 0.25)

    def test_provider_process_group_identity_is_reported_immediately(self):
        observations = []

        outcome = self.adapter().launch(
            self.request(),
            RecordingLease(),
            on_process_observation=observations.append,
        )

        self.assertEqual(outcome.kind, "implemented")
        self.assertTrue(observations)
        first = observations[0]
        self.assertEqual(set(first), {"provider_pid", "provider_pgid", "descendant_pids"})
        self.assertEqual(first["provider_pid"], first["provider_pgid"])
        self.assertGreater(first["provider_pid"], 0)
        self.assertEqual(first["descendant_pids"], [])

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
        }
        for scenario, code in cases.items():
            with self.subTest(scenario=scenario):
                outcome = self.launch(scenario)
                self.assertEqual(outcome.kind, "blocked")
                self.assertEqual(outcome.provider_code, code)
        unavailable = self.launch("unavailable")
        self.assertEqual(unavailable.kind, "transport_failed")
        self.assertEqual(unavailable.provider_code, "provider_unavailable")

    def test_top_level_and_turn_failed_auth_messages_are_stably_classified(self):
        for scenario in ("auth-message-error", "auth-turn-failed"):
            with self.subTest(scenario=scenario):
                outcome = self.launch(scenario)
                self.assertEqual(outcome.kind, "blocked")
                self.assertEqual(outcome.provider_code, "provider_auth_blocked")
                self.assertNotIn("invalid api key", outcome.stderr_tail.lower())

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

    def test_malformed_stream_and_invalid_structured_output_have_precise_codes(self):
        cases = {
            "malformed-jsonl": "provider_stream_malformed",
            "oversized-jsonl": "provider_stream_oversized",
            "invalid-output": "provider_result_invalid",
        }
        for scenario, reason in cases.items():
            with self.subTest(scenario=scenario):
                outcome = self.launch(scenario)
                self.assertEqual(outcome.kind, "failed")
                self.assertEqual(outcome.provider_code, reason)

    def test_stream_corruption_observed_while_lease_expires_beats_stall(self):
        ready = Path(str(self.log) + ".ready")

        class DelayedExpiredLease(RecordingLease):
            def expired(self, _now):
                deadline = time.monotonic() + 2
                while not ready.exists() and time.monotonic() < deadline:
                    time.sleep(0.005)
                return True

        outcome = self.launch(
            "malformed-jsonl-ready",
            lease=DelayedExpiredLease(),
        )

        self.assertEqual(outcome.kind, "failed")
        self.assertEqual(outcome.provider_code, "provider_stream_malformed")

    def test_operator_stop_explicitly_beats_observed_stream_corruption(self):
        ready = Path(str(self.log) + ".ready")

        def delayed_stop():
            deadline = time.monotonic() + 2
            while not ready.exists() and time.monotonic() < deadline:
                time.sleep(0.005)
            return True

        outcome = self.launch(
            "malformed-jsonl-ready",
            stop_requested=delayed_stop,
        )

        self.assertEqual(outcome.kind, "controller_stopped")
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
