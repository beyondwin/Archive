#!/usr/bin/env python3
"""Contract evals for the sequential plan runner."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from cpe_runtime.launcher import CodexLauncher
from cpe_runtime.runner import SequentialRunner
from cpe_runtime.state import StateStore


def git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout.strip()


class SequentialRunnerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="cpe-sequential-")
        self.root = Path(self.temporary.name)
        self.home = self.root / "codex-home"
        self.repo = self.root / "repo"
        self.home.mkdir(mode=0o700)
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        git(self.repo, "config", "user.email", "cpe@example.invalid")
        git(self.repo, "config", "user.name", "CPE Eval")
        self.specs = [self.repo / "spec-b.md", self.repo / "spec-a.md"]
        for index, path in enumerate(self.specs, 1):
            path.write_text(f"spec {index}\n", encoding="utf-8")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-q", "-m", "fixture base")
        self.log = self.root / "invocations.jsonl"
        self.fake = self.root / "codex"
        shutil.copyfile(ROOT / "evals" / "fake_codex.py", self.fake)
        self.fake.chmod(0o700)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def plan(self, number: int, scenario: str) -> Path:
        path = self.repo / f"input-plan-{number}.md"
        path.write_text(f"scenario:{scenario}\nplan {number}\n", encoding="utf-8")
        return path

    def runner(self) -> SequentialRunner:
        launcher = CodexLauncher(
            schema_path=ROOT / "templates" / "plan-result-schema.json",
            codex_bin=str(self.fake),
            timeout_seconds=5,
            environ={"PATH": os.environ["PATH"], "CODEX_HOME": str(self.home), "CPE_FAKE_INVOCATION_LOG": str(self.log)},
        )
        return SequentialRunner(codex_home=self.home, launcher=launcher)

    def invocations(self) -> list[dict[str, object]]:
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def test_snapshots_preserve_spec_and_plan_order(self) -> None:
        plans = [self.plan(2, "completed"), self.plan(1, "completed")]
        store = StateStore.create(
            run_root=self.home / "orchestrator" / "snapshot-order",
            run_id="snapshot-order",
            source_repository=self.repo,
            source_commit=git(self.repo, "rev-parse", "HEAD"),
            worktree=self.home / "worktrees" / "snapshot-order",
            branch="codex/snapshot-order",
            specs=self.specs,
            plans=plans,
        )
        inputs = store.state["inputs"]
        self.assertEqual([item["source_path"] for item in inputs], [str(path.resolve()) for path in self.specs + plans])
        self.assertEqual([item["document_id"] for item in inputs], ["spec-01", "spec-02", "plan-01", "plan-02"])
        self.assertEqual([Path(item["snapshot_path"]).read_text() for item in inputs], [path.read_text() for path in self.specs + plans])

    def test_two_plans_execute_sequentially_in_one_worktree(self) -> None:
        result = self.runner().run(workspace=self.repo, specs=self.specs, plans=[self.plan(1, "completed"), self.plan(2, "completed")], run_id="two-plans")
        self.assertEqual(result["status"], "completed")
        calls = self.invocations()
        self.assertEqual([call["plan_id"] for call in calls], ["plan-01", "plan-02"])
        self.assertEqual(len({call["worktree"] for call in calls}), 1)
        self.assertTrue((Path(calls[0]["worktree"]) / "plan-1.txt").is_file())
        self.assertTrue((Path(calls[0]["worktree"]) / "plan-2.txt").is_file())

    def test_resume_skips_completed_plan_and_continues_current_git_state(self) -> None:
        runner = self.runner()
        first = runner.run(workspace=self.repo, specs=[], plans=[self.plan(1, "completed"), self.plan(2, "resume_completed")], run_id="resume")
        self.assertEqual(first["status"], "blocked")
        prior_head = first["head_commit"]
        resumed = runner.resume(run_id="resume")
        self.assertEqual(resumed["status"], "completed")
        self.assertNotEqual(resumed["head_commit"], prior_head)
        self.assertEqual([call["plan_id"] for call in self.invocations()], ["plan-01", "plan-02", "plan-02"])

    def test_completed_requires_exact_head_ancestry_cleanliness_and_verification(self) -> None:
        for scenario in ("completed", "wrong_commit", "dirty_handoff"):
            with self.subTest(scenario=scenario):
                runner = self.runner()
                result = runner.run(workspace=self.repo, specs=[], plans=[self.plan(1, scenario)], run_id=f"handoff-{scenario}")
                self.assertEqual(result["status"], "completed" if scenario == "completed" else "failed")

    def test_initial_plus_one_recovery_attempt_is_the_automatic_limit(self) -> None:
        result = self.runner().run(workspace=self.repo, specs=[], plans=[self.plan(1, "interrupted")], run_id="attempt-limit")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["plans"][0]["attempt_count"], 2)
        self.assertEqual(len(self.invocations()), 2)

    def test_explicit_retry_failed_grants_exactly_one_attempt(self) -> None:
        runner = self.runner()
        runner.run(workspace=self.repo, specs=[], plans=[self.plan(1, "failed")], run_id="explicit-retry")
        before = len(self.invocations())
        result = runner.resume(run_id="explicit-retry", retry_failed=True)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(len(self.invocations()) - before, 1)
        self.assertEqual(result["plans"][0]["attempt_count"], 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
