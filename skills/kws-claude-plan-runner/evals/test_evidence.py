import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from plan_runner.contracts import sha256_json  # noqa: E402
from plan_runner.evidence import EvidenceStore, ExactCommand  # noqa: E402
from plan_runner.git_ops import GitWorkspace  # noqa: E402
from plan_runner.storage import StateStore  # noqa: E402


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
        self.spec.write_text("spec")
        self.plan.write_text("plan")
        state_root = self.base / "state-home" / self.run_id
        state_root.parent.mkdir(mode=0o700)
        self.state = StateStore.create(
            root=state_root, provider="claude", run_id=self.run_id,
            source_repository=self.source, source_commit=self.start,
            worktree=self.worktree_path, branch=f"claude-plan/{self.run_id}",
            specs=[self.spec], plans=[self.plan],
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

    def test_final_set_is_candidate_bound_nonempty_unique_and_loadable(self):
        command = self.command([sys.executable, "-c", "pass"], role="final")
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
        artifact = self.evidence.declare_final_set(payload, self.start)
        self.assertEqual(self.evidence.load_final_command(artifact.digest, 0), command)
        with self.assertRaises(ValueError):
            self.evidence.declare_final_set(
                {"kind": "commands", "candidate_head": self.start, "commands": []},
                self.start,
            )
        no_gate = self.evidence.declare_final_set(
            {
                "kind": "no_applicable_verification",
                "candidate_head": self.start,
                "rationale": "Documentation-only update",
            },
            self.start,
        )
        self.assertTrue(no_gate.digest)

    def test_candidate_execution_requires_clean_exact_head(self):
        command = self.command([sys.executable, "-c", "pass"])
        (self.worktree_path / "dirty").write_text("x")
        with self.assertRaisesRegex(ValueError, "clean"):
            self.evidence.execute(command, candidate_head=self.start)
        with self.assertRaises(ValueError):
            self.evidence.execute(command, candidate_head="f" * 40)


if __name__ == "__main__":
    unittest.main()
