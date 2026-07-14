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
import unittest
from unittest import mock
from pathlib import Path
SKILL_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / 'lean-fixtures'
sys.path.insert(0, str(SKILL_ROOT / 'scripts'))
from cpe_runtime.contracts import InputDocument, canonical_json, validate_document_map, validate_program_map, validate_task_brief
from cpe_runtime.launcher import ChildLauncher
from cpe_runtime.queue import QueueEngine
import cpe_runtime.store as store_module
from cpe_runtime.store import RunStore
from cpe_runtime.worktree import Worktree
from fake_codex import LeanEvalCase

def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def source_reference(document_id: str, *, source_sha256: str, exact_excerpt: str='verbatim source text') -> dict[str, object]:
    return {'document_id': document_id, 'heading': 'Accepted Inputs', 'line_start': 1, 'line_end': 3, 'source_sha256': source_sha256, 'exact_excerpt': exact_excerpt}

def bound_statement(statement: str, reference: dict[str, object]) -> dict[str, object]:
    return {'statement': statement, 'source_references': [reference], 'authority_ids': []}

def bound_command(command: str, reference: dict[str, object]) -> dict[str, object]:
    return {'command': command, 'source_references': [reference], 'authority_ids': []}

def dependency_edge(task_id: str, reference: dict[str, object]) -> dict[str, object]:
    return {'task_id': task_id, 'source_references': [reference], 'authority_ids': []}

def empty_plan_wave_graph() -> dict[str, object]:
    return {'plans': [], 'waves': [], 'edges': []}

class LeanMappingTest(LeanEvalCase):
    fixture_prefix = 'cpe-lean-mapping-'
    repository_instructions = '# Repository Instructions\n\nPreserve exact source coverage.\n'

    def setUp(self) -> None:
        super().setUp()
        self.invocation_log = self.root / 'mapping-invocations.jsonl'

    def create_store(self) -> RunStore:
        return RunStore.create(codex_home=self.home, workspace=self.repo, specs=[self.repo / 'spec-a.md', self.repo / 'spec-b.md'], plans=[self.repo / 'plan-a.md', self.repo / 'plan-b.md'], program_plan=self.repo / 'program.md')

    def create_launcher(self, *, scenario: str='mapping_success') -> ChildLauncher:
        bin_dir = self.install_fake_codex(f'fake-bin-{scenario}')
        return ChildLauncher(schema_path=SKILL_ROOT / 'templates' / 'child-result-schema.json', timeout_seconds=10, environ={**os.environ, 'PATH': str(bin_dir), 'CODEX_HOME': str(self.home), 'CPE_FAKE_SCENARIO': scenario, 'CPE_FAKE_INVOCATION_LOG': str(self.invocation_log)})

    def create_engine(self, *, store: RunStore, scenario: str='mapping_success') -> QueueEngine:
        worktree = Worktree.create(source=self.repo, root=self.root / f'worktree-{scenario}', run_id=f'mapping-{scenario}')
        return QueueEngine(store, worktree, self.create_launcher(scenario=scenario))

    def invocations(self) -> list[dict[str, object]]:
        if not self.invocation_log.exists():
            return []
        return [json.loads(line) for line in self.invocation_log.read_text(encoding='utf-8').splitlines()]

    def install_unselected_publication(self, store: RunStore, label: str) -> tuple[str, str, bytes]:
        program_path = 'maps/generation-0001/program-map.json'
        program_bytes = canonical_json({'label': label})
        artifacts = {program_path: program_bytes}
        publication_id = QueueEngine._publication_id(artifacts)
        prefix = f'maps/generation-0001/attempts/{publication_id}/artifacts'
        physical_path = f'{prefix}/{program_path}'
        store.put_artifact(physical_path, program_bytes)
        manifest = {'schema_version': 1, 'generation_id': 'generation-0001', 'publication_id': publication_id, 'program_map_sha256': sha256(program_bytes), 'artifacts': {program_path: {'relative_path': physical_path, 'sha256': sha256(program_bytes), 'byte_length': len(program_bytes)}}}
        manifest_bytes = canonical_json(manifest)
        manifest_path = f'maps/generation-0001/attempts/{publication_id}/accepted.json'
        store.put_artifact(manifest_path, manifest_bytes)
        return (manifest_path, sha256(manifest_bytes), program_bytes)

    @staticmethod
    def live_attempt_manifests(store: RunStore) -> tuple[str, ...]:
        return tuple((str(record['relative_path']) for record in store._artifact_records() if str(record['relative_path']).endswith('/accepted.json') and '/attempts/' in str(record['relative_path'])))

    @staticmethod
    def install_partial_publication(store: RunStore, label: str) -> str:
        publication_id = sha256(label.encode('utf-8'))
        relative_path = f'maps/generation-0001/attempts/{publication_id}/artifacts/briefs/{label}.json'
        store.put_artifact(relative_path, canonical_json({'label': label}))
        return relative_path

    @staticmethod
    def live_attempt_ids(store: RunStore) -> set[str]:
        return {Path(str(record['relative_path'])).parts[3] for record in store._artifact_records() if str(record['relative_path']).startswith('maps/generation-0001/attempts/')}

    def test_maps_each_snapshot_once_then_program_from_maps_and_instructions(self) -> None:
        store = self.create_store()
        engine = self.create_engine(store=store)
        document_paths = engine.map_documents()
        self.assertEqual(document_paths, tuple((f'maps/generation-0001/documents/{document.document_id}.json' for document in store.document_set())))
        self.assertEqual([item['role'] for item in self.invocations()], ['document_mapper'] * 5)
        store.append_event('run.interrupted', {'status': 'interrupted', 'failure_code': 'signal'})
        engine = QueueEngine(RunStore.open(codex_home=self.home, run_id=store.run_id), engine.worktree, engine.launcher)
        program_path = engine.map_program()
        self.assertEqual(program_path, 'maps/generation-0001/program-map.json')
        invocations = self.invocations()
        self.assertEqual([item['role'] for item in invocations], ['document_mapper'] * 5 + ['program_mapper'])
        snapshot_paths = {str((store.paths.root / document.snapshot_path).resolve()) for document in store.document_set()}
        document_invocations = invocations[:5]
        for invocation in document_invocations:
            exact_inputs = set(invocation['input_paths'])
            self.assertEqual(len(exact_inputs & snapshot_paths), 1)
            self.assertIn(str((engine.worktree.root / 'AGENTS.md').resolve()), exact_inputs)
        self.assertEqual({next(iter(set(invocation['input_paths']) & snapshot_paths)) for invocation in document_invocations}, snapshot_paths)
        program_inputs = set(invocations[-1]['input_paths'])
        expected_maps = {str((store.paths.root / relative_path).resolve()) for relative_path in document_paths}
        self.assertTrue(expected_maps <= program_inputs)
        self.assertIn(str((engine.worktree.root / 'AGENTS.md').resolve()), program_inputs)
        self.assertFalse(program_inputs & snapshot_paths)
        events = store.validate_event_chain()
        self.assertEqual(events[-1]['event_type'], 'map.generation_created')
        self.assertEqual(events[-1]['payload']['generation_id'], 'generation-0001')
        self.assertNotIn('artifact_paths', events[-1]['payload'])
        program = json.loads(store.read_artifact(program_path))
        self.assertEqual(program['plan_wave_graph']['edges'][0]['predecessor_id'], 'plan-01')
        self.assertEqual({item['kind'] for item in program['hotspots']}, {'shared_file', 'interface'})
        self.assertEqual({item['role'] for item in program['decisions']}, {'spec'})
        self.assertEqual({item['role'] for item in program['constraints']}, {'spec'})
        self.assertGreaterEqual(len(program['coverage']['spec-01:R1']['source_references']), 2)
        brief = json.loads(store.read_artifact('briefs/plan-01-T2.json'))
        self.assertEqual(brief['dependency_edges'][0]['task_id'], 'plan-01:T1')
        self.assertTrue(brief['upstream_interface_commitments'])
        before_resume = len(self.invocations())
        resumed = QueueEngine(RunStore.open(codex_home=self.home, run_id=store.run_id), engine.worktree, engine.launcher)
        self.assertEqual(resumed.map_program(), program_path)
        self.assertEqual(len(self.invocations()), before_resume)

    def valid_program_map(self) -> dict[str, object]:
        map_hashes = {'spec-01': '1' * 64, 'spec-02': '2' * 64, 'plan-01': '3' * 64, 'plan-02': '4' * 64, 'program-plan': '5' * 64}
        plan_01_ref = source_reference('plan-01', source_sha256='a' * 64)
        plan_02_ref = source_reference('plan-02', source_sha256='b' * 64)
        spec_01_ref = source_reference('spec-01', source_sha256='c' * 64)
        spec_02_ref = source_reference('spec-02', source_sha256='d' * 64)
        return {'schema_version': 1, 'generation': 1, 'document_map_sha256s': map_hashes, 'tasks': [{'task_id': 'plan-01:T1', 'title': 'Implement one bounded change', 'dependencies': [], 'dependency_edges': [], 'document_ids': ['plan-01', 'spec-01'], 'requirement_ids': ['spec-01:R1'], 'acceptance': [bound_command('python3 evals/check_lean_mapping.py', plan_01_ref)], 'global_constraints': [], 'upstream_interface_commitments': [], 'brief_path': 'briefs/plan-01-T1.json'}, {'task_id': 'plan-01:T2', 'title': 'Implement the dependent change', 'dependencies': ['plan-01:T1'], 'dependency_edges': [dependency_edge('plan-01:T1', plan_01_ref)], 'document_ids': ['plan-01', 'spec-02'], 'requirement_ids': ['spec-02:R1'], 'acceptance': [bound_command('python3 evals/check_lean_mapping.py', plan_01_ref)], 'global_constraints': [], 'upstream_interface_commitments': [bound_statement('preserve the upstream interface', plan_01_ref)], 'brief_path': 'briefs/plan-01-T2.json'}, {'task_id': 'plan-02:T1', 'title': 'Integrate both changes', 'dependencies': ['plan-01:T2'], 'dependency_edges': [dependency_edge('plan-01:T2', plan_02_ref)], 'document_ids': ['plan-02', 'program-plan'], 'requirement_ids': [], 'acceptance': [bound_command('python3 evals/check_lean_mapping.py', plan_02_ref)], 'global_constraints': [], 'upstream_interface_commitments': [], 'brief_path': 'briefs/plan-02-T1.json'}], 'coverage': {'spec-01:R1': {'disposition': 'planned', 'task_ids': ['plan-01:T1'], 'reason': None, 'source_references': [spec_01_ref, plan_01_ref], 'authority_ids': []}, 'spec-02:R1': {'disposition': 'planned', 'task_ids': ['plan-01:T2'], 'reason': None, 'source_references': [spec_02_ref, plan_01_ref], 'authority_ids': []}}, 'task_splits': [], 'plan_wave_graph': empty_plan_wave_graph(), 'hotspots': [], 'decisions': [], 'constraints': [], 'final_verification_commands': ['python3 evals/check_lean_mapping.py'], 'authority_items': []}

    @staticmethod
    def program_document_hashes() -> dict[str, str]:
        return {'spec-01': 'c' * 64, 'spec-02': 'd' * 64, 'plan-01': 'a' * 64, 'plan-02': 'b' * 64, 'program-plan': 'e' * 64}

    def test_program_map_uses_design_dispositions_and_rejects_bad_graphs(self) -> None:
        payload = self.valid_program_map()
        validated = validate_program_map(payload, document_hashes=self.program_document_hashes())
        self.assertEqual([task['task_id'] for task in validated['tasks']], ['plan-01:T1', 'plan-01:T2', 'plan-02:T1'])
        for disposition in ('planned', 'preexisting_verify', 'explicit_non_goal', 'approved_deferred', 'conflict', 'unmapped'):
            with self.subTest(disposition=disposition):
                candidate = self.valid_program_map()
                candidate['coverage']['spec-01:R1'] = {'disposition': disposition, 'task_ids': ['plan-01:T1'] if disposition == 'planned' else [], 'reason': None if disposition == 'planned' else 'recorded basis', 'source_references': [source_reference('spec-01', source_sha256='c' * 64)], 'authority_ids': ['A-defer'] if disposition == 'approved_deferred' else []}
                if disposition != 'planned':
                    candidate['tasks'][0]['requirement_ids'] = []
                if disposition == 'approved_deferred':
                    candidate['authority_items'] = [{'authority_id': 'A-defer', 'authority_code': 'material_scope_expansion', 'affected_task_ids': ['plan-01:T1'], 'question': 'Defer this approved requirement?', 'options': ['defer', 'implement'], 'recommended': 'defer', 'source_references': [source_reference('spec-01', source_sha256='c' * 64)]}]
                if disposition == 'conflict':
                    candidate['coverage']['spec-01:R1']['task_ids'] = ['plan-01:T1']
                    candidate['tasks'][0]['requirement_ids'] = ['spec-01:R1']
                    candidate['coverage']['spec-01:R1']['authority_ids'] = ['A-conflict']
                    candidate['authority_items'] = [{'authority_id': 'A-conflict', 'authority_code': 'authoritative_document_conflict', 'affected_task_ids': ['plan-01:T1'], 'question': 'Which requirement governs?', 'options': ['spec-01', 'spec-02'], 'recommended': 'spec-01', 'source_references': [source_reference('spec-01', source_sha256='c' * 64)]}]
                validate_program_map(candidate, document_hashes=self.program_document_hashes())
        wrong_conflict_task = self.valid_program_map()
        wrong_conflict_task['coverage']['spec-01:R1'] = {'disposition': 'conflict', 'task_ids': ['plan-01:T1'], 'reason': 'approved documents conflict', 'source_references': [source_reference('spec-01', source_sha256='c' * 64)], 'authority_ids': ['A-conflict']}
        wrong_conflict_task['authority_items'] = [{'authority_id': 'A-conflict', 'authority_code': 'authoritative_document_conflict', 'affected_task_ids': ['plan-02:T1'], 'question': 'Which requirement governs?', 'options': ['spec-01', 'spec-02'], 'recommended': 'spec-01', 'source_references': [source_reference('spec-01', source_sha256='c' * 64)]}]
        with self.assertRaisesRegex(ValueError, 'affected tasks'):
            validate_program_map(wrong_conflict_task, document_hashes=self.program_document_hashes())
        outdated = self.valid_program_map()
        outdated['coverage']['spec-01:R1']['disposition'] = 'implemented'
        with self.assertRaises(ValueError):
            validate_program_map(outdated, document_hashes=self.program_document_hashes())
        unknown = self.valid_program_map()
        unknown['tasks'][1]['dependencies'] = ['plan-99:T1']
        unknown['tasks'][1]['dependency_edges'] = [dependency_edge('plan-99:T1', source_reference('plan-01', source_sha256='a' * 64))]
        with self.assertRaisesRegex(ValueError, 'unknown dependency'):
            validate_program_map(unknown, document_hashes=self.program_document_hashes())
        cyclic = self.valid_program_map()
        cyclic['tasks'][0]['dependencies'] = ['plan-02:T1']
        cyclic['tasks'][0]['dependency_edges'] = [dependency_edge('plan-02:T1', source_reference('plan-01', source_sha256='a' * 64))]
        with self.assertRaisesRegex(ValueError, 'cycle'):
            validate_program_map(cyclic, document_hashes=self.program_document_hashes())
        malformed_authority = self.valid_program_map()
        malformed_authority['authority_items'] = [{'authority_id': 'A1', 'authority_code': 'authoritative_document_conflict', 'affected_task_ids': ['plan-01:T1'], 'question': 'Which authority governs?', 'options': ['spec-01', 'spec-02'], 'recommended': 'spec-01', 'source_references': [source_reference('spec-01', source_sha256='1' * 64)], 'unexpected': 'must fail closed'}]
        with self.assertRaisesRegex(ValueError, 'authority item'):
            validate_program_map(malformed_authority, document_hashes=self.program_document_hashes())

    def test_brief_is_digest_bound_lossless_and_dependency_complete(self) -> None:
        document_hashes = {'plan-01': 'a' * 64, 'spec-01': 'b' * 64}
        payload = {'schema_version': 1, 'task_id': 'plan-01:T1', 'program_map_sha256': 'c' * 64, 'title': 'Implement one bounded change', 'dependencies': [], 'dependency_edges': [], 'source_references': [source_reference('plan-01', source_sha256=document_hashes['plan-01']), source_reference('spec-01', source_sha256=document_hashes['spec-01'], exact_excerpt='The first approved requirement is immutable.')], 'global_constraints': [bound_statement('preserve the immutable approved requirement', source_reference('spec-01', source_sha256=document_hashes['spec-01'], exact_excerpt='The first approved requirement is immutable.'))], 'acceptance': [bound_command('python3 evals/check_lean_mapping.py', source_reference('plan-01', source_sha256=document_hashes['plan-01']))], 'upstream_interface_commitments': [bound_statement('preserve the upstream interface', source_reference('plan-01', source_sha256=document_hashes['plan-01']))], 'expected_report_path': 'reports/plan-01-T1.md'}
        validated = validate_task_brief(payload, program_map_sha256='c' * 64, document_hashes=document_hashes)
        self.assertEqual(validated['source_references'], payload['source_references'])
        self.assertEqual(validated['acceptance'], payload['acceptance'])
        bad = json.loads(json.dumps(payload))
        bad['source_references'][0]['source_sha256'] = 'd' * 64
        with self.assertRaisesRegex(ValueError, 'source SHA'):
            validate_task_brief(bad, program_map_sha256='c' * 64, document_hashes=document_hashes)
if __name__ == '__main__':
    unittest.main(verbosity=2)
