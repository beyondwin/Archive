#!/usr/bin/env python3
"""Focused multi-document mapping and lossless task-brief checks."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "lean-fixtures"
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from cpe_runtime.contracts import (  # noqa: E402
    InputDocument,
    canonical_json,
    validate_document_map,
    validate_program_map,
    validate_task_brief,
)
from cpe_runtime.launcher import ChildLauncher  # noqa: E402
from cpe_runtime.queue import QueueEngine  # noqa: E402
from cpe_runtime.store import RunStore  # noqa: E402
from cpe_runtime.worktree import Worktree  # noqa: E402


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def source_reference(
    document_id: str,
    *,
    source_sha256: str,
    exact_excerpt: str = "verbatim source text",
) -> dict[str, object]:
    return {
        "document_id": document_id,
        "heading": "Accepted Inputs",
        "line_start": 1,
        "line_end": 3,
        "source_sha256": source_sha256,
        "exact_excerpt": exact_excerpt,
    }


class LeanMappingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="cpe-lean-mapping-")
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
            "# Repository Instructions\n\nPreserve exact source coverage.\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "-C", str(self.repo), "add", "."], check=True)
        subprocess.run(
            ["git", "-C", str(self.repo), "commit", "-q", "-m", "fixture base"],
            check=True,
        )
        self.invocation_log = self.root / "mapping-invocations.jsonl"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def create_store(self) -> RunStore:
        return RunStore.create(
            codex_home=self.home,
            workspace=self.repo,
            specs=[self.repo / "spec-a.md", self.repo / "spec-b.md"],
            plans=[self.repo / "plan-a.md", self.repo / "plan-b.md"],
            program_plan=self.repo / "program.md",
        )

    def create_launcher(self, *, scenario: str = "mapping_success") -> ChildLauncher:
        bin_dir = self.root / f"fake-bin-{scenario}"
        bin_dir.mkdir(exist_ok=True)
        fake_codex = bin_dir / "codex"
        source = (SKILL_ROOT / "evals" / "fake_codex.py").read_text(encoding="utf-8")
        lines = source.splitlines()
        lines[0] = f"#!{sys.executable}"
        fake_codex.write_text("\n".join(lines) + "\n", encoding="utf-8")
        fake_codex.chmod(0o700)
        return ChildLauncher(
            schema_path=SKILL_ROOT / "templates" / "child-result-schema.json",
            timeout_seconds=10,
            environ={
                **os.environ,
                "PATH": str(bin_dir),
                "CODEX_HOME": str(self.home),
                "CPE_FAKE_SCENARIO": scenario,
                "CPE_FAKE_INVOCATION_LOG": str(self.invocation_log),
            },
        )

    def create_engine(
        self, *, store: RunStore, scenario: str = "mapping_success"
    ) -> QueueEngine:
        worktree = Worktree.create(
            source=self.repo,
            root=self.root / f"worktree-{scenario}",
            run_id=f"mapping-{scenario}",
        )
        return QueueEngine(store, worktree, self.create_launcher(scenario=scenario))

    def invocations(self) -> list[dict[str, object]]:
        if not self.invocation_log.exists():
            return []
        return [
            json.loads(line)
            for line in self.invocation_log.read_text(encoding="utf-8").splitlines()
        ]

    def test_maps_each_snapshot_once_then_program_from_maps_and_instructions(self) -> None:
        store = self.create_store()
        engine = self.create_engine(store=store)

        document_paths = engine.map_documents()
        self.assertEqual(
            document_paths,
            tuple(
                f"maps/generation-0001/documents/{document.document_id}.json"
                for document in store.document_set()
            ),
        )
        program_path = engine.map_program()
        self.assertEqual(program_path, "maps/generation-0001/program-map.json")

        invocations = self.invocations()
        self.assertEqual(
            [item["role"] for item in invocations],
            ["document_mapper"] * 5 + ["program_mapper"],
        )
        snapshot_paths = {
            str((store.paths.root / document.snapshot_path).resolve())
            for document in store.document_set()
        }
        document_invocations = invocations[:5]
        for invocation in document_invocations:
            exact_inputs = set(invocation["input_paths"])
            self.assertEqual(len(exact_inputs & snapshot_paths), 1)
            self.assertIn(str((engine.worktree.root / "AGENTS.md").resolve()), exact_inputs)
        self.assertEqual(
            {
                next(iter(set(invocation["input_paths"]) & snapshot_paths))
                for invocation in document_invocations
            },
            snapshot_paths,
        )

        program_inputs = set(invocations[-1]["input_paths"])
        expected_maps = {
            str((store.paths.root / relative_path).resolve())
            for relative_path in document_paths
        }
        self.assertTrue(expected_maps <= program_inputs)
        self.assertIn(str((engine.worktree.root / "AGENTS.md").resolve()), program_inputs)
        self.assertFalse(program_inputs & snapshot_paths)

        events = store.validate_event_chain()
        self.assertEqual(events[-1]["event_type"], "map.generation_created")
        self.assertEqual(events[-1]["payload"]["generation_id"], "generation-0001")
        self.assertEqual(events[-1]["payload"]["artifact_paths"], sorted(events[-1]["payload"]["artifact_paths"]))

    def test_completed_immutable_document_maps_are_reused_after_interruption(self) -> None:
        store = self.create_store()
        engine = self.create_engine(store=store)
        first = engine.map_documents()
        count_after_first = len(self.invocations())

        reopened = RunStore.open(codex_home=self.home, run_id=store.run_id)
        resumed = QueueEngine(reopened, engine.worktree, engine.launcher)
        self.assertEqual(resumed.map_documents(), first)
        self.assertEqual(len(self.invocations()), count_after_first)

    def test_partial_mapping_interruption_ingests_successes_and_retries_only_missing(self) -> None:
        store = self.create_store()
        engine = self.create_engine(store=store, scenario="mapping_partial_failure")
        with self.assertRaisesRegex(ValueError, "Codex child exited"):
            engine.map_documents()
        completed_paths = [
            engine._document_map_path(document)
            for document in store.document_set()
            if document.document_id != "plan-02"
        ]
        self.assertTrue(
            all((store.paths.root / path).is_file() for path in completed_paths)
        )
        count_after_failure = len(self.invocations())

        resumed = QueueEngine(
            store,
            engine.worktree,
            self.create_launcher(scenario="mapping_success"),
        )
        resumed.map_documents()
        retry_invocations = self.invocations()[count_after_failure:]
        self.assertEqual(len(retry_invocations), 1)
        self.assertEqual(retry_invocations[0]["role"], "document_mapper")
        self.assertIn("plan-02.md", " ".join(retry_invocations[0]["input_paths"]))

    def test_document_map_rejects_mismatched_source_sha(self) -> None:
        document = InputDocument(
            document_id="spec-01",
            role="spec",
            original_path="/tmp/spec.md",
            snapshot_path="inputs/spec-01.md",
            sha256="a" * 64,
            byte_length=10,
            input_order=0,
        )
        payload = {
            "schema_version": 1,
            "document_id": "spec-01",
            "role": "spec",
            "source_sha256": "b" * 64,
            "requirements": [],
            "task_candidates": [],
            "dependencies": [],
            "authority_items": [],
            "verification_commands": [],
        }
        with self.assertRaisesRegex(ValueError, "source SHA"):
            validate_document_map(payload, document=document)

        malformed_authority = {
            **payload,
            "source_sha256": "a" * 64,
            "authority_items": [
                {
                    "authority_id": "A1",
                    "authority_code": "authoritative_document_conflict",
                    "question": "Which authority governs?",
                    "source_references": [
                        source_reference("spec-01", source_sha256="a" * 64)
                    ],
                    "unexpected": True,
                }
            ],
        }
        with self.assertRaisesRegex(ValueError, "authority item"):
            validate_document_map(malformed_authority, document=document)

    def test_queue_rejects_excerpt_that_is_not_the_declared_source_range(self) -> None:
        store = self.create_store()
        engine = self.create_engine(store=store, scenario="mapping_bad_excerpt")
        with self.assertRaisesRegex(ValueError, "exact excerpt"):
            engine.map_documents()

    def valid_program_map(self) -> dict[str, object]:
        map_hashes = {
            "spec-01": "1" * 64,
            "spec-02": "2" * 64,
            "plan-01": "3" * 64,
            "plan-02": "4" * 64,
            "program-plan": "5" * 64,
        }
        return {
            "schema_version": 1,
            "generation": 1,
            "document_map_sha256s": map_hashes,
            "tasks": [
                {
                    "task_id": "plan-01:T1",
                    "title": "Implement one bounded change",
                    "dependencies": [],
                    "document_ids": ["plan-01", "spec-01"],
                    "requirement_ids": ["spec-01:R1"],
                    "brief_path": "briefs/plan-01-T1.json",
                },
                {
                    "task_id": "plan-01:T2",
                    "title": "Implement the dependent change",
                    "dependencies": ["plan-01:T1"],
                    "document_ids": ["plan-01", "spec-02"],
                    "requirement_ids": ["spec-02:R1"],
                    "brief_path": "briefs/plan-01-T2.json",
                },
                {
                    "task_id": "plan-02:T1",
                    "title": "Integrate both changes",
                    "dependencies": ["plan-01:T2"],
                    "document_ids": ["plan-02", "program-plan"],
                    "requirement_ids": [],
                    "brief_path": "briefs/plan-02-T1.json",
                },
            ],
            "coverage": {
                "spec-01:R1": {
                    "disposition": "planned",
                    "task_ids": ["plan-01:T1"],
                    "reason": None,
                },
                "spec-02:R1": {
                    "disposition": "planned",
                    "task_ids": ["plan-01:T2"],
                    "reason": None,
                },
            },
            "task_splits": [],
            "final_verification_commands": ["python3 evals/check_lean_mapping.py"],
            "authority_items": [],
        }

    def test_program_map_uses_design_dispositions_and_rejects_bad_graphs(self) -> None:
        payload = self.valid_program_map()
        validated = validate_program_map(
            payload, document_ids=set(payload["document_map_sha256s"])
        )
        self.assertEqual(
            [task["task_id"] for task in validated["tasks"]],
            ["plan-01:T1", "plan-01:T2", "plan-02:T1"],
        )

        for disposition in (
            "planned",
            "preexisting_verify",
            "explicit_non_goal",
            "approved_deferred",
            "conflict",
            "unmapped",
        ):
            with self.subTest(disposition=disposition):
                candidate = self.valid_program_map()
                candidate["coverage"]["spec-01:R1"] = {
                    "disposition": disposition,
                    "task_ids": ["plan-01:T1"] if disposition == "planned" else [],
                    "reason": None if disposition == "planned" else "recorded basis",
                }
                if disposition != "planned":
                    candidate["tasks"][0]["requirement_ids"] = []
                validate_program_map(
                    candidate, document_ids=set(candidate["document_map_sha256s"])
                )

        outdated = self.valid_program_map()
        outdated["coverage"]["spec-01:R1"]["disposition"] = "implemented"
        with self.assertRaises(ValueError):
            validate_program_map(outdated, document_ids=set(outdated["document_map_sha256s"]))

        unknown = self.valid_program_map()
        unknown["tasks"][1]["dependencies"] = ["plan-99:T1"]
        with self.assertRaisesRegex(ValueError, "unknown dependency"):
            validate_program_map(unknown, document_ids=set(unknown["document_map_sha256s"]))

        cyclic = self.valid_program_map()
        cyclic["tasks"][0]["dependencies"] = ["plan-02:T1"]
        with self.assertRaisesRegex(ValueError, "cycle"):
            validate_program_map(cyclic, document_ids=set(cyclic["document_map_sha256s"]))

        malformed_authority = self.valid_program_map()
        malformed_authority["authority_items"] = [
            {
                "authority_id": "A1",
                "authority_code": "authoritative_document_conflict",
                "affected_task_ids": ["plan-01:T1"],
                "question": "Which authority governs?",
                "options": ["spec-01", "spec-02"],
                "recommended": "spec-01",
                "source_references": [
                    source_reference("spec-01", source_sha256="1" * 64)
                ],
                "unexpected": "must fail closed",
            }
        ]
        with self.assertRaisesRegex(ValueError, "authority item"):
            validate_program_map(
                malformed_authority,
                document_ids=set(malformed_authority["document_map_sha256s"]),
            )

    def test_unmapped_or_conflicting_requirement_blocks_generation_acceptance(self) -> None:
        for scenario in ("mapping_unmapped", "mapping_conflict"):
            with self.subTest(scenario=scenario):
                store = self.create_store()
                engine = self.create_engine(store=store, scenario=scenario)
                engine.map_documents()
                with self.assertRaisesRegex(ValueError, "blocking coverage"):
                    engine.map_program()
                self.assertFalse(
                    any(
                        event["event_type"] == "map.generation_created"
                        for event in store.validate_event_chain()
                    )
                )
                authority_events = [
                    event
                    for event in store.validate_event_chain()
                    if event["event_type"] == "authority.opened"
                ]
                self.assertEqual(len(authority_events), 1 if scenario == "mapping_conflict" else 0)

    def test_program_mapper_must_report_exact_generation_artifact_paths(self) -> None:
        store = self.create_store()
        engine = self.create_engine(store=store, scenario="mapping_extra_artifact")
        engine.map_documents()
        with self.assertRaisesRegex(ValueError, "unexpected artifact paths"):
            engine.map_program()
        self.assertFalse(
            (store.paths.root / "logs/unexpected-mapper-output.json").exists()
        )
        self.assertFalse(
            any(
                event["event_type"] == "map.generation_created"
                for event in store.validate_event_chain()
            )
        )

    def test_brief_is_digest_bound_lossless_and_dependency_complete(self) -> None:
        document_hashes = {"plan-01": "a" * 64, "spec-01": "b" * 64}
        payload = {
            "schema_version": 1,
            "task_id": "plan-01:T1",
            "program_map_sha256": "c" * 64,
            "title": "Implement one bounded change",
            "dependencies": [],
            "source_references": [
                source_reference("plan-01", source_sha256=document_hashes["plan-01"]),
                source_reference(
                    "spec-01",
                    source_sha256=document_hashes["spec-01"],
                    exact_excerpt="The first approved requirement is immutable.",
                ),
            ],
            "global_constraints": [
                source_reference(
                    "spec-01",
                    source_sha256=document_hashes["spec-01"],
                    exact_excerpt="The first approved requirement is immutable.",
                )
            ],
            "acceptance": ["python3 evals/check_lean_mapping.py"],
            "expected_report_path": "reports/plan-01-T1.md",
        }
        validated = validate_task_brief(
            payload,
            program_map_sha256="c" * 64,
            document_hashes=document_hashes,
        )
        self.assertEqual(validated["source_references"], payload["source_references"])
        self.assertEqual(validated["acceptance"], payload["acceptance"])

        bad = json.loads(json.dumps(payload))
        bad["source_references"][0]["source_sha256"] = "d" * 64
        with self.assertRaisesRegex(ValueError, "source SHA"):
            validate_task_brief(
                bad,
                program_map_sha256="c" * 64,
                document_hashes=document_hashes,
            )

    def test_oversized_task_split_records_and_preserves_exact_source_coverage(self) -> None:
        payload = self.valid_program_map()
        original = payload["tasks"].pop()
        shared_reference = source_reference("plan-02", source_sha256="4" * 64)
        first = {
            **original,
            "task_id": "plan-02:T1.1",
            "title": "Integrate the first boundary",
            "brief_path": "briefs/plan-02-T1.1.json",
        }
        second = {
            **original,
            "task_id": "plan-02:T1.2",
            "title": "Integrate the second boundary",
            "dependencies": ["plan-02:T1.1"],
            "brief_path": "briefs/plan-02-T1.2.json",
        }
        payload["tasks"].extend([first, second])
        payload["task_splits"] = [
            {
                "source_task_id": "plan-02:T1",
                "split_task_ids": ["plan-02:T1.1", "plan-02:T1.2"],
                "source_references": [shared_reference],
                "reason": "bounded context split along an interface boundary",
            }
        ]
        validated = validate_program_map(
            payload, document_ids=set(payload["document_map_sha256s"])
        )
        split = validated["task_splits"][0]
        self.assertEqual(split["source_task_id"], "plan-02:T1")
        self.assertEqual(split["split_task_ids"], ["plan-02:T1.1", "plan-02:T1.2"])
        self.assertEqual(split["source_references"], [shared_reference])


if __name__ == "__main__":
    unittest.main(verbosity=2)
