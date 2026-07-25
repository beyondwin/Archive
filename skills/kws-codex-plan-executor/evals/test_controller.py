"""Focused contract tests for the thin Codex controller adapter."""

from __future__ import annotations

import contextlib
import io
import json
import os
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
