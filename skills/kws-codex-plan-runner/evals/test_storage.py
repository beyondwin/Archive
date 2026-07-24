import hashlib
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from plan_runner import storage  # noqa: E402
from plan_runner.contracts import canonical_json, sha256_json  # noqa: E402
from plan_runner.storage import (  # noqa: E402
    IntentLock,
    RunLock,
    StateStore,
    execution_intent_digest,
)


class InjectedStorageFault(RuntimeError):
    def __init__(self, stage):
        super().__init__(stage)
        self.stage = stage


class StateStoreTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.spec_a = self.root / "spec-a.md"
        self.spec_b = self.root / "spec-b.md"
        self.plan_a = self.root / "plan-a.md"
        self.plan_b = self.root / "plan-b.md"
        for path, text in (
            (self.spec_a, "spec a\n"),
            (self.spec_b, "spec b\n"),
            (self.plan_a, "plan a\n"),
            (self.plan_b, "plan b\n"),
        ):
            path.write_text(text, encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def create_store(self, root=None):
        return StateStore.create(
            root=root or self.root / "state" / "run-1",
            provider="codex",
            run_id="plan-a-12345678-1234-4234-8234-123456789abc",
            source_repository=self.repo,
            source_commit="a" * 40,
            worktree=self.root / "worktree",
            branch="codex-plan/plan-a-12345678-1234-4234-8234-123456789abc",
            specs=[self.spec_b, self.spec_a],
            plans=[self.plan_b, self.plan_a],
            immutable_config={
                "stall_seconds": 3600,
                "sandbox": "workspace-write",
                "git_identity": {
                    "name": "Runner Test",
                    "email": "runner@example.test",
                },
            },
            runner_runtime={
                "uv_version": "uv 0.11.28",
                "implementation": "cpython",
                "python_version": "3.13.14",
                "executable": "/managed/python3.13",
                "architecture": "arm64",
                "gil_disabled": False,
            },
        )

    def rewrite_state(self, store, mutate):
        state = store.snapshot()
        mutate(state)
        state_without_digest = dict(state)
        state_without_digest.pop("state_digest", None)
        state["state_digest"] = sha256_json(state_without_digest)
        (store.root / "state.json").write_bytes(canonical_json(state))

    def assert_references_exist(self, store):
        state = store.snapshot()
        for reference in state["artifact_refs"]:
            self.assertTrue(store.referenced_artifact(reference).is_file())

    def test_preserves_role_local_cli_order_and_original_digest(self):
        store = self.create_store()
        state = store.snapshot()
        specs = [item for item in state["inputs"] if item["role"] == "spec"]
        plans = [item for item in state["inputs"] if item["role"] == "plan"]
        self.assertEqual(
            [Path(item["source_path"]).name for item in specs],
            ["spec-b.md", "spec-a.md"],
        )
        self.assertEqual(
            [Path(item["source_path"]).name for item in plans],
            ["plan-b.md", "plan-a.md"],
        )
        self.assertEqual([item["input_order"] for item in specs], [0, 1])
        self.assertEqual([item["input_order"] for item in plans], [0, 1])
        self.assertEqual([item["status"] for item in state["plans"]], ["pending", "pending"])
        self.assertEqual(state["runner_runtime"]["python_version"], "3.13.14")
        self.assertEqual(
            [item["sha256"] for item in specs],
            [
                hashlib.sha256(b"spec b\n").hexdigest(),
                hashlib.sha256(b"spec a\n").hexdigest(),
            ],
        )

    def test_reopen_uses_immutable_snapshots_after_sources_change_or_disappear(self):
        modified = self.create_store(self.root / "state" / "modified")
        expected_modified = modified.snapshot()
        self.spec_a.write_text("modified after capture\n", encoding="utf-8")
        self.assertEqual(StateStore.open(modified.root).snapshot(), expected_modified)

        self.spec_a.write_text("spec a\n", encoding="utf-8")
        deleted = self.create_store(self.root / "state" / "deleted")
        expected_deleted = deleted.snapshot()
        self.spec_a.unlink()
        self.assertEqual(StateStore.open(deleted.root).snapshot(), expected_deleted)

    def test_artifact_is_durable_before_state_reference_and_orphan_is_ignored(self):
        store = self.create_store()
        orphan = store.put_artifact("receipts", {"outcome": "success"})
        reopened = StateStore.open(store.root)
        self.assertNotIn(orphan.digest, json.dumps(reopened.snapshot()))
        next_state = reopened.snapshot()
        next_state["artifact_refs"] = [orphan.as_dict()]
        committed = reopened.commit(next_state)
        self.assertEqual(committed["revision"], 2)
        self.assertTrue(reopened.referenced_artifact(orphan.as_dict()).is_file())

    def test_fault_windows_reopen_previous_then_next_complete_revision(self):
        store = self.create_store()
        previous = store.snapshot()
        pre_orphan = store.put_artifact("receipts", {"window": "before"})
        pre_state = store.snapshot()
        pre_state["artifact_refs"] = [pre_orphan.as_dict()]
        reached = []

        def fail_before(stage):
            reached.append(stage)
            if stage == storage.BEFORE_STATE_REPLACE:
                raise InjectedStorageFault(stage)

        store._fault_injector = fail_before
        with self.assertRaises(InjectedStorageFault) as raised:
            store.commit(pre_state)
        self.assertEqual(raised.exception.stage, storage.BEFORE_STATE_REPLACE)
        self.assertEqual(reached, [storage.BEFORE_STATE_REPLACE])

        reopened_previous = StateStore.open(store.root)
        self.assertEqual(reopened_previous.snapshot(), previous)
        self.assertNotIn(pre_orphan.digest, json.dumps(reopened_previous.snapshot()))
        self.assert_references_exist(reopened_previous)

        post_artifact = reopened_previous.put_artifact("receipts", {"window": "after"})
        post_state = reopened_previous.snapshot()
        post_state["artifact_refs"] = [post_artifact.as_dict()]
        reached = []

        def fail_after(stage):
            reached.append(stage)
            if stage == storage.AFTER_STATE_REPLACE:
                raise InjectedStorageFault(stage)

        reopened_previous._fault_injector = fail_after
        with self.assertRaises(InjectedStorageFault) as raised:
            reopened_previous.commit(post_state)
        self.assertEqual(raised.exception.stage, storage.AFTER_STATE_REPLACE)
        self.assertEqual(
            reached,
            [storage.BEFORE_STATE_REPLACE, storage.AFTER_STATE_REPLACE],
        )

        reopened_next = StateStore.open(store.root)
        self.assertEqual(reopened_next.snapshot()["revision"], previous["revision"] + 1)
        self.assertEqual(reopened_next.snapshot()["artifact_refs"], [post_artifact.as_dict()])
        self.assertNotIn(pre_orphan.digest, json.dumps(reopened_next.snapshot()))
        self.assert_references_exist(reopened_next)

    def test_rejects_symlink_input(self):
        link = self.root / "linked-spec.md"
        link.symlink_to(self.spec_a)
        with self.assertRaisesRegex(ValueError, "regular file"):
            StateStore.create(
                root=self.root / "state" / "bad",
                provider="codex",
                run_id="bad-12345678-1234-4234-8234-123456789abc",
                source_repository=self.repo,
                source_commit="a" * 40,
                worktree=self.root / "worktree",
                branch="codex-plan/bad-12345678-1234-4234-8234-123456789abc",
                specs=[link],
                plans=[self.plan_a],
                immutable_config={
                    "stall_seconds": 3600,
                    "sandbox": "workspace-write",
                    "git_identity": {
                        "name": "Runner Test",
                        "email": "runner@example.test",
                    },
                },
                runner_runtime={
                    "uv_version": "uv 0.11.28",
                    "implementation": "cpython",
                    "python_version": "3.13.14",
                    "executable": "/managed/python3.13",
                    "architecture": "arm64",
                    "gil_disabled": False,
                },
            )

    def test_open_rejects_symlink_root_and_non_private_directory(self):
        store = self.create_store()
        alias = self.root / "state-link"
        alias.symlink_to(store.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            StateStore.open(alias)

        os.chmod(store.root, 0o777)
        with self.assertRaisesRegex(ValueError, "private"):
            StateStore.open(store.root)

    def test_create_rejects_symlink_component_in_repository_path(self):
        repository_alias = self.root / "repository-alias"
        repository_alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            StateStore.create(
                root=self.root / "state" / "bad-repository",
                provider="codex",
                run_id="bad-12345678-1234-4234-8234-123456789abc",
                source_repository=repository_alias / "repo",
                source_commit="a" * 40,
                worktree=self.root / "worktree",
                branch="codex-plan/bad-12345678-1234-4234-8234-123456789abc",
                specs=[self.spec_a],
                plans=[self.plan_a],
                immutable_config={
                    "stall_seconds": 3600,
                    "sandbox": "workspace-write",
                    "git_identity": {
                        "name": "Runner Test",
                        "email": "runner@example.test",
                    },
                },
                runner_runtime={
                    "uv_version": "uv 0.11.28",
                    "implementation": "cpython",
                    "python_version": "3.13.14",
                    "executable": "/managed/python3.13",
                    "architecture": "arm64",
                    "gil_disabled": False,
                },
            )

    def test_open_rejects_tampered_or_invalid_state(self):
        cases = (
            ("format version", lambda state: state.__setitem__("format_version", 999)),
            ("run status", lambda state: state.__setitem__("status", "made-up")),
            ("plan status", lambda state: state["plans"][0].__setitem__("status", "made-up")),
            ("provider", lambda state: state.__setitem__("provider", "claude")),
            ("revision", lambda state: state.__setitem__("revision", 0)),
        )
        for label, mutate in cases:
            with self.subTest(label=label):
                store = self.create_store(self.root / label.replace(" ", "-"))
                self.rewrite_state(store, mutate)
                with self.assertRaises(ValueError):
                    StateStore.open(store.root)

        store = self.create_store(self.root / "digest")
        state_path = store.root / "state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["status"] = "running"
        state_path.write_bytes(canonical_json(state))
        with self.assertRaisesRegex(ValueError, "digest"):
            StateStore.open(store.root)

    def test_tampered_immutable_git_identity_is_rejected_on_open(self):
        store = self.create_store(self.root / "tampered-git-identity")
        self.rewrite_state(
            store,
            lambda state: state["immutable_config"]["git_identity"].__setitem__(
                "email", ""
            ),
        )

        with self.assertRaisesRegex(ValueError, "Git identity"):
            StateStore.open(store.root)

    def test_provider_checkpoint_requires_exact_worktree_observation(self):
        store = self.create_store(self.root / "provider-checkpoint")
        checkpoint = {
            "head": "a" * 40,
            "branch": "codex-plan/plan-a-12345678-1234-4234-8234-123456789abc",
            "porcelain_digest": "b" * 64,
            "tree_digest": "c" * 64,
            "clean": False,
        }
        state = store.snapshot()
        state["attempts"].append(
            {
                "attempt_id": str(__import__("uuid").uuid4()),
                "mode": "implementation",
                "plan_index": 0,
                "completed": True,
                "outcome": "failed",
                "post_provider_worktree": checkpoint,
                "next_strategy": "fresh_root_full_diff",
                "previous_failed_strategy": None,
            }
        )
        state["failure"] = {
            "reason_code": "provider_result_invalid",
            "partial_worktree": checkpoint,
            "partial_attempt_id": state["attempts"][-1]["attempt_id"],
            "partial_mode": "implementation",
            "next_strategy": "fresh_root_full_diff",
        }
        store.commit(state)
        self.assertEqual(
            StateStore.open(store.root).snapshot()["failure"]["partial_worktree"],
            checkpoint,
        )

        invalid = store.snapshot()
        invalid["attempts"][-1]["post_provider_worktree"] = {
            **checkpoint,
            "alternate_digest": "d" * 64,
        }
        with self.assertRaisesRegex(ValueError, "worktree observation"):
            store.commit(invalid)

    def test_rejects_stale_revision_and_unsafe_or_missing_artifact_reference(self):
        first = self.create_store()
        stale = StateStore.open(first.root)
        next_state = first.snapshot()
        first.commit(next_state)
        with self.assertRaisesRegex(ValueError, "revision"):
            stale.commit(stale.snapshot())

        unsafe = first.snapshot()
        unsafe["artifact_refs"] = [
            {
                "kind": "receipts",
                "digest": "b" * 64,
                "relative_path": "../outside.json",
            }
        ]
        with self.assertRaisesRegex(ValueError, "relative artifact path"):
            first.commit(unsafe)

        missing = first.snapshot()
        missing["artifact_refs"] = [
            {
                "kind": "receipts",
                "digest": "b" * 64,
                "relative_path": f"artifacts/receipts/{'b' * 64}.json",
            }
        ]
        with self.assertRaisesRegex(ValueError, "missing artifact"):
            first.commit(missing)

    def test_rejects_noncanonical_paths_even_when_they_resolve_inside_root(self):
        store = self.create_store()
        artifact = store.put_artifact("receipts", {"outcome": "success"})
        noncanonical_artifact = store.snapshot()
        reference = artifact.as_dict()
        reference["relative_path"] = (
            f"artifacts/receipts/./{artifact.digest}.json"
        )
        noncanonical_artifact["artifact_refs"] = [reference]
        with self.assertRaisesRegex(ValueError, "relative artifact path"):
            store.commit(noncanonical_artifact)

        state = store.snapshot()
        spec = next(item for item in state["inputs"] if item["role"] == "spec")
        state["inputs"][0]["snapshot_path"] = str(
            store.root
            / "inputs"
            / ".."
            / "inputs"
            / Path(spec["snapshot_path"]).name
        )
        self.rewrite_state(store, lambda target: target.update(state))
        with self.assertRaisesRegex(ValueError, "snapshot"):
            StateStore.open(store.root)

    def test_rejects_artifact_beneath_non_private_kind_directory(self):
        store = self.create_store()
        artifact = store.put_artifact("receipts", {"outcome": "success"})
        artifact_path = store.root / artifact.relative_path
        os.chmod(artifact_path.parent, 0o777)
        with self.assertRaisesRegex(ValueError, "private|writable"):
            store.referenced_artifact(artifact.as_dict())

    def test_rejects_every_intermediate_symlink_regardless_of_owner(self):
        real = self.root / "real"
        real.mkdir()
        target = real / "payload.json"
        target.write_text("{}", encoding="utf-8")
        alias = self.root / "alias"
        alias.symlink_to(real, target_is_directory=True)
        candidate = alias / target.name

        with mock.patch.object(storage.os, "getuid", return_value=os.getuid() + 1):
            with self.assertRaisesRegex(ValueError, "symlink"):
                storage._reject_symlink_components(candidate)

    def test_second_nonblocking_lock_is_rejected_and_release_allows_reacquire(self):
        store = self.create_store()
        lock_path = store.root / "run.lock"
        with RunLock(lock_path) as held:
            self.assertIsInstance(held, RunLock)
            with self.assertRaisesRegex(RuntimeError, "run is busy"):
                with RunLock(lock_path):
                    self.fail("second lock must not be acquired")
        with RunLock(lock_path):
            pass

    def test_execution_intent_digest_is_ordered_and_profile_independent(self):
        common_dir = self.root / "common"
        common_dir.mkdir()

        first = execution_intent_digest(
            source_common_dir=common_dir,
            starting_commit="a" * 40,
            specs=[self.spec_a, self.spec_b],
            plans=[self.plan_a, self.plan_b],
        )
        same_inputs = execution_intent_digest(
            source_common_dir=common_dir,
            starting_commit="a" * 40,
            specs=[self.spec_a, self.spec_b],
            plans=[self.plan_a, self.plan_b],
        )
        reversed_plans = execution_intent_digest(
            source_common_dir=common_dir,
            starting_commit="a" * 40,
            specs=[self.spec_a, self.spec_b],
            plans=[self.plan_b, self.plan_a],
        )

        self.assertEqual(first, same_inputs)
        self.assertNotEqual(first, reversed_plans)

    def test_create_rejects_input_changed_after_intent_was_computed(self):
        common_dir = self.root / "common"
        common_dir.mkdir()
        intent = execution_intent_digest(
            source_common_dir=common_dir,
            starting_commit="a" * 40,
            specs=[self.spec_a],
            plans=[self.plan_a],
        )
        self.plan_a.write_text("changed after admission digest\n", encoding="utf-8")
        run_root = self.root / "state" / "run-1"

        with self.assertRaisesRegex(ValueError, "input changed"):
            StateStore.create(
                root=run_root,
                provider="codex",
                run_id="plan-a-12345678-1234-4234-8234-123456789abc",
                source_repository=self.repo,
                source_commit="a" * 40,
                worktree=self.root / "worktree",
                branch="codex-plan/plan-a-12345678-1234-4234-8234-123456789abc",
                specs=[self.spec_a],
                plans=[self.plan_a],
                immutable_config={
                    "git_common_dir": str(common_dir),
                    "execution_intent_digest": intent,
                    "git_identity": {
                        "name": "Runner Test",
                        "email": "runner@example.test",
                    },
                },
                runner_runtime={
                    "uv_version": "uv test",
                    "implementation": "cpython",
                    "python_version": "3.13.9",
                    "executable": "/managed/python3.13",
                    "architecture": "arm64",
                    "gil_disabled": False,
                },
            )

        self.assertFalse(run_root.exists())

    def test_intent_lock_serializes_waiters_instead_of_reporting_busy(self):
        lock_home = self.root / "intent-locks"
        lock_home.mkdir(mode=0o700)
        entered = threading.Event()
        release = threading.Event()
        order = []

        def holder():
            with IntentLock(lock_home, "a" * 64):
                order.append("holder")
                entered.set()
                release.wait(timeout=5)

        def waiter():
            entered.wait(timeout=5)
            with IntentLock(lock_home, "a" * 64):
                order.append("waiter")

        first = threading.Thread(target=holder)
        second = threading.Thread(target=waiter)
        first.start()
        second.start()
        self.assertTrue(entered.wait(timeout=5))
        self.assertEqual(order, ["holder"])
        release.set()
        first.join(timeout=5)
        second.join(timeout=5)

        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(order, ["holder", "waiter"])

    def test_intent_scan_stops_after_bound_plus_one_before_sorting(self):
        state_home = self.root / "state-home"
        state_home.mkdir(mode=0o700)
        yielded = 0

        def candidates():
            nonlocal yielded
            for index in range(storage._MAX_INTENT_SCAN_ROOTS + 100):
                yielded += 1
                yield state_home / f"not-a-run-{index}"

        with mock.patch.object(Path, "iterdir", return_value=candidates()):
            with self.assertRaisesRegex(ValueError, "scan limit"):
                storage.find_execution_intent(state_home, "a" * 64)

        self.assertEqual(yielded, storage._MAX_INTENT_SCAN_ROOTS + 1)


if __name__ == "__main__":
    unittest.main()
