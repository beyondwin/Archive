#!/usr/bin/env python3
"""Focused multi-document mapping and lossless task-brief checks."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import stat
import sys
import tempfile
import unittest
from unittest import mock
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
import cpe_runtime.store as store_module  # noqa: E402
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


def bound_statement(
    statement: str, reference: dict[str, object]
) -> dict[str, object]:
    return {
        "statement": statement,
        "source_references": [reference],
        "authority_ids": [],
    }


def bound_command(command: str, reference: dict[str, object]) -> dict[str, object]:
    return {
        "command": command,
        "source_references": [reference],
        "authority_ids": [],
    }


def dependency_edge(task_id: str, reference: dict[str, object]) -> dict[str, object]:
    return {
        "task_id": task_id,
        "source_references": [reference],
        "authority_ids": [],
    }


def empty_plan_wave_graph() -> dict[str, object]:
    return {"plans": [], "waves": [], "edges": []}


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
        self.assertNotIn("artifact_paths", events[-1]["payload"])

        program = json.loads(store.read_artifact(program_path))
        self.assertEqual(
            program["plan_wave_graph"]["edges"][0]["predecessor_id"],
            "plan-01",
        )
        self.assertEqual(
            {item["kind"] for item in program["hotspots"]},
            {"shared_file", "interface"},
        )
        self.assertEqual(
            {item["role"] for item in program["decisions"]}, {"spec"}
        )
        self.assertEqual(
            {item["role"] for item in program["constraints"]}, {"spec"}
        )
        self.assertGreaterEqual(
            len(program["coverage"]["spec-01:R1"]["source_references"]), 2
        )
        brief = json.loads(store.read_artifact("briefs/plan-01-T2.json"))
        self.assertEqual(brief["dependency_edges"][0]["task_id"], "plan-01:T1")
        self.assertTrue(brief["upstream_interface_commitments"])

    def test_generation_event_stays_bounded_for_sixty_two_task_program(self) -> None:
        store = self.create_store()
        engine = self.create_engine(store=store, scenario="mapping_many_tasks")

        program_path = engine.map_program()

        program = json.loads(store.read_artifact(program_path))
        self.assertEqual(len(program["tasks"]), 62)
        generation_event = next(
            event
            for event in store.validate_event_chain()
            if event["event_type"] == "map.generation_created"
        )
        payload = generation_event["payload"]
        self.assertNotIn("artifact_paths", payload)
        self.assertEqual(
            set(payload),
            {
                "generation_id",
                "map_sha256",
                "publication_manifest_path",
                "publication_manifest_sha256",
                "authority_ids",
                "task_ids",
            },
        )
        manifest = json.loads(store.read_artifact(payload["publication_manifest_path"]))
        self.assertEqual(len(manifest["artifacts"]), 65)
        self.assertEqual(
            set(manifest["artifacts"]),
            {
                program_path,
                "maps/generation-0001/coverage.json",
                "maps/generation-0001/authority-queue.json",
                *(task["brief_path"] for task in program["tasks"]),
            },
        )
        self.assertEqual(
            json.loads(store.read_artifact("briefs/plan-02-T60.json"))["task_id"],
            "plan-02:T60",
        )

    def test_accepted_publication_batch_loads_durable_state_once(self) -> None:
        store = self.create_store()
        engine = self.create_engine(store=store, scenario="mapping_many_tasks")
        engine.map_program()
        generation_event = next(
            event
            for event in store.validate_event_chain()
            if event["event_type"] == "map.generation_created"
        )
        payload = generation_event["payload"]

        with (
            mock.patch.object(
                store, "_artifact_records", wraps=store._artifact_records
            ) as artifact_records,
            mock.patch.object(
                store, "validate_event_chain", wraps=store.validate_event_chain
            ) as event_chain,
            mock.patch.object(
                store,
                "_validate_publication_manifest",
                wraps=store._validate_publication_manifest,
            ) as manifest_validation,
            mock.patch.object(
                store, "read_artifact", wraps=store.read_artifact
            ) as logical_reads,
        ):
            artifacts = engine._accepted_program_artifacts(
                payload["publication_manifest_path"],
                payload["publication_manifest_sha256"],
            )

        self.assertEqual(len(artifacts), 65)
        self.assertEqual(artifact_records.call_count, 1)
        self.assertEqual(event_chain.call_count, 1)
        self.assertEqual(manifest_validation.call_count, 1)
        self.assertEqual(logical_reads.call_count, 0)

    def test_accepted_publication_batch_rejects_physical_mode_drift(self) -> None:
        store = self.create_store()
        engine = self.create_engine(store=store, scenario="mapping_success")
        engine.map_program()
        generation_event = next(
            event
            for event in store.validate_event_chain()
            if event["event_type"] == "map.generation_created"
        )
        payload = generation_event["payload"]
        manifest = json.loads(store.read_artifact(payload["publication_manifest_path"]))
        physical_path = manifest["artifacts"]["briefs/plan-01-T1.json"][
            "relative_path"
        ]
        (store.paths.root / physical_path).chmod(0o644)

        with self.assertRaisesRegex(ValueError, "mode"):
            engine._accepted_program_artifacts(
                payload["publication_manifest_path"],
                payload["publication_manifest_sha256"],
            )

    def test_event_selected_publication_ignores_direct_logical_shadows(self) -> None:
        store = self.create_store()
        engine = self.create_engine(store=store, scenario="mapping_success")
        engine.map_program()
        logical_paths = (
            "maps/generation-0001/program-map.json",
            "maps/generation-0001/coverage.json",
            "briefs/plan-01-T1.json",
        )
        selected_bytes = {
            logical_path: store.read_artifact(logical_path)
            for logical_path in logical_paths
        }
        for logical_path in logical_paths:
            store.put_artifact(logical_path, b'{"shadow":true}')

        for logical_path in logical_paths:
            with self.subTest(logical_path=logical_path):
                self.assertEqual(
                    store.read_artifact(logical_path),
                    selected_bytes[logical_path],
                )

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
            "plan_wave_graph": empty_plan_wave_graph(),
            "hotspots": [],
            "decisions": [],
            "constraints": [],
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

    def test_document_map_rejects_unknown_requirement_kind(self) -> None:
        document = InputDocument(
            document_id="spec-01",
            role="spec",
            original_path="/tmp/spec.md",
            snapshot_path="inputs/spec-01.md",
            sha256="a" * 64,
            byte_length=10,
            input_order=0,
        )
        reference = source_reference("spec-01", source_sha256=document.sha256)
        payload = {
            "schema_version": 1,
            "document_id": "spec-01",
            "role": "spec",
            "source_sha256": document.sha256,
            "requirements": [
                {
                    "requirement_id": "spec-01:R1",
                    "kind": "invented_kind",
                    "heading": reference["heading"],
                    "line_start": reference["line_start"],
                    "line_end": reference["line_end"],
                    "exact_excerpt": reference["exact_excerpt"],
                    "constraints": [],
                }
            ],
            "task_candidates": [],
            "dependencies": [],
            "authority_items": [],
            "verification_commands": [],
            "plan_wave_graph": empty_plan_wave_graph(),
            "hotspots": [],
            "decisions": [],
            "constraints": [],
        }
        with self.assertRaisesRegex(ValueError, "requirement kind"):
            validate_document_map(payload, document=document)

        wrong_role = json.loads(json.dumps(payload))
        wrong_role["requirements"][0]["kind"] = "normative"
        wrong_role["decisions"] = [
            {
                "decision_id": "spec-01:D1",
                "role": "plan",
                "kind": "ordering",
                "statement": "invent a plan-only decision from a spec map",
                "source_references": [reference],
                "authority_ids": [],
            }
        ]
        with self.assertRaisesRegex(ValueError, "document role"):
            validate_document_map(wrong_role, document=document)

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
        plan_01_ref = source_reference("plan-01", source_sha256="a" * 64)
        plan_02_ref = source_reference("plan-02", source_sha256="b" * 64)
        spec_01_ref = source_reference("spec-01", source_sha256="c" * 64)
        spec_02_ref = source_reference("spec-02", source_sha256="d" * 64)
        return {
            "schema_version": 1,
            "generation": 1,
            "document_map_sha256s": map_hashes,
            "tasks": [
                {
                    "task_id": "plan-01:T1",
                    "title": "Implement one bounded change",
                    "dependencies": [],
                    "dependency_edges": [],
                    "document_ids": ["plan-01", "spec-01"],
                    "requirement_ids": ["spec-01:R1"],
                    "acceptance": [
                        bound_command("python3 evals/check_lean_mapping.py", plan_01_ref)
                    ],
                    "global_constraints": [],
                    "upstream_interface_commitments": [],
                    "brief_path": "briefs/plan-01-T1.json",
                },
                {
                    "task_id": "plan-01:T2",
                    "title": "Implement the dependent change",
                    "dependencies": ["plan-01:T1"],
                    "dependency_edges": [dependency_edge("plan-01:T1", plan_01_ref)],
                    "document_ids": ["plan-01", "spec-02"],
                    "requirement_ids": ["spec-02:R1"],
                    "acceptance": [
                        bound_command("python3 evals/check_lean_mapping.py", plan_01_ref)
                    ],
                    "global_constraints": [],
                    "upstream_interface_commitments": [
                        bound_statement("preserve the upstream interface", plan_01_ref)
                    ],
                    "brief_path": "briefs/plan-01-T2.json",
                },
                {
                    "task_id": "plan-02:T1",
                    "title": "Integrate both changes",
                    "dependencies": ["plan-01:T2"],
                    "dependency_edges": [dependency_edge("plan-01:T2", plan_02_ref)],
                    "document_ids": ["plan-02", "program-plan"],
                    "requirement_ids": [],
                    "acceptance": [
                        bound_command("python3 evals/check_lean_mapping.py", plan_02_ref)
                    ],
                    "global_constraints": [],
                    "upstream_interface_commitments": [],
                    "brief_path": "briefs/plan-02-T1.json",
                },
            ],
            "coverage": {
                "spec-01:R1": {
                    "disposition": "planned",
                    "task_ids": ["plan-01:T1"],
                    "reason": None,
                    "source_references": [spec_01_ref, plan_01_ref],
                    "authority_ids": [],
                },
                "spec-02:R1": {
                    "disposition": "planned",
                    "task_ids": ["plan-01:T2"],
                    "reason": None,
                    "source_references": [spec_02_ref, plan_01_ref],
                    "authority_ids": [],
                },
            },
            "task_splits": [],
            "plan_wave_graph": empty_plan_wave_graph(),
            "hotspots": [],
            "decisions": [],
            "constraints": [],
            "final_verification_commands": ["python3 evals/check_lean_mapping.py"],
            "authority_items": [],
        }

    @staticmethod
    def program_document_hashes() -> dict[str, str]:
        return {
            "spec-01": "c" * 64,
            "spec-02": "d" * 64,
            "plan-01": "a" * 64,
            "plan-02": "b" * 64,
            "program-plan": "e" * 64,
        }

    def test_program_map_uses_design_dispositions_and_rejects_bad_graphs(self) -> None:
        payload = self.valid_program_map()
        validated = validate_program_map(
            payload,
            document_hashes=self.program_document_hashes(),
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
                    "source_references": [
                        source_reference("spec-01", source_sha256="c" * 64)
                    ],
                    "authority_ids": ["A-defer"]
                    if disposition == "approved_deferred"
                    else [],
                }
                if disposition != "planned":
                    candidate["tasks"][0]["requirement_ids"] = []
                if disposition == "approved_deferred":
                    candidate["authority_items"] = [
                        {
                            "authority_id": "A-defer",
                            "authority_code": "material_scope_expansion",
                            "affected_task_ids": ["plan-01:T1"],
                            "question": "Defer this approved requirement?",
                            "options": ["defer", "implement"],
                            "recommended": "defer",
                            "source_references": [
                                source_reference("spec-01", source_sha256="c" * 64)
                            ],
                        }
                    ]
                if disposition == "conflict":
                    candidate["coverage"]["spec-01:R1"]["task_ids"] = [
                        "plan-01:T1"
                    ]
                    candidate["tasks"][0]["requirement_ids"] = ["spec-01:R1"]
                    candidate["coverage"]["spec-01:R1"]["authority_ids"] = [
                        "A-conflict"
                    ]
                    candidate["authority_items"] = [
                        {
                            "authority_id": "A-conflict",
                            "authority_code": "authoritative_document_conflict",
                            "affected_task_ids": ["plan-01:T1"],
                            "question": "Which requirement governs?",
                            "options": ["spec-01", "spec-02"],
                            "recommended": "spec-01",
                            "source_references": [
                                source_reference(
                                    "spec-01", source_sha256="c" * 64
                                )
                            ],
                        }
                    ]
                validate_program_map(
                    candidate,
                    document_hashes=self.program_document_hashes(),
                )

        wrong_conflict_task = self.valid_program_map()
        wrong_conflict_task["coverage"]["spec-01:R1"] = {
            "disposition": "conflict",
            "task_ids": ["plan-01:T1"],
            "reason": "approved documents conflict",
            "source_references": [
                source_reference("spec-01", source_sha256="c" * 64)
            ],
            "authority_ids": ["A-conflict"],
        }
        wrong_conflict_task["authority_items"] = [
            {
                "authority_id": "A-conflict",
                "authority_code": "authoritative_document_conflict",
                "affected_task_ids": ["plan-02:T1"],
                "question": "Which requirement governs?",
                "options": ["spec-01", "spec-02"],
                "recommended": "spec-01",
                "source_references": [
                    source_reference("spec-01", source_sha256="c" * 64)
                ],
            }
        ]
        with self.assertRaisesRegex(ValueError, "affected tasks"):
            validate_program_map(
                wrong_conflict_task,
                document_hashes=self.program_document_hashes(),
            )

        outdated = self.valid_program_map()
        outdated["coverage"]["spec-01:R1"]["disposition"] = "implemented"
        with self.assertRaises(ValueError):
            validate_program_map(outdated, document_hashes=self.program_document_hashes())

        unknown = self.valid_program_map()
        unknown["tasks"][1]["dependencies"] = ["plan-99:T1"]
        unknown["tasks"][1]["dependency_edges"] = [
            dependency_edge(
                "plan-99:T1",
                source_reference("plan-01", source_sha256="a" * 64),
            )
        ]
        with self.assertRaisesRegex(ValueError, "unknown dependency"):
            validate_program_map(unknown, document_hashes=self.program_document_hashes())

        cyclic = self.valid_program_map()
        cyclic["tasks"][0]["dependencies"] = ["plan-02:T1"]
        cyclic["tasks"][0]["dependency_edges"] = [
            dependency_edge(
                "plan-02:T1",
                source_reference("plan-01", source_sha256="a" * 64),
            )
        ]
        with self.assertRaisesRegex(ValueError, "cycle"):
            validate_program_map(cyclic, document_hashes=self.program_document_hashes())

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
                document_hashes=self.program_document_hashes(),
            )

    def test_unmapped_requirement_blocks_generation_acceptance(self) -> None:
        store = self.create_store()
        engine = self.create_engine(store=store, scenario="mapping_unmapped")
        engine.map_documents()
        with self.assertRaisesRegex(ValueError, "blocking coverage"):
            engine.map_program()
        self.assertFalse(
            any(
                event["event_type"] == "map.generation_created"
                for event in store.validate_event_chain()
            )
        )

    def test_conflict_accepts_generation_and_gates_only_affected_tasks(self) -> None:
        store = self.create_store()
        engine = self.create_engine(store=store, scenario="mapping_conflict")

        program_path = engine.map_program()

        program = json.loads(store.read_artifact(program_path))
        self.assertEqual(
            [task["task_id"] for task in program["tasks"]],
            ["plan-01:T1", "plan-01:T2", "plan-02:T1"],
        )
        self.assertEqual(program["tasks"][0]["requirement_ids"], ["spec-01:R1"])
        events = store.validate_event_chain()
        self.assertEqual(
            [event["event_type"] for event in events[-2:]],
            ["map.generation_created", "authority.opened"],
        )
        self.assertEqual(events[-1]["payload"]["task_ids"], ["plan-01:T1"])
        self.assertEqual(store.replay()["status"], "waiting_authority")

    def test_unsplit_brief_cannot_omit_assigned_requirement_source(self) -> None:
        store = self.create_store()
        engine = self.create_engine(
            store=store, scenario="mapping_brief_omits_requirement"
        )
        with self.assertRaisesRegex(ValueError, "requirement source"):
            engine.map_program()

    def test_unsplit_brief_cannot_substitute_unrelated_same_document_excerpt(self) -> None:
        store = self.create_store()
        engine = self.create_engine(
            store=store, scenario="mapping_brief_substitutes_requirement"
        )
        with self.assertRaisesRegex(ValueError, "requirement source"):
            engine.map_program()

    def test_each_split_brief_keeps_its_assigned_requirement_source(self) -> None:
        store = self.create_store()
        engine = self.create_engine(
            store=store,
            scenario="mapping_split_brief_substitutes_requirement",
        )
        with self.assertRaisesRegex(ValueError, "requirement source"):
            engine.map_program()

    def test_program_mapper_must_report_exact_generation_artifact_paths(self) -> None:
        for scenario in (
            "mapping_extra_artifact",
            "mapping_unreported_extra_artifact",
        ):
            with self.subTest(scenario=scenario):
                store = self.create_store()
                engine = self.create_engine(store=store, scenario=scenario)
                engine.map_documents()
                with self.assertRaisesRegex(ValueError, "unexpected artifact paths"):
                    engine.map_program()
                self.assertFalse(
                    (store.paths.root / "logs/unexpected-mapper-output.json").exists()
                )
                self.assertFalse(any(store.paths.outbox.iterdir()))
                self.assertFalse(
                    any(
                        event["event_type"] == "map.generation_created"
                        for event in store.validate_event_chain()
                    )
                )

    def test_rejected_staging_generation_is_discarded_and_resume_retries_cleanly(self) -> None:
        store = self.create_store()
        engine = self.create_engine(store=store, scenario="mapping_invalid_companion")
        engine.map_documents()
        with self.assertRaisesRegex(ValueError, "coverage companion"):
            engine.map_program()
        self.assertFalse((store.paths.root / "maps/generation-0001/program-map.json").exists())
        self.assertFalse(any(store.paths.outbox.iterdir()))

        resumed = QueueEngine(
            store,
            engine.worktree,
            self.create_launcher(scenario="mapping_success"),
        )
        self.assertEqual(
            resumed.map_program(), "maps/generation-0001/program-map.json"
        )

    def test_interrupted_publication_retries_with_different_valid_bytes(self) -> None:
        class SimulatedProcessInterruption(BaseException):
            pass

        store = self.create_store()
        engine = self.create_engine(store=store, scenario="mapping_success")
        engine.map_documents()
        original_put_artifact = store.put_artifact
        writes = 0

        def interrupt_after_first_write(relative_path: str, data: bytes) -> Path:
            nonlocal writes
            result = original_put_artifact(relative_path, data)
            writes += 1
            if writes == 1:
                raise SimulatedProcessInterruption
            return result

        store.put_artifact = interrupt_after_first_write  # type: ignore[method-assign]
        with self.assertRaises(SimulatedProcessInterruption):
            engine.map_program()
        self.assertGreater(
            len(store._artifact_records()),  # noqa: SLF001 - durable-state eval
            len(store.document_set()),
        )
        self.assertFalse(
            any(
                event["event_type"] == "map.generation_created"
                for event in store.validate_event_chain()
            )
        )

        reopened = RunStore.open(codex_home=self.home, run_id=store.run_id)
        resumed = QueueEngine(
            reopened,
            engine.worktree,
            self.create_launcher(scenario="mapping_success_retry_variant"),
        )
        self.assertEqual(
            resumed.map_program(), "maps/generation-0001/program-map.json"
        )
        brief = json.loads(reopened.read_artifact("briefs/plan-01-T1.json"))
        self.assertEqual(
            brief["expected_report_path"], "reports/retry-plan-01-T1.md"
        )

    def test_accepted_manifest_install_before_index_recovers_and_retry_selects_new_bytes(
        self,
    ) -> None:
        class SimulatedProcessInterruption(BaseException):
            pass

        store = self.create_store()
        engine = self.create_engine(store=store, scenario="mapping_success")
        engine.map_documents()
        original_atomic_write = store_module._atomic_write_new
        installed: list[Path] = []

        def interrupt_after_accepted_install(path: Path, data: bytes) -> None:
            original_atomic_write(path, data)
            if path.name == "accepted.json" and "attempts" in path.parts:
                installed.append(path)
                raise SimulatedProcessInterruption

        with mock.patch.object(
            store_module, "_atomic_write_new", interrupt_after_accepted_install
        ):
            with self.assertRaises(SimulatedProcessInterruption):
                engine.map_program()

        self.assertEqual(len(installed), 1)
        orphan_manifest = installed[0]
        orphan_relative = orphan_manifest.relative_to(store.paths.root).as_posix()
        self.assertNotIn(
            orphan_relative,
            {str(record["relative_path"]) for record in store._artifact_records()},
        )
        self.assertEqual(stat.S_IMODE(orphan_manifest.stat().st_mode), 0o600)
        self.assertFalse(
            any(
                event["event_type"] == "map.generation_created"
                for event in store.validate_event_chain()
            )
        )

        reopened = RunStore.open(codex_home=self.home, run_id=store.run_id)
        self.assertIn(
            orphan_relative,
            {str(record["relative_path"]) for record in reopened._artifact_records()},
        )
        resumed = QueueEngine(
            reopened,
            engine.worktree,
            self.create_launcher(scenario="mapping_success_retry_variant"),
        )
        self.assertEqual(
            resumed.map_program(), "maps/generation-0001/program-map.json"
        )
        generation_event = next(
            event
            for event in reopened.validate_event_chain()
            if event["event_type"] == "map.generation_created"
        )
        selected_manifest = generation_event["payload"]["publication_manifest_path"]
        self.assertNotEqual(selected_manifest, orphan_relative)
        self.assertIn("/attempts/", selected_manifest)
        brief = json.loads(reopened.read_artifact("briefs/plan-01-T1.json"))
        self.assertEqual(
            brief["expected_report_path"], "reports/retry-plan-01-T1.md"
        )

    def test_generation_event_replays_authority_wait_and_resume_repairs_open_event(
        self,
    ) -> None:
        class SimulatedProcessInterruption(BaseException):
            pass

        store = self.create_store()
        engine = self.create_engine(store=store, scenario="mapping_conflict")

        def interrupt_before_authority_events(*_args: object) -> None:
            raise SimulatedProcessInterruption

        engine._append_authority_events = (  # type: ignore[method-assign]
            interrupt_before_authority_events
        )
        with self.assertRaises(SimulatedProcessInterruption):
            engine.map_program()

        events = store.validate_event_chain()
        self.assertEqual(events[-1]["event_type"], "map.generation_created")
        self.assertEqual(
            events[-1]["payload"]["authority_ids"], ["mapping-conflict-1"]
        )
        self.assertEqual(events[-1]["payload"]["task_ids"], ["plan-01:T1"])
        self.assertEqual(store.replay()["status"], "waiting_authority")

        reopened = RunStore.open(codex_home=self.home, run_id=store.run_id)
        resumed = QueueEngine(
            reopened,
            engine.worktree,
            self.create_launcher(scenario="mapping_success"),
        )
        self.assertEqual(
            resumed.map_program(), "maps/generation-0001/program-map.json"
        )
        repaired_events = reopened.validate_event_chain()
        self.assertEqual(repaired_events[-1]["event_type"], "authority.opened")
        self.assertEqual(reopened.replay()["status"], "waiting_authority")
        self.assertEqual(
            sum(
                invocation["role"] == "program_mapper"
                for invocation in self.invocations()
            ),
            1,
        )

    def test_event_selected_publication_rejects_manifest_and_physical_tamper(
        self,
    ) -> None:
        for target_kind in ("manifest", "physical"):
            with self.subTest(target_kind=target_kind):
                store = self.create_store()
                worktree = Worktree.create(
                    source=self.repo,
                    root=self.root / f"worktree-tamper-{target_kind}",
                    run_id=f"mapping-tamper-{target_kind}",
                )
                engine = QueueEngine(
                    store,
                    worktree,
                    self.create_launcher(scenario="mapping_success"),
                )
                engine.map_program()
                generation_event = next(
                    event
                    for event in store.validate_event_chain()
                    if event["event_type"] == "map.generation_created"
                )
                manifest_path = generation_event["payload"][
                    "publication_manifest_path"
                ]
                manifest = json.loads(store.read_artifact(manifest_path))
                if target_kind == "manifest":
                    tamper_path = store.paths.root / manifest_path
                else:
                    tamper_path = store.paths.root / manifest["artifacts"][
                        "briefs/plan-01-T1.json"
                    ]["relative_path"]
                original = tamper_path.read_bytes()
                tamper_path.write_bytes(b"x" + original[1:])
                tamper_path.chmod(0o600)
                with self.assertRaisesRegex(ValueError, "digest"):
                    store.read_artifact("briefs/plan-01-T1.json")

    def test_noncompleted_mapper_does_not_hide_successful_sibling_outputs(self) -> None:
        store = self.create_store()
        engine = self.create_engine(store=store, scenario="mapping_noncompleted_result")
        with self.assertRaisesRegex(ValueError, "did not complete"):
            engine.map_documents()
        completed_paths = [
            engine._document_map_path(document)
            for document in store.document_set()
            if document.document_id != "spec-01"
        ]
        self.assertTrue(
            all((store.paths.root / path).is_file() for path in completed_paths)
        )

    def test_document_instruction_chains_and_program_union_are_deterministic(self) -> None:
        nested = self.repo / "specs"
        nested.mkdir()
        nested_spec = nested / "spec-a.md"
        shutil.copyfile(FIXTURES / "spec-a.md", nested_spec)
        (nested / "AGENTS.md").write_text(
            "# Nested Instructions\n\nPreserve nested spec ownership.\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "-C", str(self.repo), "add", "."], check=True)
        subprocess.run(
            ["git", "-C", str(self.repo), "commit", "-q", "-m", "nested instructions"],
            check=True,
        )
        store = RunStore.create(
            codex_home=self.home,
            workspace=self.repo,
            specs=[nested_spec, self.repo / "spec-b.md"],
            plans=[self.repo / "plan-a.md", self.repo / "plan-b.md"],
            program_plan=self.repo / "program.md",
        )
        engine = self.create_engine(store=store)
        engine.map_program()
        invocations = self.invocations()
        root_agents = str((engine.worktree.root / "AGENTS.md").resolve())
        nested_agents = str((engine.worktree.root / "specs/AGENTS.md").resolve())
        spec_invocation = next(
            item
            for item in invocations
            if item["role"] == "document_mapper"
            and any("spec-01.md" in path for path in item["input_paths"])
        )
        self.assertEqual(spec_invocation["input_paths"][-2:], [root_agents, nested_agents])
        program_invocation = invocations[-1]
        instruction_inputs = [
            path for path in program_invocation["input_paths"] if path.endswith("AGENTS.md")
        ]
        self.assertEqual(instruction_inputs, [root_agents, nested_agents])

    def test_mapping_allows_repository_without_root_agents(self) -> None:
        (self.repo / "AGENTS.md").unlink()
        subprocess.run(["git", "-C", str(self.repo), "add", "-u"], check=True)
        subprocess.run(
            ["git", "-C", str(self.repo), "commit", "-q", "-m", "no root instructions"],
            check=True,
        )
        store = self.create_store()
        engine = self.create_engine(store=store)
        self.assertEqual(engine.map_program(), "maps/generation-0001/program-map.json")
        self.assertFalse(
            any(
                path.endswith("AGENTS.md")
                for invocation in self.invocations()
                for path in invocation["input_paths"]
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
            "dependency_edges": [],
            "source_references": [
                source_reference("plan-01", source_sha256=document_hashes["plan-01"]),
                source_reference(
                    "spec-01",
                    source_sha256=document_hashes["spec-01"],
                    exact_excerpt="The first approved requirement is immutable.",
                ),
            ],
            "global_constraints": [
                bound_statement(
                    "preserve the immutable approved requirement",
                    source_reference(
                        "spec-01",
                        source_sha256=document_hashes["spec-01"],
                        exact_excerpt="The first approved requirement is immutable.",
                    ),
                )
            ],
            "acceptance": [
                bound_command(
                    "python3 evals/check_lean_mapping.py",
                    source_reference("plan-01", source_sha256=document_hashes["plan-01"]),
                )
            ],
            "upstream_interface_commitments": [
                bound_statement(
                    "preserve the upstream interface",
                    source_reference("plan-01", source_sha256=document_hashes["plan-01"]),
                )
            ],
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
        shared_reference = source_reference("plan-02", source_sha256="b" * 64)
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
            "dependency_edges": [
                dependency_edge("plan-02:T1.1", shared_reference)
            ],
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
            payload, document_hashes=self.program_document_hashes()
        )
        split = validated["task_splits"][0]
        self.assertEqual(split["source_task_id"], "plan-02:T1")
        self.assertEqual(split["split_task_ids"], ["plan-02:T1.1", "plan-02:T1.2"])
        self.assertEqual(split["source_references"], [shared_reference])

    def test_program_authority_and_split_refs_require_immutable_document_sha(self) -> None:
        authority = self.valid_program_map()
        authority["authority_items"] = [
            {
                "authority_id": "A1",
                "authority_code": "authoritative_document_conflict",
                "affected_task_ids": ["plan-01:T1"],
                "question": "Which authority governs?",
                "options": ["a", "b"],
                "recommended": "a",
                "source_references": [
                    source_reference("spec-01", source_sha256="f" * 64)
                ],
            }
        ]
        with self.assertRaisesRegex(ValueError, "source SHA"):
            validate_program_map(
                authority, document_hashes=self.program_document_hashes()
            )

        split = self.valid_program_map()
        original = split["tasks"].pop()
        split["tasks"].extend(
            [
                {
                    **original,
                    "task_id": "plan-02:T1.1",
                    "brief_path": "briefs/plan-02-T1.1.json",
                },
                {
                    **original,
                    "task_id": "plan-02:T1.2",
                    "dependencies": ["plan-02:T1.1"],
                    "dependency_edges": [
                        dependency_edge(
                            "plan-02:T1.1",
                            source_reference("plan-02", source_sha256="b" * 64),
                        )
                    ],
                    "brief_path": "briefs/plan-02-T1.2.json",
                },
            ]
        )
        split["task_splits"] = [
            {
                "source_task_id": "plan-02:T1",
                "split_task_ids": ["plan-02:T1.1", "plan-02:T1.2"],
                "source_references": [
                    source_reference("plan-02", source_sha256="f" * 64)
                ],
                "reason": "bounded split",
            }
        ]
        with self.assertRaisesRegex(ValueError, "source SHA"):
            validate_program_map(split, document_hashes=self.program_document_hashes())

    def test_conflict_authority_must_equal_split_tasks_with_requirement_edges(
        self,
    ) -> None:
        payload = self.valid_program_map()
        original = payload["tasks"].pop(0)
        plan_reference = source_reference("plan-01", source_sha256="a" * 64)
        first = {
            **original,
            "task_id": "plan-01:T1.1",
            "requirement_ids": [],
            "brief_path": "briefs/plan-01-T1.1.json",
        }
        second = {
            **original,
            "task_id": "plan-01:T1.2",
            "dependencies": ["plan-01:T1.1"],
            "dependency_edges": [
                dependency_edge("plan-01:T1.1", plan_reference)
            ],
            "brief_path": "briefs/plan-01-T1.2.json",
        }
        payload["tasks"][:0] = [first, second]
        payload["tasks"][2]["dependencies"] = ["plan-01:T1.2"]
        payload["tasks"][2]["dependency_edges"] = [
            dependency_edge("plan-01:T1.2", plan_reference)
        ]
        payload["coverage"]["spec-01:R1"] = {
            "disposition": "conflict",
            "task_ids": ["plan-01:T1.2"],
            "reason": "approved documents conflict",
            "source_references": [
                source_reference("spec-01", source_sha256="c" * 64)
            ],
            "authority_ids": ["A-conflict"],
        }
        payload["task_splits"] = [
            {
                "source_task_id": "plan-01:T1",
                "split_task_ids": ["plan-01:T1.1", "plan-01:T1.2"],
                "source_references": [plan_reference],
                "reason": "split along the conflicting requirement edge",
            }
        ]
        payload["authority_items"] = [
            {
                "authority_id": "A-conflict",
                "authority_code": "authoritative_document_conflict",
                "affected_task_ids": ["plan-01:T1.1"],
                "question": "Which requirement governs?",
                "options": ["spec-01", "spec-02"],
                "recommended": "spec-01",
                "source_references": [
                    source_reference("spec-01", source_sha256="c" * 64)
                ],
            }
        ]

        with self.assertRaisesRegex(ValueError, "affected tasks"):
            validate_program_map(
                payload,
                document_hashes=self.program_document_hashes(),
            )

    def test_split_briefs_collectively_preserve_candidate_contract(self) -> None:
        store = self.create_store()
        engine = self.create_engine(store=store, scenario="mapping_lossy_split")
        engine.map_documents()
        with self.assertRaisesRegex(ValueError, "split.*acceptance|split.*dependencies"):
            engine.map_program()

    def test_program_mapper_cannot_weaken_an_unsplit_candidate_contract(self) -> None:
        store = self.create_store()
        engine = self.create_engine(store=store, scenario="mapping_weaken_candidate")
        engine.map_documents()
        with self.assertRaisesRegex(ValueError, "task acceptance"):
            engine.map_program()


if __name__ == "__main__":
    unittest.main(verbosity=2)
