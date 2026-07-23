import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from plan_runner.git_ops import GitWorkspace, sanitized_child_env  # noqa: E402


def git(cwd, *args):
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


class ClaudeGitWorkspaceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        git(self.source, "init")
        git(self.source, "config", "user.email", "tests@example.invalid")
        git(self.source, "config", "user.name", "Claude Runner Tests")
        (self.source / "file.txt").write_text("base\n")
        git(self.source, "add", "file.txt")
        git(self.source, "commit", "-m", "base")
        self.worktree = self.root / "worktree"
        self.branch = "claude-plan/test-run"

    def tearDown(self):
        self.temp.cleanup()

    def test_create_requires_clean_source_and_exact_registered_branch(self):
        (self.source / "dirty.txt").write_text("dirty")
        with self.assertRaisesRegex(ValueError, "clean"):
            GitWorkspace.create(self.source, self.worktree, self.branch)
        (self.source / "dirty.txt").unlink()
        workspace = GitWorkspace.create(self.source, self.worktree, self.branch)
        self.assertEqual(workspace.observe().branch, self.branch)
        with self.assertRaises(ValueError):
            GitWorkspace.open(self.source, self.worktree, "claude-plan/wrong")

    def test_tree_digest_tracks_worktree_index_and_untracked_bytes(self):
        workspace = GitWorkspace.create(self.source, self.worktree, self.branch)
        clean = workspace.observe()
        self.assertTrue(clean.clean)
        (self.worktree / "file.txt").write_text("changed")
        changed = workspace.observe()
        self.assertFalse(changed.clean)
        self.assertNotEqual(changed.tree_digest, clean.tree_digest)
        git(self.worktree, "add", "file.txt")
        staged = workspace.observe()
        self.assertNotEqual(staged.tree_digest, changed.tree_digest)
        (self.worktree / "extra.txt").write_text("extra")
        self.assertNotEqual(workspace.observe().tree_digest, staged.tree_digest)

    def test_final_identity_rejects_dirty_head_ancestry_and_protected_ref_drift(self):
        workspace = GitWorkspace.create(self.source, self.worktree, self.branch)
        start = workspace.observe().head
        (self.worktree / "file.txt").write_text("dirty")
        with self.assertRaisesRegex(ValueError, "clean"):
            workspace.require_clean_ancestor(start)
        git(self.worktree, "checkout", "--", "file.txt")
        git(self.source, "branch", "protected", start)
        # protected set changed after workspace creation
        with self.assertRaisesRegex(ValueError, "protected"):
            workspace.require_clean_ancestor(start)

    def test_child_environment_preserves_only_anthropic_auth_and_disables_push(self):
        env = {
            "PATH": os.environ.get("PATH", ""),
            "ANTHROPIC_API_KEY": "provider-secret",
            "OPENAI_API_KEY": "remove",
            "GITHUB_TOKEN": "remove",
            "SSH_AUTH_SOCK": "/tmp/agent",
            "CLAUDECODE": "nested",
        }
        clean = sanitized_child_env(
            env,
            provider_auth_prefixes=("ANTHROPIC_",),
            remotes=["origin", "backup"],
            run_id="claude-run",
        )
        self.assertEqual(clean["ANTHROPIC_API_KEY"], "provider-secret")
        for forbidden in ("OPENAI_API_KEY", "GITHUB_TOKEN", "SSH_AUTH_SOCK"):
            self.assertNotIn(forbidden, clean)
        self.assertEqual(clean["GIT_TERMINAL_PROMPT"], "0")
        self.assertEqual(clean["GIT_CONFIG_COUNT"], "2")
        self.assertTrue(all("disabled://plan-runner/claude-run/" in clean[f"GIT_CONFIG_VALUE_{i}"] for i in range(2)))

    def test_remote_control_characters_are_rejected(self):
        with self.assertRaises(ValueError):
            sanitized_child_env({}, provider_auth_prefixes=("ANTHROPIC_",), remotes=["bad\nname"], run_id="x")


if __name__ == "__main__":
    unittest.main()
