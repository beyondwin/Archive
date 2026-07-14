#!/usr/bin/env python3
"""Focused schema-4 public CLI and export checks."""
from __future__ import annotations
import hashlib
import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path
SKILL_ROOT = Path(__file__).resolve().parents[1]
CLI = SKILL_ROOT / 'scripts' / 'cpe.py'
PUBLIC_FIELDS = {'status', 'run_id', 'state_path', 'summary', 'next_action', 'failure_code', 'authority_items', 'terminal_artifact'}
from fake_codex import LeanEvalCase

class LeanCliTest(LeanEvalCase):
    fixture_prefix = 'cpe-lean-cli-'

    def setUp(self) -> None:
        super().setUp()
        self.env = {**os.environ, 'CODEX_HOME': str(self.home)}

    def cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, str(CLI), *arguments], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.env, check=False)

    @staticmethod
    def inventory(root: Path) -> tuple[tuple[str, int, int], ...]:
        if not root.exists():
            return ()
        return tuple(((str(path.relative_to(root)), path.stat().st_mode, path.stat().st_size) for path in sorted(root.rglob('*'))))

    def test_help_lists_only_four_public_commands(self) -> None:
        result = self.cli('--help')
        self.assertEqual(result.returncode, 0, result.stderr)
        usage = result.stdout.split('\n', 2)[0]
        self.assertIn('{run,resume,inspect,export}', usage)
        for removed in ('supervise', 'maintenance', 'repair', 'release'):
            self.assertNotIn(removed, result.stdout)

    def test_argument_shape_rejects_missing_plan_and_invalid_resume_combinations(self) -> None:
        missing_plan = self.cli('run', '--workspace', str(self.repo))
        self.assertEqual(missing_plan.returncode, 2)
        missing_answer = self.cli('resume', '--run-id', 'missing', '--authority-id', 'A0001')
        self.assertEqual(missing_answer.returncode, 2)
        combined = self.cli('resume', '--run-id', 'missing', '--authority-id', 'A0001', '--authority-answer', 'yes', '--refresh-inputs')
        self.assertEqual(combined.returncode, 2)
        removed = self.cli('run', '--plan', str(self.repo / 'plan-a.md'), '--workspace', str(self.repo), '--mode', 'interactive')
        self.assertEqual(removed.returncode, 2)
        for command in ('run', 'export'):
            duplicate_program = self.cli(command, '--plan', str(self.repo / 'plan-a.md'), '--program-plan', str(self.repo / 'program.md'), '--program-plan', str(self.repo / 'spec-a.md'), '--workspace', str(self.repo))
            self.assertEqual(duplicate_program.returncode, 2)
        duplicate_cases = [('run', '--workspace', str(self.repo)), ('resume', '--run-id', 'missing'), ('resume', '--authority-id', 'A0001'), ('resume', '--authority-answer', 'yes'), ('resume', '--refresh-inputs', None), ('inspect', '--run-id', 'missing'), ('export', '--workspace', str(self.repo)), ('export', '--mode', 'prompt')]
        for command, flag, value in duplicate_cases:
            base = [command]
            if command in {'run', 'export'}:
                base.extend(('--plan', str(self.repo / 'plan-a.md')))
                if flag != '--workspace':
                    base.extend(('--workspace', str(self.repo)))
            elif command == 'resume' and flag != '--run-id':
                base.extend(('--run-id', 'missing'))
            repeated = [flag, *([] if value is None else [value])] * 2
            self.assertEqual(self.cli(*base, *repeated).returncode, 2)

    def test_export_preserves_order_hashes_and_creates_no_state(self) -> None:
        home_before = self.inventory(self.home)
        repo_before = self.inventory(self.repo)
        ordered = [self.repo / 'spec-b.md', self.repo / 'spec-a.md', self.repo / 'plan-b.md', self.repo / 'plan-a.md', self.repo / 'program.md']
        result = self.cli('export', '--spec', str(ordered[0]), '--spec', str(ordered[1]), '--plan', str(ordered[2]), '--plan', str(ordered[3]), '--program-plan', str(ordered[4]), '--workspace', str(self.repo), '--mode', 'handoff')
        self.assertEqual(result.returncode, 0, result.stderr)
        positions = [result.stdout.index(str(path.resolve())) for path in ordered]
        self.assertEqual(positions, sorted(positions))
        for path in ordered:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertIn(digest, result.stdout)
        self.assertIn('No CPE run started', result.stdout)
        self.assertIn('scripts/cpe.py run', result.stdout)
        self.assertEqual(self.inventory(self.home), home_before)
        self.assertEqual(self.inventory(self.repo), repo_before)
if __name__ == '__main__':
    unittest.main()
