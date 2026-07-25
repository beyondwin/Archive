from __future__ import annotations

import importlib.util
import hashlib
import io
import json
import os
import signal
import stat
import subprocess
import sys
import tempfile
import time
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
        self.assertIn(
            'exec "$PYTHON_BIN" "$SCRIPT_DIR/plan-runner-live-canary.py" \\\n'
            '  --provider "$PROVIDER" --mode "$MODE"',
            text,
        )
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

    def test_invalid_args_exit_64_before_missing_runtime(self):
        launcher = SCRIPT_DIR / "plan-runner-live-canary"
        result = subprocess.run(
            ["/bin/sh", str(launcher), "--provider", "bogus", "--mode", "session"],
            cwd="/tmp",
            env={"PATH": "/usr/bin:/bin"},
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 64)
        lines = result.stdout.splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])["reason_code"], "invalid_invocation")

    def test_missing_runtime_emits_one_blocked_line_per_requested_probe(self):
        launcher = SCRIPT_DIR / "plan-runner-live-canary"
        result = subprocess.run(
            ["/bin/sh", str(launcher), "--provider", "all", "--mode", "all"],
            cwd="/tmp",
            env={"PATH": "/usr/bin:/bin"},
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 3)
        values = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(
            {(item["provider"], item["mode"]) for item in values},
            {
                ("codex", "session"),
                ("codex", "runner"),
                ("claude", "session"),
                ("claude", "runner"),
            },
        )
        self.assertTrue(all(item["reason_code"] == "runtime_missing" for item in values))

    def test_valid_preparsed_args_reach_managed_interpreter(self):
        launcher = SCRIPT_DIR / "plan-runner-live-canary"
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            capture = root / "argv.json"
            uv_capture = root / "uv-install-dir.txt"
            interpreter = root / "managed/uv/python/cpython-3.13-test/bin/python3.13"
            interpreter.parent.mkdir(parents=True)
            interpreter.write_text(
                "#!/bin/sh\n"
                "script=$1\n"
                "shift\n"
                "printf '%s\\n' \"$script\" \"$@\" > \"$CANARY_ARGV_CAPTURE\"\n"
                "printf '%s\\n' \"$UV_PYTHON_INSTALL_DIR\" > \"$CANARY_UV_CAPTURE\"\n",
                encoding="utf-8",
            )
            interpreter.chmod(0o755)
            uv = root / "uv"
            uv.write_text(
                "#!/bin/sh\n"
                "if [ \"$1\" = python ] && [ \"$2\" = find ]; then\n"
                "  printf '%s\\n' \"$FAKE_MANAGED_PYTHON\"\n"
                "  exit 0\n"
                "fi\n"
                "exit 1\n",
                encoding="utf-8",
            )
            uv.chmod(0o755)
            result = subprocess.run(
                [
                    "/bin/sh",
                    str(launcher),
                    "--provider",
                    "codex",
                    "--mode",
                    "session",
                ],
                cwd="/tmp",
                env={
                    "PATH": f"{root}:/usr/bin:/bin",
                    "FAKE_MANAGED_PYTHON": str(interpreter),
                    "CANARY_ARGV_CAPTURE": str(capture),
                    "CANARY_UV_CAPTURE": str(uv_capture),
                },
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                capture.read_text(encoding="utf-8").splitlines(),
                [
                    str(SCRIPT_DIR / "plan-runner-live-canary.py"),
                    "--provider",
                    "codex",
                    "--mode",
                    "session",
                ],
            )
            self.assertEqual(
                uv_capture.read_text(encoding="utf-8").strip(),
                str(root / "managed/uv/python"),
            )


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

    def test_controller_exception_cleans_and_reaps_process_group(self):
        process = mock.Mock()
        process.pid = 654
        process.communicate.side_effect = [KeyboardInterrupt(), ("", "")]
        process.returncode = -signal.SIGTERM
        with (
            mock.patch.object(canary.subprocess, "Popen", return_value=process),
            mock.patch.object(canary.os, "killpg") as killpg,
        ):
            with self.assertRaises(KeyboardInterrupt):
                canary.run_bounded(["provider"], cwd=Path("/tmp"), timeout=10)
        killpg.assert_called_once_with(654, signal.SIGTERM)
        self.assertEqual(process.communicate.call_count, 2)

    def test_deadline_leaves_no_running_descendant_in_process_group(self):
        child_code = (
            "import signal,time;"
            "signal.signal(signal.SIGTERM,signal.SIG_IGN);"
            "time.sleep(30)"
        )
        leader_code = (
            "import signal,subprocess,sys,time;"
            f"child=subprocess.Popen([sys.executable,'-c',{child_code!r}]);"
            "print(child.pid,flush=True);"
            "signal.signal(signal.SIGTERM,signal.SIG_IGN);"
            "time.sleep(30)"
        )
        result = canary.run_bounded(
            [sys.executable, "-c", leader_code],
            cwd=Path("/tmp"),
            timeout=0.1,
        )
        self.assertTrue(result.timed_out)
        descendant = int(result.stdout.splitlines()[0])
        deadline = time.monotonic() + 2
        state = ""
        while time.monotonic() < deadline:
            observed = subprocess.run(
                ["/bin/ps", "-p", str(descendant), "-o", "stat="],
                text=True,
                capture_output=True,
                check=False,
            )
            state = observed.stdout.strip()
            if not state or state.startswith("Z"):
                break
            time.sleep(0.02)
        self.assertTrue(not state or state.startswith("Z"), state)

    def test_command_installs_and_restores_sigint_sigterm_handlers(self):
        process = mock.Mock()
        process.pid = 777
        process.communicate.return_value = ("", "")
        process.returncode = 0
        with (
            mock.patch.object(canary.subprocess, "Popen", return_value=process),
            mock.patch.object(canary.signal, "getsignal", return_value="old"),
            mock.patch.object(canary.signal, "signal") as install,
        ):
            canary.run_bounded(["provider"], cwd=Path("/tmp"), timeout=10)
        installed = [call.args[0] for call in install.call_args_list[:2]]
        restored = install.call_args_list[-2:]
        self.assertEqual(installed, [signal.SIGINT, signal.SIGTERM])
        self.assertEqual(
            restored,
            [mock.call(signal.SIGINT, "old"), mock.call(signal.SIGTERM, "old")],
        )

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

    def test_structured_runtime_missing_is_blocked_before_stderr_fallback(self):
        raw = json.dumps(
            {"type": "error", "error": {"code": "runtime_missing"}}
        ) + "\n"
        parsed = canary.parse_codex_stream(raw)
        outcome = canary.classify_provider_result(
            canary.CommandResult(3, raw, "unrelated failure", False), parsed
        )
        self.assertEqual(outcome, ("blocked", "runtime_missing"))

    def test_runner_structured_blocked_summary_wins_over_stderr(self):
        outcome = canary.classify_runner_summary(
            3,
            {"status": "blocked", "reason_code": "provider_auth_blocked"},
            "unparseable diagnostic",
        )
        self.assertEqual(outcome, ("blocked", "provider_auth_blocked"))

    def test_runner_blocked_state_refines_structured_reason(self):
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw)
            run_id = "plan-" + str(uuid.uuid4())
            root = home / ".codex/plan-runner" / run_id
            root.mkdir(parents=True)
            (root / "state.json").write_text(
                json.dumps(
                    {
                        "status": "blocked",
                        "failure": {"reason_code": "provider_auth_blocked"},
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(
                canary.blocked_runner_reason(home, "codex", run_id),
                "provider_auth_blocked",
            )


class IsolationTests(unittest.TestCase):
    def test_codex_auth_is_copied_to_private_disposable_home_only(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            operator = root / "operator"
            isolated = root / "isolated"
            (operator / ".codex").mkdir(parents=True)
            auth = operator / ".codex/auth.json"
            auth.write_text('{"token":"secret"}', encoding="utf-8")
            auth.chmod(0o600)
            env = canary.isolated_provider_environment(
                "codex",
                isolated,
                operator_home=operator,
                source_env={"PATH": "/usr/bin:/bin", "OPENAI_API_KEY": "env-secret"},
            )
            copied = isolated / ".codex/auth.json"
            self.assertEqual(env["HOME"], str(isolated))
            self.assertEqual(env["CODEX_HOME"], str(isolated / ".codex"))
            self.assertEqual(copied.read_text(encoding="utf-8"), '{"token":"secret"}')
            self.assertEqual(stat.S_IMODE(copied.stat().st_mode), 0o600)
            self.assertEqual(auth.read_text(encoding="utf-8"), '{"token":"secret"}')
            self.assertFalse((isolated / ".codex/history.jsonl").exists())

    def test_claude_uses_empty_disposable_config_and_preserves_env_auth(self):
        with tempfile.TemporaryDirectory() as raw:
            isolated = Path(raw) / "isolated"
            env = canary.isolated_provider_environment(
                "claude",
                isolated,
                operator_home=Path(raw) / "operator",
                source_env={
                    "PATH": "/usr/bin:/bin",
                    "ANTHROPIC_API_KEY": "env-secret",
                },
            )
            config = isolated / ".claude"
            self.assertEqual(env["HOME"], str(isolated))
            self.assertEqual(env["CLAUDE_CONFIG_DIR"], str(config))
            self.assertEqual(env["ANTHROPIC_API_KEY"], "env-secret")
            self.assertEqual(list(config.iterdir()), [])

    def test_claude_without_isolated_env_auth_blocks_before_provider_session(self):
        with (
            mock.patch.object(
                canary,
                "isolated_provider_environment",
                return_value={"HOME": "/private/tmp/isolated"},
            ),
            mock.patch.object(
                canary,
                "_provider_version",
                return_value=("2.1.206 (Claude Code)", None),
            ),
            mock.patch.object(
                canary, "claude_auth_available", return_value=False, create=True
            ),
            mock.patch.object(canary, "_create_repository") as create_repository,
            mock.patch.object(
                canary,
                "_probe_claude_session",
                return_value=("passed", None, "fresh_then_resume"),
            ) as provider_session,
        ):
            result = canary.probe_session("claude")
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason_code"], "provider_auth_blocked")
        self.assertEqual(result["session_action"], "not_started")
        create_repository.assert_not_called()
        provider_session.assert_not_called()

    def test_runner_resolves_temporary_symlink_before_workspace_creation(self):
        with tempfile.TemporaryDirectory() as raw:
            real = Path(raw) / "real"
            real.mkdir()
            alias = Path(raw) / "alias"
            alias.symlink_to(real, target_is_directory=True)
            expected_workspace = real.resolve(strict=True) / "source"
            temporary = mock.MagicMock()
            temporary.return_value.__enter__.return_value = str(alias)
            temporary.return_value.__exit__.return_value = False
            with (
                mock.patch.object(canary.tempfile, "TemporaryDirectory", temporary),
                mock.patch.object(canary, "_runner_environment", return_value={}),
                mock.patch.object(
                    canary,
                    "_provider_version",
                    return_value=("codex-cli test", None),
                ),
                mock.patch.object(
                    canary,
                    "_create_repository",
                    side_effect=canary.CanaryError("runner_probe_failed"),
                ) as create_repository,
            ):
                canary.probe_runner("codex")
        self.assertEqual(
            create_repository.call_args.args[0],
            expected_workspace,
        )

    def test_claude_runner_without_isolated_auth_blocks_before_repository(self):
        with (
            mock.patch.object(canary, "_runner_environment", return_value={}),
            mock.patch.object(
                canary,
                "_provider_version",
                return_value=("2.1.206 (Claude Code)", None),
            ),
            mock.patch.object(canary, "claude_auth_available", return_value=False),
            mock.patch.object(canary, "_create_repository") as create_repository,
            mock.patch.object(
                canary,
                "run_bounded",
                return_value=canary.CommandResult(1, "", "", False),
            ),
        ):
            result = canary.probe_runner("claude")
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason_code"], "provider_auth_blocked")
        self.assertEqual(result["session_action"], "not_started")
        create_repository.assert_not_called()


class SessionAndRunnerOutcomeTests(unittest.TestCase):
    def _assert_launcher_accepts_scenario_mode(self, mode):
        launcher = SCRIPT_DIR / "plan-runner-live-canary"
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            capture = root / "argv.json"
            interpreter = root / "managed/uv/python/cpython-3.13-test/bin/python3.13"
            interpreter.parent.mkdir(parents=True)
            interpreter.write_text(
                "#!/bin/sh\n"
                "shift\n"
                "printf '%s\\n' \"$@\" > \"$CANARY_ARGV_CAPTURE\"\n",
                encoding="utf-8",
            )
            interpreter.chmod(0o755)
            uv = root / "uv"
            uv.write_text(
                "#!/bin/sh\n"
                "if [ \"$1\" = python ] && [ \"$2\" = find ]; then\n"
                "  printf '%s\\n' \"$FAKE_MANAGED_PYTHON\"\n"
                "  exit 0\n"
                "fi\n"
                "exit 1\n",
                encoding="utf-8",
            )
            uv.chmod(0o755)
            result = subprocess.run(
                [
                    "/bin/sh",
                    str(launcher),
                    "--provider",
                    "all",
                    "--mode",
                    mode,
                ],
                cwd="/tmp",
                env={
                    "PATH": f"{root}:/usr/bin:/bin",
                    "FAKE_MANAGED_PYTHON": str(interpreter),
                    "CANARY_ARGV_CAPTURE": str(capture),
                },
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(
                capture.read_text(encoding="utf-8").splitlines(),
                ["--provider", "all", "--mode", mode],
            )

    @staticmethod
    def _ownership_scenario():
        first_head = "b" * 40
        final_head = "c" * 40
        first_set = {
            "digest": "1" * 64,
            "candidate_head": first_head,
            "commands": [
                {
                    "argv": ["/usr/bin/true"],
                    "cwd": ".",
                    "input_digest": "a" * 64,
                    "deadline_seconds": 30,
                }
            ],
        }
        second_set = {
            "digest": "2" * 64,
            "candidate_head": final_head,
            "commands": [
                {
                    "argv": ["/usr/bin/true"],
                    "cwd": ".",
                    "input_digest": "a" * 64,
                    "deadline_seconds": 30,
                },
                {
                    "argv": ["/usr/bin/false", "--version"],
                    "cwd": ".",
                    "input_digest": "b" * 64,
                    "deadline_seconds": 30,
                },
            ],
        }
        return {
            "plan_labels": [
                ["Task 1", "Task 2"],
                ["Task 1", "Task 2"],
            ],
            "source_head": "a" * 40,
            "observed_head": final_head,
            "porcelain": "",
            "prior_handoff_is_ancestor": True,
            "state": {
                "format_version": 2,
                "contract_version": 2,
                "status": "ready_for_integration",
                "integration": "not_observed",
                "plans": [
                    {
                        "status": "implemented",
                        "handoff_digest": "3" * 64,
                    },
                    {
                        "status": "implemented",
                        "handoff_digest": "4" * 64,
                    },
                ],
                "sessions": [
                    {
                        "mode": "implementation",
                        "plan_index": 0,
                        "session_id": "session-a",
                        "health": "healthy",
                    },
                    {
                        "mode": "implementation",
                        "plan_index": 1,
                        "session_id": "session-b",
                        "health": "healthy",
                    },
                ],
                "failure": None,
            },
            "plan_handoffs": [
                {
                    "digest": "3" * 64,
                    "plan_index": 0,
                    "head_commit": first_head,
                    "verification_set_digest": first_set["digest"],
                },
                {
                    "digest": "4" * 64,
                    "plan_index": 1,
                    "head_commit": final_head,
                    "verification_set_digest": "5" * 64,
                },
            ],
            "plan_verification_sets": [first_set, second_set],
            "run_verification_set": {
                "digest": "5" * 64,
                "candidate_head": final_head,
                "plan_set_digests": [
                    first_set["digest"],
                    second_set["digest"],
                ],
                "commands": [
                    first_set["commands"][0],
                    second_set["commands"][1],
                ],
            },
            "verification_receipts": [
                {
                    "candidate_head": final_head,
                    "command": first_set["commands"][0],
                    "outcome": "success",
                    "exit_code": 0,
                },
                {
                    "candidate_head": final_head,
                    "command": second_set["commands"][1],
                    "outcome": "success",
                    "exit_code": 0,
                },
            ],
        }

    def test_multi_plan_ownership_scenario(self):
        self._assert_launcher_accepts_scenario_mode("ownership")
        evidence = self._ownership_scenario()
        self.assertEqual(
            canary.validate_multi_plan_ownership_scenario(evidence),
            (True, None, "c" * 40),
        )

        mutations = {
            "same labels": lambda value: value["plan_labels"][1].append("Task 3"),
            "distinct commits": lambda value: value["plan_handoffs"][1].update(
                head_commit="b" * 40
            ),
            "fresh sessions": lambda value: value["state"]["sessions"][1].update(
                session_id="session-a"
            ),
            "ancestry": lambda value: value.update(
                prior_handoff_is_ancestor=False
            ),
            "no workflow state": lambda value: value["state"].update(
                finalization={}
            ),
            "exact run union": lambda value: value[
                "run_verification_set"
            ]["commands"].reverse(),
            "handoff head": lambda value: value["plan_handoffs"][1].update(
                head_commit="d" * 40
            ),
            "clean head": lambda value: value.update(porcelain=" M partial.txt"),
            "receipt binding": lambda value: value[
                "verification_receipts"
            ].pop(),
            "integration": lambda value: value["state"].update(
                integration="merged"
            ),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                changed = json.loads(json.dumps(evidence))
                mutate(changed)
                valid, reason, _head = (
                    canary.validate_multi_plan_ownership_scenario(changed)
                )
                self.assertFalse(valid)
                self.assertIsInstance(reason, str)

        providers = []

        def fake_probe(provider):
            providers.append(provider)
            valid, reason, head = canary.validate_multi_plan_ownership_scenario(
                self._ownership_scenario()
            )
            self.assertTrue(valid, reason)
            return canary.normalized_result(
                provider=provider,
                mode="ownership",
                status="passed",
                provider_version=f"{provider}-test",
                session_action="two_fresh_plan_sessions",
                final_head=head,
                elapsed=0,
            )

        with (
            mock.patch.object(canary, "require_runtime"),
            mock.patch.object(
                canary, "probe_runner", side_effect=fake_probe
            ),
            mock.patch("sys.stdout", new_callable=io.StringIO) as output,
        ):
            code = canary.main(
                ["--provider", "all", "--mode", "ownership"]
            )
        self.assertEqual(code, 0)
        self.assertEqual(providers, ["codex", "claude"])
        values = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(
            [(value["provider"], value["mode"]) for value in values],
            [("codex", "ownership"), ("claude", "ownership")],
        )

    def test_interruption_resume_scenario(self):
        self._assert_launcher_accepts_scenario_mode("interruption")
        checkpoint = {
            "head": "b" * 40,
            "branch": "codex-plan/canary",
            "porcelain_digest": "6" * 64,
            "tree_digest": "7" * 64,
            "clean": False,
        }
        evidence = {
            "sigint_sent": True,
            "provider_process_group_quiescent": True,
            "interrupted_status": "resumable",
            "interrupted_checkpoint": checkpoint,
            "resume_checkpoint": dict(checkpoint),
            "recorded_session": {
                "session_id": "healthy-session",
                "health": "healthy",
                "plan_index": 1,
            },
            "resume_session_id": "healthy-session",
            "completed_first_handoff_before": "3" * 64,
            "completed_first_handoff_after": "3" * 64,
            "first_plan_session_count_before": 1,
            "first_plan_session_count_after": 1,
            "final_ownership": self._ownership_scenario(),
            "drift_rejected": True,
            "drift_reason_code": "dirty_checkpoint_drift",
            "provider_launch_count_before_drift": 3,
            "provider_launch_count_after_drift": 3,
        }
        self.assertEqual(
            canary.validate_interruption_resume_scenario(evidence),
            (True, None, "c" * 40),
        )

        mutations = {
            "no SIGINT": lambda value: value.update(sigint_sent=False),
            "live process group": lambda value: value.update(
                provider_process_group_quiescent=False
            ),
            "not resumable": lambda value: value.update(
                interrupted_status="failed"
            ),
            "checkpoint changed": lambda value: value[
                "resume_checkpoint"
            ].update(tree_digest="8" * 64),
            "unhealthy session": lambda value: value[
                "recorded_session"
            ].update(health="failed"),
            "wrong resume": lambda value: value.update(
                resume_session_id="new-session"
            ),
            "replayed first task": lambda value: value.update(
                first_plan_session_count_after=2
            ),
            "handoff replaced": lambda value: value.update(
                completed_first_handoff_after="9" * 64
            ),
            "drift accepted": lambda value: value.update(drift_rejected=False),
            "provider relaunched": lambda value: value.update(
                provider_launch_count_after_drift=4
            ),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                changed = json.loads(json.dumps(evidence))
                mutate(changed)
                valid, reason, _head = (
                    canary.validate_interruption_resume_scenario(changed)
                )
                self.assertFalse(valid)
                self.assertIsInstance(reason, str)

        providers = []

        def fake_probe(provider):
            providers.append(provider)
            valid, reason, head = canary.validate_interruption_resume_scenario(
                evidence
            )
            self.assertTrue(valid, reason)
            return canary.normalized_result(
                provider=provider,
                mode="interruption",
                status="passed",
                provider_version=f"{provider}-test",
                session_action="sigint_then_recorded_resume",
                final_head=head,
                elapsed=0,
            )

        with (
            mock.patch.object(canary, "require_runtime"),
            mock.patch.object(
                canary, "probe_session", side_effect=fake_probe
            ),
            mock.patch("sys.stdout", new_callable=io.StringIO) as output,
        ):
            code = canary.main(
                ["--provider", "all", "--mode", "interruption"]
            )
        self.assertEqual(code, 0)
        self.assertEqual(providers, ["codex", "claude"])
        values = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(
            [(value["provider"], value["mode"]) for value in values],
            [("codex", "interruption"), ("claude", "interruption")],
        )

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

    def _sealed_evidence(self, root: Path):
        run_root = root / "run"
        worktree = root / "worktree"
        run_root.mkdir()
        worktree.mkdir()
        executable = root / "verify"
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(0o755)
        executable = executable.resolve()
        candidate = "f" * 40
        command = {
            "command_id": "final-1",
            "command_role": "final",
            "argv": [str(executable), "--check"],
            "cwd": ".",
            "input_digest": "a" * 64,
            "deadline_seconds": 30,
        }
        final_set = {
            "kind": "commands",
            "candidate_head": candidate,
            "commands": [command],
        }
        identity = {
            "argv": command["argv"],
            "candidate_head": candidate,
            "command_role": "final",
            "cwd": str(worktree.resolve()),
            "environment_fingerprint": "b" * 64,
            "executable_identity": {
                "path": str(executable),
                "sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
                "mode": executable.stat().st_mode,
                "size": executable.stat().st_size,
            },
            "input_digest": command["input_digest"],
            "worktree_digest": "c" * 64,
        }
        receipt = {
            "schema_version": 1,
            "identity": identity,
            "identity_digest": hashlib.sha256(
                json.dumps(
                    identity, sort_keys=True, separators=(",", ":")
                ).encode()
            ).hexdigest(),
            "outcome": "success",
            "exit_code": 0,
            "stdout_tail": "",
            "stderr_tail": "",
            "process": {},
        }
        documents = {
            "final_verification_set": final_set,
            "verification_receipt": receipt,
        }
        refs = {}
        for kind, value in documents.items():
            raw_value = json.dumps(
                value, sort_keys=True, separators=(",", ":")
            ).encode()
            digest = hashlib.sha256(raw_value).hexdigest()
            relative = Path("artifacts") / kind / f"{digest}.json"
            path = run_root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw_value)
            refs[kind] = {
                "kind": kind,
                "digest": digest,
                "relative_path": str(relative),
            }
        review = {
            "status": "reviewed",
            "candidate_head": candidate,
            "review_head": candidate,
            "verification_set_digest": refs["final_verification_set"]["digest"],
            "open_findings": [],
            "open_obligation_ids": [],
        }
        handoff = {
            "status": "ready_for_integration",
            "candidate_head": candidate,
            "review_head": candidate,
            "verification_set_digest": refs["final_verification_set"]["digest"],
            "review_receipt": None,
            "verification_receipts": [refs["verification_receipt"]],
            "integration": "not_observed",
        }
        for kind, value in (
            ("final_review_receipt", review),
            ("branch_handoff", handoff),
        ):
            raw_value = json.dumps(
                value, sort_keys=True, separators=(",", ":")
            ).encode()
            digest = hashlib.sha256(raw_value).hexdigest()
            relative = Path("artifacts") / kind / f"{digest}.json"
            path = run_root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw_value)
            refs[kind] = {
                "kind": kind,
                "digest": digest,
                "relative_path": str(relative),
            }
        handoff["review_receipt"] = refs["final_review_receipt"]
        raw_handoff = json.dumps(
            handoff, sort_keys=True, separators=(",", ":")
        ).encode()
        old_handoff = run_root / refs["branch_handoff"]["relative_path"]
        old_handoff.unlink()
        digest = hashlib.sha256(raw_handoff).hexdigest()
        relative = Path("artifacts/branch_handoff") / f"{digest}.json"
        (run_root / relative).write_bytes(raw_handoff)
        refs["branch_handoff"] = {
            "kind": "branch_handoff",
            "digest": digest,
            "relative_path": str(relative),
        }
        state = {
            "artifact_refs": [
                refs["final_verification_set"],
                refs["verification_receipt"],
                refs["final_review_receipt"],
                refs["branch_handoff"],
            ],
            "finalization": {
                "candidate_head": candidate,
                "review_head": candidate,
                "verification_set_digest": refs["final_verification_set"]["digest"],
            },
        }
        return run_root, worktree, candidate, state, refs

    def test_artifacts_require_exact_command_receipt_binding(self):
        with tempfile.TemporaryDirectory() as raw:
            run_root, worktree, candidate, state, _refs = self._sealed_evidence(
                Path(raw)
            )
            valid, reason = canary.validate_runner_artifacts(
                state, run_root, worktree, candidate
            )
            self.assertTrue(valid, reason)

    def test_artifacts_reject_duplicate_receipt_reference(self):
        with tempfile.TemporaryDirectory() as raw:
            run_root, worktree, candidate, state, refs = self._sealed_evidence(
                Path(raw)
            )
            state["artifact_refs"].append(refs["verification_receipt"])
            valid, reason = canary.validate_runner_artifacts(
                state, run_root, worktree, candidate
            )
            self.assertFalse(valid)
            self.assertEqual(reason, "verification_receipt_duplicate")

    def test_artifacts_reject_finalization_set_digest_mismatch(self):
        with tempfile.TemporaryDirectory() as raw:
            run_root, worktree, candidate, state, _refs = self._sealed_evidence(
                Path(raw)
            )
            state["finalization"]["verification_set_digest"] = "0" * 64
            valid, reason = canary.validate_runner_artifacts(
                state, run_root, worktree, candidate
            )
            self.assertFalse(valid)
            self.assertEqual(reason, "verification_set_invalid")

    def test_artifacts_reject_changed_executable_identity(self):
        with tempfile.TemporaryDirectory() as raw:
            run_root, worktree, candidate, state, refs = self._sealed_evidence(
                Path(raw)
            )
            receipt = json.loads(
                (run_root / refs["verification_receipt"]["relative_path"]).read_text()
            )
            Path(receipt["identity"]["executable_identity"]["path"]).write_text(
                "#!/bin/sh\nexit 1\n", encoding="utf-8"
            )
            valid, reason = canary.validate_runner_artifacts(
                state, run_root, worktree, candidate
            )
            self.assertFalse(valid)
            self.assertEqual(reason, "verification_receipt_invalid")

    def test_artifacts_reject_command_argv_mismatch(self):
        with tempfile.TemporaryDirectory() as raw:
            run_root, worktree, candidate, state, refs = self._sealed_evidence(
                Path(raw)
            )
            receipt_path = run_root / refs["verification_receipt"]["relative_path"]
            receipt = json.loads(receipt_path.read_text())
            receipt["identity"]["argv"] = ["/bin/false"]
            receipt["identity_digest"] = hashlib.sha256(
                json.dumps(
                    receipt["identity"], sort_keys=True, separators=(",", ":")
                ).encode()
            ).hexdigest()
            raw_receipt = json.dumps(
                receipt, sort_keys=True, separators=(",", ":")
            ).encode()
            receipt_path.unlink()
            receipt_digest = hashlib.sha256(raw_receipt).hexdigest()
            receipt_relative = (
                Path("artifacts/verification_receipt")
                / f"{receipt_digest}.json"
            )
            (run_root / receipt_relative).write_bytes(raw_receipt)
            old_ref = refs["verification_receipt"]
            new_ref = {
                "kind": "verification_receipt",
                "digest": receipt_digest,
                "relative_path": str(receipt_relative),
            }
            state["artifact_refs"][
                state["artifact_refs"].index(old_ref)
            ] = new_ref
            handoff_ref = refs["branch_handoff"]
            handoff_path = run_root / handoff_ref["relative_path"]
            handoff = json.loads(handoff_path.read_text())
            handoff["verification_receipts"] = [new_ref]
            handoff_path.unlink()
            raw_handoff = json.dumps(
                handoff, sort_keys=True, separators=(",", ":")
            ).encode()
            handoff_digest = hashlib.sha256(raw_handoff).hexdigest()
            handoff_relative = (
                Path("artifacts/branch_handoff") / f"{handoff_digest}.json"
            )
            (run_root / handoff_relative).write_bytes(raw_handoff)
            state["artifact_refs"][
                state["artifact_refs"].index(handoff_ref)
            ] = {
                "kind": "branch_handoff",
                "digest": handoff_digest,
                "relative_path": str(handoff_relative),
            }
            valid, reason = canary.validate_runner_artifacts(
                state, run_root, worktree, candidate
            )
            self.assertFalse(valid)
            self.assertEqual(reason, "verification_receipt_identity_mismatch")

    def test_failed_runner_preserves_sanitized_state_evidence_before_cleanup(self):
        run_id = "plan-observability"

        def failed_runner(argv, *, cwd, timeout, env, input_text=None):
            state_root = Path(env["HOME"]) / ".codex" / "plan-runner" / run_id
            state_root.mkdir(parents=True)
            (state_root / "state.json").write_text(
                json.dumps(
                    {
                        "run_id": run_id,
                        "status": "failed",
                        "revision": 7,
                        "plans": [
                            {"status": "implemented"},
                            {"status": "running"},
                        ],
                        "sessions": [{"mode": "implementation"}],
                        "artifact_refs": [
                            {"kind": "receipt"},
                            {"kind": "checkpoint"},
                        ],
                        "failure": {
                            "reason_code": "provider_command_failed",
                            "detail": "SECRET prompt and raw provider stream",
                        },
                    }
                ),
                encoding="utf-8",
            )
            return canary.CommandResult(
                4,
                json.dumps({"run_id": run_id, "status": "failed"}) + "\n",
                "",
                False,
            )

        with (
            mock.patch.object(
                canary,
                "_runner_environment",
                side_effect=lambda provider, home: {"HOME": str(home)},
            ),
            mock.patch.object(
                canary,
                "_provider_version",
                return_value=("codex-cli test", None),
            ),
            mock.patch.object(canary, "_create_repository"),
            mock.patch.object(canary, "run_bounded", side_effect=failed_runner),
        ):
            result = canary.probe_runner("codex")

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["reason_code"], "provider_command_failed")
        self.assertEqual(
            result["failure_evidence"],
            {
                "artifact_count": 2,
                "implemented_plan_count": 1,
                "plan_count": 2,
                "reason_code": "provider_command_failed",
                "receipt_count": 1,
                "revision": 7,
                "runner_status": "failed",
                "session_count": 1,
                "state_sha256": mock.ANY,
            },
        )
        self.assertRegex(
            result["failure_evidence"]["state_sha256"], r"^[0-9a-f]{64}$"
        )
        serialized = json.dumps(result, sort_keys=True)
        for forbidden in ("SECRET", "prompt", "raw provider stream"):
            self.assertNotIn(forbidden, serialized)

    def test_failure_evidence_never_echoes_unknown_reason_text(self):
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw)
            run_id = "plan-unknown-reason"
            state_root = home / ".codex" / "plan-runner" / run_id
            state_root.mkdir(parents=True)
            (state_root / "state.json").write_text(
                json.dumps(
                    {
                        "status": "failed",
                        "failure": {
                            "reason_code": "SECRET prompt raw provider stream"
                        },
                    }
                ),
                encoding="utf-8",
            )
            evidence = canary.runner_failure_evidence(home, "codex", run_id)
        self.assertIsNotNone(evidence)
        self.assertEqual(
            evidence["reason_code"], "unknown_provider_stage_failure"
        )
        self.assertNotIn("secret", json.dumps(evidence).lower())

    def test_failure_evidence_rejects_symlink_state(self):
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw)
            run_id = "plan-symlink-state"
            state_root = home / ".codex" / "plan-runner" / run_id
            state_root.mkdir(parents=True)
            target = state_root / "real-state.json"
            target.write_text(
                json.dumps({"status": "failed"}),
                encoding="utf-8",
            )
            (state_root / "state.json").symlink_to(target)
            evidence = canary.runner_failure_evidence(home, "codex", run_id)
        self.assertIsNone(evidence)

    def test_failure_evidence_rejects_oversized_state_before_read(self):
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw)
            run_id = "plan-oversized-state"
            state_root = home / ".codex" / "plan-runner" / run_id
            state_root.mkdir(parents=True)
            (state_root / "state.json").write_bytes(
                b"x" * (canary.STREAM_LIMIT + 1)
            )
            with mock.patch.object(
                canary.os,
                "read",
                side_effect=AssertionError("oversized state must not be read"),
            ):
                evidence = canary.runner_failure_evidence(home, "codex", run_id)
        self.assertIsNone(evidence)

    def test_failure_evidence_rejects_path_swap_after_fd_open(self):
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw)
            run_id = "plan-swapped-state"
            state_root = home / ".codex" / "plan-runner" / run_id
            state_root.mkdir(parents=True)
            state_path = state_root / "state.json"
            payload = json.dumps(
                {
                    "status": "failed",
                    "failure": {"reason_code": "provider_command_failed"},
                }
            ).encode()
            state_path.write_bytes(payload)
            replaced = state_root / "opened-state.json"
            original_read = os.read
            swapped = False

            def swap_then_read(descriptor, size):
                nonlocal swapped
                if not swapped:
                    swapped = True
                    state_path.replace(replaced)
                    state_path.write_bytes(payload)
                return original_read(descriptor, size)

            with mock.patch.object(canary.os, "read", side_effect=swap_then_read):
                evidence = canary.runner_failure_evidence(home, "codex", run_id)
        self.assertTrue(swapped)
        self.assertIsNone(evidence)

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
