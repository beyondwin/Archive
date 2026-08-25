#!/usr/bin/env python3
"""Completion-gate evals against a real temp git repo."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import clpe


def run_git(cwd, *args):
    subprocess.run(["git", *args], cwd=str(cwd), check=True,
                   capture_output=True, text=True)


class CompletionGatesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="clpe-gates-")
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name) / "repo"
        self.repo.mkdir()
        run_git(self.repo, "init", "-b", "main")
        run_git(self.repo, "config", "user.email", "eval@example.com")
        run_git(self.repo, "config", "user.name", "Eval")
        (self.repo / "seed.txt").write_text("seed\n", encoding="utf-8")
        run_git(self.repo, "add", "-A")
        run_git(self.repo, "commit", "-m", "seed")
        self.start = self.head()
        (self.repo / "work.txt").write_text("work\n", encoding="utf-8")
        run_git(self.repo, "add", "-A")
        run_git(self.repo, "commit", "-m", "work")

    def head(self):
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(self.repo),
                                capture_output=True, text=True, check=True)
        return result.stdout.strip()

    def structured(self, **overrides):
        base = {"status": "completed", "head_commit": self.head(),
                "summary": "done", "open_findings": []}
        base.update(overrides)
        return base

    def test_clean_matching_completion_passes(self):
        self.assertEqual(
            clpe.completion_gates(self.structured(), self.repo, self.start), []
        )

    def test_dirty_worktree_fails(self):
        (self.repo / "untracked.txt").write_text("x\n", encoding="utf-8")
        failures = clpe.completion_gates(self.structured(), self.repo, self.start)
        self.assertTrue(any("not clean" in f for f in failures))

    def test_head_mismatch_fails(self):
        failures = clpe.completion_gates(
            self.structured(head_commit="deadbeef" * 5), self.repo, self.start
        )
        self.assertTrue(any("head mismatch" in f for f in failures))

    def test_short_sha_prefix_accepted(self):
        failures = clpe.completion_gates(
            self.structured(head_commit=self.head()[:12]), self.repo, self.start
        )
        self.assertEqual(failures, [])

    def test_broken_ancestry_fails(self):
        failures = clpe.completion_gates(
            self.structured(), self.repo, "0" * 40
        )
        self.assertTrue(any("ancestor" in f for f in failures))

    def test_open_findings_fail(self):
        failures = clpe.completion_gates(
            self.structured(open_findings=["unfixed lint"]), self.repo, self.start
        )
        self.assertTrue(any("open_findings" in f for f in failures))


if __name__ == "__main__":
    unittest.main(verbosity=2)
