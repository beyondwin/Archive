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


def sealed_identity(name: str = "Runner Test", email: str = "runner@example.test"):
    identity_type = getattr(git_ops, "GitIdentity", None)
    if identity_type is None:
        raise AssertionError("GitIdentity contract is missing")
    return identity_type(name=name, email=email)


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

    def test_configured_identity_is_bounded_and_required(self):
        configured_git_identity = getattr(git_ops, "configured_git_identity", None)
        self.assertIsNotNone(configured_git_identity, "configured_git_identity contract is missing")
        isolated_home = self.root / "isolated-home"
        isolated_home.mkdir()
        with mock.patch.dict(
            os.environ,
            {"HOME": str(isolated_home), "GIT_CONFIG_NOSYSTEM": "1"},
        ):
            self.assertEqual(
                configured_git_identity(self.source),
                sealed_identity(),
            )
            git("config", "--unset", "user.email", cwd=self.source)
            with self.assertRaisesRegex(RuntimeError, "configured Git identity"):
                configured_git_identity(self.source)

    def test_git_identity_round_trips_exactly_and_rejects_unbounded_or_unsafe_values(self):
        identity = sealed_identity("Sealed Name", "sealed@example.test")
        self.assertEqual(identity.as_dict(), {"name": "Sealed Name", "email": "sealed@example.test"})
        self.assertEqual(type(identity).from_mapping(identity.as_dict()), identity)
        invalid_values = (
            {"name": " Sealed Name", "email": "sealed@example.test"},
            {"name": "Sealed\nName", "email": "sealed@example.test"},
            {"name": "Sealed Name", "email": "sealed@example.test\x7f"},
            {"name": "x" * 1025, "email": "sealed@example.test"},
            {"name": "Sealed Name", "email": "sealed@example.test", "extra": "value"},
        )
        for value in invalid_values:
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "invalid .*Git identity"):
                    type(identity).from_mapping(value)

    def test_child_environment_injects_only_sealed_identity(self):
        env = sanitized_child_env(
            {
                "PATH": "/usr/bin",
                "HOME": "/Users/operator",
                "EMAIL": "ambient@example.test",
                "GIT_AUTHOR_NAME": "Ambient",
                "GIT_AUTHOR_EMAIL": "ambient@example.test",
                "GIT_AUTHOR_DATE": "2000-01-01T00:00:00+00:00",
                "GIT_COMMITTER_NAME": "Ambient",
                "GIT_COMMITTER_EMAIL": "ambient@example.test",
                "GIT_COMMITTER_DATE": "2000-01-01T00:00:00+00:00",
                "GIT_CONFIG_COUNT": "99",
                "GIT_CONFIG_GLOBAL": "/tmp/ambient-global-config",
                "GIT_CONFIG_KEY_0": "commit.gpgSign",
                "GIT_CONFIG_NOSYSTEM": "0",
                "GIT_CONFIG_SYSTEM": "/tmp/ambient-system-config",
                "GIT_CONFIG_VALUE_0": "true",
            },
            provider_auth_prefixes=("OPENAI_",),
            remotes=("origin",),
            run_id="run-1",
            git_identity=sealed_identity("Sealed Name", "sealed@example.test"),
        )
        self.assertNotIn("HOME", env)
        self.assertEqual(env["GIT_AUTHOR_NAME"], "Sealed Name")
        self.assertEqual(env["GIT_AUTHOR_EMAIL"], "sealed@example.test")
        self.assertEqual(env["GIT_COMMITTER_NAME"], "Sealed Name")
        self.assertEqual(env["GIT_COMMITTER_EMAIL"], "sealed@example.test")
        self.assertEqual(env["GIT_TERMINAL_PROMPT"], "0")
        self.assertEqual(env["GCM_INTERACTIVE"], "Never")
        self.assertEqual(env["GIT_CONFIG_COUNT"], "5")
        self.assertEqual(
            [
                (env[f"GIT_CONFIG_KEY_{index}"], env[f"GIT_CONFIG_VALUE_{index}"])
                for index in range(5)
            ],
            [
                ("user.name", "Sealed Name"),
                ("user.email", "sealed@example.test"),
                ("user.useConfigOnly", "true"),
                ("commit.gpgSign", "false"),
                ("remote.origin.pushurl", "disabled://plan-runner/run-1/origin"),
            ],
        )
        for inherited in (
            "EMAIL",
            "GIT_AUTHOR_DATE",
            "GIT_COMMITTER_DATE",
            "GIT_CONFIG_SYSTEM",
        ):
            self.assertNotIn(inherited, env)
        self.assertEqual(env["GIT_CONFIG_GLOBAL"], os.devnull)
        self.assertEqual(env["GIT_CONFIG_NOSYSTEM"], "1")

    def test_child_git_ignores_inherited_global_config_behavior(self):
        workspace = self.create()
        hooks = self.root / "ambient-hooks"
        hooks.mkdir()
        rejecting_hook = hooks / "pre-commit"
        rejecting_hook.write_text("#!/bin/sh\nexit 97\n", encoding="utf-8")
        rejecting_hook.chmod(0o700)
        global_config = self.root / "ambient-global.gitconfig"
        global_config.write_text(
            f"[core]\n\thooksPath = {hooks}\n",
            encoding="utf-8",
        )
        env = sanitized_child_env(
            {
                "PATH": os.environ["PATH"],
                "GIT_CONFIG_GLOBAL": str(global_config),
            },
            provider_auth_prefixes=("OPENAI_", "CODEX_"),
            remotes=(),
            run_id="run-123",
            git_identity=sealed_identity(),
        )

        committed = subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "global config ignored"],
            cwd=workspace.worktree,
            env=env,
            check=False,
            capture_output=True,
        )

        self.assertEqual(
            committed.returncode,
            0,
            committed.stderr.decode("utf-8", "replace"),
        )

    def test_child_environment_suppresses_repository_signing_and_seals_commit_identity(self):
        workspace = self.create()
        git("config", "commit.gpgSign", "true", cwd=workspace.worktree)
        git("config", "gpg.program", "/bin/false", cwd=workspace.worktree)
        env = sanitized_child_env(
            {"PATH": os.environ["PATH"]},
            provider_auth_prefixes=("OPENAI_", "CODEX_"),
            remotes=(),
            run_id="run-123",
            git_identity=sealed_identity("Sealed Name", "sealed@example.test"),
        )
        git("commit", "--allow-empty", "-m", "sealed", cwd=workspace.worktree, env=env)
        identity_fields = git(
            "show",
            "-s",
            "--format=%an%x00%ae%x00%cn%x00%ce",
            "HEAD",
            cwd=workspace.worktree,
        ).stdout.rstrip(b"\n").split(b"\0")
        self.assertEqual(
            identity_fields,
            [b"Sealed Name", b"sealed@example.test", b"Sealed Name", b"sealed@example.test"],
        )
        git_ops.validate_commit_identities(
            workspace.worktree,
            self.start,
            git("rev-parse", "HEAD", cwd=workspace.worktree).stdout.decode().strip(),
            sealed_identity("Sealed Name", "sealed@example.test"),
        )

    def test_candidate_commit_identity_must_match_sealed_identity(self):
        workspace = self.create()
        git(
            "-c",
            "user.name=Wrong",
            "-c",
            "user.email=wrong@example.test",
            "commit",
            "--allow-empty",
            "-m",
            "wrong",
            cwd=workspace.worktree,
        )
        env = sanitized_child_env(
            {"PATH": os.environ["PATH"]},
            provider_auth_prefixes=("OPENAI_", "CODEX_"),
            remotes=(),
            run_id="run-123",
            git_identity=sealed_identity(),
        )
        git("commit", "--allow-empty", "-m", "sealed", cwd=workspace.worktree, env=env)
        validate_commit_identities = getattr(git_ops, "validate_commit_identities", None)
        self.assertIsNotNone(validate_commit_identities, "validate_commit_identities contract is missing")
        with self.assertRaisesRegex(RuntimeError, "commit identity mismatch"):
            validate_commit_identities(
                workspace.worktree,
                self.start,
                git("rev-parse", "HEAD", cwd=workspace.worktree).stdout.decode().strip(),
                sealed_identity(),
            )

    def test_candidate_commit_identity_validation_rejects_malformed_git_output(self):
        validate_commit_identities = getattr(git_ops, "validate_commit_identities", None)
        self.assertIsNotNone(validate_commit_identities, "validate_commit_identities contract is missing")
        result = subprocess.CompletedProcess(
            args=["git"],
            returncode=0,
            stdout=b"malformed",
            stderr=b"",
        )
        with mock.patch.object(git_ops, "_git", return_value=result):
            with self.assertRaisesRegex(RuntimeError, "malformed commit identity"):
                validate_commit_identities(
                    self.source,
                    self.start,
                    self.start,
                    sealed_identity(),
                )

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

    def test_only_two_confirmed_turn_diff_namespaces_are_volatile(self):
        is_volatile_ref = getattr(git_ops, "is_volatile_ref", None)
        self.assertIsNotNone(is_volatile_ref, "is_volatile_ref contract is missing")
        self.assertTrue(is_volatile_ref("refs/codex/turn-diffs/captures/abc"))
        self.assertTrue(is_volatile_ref("refs/codex/turn-diffs/checkpoints/abc"))
        self.assertFalse(is_volatile_ref("refs/codex/other/abc"))
        self.assertFalse(is_volatile_ref("refs/codex/turn-diffs/captures"))
        self.assertFalse(is_volatile_ref("refs/codex/turn-diffs/captures-unknown/abc"))
        self.assertFalse(is_volatile_ref("refs/codex/turn-diffs/checkpoints"))
        self.assertFalse(is_volatile_ref("refs/codex/turn-diffs/checkpoints-unknown/abc"))
        self.assertFalse(is_volatile_ref("refs/heads/main"))
        self.assertFalse(is_volatile_ref("refs/tags/v1"))

    def test_unknown_codex_ref_is_not_volatile(self):
        is_volatile_ref = getattr(git_ops, "is_volatile_ref", None)
        self.assertIsNotNone(is_volatile_ref, "is_volatile_ref contract is missing")
        self.assertFalse(is_volatile_ref("refs/codex/other/abc"))

    def test_protected_refs_ignore_volatile_churn_but_keep_unknown_and_product_refs(self):
        workspace = self.create()
        git(
            "update-ref",
            "refs/codex/turn-diffs/captures/abc",
            self.start,
            cwd=self.worktree,
        )
        git(
            "update-ref",
            "refs/codex/turn-diffs/checkpoints/abc",
            self.start,
            cwd=self.worktree,
        )
        workspace.require_clean_ancestor(self.start)

        git("update-ref", "refs/codex/other/abc", self.start, cwd=self.worktree)
        with self.assertRaisesRegex(ValueError, "protected ref"):
            workspace.require_clean_ancestor(self.start)

        git("update-ref", "-d", "refs/codex/other/abc", cwd=self.worktree)
        git("update-ref", "refs/tags/product-test", self.start, cwd=self.worktree)
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
            git_identity=sealed_identity(),
        )
        for key in ("SSH_AUTH_SOCK", "SSH_ASKPASS", "GIT_ASKPASS", "GH_TOKEN", "GITHUB_TOKEN", "OTHER_TOKEN", "OTHER_SECRET", "OTHER_API_KEY"):
            self.assertNotIn(key, clean)
        self.assertEqual(clean["OPENAI_API_KEY"], "preserve")
        self.assertEqual(clean["CODEX_TOKEN"], "preserve")
        self.assertEqual(clean["GIT_TERMINAL_PROMPT"], "0")
        self.assertEqual(clean["GIT_CONFIG_COUNT"], "5")
        self.assertEqual(clean["GIT_CONFIG_KEY_4"], "remote.origin.pushurl")
        self.assertEqual(clean["GIT_CONFIG_VALUE_4"], "disabled://plan-runner/run-123/origin")
        configured_remote = git("remote", "get-url", "origin", cwd=workspace.worktree).stdout.decode().strip()
        self.assertEqual(configured_remote, str(remote))
        pushed = subprocess.run(
            ["git", "push", "origin", "HEAD"], cwd=workspace.worktree, env=clean, capture_output=True, text=True
        )
        self.assertNotEqual(pushed.returncode, 0)

    def test_sanitized_environment_strips_higher_precedence_git_config_parameters(self):
        workspace = self.create()
        clean = sanitized_child_env(
            {
                "PATH": os.environ["PATH"],
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_PARAMETERS": (
                    "'remote.origin.pushurl'='file:///unsafe' "
                    "'commit.gpgSign'='true' "
                    "'credential.helper'='store'"
                ),
            },
            provider_auth_prefixes=("OPENAI_", "CODEX_"),
            remotes=("origin",),
            run_id="run-123",
            git_identity=sealed_identity(),
        )

        self.assertEqual(
            git("config", "--get", "remote.origin.pushurl", cwd=workspace.worktree, env=clean)
            .stdout.decode()
            .strip(),
            "disabled://plan-runner/run-123/origin",
        )
        self.assertEqual(
            git("config", "--get", "commit.gpgSign", cwd=workspace.worktree, env=clean)
            .stdout.decode()
            .strip(),
            "false",
        )
        credential_helper = subprocess.run(
            ["git", "config", "--get", "credential.helper"],
            cwd=workspace.worktree,
            env=clean,
            check=False,
            capture_output=True,
        )
        self.assertEqual(credential_helper.returncode, 1)
        self.assertNotIn("GIT_CONFIG_PARAMETERS", clean)

    def test_sanitized_environment_rejects_control_characters_in_remote_names(self):
        with self.assertRaisesRegex(ValueError, "control characters"):
            sanitized_child_env(
                {"PATH": os.environ["PATH"]},
                provider_auth_prefixes=("OPENAI_", "CODEX_"),
                remotes=("origin\nmalicious",),
                run_id="run-123",
                git_identity=sealed_identity(),
            )

    def test_sanitized_environment_strips_unrelated_cloud_credentials_and_config_paths(self):
        unrelated = {
            "AWS_ACCESS_KEY_ID": "cloud-id",
            "AWS_SECRET_ACCESS_KEY": "cloud-secret",
            "AWS_PROFILE": "production",
            "AWS_SHARED_CREDENTIALS_FILE": "/tmp/aws-credentials",
            "AZURE_CLIENT_SECRET": "azure-secret",
            "BITBUCKET_APP_PASSWORD": "bitbucket-password",
            "GOOGLE_APPLICATION_CREDENTIALS": "/tmp/gcp.json",
            "CLOUDSDK_CONFIG": "/tmp/gcloud",
            "GITHUB_CONFIG_DIR": "/tmp/github",
            "GITLAB_AUTH_TOKEN": "gitlab-token",
            "OCI_CONFIG_FILE": "/tmp/oci",
            "DOCKER_CONFIG": "/tmp/docker",
            "KUBECONFIG": "/tmp/kubeconfig",
            "NETRC": "/tmp/netrc",
            "NPM_CONFIG_USERCONFIG": "/tmp/npmrc",
            "TF_CLI_CONFIG_FILE": "/tmp/terraformrc",
        }
        source_env = {
            "PATH": os.environ["PATH"],
            "LANG": "C.UTF-8",
            "HOME": "/Users/operator",
            "XDG_CONFIG_HOME": "/Users/operator/.config",
            "AWS_REGION": "ap-northeast-2",
            "GOOGLE_CLOUD_PROJECT": "example-project",
            "OPENAI_API_KEY": "provider-secret",
            "OPENAI_ORG_ID": "provider-org",
            "CODEX_HOME": "/tmp/codex",
            "DOCKER_AUTH_CONFIG": '{"auths":{"registry.example":"secret"}}',
            "DATABASE_URL": "postgres://operator:secret@database/app",
            "PGPASSWORD": "database-secret",
            "STRIPE_SECRET_KEY": "sk_live_service_secret",
            **unrelated,
        }

        clean = sanitized_child_env(
            source_env,
            provider_auth_prefixes=("OPENAI_", "CODEX_"),
            remotes=(),
            run_id="run-123",
            git_identity=sealed_identity(),
        )

        self.assertTrue(unrelated.keys().isdisjoint(clean))
        for key in (
            "HOME",
            "XDG_CONFIG_HOME",
            "DOCKER_AUTH_CONFIG",
            "DATABASE_URL",
            "PGPASSWORD",
            "STRIPE_SECRET_KEY",
        ):
            self.assertNotIn(key, clean)
        self.assertEqual(clean["OPENAI_API_KEY"], "provider-secret")
        self.assertEqual(clean["OPENAI_ORG_ID"], "provider-org")
        self.assertEqual(clean["CODEX_HOME"], "/tmp/codex")
        self.assertEqual(clean["AWS_REGION"], "ap-northeast-2")
        self.assertEqual(clean["GOOGLE_CLOUD_PROJECT"], "example-project")
        self.assertEqual(clean["LANG"], "C.UTF-8")

    def test_sanitized_environment_strips_generic_credentials_without_overmatching_keys_or_urls(self):
        credentials = {
            "DATABASE_PASSWORD": "database-secret",
            "POSTGRES_PASSWORD": "postgres-secret",
            "SMTP_PASSWORD": "smtp-secret",
            "LEGACY_PASSWD": "legacy-secret",
            "JWT_PRIVATE_KEY": "private-key",
            "STRIPE_SECRET_KEY": "stripe-secret",
            "SERVICE_ACCESS_KEY": "service-key",
            "DEPLOY_CREDENTIAL": "deploy-credential",
            "BUILD_CREDENTIALS": "build-credentials",
            "AZURE_STORAGE_CONNECTION_STRING": "azure-connection",
            "PRIVATE_DATABASE_URL": "postgres://operator:secret@database/app",
        }
        benign = {
            "CACHE_KEY": "cache-v1",
            "SORT_KEY": "created_at",
            "PUBLIC_URL": "https://example.test/app",
            "DATABASE_URL": "postgres://database/app",
            "AWS_REGION": "ap-northeast-2",
            "OPENAI_SERVICE_PASSWORD": "provider-auth",
            "CODEX_CONNECTION_STRING": "provider-config",
        }

        clean = sanitized_child_env(
            {**credentials, **benign},
            provider_auth_prefixes=("OPENAI_", "CODEX_"),
            remotes=(),
            run_id="run-123",
            git_identity=sealed_identity(),
        )

        self.assertTrue(credentials.keys().isdisjoint(clean))
        for key, value in benign.items():
            self.assertEqual(clean[key], value)


if __name__ == "__main__":
    unittest.main()
