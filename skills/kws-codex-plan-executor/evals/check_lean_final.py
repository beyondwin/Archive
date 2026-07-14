#!/usr/bin/env python3
"""Focused document-audit and single terminal-integration checks."""
from __future__ import annotations
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / 'scripts'))
from cpe_runtime import contracts
from cpe_runtime.launcher import ChildLauncher
from cpe_runtime.queue import QueueEngine
from cpe_runtime.store import RunStore
from cpe_runtime.worktree import Worktree
from fake_codex import LeanEvalCase

class LeanFinalTest(LeanEvalCase):
    fixture_prefix = 'cpe-lean-final-'
    repository_instructions = '# Repository Instructions\n\nUse strict TDD and one final verification.\n'

    def setUp(self) -> None:
        super().setUp()
        self.invocation_log = self.root / 'final-invocations.jsonl'
        self.fake_state = self.root / 'final-state.json'
        self.verification_log = self.root / 'verification-invocations.jsonl'
        self.bin_dir = self.install_fake_codex()

    def create_engine(self, scenario: str) -> tuple[RunStore, QueueEngine]:
        store = RunStore.create(codex_home=self.home, workspace=self.repo, specs=[self.repo / 'spec-a.md', self.repo / 'spec-b.md'], plans=[self.repo / 'plan-a.md', self.repo / 'plan-b.md'], program_plan=self.repo / 'program.md')
        worktree = Worktree.create(source=self.repo, root=self.root / f'worktree-{scenario}', run_id=f'final-{scenario}')
        launcher = ChildLauncher(schema_path=SKILL_ROOT / 'templates' / 'child-result-schema.json', timeout_seconds=10, terminate_grace_seconds=0.05, environ={**os.environ, 'PATH': str(self.bin_dir), 'CODEX_HOME': str(self.home), 'CPE_FAKE_SCENARIO': 'mapping_success', 'CPE_FAKE_INVOCATION_LOG': str(self.invocation_log), 'CPE_FAKE_QUEUE_STATE': str(self.fake_state), 'CPE_FAKE_VERIFICATION_LOG': str(self.verification_log)})
        engine = QueueEngine(store, worktree, launcher)
        engine.map_program()
        launcher.environ['CPE_FAKE_SCENARIO'] = scenario
        return (store, engine)

    def invocations(self) -> list[dict[str, object]]:
        return [json.loads(line) for line in self.invocation_log.read_text(encoding='utf-8').splitlines()]

    def verification_invocations(self) -> list[dict[str, object]]:
        if not self.verification_log.exists():
            return []
        return [json.loads(line) for line in self.verification_log.read_text(encoding='utf-8').splitlines()]

    def test_each_document_audits_scoped_evidence_before_one_terminal_pass(self) -> None:
        store, engine = self.create_engine('final_success')
        base = engine.worktree.base_commit
        while engine.tick() is not None:
            pass
        revision = engine.worktree.head()
        engine._run_document_audits(revision)
        before_resume = len(self.invocations())
        store.append_event('run.interrupted', {'status': 'interrupted', 'failure_code': 'signal'})
        state = engine.run_until_terminal()
        self.assertEqual(state['status'], 'completed')
        self.assertEqual(len([item for item in self.invocations()[:before_resume] if item['role'] == 'document_auditor']), 5)
        self.assertEqual(len([item for item in self.invocations()[before_resume:] if item['role'] == 'document_auditor']), 0)
        self.assertTrue(store.paths.result.is_file())
        documents = store.document_set()
        invocations = self.invocations()
        auditors = [item for item in invocations if item['role'] == 'document_auditor']
        self.assertEqual([item['item_id'] for item in auditors], [doc.document_id for doc in documents])
        program, selected = engine._program_context()
        task_by_id = {str(task['task_id']): task for task in program['tasks']}
        snapshots = {doc.document_id: str((store.paths.root / doc.snapshot_path).resolve()) for doc in documents}
        for invocation in auditors:
            document_id = str(invocation['item_id'])
            inputs = set(invocation['input_paths'])
            self.assertIn(snapshots[document_id], inputs)
            self.assertFalse({path for key, path in snapshots.items() if key != document_id} & inputs)
            relevant = {str(selected[str(task['brief_path'])]) for task in task_by_id.values() if document_id in task['document_ids']}
            unrelated = {str(selected[str(task['brief_path'])]) for task in task_by_id.values() if document_id not in task['document_ids']}
            self.assertTrue(relevant <= inputs)
            self.assertFalse(unrelated & inputs)
        plan_one = next((item for item in auditors if item['item_id'] == 'plan-01'))
        task_diffs = {Path(path).name: Path(path).read_text(encoding='utf-8') for path in plan_one['input_paths'] if '/diffs/plan-01-' in path}
        self.assertNotIn('cpe-plan-01-T2.txt', task_diffs['plan-01-plan-01-T1.patch'])
        self.assertNotIn('cpe-plan-02-T1.txt', task_diffs['plan-01-plan-01-T2.patch'])
        integrators = [item for item in invocations if item['role'] == 'program_final_integrator']
        self.assertEqual(len(integrators), 1)
        whole = [Path(path) for path in integrators[0]['input_paths'] if 'whole.patch' in path]
        self.assertEqual(len(whole), 1)
        self.assertEqual(whole[0].read_text(encoding='utf-8'), engine.worktree.diff(base, revision))
        terminal = json.loads(store.paths.result.read_text(encoding='utf-8'))
        self.assertEqual(terminal['revision'], revision)
        self.assertEqual(set(terminal['auditor_verdicts']), {doc.document_id for doc in documents})
        handoff_path = store.paths.root / f'verification/final/{revision}/integration-handoff.json'
        handoff = json.loads(handoff_path.read_text(encoding='utf-8'))
        self.assertEqual(handoff['producer'], 'cpe_launcher')
        self.assertEqual(handoff_path.stat().st_mode & 511, 384)
        self.assertEqual(len(self.verification_invocations()), 1)

    def test_blocked_auditor_prevents_integrator_and_completion(self) -> None:
        store, engine = self.create_engine('final_auditor_blocked')
        state = engine.run_until_terminal()
        self.assertEqual(state['status'], 'final_audit')
        self.assertFalse(store.paths.result.exists())
        roles = [item['role'] for item in self.invocations()]
        self.assertEqual(roles.count('document_auditor'), 5)
        self.assertNotIn('program_final_integrator', roles)

    def test_integration_fix_invalidates_all_final_evidence_and_repeats_once(self) -> None:
        store, engine = self.create_engine('final_integration_fix')
        state = engine.run_until_terminal()
        self.assertEqual(state['status'], 'completed')
        roles = [item['role'] for item in self.invocations()]
        self.assertEqual(roles.count('integration_fix_agent'), 1)
        self.assertEqual(roles.count('document_auditor'), 10)
        self.assertEqual(roles.count('program_final_integrator'), 2)
        audit_revisions = {event['payload']['commit'] for event in store.validate_event_chain() if event['event_type'] == 'audit.reported'}
        self.assertEqual(len(audit_revisions), 2)
        self.assertEqual(len(self.verification_invocations()), 2)
        self.assertEqual(json.loads(store.paths.result.read_text(encoding='utf-8'))['revision'], engine.worktree.head())
if __name__ == '__main__':
    unittest.main()
