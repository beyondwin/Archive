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

        first = store.append_event(
            "map.generation_created", {"generation_id": "generation-0001"}
        )
        self.assertIsNone(first["prev_event_sha256"])
        self.assertEqual(store.replay()["status"], "running")

        second = store.append_event("run.interrupted", {"reason": "signal"})
        self.assertEqual(second["prev_event_sha256"], first["event_sha256"])
        events = store.validate_event_chain()
        self.assertEqual(events, (first, second))
        for event in events:
            body = {key: value for key, value in event.items() if key != "event_sha256"}
            self.assertEqual(
                event["event_sha256"], hashlib.sha256(canonical_json(body)).hexdigest()
            )
        replayed = store.replay()
        self.assertEqual(replayed["status"], "interrupted")
        self.assertEqual(replayed["event_count"], 2)

        raw = store.paths.events.read_text(encoding="utf-8")
        store.paths.events.write_text(raw.replace("signal", "tamper"), encoding="utf-8")
        os.chmod(store.paths.events, 0o600)
        with self.assertRaises(ValueError):
            store.validate_event_chain()

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
