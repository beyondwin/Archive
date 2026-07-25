import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest import mock

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from plan_runner.contracts import sha256_json  # noqa: E402
from plan_runner.evidence import EvidenceStore, ExactCommand  # noqa: E402
from plan_runner.git_ops import GitWorkspace  # noqa: E402
from plan_runner.storage import StateStore  # noqa: E402
from plan_runner import process as process_module  # noqa: E402


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class ExactEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name).resolve()
        self.source = self.base / "source"
        self.source.mkdir()
        git(self.source, "init")
        git(self.source, "config", "user.email", "tests@example.invalid")
        git(self.source, "config", "user.name", "Claude Runner")
        (self.source / "tracked.txt").write_text("base\n")
        git(self.source, "add", ".")
        git(self.source, "commit", "-m", "base")
        self.start = git(self.source, "rev-parse", "HEAD")
        self.run_id = f"evidence-{uuid.uuid4()}"
        self.worktree_path = self.base / "worktree"
        self.workspace = GitWorkspace.create(
            self.source, self.worktree_path, f"claude-plan/{self.run_id}"
        )
        self.spec = self.base / "spec.md"
        self.plan = self.base / "plan.md"
        self.plan_two = self.base / "plan-two.md"
        self.spec.write_text("spec")
        self.plan.write_text("plan")
        self.plan_two.write_text("plan two")
        state_root = self.base / "state-home" / self.run_id
        state_root.parent.mkdir(mode=0o700)
        self.state = StateStore.create(
            root=state_root, provider="claude", run_id=self.run_id,
            source_repository=self.source, source_commit=self.start,
            worktree=self.worktree_path, branch=f"claude-plan/{self.run_id}",
            specs=[self.spec], plans=[self.plan, self.plan_two],
            immutable_config={}, runner_runtime={},
        )
        self.env = {"PATH": os.environ.get("PATH", ""), "ANTHROPIC_API_KEY": "hidden"}
        self.evidence = EvidenceStore(self.state, self.workspace, self.env, output_limit=256)

    def tearDown(self):
        self.temp.cleanup()

    def command(self, argv, *, role="focused", deadline=5, command_id="cmd"):
        return ExactCommand(
            command_id, role, tuple(argv), ".", sha256_json({"input": command_id}), deadline
        )

    def test_literal_argv_receipt_is_redacted_and_success_reuses_same_identity(self):
        command = self.command([
            sys.executable, "-c",
            "import os,sys;print(sys.argv[1]);print('ANTHROPIC_API_KEY='+os.environ['ANTHROPIC_API_KEY'], file=sys.stderr)",
            "argument with spaces; untouched",
        ])
        first = self.evidence.execute(command, candidate_head=self.start)
        second = self.evidence.execute(command, candidate_head=self.start)
        self.assertEqual(first.outcome, "success")
        self.assertFalse(first.reused)
        self.assertTrue(second.reused)
        document = self.state.referenced_artifact(first.artifact.as_dict()).read_text()
        self.assertIn("argument with spaces; untouched", document)
        self.assertNotIn("hidden", document)

    def test_nonzero_is_not_reused_and_deadline_timeout_is_separate(self):
        failing = self.command([sys.executable, "-c", "raise SystemExit(7)"], command_id="fail")
        first = self.evidence.execute(failing, candidate_head=self.start)
        second = self.evidence.execute(failing, candidate_head=self.start)
        self.assertEqual((first.outcome, first.exit_code), ("failed", 7))
        self.assertFalse(second.reused)
        timeout = self.command(
            [sys.executable, "-c", "import time; time.sleep(10)"],
            deadline=0.1,
            command_id="timeout",
        )
        receipt = self.evidence.execute(timeout, candidate_head=self.start)
        self.assertEqual((receipt.outcome, receipt.exit_code), ("timed_out", None))

    def test_identity_changes_with_head_environment_tree_or_command(self):
        base = self.command([sys.executable, "-c", "pass"])
        original = self.evidence.identity_digest(base, candidate_head=self.start)
        changed_argv = self.evidence.identity_digest(
            self.command([sys.executable, "-c", "print(1)"], command_id="other"),
            candidate_head=self.start,
        )
        self.assertNotEqual(original, changed_argv)
        (self.worktree_path / "untracked").write_text("x")
        dirty_identity = self.evidence.identity_digest(base, candidate_head=self.start)
        self.assertNotEqual(original, dirty_identity)
        (self.worktree_path / "untracked").unlink()

    def test_plan_set_is_candidate_bound_nonempty_and_loadable(self):
        command = self.command(
            [sys.executable, "-c", "pass"],
            role="handoff",
        )
        payload = {
            "kind": "commands",
            "candidate_head": self.start,
            "commands": [{
                "command_id": command.command_id,
                "command_role": command.command_role,
                "argv": list(command.argv),
                "cwd": command.cwd,
                "input_digest": command.input_digest,
                "deadline_seconds": command.deadline_seconds,
            }],
        }
        artifact = self.evidence.declare_verification(
            payload,
            self.start,
            plan_index=0,
            prior_set_digests=[],
            is_final_plan=False,
        )
        self.assertEqual(
            self.evidence.load_verification_command(artifact.digest, 0),
            command,
        )
        with self.assertRaises(ValueError):
            self.evidence.declare_verification(
                {"kind": "commands", "candidate_head": self.start, "commands": []},
                self.start,
                plan_index=0,
                prior_set_digests=[],
                is_final_plan=False,
            )
        no_gate = self.evidence.declare_verification(
            {
                "kind": "no_applicable_verification",
                "candidate_head": self.start,
                "rationale": "Documentation-only update",
            },
            self.start,
            plan_index=0,
            prior_set_digests=[],
            is_final_plan=False,
        )
        self.assertTrue(no_gate.digest)

    def test_plan_verification_commands_require_a_sealed_candidate_head_set(self):
        command = self.command(
            [sys.executable, "-c", "pass"],
            role="handoff",
        )
        payload = {
            "kind": "commands",
            "candidate_head": self.start,
            "commands": [command.as_dict()],
        }
        artifact = self.evidence.declare_verification(
            payload,
            self.start,
            plan_index=0,
            prior_set_digests=[],
            is_final_plan=False,
        )
        with self.assertRaisesRegex(ValueError, "receipt"):
            self.evidence.require_successful_verification_set(
                artifact.digest,
                candidate_head=self.start,
                artifact_kind="plan_verification_set",
                plan_index=0,
            )
        receipt = self.evidence.execute(
            command,
            candidate_head=self.start,
        )
        self.assertEqual(receipt.outcome, "success")
        self.evidence.require_successful_verification_set(
            artifact.digest,
            candidate_head=self.start,
            artifact_kind="plan_verification_set",
            plan_index=0,
        )

    def test_final_run_set_is_the_exact_ordered_duplicate_free_plan_union(self):
        shared = self.command(
            [sys.executable, "-c", "pass"],
            role="handoff",
            command_id="shared-first",
        )
        first = self.evidence.declare_verification(
            {
                "kind": "commands",
                "candidate_head": self.start,
                "commands": [shared.as_dict()],
            },
            self.start,
            plan_index=0,
            prior_set_digests=[],
            is_final_plan=False,
        )
        self.evidence.execute(shared, candidate_head=self.start)
        handoff = self.state.put_artifact(
            "plan_handoff",
            {
                "plan_index": 0,
                "verification_set_digest": first.digest,
            },
        )
        state = self.state.snapshot()
        state["artifact_refs"].append(handoff.as_dict())
        state["plans"][0]["status"] = "implemented"
        state["plans"][0]["handoff_digest"] = handoff.digest
        state["current_plan_index"] = 1
        self.state.commit(state)

        duplicate = ExactCommand(
            "shared-again",
            shared.command_role,
            shared.argv,
            shared.cwd,
            shared.input_digest,
            shared.deadline_seconds,
        )
        unique = self.command(
            [sys.executable, "-c", "print('second')"],
            role="handoff",
            command_id="unique-second",
        )
        final = self.evidence.declare_verification(
            {
                "kind": "commands",
                "candidate_head": self.start,
                "commands": [duplicate.as_dict(), unique.as_dict()],
            },
            self.start,
            plan_index=1,
            prior_set_digests=[first.digest],
            is_final_plan=True,
        )
        document = json.loads(
            self.state.referenced_artifact(final.as_dict()).read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(document["kind"], "run_verification")
        self.assertEqual(
            [command["command_id"] for command in document["commands"]],
            ["shared-first", "unique-second"],
        )
        self.evidence.execute(unique, candidate_head=self.start)
        self.evidence.require_successful_verification_set(
            final.digest,
            candidate_head=self.start,
            artifact_kind="run_verification_set",
            plan_index=1,
        )

    def test_candidate_execution_requires_clean_exact_head(self):
        command = self.command([sys.executable, "-c", "pass"])
        (self.worktree_path / "dirty").write_text("x")
        with self.assertRaisesRegex(ValueError, "clean"):
            self.evidence.execute(command, candidate_head=self.start)
        with self.assertRaises(ValueError):
            self.evidence.execute(command, candidate_head="f" * 40)

    def test_exited_leader_stays_unreaped_while_closed_stream_descendant_is_signaled(self):
        child_file = self.base / "closed-stream-child.pid"
        command = self.command(
            [
                sys.executable,
                "-c",
                (
                    "import os,pathlib,subprocess,sys;"
                    "child=subprocess.Popen([sys.executable,'-c',"
                    "'import os,time;os.close(1);os.close(2);time.sleep(8)']);"
                    "pathlib.Path(sys.argv[1]).write_text(str(child.pid));"
                    "os.close(1);os.close(2)"
                ),
                str(child_file),
            ],
            deadline=2,
            command_id="closed-stream-group",
        )
        launched = []
        leader_states_at_signal = []
        real_popen = subprocess.Popen
        real_killpg = os.killpg

        def observe_launch(*args, **kwargs):
            child = real_popen(*args, **kwargs)
            if kwargs.get("start_new_session"):
                launched.append(child)
            return child

        def observe_signal(group, sig):
            if sig in (signal.SIGTERM, signal.SIGKILL):
                leader_states_at_signal.append(launched[0].returncode)
            return real_killpg(group, sig)

        try:
            with (
                mock.patch.object(process_module.subprocess, "Popen", side_effect=observe_launch),
                mock.patch.object(process_module.os, "killpg", side_effect=observe_signal),
            ):
                receipt = self.evidence.execute(command, candidate_head=self.start)
            self.assertEqual(receipt.outcome, "success")
            self.assertTrue(leader_states_at_signal)
            self.assertTrue(all(state is None for state in leader_states_at_signal))
            with self.assertRaises(ProcessLookupError):
                os.kill(int(child_file.read_text()), 0)
        finally:
            if child_file.exists():
                try:
                    os.kill(int(child_file.read_text()), signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def test_executable_replacement_is_rejected_before_and_after_spawn(self):
        original = self.base / "sealed-executable"
        replacement = self.base / "replacement-executable"
        original.write_text("#!/bin/sh\nsleep 8\n", encoding="utf-8")
        replacement.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        original.chmod(0o700)
        replacement.chmod(0o700)
        opened = process_module.open_executable(
            str(original), cwd=self.base, env=self.env
        )
        os.replace(replacement, original)
        try:
            with self.assertRaisesRegex(ValueError, "changed"):
                process_module.run_exact(
                    (str(original),),
                    cwd=self.base,
                    env=self.env,
                    deadline_seconds=1,
                    opened_executable=opened,
                )
        finally:
            opened.close()

        original.write_text("#!/bin/sh\nsleep 8\n", encoding="utf-8")
        replacement.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        original.chmod(0o700)
        replacement.chmod(0o700)
        opened = process_module.open_executable(
            str(original), cwd=self.base, env=self.env
        )
        real_revalidate = opened.revalidate
        count = 0

        def swap_during_spawn():
            nonlocal count
            count += 1
            if count == 2:
                os.replace(replacement, original)
            return real_revalidate()

        try:
            with mock.patch.object(opened, "revalidate", side_effect=swap_during_spawn):
                with self.assertRaisesRegex(ValueError, "changed"):
                    process_module.run_exact(
                        (str(original),),
                        cwd=self.base,
                        env=self.env,
                        deadline_seconds=1,
                        opened_executable=opened,
                    )
        finally:
            opened.close()

    def test_group_observation_failure_is_bounded_and_fails_closed(self):
        failed = subprocess.CompletedProcess(
            ("/bin/ps",), 1, stdout=b"", stderr=b"unavailable"
        )
        with mock.patch.object(process_module.subprocess, "run", return_value=failed):
            with self.assertRaisesRegex(RuntimeError, "unverifiable"):
                process_module._observe_group(123456, timeout=0.05)
        with mock.patch.object(
            process_module.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(("/bin/ps",), 0.05),
        ):
            with self.assertRaisesRegex(RuntimeError, "unverifiable"):
                process_module._observe_group(123456, timeout=0.05)

    def test_group_signal_permission_failure_still_reaps_direct_child_boundedly(self):
        launched = []
        real_popen = subprocess.Popen

        def observe_launch(*args, **kwargs):
            child = real_popen(*args, **kwargs)
            if kwargs.get("start_new_session"):
                launched.append(child)
            return child

        def reject_kill(_group, sig):
            if sig == signal.SIGKILL:
                raise PermissionError("denied")
            return None

        started = time.monotonic()
        with (
            mock.patch.object(process_module.subprocess, "Popen", side_effect=observe_launch),
            mock.patch.object(process_module.os, "killpg", side_effect=reject_kill),
            mock.patch.object(process_module, "_wait_for_quiet_group", return_value=False),
        ):
            with self.assertRaisesRegex(RuntimeError, "unverifiable"):
                process_module.run_exact(
                    [sys.executable, "-c", "import time;time.sleep(8)"],
                    cwd=self.base,
                    env=self.env,
                    deadline_seconds=0.1,
                )
        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual(len(launched), 1)
        self.assertIsNotNone(launched[0].returncode)
        with self.assertRaises(ChildProcessError):
            os.waitpid(launched[0].pid, os.WNOHANG)


if __name__ == "__main__":
    unittest.main()
