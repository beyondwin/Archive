import hashlib
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


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from plan_runner import evidence as evidence_module  # noqa: E402
from plan_runner import process as process_module  # noqa: E402
from plan_runner.evidence import EvidenceStore, ExactCommand  # noqa: E402
from plan_runner.git_ops import GitWorkspace  # noqa: E402
from plan_runner.process import ProcessResult  # noqa: E402
from plan_runner.storage import StateStore  # noqa: E402


def python_command(source: str, *arguments: str) -> tuple[str, ...]:
    return (sys.executable, "-c", source, *arguments)


def git(*arguments: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *arguments], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def init_repository(path: Path) -> str:
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True)
    git("config", "user.name", "Runner Test", cwd=path)
    git("config", "user.email", "runner@example.test", cwd=path)
    (path / "README.md").write_text("base\n", encoding="utf-8")
    git("add", "README.md", cwd=path)
    git("commit", "-m", "base", cwd=path)
    return git("rev-parse", "HEAD", cwd=path)


class EvidenceStoreTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / "source"
        self.source.mkdir()
        self.head = init_repository(self.source)
        self.worktree_path = self.root / "worktree"
        self.workspace = GitWorkspace.create(
            self.source, self.worktree_path, "codex-plan/evidence"
        )
        self.spec = self.root / "spec.md"
        self.plan = self.root / "plan.md"
        self.spec.write_text("spec\n", encoding="utf-8")
        self.plan.write_text("plan\n", encoding="utf-8")
        self.state = StateStore.create(
            root=self.root / "run",
            provider="codex",
            run_id="evidence-12345678-1234-4123-8123-123456789abc",
            source_repository=self.source,
            source_commit=self.head,
            worktree=self.worktree_path,
            branch="codex-plan/evidence",
            specs=[self.spec],
            plans=[self.plan],
            immutable_config={},
            runner_runtime={},
        )
        self.environment = {"PATH": os.environ["PATH"], "SECRET_TOKEN": "super-secret"}
        self.evidence = EvidenceStore(self.state, self.workspace, self.environment)
        self.input_digest = hashlib.sha256(b"input").hexdigest()

    def tearDown(self):
        self.temp.cleanup()

    def command(self, argv, **overrides):
        values = {
            "command_id": "unit",
            "command_role": "final",
            "argv": tuple(argv),
            "cwd": ".",
            "input_digest": self.input_digest,
            "deadline_seconds": 2.0,
        }
        values.update(overrides)
        return ExactCommand(**values)

    def test_literal_argv_and_redacted_bounded_separate_output_are_sealed(self):
        command = self.command(
            python_command(
                "import sys; print(sys.argv[1]); print('x' * 200 + ' SECRET_TOKEN=super-secret', file=sys.stderr)",
                "$(touch should-not-exist)",
            )
        )
        receipt = self.evidence.execute(command, candidate_head=self.head)
        payload = json.loads(self.state.referenced_artifact(receipt.artifact.as_dict()).read_text())
        self.assertEqual(receipt.outcome, "success")
        self.assertIn("$(touch should-not-exist)", payload["stdout_tail"])
        self.assertFalse((self.worktree_path / "should-not-exist").exists())
        self.assertNotIn("super-secret", payload["stderr_tail"])
        self.assertIn("[REDACTED]", payload["stderr_tail"])
        self.assertLessEqual(len(payload["stdout_tail"].encode()), 1_048_576)
        self.assertLessEqual(len(payload["stderr_tail"].encode()), 1_048_576)

    def test_timeout_kills_the_entire_process_group(self):
        child = self.root / "child.pid"
        command = self.command(
            python_command(
                "import pathlib, subprocess, sys, time; "
                "child=subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(5)']); "
                "pathlib.Path(sys.argv[1]).write_text(str(child.pid)); time.sleep(5)",
                str(child),
            ),
            deadline_seconds=1,
        )
        started = time.monotonic()
        receipt = self.evidence.execute(command, candidate_head=self.head)
        self.assertLess(time.monotonic() - started, 12)
        self.assertEqual(receipt.outcome, "timed_out")
        self.assertEqual(receipt.exit_code, None)
        self.assertTrue(child.exists())
        with self.assertRaises(ProcessLookupError):
            os.kill(int(child.read_text()), 0)

    def test_timeout_reaps_leader_when_zero_signal_probe_would_be_eperm(self):
        launched = []
        real_killpg = os.killpg
        real_popen = subprocess.Popen

        def capture_popen(*args, **kwargs):
            process = real_popen(*args, **kwargs)
            if kwargs.get("start_new_session"):
                launched.append(process)
            return process

        def reject_zero_signal(pgid, sig):
            if sig == 0:
                raise PermissionError("Darwin zombie-only process group")
            return real_killpg(pgid, sig)

        with (
            mock.patch.object(
                process_module.subprocess, "Popen", side_effect=capture_popen
            ),
            mock.patch.object(
                process_module.os, "killpg", side_effect=reject_zero_signal
            ),
        ):
            receipt = self.evidence.execute(
                self.command(
                    python_command("import time; time.sleep(5)"),
                    deadline_seconds=0.15,
                ),
                candidate_head=self.head,
            )

        self.assertEqual(receipt.outcome, "timed_out")
        self.assertEqual(len(launched), 1)
        self.assertIsNotNone(launched[0].returncode)
        with self.assertRaises(ChildProcessError):
            os.waitpid(launched[0].pid, os.WNOHANG)

    def test_deadline_survives_closed_streams_and_terminates_the_group(self):
        command = self.command(
            python_command("import os, time; os.close(1); os.close(2); time.sleep(5)"),
            deadline_seconds=0.15,
        )
        started = time.monotonic()
        receipt = self.evidence.execute(command, candidate_head=self.head)
        self.assertLess(time.monotonic() - started, 1.5)
        self.assertEqual(receipt.outcome, "timed_out")

    def test_normal_leader_exit_reaps_same_group_child_after_streams_close(self):
        child_pid = self.root / "orphan.pid"
        command = self.command(
            python_command(
                "import os, pathlib, subprocess, sys; "
                "child=subprocess.Popen([sys.executable, '-c', 'import os,time; os.close(1); os.close(2); time.sleep(5)']); "
                "pathlib.Path(sys.argv[1]).write_text(str(child.pid)); os.close(1); os.close(2)",
                str(child_pid),
            ),
            deadline_seconds=1,
        )
        launched = []
        signal_returncodes = []
        real_killpg = os.killpg
        real_popen = subprocess.Popen

        def capture_popen(*args, **kwargs):
            process = real_popen(*args, **kwargs)
            if kwargs.get("start_new_session"):
                launched.append(process)
            return process

        def record_signal(pgid, sig):
            if sig in (signal.SIGTERM, signal.SIGKILL):
                signal_returncodes.append(launched[0].returncode)
            return real_killpg(pgid, sig)

        try:
            with (
                mock.patch.object(
                    process_module.subprocess, "Popen", side_effect=capture_popen
                ),
                mock.patch.object(
                    process_module.os, "killpg", side_effect=record_signal
                ),
            ):
                receipt = self.evidence.execute(command, candidate_head=self.head)
            self.assertEqual(receipt.outcome, "success")
            self.assertTrue(child_pid.exists())
            self.assertTrue(signal_returncodes)
            self.assertTrue(
                all(returncode is None for returncode in signal_returncodes)
            )
            with self.assertRaises(ProcessLookupError):
                os.kill(int(child_pid.read_text()), 0)
        finally:
            if child_pid.exists():
                try:
                    os.kill(int(child_pid.read_text()), 9)
                except ProcessLookupError:
                    pass

    def test_only_success_is_reused_and_every_identity_input_matters(self):
        counter = self.root / "counter"
        counter.write_text("0", encoding="utf-8")
        success = self.command(
            python_command(
                "import pathlib, sys; p=pathlib.Path(sys.argv[1]); p.write_text(str(int(p.read_text() or '0') + 1))",
                str(counter),
            )
        )
        first = self.evidence.execute(success, candidate_head=self.head)
        second = self.evidence.execute(success, candidate_head=self.head)
        self.assertFalse(first.reused)
        self.assertTrue(second.reused)
        self.assertEqual(counter.read_text(), "1")
        altered = first.identity_digest[:-1] + ("0" if first.identity_digest[-1] != "0" else "1")
        self.assertIsNone(self.evidence.reusable_success(altered))

        failed = self.evidence.execute(self.command(python_command("raise SystemExit(9)"), command_id="failed"), candidate_head=self.head)
        timed = self.evidence.execute(self.command(python_command("import time; time.sleep(5)"), command_id="timed", deadline_seconds=.15), candidate_head=self.head)
        self.assertEqual(failed.outcome, "failed")
        self.assertEqual(timed.outcome, "timed_out")
        self.assertIsNone(self.evidence.reusable_success(failed.identity_digest))
        self.assertIsNone(self.evidence.reusable_success(timed.identity_digest))

        variants = (
            self.command((*success.argv, "changed")),
            self.command(success.argv, cwd="subdir"),
            self.command(("/bin/sh", *success.argv[1:])),
            self.command(success.argv, input_digest="a" * 64),
            self.command(success.argv, command_role="affected"),
        )
        (self.worktree_path / "subdir").mkdir()
        digests = {first.identity_digest}
        for variant in variants:
            with self.subTest(variant=variant):
                digests.add(self.evidence.identity_digest(variant, candidate_head=self.head))
        self.assertEqual(len(digests), len(variants) + 1)
        self.assertNotEqual(first.identity_digest, self.evidence.identity_digest(success, candidate_head="b" * 40))
        self.evidence.environment["PATH"] = os.environ["PATH"] + ":/different"
        self.assertNotEqual(first.identity_digest, self.evidence.identity_digest(success, candidate_head=self.head))
        self.evidence.environment["PATH"] = os.environ["PATH"]
        (self.worktree_path / "drift.txt").write_text("drift", encoding="utf-8")
        self.assertNotEqual(first.identity_digest, self.evidence.identity_digest(success, candidate_head=self.head))

    def test_final_commands_require_a_sealed_candidate_head_set_or_structured_no_applicable(self):
        payload = {
            "kind": "commands",
            "candidate_head": self.head,
            "commands": [
                {
                    "command_id": "final-unit",
                    "command_role": "final",
                    "argv": list(python_command("print('ok')")),
                    "cwd": ".",
                    "input_digest": self.input_digest,
                    "deadline_seconds": 10,
                }
            ],
        }
        artifact = self.evidence.declare_final_set(payload, self.head)
        loaded = self.evidence.load_final_command(artifact.digest, 0)
        self.assertEqual(loaded.command_id, "final-unit")
        with self.assertRaises(ValueError):
            self.evidence.load_final_command("a" * 64, 0)
        for invalid in (
            {"kind": "commands", "candidate_head": self.head, "commands": []},
            {"kind": "no_applicable_verification", "candidate_head": self.head, "rationale": ""},
            {"kind": "commands", "candidate_head": self.head, "commands": [{**payload["commands"][0], "cwd": "../escape"}]},
            {"kind": "commands", "candidate_head": self.head, "commands": [{**payload["commands"][0], "command_role": "affected"}]},
            {"kind": "commands", "candidate_head": "a" * 40, "commands": payload["commands"]},
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    self.evidence.declare_final_set(invalid, self.head)
        no_applicable = self.evidence.declare_final_set(
            {"kind": "no_applicable_verification", "candidate_head": self.head, "rationale": "documentation only"},
            self.head,
        )
        self.assertTrue(self.state.referenced_artifact(no_applicable.as_dict()).exists())
        (self.state.root / artifact.relative_path).write_text('{"tampered":true}', encoding="utf-8")
        with self.assertRaises(ValueError):
            self.evidence.load_final_command(artifact.digest, 0)

    def test_receipts_are_durable_before_state_reference_and_liveness_is_not_progress(self):
        receipt = self.evidence.execute(self.command(python_command("print('ok')")), candidate_head=self.head)
        self.assertTrue(self.state.referenced_artifact(receipt.artifact.as_dict()).exists())
        state = self.state.snapshot()
        self.assertIn(receipt.artifact.as_dict(), state["artifact_refs"])
        self.assertIsNone(self.evidence.record_liveness({"pid": 123, "at": "now"}))
        self.assertNotIn("material_progress", self.state.snapshot())

    def test_receipt_reuse_rejects_tampering_and_nonzero_success_exit(self):
        first = self.evidence.execute(self.command(python_command("print('ok')")), candidate_head=self.head)
        forged = {
            "schema_version": 1,
            "identity": {"forged": True},
            "identity_digest": "f" * 64,
            "outcome": "success",
            "exit_code": 7,
            "stdout_tail": "",
            "stderr_tail": "",
            "process": {},
        }
        forged["identity_digest"] = evidence_module.sha256_json(forged["identity"])
        artifact = self.state.put_artifact("verification_receipt", forged)
        self.evidence._append_artifact(artifact)
        self.assertIsNone(self.evidence.reusable_success(forged["identity_digest"]))

        receipt_path = self.state.root / first.artifact.relative_path
        receipt_path.write_text('{"tampered":true}', encoding="utf-8")
        self.assertIsNone(self.evidence.reusable_success(first.identity_digest))

    def test_execution_uses_the_identity_resolved_executable_once(self):
        command = self.command(python_command("print('ok')"))
        opened = process_module.open_executable(
            sys.executable, cwd=self.root, env=self.environment
        )
        result = ProcessResult(
            kind="success", exit_code=0, stdout_tail=b"", stderr_tail=b"",
            stdout_digest="a" * 64, stderr_digest="b" * 64,
            started_at="start", finished_at="finish", forced_kill=False,
        )
        with (
            mock.patch.object(evidence_module, "open_executable", return_value=opened) as open_exact,
            mock.patch.object(evidence_module, "run_exact", return_value=result) as launch,
        ):
            self.evidence.execute(command, candidate_head=self.head)
        open_exact.assert_called_once()
        self.assertIs(launch.call_args.kwargs["opened_executable"], opened)
        self.assertEqual(launch.call_args.args[0], command.argv)
        self.assertEqual(opened.fd, -1)

    def test_redacted_invalid_utf8_tails_stay_inside_configured_byte_cap(self):
        evidence = EvidenceStore(self.state, self.workspace, self.environment, output_limit=32)
        command = self.command(
            python_command(
                "import os; os.write(1, b'x' * 128 + b' SECRET_TOKEN=super-secret' + b'\\xff' * 7); "
                "os.write(2, b'x' * 128 + b' SECRET_TOKEN=super-secret' + b'\\xff' * 7)"
            )
        )
        receipt = evidence.execute(command, candidate_head=self.head)
        payload = json.loads(self.state.referenced_artifact(receipt.artifact.as_dict()).read_text())
        self.assertLessEqual(len(payload["stdout_tail"].encode("utf-8")), 32)
        self.assertLessEqual(len(payload["stderr_tail"].encode("utf-8")), 32)
        self.assertNotIn("super-secret", payload["stdout_tail"] + payload["stderr_tail"])

    def test_opened_executable_fd_runs_sealed_bytes_after_path_replacement(self):
        executable = self.root / "sealed-python"
        replacement = self.root / "replacement"
        executable.write_text("#!/bin/sh\nprintf sealed\n", encoding="utf-8")
        executable.chmod(0o700)
        replacement.write_text("#!/bin/sh\nprintf replaced\n", encoding="utf-8")
        replacement.chmod(0o700)
        opened = process_module.open_executable(
            str(executable), cwd=self.root, env=self.environment
        )
        snapshot = opened.launch_path
        snapshot_directory = snapshot.parent
        self.assertNotEqual(snapshot_directory, self.root)
        self.assertEqual(snapshot_directory.stat().st_mode & 0o777, 0o700)
        try:
            os.replace(replacement, executable)
            result = process_module.run_exact(
                (str(executable),),
                cwd=self.root,
                env=self.environment,
                deadline_seconds=2,
                opened_executable=opened,
            )
            self.assertEqual(result.kind, "success")
            self.assertEqual(result.stdout_tail, b"sealed")
        finally:
            descriptor = opened.fd
            opened.close()
        with self.assertRaises(OSError):
            os.fstat(descriptor)
        self.assertFalse(snapshot.exists())
        self.assertFalse(snapshot_directory.exists())

    def test_open_executable_and_group_observation_fail_closed(self):
        with mock.patch.object(process_module.os, "open", side_effect=OSError("blocked")):
            with self.assertRaises(ValueError):
                process_module.open_executable(sys.executable, cwd=self.root, env=self.environment)
        failed_ps = subprocess.CompletedProcess(
            ("/bin/ps",), 1, stdout=b"", stderr=b"blocked"
        )
        with mock.patch.object(
            process_module.subprocess, "run", return_value=failed_ps
        ):
            with self.assertRaises(RuntimeError):
                process_module._observe_group(12345)


if __name__ == "__main__":
    unittest.main()
