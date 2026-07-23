import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from plan_runner import git_ops  # noqa: E402
from plan_runner.git_ops import GitWorkspace, sanitized_child_env  # noqa: E402


def git(*arguments: str, cwd: Path, env=None) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *arguments],
        cwd=str(cwd),
        env=env,
        check=True,
        capture_output=True,
        text=False,
    )


def init_repository(path: Path) -> str:
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Runner Test"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "runner@example.test"], check=True)
    (path / "README.md").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-m", "base"], check=True)
    return subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


class GitWorkspaceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.start = init_repository(self.source)
        self.worktree = self.root / "run"
        self.branch = "codex-plan/run-123"

    def tearDown(self):
        self.temp.cleanup()

    def create(self):
        return GitWorkspace.create(self.source, self.worktree, self.branch)

    def test_create_rejects_dirty_source(self):
        (self.source / "dirty.txt").write_text("dirty\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "source.*clean"):
            self.create()

    def test_create_once_and_open_requires_exact_registered_worktree(self):
        workspace = self.create()
        self.assertEqual(workspace.observe().head, self.start)
        self.assertEqual(workspace.observe().branch, self.branch)
        reopened = GitWorkspace.open(self.source, self.worktree, self.branch)
        self.assertEqual(reopened.require_identity(), workspace.require_identity())
        with self.assertRaisesRegex(ValueError, "already exists|registered"):
            self.create()
        with self.assertRaisesRegex(ValueError, "registered"):
            GitWorkspace.open(self.source, self.root / "other", self.branch)

    def test_identity_detects_branch_and_actual_ancestry_drift(self):
        workspace = self.create()
        git("checkout", "-b", "other", cwd=self.worktree)
        with self.assertRaisesRegex(ValueError, "branch"):
            workspace.require_identity()
        git("checkout", self.branch, cwd=self.worktree)
        git("checkout", "--orphan", "unrelated", cwd=self.worktree)
        git("add", "--all", cwd=self.worktree)
        git("commit", "-m", "unrelated", cwd=self.worktree)
        git("branch", "-f", self.branch, "HEAD", cwd=self.worktree)
        git("checkout", self.branch, cwd=self.worktree)
        with self.assertRaisesRegex(ValueError, "ancestor"):
            workspace.require_clean_ancestor(self.start)

    def test_require_identity_detects_runtime_common_directory_drift(self):
        workspace = self.create()
        drifted_common = self.root / "drifted-common"
        drifted_common.mkdir()
        with mock.patch.object(
            git_ops,
            "_common_directory",
            side_effect=(workspace._common_dir, drifted_common),
        ):
            with self.assertRaisesRegex(ValueError, "common directory"):
                workspace.require_identity()

    def test_open_rejects_a_worktree_with_a_different_common_directory(self):
        self.create()
        other_source = self.root / "other-source"
        init_repository(other_source)
        with self.assertRaisesRegex(ValueError, "common directory"):
            GitWorkspace.open(other_source, self.worktree, self.branch)

    def test_observation_digests_track_tracked_staged_and_untracked_content(self):
        workspace = self.create()
        clean = workspace.observe()
        (self.worktree / "README.md").write_text("working\n", encoding="utf-8")
        tracked = workspace.observe()
        self.assertNotEqual(clean.porcelain_digest, tracked.porcelain_digest)
        self.assertNotEqual(clean.tree_digest, tracked.tree_digest)
        git("add", "README.md", cwd=self.worktree)
        staged = workspace.observe()
        self.assertNotEqual(tracked.tree_digest, staged.tree_digest)
        (self.worktree / "new.txt").write_text("untracked\n", encoding="utf-8")
        untracked = workspace.observe()
        self.assertNotEqual(staged.porcelain_digest, untracked.porcelain_digest)
        self.assertNotEqual(staged.tree_digest, untracked.tree_digest)
        self.assertFalse(untracked.clean)

    def test_clean_ancestor_rejects_dirty_worktree_and_protected_ref_mutation(self):
        workspace = self.create()
        (self.worktree / "README.md").write_text("dirty\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "clean"):
            workspace.require_clean_ancestor(self.start)
        git("checkout", "--", "README.md", cwd=self.worktree)
        git("branch", "protected-change", cwd=self.worktree)
        with self.assertRaisesRegex(ValueError, "protected ref"):
            workspace.require_clean_ancestor(self.start)

    def test_sanitized_environment_scrubs_credentials_and_blocks_push_without_remote_write(self):
        remote = self.root / "remote.git"
        subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
        git("remote", "add", "origin", str(remote), cwd=self.source)
        workspace = self.create()
        source_env = {
            "PATH": os.environ["PATH"],
            "SSH_AUTH_SOCK": "/tmp/agent.sock",
            "SSH_ASKPASS": "/tmp/askpass",
            "GIT_ASKPASS": "/tmp/git-askpass",
            "GH_TOKEN": "remove",
            "GITHUB_TOKEN": "remove",
            "OTHER_TOKEN": "remove",
            "OTHER_SECRET": "remove",
            "OTHER_API_KEY": "remove",
            "OPENAI_API_KEY": "preserve",
            "CODEX_TOKEN": "preserve",
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "remote.origin.pushurl",
            "GIT_CONFIG_VALUE_0": "file:///unsafe",
        }
        clean = sanitized_child_env(
            source_env,
            provider_auth_prefixes=("OPENAI_", "CODEX_"),
            remotes=("origin",),
            run_id="run-123",
        )
        for key in ("SSH_AUTH_SOCK", "SSH_ASKPASS", "GIT_ASKPASS", "GH_TOKEN", "GITHUB_TOKEN", "OTHER_TOKEN", "OTHER_SECRET", "OTHER_API_KEY"):
            self.assertNotIn(key, clean)
        self.assertEqual(clean["OPENAI_API_KEY"], "preserve")
        self.assertEqual(clean["CODEX_TOKEN"], "preserve")
        self.assertEqual(clean["GIT_TERMINAL_PROMPT"], "0")
        self.assertEqual(clean["GIT_CONFIG_COUNT"], "1")
        self.assertEqual(clean["GIT_CONFIG_KEY_0"], "remote.origin.pushurl")
        self.assertEqual(clean["GIT_CONFIG_VALUE_0"], "disabled://plan-runner/run-123/origin")
        configured_remote = git("remote", "get-url", "origin", cwd=workspace.worktree).stdout.decode().strip()
        self.assertEqual(configured_remote, str(remote))
        pushed = subprocess.run(
            ["git", "push", "origin", "HEAD"], cwd=workspace.worktree, env=clean, capture_output=True, text=True
        )
        self.assertNotEqual(pushed.returncode, 0)

    def test_sanitized_environment_rejects_control_characters_in_remote_names(self):
        with self.assertRaisesRegex(ValueError, "control characters"):
            sanitized_child_env(
                {"PATH": os.environ["PATH"]},
                provider_auth_prefixes=("OPENAI_", "CODEX_"),
                remotes=("origin\nmalicious",),
                run_id="run-123",
            )


if __name__ == "__main__":
    unittest.main()
