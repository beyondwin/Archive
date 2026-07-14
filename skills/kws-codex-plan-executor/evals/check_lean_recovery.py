#!/usr/bin/env python3
"""Focused schema-4 recovery, authority, refresh, and legacy checks."""
from __future__ import annotations
import json
import os
import stat
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock
SKILL_ROOT = Path(__file__).resolve().parents[1]
CLI = SKILL_ROOT / 'scripts' / 'cpe.py'
sys.path.insert(0, str(SKILL_ROOT / 'scripts'))
from cpe_runtime.launcher import ChildLauncher
from cpe_runtime.queue import QueueEngine
from cpe_runtime.store import RunStore
from cpe_runtime.worktree import Worktree
import cpe as cpe_cli
import cpe_runtime.store as store_module
from fake_codex import LeanEvalCase

class LeanRecoveryTest(LeanEvalCase):
    fixture_prefix = 'cpe-lean-recovery-'

    def setUp(self) -> None:
        super().setUp()
        self.invocations = self.root / 'invocations.jsonl'
        self.fake_state = self.root / 'state.json'
        self.bin_dir = self.install_fake_codex('bin')
        self.env = {**os.environ, 'PATH': f"{self.bin_dir}{os.pathsep}{os.environ.get('PATH', '')}", 'CODEX_HOME': str(self.home), 'CPE_FAKE_SCENARIO': 'mapping_success', 'CPE_FAKE_INVOCATION_LOG': str(self.invocations), 'CPE_FAKE_QUEUE_STATE': str(self.fake_state)}

    def cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, str(CLI), *arguments], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.env, check=False)

    def create_engine(self, scenario: str='mapping_success') -> tuple[RunStore, QueueEngine]:
        store = RunStore.create(codex_home=self.home, workspace=self.repo, specs=[self.repo / 'spec-a.md', self.repo / 'spec-b.md'], plans=[self.repo / 'plan-a.md', self.repo / 'plan-b.md'], program_plan=self.repo / 'program.md')
        (self.home / 'worktrees').mkdir(exist_ok=True)
        worktree = Worktree.create(source=self.repo, root=self.home / 'worktrees' / store.run_id, run_id=store.run_id)
        launcher = ChildLauncher(schema_path=SKILL_ROOT / 'templates' / 'child-result-schema.json', timeout_seconds=10, terminate_grace_seconds=0.05, environ={**self.env, 'CPE_FAKE_SCENARIO': scenario})
        return (store, QueueEngine(store, worktree, launcher))

    @staticmethod
    def file_snapshot(root: Path) -> tuple[tuple[str, bytes, int, int], ...]:
        return tuple(((str(path.relative_to(root)), path.read_bytes(), stat.S_IMODE(path.stat().st_mode), path.stat().st_mtime_ns) for path in sorted(root.rglob('*')) if path.is_file()))

    def test_schema3_inspect_is_read_only_and_resume_is_rejected(self) -> None:
        run_id = 'legacy-run'
        run = self.home / 'orchestrator' / run_id
        run.mkdir(parents=True, mode=448)
        (run / 'run_manifest.json').write_text(json.dumps({'schema_version': '3', 'run_id': run_id, 'execution_worktree': '/tmp/legacy-worktree'}), encoding='utf-8')
        (run / 'state.json').write_text(json.dumps({'status': 'interrupted', 'current_task': 'T3', 'tasks': ['T1', 'T2', 'T3']}), encoding='utf-8')
        before = self.file_snapshot(run)
        inspected = self.cli('inspect', '--run-id', run_id)
        self.assertEqual(inspected.returncode, 0, inspected.stderr or inspected.stdout)
        payload = json.loads(inspected.stdout)
        self.assertEqual(payload['schema_version'], 3)
        self.assertFalse(payload['resume_supported'])
        self.assertEqual(self.file_snapshot(run), before)
        resumed = self.cli('resume', '--run-id', run_id)
        self.assertEqual(resumed.returncode, 1, resumed.stderr)
        self.assertEqual(json.loads(resumed.stdout)['failure_code'], 'legacy_run_requires_historical_cpe')
        self.assertEqual(self.file_snapshot(run), before)

    def test_authority_resolution_requires_offered_answer_and_preserves_packet(self) -> None:
        store, engine = self.create_engine('mapping_conflict')
        engine.map_program()
        authority_path = 'maps/generation-0001/authority-queue.json'
        before = store.read_artifact(authority_path)
        rejected = self.cli('resume', '--run-id', store.run_id, '--authority-id', 'mapping-conflict-1', '--authority-answer', 'not-an-option')
        self.assertEqual(rejected.returncode, 1)
        self.assertEqual(json.loads(rejected.stdout)['failure_code'], 'authority_answer_invalid')
        self.assertEqual(store.read_artifact(authority_path), before)
        self.env['CPE_FAKE_SCENARIO'] = 'final_success'
        accepted = self.cli('resume', '--run-id', store.run_id, '--authority-id', 'mapping-conflict-1', '--authority-answer', 'spec-01')
        self.assertIn(accepted.returncode, {0, 2, 3}, accepted.stderr or accepted.stdout)
        reopened = RunStore.open(codex_home=self.home, run_id=store.run_id)
        resolved = [event for event in reopened.validate_event_chain() if event['event_type'] == 'authority.resolved']
        self.assertEqual(len(resolved), 1)
        self.assertEqual(reopened.read_artifact(authority_path), before)

    def test_explicit_refresh_creates_new_generation_and_preserves_first(self) -> None:
        store, engine = self.create_engine()
        engine.map_program()
        first_program = store.read_artifact('maps/generation-0001/program-map.json')
        (self.repo / 'spec-a.md').write_text((self.repo / 'spec-a.md').read_text(encoding='utf-8') + '\nNew constraint.\n', encoding='utf-8')
        self.env['CPE_FAKE_SCENARIO'] = 'refresh_success'
        refreshed = self.cli('resume', '--run-id', store.run_id, '--refresh-inputs')
        self.assertIn(refreshed.returncode, {0, 2, 3}, refreshed.stderr or refreshed.stdout)
        reopened = RunStore.open(codex_home=self.home, run_id=store.run_id)
        generation_ids = [event['payload']['generation_id'] for event in reopened.validate_event_chain() if event['event_type'] == 'map.generation_created']
        self.assertEqual(generation_ids, ['generation-0001', 'generation-0002'])
        self.assertEqual(reopened.read_artifact('maps/generation-0001/program-map.json'), first_program)
        self.assertTrue(reopened.read_artifact('maps/generation-0002/program-map.json'))
        invocations = [json.loads(line) for line in self.invocations.read_text(encoding='utf-8').splitlines()]
        self.assertEqual(len([item for item in invocations if item['role'] == 'document_mapper']), 6)

    def test_resume_rejects_branch_reset_that_discards_completed_commit(self) -> None:
        store, engine = self.create_engine()
        engine.map_program()
        engine.launcher.environ['CPE_FAKE_SCENARIO'] = 'queue_success'
        engine.tick()
        worktree = self.home / 'worktrees' / store.run_id
        base = subprocess.run(['git', '-C', str(worktree), 'rev-parse', 'HEAD^'], check=True, text=True, stdout=subprocess.PIPE).stdout.strip()
        subprocess.run(['git', '-C', str(worktree), 'reset', '--hard', base], check=True)
        before = len(self.invocations.read_text(encoding='utf-8').splitlines())
        self.env['CPE_FAKE_SCENARIO'] = 'final_success'
        resumed = self.cli('resume', '--run-id', store.run_id)
        self.assertEqual(resumed.returncode, 1)
        after = len(self.invocations.read_text(encoding='utf-8').splitlines())
        self.assertEqual(after, before)
if __name__ == '__main__':
    unittest.main()
