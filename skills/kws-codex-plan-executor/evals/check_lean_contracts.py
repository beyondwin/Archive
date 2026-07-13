#!/usr/bin/env python3
"""Focused schema-4 contract and immutable RunStore checks."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "lean-fixtures"
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from cpe_runtime.contracts import (  # noqa: E402
    ChildResult,
    canonical_json,
    validate_child_result,
)
from cpe_runtime.store import RunStore  # noqa: E402


class LeanContractsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="cpe-lean-contracts-")
        self.root = Path(self.temporary.name)
        self.home = self.root / "codex-home"
        self.repo = self.root / "repo"
        self.home.mkdir(mode=0o700)
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        for name in ("spec-a.md", "spec-b.md", "plan-a.md", "plan-b.md", "program.md"):
            shutil.copyfile(FIXTURES / name, self.repo / name)

        self.spec_a = self.repo / "spec-a.md"
        self.spec_b = self.repo / "spec-b.md"
        self.plan_a = self.repo / "plan-a.md"
        self.plan_b = self.repo / "plan-b.md"
        self.program = self.repo / "program.md"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def create_store(self) -> RunStore:
        return RunStore.create(
            codex_home=self.home,
            workspace=self.repo,
            specs=[self.spec_a, self.spec_b],
            plans=[self.plan_a, self.plan_b],
            program_plan=self.program,
        )

    def create_store_with_relationships(self) -> RunStore:
        return RunStore.create(
            codex_home=self.home,
            workspace=self.repo,
            specs=[self.spec_a, self.spec_b],
            plans=[self.plan_a, self.plan_b],
            program_plan=self.program,
            document_relationships={
                "plan-02": [
                    {
                        "relationship_type": "amends",
                        "target_document_id": "plan-01",
                    }
                ],
                "program-plan": [
                    {
                        "relationship_type": "coordinates",
                        "target_document_id": "plan-02",
                    },
                    {
                        "relationship_type": "coordinates",
                        "target_document_id": "plan-01",
                    },
                ],
            },
        )

    def test_snapshots_have_stable_role_local_order_and_are_immutable(self) -> None:
        store = self.create_store()
        documents = store.document_set()
        self.assertEqual(
            [(item.document_id, item.role) for item in documents],
            [
                ("spec-01", "spec"),
                ("spec-02", "spec"),
                ("plan-01", "plan"),
                ("plan-02", "plan"),
                ("program-plan", "program_plan"),
            ],
        )

        original = self.spec_a.read_bytes()
        first = documents[0]
        self.assertEqual(first.sha256, hashlib.sha256(original).hexdigest())
        self.assertEqual(first.byte_length, len(original))
        self.assertEqual(first.input_order, 0)
        self.assertEqual(store.read_artifact(first.snapshot_path), original)

        self.spec_a.write_text("# changed after create\n", encoding="utf-8")
        reopened = RunStore.open(codex_home=self.home, run_id=store.run_id)
        self.assertEqual(reopened.document_set(), documents)
        self.assertEqual(reopened.read_artifact(first.snapshot_path), original)
        self.assertEqual(reopened.document_set()[0].sha256, first.sha256)

    def test_document_relationships_are_canonical_immutable_and_reopened(self) -> None:
        store = self.create_store_with_relationships()
        documents = {item.document_id: item for item in store.document_set()}
        self.assertEqual(
            [
                (item.relationship_type, item.target_document_id)
                for item in documents["plan-02"].relationships
            ],
            [("amends", "plan-01")],
        )
        self.assertEqual(
            [
                (item.relationship_type, item.target_document_id)
                for item in documents["program-plan"].relationships
            ],
            [("coordinates", "plan-01"), ("coordinates", "plan-02")],
        )
        reopened = RunStore.open(codex_home=self.home, run_id=store.run_id)
        self.assertEqual(reopened.document_set(), store.document_set())

        with self.assertRaises(ValueError):
            RunStore.create(
                codex_home=self.root / "invalid-home",
                workspace=self.repo,
                specs=[self.spec_a],
                plans=[self.plan_a],
                program_plan=None,
                document_relationships={
                    "plan-01": [
                        {
                            "relationship_type": "amends",
                            "target_document_id": "unknown-document",
                        }
                    ]
                },
            )
        self.assertFalse((self.root / "invalid-home").exists())
        with self.assertRaises(ValueError):
            RunStore.create(
                codex_home=self.root / "invalid-type-home",
                workspace=self.repo,
                specs=[self.spec_a],
                plans=[self.plan_a],
                program_plan=None,
                document_relationships={
                    "plan-01": [
                        {
                            "relationship_type": "amends",
                            "target_document_id": ["spec-01"],
                        }
                    ]
                },
            )
        self.assertFalse((self.root / "invalid-type-home").exists())

    def test_identical_document_bytes_preserve_distinct_snapshot_provenance(self) -> None:
        self.spec_b.write_bytes(self.spec_a.read_bytes())
        store = self.create_store()
        documents = store.document_set()
        self.assertEqual(documents[0].sha256, documents[1].sha256)
        snapshotted = store.validate_event_chain()[1]
        self.assertEqual(
            snapshotted["payload"]["snapshot_sha256s"][:2],
            [documents[0].sha256, documents[1].sha256],
        )

    def test_rejects_duplicate_paths_and_non_utf8_before_creating_a_run(self) -> None:
        orchestrator = self.home / "orchestrator"

        with self.assertRaises(ValueError):
            RunStore.create(
                codex_home=self.home,
                workspace=self.repo,
                specs=[self.spec_a],
                plans=[self.spec_a],
                program_plan=None,
            )
        self.assertFalse(orchestrator.exists())

        invalid = self.repo / "invalid.md"
        invalid.write_bytes(b"\xff\xfe")
        with self.assertRaises(ValueError):
            RunStore.create(
                codex_home=self.home,
                workspace=self.repo,
                specs=[self.spec_a],
                plans=[invalid],
                program_plan=None,
            )
        self.assertFalse(orchestrator.exists())

    def test_run_files_are_private(self) -> None:
        store = self.create_store()
        store.put_artifact("reports/task-1/report.md", b"report\n")
        outbox = store.allocate_outbox("attempt-1")

        directories = [store.paths.root, outbox]
        directories.extend(path for path in store.paths.root.rglob("*") if path.is_dir())
        files = [path for path in store.paths.root.rglob("*") if path.is_file()]
        self.assertTrue(files)
        for path in directories:
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700, path)
        for path in files:
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600, path)

    def test_events_are_hash_chained_replayed_and_tamper_evident(self) -> None:
        store = self.create_store()
        self.assertEqual(store.replay()["status"], "mapping")

        provenance = store.validate_event_chain()
        self.assertEqual(
            [event["event_type"] for event in provenance],
            ["run.created", "documents.snapshotted"],
        )
        self.assertEqual(provenance[0]["payload"]["run_id"], store.run_id)
        self.assertEqual(
            provenance[1]["payload"]["document_ids"],
            ["spec-01", "spec-02", "plan-01", "plan-02", "program-plan"],
        )

        first = store.append_event(
            "map.generation_created",
            {
                "generation_id": "generation-0001",
                "artifact_paths": ["maps/generation-0001/program-map.json"],
            },
        )
        self.assertEqual(first["prev_event_sha256"], provenance[-1]["event_sha256"])
        self.assertEqual(store.replay()["status"], "running")

        second = store.append_event(
            "run.interrupted",
            {"status": "interrupted", "failure_code": "signal"},
        )
        self.assertEqual(second["prev_event_sha256"], first["event_sha256"])
        events = store.validate_event_chain()
        self.assertEqual(events[-2:], (first, second))
        for event in events:
            body = {key: value for key, value in event.items() if key != "event_sha256"}
            self.assertEqual(
                event["event_sha256"], hashlib.sha256(canonical_json(body)).hexdigest()
            )
        replayed = store.replay()
        self.assertEqual(replayed["status"], "interrupted")
        self.assertEqual(replayed["event_count"], 4)

        raw = store.paths.events.read_text(encoding="utf-8")
        store.paths.events.write_text(
            raw.replace('"failure_code":"signal"', '"failure_code":"tamper"'),
            encoding="utf-8",
        )
        os.chmod(store.paths.events, 0o600)
        with self.assertRaises(ValueError):
            store.validate_event_chain()

    def test_event_suffix_and_empty_truncation_fail_closed(self) -> None:
        for truncate_to_empty in (False, True):
            with self.subTest(truncate_to_empty=truncate_to_empty):
                store = self.create_store()
                store.append_event(
                    "map.generation_created",
                    {"generation_id": "generation-0001", "artifact_paths": []},
                )
                lines = store.paths.events.read_bytes().splitlines(keepends=True)
                store.paths.events.write_bytes(
                    b"" if truncate_to_empty else b"".join(lines[:-1])
                )
                os.chmod(store.paths.events, 0o600)
                with self.assertRaises(ValueError):
                    store.validate_event_chain()
                with self.assertRaises(ValueError):
                    store.replay()
                with self.assertRaises(ValueError):
                    RunStore.open(codex_home=self.home, run_id=store.run_id)

    def test_event_types_and_payloads_are_strict_and_bounded(self) -> None:
        store = self.create_store()
        with self.assertRaises(ValueError):
            store.append_event("unknown.event", {"task_id": "plan-01:T1"})

        forbidden_fields = ("prompt", "source", "diff", "log", "report")
        for field in forbidden_fields:
            with self.subTest(field=field), self.assertRaises(ValueError):
                store.append_event(
                    "task.started",
                    {
                        "task_id": "plan-01:T1",
                        "attempt_id": "attempt-1",
                        "strategy_key": "initial",
                        field: "heavy content",
                    },
                )

        with self.assertRaises(ValueError):
            store.append_event(
                "task.started",
                {
                    "task_id": "plan-01:T1",
                    "attempt_id": "attempt-1",
                    "strategy_key": "x" * 513,
                },
            )
        with self.assertRaises(ValueError):
            store.append_event(
                "task.started",
                {
                    "task_id": "plan-01:T1",
                    "attempt_id": "attempt-1",
                    "strategy_key": "initial",
                    "artifact_paths": ["logs/full.log"],
                },
            )
        with self.assertRaises(ValueError):
            store.append_event(
                "run.interrupted",
                {"status": "completed", "failure_code": "signal"},
            )
        with self.assertRaises(ValueError):
            store.append_event(
                "review.reported",
                {
                    "task_id": "plan-01:T1",
                    "review_id": "review-1",
                    "status": "completed",
                    "verdict": ["pass"],
                    "artifact_paths": ["reviews/plan-01-T1/review-1.md"],
                },
            )

    def test_artifacts_are_immutable_and_outbox_ingestion_is_bounded(self) -> None:
        store = self.create_store()
        expected = store.put_artifact("reports/task-1/report.md", b"same bytes\n")
        self.assertEqual(
            store.put_artifact("reports/task-1/report.md", b"same bytes\n"), expected
        )
        with self.assertRaises(ValueError):
            store.put_artifact("reports/task-1/report.md", b"different bytes\n")

        outbox = store.allocate_outbox("attempt-1")
        child_report = outbox / "reports" / "child.md"
        child_report.parent.mkdir(mode=0o700)
        child_report.write_bytes(b"child report\n")
        self.assertEqual(
            store.ingest_outbox("attempt-1", ["reports/child.md"]),
            ("reports/child.md",),
        )
        self.assertEqual(store.read_artifact("reports/child.md"), b"child report\n")
        for unsafe in ("../escape.md", "/absolute.md", "reports/../escape.md"):
            with self.assertRaises(ValueError):
                store.put_artifact(unsafe, b"no\n")
        with self.assertRaises(ValueError):
            store.put_artifact("result.json/nested", b"no\n")

        second_outbox = store.allocate_outbox("attempt-2")
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "escaped.md").write_bytes(b"outside\n")
        (second_outbox / "reviews").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            store.ingest_outbox("attempt-2", ["reviews/escaped.md"])

    def test_artifact_digest_mutation_fails_read_open_and_replay(self) -> None:
        store = self.create_store()
        path = store.put_artifact("reports/task-1/report.md", b"original\n")
        self.assertEqual(store.read_artifact("reports/task-1/report.md"), b"original\n")

        path.write_bytes(b"mutated!\n")
        os.chmod(path, 0o600)
        with self.assertRaises(ValueError):
            store.read_artifact("reports/task-1/report.md")
        with self.assertRaises(ValueError):
            RunStore.open(codex_home=self.home, run_id=store.run_id)
        with self.assertRaises(ValueError):
            store.replay()

    def test_child_result_contract_is_exact_and_role_aware(self) -> None:
        valid = {
            "role": "reviewer",
            "status": "completed",
            "item_id": "plan-01:T1-review",
            "commit": None,
            "verdict": "pass",
            "failure_code": None,
            "authority_id": None,
            "strategy_key": None,
            "affected_document_ids": ["spec-01", "plan-01"],
            "artifact_paths": ["reviews/plan-01-T1/review-1.md"],
            "summary": "Review passed.",
        }
        result = validate_child_result(
            valid, expected_role="reviewer", expected_item_id="plan-01:T1-review"
        )
        self.assertIsInstance(result, ChildResult)
        self.assertEqual(result.artifact_paths, ("reviews/plan-01-T1/review-1.md",))

        invalid_payloads = []
        invalid_payloads.append({**valid, "role": "unknown_role"})
        invalid_payloads.append({**valid, "status": "unknown_status"})
        invalid_payloads.append({**valid, "extra": True})
        invalid_payloads.append({**valid, "verdict": ["pass"]})
        invalid_payloads.append(
            {
                **valid,
                "status": "waiting_authority",
                "verdict": "blocked",
                "authority_id": "invented_authority_code",
            }
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                validate_child_result(
                    payload,
                    expected_role=payload["role"],
                    expected_item_id="plan-01:T1-review",
                )

        write_success = {
            **valid,
            "role": "task_agent",
            "item_id": "plan-01:T1",
            "verdict": None,
        }
        with self.assertRaises(ValueError):
            validate_child_result(
                write_success, expected_role="task_agent", expected_item_id="plan-01:T1"
            )
        with self.assertRaises(ValueError):
            validate_child_result(
                {**valid, "verdict": "pass", "role": "task_agent"},
                expected_role="task_agent",
                expected_item_id="plan-01:T1-review",
            )
        with self.assertRaises(ValueError):
            validate_child_result(
                {**valid, "artifact_paths": ["reviews/../escape.md"]},
                expected_role="reviewer",
                expected_item_id="plan-01:T1-review",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
