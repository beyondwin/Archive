import json
import os
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from plan_runner.storage import (  # noqa: E402
    AFTER_STATE_REPLACE,
    BEFORE_STATE_REPLACE,
    RunLock,
    StateStore,
)


SHA = "a" * 40


class DurableClaudeStateTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name).resolve()
        self.repo = self.base / "repo"
        self.repo.mkdir()
        self.specs = [self.base / "z-spec.md", self.base / "a-spec.md"]
        self.plans = [self.base / "two.md", self.base / "one.md"]
        for index, file in enumerate([*self.specs, *self.plans]):
            file.write_text(f"document {index}\n", encoding="utf-8")
        self.root = self.base / "private" / "run"
        self.root.parent.mkdir(mode=0o700)
        self.run_id = f"claude-{uuid.uuid4()}"

    def tearDown(self):
        self.temp.cleanup()

    def create(self):
        return StateStore.create(
            root=self.root,
            provider="claude",
            run_id=self.run_id,
            source_repository=self.repo,
            source_commit=SHA,
            worktree=self.base / "worktree",
            branch=f"claude-plan/{self.run_id}",
            specs=self.specs,
            plans=self.plans,
            immutable_config={"stall_seconds": 3600},
            runner_runtime={"implementation": "cpython"},
        )

    def test_snapshots_preserve_each_role_order_and_survive_source_removal(self):
        store = self.create()
        state = store.snapshot()
        self.assertEqual(
            [(row["role"], row["source_path"]) for row in state["inputs"]],
            [
                ("spec", str(self.specs[0])),
                ("spec", str(self.specs[1])),
                ("plan", str(self.plans[0])),
                ("plan", str(self.plans[1])),
            ],
        )
        self.assertEqual([p["status"] for p in state["plans"]], ["pending", "pending"])
        for source in [*self.specs, *self.plans]:
            source.unlink()
        reopened = StateStore.open(self.root).snapshot()
        self.assertEqual(reopened["state_digest"], state["state_digest"])
        self.assertEqual(reopened["provider"], "claude")
        self.assertTrue(reopened["repository"]["branch"].startswith("claude-plan/"))

    def test_version_two_state_contains_no_superpowers_workflow_state(self):
        state = self.create().snapshot()
        self.assertEqual(state["format_version"], 2)
        self.assertEqual(state["contract_version"], 2)
        self.assertNotIn("task_ledger", state)
        self.assertNotIn("finalization", state)
        self.assertEqual(
            set(state["plans"][0]),
            {
                "plan_id",
                "status",
                "input_order",
                "source_path",
                "snapshot_path",
                "sha256",
                "byte_length",
                "handoff_digest",
            },
        )

    def test_artifact_becomes_authoritative_only_after_state_reference(self):
        store = self.create()
        orphan = store.put_artifact("receipt", {"ok": True})
        self.assertNotIn(orphan.as_dict(), store.snapshot()["artifact_refs"])
        reopened = StateStore.open(self.root).snapshot()
        self.assertNotIn(orphan.as_dict(), reopened["artifact_refs"])
        updated = store.snapshot()
        updated["artifact_refs"].append(orphan.as_dict())
        store.commit(updated)
        self.assertEqual(StateStore.open(self.root).referenced_artifact(orphan.as_dict()).name, f"{orphan.digest}.json")

    def test_fault_boundaries_leave_complete_previous_or_next_revision(self):
        original = self.create()
        for boundary in (BEFORE_STATE_REPLACE, AFTER_STATE_REPLACE):
            seen = []
            reopened = StateStore.open(self.root)
            reopened._fault_injector = lambda point, target=boundary: (
                seen.append(point),
                (_ for _ in ()).throw(RuntimeError("crash")) if point == target else None,
            )[1]
            candidate = reopened.snapshot()
            candidate["status"] = "running"
            with self.assertRaises(RuntimeError):
                reopened.commit(candidate)
            disk = StateStore.open(self.root).snapshot()
            self.assertIn(disk["revision"], {1, 2})
            self.assertIn(boundary, seen)
            if disk["revision"] == 2:
                disk["status"] = "resumable"
                StateStore.open(self.root).commit(disk)
            else:
                self.assertEqual(original.snapshot()["state_digest"], disk["state_digest"])

    def test_symlinks_permissions_tampering_and_stale_writer_are_rejected(self):
        symlink = self.base / "linked.md"
        symlink.symlink_to(self.specs[0])
        bad_specs = self.specs
        self.specs = [symlink]
        with self.assertRaises(ValueError):
            self.create()
        self.specs = bad_specs
        first = self.create()
        second = StateStore.open(self.root)
        next_state = first.snapshot()
        next_state["status"] = "running"
        first.commit(next_state)
        stale = second.snapshot()
        stale["status"] = "blocked"
        with self.assertRaisesRegex(ValueError, "non-monotonic"):
            second.commit(stale)
        raw = json.loads((self.root / "state.json").read_text())
        raw["provider"] = "codex"
        (self.root / "state.json").write_text(json.dumps(raw))
        with self.assertRaises(ValueError):
            StateStore.open(self.root)

    def test_run_lock_is_exclusive_and_reusable(self):
        store = self.create()
        lock_path = store.root / "run.lock"
        with RunLock(lock_path):
            with self.assertRaisesRegex(RuntimeError, "busy"):
                with RunLock(lock_path):
                    pass
        with RunLock(lock_path):
            self.assertEqual(os.stat(lock_path).st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
