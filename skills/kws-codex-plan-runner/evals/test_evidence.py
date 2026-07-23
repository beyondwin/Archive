import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from plan_runner.evidence import EvidenceStore, ExactCommand  # noqa: E402
from plan_runner.git_ops import GitWorkspace  # noqa: E402
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
            deadline_seconds=0.15,
        )
        started = time.monotonic()
        receipt = self.evidence.execute(command, candidate_head=self.head)
        self.assertLess(time.monotonic() - started, 12)
        self.assertEqual(receipt.outcome, "timed_out")
        self.assertEqual(receipt.exit_code, None)
        self.assertTrue(child.exists())
        with self.assertRaises(ProcessLookupError):
            os.kill(int(child.read_text()), 0)

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

    def test_receipts_are_durable_before_state_reference_and_liveness_is_not_progress(self):
        receipt = self.evidence.execute(self.command(python_command("print('ok')")), candidate_head=self.head)
        self.assertTrue(self.state.referenced_artifact(receipt.artifact.as_dict()).exists())
        state = self.state.snapshot()
        self.assertIn(receipt.artifact.as_dict(), state["artifact_refs"])
        self.assertIsNone(self.evidence.record_liveness({"pid": 123, "at": "now"}))
        self.assertNotIn("material_progress", self.state.snapshot())


if __name__ == "__main__":
    unittest.main()
