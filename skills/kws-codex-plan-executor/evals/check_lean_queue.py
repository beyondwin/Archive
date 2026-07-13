#!/usr/bin/env python3
"""Focused durable task, review, fix, and autonomous recovery queue checks."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "lean-fixtures"
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from cpe_runtime.launcher import ChildLauncher, ChildRequest  # noqa: E402
from cpe_runtime.queue import QueueEngine  # noqa: E402
from cpe_runtime.store import RunStore  # noqa: E402
from cpe_runtime.worktree import Worktree  # noqa: E402


class LeanQueueTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="cpe-lean-queue-")
        self.root = Path(self.temporary.name)
        self.home = self.root / "codex-home"
        self.repo = self.root / "repo"
        self.home.mkdir(mode=0o700)
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(
            ["git", "-C", str(self.repo), "config", "user.email", "cpe@example.invalid"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(self.repo), "config", "user.name", "CPE Eval"],
            check=True,
        )
        for name in ("spec-a.md", "spec-b.md", "plan-a.md", "plan-b.md", "program.md"):
            shutil.copyfile(FIXTURES / name, self.repo / name)
        (self.repo / "AGENTS.md").write_text(
            "# Repository Instructions\n\nUse strict TDD and commit clean handoffs.\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "-C", str(self.repo), "add", "."], check=True)
        subprocess.run(
            ["git", "-C", str(self.repo), "commit", "-q", "-m", "fixture base"],
            check=True,
        )
        self.invocation_log = self.root / "queue-invocations.jsonl"
        self.fake_state = self.root / "queue-state.json"
        self.bin_dir = self.root / "fake-bin"
        self.bin_dir.mkdir()
        fake_codex = self.bin_dir / "codex"
        source = (SKILL_ROOT / "evals" / "fake_codex.py").read_text(encoding="utf-8")
        lines = source.splitlines()
        lines[0] = f"#!{sys.executable}"
        fake_codex.write_text("\n".join(lines) + "\n", encoding="utf-8")
        fake_codex.chmod(0o700)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def create_engine(self, scenario: str) -> tuple[RunStore, QueueEngine]:
        store = RunStore.create(
            codex_home=self.home,
            workspace=self.repo,
            specs=[self.repo / "spec-a.md", self.repo / "spec-b.md"],
            plans=[self.repo / "plan-a.md", self.repo / "plan-b.md"],
            program_plan=self.repo / "program.md",
        )
        worktree = Worktree.create(
            source=self.repo,
            root=self.root / f"worktree-{scenario}",
            run_id=f"queue-{scenario}",
        )
        launcher = ChildLauncher(
            schema_path=SKILL_ROOT / "templates" / "child-result-schema.json",
            timeout_seconds=10,
            environ={
                **os.environ,
                "PATH": str(self.bin_dir),
                "CODEX_HOME": str(self.home),
                "CPE_FAKE_SCENARIO": "mapping_success",
                "CPE_FAKE_INVOCATION_LOG": str(self.invocation_log),
                "CPE_FAKE_QUEUE_STATE": str(self.fake_state),
            },
        )
        engine = QueueEngine(store, worktree, launcher)
        engine.map_program()
        launcher.environ["CPE_FAKE_SCENARIO"] = scenario
        return store, engine

    def invocations(self) -> list[dict[str, object]]:
        if not self.invocation_log.exists():
            return []
        return [
            json.loads(line)
            for line in self.invocation_log.read_text(encoding="utf-8").splitlines()
        ]

    @staticmethod
    def lifecycle_events(store: RunStore) -> list[dict[str, object]]:
        return [
            event
            for event in store.validate_event_chain()
            if event["event_type"]
            in {"task.started", "task.reported", "review.reported"}
        ]

    def test_dependencies_commit_bound_review_and_resume_do_not_redispatch(self) -> None:
        store, engine = self.create_engine("queue_success")

        self.assertEqual(engine.tick(), "plan-01:T1")
        first_events = self.lifecycle_events(store)
        self.assertEqual(
            [(event["event_type"], event["payload"]["task_id"]) for event in first_events],
            [
                ("task.started", "plan-01:T1"),
                ("task.reported", "plan-01:T1"),
                ("review.reported", "plan-01:T1"),
            ],
        )
        task_commit = first_events[1]["payload"]["commit"]
        self.assertEqual(first_events[2]["payload"]["commit"], task_commit)
        self.assertEqual(first_events[2]["payload"]["verdict"], "pass")

        self.assertEqual(engine.tick(), "plan-01:T2")
        self.assertNotEqual(engine.tick(), "plan-01:T1")
        t1_starts = [
            event
            for event in self.lifecycle_events(store)
            if event["event_type"] == "task.started"
            and event["payload"]["task_id"] == "plan-01:T1"
        ]
        self.assertEqual(len(t1_starts), 1)

    def test_review_gets_exact_range_evidence_and_fix_is_consolidated(self) -> None:
        store, engine = self.create_engine("queue_review_fix")
        start = engine.worktree.head()

        self.assertEqual(engine.tick(), "plan-01:T1")

        events = self.lifecycle_events(store)
        task_reports = [
            event for event in events if event["event_type"] == "task.reported"
        ]
        reviews = [event for event in events if event["event_type"] == "review.reported"]
        self.assertEqual(len(task_reports), 2)
        self.assertEqual(len(reviews), 2)
        self.assertEqual(reviews[0]["payload"]["verdict"], "changes_requested")
        self.assertEqual(reviews[1]["payload"]["verdict"], "pass")
        started_roles = [
            event["payload"]["role"]
            for event in events
            if event["event_type"] == "task.started"
        ]
        self.assertEqual(started_roles, ["task_agent", "fix_agent"])
        end = task_reports[-1]["payload"]["commit"]

        invocations = [
            item
            for item in self.invocations()
            if item["role"] not in {"program_mapper", "document_mapper"}
        ]
        self.assertEqual(
            [item["role"] for item in invocations],
            ["task_agent", "reviewer", "fix_agent", "reviewer"],
        )
        reviewer_inputs = invocations[-1]["input_paths"]
        diff_paths = [path for path in reviewer_inputs if path.endswith(".patch")]
        self.assertEqual(len(diff_paths), 1)
        self.assertEqual(
            Path(diff_paths[0]).read_text(encoding="utf-8"),
            engine.worktree.diff(start, end),
        )
        self.assertIn(
            "do not rerun the implementer's identical focused tests",
            invocations[-1]["prompt"],
        )
        self.assertTrue(any("findings" in path for path in invocations[2]["input_paths"]))

    def test_ordinary_failure_investigates_changes_strategy_and_records_decision(self) -> None:
        store, engine = self.create_engine("queue_ordinary_failure")

        self.assertEqual(engine.tick(), "plan-01:T1")

        roles = [
            item["role"]
            for item in self.invocations()
            if item["role"] not in {"document_mapper", "program_mapper"}
        ]
        self.assertEqual(roles, ["task_agent", "investigator", "fix_agent", "reviewer"])
        task_starts = [
            event["payload"]
            for event in self.lifecycle_events(store)
            if event["event_type"] == "task.started"
        ]
        self.assertEqual(task_starts[0]["strategy_key"], "initial")
        self.assertNotEqual(task_starts[1]["strategy_key"], "initial")
        decisions = [
            json.loads(line)
            for line in store.paths.autonomy_decisions.read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0]["affected_tasks"], ["plan-01:T1"])
        self.assertEqual(decisions[0]["selected"], "fresh root-cause investigation")
        self.assertEqual(
            [
                event["event_type"]
                for event in store.validate_event_chain()
                if event["event_type"] == "autonomy.recorded"
            ],
            ["autonomy.recorded"],
        )

    def test_only_allowlisted_authority_waits_and_test_failure_recovers(self) -> None:
        store, engine = self.create_engine("queue_authority")
        self.assertEqual(engine.tick(), "plan-01:T1")
        opened = [
            event
            for event in store.validate_event_chain()
            if event["event_type"] == "authority.opened"
        ]
        self.assertEqual(len(opened), 1)
        self.assertEqual(opened[0]["payload"]["authority_code"], "credential_required")
        self.assertEqual(opened[0]["payload"]["task_ids"], ["plan-01:T1"])

        other_home = self.root / "test-failure-home"
        other_home.mkdir(mode=0o700)
        self.home = other_home
        self.invocation_log = self.root / "test-failure-invocations.jsonl"
        self.fake_state = self.root / "test-failure-state.json"
        store2, engine2 = self.create_engine("queue_test_failure")
        self.assertEqual(engine2.tick(), "plan-01:T1")
        self.assertFalse(
            any(
                event["event_type"] == "authority.opened"
                for event in store2.validate_event_chain()
            )
        )
        self.assertTrue(
            any(item["role"] == "investigator" for item in self.invocations())
        )

    def test_unchanged_strategy_key_cannot_be_redispatched(self) -> None:
        store, engine = self.create_engine("queue_unchanged_strategy")

        with self.assertRaisesRegex(ValueError, "unchanged strategy_key"):
            engine.tick()
        roles = [
            item["role"]
            for item in self.invocations()
            if item["role"] not in {"document_mapper", "program_mapper"}
        ]
        self.assertEqual(roles, ["task_agent", "investigator"])
        self.assertFalse(
            any(
                event["event_type"] == "autonomy.recorded"
                for event in store.validate_event_chain()
            )
        )

    def test_write_roles_share_one_non_overlapping_lease(self) -> None:
        store, engine = self.create_engine("writer_hold")
        marker = self.root / "writer-started"
        engine.launcher.environ["CPE_FAKE_WRITER_MARKER"] = str(marker)
        first_outbox = store.allocate_outbox("writer-one")
        second_outbox = store.allocate_outbox("writer-two")
        second_launcher = ChildLauncher(
            schema_path=SKILL_ROOT / "templates" / "child-result-schema.json",
            timeout_seconds=10,
            environ=engine.launcher.environ,
        )

        def request(role: str, item_id: str, outbox: Path) -> ChildRequest:
            return ChildRequest(
                role=role,
                item_id=item_id,
                goal="Prove the shared writer lease.",
                input_paths=(self.repo / "plan-a.md",),
                repository=engine.worktree.source,
                worktree=engine.worktree.root,
                outbox=outbox,
                report_path=f"reports/{item_id}.md",
                applicable_skills=("using-superpowers", "test-driven-development"),
                done_when=("one clean commit exists",),
            )

        outcomes: list[object] = []

        def launch_first() -> None:
            outcomes.append(
                engine.launcher.launch(
                    request("task_agent", "writer-one", first_outbox),
                    worktree=engine.worktree,
                    store=store,
                )
            )

        thread = threading.Thread(target=launch_first)
        thread.start()
        deadline = time.monotonic() + 3
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(marker.exists())
        with self.assertRaisesRegex(ValueError, "writer lease"):
            second_launcher.launch(
                request("integration_fix_agent", "writer-two", second_outbox),
                worktree=engine.worktree,
                store=store,
            )
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(outcomes), 1)

    def test_resume_after_task_commit_runs_review_without_redispatching_writer(self) -> None:
        store, engine = self.create_engine("queue_review_crash")

        with self.assertRaisesRegex(ValueError, "Codex child exited"):
            engine.tick()
        task_reports = [
            event
            for event in self.lifecycle_events(store)
            if event["event_type"] == "task.reported"
        ]
        self.assertEqual(len(task_reports), 1)
        self.assertEqual(task_reports[0]["payload"]["status"], "completed")

        engine.launcher.environ["CPE_FAKE_SCENARIO"] = "queue_success"
        self.assertEqual(engine.tick(), "plan-01:T1")
        roles = [
            item["role"]
            for item in self.invocations()
            if item["role"] not in {"document_mapper", "program_mapper"}
        ]
        self.assertEqual(roles.count("task_agent"), 1)
        reviews = [
            event
            for event in self.lifecycle_events(store)
            if event["event_type"] == "review.reported"
        ]
        self.assertEqual(len(reviews), 1)
        self.assertEqual(reviews[0]["payload"]["verdict"], "pass")


if __name__ == "__main__":
    unittest.main()
