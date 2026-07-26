import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from plan_runner.git_ops import (  # noqa: E402
    GitIdentity,
    GitWorkspace,
    configured_git_identity,
    sanitized_child_env,
    sanitized_controller_env,
    validate_commit_identities,
)


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
        identity = GitIdentity("Claude Runner Tests", "tests@example.invalid")
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
            git_identity=identity,
        )
        self.assertEqual(clean["ANTHROPIC_API_KEY"], "provider-secret")
        for forbidden in ("OPENAI_API_KEY", "GITHUB_TOKEN", "SSH_AUTH_SOCK"):
            self.assertNotIn(forbidden, clean)
        self.assertEqual(clean["GIT_TERMINAL_PROMPT"], "0")
        self.assertEqual(clean["GIT_CONFIG_COUNT"], "6")
        self.assertEqual(clean["GIT_AUTHOR_NAME"], identity.name)
        self.assertEqual(clean["GIT_AUTHOR_EMAIL"], identity.email)
        self.assertEqual(clean["GIT_COMMITTER_NAME"], identity.name)
        self.assertEqual(clean["GIT_COMMITTER_EMAIL"], identity.email)
        self.assertTrue(
            all(
                "disabled://plan-runner/claude-run/"
                in clean[f"GIT_CONFIG_VALUE_{index}"]
                for index in range(4, 6)
            )
        )

    def test_remote_control_characters_are_rejected(self):
        with self.assertRaises(ValueError):
            sanitized_child_env(
                {},
                provider_auth_prefixes=("ANTHROPIC_",),
                remotes=["bad\nname"],
                run_id="x",
                git_identity=GitIdentity(
                    "Claude Runner Tests",
                    "tests@example.invalid",
                ),
            )

    def test_controller_and_child_scrub_hostile_git_routing_and_identity(self):
        hostile = {
            "PATH": os.environ["PATH"],
            "HOME": "/tmp/hostile-home",
            "GIT_DIR": "/tmp/hostile.git",
            "GIT_WORK_TREE": "/tmp/hostile-worktree",
            "GIT_INDEX_FILE": "/tmp/hostile-index",
            "GIT_OBJECT_DIRECTORY": "/tmp/hostile-objects",
            "GIT_ALTERNATE_OBJECT_DIRECTORIES": "/tmp/alternate",
            "GIT_CONFIG": "/tmp/hostile-command-config",
            "GIT_CONFIG_GLOBAL": "/tmp/hostile-config",
            "GIT_CONFIG_SYSTEM": "/tmp/hostile-config",
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "user.name",
            "GIT_CONFIG_VALUE_0": "Hostile",
            "GIT_AUTHOR_NAME": "Hostile Author",
            "GIT_AUTHOR_EMAIL": "hostile-author@example.invalid",
            "GIT_COMMITTER_NAME": "Hostile Committer",
            "GIT_COMMITTER_EMAIL": "hostile-committer@example.invalid",
        }
        controller = sanitized_controller_env(hostile)
        for key in (
            "GIT_DIR",
            "GIT_WORK_TREE",
            "GIT_INDEX_FILE",
            "GIT_OBJECT_DIRECTORY",
            "GIT_ALTERNATE_OBJECT_DIRECTORIES",
            "GIT_CONFIG",
            "GIT_CONFIG_SYSTEM",
            "GIT_CONFIG_KEY_0",
            "GIT_CONFIG_VALUE_0",
            "GIT_AUTHOR_NAME",
            "GIT_COMMITTER_NAME",
        ):
            self.assertNotIn(key, controller)
        self.assertEqual(controller["GIT_CONFIG_GLOBAL"], os.devnull)

        identity = configured_git_identity(self.source, hostile)
        self.assertEqual(
            identity,
            GitIdentity("Claude Runner Tests", "tests@example.invalid"),
        )
        child = sanitized_child_env(
            hostile,
            provider_auth_prefixes=("ANTHROPIC_",),
            remotes=["origin"],
            run_id="claude-run",
            git_identity=identity,
        )
        self.assertEqual(child["HOME"], hostile["HOME"])
        self.assertNotIn("GIT_DIR", child)
        self.assertEqual(child["GIT_AUTHOR_NAME"], identity.name)
        self.assertEqual(child["GIT_COMMITTER_NAME"], identity.name)

    def test_commit_identity_validation_checks_author_and_committer(self):
        workspace = GitWorkspace.create(
            self.source,
            self.worktree,
            self.branch,
        )
        start = workspace.observe().head
        identity = configured_git_identity(self.source)
        (self.worktree / "valid.txt").write_text("valid\n")
        git(self.worktree, "add", "valid.txt")
        git(self.worktree, "commit", "-m", "valid")
        valid_head = workspace.observe().head
        validate_commit_identities(
            self.worktree,
            start,
            valid_head,
            identity,
        )
        (self.worktree / "invalid.txt").write_text("invalid\n")
        git(self.worktree, "add", "invalid.txt")
        subprocess.run(
            ["git", "commit", "-m", "invalid"],
            cwd=self.worktree,
            env={
                **os.environ,
                "GIT_AUTHOR_NAME": "Wrong Author",
                "GIT_AUTHOR_EMAIL": "wrong@example.invalid",
                "GIT_COMMITTER_NAME": identity.name,
                "GIT_COMMITTER_EMAIL": identity.email,
            },
            check=True,
            capture_output=True,
            text=True,
        )
        with self.assertRaisesRegex(ValueError, "identity"):
            validate_commit_identities(
                self.worktree,
                start,
                workspace.observe().head,
                identity,
            )

    def test_identity_capture_uses_effective_operator_configuration(self):
        git(self.source, "config", "--unset", "user.name")
        git(self.source, "config", "--unset", "user.email")
        operator_home = self.root / "operator-home"
        operator_home.mkdir()
        (operator_home / ".gitconfig").write_text(
            "[user]\n"
            "\tname = Effective Operator\n"
            "\temail = operator@example.invalid\n",
            encoding="utf-8",
        )
        identity = configured_git_identity(
            self.source,
            {
                "PATH": os.environ["PATH"],
                "HOME": str(operator_home),
            },
        )
        self.assertEqual(
            identity,
            GitIdentity(
                "Effective Operator",
                "operator@example.invalid",
            ),
        )


if __name__ == "__main__":
    unittest.main()
