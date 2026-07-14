#!/usr/bin/env python3
"""Focused durable task, review, fix, and autonomous recovery queue checks."""
from __future__ import annotations
import json
import os
import subprocess
import sys
import threading
import time
import unittest
from collections.abc import Mapping
from pathlib import Path
SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / 'scripts'))
from cpe_runtime.launcher import ChildLauncher, ChildRequest
from cpe_runtime.contracts import AUTHORITY_CODES, ChildResult, validate_child_result
from cpe_runtime.queue import QueueEngine
from cpe_runtime.store import RunStore
from cpe_runtime.worktree import Worktree
from fake_codex import LeanEvalCase

class LeanQueueTest(LeanEvalCase):
    fixture_prefix = 'cpe-lean-queue-'
    repository_instructions = '# Repository Instructions\n\nUse strict TDD and commit clean handoffs.\n'

    def setUp(self) -> None:
        super().setUp()
        self.invocation_log = self.root / 'queue-invocations.jsonl'
        self.fake_state = self.root / 'queue-state.json'
        self.bin_dir = self.install_fake_codex()

    def create_engine(self, scenario: str, *, mapping_scenario: str='mapping_success') -> tuple[RunStore, QueueEngine]:
        store = RunStore.create(codex_home=self.home, workspace=self.repo, specs=[self.repo / 'spec-a.md', self.repo / 'spec-b.md'], plans=[self.repo / 'plan-a.md', self.repo / 'plan-b.md'], program_plan=self.repo / 'program.md')
        worktree = Worktree.create(source=self.repo, root=self.root / f'worktree-{scenario}', run_id=f'queue-{scenario}')
        launcher = ChildLauncher(schema_path=SKILL_ROOT / 'templates' / 'child-result-schema.json', timeout_seconds=10, environ={**os.environ, 'PATH': str(self.bin_dir), 'CODEX_HOME': str(self.home), 'CPE_FAKE_SCENARIO': mapping_scenario, 'CPE_FAKE_INVOCATION_LOG': str(self.invocation_log), 'CPE_FAKE_QUEUE_STATE': str(self.fake_state)})
        engine = QueueEngine(store, worktree, launcher)
        engine.map_program()
        launcher.environ['CPE_FAKE_SCENARIO'] = scenario
        return (store, engine)

    def invocations(self) -> list[dict[str, object]]:
        if not self.invocation_log.exists():
            return []
        return [json.loads(line) for line in self.invocation_log.read_text(encoding='utf-8').splitlines()]

    @staticmethod
    def lifecycle_events(store: RunStore) -> list[dict[str, object]]:
        return [event for event in store.validate_event_chain() if event['event_type'] in {'task.started', 'task.reported', 'review.reported'}]

    def test_dependencies_commit_bound_review_and_resume_do_not_redispatch(self) -> None:
        store, engine = self.create_engine('queue_success')
        self.assertEqual(engine.tick(), 'plan-01:T1')
        first_events = self.lifecycle_events(store)
        self.assertEqual([(event['event_type'], event['payload']['task_id']) for event in first_events], [('task.started', 'plan-01:T1'), ('task.reported', 'plan-01:T1'), ('review.reported', 'plan-01:T1')])
        task_commit = first_events[1]['payload']['commit']
        self.assertEqual(first_events[2]['payload']['commit'], task_commit)
        self.assertEqual(first_events[2]['payload']['verdict'], 'pass')
        store.append_event('run.interrupted', {'status': 'interrupted', 'failure_code': 'signal'})
        resumed = QueueEngine(RunStore.open(codex_home=self.home, run_id=store.run_id), engine.worktree, engine.launcher)
        self.assertEqual(resumed.tick(), 'plan-01:T2')
        t1_starts = [event for event in self.lifecycle_events(store) if event['event_type'] == 'task.started' and event['payload']['task_id'] == 'plan-01:T1']
        self.assertEqual(len(t1_starts), 1)

    def test_review_gets_exact_range_evidence_and_fix_is_consolidated(self) -> None:
        store, engine = self.create_engine('queue_review_fix')
        start = engine.worktree.head()
        self.assertEqual(engine.tick(), 'plan-01:T1')
        events = self.lifecycle_events(store)
        task_reports = [event for event in events if event['event_type'] == 'task.reported']
        reviews = [event for event in events if event['event_type'] == 'review.reported']
        self.assertEqual(len(task_reports), 2)
        self.assertEqual(len(reviews), 2)
        self.assertEqual(reviews[0]['payload']['verdict'], 'changes_requested')
        self.assertEqual(reviews[1]['payload']['verdict'], 'pass')
        started_roles = [event['payload']['role'] for event in events if event['event_type'] == 'task.started']
        self.assertEqual(started_roles, ['task_agent', 'fix_agent'])
        end = task_reports[-1]['payload']['commit']
        invocations = [item for item in self.invocations() if item['role'] not in {'program_mapper', 'document_mapper'}]
        self.assertEqual([item['role'] for item in invocations], ['task_agent', 'reviewer', 'fix_agent', 'reviewer'])
        reviewer_inputs = invocations[-1]['input_paths']
        diff_paths = [path for path in reviewer_inputs if path.endswith('.patch')]
        self.assertEqual(len(diff_paths), 1)
        self.assertEqual(Path(diff_paths[0]).read_text(encoding='utf-8'), engine.worktree.diff(start, end))
        self.assertIn("do not rerun the implementer's identical focused tests", invocations[-1]['prompt'])
        self.assertTrue(any(('findings' in path for path in invocations[2]['input_paths'])))
        before_resume = [item for item in self.invocations() if item['item_id'] == 'plan-01:T1']
        store.append_event('run.interrupted', {'status': 'interrupted', 'failure_code': 'signal'})
        resumed = QueueEngine(RunStore.open(codex_home=self.home, run_id=store.run_id), engine.worktree, engine.launcher)
        self.assertEqual(resumed.tick(), 'plan-01:T2')
        self.assertEqual([item for item in self.invocations() if item['item_id'] == 'plan-01:T1'], before_resume)
        marker = self.root / 'writer-started'
        engine.launcher.environ.update(CPE_FAKE_SCENARIO='writer_hold', CPE_FAKE_WRITER_MARKER=str(marker))
        first_outbox = store.allocate_outbox('writer-one')
        second_outbox = store.allocate_outbox('writer-two')
        second_launcher = ChildLauncher(schema_path=SKILL_ROOT / 'templates' / 'child-result-schema.json', timeout_seconds=10, environ=engine.launcher.environ)
        def request(role: str, item: str, outbox: Path) -> ChildRequest:
            return ChildRequest(role=role, item_id=item, goal='Prove one writer.', input_paths=(self.repo / 'plan-a.md',), repository=engine.worktree.source, worktree=engine.worktree.root, outbox=outbox, report_path=f'reports/{item}.md', applicable_skills=('using-superpowers',), done_when=('clean commit',))
        outcomes: list[object] = []
        thread = threading.Thread(target=lambda: outcomes.append(engine.launcher.launch(request('task_agent', 'writer-one', first_outbox), worktree=engine.worktree, store=store)))
        thread.start()
        deadline = time.monotonic() + 3
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(marker.exists())
        with self.assertRaisesRegex(ValueError, 'writer lease'):
            second_launcher.launch(request('integration_fix_agent', 'writer-two', second_outbox), worktree=engine.worktree, store=store)
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(outcomes), 1)

    def test_ordinary_failure_investigates_changes_strategy_and_records_decision(self) -> None:
        store, engine = self.create_engine('queue_ordinary_failure')
        self.assertEqual(engine.tick(), 'plan-01:T1')
        roles = [item['role'] for item in self.invocations() if item['role'] not in {'document_mapper', 'program_mapper'}]
        self.assertEqual(roles, ['task_agent', 'investigator', 'fix_agent', 'reviewer'])
        task_starts = [event['payload'] for event in self.lifecycle_events(store) if event['event_type'] == 'task.started']
        self.assertEqual(task_starts[0]['strategy_key'], 'initial')
        self.assertNotEqual(task_starts[1]['strategy_key'], 'initial')
        decisions = [json.loads(line) for line in store.paths.autonomy_decisions.read_text(encoding='utf-8').splitlines()]
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0]['affected_tasks'], ['plan-01:T1'])
        self.assertEqual(decisions[0]['selected'], 'fresh root-cause investigation')
        self.assertEqual([event['event_type'] for event in store.validate_event_chain() if event['event_type'] == 'autonomy.recorded'], ['autonomy.recorded'])
        evidence = task_starts[0]['evidence_sha256']
        engine._assert_new_attempt('plan-01:T1', 'third-distinct-strategy', evidence)
        with self.assertRaisesRegex(ValueError, 'strategy and evidence'):
            engine._assert_new_attempt('plan-01:T1', task_starts[0]['strategy_key'], evidence)
        launch = {'schema_version': 1, 'investigation_id': 'plan-01-T1-investigation-0003', 'task_id': 'plan-01:T1', 'sequence': 3, 'recovery_method': 'investigation-3', 'previous_strategy': 'second', 'dispatch_evidence_sha256': evidence, 'attempted_strategies': ['initial', 'second'], 'report_path': 'reports/plan-01-T1/investigation-3.md'}
        self.assertEqual(engine._validate_investigation_launch(launch, task_id='plan-01:T1', expected_sequence=3)['recovery_method'], 'investigation-3')
        base = {'role': 'task_agent', 'status': 'waiting_authority', 'item_id': 'T', 'commit': None, 'verdict': None, 'failure_code': None, 'strategy_key': None, 'affected_document_ids': [], 'artifact_paths': [], 'summary': 'authority'}
        for authority in AUTHORITY_CODES:
            self.assertEqual(validate_child_result({**base, 'authority_id': authority}, 'task_agent', 'T').authority_id, authority)
if __name__ == '__main__':
    unittest.main()
