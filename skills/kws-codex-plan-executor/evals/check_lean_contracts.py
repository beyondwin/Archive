#!/usr/bin/env python3
"""Focused schema-4 contract and immutable RunStore checks."""

from __future__ import annotations

import hashlib
import json
import os
import signal
import stat
import subprocess
import sys
import time
import unittest
from dataclasses import replace
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from cpe_runtime.contracts import (  # noqa: E402
    ChildResult,
    canonical_json,
    validate_child_result,
)
from cpe_runtime.store import RunStore  # noqa: E402
from cpe_runtime.launcher import ChildLauncher, ChildRequest  # noqa: E402
from cpe_runtime.worktree import Worktree  # noqa: E402
from fake_codex import LeanEvalCase  # noqa: E402


class LeanContractsTest(LeanEvalCase):
    fixture_prefix = "cpe-lean-contracts-"

    def setUp(self) -> None:
        super().setUp()
        self.spec_a = self.repo / "spec-a.md"
        self.spec_b = self.repo / "spec-b.md"
        self.plan_a = self.repo / "plan-a.md"
        self.plan_b = self.repo / "plan-b.md"
        self.program = self.repo / "program.md"

    def create_store(self) -> RunStore:
        return RunStore.create(
            codex_home=self.home,
            workspace=self.repo,
            specs=[self.spec_a, self.spec_b],
            plans=[self.plan_a, self.plan_b],
            program_plan=self.program,
        )

    @staticmethod
    def generation_event_payload(**overrides: object) -> dict[str, object]:
        payload: dict[str, object] = {
            "generation_id": "generation-0001",
            "map_sha256": "a" * 64,
            "publication_manifest_path": (
                "maps/generation-0001/attempts/" + "b" * 64 + "/accepted.json"
            ),
            "publication_manifest_sha256": "c" * 64,
            "authority_ids": [],
            "task_ids": [],
        }
        payload.update(overrides)
        return payload

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

    def create_fake_codex_bin(self) -> tuple[Path, Path]:
        bin_dir = self.install_fake_codex()
        fake_codex = bin_dir / "codex"
        return bin_dir, fake_codex

    def make_child_request(
        self,
        *,
        store: RunStore,
        worktree: Worktree,
        attempt_id: str,
        role: str,
        item_id: str,
    ) -> ChildRequest:
        outbox = store.allocate_outbox(attempt_id)
        return ChildRequest(
            role=role,
            item_id=item_id,
            goal="Exercise one bounded launcher role.",
            input_paths=(self.plan_a.resolve(), self.spec_a.resolve()),
            repository=worktree.source,
            worktree=worktree.root,
            outbox=outbox,
            report_path=f"reports/{attempt_id}.md",
            applicable_skills=("using-superpowers", "test-driven-development"),
            done_when=("the bounded role reports a valid result",),
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
            self.generation_event_payload(),
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
                    self.generation_event_payload(),
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
        baseline = subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"],
            check=True,
            stdout=subprocess.PIPE,
            text=True,
        ).stdout.strip()
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
        started = store.append_event(
            "task.started",
            {
                "task_id": "plan-01:T1",
                "attempt_id": "attempt-1",
                "role": "task_agent",
                "strategy_key": "initial",
                "baseline_commit": baseline,
                "evidence_sha256": "d" * 64,
            },
        )
        self.assertEqual(started["payload"]["baseline_commit"], baseline)
        with self.assertRaisesRegex(ValueError, "missing=.*evidence_sha256"):
            store.append_event(
                "task.started",
                {
                    "task_id": "plan-01:T1",
                    "attempt_id": "attempt-2",
                    "strategy_key": "changed",
                    "baseline_commit": baseline,
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
        with self.assertRaisesRegex(ValueError, "at most 64"):
            store.append_event(
                "map.generation_created",
                self.generation_event_payload(
                    authority_ids=[f"A{index}" for index in range(65)]
                ),
            )
        with self.assertRaisesRegex(ValueError, "artifact path"):
            store.append_event(
                "map.generation_created",
                self.generation_event_payload(
                    publication_manifest_path="maps/../accepted.json"
                ),
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

    def test_unindexed_artifact_reconciliation_requires_identical_private_regular_file(
        self,
    ) -> None:
        store = self.create_store()

        identical = store.paths.reports / "identical.md"
        identical.write_bytes(b"installed before index\n")
        identical.chmod(0o600)
        store.put_artifact("reports/identical.md", b"installed before index\n")
        self.assertEqual(
            store.read_artifact("reports/identical.md"), b"installed before index\n"
        )

        different = store.paths.reports / "different.md"
        different.write_bytes(b"unexpected bytes\n")
        different.chmod(0o600)
        with self.assertRaisesRegex(ValueError, "different bytes"):
            store.put_artifact("reports/different.md", b"expected bytes\n")

        symlink = store.paths.reports / "symlink.md"
        symlink.symlink_to(identical)
        with self.assertRaisesRegex(ValueError, "private regular file"):
            store.put_artifact("reports/symlink.md", b"installed before index\n")

        wrong_type = store.paths.reports / "directory.md"
        wrong_type.mkdir(mode=0o700)
        with self.assertRaisesRegex(ValueError, "private regular file"):
            store.put_artifact("reports/directory.md", b"directory\n")

        wrong_mode = store.paths.reports / "mode.md"
        wrong_mode.write_bytes(b"mode drift\n")
        wrong_mode.chmod(0o644)
        with self.assertRaisesRegex(ValueError, "mode"):
            store.put_artifact("reports/mode.md", b"mode drift\n")

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

    def test_worktree_create_rejects_tracked_source_dirt_without_editing_source(self) -> None:
        source_head = subprocess.check_output(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"], text=True
        ).strip()
        clean_status = subprocess.check_output(
            [
                "git",
                "-C",
                str(self.repo),
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
            ],
            text=True,
        )
        created = Worktree.create(
            source=self.repo,
            root=self.root / "worktree-clean",
            run_id="lean-task-2",
        )
        self.assertEqual(created.branch, "codex/lean-task-2")
        self.assertEqual(created.base_commit, source_head)
        self.assertEqual(created.head(), source_head)
        self.assertEqual(created.status(), ())
        self.assertEqual(
            subprocess.check_output(
                ["git", "-C", str(self.repo), "rev-parse", "HEAD"], text=True
            ).strip(),
            source_head,
        )
        self.assertEqual(
            subprocess.check_output(
                [
                    "git",
                    "-C",
                    str(self.repo),
                    "status",
                    "--porcelain=v1",
                    "--untracked-files=all",
                ],
                text=True,
            ),
            clean_status,
        )

        self.spec_a.write_text("# tracked dirt\n", encoding="utf-8")
        dirty_root = self.root / "worktree-dirty-source"
        with self.assertRaises(ValueError):
            Worktree.create(source=self.repo, root=dirty_root, run_id="source-dirty")
        self.assertFalse(dirty_root.exists())

    def test_worktree_handoffs_reject_wrong_commit_and_any_visible_dirt(self) -> None:
        worktree = Worktree.create(
            source=self.repo,
            root=self.root / "handoff-worktree",
            run_id="handoff",
        )
        changed = worktree.root / "bounded.txt"
        changed.write_text("bounded change\n", encoding="utf-8")
        subprocess.run(
            ["git", "-C", str(worktree.root), "add", "bounded.txt"], check=True
        )
        subprocess.run(
            ["git", "-C", str(worktree.root), "commit", "-q", "-m", "bounded"],
            check=True,
        )
        commit = worktree.head()
        with self.assertRaises(ValueError):
            worktree.verify_write_handoff(worktree.base_commit)
        worktree.verify_write_handoff(commit)
        self.assertIn("bounded change", worktree.diff(worktree.base_commit, commit))

        (worktree.root / "untracked.txt").write_text("dirty\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            worktree.verify_write_handoff(commit)

    def test_launcher_uses_bounded_command_env_and_ingests_normalized_artifacts(self) -> None:
        store = self.create_store()
        worktree = Worktree.create(
            source=self.repo,
            root=self.root / "launcher-worktree",
            run_id="launcher",
        )
        bin_dir, _ = self.create_fake_codex_bin()
        invocation_log = self.root / "invocations.jsonl"
        launcher = ChildLauncher(
            schema_path=SKILL_ROOT / "templates" / "child-result-schema.json",
            timeout_seconds=5,
            environ={
                **os.environ,
                "PATH": str(bin_dir),
                "CODEX_HOME": str(self.home),
                "OPENAI_API_KEY": "must-be-removed",
                "ANTHROPIC_API_KEY": "must-be-removed",
                "AWS_SECRET_ACCESS_KEY": "must-be-removed",
                "AWS_SESSION_TOKEN": "must-be-removed",
                "GITHUB_TOKEN": "must-be-removed",
                "CPE_FAKE_SCENARIO": "success",
                "CPE_FAKE_INVOCATION_LOG": str(invocation_log),
            },
        )
        request = self.make_child_request(
            store=store,
            worktree=worktree,
            attempt_id="review-success",
            role="reviewer",
            item_id="plan-01:T1-review",
        )
        outcome = launcher.launch(request, worktree=worktree, store=store)
        self.assertEqual(outcome.result.status, "completed")
        self.assertEqual(outcome.result.verdict, "pass")
        self.assertEqual(len(outcome.event_digest), 64)
        self.assertGreaterEqual(outcome.elapsed_ms, 0)
        self.assertEqual(
            store.read_artifact("reports/review-success.md"),
            b"deterministic child report\n",
        )
        invocation = json.loads(invocation_log.read_text(encoding="utf-8"))
        self.assertEqual(invocation["env"]["PATH"], str(bin_dir))
        self.assertEqual(invocation["env"]["CODEX_HOME"], str(self.home))
        for key in (
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "AWS_SECRET_ACCESS_KEY",
            "AWS_SESSION_TOKEN",
            "GITHUB_TOKEN",
        ):
            self.assertNotIn(key, invocation["env"])
        argv = invocation["argv"]
        self.assertEqual(
            argv,
            [
                "exec",
                "--ignore-user-config",
                "--json",
                "--sandbox",
                "read-only",
                "-C",
                str(worktree.root),
                "--add-dir",
                str(request.outbox.resolve(strict=True)),
                "--output-schema",
                str((SKILL_ROOT / "templates" / "child-result-schema.json").resolve()),
                "--output-last-message",
                str(request.outbox.resolve(strict=True) / ".child-result.json"),
                "-",
            ],
        )
        prohibited_policy_args = {
            "--model",
            "-m",
            "--profile",
            "-p",
            "--pricing",
            "--pricing-mode",
            "--billing-mode",
            "--release",
            "--release-status",
            "--proof-profile",
            "--compatibility",
            "--compatibility-policy",
            "--config",
            "-c",
        }
        self.assertTrue(prohibited_policy_args.isdisjoint(argv))

        write_request = self.make_child_request(
            store=store,
            worktree=worktree,
            attempt_id="task-success",
            role="task_agent",
            item_id="plan-01:T1",
        )
        write_outcome = launcher.launch(write_request, worktree=worktree, store=store)
        self.assertEqual(write_outcome.result.commit, worktree.head())
        second_invocation = json.loads(
            invocation_log.read_text(encoding="utf-8").splitlines()[1]
        )
        second_argv = second_invocation["argv"]
        self.assertEqual(
            second_argv,
            [
                "exec",
                "--ignore-user-config",
                "--json",
                "--sandbox",
                "workspace-write",
                "-C",
                str(worktree.root),
                "--add-dir",
                str(write_request.outbox.resolve(strict=True)),
                "--output-schema",
                str((SKILL_ROOT / "templates" / "child-result-schema.json").resolve()),
                "--output-last-message",
                str(write_request.outbox.resolve(strict=True) / ".child-result.json"),
                "-",
            ],
        )
        self.assertTrue(prohibited_policy_args.isdisjoint(second_argv))

    def test_launcher_rejects_original_worktree_and_outbox_symlinks(self) -> None:
        store = self.create_store()
        worktree = Worktree.create(
            source=self.repo,
            root=self.root / "symlink-worktree",
            run_id="symlink-inputs",
        )
        bin_dir, _ = self.create_fake_codex_bin()
        launcher = ChildLauncher(
            schema_path=SKILL_ROOT / "templates" / "child-result-schema.json",
            timeout_seconds=5,
            environ={
                **os.environ,
                "PATH": str(bin_dir),
                "CODEX_HOME": str(self.home),
                "CPE_FAKE_SCENARIO": "success",
            },
        )

        worktree_alias = self.root / "worktree-alias"
        worktree_alias.symlink_to(worktree.root, target_is_directory=True)
        worktree_request = self.make_child_request(
            store=store,
            worktree=worktree,
            attempt_id="symlink-worktree-attempt",
            role="reviewer",
            item_id="review-symlink-worktree",
        )
        with self.assertRaisesRegex(ValueError, "worktree.*real directory"):
            launcher.launch(
                replace(worktree_request, worktree=worktree_alias),
                worktree=worktree,
                store=store,
            )

        outbox_request = self.make_child_request(
            store=store,
            worktree=worktree,
            attempt_id="symlink-outbox-attempt",
            role="reviewer",
            item_id="review-symlink-outbox",
        )
        outbox_alias = self.root / "outbox-alias"
        outbox_alias.symlink_to(outbox_request.outbox, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "outbox.*real directory"):
            launcher.launch(
                replace(outbox_request, outbox=outbox_alias),
                worktree=worktree,
                store=store,
            )

    def test_launcher_uses_validated_canonical_paths_at_every_child_boundary(self) -> None:
        store = self.create_store()
        worktree = Worktree.create(
            source=self.repo,
            root=self.root / "canonical-worktree",
            run_id="canonical-paths",
        )
        bin_dir, _ = self.create_fake_codex_bin()
        invocation_log = self.root / "canonical-invocation.jsonl"
        launcher = ChildLauncher(
            schema_path=SKILL_ROOT / "templates" / "child-result-schema.json",
            timeout_seconds=5,
            environ={
                **os.environ,
                "PATH": str(bin_dir),
                "CODEX_HOME": str(self.home),
                "CPE_FAKE_SCENARIO": "success",
                "CPE_FAKE_INVOCATION_LOG": str(invocation_log),
            },
        )
        request = self.make_child_request(
            store=store,
            worktree=worktree,
            attempt_id="canonical-attempt",
            role="reviewer",
            item_id="review-canonical-paths",
        )
        (worktree.root / "path-spelling").mkdir()
        (request.outbox / "path-spelling").mkdir()
        spelled_worktree = worktree.root / "path-spelling" / ".."
        spelled_outbox = request.outbox / "path-spelling" / ".."

        outcome = launcher.launch(
            replace(request, worktree=spelled_worktree, outbox=spelled_outbox),
            worktree=worktree,
            store=store,
        )

        self.assertEqual(outcome.result.status, "completed")
        invocation = json.loads(invocation_log.read_text(encoding="utf-8"))
        argv = invocation["argv"]
        self.assertEqual(argv[argv.index("-C") + 1], str(worktree.root))
        self.assertEqual(
            argv[argv.index("--add-dir") + 1], str(request.outbox.resolve(strict=True))
        )
        self.assertEqual(
            argv[argv.index("--output-last-message") + 1],
            str(request.outbox.resolve(strict=True) / ".child-result.json"),
        )
        self.assertIn(f"- repository: {worktree.source}", invocation["prompt"])
        self.assertIn(f"- worktree: {worktree.root}", invocation["prompt"])
        self.assertIn(
            f"- attempt outbox: {request.outbox.resolve(strict=True)}",
            invocation["prompt"],
        )
        self.assertNotIn(str(spelled_worktree), invocation["prompt"])
        self.assertNotIn(str(spelled_outbox), invocation["prompt"])

    def test_launcher_rejects_read_only_git_changes_and_artifact_traversal(self) -> None:
        store = self.create_store()
        bin_dir, _ = self.create_fake_codex_bin()
        for scenario in ("dirty_handoff", "tampered_artifact_path"):
            with self.subTest(scenario=scenario):
                worktree = Worktree.create(
                    source=self.repo,
                    root=self.root / f"worktree-{scenario}",
                    run_id=scenario.replace("_", "-"),
                )
                launcher = ChildLauncher(
                    schema_path=SKILL_ROOT / "templates" / "child-result-schema.json",
                    timeout_seconds=5,
                    environ={
                        **os.environ,
                        "PATH": str(bin_dir),
                        "CODEX_HOME": str(self.home),
                        "CPE_FAKE_SCENARIO": scenario,
                    },
                )
                request = self.make_child_request(
                    store=store,
                    worktree=worktree,
                    attempt_id=f"attempt-{scenario.replace('_', '-')}",
                    role="reviewer",
                    item_id=f"review-{scenario}",
                )
                with self.assertRaises(ValueError):
                    launcher.launch(request, worktree=worktree, store=store)

    def test_launcher_rejects_wrong_write_commit(self) -> None:
        store = self.create_store()
        worktree = Worktree.create(
            source=self.repo,
            root=self.root / "wrong-commit-worktree",
            run_id="wrong-commit",
        )
        bin_dir, _ = self.create_fake_codex_bin()
        launcher = ChildLauncher(
            schema_path=SKILL_ROOT / "templates" / "child-result-schema.json",
            timeout_seconds=5,
            environ={
                **os.environ,
                "PATH": str(bin_dir),
                "CODEX_HOME": str(self.home),
                "CPE_FAKE_SCENARIO": "wrong_commit",
            },
        )
        request = self.make_child_request(
            store=store,
            worktree=worktree,
            attempt_id="attempt-wrong-commit",
            role="task_agent",
            item_id="plan-01:T-wrong",
        )
        with self.assertRaises(ValueError):
            launcher.launch(request, worktree=worktree, store=store)

    def test_launcher_timeout_terminates_the_entire_child_process_group(self) -> None:
        store = self.create_store()
        worktree = Worktree.create(
            source=self.repo,
            root=self.root / "timeout-worktree",
            run_id="timeout",
        )
        bin_dir, _ = self.create_fake_codex_bin()
        descendant_pid_path = self.root / "descendant.pid"
        launcher = ChildLauncher(
            schema_path=SKILL_ROOT / "templates" / "child-result-schema.json",
            timeout_seconds=1.5,
            terminate_grace_seconds=0.2,
            environ={
                **os.environ,
                "PATH": str(bin_dir),
                "CODEX_HOME": str(self.home),
                "CPE_FAKE_SCENARIO": "timeout",
                "CPE_FAKE_DESCENDANT_PID": str(descendant_pid_path),
            },
        )
        request = self.make_child_request(
            store=store,
            worktree=worktree,
            attempt_id="attempt-timeout",
            role="reviewer",
            item_id="review-timeout",
        )
        with self.assertRaises(TimeoutError):
            launcher.launch(request, worktree=worktree, store=store)
        self.assertTrue(descendant_pid_path.is_file())
        descendant_pid = int(descendant_pid_path.read_text(encoding="utf-8"))
        for _ in range(40):
            try:
                os.kill(descendant_pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.025)
        else:
            self.fail(f"timeout descendant still alive: {descendant_pid}")

    def test_launcher_timeout_kills_group_after_leader_exits_and_closes_pipes(self) -> None:
        store = self.create_store()
        worktree = Worktree.create(
            source=self.repo,
            root=self.root / "timeout-leader-exit-worktree",
            run_id="timeout-leader-exit",
        )
        bin_dir, _ = self.create_fake_codex_bin()
        descendant_pid_path = self.root / "surviving-descendant.pid"
        launcher = ChildLauncher(
            schema_path=SKILL_ROOT / "templates" / "child-result-schema.json",
            timeout_seconds=1.5,
            terminate_grace_seconds=0.2,
            environ={
                **os.environ,
                "PATH": str(bin_dir),
                "CODEX_HOME": str(self.home),
                "CPE_FAKE_SCENARIO": "timeout_leader_exits_descendant_survives",
                "CPE_FAKE_DESCENDANT_PID": str(descendant_pid_path),
            },
        )
        request = self.make_child_request(
            store=store,
            worktree=worktree,
            attempt_id="attempt-timeout-leader-exit",
            role="reviewer",
            item_id="review-timeout-leader-exit",
        )
        with self.assertRaises(TimeoutError):
            launcher.launch(request, worktree=worktree, store=store)
        self.assertTrue(descendant_pid_path.is_file())
        descendant_pid = int(descendant_pid_path.read_text(encoding="utf-8"))
        try:
            for _ in range(40):
                try:
                    os.kill(descendant_pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.025)
            else:
                self.fail(
                    "timeout descendant survived after leader exited and closed pipes: "
                    f"{descendant_pid}"
                )
        finally:
            try:
                os.kill(descendant_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


if __name__ == "__main__":
    unittest.main(verbosity=2)
