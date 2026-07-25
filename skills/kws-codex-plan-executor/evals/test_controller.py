"""Focused contract tests for the thin Codex controller adapter."""

from __future__ import annotations

import contextlib
import fcntl
import io
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from cpe_runtime.controller import (
    CodexController,
    ControllerOutcome,
    ControllerRequest,
)
from cpe_runtime.state import GitIdentity, RunLock


SESSION_ID = "11111111-1111-4111-8111-111111111111"
MAX_JSONL_LINE_BYTES = 1_048_576
MAX_TERMINAL_ENVELOPE_BYTES = 65_536
MAX_LIVE_OUTPUT_BYTES = 65_536


class ControllerContractTests(unittest.TestCase):
    """The adapter owns process transport, not Superpowers semantics."""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary_directory.name)
        self.worktree = self.base / "worktree"
        self.worktree.mkdir()
        self.git_common_dir = self.base / "git-common"
        self.git_common_dir.mkdir()
        self.schema_path = self.base / "terminal-envelope.schema.json"
        self.schema_path.write_text("{}\n", encoding="utf-8")
        self.fake_codex = Path(__file__).with_name("fake_codex.py").resolve()
        self.run_lock = RunLock(self.base / "run.lock")
        self.run_lock.__enter__()

    def tearDown(self) -> None:
        self.run_lock.__exit__(None, None, None)
        self.temporary_directory.cleanup()

    def request(
        self,
        *,
        session_id: str | None = None,
        prompt: str = "Execute the approved plan.",
    ) -> ControllerRequest:
        return ControllerRequest(
            mode="initial" if session_id is None else "resume",
            worktree=self.worktree,
            git_common_dir=self.git_common_dir,
            sandbox="workspace-write",
            prompt=prompt,
            schema_path=self.schema_path,
            session_id=session_id,
            generation=0,
            git_identity=GitIdentity(
                author_name="CPE Canary",
                author_email="cpe@example.invalid",
                committer_name="CPE Committer",
                committer_email="committer@example.invalid",
            ),
            lock_fd=self.run_lock.fileno(),
        )

    def launch_captured(
        self,
        controller: CodexController,
        request: ControllerRequest,
        *,
        scenario: str | None = None,
        environment: dict[str, str] | None = None,
        on_session_id=None,
        on_process_started=None,
    ) -> tuple[ControllerOutcome, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        additions = dict(environment or {})
        if scenario is not None:
            additions["CPE_FAKE_SCENARIO"] = scenario
        with (
            mock.patch.dict(os.environ, additions, clear=False),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            outcome = controller.launch(
                request,
                on_session_id=on_session_id or (lambda _session_id: None),
                on_process_started=on_process_started or (lambda _pid, _group: None),
            )
        return outcome, stdout.getvalue(), stderr.getvalue()

    def launch_fake(
        self,
        *,
        scenario: str,
        on_session_id=None,
        on_process_started=None,
        environment: dict[str, str] | None = None,
    ) -> ControllerOutcome:
        outcome, _, _ = self.launch_captured(
            CodexController(executable=str(self.fake_codex)),
            self.request(),
            scenario=scenario,
            environment=environment,
            on_session_id=on_session_id,
            on_process_started=on_process_started,
        )
        return outcome

    def write_provider(self, name: str, source: str) -> Path:
        provider = self.base / name
        provider.write_text(
            "#!/usr/bin/env python3\n" + source,
            encoding="utf-8",
        )
        provider.chmod(0o755)
        return provider

    def controller_helper(self, name: str) -> Path:
        scripts = Path(__file__).resolve().parents[1] / "scripts"
        return self.write_provider(
            name,
            """
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, %r)

from cpe_runtime.controller import CodexController, ControllerRequest
from cpe_runtime.state import GitIdentity, RunLock

base = Path(os.environ["CPE_HELPER_BASE"])
prompt = Path(os.environ["CPE_HELPER_PROMPT"]).read_text(encoding="utf-8")
result_path = Path(os.environ["CPE_HELPER_RESULT"])
started_path = Path(os.environ["CPE_HELPER_STARTED"])
session_path = Path(os.environ["CPE_HELPER_SESSION"])

with RunLock(Path(os.environ["CPE_HELPER_LOCK"])) as lock:
    request = ControllerRequest(
        mode="initial",
        worktree=Path(os.environ["CPE_HELPER_WORKTREE"]),
        git_common_dir=Path(os.environ["CPE_HELPER_GIT_COMMON"]),
        sandbox="workspace-write",
        prompt=prompt,
        schema_path=Path(os.environ["CPE_HELPER_SCHEMA"]),
        session_id=None,
        generation=0,
        git_identity=GitIdentity(
            author_name="CPE Canary",
            author_email="cpe@example.invalid",
            committer_name="CPE Committer",
            committer_email="committer@example.invalid",
        ),
        lock_fd=lock.fileno(),
    )

    def process_started(pid, process_group):
        started_path.write_text(
            json.dumps({"pid": pid, "process_group": process_group}),
            encoding="utf-8",
        )

    def session_started(session_id):
        session_path.write_text(session_id, encoding="utf-8")

    try:
        outcome = CodexController(
            executable=os.environ["CPE_HELPER_PROVIDER"],
            termination_grace_seconds=float(
                os.environ.get("CPE_HELPER_TERM_GRACE", "0.05")
            ),
        ).launch(
            request,
            on_session_id=session_started,
            on_process_started=process_started,
        )
    except KeyboardInterrupt:
        result_path.write_text(
            json.dumps({"interrupted": True}),
            encoding="utf-8",
        )
        raise SystemExit(42)

result_path.write_text(
    json.dumps({
        "interrupted": False,
        "session_id": outcome.session_id,
        "exit_code": outcome.exit_code,
        "process_class": outcome.process_class,
    }),
    encoding="utf-8",
)
"""
            % str(scripts),
        )

    def start_controller_helper(
        self,
        *,
        name: str,
        provider: Path,
        prompt: str,
        environment: dict[str, str] | None = None,
    ) -> tuple[subprocess.Popen[bytes], dict[str, Path]]:
        helper_base = self.base / name
        helper_base.mkdir()
        worktree = helper_base / "worktree"
        git_common = helper_base / "git-common"
        worktree.mkdir()
        git_common.mkdir()
        schema = helper_base / "schema.json"
        schema.write_text("{}\n", encoding="utf-8")
        prompt_path = helper_base / "prompt.txt"
        prompt_path.write_text(prompt, encoding="utf-8")
        paths = {
            "base": helper_base,
            "result": helper_base / "result.json",
            "started": helper_base / "started.json",
            "session": helper_base / "session.txt",
            "lock": helper_base / "run.lock",
            "stdout": helper_base / "stdout.log",
            "stderr": helper_base / "stderr.log",
        }
        child_environment = os.environ.copy()
        child_environment.update(
            {
                "CPE_HELPER_BASE": str(helper_base),
                "CPE_HELPER_PROMPT": str(prompt_path),
                "CPE_HELPER_RESULT": str(paths["result"]),
                "CPE_HELPER_STARTED": str(paths["started"]),
                "CPE_HELPER_SESSION": str(paths["session"]),
                "CPE_HELPER_LOCK": str(paths["lock"]),
                "CPE_HELPER_WORKTREE": str(worktree),
                "CPE_HELPER_GIT_COMMON": str(git_common),
                "CPE_HELPER_SCHEMA": str(schema),
                "CPE_HELPER_PROVIDER": str(provider),
                "CPE_HELPER_TERM_GRACE": "0.05",
            }
        )
        child_environment.update(environment or {})
        with (
            paths["stdout"].open("wb") as stdout,
            paths["stderr"].open("wb") as stderr,
        ):
            helper = subprocess.Popen(
                [sys.executable, str(self.controller_helper(f"{name}-helper"))],
                stdout=stdout,
                stderr=stderr,
                env=child_environment,
            )
        return helper, paths

    def wait_for_path(self, path: Path, timeout: float = 2.0) -> None:
        deadline = time.monotonic() + timeout
        while not path.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(path.exists(), f"timed out waiting for {path}")

    @staticmethod
    def process_group_exists(process_group: int) -> bool:
        try:
            os.killpg(process_group, 0)
        except ProcessLookupError:
            return False
        return True

    @staticmethod
    def lock_is_available(path: Path) -> bool:
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return False
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            return True
        finally:
            os.close(descriptor)

    @staticmethod
    def cleanup_helper(
        helper: subprocess.Popen[bytes],
        process_group: int | None,
    ) -> None:
        if helper.poll() is None:
            helper.kill()
        try:
            helper.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass
        if process_group is not None:
            try:
                os.killpg(process_group, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def terminal_provider(self) -> Path:
        return self.write_provider(
            "terminal-provider",
            """
import json
import os
import sys
from pathlib import Path

sys.stdin.read()
terminal = Path(os.environ["CPE_TEST_TERMINAL_PATH"]).read_text(encoding="utf-8")
print(json.dumps({"type": "thread.started", "thread_id": %r}), flush=True)
print(json.dumps({
    "type": "item.completed",
    "item": {"type": "agent_message", "text": terminal},
}), flush=True)
print(json.dumps({"type": "turn.completed"}), flush=True)
"""
            % SESSION_ID,
        )

    def launch_terminal_text(self, terminal: str) -> ControllerOutcome:
        terminal_path = self.base / "terminal.json"
        terminal_path.write_text(terminal, encoding="utf-8")
        outcome, _, _ = self.launch_captured(
            CodexController(executable=str(self.terminal_provider())),
            self.request(),
            environment={"CPE_TEST_TERMINAL_PATH": str(terminal_path)},
        )
        return outcome

    def test_initial_and_resume_argv_share_one_profile(self) -> None:
        controller = CodexController(executable="/opt/fake/codex")
        initial = controller.build_argv(self.request(session_id=None))
        resumed = controller.build_argv(
            self.request(session_id="11111111-1111-4111-8111-111111111111")
        )
        required = [
            "--ignore-user-config",
            "--ignore-rules",
            "--strict-config",
            "-c",
            'approval_policy="never"',
            "--json",
            "--sandbox",
            "workspace-write",
        ]
        for argument in required:
            self.assertIn(argument, initial)
            self.assertIn(argument, resumed)
        self.assertEqual(
            initial,
            [
                "/opt/fake/codex",
                "exec",
                "--ignore-user-config",
                "--ignore-rules",
                "--strict-config",
                "-c",
                'approval_policy="never"',
                "--json",
                "--output-schema",
                str(self.schema_path),
                "--cd",
                str(self.worktree),
                "--sandbox",
                "workspace-write",
                "--add-dir",
                str(self.git_common_dir),
                "-",
            ],
        )
        self.assertEqual(initial[-1], "-")
        self.assertEqual(
            resumed[-3:],
            ["resume", "11111111-1111-4111-8111-111111111111", "-"],
        )
        self.assertNotIn("--ephemeral", initial + resumed)
        self.assertNotIn("--output-last-message", initial + resumed)

    def test_git_identity_is_injected_without_copying_git_config(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "GIT_CONFIG": "/tmp/attacker-config",
                "GIT_CONFIG_GLOBAL": "/tmp/attacker-global",
                "GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": "alias.commit",
                "GIT_CONFIG_VALUE_0": "!false",
                "GIT_DIR": "/tmp/routed-git-dir",
                "GIT_WORK_TREE": "/tmp/routed-worktree",
                "GIT_COMMON_DIR": "/tmp/routed-common-dir",
                "GIT_INDEX_FILE": "/tmp/routed-index",
                "GIT_OBJECT_DIRECTORY": "/tmp/routed-objects",
                "GIT_ALTERNATE_OBJECT_DIRECTORIES": "/tmp/routed-alternates",
                "OPENAI_API_KEY": "openai-secret",
                "ANTHROPIC_API_KEY": "anthropic-secret",
                "AWS_SECRET_ACCESS_KEY": "aws-secret",
                "AWS_SESSION_TOKEN": "aws-session-secret",
                "GITHUB_TOKEN": "github-secret",
                "CODEX_HOME": "/tmp/codex-home",
            },
            clear=False,
        ):
            environment = CodexController.build_environment(self.request())
        self.assertEqual(environment["GIT_AUTHOR_NAME"], "CPE Canary")
        self.assertEqual(environment["GIT_AUTHOR_EMAIL"], "cpe@example.invalid")
        self.assertEqual(environment["GIT_COMMITTER_NAME"], "CPE Committer")
        self.assertEqual(
            environment["GIT_COMMITTER_EMAIL"],
            "committer@example.invalid",
        )
        self.assertFalse(
            [name for name in environment if name == "GIT_CONFIG" or name.startswith("GIT_CONFIG_")]
        )
        for name in (
            "GIT_DIR",
            "GIT_WORK_TREE",
            "GIT_COMMON_DIR",
            "GIT_INDEX_FILE",
            "GIT_OBJECT_DIRECTORY",
            "GIT_ALTERNATE_OBJECT_DIRECTORIES",
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "AWS_SECRET_ACCESS_KEY",
            "AWS_SESSION_TOKEN",
            "GITHUB_TOKEN",
        ):
            self.assertNotIn(name, environment)
        self.assertEqual(environment["CODEX_HOME"], "/tmp/codex-home")

    def test_stream_persists_first_session_and_terminal_envelope(self) -> None:
        observed: list[str] = []
        outcome = self.launch_fake(
            scenario="completed",
            on_session_id=observed.append,
        )
        self.assertEqual(observed, ["11111111-1111-4111-8111-111111111111"])
        self.assertEqual(outcome.session_id, observed[0])
        self.assertEqual(outcome.terminal.claim, "completed")
        self.assertEqual(outcome.process_class, "completed")

    def test_session_id_must_be_one_canonical_uuid(self) -> None:
        controller = CodexController(executable="/opt/fake/codex")
        for invalid in (
            "",
            "not-a-uuid",
            "{11111111-1111-4111-8111-111111111111}",
            "11111111111141118111111111111111",
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    controller.build_argv(self.request(session_id=invalid))

    def test_invalid_stream_session_fails_closed(self) -> None:
        provider = self.write_provider(
            "invalid-session-provider",
            """
import json
import sys

sys.stdin.read()
print(json.dumps({"type": "thread.started", "thread_id": "not-a-uuid"}), flush=True)
print(json.dumps({
    "type": "item.completed",
    "item": {
        "type": "agent_message",
        "text": json.dumps({"claim": "completed", "head_commit": "a" * 40}),
    },
}), flush=True)
""",
        )
        outcome, _, _ = self.launch_captured(
            CodexController(executable=str(provider)),
            self.request(),
        )
        self.assertEqual(outcome.process_class, "invalid_envelope")
        self.assertIsNone(outcome.session_id)
        self.assertIsNone(outcome.terminal)

    def test_conflicting_duplicate_session_fails_after_first_callback(self) -> None:
        observed: list[str] = []
        outcome = self.launch_fake(
            scenario="duplicate_session",
            on_session_id=observed.append,
        )
        self.assertEqual(observed, [SESSION_ID])
        self.assertEqual(outcome.session_id, SESSION_ID)
        self.assertEqual(outcome.process_class, "invalid_envelope")
        self.assertIsNone(outcome.terminal)

    def test_jsonl_line_over_one_mebibyte_fails_closed(self) -> None:
        provider = self.write_provider(
            "oversized-line-provider",
            """
import json
import sys

sys.stdin.read()
print(json.dumps({"type": "diagnostic", "text": "x" * (%d + 1)}), flush=True)
print(json.dumps({"type": "thread.started", "thread_id": %r}), flush=True)
print(json.dumps({
    "type": "item.completed",
    "item": {
        "type": "agent_message",
        "text": json.dumps({"claim": "completed", "head_commit": "a" * 40}),
    },
}), flush=True)
"""
            % (MAX_JSONL_LINE_BYTES, SESSION_ID),
        )
        outcome, stdout, _ = self.launch_captured(
            CodexController(executable=str(provider)),
            self.request(),
        )
        self.assertEqual(outcome.process_class, "invalid_envelope")
        self.assertIsNone(outcome.terminal)
        self.assertLessEqual(len(stdout.encode("utf-8")), MAX_LIVE_OUTPUT_BYTES)

    def test_final_envelope_over_64_kib_fails_closed(self) -> None:
        oversized = json.dumps(
            {
                "claim": "completed",
                "head_commit": "a" * 40,
                "blocker": {"detail": "x" * MAX_TERMINAL_ENVELOPE_BYTES},
            }
        )
        outcome = self.launch_terminal_text(oversized)
        self.assertEqual(outcome.process_class, "invalid_envelope")
        self.assertIsNone(outcome.terminal)

    def test_live_output_is_bounded_without_truncating_parsing(self) -> None:
        provider = self.write_provider(
            "large-live-output-provider",
            """
import json
import sys

sys.stdin.read()
print(json.dumps({"type": "thread.started", "thread_id": %r}), flush=True)
for index in range(200):
    print(json.dumps({"type": "diagnostic", "index": index, "text": "x" * 1000}), flush=True)
print(json.dumps({
    "type": "item.completed",
    "item": {
        "type": "agent_message",
        "text": json.dumps({"claim": "completed", "head_commit": "a" * 40}),
    },
}), flush=True)
print(json.dumps({"type": "turn.completed"}), flush=True)
"""
            % SESSION_ID,
        )
        outcome, stdout, _ = self.launch_captured(
            CodexController(executable=str(provider)),
            self.request(),
        )
        self.assertEqual(outcome.process_class, "completed")
        self.assertLessEqual(len(stdout.encode("utf-8")), MAX_LIVE_OUTPUT_BYTES)

    def test_raw_stderr_is_forwarded_but_never_persisted(self) -> None:
        before = set(self.worktree.rglob("*"))
        outcome, _, stderr = self.launch_captured(
            CodexController(executable=str(self.fake_codex)),
            self.request(),
            scenario="blocked_auth",
        )
        self.assertEqual(outcome.provider_code, "auth")
        self.assertIn("RAW_PROVIDER_STDERR", stderr)
        self.assertNotIn("RAW_PROVIDER_STDERR", repr(outcome))
        self.assertEqual(set(self.worktree.rglob("*")), before)

    def test_provider_codes_are_normalized_to_the_closed_transport_set(self) -> None:
        expected = {
            "blocked_auth": "auth",
            "blocked_quota": "quota",
            "provider_unavailable": "provider_unavailable",
            "session_unavailable": "session_unavailable",
            "transport": "transport",
        }
        allowed = {
            "auth",
            "quota",
            "provider_unavailable",
            "session_unavailable",
            "transport",
            "unknown",
        }
        for scenario, provider_code in expected.items():
            with self.subTest(scenario=scenario):
                outcome = self.launch_fake(scenario=scenario)
                self.assertEqual(outcome.provider_code, provider_code)
                self.assertIn(outcome.provider_code, allowed)

    def test_generic_nonzero_is_unknown_not_session_unavailable(self) -> None:
        provider = self.write_provider(
            "generic-nonzero-provider",
            """
import sys

sys.stdin.read()
print("generic provider failure", file=sys.stderr, flush=True)
raise SystemExit(7)
""",
        )
        outcome, _, _ = self.launch_captured(
            CodexController(executable=str(provider)),
            self.request(),
        )
        self.assertEqual(outcome.exit_code, 7)
        self.assertEqual(outcome.process_class, "failed")
        self.assertEqual(outcome.provider_code, "unknown")
        self.assertNotEqual(outcome.provider_code, "session_unavailable")

    def test_malformed_terminal_json_is_an_invalid_envelope(self) -> None:
        outcome = self.launch_fake(scenario="invalid_envelope")
        self.assertEqual(outcome.process_class, "invalid_envelope")
        self.assertIsNone(outcome.terminal)

    def test_process_callback_fires_before_output_consumption(self) -> None:
        stdout = io.StringIO()
        observed: list[tuple[int, int]] = []

        def process_started(pid: int, process_group: int) -> None:
            self.assertEqual(stdout.getvalue(), "")
            self.assertEqual(process_group, pid)
            self.assertEqual(os.getpgid(pid), process_group)
            observed.append((pid, process_group))

        with (
            mock.patch.dict(
                os.environ,
                {"CPE_FAKE_SCENARIO": "completed"},
                clear=False,
            ),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            outcome = CodexController(executable=str(self.fake_codex)).launch(
                self.request(),
                on_session_id=lambda _session_id: None,
                on_process_started=process_started,
            )
        self.assertEqual(outcome.process_class, "completed")
        self.assertEqual(len(observed), 1)
        self.assertIn("thread.started", stdout.getvalue())

    def test_child_receives_run_lock_descriptor(self) -> None:
        outcome = self.launch_fake(
            scenario="completed",
            environment={
                "CPE_FAKE_EXPECT_LOCK_FD": str(self.run_lock.fileno()),
            },
        )
        self.assertEqual(outcome.process_class, "completed")

    def test_sigterm_escalates_to_sigkill_after_bounded_grace(self) -> None:
        class StopLaunch(RuntimeError):
            pass

        marker = self.base / "sigterm-observed"
        process_ids: list[int] = []

        def stop_after_session(_session_id: str) -> None:
            raise StopLaunch("stop after session persistence")

        started = time.monotonic()
        with (
            mock.patch.dict(
                os.environ,
                {
                    "CPE_FAKE_SCENARIO": "ignore_term",
                    "CPE_FAKE_TERM_MARKER": str(marker),
                },
                clear=False,
            ),
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            with self.assertRaises(StopLaunch):
                CodexController(
                    executable=str(self.fake_codex),
                    termination_grace_seconds=0.05,
                ).launch(
                    self.request(),
                    on_session_id=stop_after_session,
                    on_process_started=lambda pid, _group: process_ids.append(pid),
                )
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 1.0)
        self.assertTrue(marker.is_file())
        self.assertEqual(len(process_ids), 1)
        with self.assertRaises(ProcessLookupError):
            os.kill(process_ids[0], 0)

    def test_actual_sigterm_cleans_provider_group_and_inherited_lock(self) -> None:
        term_marker = self.base / "actual-sigterm-observed"
        helper, paths = self.start_controller_helper(
            name="actual-sigterm",
            provider=self.fake_codex,
            prompt="Execute the approved plan.",
            environment={
                "CPE_FAKE_SCENARIO": "ignore_term",
                "CPE_FAKE_TERM_MARKER": str(term_marker),
            },
        )
        process_group: int | None = None
        try:
            self.wait_for_path(paths["session"])
            started = json.loads(paths["started"].read_text(encoding="utf-8"))
            process_group = started["process_group"]
            os.kill(helper.pid, signal.SIGTERM)
            return_code = helper.wait(timeout=2)
            group_alive = self.process_group_exists(process_group)
            lock_available = self.lock_is_available(paths["lock"])
            term_observed = term_marker.is_file()
        finally:
            self.cleanup_helper(helper, process_group)
        self.assertEqual(return_code, 42)
        self.assertFalse(group_alive)
        self.assertTrue(lock_available)
        self.assertTrue(term_observed)

    def test_group_signals_keep_exited_leader_as_identity_anchor(self) -> None:
        leader = subprocess.Popen(
            [sys.executable, "-c", "pass"],
            start_new_session=True,
        )
        wait_flags = os.WEXITED | os.WNOHANG | os.WNOWAIT
        deadline = time.monotonic() + 2
        while os.waitid(os.P_PID, leader.pid, wait_flags) is None:
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.01)

        real_killpg = os.killpg
        anchor_observations: list[bool] = []

        def probe_killpg(process_group: int, signal_number: int) -> None:
            try:
                waitable = os.waitid(os.P_PID, leader.pid, wait_flags)
            except ChildProcessError:
                waitable = None
            anchor_observations.append(
                waitable is not None and waitable.si_pid == leader.pid
            )
            real_killpg(process_group, signal_number)

        try:
            with mock.patch(
                "cpe_runtime.controller.os.killpg",
                side_effect=probe_killpg,
            ):
                CodexController(termination_grace_seconds=0)._terminate(leader)
        finally:
            if leader.returncode is None:
                leader.wait()

        self.assertTrue(anchor_observations)
        self.assertTrue(
            all(anchor_observations),
            "numeric PGID access occurred after the leader PID was reaped",
        )

    def test_late_cleanup_never_accesses_an_already_reaped_group(self) -> None:
        class LateFailure(RuntimeError):
            pass

        class LateFailureController(CodexController):
            leader: subprocess.Popen[bytes] | None = None

            def _drain(
                self,
                process: subprocess.Popen[bytes],
                prompt: str,
                expected_session_id: str | None,
                on_session_id: object,
            ) -> object:
                self.leader = process
                super()._drain(
                    process,
                    prompt,
                    expected_session_id,
                    on_session_id,
                )
                if process.returncode is None:
                    raise AssertionError("probe requires a reaped leader")
                raise LateFailure("late cleanup after drain")

        provider = self.write_provider(
            "late-cleanup-provider",
            """
import subprocess
import sys

sys.stdin.read()
subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
""",
        )
        controller = LateFailureController(
            executable=str(provider),
            termination_grace_seconds=0,
        )
        real_killpg = os.killpg
        post_reap_accesses: list[tuple[int, int]] = []

        def reject_reaped_group(
            process_group: int,
            signal_number: int,
        ) -> None:
            if (
                controller.leader is not None
                and controller.leader.returncode is not None
            ):
                post_reap_accesses.append((process_group, signal_number))
                raise ProcessLookupError
            real_killpg(process_group, signal_number)

        previous_handler = signal.getsignal(signal.SIGTERM)

        def sentinel_handler(_signum: int, _frame: object) -> None:
            return None

        signal.signal(signal.SIGTERM, sentinel_handler)
        try:
            with (
                mock.patch(
                    "cpe_runtime.controller.os.killpg",
                    side_effect=reject_reaped_group,
                ),
                self.assertRaises(LateFailure),
            ):
                controller.launch(
                    self.request(),
                    on_session_id=lambda _session_id: None,
                    on_process_started=lambda _pid, _group: None,
                )
            restored_handler = signal.getsignal(signal.SIGTERM)
        finally:
            signal.signal(signal.SIGTERM, previous_handler)

        self.assertEqual(post_reap_accesses, [])
        self.assertIs(restored_handler, sentinel_handler)

    def test_group_disappearance_still_unconditionally_reaps_leader(self) -> None:
        leader = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            start_new_session=True,
        )
        real_killpg = os.killpg
        wait_flags = os.WEXITED | os.WNOHANG | os.WNOWAIT
        disappeared = False

        def disappear_on_probe(
            process_group: int,
            signal_number: int,
        ) -> None:
            nonlocal disappeared
            if signal_number == 0 and not disappeared:
                disappeared = True
                real_killpg(process_group, signal.SIGKILL)
                deadline = time.monotonic() + 2
                while os.waitid(os.P_PID, leader.pid, wait_flags) is None:
                    if time.monotonic() >= deadline:
                        self.fail("leader did not exit during disappearance probe")
                    time.sleep(0.01)
                raise ProcessLookupError
            real_killpg(process_group, signal_number)

        return_code: int | None = None
        reaped = False
        try:
            with mock.patch(
                "cpe_runtime.controller.os.killpg",
                side_effect=disappear_on_probe,
            ):
                CodexController(termination_grace_seconds=0)._terminate(leader)
            return_code = leader.returncode
            try:
                os.waitid(os.P_PID, leader.pid, wait_flags)
            except ChildProcessError:
                reaped = True
        finally:
            if leader.returncode is None:
                leader.wait()

        self.assertTrue(disappeared)
        self.assertEqual(return_code, -signal.SIGKILL)
        self.assertTrue(reaped, "group disappearance left an exited leader unreaped")

    def test_large_prompt_and_provider_output_do_not_deadlock(self) -> None:
        provider = self.write_provider(
            "write-before-read-provider",
            """
import json
import sys

for index in range(2200):
    print(json.dumps({
        "type": "diagnostic",
        "index": index,
        "text": "x" * 1000,
    }), flush=True)
sys.stdin.read()
print(json.dumps({"type": "thread.started", "thread_id": %r}), flush=True)
print(json.dumps({
    "type": "item.completed",
    "item": {
        "type": "agent_message",
        "text": json.dumps({"claim": "completed", "head_commit": "a" * 40}),
    },
}), flush=True)
print(json.dumps({"type": "turn.completed"}), flush=True)
"""
            % SESSION_ID,
        )
        helper, paths = self.start_controller_helper(
            name="concurrent-prompt",
            provider=provider,
            prompt="p" * 2_097_152,
        )
        process_group: int | None = None
        timed_out = False
        return_code: int | None = None
        result: dict[str, object] | None = None
        try:
            self.wait_for_path(paths["started"])
            started = json.loads(paths["started"].read_text(encoding="utf-8"))
            process_group = started["process_group"]
            try:
                return_code = helper.wait(timeout=3)
            except subprocess.TimeoutExpired:
                timed_out = True
            if paths["result"].is_file():
                result = json.loads(paths["result"].read_text(encoding="utf-8"))
        finally:
            self.cleanup_helper(helper, process_group)
        self.assertFalse(timed_out, "controller deadlocked on prompt/output pipes")
        self.assertEqual(
            return_code,
            0,
            paths["stderr"].read_text(encoding="utf-8", errors="replace"),
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["process_class"], "completed")

    def test_leader_exit_with_descendant_held_pipes_is_bounded(self) -> None:
        descendant_path = self.base / "descendant-pid"
        provider = self.write_provider(
            "descendant-pipe-provider",
            """
import json
import os
import subprocess
import sys
from pathlib import Path

sys.stdin.read()
descendant = subprocess.Popen(
    [sys.executable, "-c", "import time; time.sleep(60)"],
)
Path(os.environ["CPE_DESCENDANT_PID"]).write_text(
    str(descendant.pid),
    encoding="utf-8",
)
print(json.dumps({"type": "thread.started", "thread_id": %r}), flush=True)
print(json.dumps({
    "type": "item.completed",
    "item": {
        "type": "agent_message",
        "text": json.dumps({"claim": "completed", "head_commit": "a" * 40}),
    },
}), flush=True)
print(json.dumps({"type": "turn.completed"}), flush=True)
"""
            % SESSION_ID,
        )
        helper, paths = self.start_controller_helper(
            name="descendant-pipes",
            provider=provider,
            prompt="Execute the approved plan.",
            environment={"CPE_DESCENDANT_PID": str(descendant_path)},
        )
        process_group: int | None = None
        timed_out = False
        return_code: int | None = None
        result: dict[str, object] | None = None
        group_alive = True
        try:
            self.wait_for_path(paths["started"])
            self.wait_for_path(descendant_path)
            started = json.loads(paths["started"].read_text(encoding="utf-8"))
            process_group = started["process_group"]
            try:
                return_code = helper.wait(timeout=3)
            except subprocess.TimeoutExpired:
                timed_out = True
            group_alive = self.process_group_exists(process_group)
            if paths["result"].is_file():
                result = json.loads(paths["result"].read_text(encoding="utf-8"))
        finally:
            self.cleanup_helper(helper, process_group)
        self.assertFalse(timed_out, "descendant-held pipes stalled controller")
        self.assertEqual(
            return_code,
            0,
            paths["stderr"].read_text(encoding="utf-8", errors="replace"),
        )
        self.assertFalse(group_alive)
        self.assertIsNotNone(result)
        self.assertEqual(result["process_class"], "completed")

    def test_resume_capsule_matches_task_one_byte_and_count_bounds(self) -> None:
        capsule = {
            "head_commit": "b" * 40,
            "worktree_status_digest": "c" * 64,
            "note": "n" * 2048,
            "evidence_refs": ["e" * 512 for _ in range(16)],
        }
        payload = {
            "claim": "interrupted",
            "head_commit": "a" * 40,
            "resume_capsule": capsule,
        }
        accepted = self.launch_terminal_text(json.dumps(payload))
        self.assertEqual(accepted.process_class, "interrupted")
        self.assertEqual(accepted.terminal.resume_capsule.note, "n" * 2048)
        self.assertEqual(len(accepted.terminal.resume_capsule.evidence_refs), 16)

        invalid_capsules = [
            {**capsule, "note": "n" * 2049},
            {**capsule, "evidence_refs": ["e" for _ in range(17)]},
            {**capsule, "evidence_refs": ["e" * 513]},
        ]
        for invalid_capsule in invalid_capsules:
            with self.subTest(invalid_capsule=invalid_capsule):
                rejected = self.launch_terminal_text(
                    json.dumps({**payload, "resume_capsule": invalid_capsule})
                )
                self.assertEqual(rejected.process_class, "invalid_envelope")
                self.assertIsNone(rejected.terminal)

    def test_terminal_claims_require_their_approved_optional_fields(self) -> None:
        capsule = {
            "head_commit": "b" * 40,
            "worktree_status_digest": "c" * 64,
            "note": "resume locally",
            "evidence_refs": [],
        }
        blocker = {
            "class": "operator_owned",
            "code": "approval_required",
            "resource": "local-worktree",
            "operation": "continue_execution",
            "retry_condition": "operator supplies the required decision",
            "provider_code": None,
        }
        invalid_payloads = [
            {"claim": "failed", "head_commit": "a" * 40},
            {
                "claim": "completed",
                "head_commit": "a" * 40,
                "resume_capsule": capsule,
            },
            {
                "claim": "completed",
                "head_commit": "a" * 40,
                "blocker": blocker,
            },
            {"claim": "interrupted", "head_commit": "a" * 40},
            {
                "claim": "interrupted",
                "head_commit": "a" * 40,
                "resume_capsule": capsule,
                "blocker": blocker,
            },
            {"claim": "blocked", "head_commit": "a" * 40},
        ]
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                outcome = self.launch_terminal_text(json.dumps(payload))
                self.assertEqual(outcome.process_class, "invalid_envelope")
                self.assertIsNone(outcome.terminal)

    def test_explicit_null_terminal_objects_are_invalid(self) -> None:
        for field in ("resume_capsule", "blocker"):
            with self.subTest(field=field):
                outcome = self.launch_terminal_text(
                    json.dumps(
                        {
                            "claim": "completed",
                            "head_commit": "a" * 40,
                            field: None,
                        }
                    )
                )
                self.assertEqual(outcome.process_class, "invalid_envelope")
                self.assertIsNone(outcome.terminal)

    def test_blocker_has_exact_keys_and_utf8_byte_bounds(self) -> None:
        blocker = {
            "class": "operator_owned",
            "code": "approval_required",
            "resource": "local-worktree",
            "operation": "continue_execution",
            "retry_condition": "operator supplies the required decision",
            "provider_code": "auth",
        }
        accepted = self.launch_terminal_text(
            json.dumps(
                {
                    "claim": "blocked",
                    "head_commit": "a" * 40,
                    "blocker": blocker,
                }
            )
        )
        self.assertEqual(accepted.process_class, "blocked")
        self.assertEqual(accepted.terminal.blocker, blocker)

        missing = dict(blocker)
        missing.pop("retry_condition")
        invalid_blockers = [
            missing,
            {**blocker, "unexpected": "semantic detail"},
            {**blocker, "class": ""},
            {**blocker, "class": "é" * 33},
            {**blocker, "code": "c" * 129},
            {**blocker, "resource": "r" * 257},
            {**blocker, "operation": "o" * 129},
            {**blocker, "retry_condition": "r" * 513},
            {**blocker, "provider_code": 7},
            {**blocker, "provider_code": "p" * 129},
        ]
        for invalid_blocker in invalid_blockers:
            with self.subTest(invalid_blocker=invalid_blocker):
                outcome = self.launch_terminal_text(
                    json.dumps(
                        {
                            "claim": "blocked",
                            "head_commit": "a" * 40,
                            "blocker": invalid_blocker,
                        }
                    )
                )
                self.assertEqual(outcome.process_class, "invalid_envelope")
                self.assertIsNone(outcome.terminal)

    def test_terminal_envelope_rejects_semantic_completion_fields(self) -> None:
        semantic_fields = {
            "tasks": ["task-1"],
            "review_approved": True,
            "verification": [{"command": "tests", "exit_code": 0}],
        }
        for name, value in semantic_fields.items():
            with self.subTest(name=name):
                outcome = self.launch_terminal_text(
                    json.dumps(
                        {
                            "claim": "completed",
                            "head_commit": "a" * 40,
                            name: value,
                        }
                    )
                )
                self.assertEqual(outcome.process_class, "invalid_envelope")
                self.assertIsNone(outcome.terminal)


if __name__ == "__main__":
    unittest.main()
