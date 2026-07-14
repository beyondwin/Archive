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
sys.path.insert(0, str(SKILL_ROOT / 'scripts'))
from cpe_runtime.contracts import ChildResult, canonical_json, validate_child_result
from cpe_runtime.store import RunStore
from cpe_runtime.launcher import ChildLauncher, ChildRequest
from cpe_runtime.worktree import Worktree
from fake_codex import LeanEvalCase

class LeanContractsTest(LeanEvalCase):
    fixture_prefix = 'cpe-lean-contracts-'

    def setUp(self) -> None:
        super().setUp()
        self.spec_a = self.repo / 'spec-a.md'
        self.spec_b = self.repo / 'spec-b.md'
        self.plan_a = self.repo / 'plan-a.md'
        self.plan_b = self.repo / 'plan-b.md'
        self.program = self.repo / 'program.md'

    def create_store(self) -> RunStore:
        return RunStore.create(codex_home=self.home, workspace=self.repo, specs=[self.spec_a, self.spec_b], plans=[self.plan_a, self.plan_b], program_plan=self.program)

    @staticmethod
    def generation_event_payload(**overrides: object) -> dict[str, object]:
        payload: dict[str, object] = {'generation_id': 'generation-0001', 'map_sha256': 'a' * 64, 'publication_manifest_path': 'maps/generation-0001/attempts/' + 'b' * 64 + '/accepted.json', 'publication_manifest_sha256': 'c' * 64, 'authority_ids': [], 'task_ids': []}
        payload.update(overrides)
        return payload

    def create_store_with_relationships(self) -> RunStore:
        return RunStore.create(codex_home=self.home, workspace=self.repo, specs=[self.spec_a, self.spec_b], plans=[self.plan_a, self.plan_b], program_plan=self.program, document_relationships={'plan-02': [{'relationship_type': 'amends', 'target_document_id': 'plan-01'}], 'program-plan': [{'relationship_type': 'coordinates', 'target_document_id': 'plan-02'}, {'relationship_type': 'coordinates', 'target_document_id': 'plan-01'}]})

    def create_fake_codex_bin(self) -> tuple[Path, Path]:
        bin_dir = self.install_fake_codex()
        fake_codex = bin_dir / 'codex'
        return (bin_dir, fake_codex)

    def make_child_request(self, *, store: RunStore, worktree: Worktree, attempt_id: str, role: str, item_id: str) -> ChildRequest:
        outbox = store.allocate_outbox(attempt_id)
        return ChildRequest(role=role, item_id=item_id, goal='Exercise one bounded launcher role.', input_paths=(self.plan_a.resolve(), self.spec_a.resolve()), repository=worktree.source, worktree=worktree.root, outbox=outbox, report_path=f'reports/{attempt_id}.md', applicable_skills=('using-superpowers', 'test-driven-development'), done_when=('the bounded role reports a valid result',))

    def test_snapshots_have_stable_role_local_order_and_are_immutable(self) -> None:
        store = self.create_store()
        documents = store.document_set()
        self.assertEqual([(item.document_id, item.role) for item in documents], [('spec-01', 'spec'), ('spec-02', 'spec'), ('plan-01', 'plan'), ('plan-02', 'plan'), ('program-plan', 'program_plan')])
        original = self.spec_a.read_bytes()
        first = documents[0]
        self.assertEqual(first.sha256, hashlib.sha256(original).hexdigest())
        self.assertEqual(first.byte_length, len(original))
        self.assertEqual(first.input_order, 0)
        self.assertEqual(store.read_artifact(first.snapshot_path), original)
        self.spec_a.write_text('# changed after create\n', encoding='utf-8')
        reopened = RunStore.open(codex_home=self.home, run_id=store.run_id)
        self.assertEqual(reopened.document_set(), documents)
        self.assertEqual(reopened.read_artifact(first.snapshot_path), original)
        self.assertEqual(reopened.document_set()[0].sha256, first.sha256)

    def test_events_are_hash_chained_replayed_and_tamper_evident(self) -> None:
        store = self.create_store()
        self.assertEqual(store.replay()['status'], 'mapping')
        provenance = store.validate_event_chain()
        self.assertEqual([event['event_type'] for event in provenance], ['run.created', 'documents.snapshotted'])
        self.assertEqual(provenance[0]['payload']['run_id'], store.run_id)
        self.assertEqual(provenance[1]['payload']['document_ids'], ['spec-01', 'spec-02', 'plan-01', 'plan-02', 'program-plan'])
        first = store.append_event('map.generation_created', self.generation_event_payload())
        self.assertEqual(first['prev_event_sha256'], provenance[-1]['event_sha256'])
        self.assertEqual(store.replay()['status'], 'running')
        second = store.append_event('run.interrupted', {'status': 'interrupted', 'failure_code': 'signal'})
        self.assertEqual(second['prev_event_sha256'], first['event_sha256'])
        events = store.validate_event_chain()
        self.assertEqual(events[-2:], (first, second))
        for event in events:
            body = {key: value for key, value in event.items() if key != 'event_sha256'}
            self.assertEqual(event['event_sha256'], hashlib.sha256(canonical_json(body)).hexdigest())
        replayed = store.replay()
        self.assertEqual(replayed['status'], 'interrupted')
        self.assertEqual(replayed['event_count'], 4)
        raw = store.paths.events.read_text(encoding='utf-8')
        store.paths.events.write_text(raw.replace('"failure_code":"signal"', '"failure_code":"tamper"'), encoding='utf-8')
        os.chmod(store.paths.events, 384)
        with self.assertRaises(ValueError):
            store.validate_event_chain()

    def test_launcher_uses_bounded_command_env_and_ingests_normalized_artifacts(self) -> None:
        store = self.create_store()
        worktree = Worktree.create(source=self.repo, root=self.root / 'launcher-worktree', run_id='launcher')
        bin_dir, _ = self.create_fake_codex_bin()
        invocation_log = self.root / 'invocations.jsonl'
        launcher = ChildLauncher(schema_path=SKILL_ROOT / 'templates' / 'child-result-schema.json', timeout_seconds=5, environ={**os.environ, 'PATH': str(bin_dir), 'CODEX_HOME': str(self.home), 'OPENAI_API_KEY': 'must-be-removed', 'ANTHROPIC_API_KEY': 'must-be-removed', 'AWS_SECRET_ACCESS_KEY': 'must-be-removed', 'AWS_SESSION_TOKEN': 'must-be-removed', 'GITHUB_TOKEN': 'must-be-removed', 'CPE_FAKE_SCENARIO': 'success', 'CPE_FAKE_INVOCATION_LOG': str(invocation_log)})
        request = self.make_child_request(store=store, worktree=worktree, attempt_id='review-success', role='reviewer', item_id='plan-01:T1-review')
        outcome = launcher.launch(request, worktree=worktree, store=store)
        self.assertEqual(outcome.result.status, 'completed')
        self.assertEqual(outcome.result.verdict, 'pass')
        self.assertEqual(len(outcome.event_digest), 64)
        self.assertGreaterEqual(outcome.elapsed_ms, 0)
        self.assertEqual(store.read_artifact('reports/review-success.md'), b'deterministic child report\n')
        invocation = json.loads(invocation_log.read_text(encoding='utf-8'))
        self.assertEqual(invocation['env']['PATH'], str(bin_dir))
        self.assertEqual(invocation['env']['CODEX_HOME'], str(self.home))
        for key in ('OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'AWS_SECRET_ACCESS_KEY', 'AWS_SESSION_TOKEN', 'GITHUB_TOKEN'):
            self.assertNotIn(key, invocation['env'])
        argv = invocation['argv']
        self.assertEqual(argv, ['exec', '--ignore-user-config', '--json', '--sandbox', 'read-only', '-C', str(worktree.root), '--add-dir', str(request.outbox.resolve(strict=True)), '--output-schema', str((SKILL_ROOT / 'templates' / 'child-result-schema.json').resolve()), '--output-last-message', str(request.outbox.resolve(strict=True) / '.child-result.json'), '-'])
        prohibited_policy_args = {'--model', '-m', '--profile', '-p', '--pricing', '--pricing-mode', '--billing-mode', '--release', '--release-status', '--proof-profile', '--compatibility', '--compatibility-policy', '--config', '-c'}
        self.assertTrue(prohibited_policy_args.isdisjoint(argv))
        write_request = self.make_child_request(store=store, worktree=worktree, attempt_id='task-success', role='task_agent', item_id='plan-01:T1')
        write_outcome = launcher.launch(write_request, worktree=worktree, store=store)
        self.assertEqual(write_outcome.result.commit, worktree.head())
        second_invocation = json.loads(invocation_log.read_text(encoding='utf-8').splitlines()[1])
        second_argv = second_invocation['argv']
        self.assertEqual(second_argv, ['exec', '--ignore-user-config', '--json', '--sandbox', 'workspace-write', '-C', str(worktree.root), '--add-dir', str(write_request.outbox.resolve(strict=True)), '--output-schema', str((SKILL_ROOT / 'templates' / 'child-result-schema.json').resolve()), '--output-last-message', str(write_request.outbox.resolve(strict=True) / '.child-result.json'), '-'])
        self.assertTrue(prohibited_policy_args.isdisjoint(second_argv))
if __name__ == '__main__':
    unittest.main(verbosity=2)
