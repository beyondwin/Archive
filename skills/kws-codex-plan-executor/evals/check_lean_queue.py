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
from cpe_runtime.contracts import ChildResult  # noqa: E402
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

    def create_engine(
        self, scenario: str, *, mapping_scenario: str = "mapping_success"
    ) -> tuple[RunStore, QueueEngine]:
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
                "CPE_FAKE_SCENARIO": mapping_scenario,
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
        self.assertEqual(
            opened[0]["payload"]["task_ids"], ["plan-01:T1", "plan-01:T2"]
        )

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

    def test_writer_lifecycle_stays_owned_until_task_report_is_published(self) -> None:
        store, engine = self.create_engine("queue_success")
        original_launch_role = engine._launch_role
        launcher_returned = threading.Event()
        release_first_engine = threading.Event()
        first_errors: list[BaseException] = []

        def pause_after_launcher(**kwargs: object) -> object:
            outcome = original_launch_role(**kwargs)  # type: ignore[arg-type]
            if kwargs.get("role") == "task_agent":
                launcher_returned.set()
                if not release_first_engine.wait(timeout=5):
                    raise RuntimeError("timed out waiting to release first engine")
            return outcome

        engine._launch_role = pause_after_launcher  # type: ignore[method-assign]
        second_launcher = ChildLauncher(
            schema_path=SKILL_ROOT / "templates" / "child-result-schema.json",
            timeout_seconds=10,
            environ=engine.launcher.environ,
        )
        second_engine = QueueEngine(store, engine.worktree, second_launcher)

        def run_first() -> None:
            try:
                engine.tick()
            except BaseException as exc:  # pragma: no cover - assertion reports detail
                first_errors.append(exc)

        thread = threading.Thread(target=run_first)
        thread.start()
        self.assertTrue(launcher_returned.wait(timeout=5))
        try:
            with self.assertRaisesRegex(ValueError, "writer lease"):
                second_engine.tick()
        finally:
            release_first_engine.set()
            thread.join(timeout=10)
        self.assertFalse(thread.is_alive())
        self.assertEqual(first_errors, [])
        reports = [
            event["payload"]
            for event in self.lifecycle_events(store)
            if event["event_type"] == "task.reported"
        ]
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0]["status"], "completed")

    def test_replay_rejects_task_report_for_a_different_active_attempt(self) -> None:
        store, engine = self.create_engine("queue_success")
        evidence_path = "reports/plan-01-T1/mismatched-report.md"
        store.put_artifact(evidence_path, b"mismatched report regression\n")
        engine._append_task_started(
            task_id="plan-01:T1",
            attempt_id="plan-01-T1-attempt-0001",
            role="task_agent",
            strategy_key="initial",
            baseline_commit=engine.worktree.head(),
            evidence_sha256="a" * 64,
        )
        store.append_event(
            "task.reported",
            {
                "task_id": "plan-01:T1",
                "attempt_id": "plan-01-T1-attempt-9999",
                "status": "failed",
                "strategy_key": "initial",
                "artifact_paths": [evidence_path],
            },
        )
        with self.assertRaisesRegex(ValueError, "active attempt"):
            store.replay()

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

    def test_resume_reconciles_clean_unreported_writer_commit_without_task_redispatch(
        self,
    ) -> None:
        store, engine = self.create_engine("queue_success")
        original_append = engine._append_task_result
        interrupted = False

        def interrupt_after_writer(*args: object, **kwargs: object) -> None:
            nonlocal interrupted
            if not interrupted:
                interrupted = True
                raise RuntimeError("interrupt before task.reported")
            original_append(*args, **kwargs)

        engine._append_task_result = interrupt_after_writer  # type: ignore[method-assign]
        with self.assertRaisesRegex(RuntimeError, "before task.reported"):
            engine.tick()
        advanced_head = engine.worktree.head()
        active = store.replay()["tasks"]["plan-01:T1"]["active_attempt"]
        self.assertNotEqual(active["baseline_commit"], advanced_head)
        self.assertRegex(active["evidence_sha256"], r"^[0-9a-f]{64}$")

        engine._append_task_result = original_append  # type: ignore[method-assign]
        engine.launcher.environ["CPE_FAKE_SCENARIO"] = "queue_ordinary_failure"
        self.assertEqual(engine.tick(), "plan-01:T1")
        roles = [
            item["role"]
            for item in self.invocations()
            if item["role"] not in {"document_mapper", "program_mapper"}
        ]
        self.assertEqual(roles.count("task_agent"), 1)
        self.assertEqual(roles, ["task_agent", "investigator", "fix_agent", "reviewer"])
        recovered = [
            event
            for event in self.lifecycle_events(store)
            if event["event_type"] == "task.reported"
        ][0]["payload"]
        self.assertEqual(recovered["status"], "interrupted")
        self.assertEqual(recovered["commit"], advanced_head)
        self.assertTrue(any(path.endswith("interrupted.patch") for path in recovered["artifact_paths"]))

    def test_resume_interrupted_task_agent_from_preserved_evidence(self) -> None:
        store, engine = self.create_engine("queue_success")
        original_append = engine._append_task_result

        def interrupt_before_report(*args: object, **kwargs: object) -> None:
            raise RuntimeError("interrupt before initial task report")

        engine._append_task_result = interrupt_before_report  # type: ignore[method-assign]
        with self.assertRaisesRegex(RuntimeError, "initial task report"):
            engine.tick()
        engine._append_task_result = original_append  # type: ignore[method-assign]

        original_investigation = engine._run_investigation

        def interrupt_after_interrupted_report(*args: object, **kwargs: object) -> object:
            raise RuntimeError("interrupt after interrupted task report")

        engine._run_investigation = interrupt_after_interrupted_report  # type: ignore[method-assign]
        with self.assertRaisesRegex(RuntimeError, "interrupted task report"):
            engine.tick()
        engine._run_investigation = original_investigation  # type: ignore[method-assign]
        interrupted = store.replay()["tasks"]["plan-01:T1"]["attempts"][-1]
        self.assertEqual(interrupted["status"], "interrupted")

        engine.launcher.environ["CPE_FAKE_SCENARIO"] = "queue_ordinary_failure"
        self.assertEqual(engine.tick(), "plan-01:T1")
        roles = [
            item["role"]
            for item in self.invocations()
            if item["role"] not in {"document_mapper", "program_mapper"}
        ]
        self.assertEqual(roles, ["task_agent", "investigator", "fix_agent", "reviewer"])

    def test_resume_interrupted_fix_agent_from_preserved_evidence(self) -> None:
        store, engine = self.create_engine("queue_review_fix")
        original_append = engine._append_task_result
        interrupted = False

        def interrupt_fix_before_report(
            result: ChildResult, *args: object, **kwargs: object
        ) -> None:
            nonlocal interrupted
            if result.role == "fix_agent" and not interrupted:
                interrupted = True
                raise RuntimeError("interrupt before fix report")
            original_append(result, *args, **kwargs)  # type: ignore[arg-type]

        engine._append_task_result = interrupt_fix_before_report  # type: ignore[method-assign]
        with self.assertRaisesRegex(RuntimeError, "before fix report"):
            engine.tick()
        engine._append_task_result = original_append  # type: ignore[method-assign]

        original_investigation = engine._run_investigation

        def interrupt_after_interrupted_report(*args: object, **kwargs: object) -> object:
            raise RuntimeError("interrupt after interrupted fix report")

        engine._run_investigation = interrupt_after_interrupted_report  # type: ignore[method-assign]
        with self.assertRaisesRegex(RuntimeError, "interrupted fix report"):
            engine.tick()
        engine._run_investigation = original_investigation  # type: ignore[method-assign]
        last_attempt = store.replay()["tasks"]["plan-01:T1"]["attempts"][-1]
        self.assertEqual(last_attempt["role"], "fix_agent")
        self.assertEqual(last_attempt["status"], "interrupted")

        engine.launcher.environ["CPE_FAKE_SCENARIO"] = "queue_ordinary_failure"
        self.assertEqual(engine.tick(), "plan-01:T1")
        roles = [
            item["role"]
            for item in self.invocations()
            if item["role"] not in {"document_mapper", "program_mapper"}
        ]
        self.assertEqual(roles.count("task_agent"), 1)
        self.assertEqual(roles.count("fix_agent"), 2)
        self.assertEqual(roles.count("investigator"), 1)

    def test_resume_after_reported_fix_reviews_expanded_range_without_refixing(self) -> None:
        store, engine = self.create_engine("queue_fix_review_crash")
        original = engine.worktree.head()

        with self.assertRaisesRegex(ValueError, "Codex child exited"):
            engine.tick()
        reports = [
            event["payload"]
            for event in self.lifecycle_events(store)
            if event["event_type"] == "task.reported"
        ]
        self.assertEqual([report["status"] for report in reports], ["completed", "completed"])
        fix_commit = reports[-1]["commit"]

        engine.launcher.environ["CPE_FAKE_SCENARIO"] = "queue_success"
        self.assertEqual(engine.tick(), "plan-01:T1")
        invocations = [
            item
            for item in self.invocations()
            if item["role"] not in {"document_mapper", "program_mapper"}
        ]
        self.assertEqual([item["role"] for item in invocations].count("fix_agent"), 1)
        resumed_review = invocations[-1]
        self.assertEqual(resumed_review["role"], "reviewer")
        patch_paths = [
            Path(path) for path in resumed_review["input_paths"] if path.endswith(".patch")
        ]
        self.assertEqual(len(patch_paths), 1)
        self.assertEqual(
            patch_paths[0].read_text(encoding="utf-8"),
            engine.worktree.diff(original, str(fix_commit)),
        )

    def test_repeated_identical_review_evidence_investigates_before_second_fix(self) -> None:
        store, engine = self.create_engine("queue_repeated_review_finding")

        self.assertEqual(engine.tick(), "plan-01:T1")
        roles = [
            item["role"]
            for item in self.invocations()
            if item["role"] not in {"document_mapper", "program_mapper"}
        ]
        self.assertEqual(
            roles,
            [
                "task_agent",
                "reviewer",
                "fix_agent",
                "reviewer",
                "investigator",
                "fix_agent",
                "reviewer",
            ],
        )
        reviews = [
            event["payload"]
            for event in self.lifecycle_events(store)
            if event["event_type"] == "review.reported"
        ]
        self.assertEqual(reviews[0]["evidence_sha256"], reviews[1]["evidence_sha256"])
        starts = [
            event["payload"]
            for event in self.lifecycle_events(store)
            if event["event_type"] == "task.started"
        ]
        self.assertEqual(starts[1]["evidence_sha256"], reviews[0]["evidence_sha256"])
        self.assertEqual(starts[2]["evidence_sha256"], reviews[1]["evidence_sha256"])
        self.assertNotIn("review-consolidated-2", starts[2]["strategy_key"])

    def test_replay_rejects_nonadjacent_strategy_evidence_cycle(self) -> None:
        store, engine = self.create_engine("queue_success")
        task = engine._task_by_id("plan-01:T1")
        finding_path = "reviews/plan-01-T1/immutable-finding.json"
        store.put_artifact(finding_path, b'{"finding":"same bytes"}')

        self.assertIsNotNone(
            engine._run_consolidated_fix(task, [finding_path], strategy_key="strategy-A")
        )
        self.assertIsNotNone(
            engine._run_consolidated_fix(task, [finding_path], strategy_key="strategy-B")
        )
        with self.assertRaisesRegex(ValueError, "previously attempted strategy and evidence"):
            engine._run_consolidated_fix(task, [finding_path], strategy_key="strategy-A")
        fixes = [
            item
            for item in self.invocations()
            if item["role"] == "fix_agent"
        ]
        self.assertEqual(len(fixes), 2)

    def test_historical_investigator_strategy_is_rejected_before_writer(self) -> None:
        store, engine = self.create_engine("queue_historical_strategy")
        task_id = "plan-01:T1"
        evidence_path = "reports/plan-01-T1/historical-evidence.json"
        store.put_artifact(evidence_path, b'{"failure":"same evidence"}')
        evidence_sha256 = engine._artifact_evidence_digest([evidence_path])
        baseline = engine.worktree.head()
        for number, strategy in enumerate(("strategy-A", "strategy-B"), 1):
            attempt_id = f"plan-01-T1-attempt-{number:04d}"
            engine._append_task_started(
                task_id=task_id,
                attempt_id=attempt_id,
                role="fix_agent",
                strategy_key=strategy,
                baseline_commit=baseline,
                evidence_sha256=evidence_sha256,
            )
            store.append_event(
                "task.reported",
                {
                    "task_id": task_id,
                    "attempt_id": attempt_id,
                    "status": "failed",
                    "strategy_key": strategy,
                    "artifact_paths": [evidence_path],
                },
            )

        strategy, investigation_paths = engine._run_investigation(
            engine._task_by_id(task_id),
            [evidence_path],
            previous_strategy="strategy-B",
            dispatch_evidence_sha256=evidence_sha256,
        )
        recovered = engine._run_consolidated_fix(
            engine._task_by_id(task_id),
            [evidence_path, *investigation_paths],
            strategy_key=strategy,
            evidence_sha256=evidence_sha256,
        )
        self.assertIsNotNone(recovered)
        roles = [
            item["role"]
            for item in self.invocations()
            if item["role"] not in {"document_mapper", "program_mapper"}
        ]
        self.assertEqual(roles, ["investigator", "investigator", "fix_agent"])
        starts = [
            event["payload"]
            for event in self.lifecycle_events(store)
            if event["event_type"] == "task.started"
        ]
        self.assertEqual(starts[-1]["strategy_key"], "strategy-C")

    def test_invalid_authority_handoff_becomes_ordinary_recovery(self) -> None:
        store, engine = self.create_engine("queue_invalid_authority")

        self.assertEqual(engine.tick(), "plan-01:T1")
        self.assertFalse(
            any(
                event["event_type"] == "authority.opened"
                for event in store.validate_event_chain()
            )
        )
        reports = [
            event["payload"]
            for event in self.lifecycle_events(store)
            if event["event_type"] == "task.reported"
        ]
        self.assertEqual(reports[0]["status"], "failed")
        roles = [
            item["role"]
            for item in self.invocations()
            if item["role"] not in {"document_mapper", "program_mapper"}
        ]
        self.assertEqual(roles, ["task_agent", "investigator", "fix_agent", "reviewer"])

    def test_orphan_autonomy_ledger_reconciles_once_without_duplicate_investigation(
        self,
    ) -> None:
        store, engine = self.create_engine("queue_ordinary_failure")
        original_append_event = store.append_event
        interrupted = False

        def interrupt_autonomy(event_type: str, payload: object) -> object:
            nonlocal interrupted
            if event_type == "autonomy.recorded" and not interrupted:
                interrupted = True
                raise RuntimeError("interrupt after autonomy ledger fsync")
            return original_append_event(event_type, payload)  # type: ignore[arg-type]

        store.append_event = interrupt_autonomy  # type: ignore[method-assign]
        with self.assertRaisesRegex(RuntimeError, "ledger fsync"):
            engine.tick()
        self.assertEqual(len(store.autonomy_decisions()), 1)
        self.assertFalse(
            any(event["event_type"] == "autonomy.recorded" for event in store.validate_event_chain())
        )

        store.append_event = original_append_event  # type: ignore[method-assign]
        self.assertEqual(engine.tick(), "plan-01:T1")
        roles = [
            item["role"]
            for item in self.invocations()
            if item["role"] not in {"document_mapper", "program_mapper"}
        ]
        self.assertEqual(roles.count("investigator"), 1)
        self.assertEqual(len(store.autonomy_decisions()), 1)
        self.assertEqual(
            len(
                [
                    event
                    for event in store.validate_event_chain()
                    if event["event_type"] == "autonomy.recorded"
                ]
            ),
            1,
        )

    def test_authority_uses_document_edges_and_rejects_unknown_documents(self) -> None:
        store, engine = self.create_engine(
            "queue_authority", mapping_scenario="mapping_many_tasks"
        )
        engine.launcher.environ["CPE_FAKE_AFFECTED_DOCUMENT_IDS"] = '["plan-01"]'
        self.assertEqual(engine.tick(), "plan-01:T1")
        opened = [
            event["payload"]
            for event in store.validate_event_chain()
            if event["event_type"] == "authority.opened"
        ]
        self.assertEqual(opened[-1]["task_ids"], ["plan-01:T1", "plan-01:T2"])
        self.assertEqual(
            engine._next_ready_task(store.replay())["task_id"], "plan-02:T2"
        )

        with self.assertRaisesRegex(ValueError, "unknown affected document"):
            engine._open_authority(
                ChildResult(
                    role="task_agent",
                    status="waiting_authority",
                    item_id="plan-02:T2",
                    commit=None,
                    verdict=None,
                    failure_code=None,
                    authority_id="credential_required",
                    strategy_key="initial",
                    affected_document_ids=("unknown-doc",),
                    artifact_paths=("reports/plan-01-T1/attempt-1.md",),
                    summary="unknown document regression",
                ),
                "plan-02:T2",
            )
        self.assertEqual(
            len(
                [
                    event
                    for event in store.validate_event_chain()
                    if event["event_type"] == "authority.opened"
                ]
            ),
            1,
        )


if __name__ == "__main__":
    unittest.main()
