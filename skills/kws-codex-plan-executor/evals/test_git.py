"""Focused contract tests for CPE's mechanical Git boundary."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from cpe_runtime.git import (
    _parse_ident,
    adopt_worktree,
    capture_git_identity,
    create_worktree,
    observe_git,
    require_ancestor,
)


class GitContractTests(unittest.TestCase):
    """Git helpers validate facts without choosing integration policy."""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.temp = Path(self.temporary_directory.name)
        self.original_environment = os.environ.copy()
        self.home = self.temp / "home"
        self.home.mkdir()
        os.environ.update(
            {
                "HOME": str(self.home),
                "CODEX_HOME": str(self.home / ".codex"),
                "XDG_CONFIG_HOME": str(self.home / ".config"),
                "GIT_CONFIG_NOSYSTEM": "1",
            }
        )
        self.repository = self.temp / "repository"
        self.repository.mkdir()
        self.git("init", "-q", "--initial-branch=main")
        self.git("config", "user.name", "CPE Canary")
        self.git("config", "user.email", "cpe@example.invalid")
        (self.repository / "tracked.txt").write_text("initial\n", encoding="utf-8")
        self.git("add", "tracked.txt")
        self.git("commit", "-q", "-m", "initial")
        self.base = self.git("rev-parse", "HEAD")

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self.original_environment)
        self.temporary_directory.cleanup()

    def run_git(
        self,
        cwd: Path,
        *args: str,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=check,
            capture_output=True,
            text=True,
        )

    def git(self, *args: str, check: bool = True) -> str:
        return self.run_git(self.repository, *args, check=check).stdout.strip()

    def git_at(self, cwd: Path, *args: str, check: bool = True) -> str:
        return self.run_git(cwd, *args, check=check).stdout.strip()

    def make_linked_worktree(
        self,
        *,
        name: str = "adopted",
        repository: Path | None = None,
    ) -> Path:
        source = repository or self.repository
        worktree = self.temp / name
        self.run_git(
            source,
            "worktree",
            "add",
            "-q",
            "-b",
            f"codex/{name}",
            str(worktree),
            "HEAD",
        )
        return worktree

    def write_v3_manifest(self, run_id: str, worktree: Path) -> Path:
        run_root = Path(os.environ["CODEX_HOME"]) / "cpe-v3" / "runs" / run_id
        run_root.mkdir(parents=True)
        manifest = {
            "format_version": 5,
            "contract_version": 3,
            "run_id": run_id,
            "source_repository": str(self.repository.resolve()),
            "base_commit": self.base,
            "branch": "codex/adopted",
            "worktree": str(worktree),
            "documents": [
                {
                    "order": 1,
                    "source_path": str(self.temp / "source.md"),
                    "snapshot_path": str(run_root / "inputs" / "document-001-source.md"),
                    "sha256": "a" * 64,
                    "byte_length": 1,
                }
            ],
            "superpowers_skill": "subagent-driven-development",
            "git_identity": {
                "author_name": "CPE Canary",
                "author_email": "cpe@example.invalid",
                "committer_name": "CPE Canary",
                "committer_email": "cpe@example.invalid",
            },
            "sandbox": "workspace-write",
            "approval_policy": "never",
            "integration_policy": "local-handoff-only",
            "remote_action_policy": "forbidden",
            "created_at": "2026-07-25T00:00:00Z",
        }
        (run_root / "manifest.json").write_text(
            json.dumps(manifest),
            encoding="utf-8",
        )
        return run_root

    def test_capture_git_identity_reads_only_name_and_email(self) -> None:
        identity = capture_git_identity(self.repository)
        self.assertEqual(identity.author_name, "CPE Canary")
        self.assertEqual(identity.author_email, "cpe@example.invalid")
        self.assertEqual(identity.committer_name, "CPE Canary")
        self.assertEqual(identity.committer_email, "cpe@example.invalid")

    def test_missing_git_identity_blocks_before_worktree_creation(self) -> None:
        self.git("config", "--unset-all", "user.name", check=False)
        self.git("config", "--unset-all", "user.email", check=False)
        with self.assertRaisesRegex(ValueError, "Git identity"):
            capture_git_identity(self.repository)
        self.assertFalse((self.temp / "worktrees").exists())

    def test_identity_parser_rejects_control_empty_and_oversized_values(self) -> None:
        self.assertEqual(
            _parse_ident("CPE Canary <cpe@example.invalid> 1721870000 +0900"),
            ("CPE Canary", "cpe@example.invalid"),
        )
        for ident in (
            " <cpe@example.invalid> 1721870000 +0900",
            "CPE Canary <> 1721870000 +0900",
            "CPE\nCanary <cpe@example.invalid> 1721870000 +0900",
            "CPE\x00Canary <cpe@example.invalid> 1721870000 +0900",
            f"{'x' * 321} <cpe@example.invalid> 1721870000 +0900",
        ):
            with self.subTest(ident=ident[:40]):
                with self.assertRaisesRegex(ValueError, "Git identity"):
                    _parse_ident(ident)

    def test_create_worktree_uses_exact_base_and_run_branch(self) -> None:
        assignment = create_worktree(
            self.repository,
            base=self.base,
            run_id="cpe-0123456789abcdef",
            root=self.temp / "worktrees",
        )
        self.assertEqual(assignment.repository, self.repository.resolve())
        self.assertEqual(
            assignment.worktree,
            (self.temp / "worktrees" / "cpe-0123456789abcdef").resolve(),
        )
        self.assertEqual(assignment.branch, "codex/cpe-0123456789abcdef")
        self.assertEqual(assignment.base_commit, self.base)
        self.assertEqual(assignment.git_common_dir, (self.repository / ".git").resolve())
        self.assertEqual(self.git_at(assignment.worktree, "rev-parse", "HEAD"), self.base)

    def test_failed_creation_removes_only_the_new_path_and_branch(self) -> None:
        run_id = "cpe-1111111111111111"
        worktree = (self.temp / "worktrees" / run_id).resolve()
        branch = f"codex/{run_id}"
        real_run = subprocess.run
        failed_once = False

        def fail_after_add(*args: object, **kwargs: object) -> subprocess.CompletedProcess:
            nonlocal failed_once
            result = real_run(*args, **kwargs)
            argv = args[0]
            if (
                not failed_once
                and isinstance(argv, list)
                and argv[1:3] == ["worktree", "add"]
            ):
                failed_once = True
                raise subprocess.CalledProcessError(1, argv)
            return result

        with mock.patch("cpe_runtime.git.subprocess.run", side_effect=fail_after_add):
            with self.assertRaises(subprocess.CalledProcessError):
                create_worktree(
                    self.repository,
                    base=self.base,
                    run_id=run_id,
                    root=self.temp / "worktrees",
                )
        self.assertFalse(worktree.exists())
        self.assertNotEqual(
            self.git("show-ref", "--verify", f"refs/heads/{branch}", check=False),
            self.base,
        )
        self.assertTrue((self.repository / "tracked.txt").exists())

    def test_pre_add_race_never_deletes_foreign_branch_or_path(self) -> None:
        run_id = "cpe-1212121212121212"
        root = self.temp / "worktrees"
        worktree = (root / run_id).resolve()
        branch = f"codex/{run_id}"
        branch_ref = f"refs/heads/{branch}"
        sentinel = worktree / "foreign.txt"
        real_run = subprocess.run
        injected = False

        def inject_foreign_artifacts() -> None:
            nonlocal injected
            if injected:
                return
            injected = True
            real_run(
                ["git", "branch", branch, self.base],
                cwd=self.repository,
                check=True,
                capture_output=True,
                text=True,
            )
            worktree.mkdir(parents=True)
            sentinel.write_text("foreign\n", encoding="utf-8")

        def race_before_claim(*args: object, **kwargs: object) -> subprocess.CompletedProcess:
            argv = args[0]
            if (
                isinstance(argv, list)
                and argv[:3] == ["git", "update-ref", "--no-deref"]
                and argv[3] == branch_ref
            ):
                inject_foreign_artifacts()
            try:
                return real_run(*args, **kwargs)
            except subprocess.CalledProcessError:
                if (
                    isinstance(argv, list)
                    and argv[:4] == ["git", "show-ref", "--verify", "--quiet"]
                    and argv[4] == branch_ref
                ):
                    inject_foreign_artifacts()
                raise

        with mock.patch("cpe_runtime.git.subprocess.run", side_effect=race_before_claim):
            with self.assertRaises(subprocess.CalledProcessError):
                create_worktree(
                    self.repository,
                    base=self.base,
                    run_id=run_id,
                    root=root,
                )

        self.assertTrue(injected)
        self.assertEqual(
            self.git("rev-parse", "--verify", f"{branch_ref}^{{commit}}"),
            self.base,
        )
        self.assertTrue(worktree.is_dir())
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "foreign\n")

    def test_adopt_dirty_worktree_without_mutating_it(self) -> None:
        worktree = self.make_linked_worktree()
        dirty = worktree / "unfinished.txt"
        dirty.write_text("preserve me", encoding="utf-8")
        tracked = worktree / "tracked.txt"
        tracked.write_text("changed\n", encoding="utf-8")
        before = {
            dirty: dirty.read_bytes(),
            tracked: tracked.read_bytes(),
        }
        assignment = adopt_worktree(
            self.repository,
            worktree=worktree,
            base=self.base,
        )
        self.assertEqual(assignment.repository, self.repository.resolve())
        self.assertEqual(assignment.worktree, worktree.resolve())
        self.assertEqual(assignment.branch, "codex/adopted")
        self.assertEqual(assignment.base_commit, self.base)
        self.assertEqual(assignment.git_common_dir, (self.repository / ".git").resolve())
        self.assertEqual({path: path.read_bytes() for path in before}, before)

    def test_adoption_rejects_non_worktree_symlink_detached_or_wrong_repository(self) -> None:
        ordinary = self.temp / "ordinary"
        ordinary.mkdir()
        adopted = self.make_linked_worktree()
        symlink = self.temp / "symlinked-worktree"
        symlink.symlink_to(adopted, target_is_directory=True)
        detached = self.temp / "detached"
        self.run_git(
            self.repository,
            "worktree",
            "add",
            "-q",
            "--detach",
            str(detached),
            self.base,
        )
        other = self.temp / "other"
        other.mkdir()
        self.run_git(other, "init", "-q", "--initial-branch=main")
        self.run_git(other, "config", "user.name", "Other")
        self.run_git(other, "config", "user.email", "other@example.invalid")
        (other / "other.txt").write_text("other\n", encoding="utf-8")
        self.run_git(other, "add", "other.txt")
        self.run_git(other, "commit", "-q", "-m", "other")
        other_worktree = self.make_linked_worktree(name="other-worktree", repository=other)
        for label, candidate in (
            ("ordinary", ordinary),
            ("symlink", symlink),
            ("detached", detached),
            ("wrong repository", other_worktree),
        ):
            with self.subTest(label=label):
                with self.assertRaisesRegex(ValueError, "worktree"):
                    adopt_worktree(
                        self.repository,
                        worktree=candidate,
                        base=self.base,
                    )

    def test_source_path_must_be_the_worktrees_common_repository(self) -> None:
        first = self.make_linked_worktree(name="first")
        second = self.make_linked_worktree(name="second")
        with self.assertRaisesRegex(ValueError, "repository"):
            adopt_worktree(first, worktree=second, base=self.base)

    def test_only_an_actively_held_valid_v3_worktree_lock_blocks_adoption(self) -> None:
        worktree = self.make_linked_worktree()
        stale_root = self.write_v3_manifest("cpe-2222222222222222", worktree.resolve())
        stale_lock = stale_root / "run.lock"
        stale_lock.touch(mode=0o600)
        adopt_worktree(self.repository, worktree=worktree, base=self.base)

        invalid_root = self.write_v3_manifest("cpe-3333333333333333", worktree.resolve())
        (invalid_root / "manifest.json").write_text("{}", encoding="utf-8")
        invalid_lock = invalid_root / "run.lock"
        invalid_lock.touch(mode=0o600)
        invalid_descriptor = os.open(invalid_lock, os.O_RDWR)
        fcntl.flock(invalid_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            adopt_worktree(self.repository, worktree=worktree, base=self.base)
        finally:
            fcntl.flock(invalid_descriptor, fcntl.LOCK_UN)
            os.close(invalid_descriptor)

        live_root = self.write_v3_manifest("cpe-4444444444444444", worktree.resolve())
        live_lock = live_root / "run.lock"
        live_lock.touch(mode=0o600)
        live_descriptor = os.open(live_lock, os.O_RDWR)
        fcntl.flock(live_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            with self.assertRaisesRegex(ValueError, "live v3 worktree lock"):
                adopt_worktree(self.repository, worktree=worktree, base=self.base)
        finally:
            fcntl.flock(live_descriptor, fcntl.LOCK_UN)
            os.close(live_descriptor)

    def test_base_and_head_must_be_commits_and_base_must_be_ancestor(self) -> None:
        worktree = self.make_linked_worktree()
        sibling = self.temp / "sibling"
        self.run_git(
            self.repository,
            "worktree",
            "add",
            "-q",
            "-b",
            "codex/sibling",
            str(sibling),
            self.base,
        )
        (sibling / "sibling.txt").write_text("sibling\n", encoding="utf-8")
        self.run_git(sibling, "add", "sibling.txt")
        self.run_git(sibling, "commit", "-q", "-m", "sibling")
        sibling_head = self.git_at(sibling, "rev-parse", "HEAD")
        for base, head in (
            ("HEAD", self.base),
            ("a" * 39, self.base),
            ("A" * 40, self.base),
            (self.base, "HEAD"),
            (sibling_head, self.base),
        ):
            with self.subTest(base=base, head=head):
                with self.assertRaisesRegex(ValueError, "Git ancestry"):
                    require_ancestor(worktree, base, head)
        self.assertIsNone(require_ancestor(worktree, self.base, self.base))

    def test_observe_git_distinguishes_tracked_dirt_and_untracked_presence(self) -> None:
        clean = observe_git(self.repository)
        self.assertTrue(clean.tracked_clean)
        self.assertFalse(clean.untracked_present)
        untracked = self.repository / "untracked.txt"
        untracked.write_text("new\n", encoding="utf-8")
        only_untracked = observe_git(self.repository)
        self.assertTrue(only_untracked.tracked_clean)
        self.assertTrue(only_untracked.untracked_present)
        (self.repository / "tracked.txt").write_text("changed\n", encoding="utf-8")
        both = observe_git(self.repository)
        self.assertFalse(both.tracked_clean)
        self.assertTrue(both.untracked_present)
        self.assertEqual(both.head, self.base)

    def test_status_digest_is_over_raw_nul_delimited_status_bytes(self) -> None:
        (self.repository / "untracked\nname.txt").write_text("raw\n", encoding="utf-8")
        raw = subprocess.run(
            ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
            cwd=self.repository,
            check=True,
            capture_output=True,
        ).stdout
        first = observe_git(self.repository)
        second = observe_git(self.repository)
        self.assertEqual(first.status_digest, hashlib.sha256(raw).hexdigest())
        self.assertEqual(second.status_digest, first.status_digest)

    def test_create_and_adopt_never_run_integration_or_replacement_commands(self) -> None:
        commands: list[list[str]] = []
        real_run = subprocess.run

        def record(*args: object, **kwargs: object) -> subprocess.CompletedProcess:
            argv = args[0]
            if isinstance(argv, list):
                commands.append(argv)
            return real_run(*args, **kwargs)

        with mock.patch("cpe_runtime.git.subprocess.run", side_effect=record):
            assignment = create_worktree(
                self.repository,
                base=self.base,
                run_id="cpe-fedcba9876543210",
                root=self.temp / "logged-worktrees",
            )
            adopt_worktree(
                self.repository,
                worktree=assignment.worktree,
                base=self.base,
            )
        forbidden = {"reset", "rebase", "merge", "cherry-pick", "checkout"}
        self.assertFalse(
            any(len(command) > 1 and command[1] in forbidden for command in commands),
            commands,
        )


if __name__ == "__main__":
    unittest.main()
