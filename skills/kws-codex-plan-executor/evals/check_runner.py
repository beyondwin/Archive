#!/usr/bin/env python3
"""Contract evals for the sequential plan runner."""

from __future__ import annotations

import json
import os
import signal
import shutil
import subprocess
import sys
import tempfile
import time
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


class FailingCreateRunner(SequentialRunner):
    def _add_new_worktree(self, store: StateStore) -> None:
        raise subprocess.CalledProcessError(128, ["git", "worktree", "add"])


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

    def runner(self, **extra_environment: str) -> SequentialRunner:
        environment = {
            "PATH": os.environ["PATH"],
            "CODEX_HOME": str(self.home),
            "CPE_FAKE_INVOCATION_LOG": str(self.log),
            **extra_environment,
        }
        launcher = CodexLauncher(
            schema_path=ROOT / "templates" / "plan-result-schema.json",
            codex_bin=str(self.fake),
            timeout_seconds=5,
            environ=environment,
        )
        return SequentialRunner(codex_home=self.home, launcher=launcher)

    def invocations(self) -> list[dict[str, object]]:
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def start_run_process(
        self,
        *,
        run_id: str,
        plan: Path,
        extra_environment: dict[str, str],
    ) -> subprocess.Popen[str]:
        environment = dict(os.environ)
        environment.update(
            {
                "PYTHONPATH": str(ROOT / "scripts"),
                "CPE_TEST_HOME": str(self.home),
                "CPE_TEST_REPO": str(self.repo),
                "CPE_TEST_PLAN": str(plan),
                "CPE_TEST_RUN_ID": run_id,
                "CPE_TEST_CODEX": str(self.fake),
                "CPE_TEST_SCHEMA": str(
                    ROOT / "templates" / "plan-result-schema.json"
                ),
                "CPE_FAKE_INVOCATION_LOG": str(self.log),
                **extra_environment,
            }
        )
        program = """
import json
import os
from pathlib import Path
from cpe_runtime.launcher import CodexLauncher
from cpe_runtime.runner import SequentialRunner

launcher = CodexLauncher(
    schema_path=Path(os.environ["CPE_TEST_SCHEMA"]),
    codex_bin=os.environ["CPE_TEST_CODEX"],
    timeout_seconds=5,
    environ=dict(os.environ),
)
runner = SequentialRunner(
    codex_home=Path(os.environ["CPE_TEST_HOME"]),
    launcher=launcher,
)
result = runner.run(
    workspace=Path(os.environ["CPE_TEST_REPO"]),
    specs=[],
    plans=[Path(os.environ["CPE_TEST_PLAN"])],
    run_id=os.environ["CPE_TEST_RUN_ID"],
)
print(json.dumps(result, sort_keys=True), flush=True)
"""
        return subprocess.Popen(
            [sys.executable, "-c", program],
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def wait_for_path(self, path: Path, timeout: float = 3) -> None:
        deadline = time.monotonic() + timeout
        while not path.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertTrue(path.exists(), f"timed out waiting for {path}")

    def wait_for_process_exit(self, pid: int, timeout: float = 3) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.02)
        self.fail(f"process {pid} did not exit")

    def assert_state_rejected(self, store: StateStore, message: str) -> None:
        with self.assertRaisesRegex(ValueError, message):
            store.save()

    def test_state_rejects_impossible_plan_and_run_relationships(self) -> None:
        plans = [self.plan(1, "completed"), self.plan(2, "completed")]
        store = StateStore.create(
            run_root=self.home / "orchestrator" / "semantic-state",
            run_id="semantic-state",
            source_repository=self.repo,
            source_commit=git(self.repo, "rev-parse", "HEAD"),
            worktree=self.home / "worktrees" / "semantic-state",
            branch="codex/semantic-state",
            specs=[],
            plans=plans,
        )
        store.state["current_plan_index"] = 1
        self.assert_state_rejected(store, "completed prefix")

        store.state["current_plan_index"] = 0
        store.state["plans"].append(dict(store.state["plans"][0]))
        self.assert_state_rejected(store, "plan input count")

    def test_state_rejects_incomplete_completed_evidence(self) -> None:
        store = StateStore.create(
            run_root=self.home / "orchestrator" / "completed-evidence",
            run_id="completed-evidence",
            source_repository=self.repo,
            source_commit=git(self.repo, "rev-parse", "HEAD"),
            worktree=self.home / "worktrees" / "completed-evidence",
            branch="codex/completed-evidence",
            specs=[],
            plans=[self.plan(1, "completed")],
        )
        plan = store.state["plans"][0]
        plan.update(
            status="completed",
            starting_commit="1" * 40,
            accepted_commit="2" * 40,
        )
        store.state["current_plan_index"] = 1
        store.state["status"] = "completed"
        self.assert_state_rejected(store, "completed plan evidence is incomplete")

    def test_state_rejects_nonpristine_future_plan(self) -> None:
        store = StateStore.create(
            run_root=self.home / "orchestrator" / "future-plan",
            run_id="future-plan",
            source_repository=self.repo,
            source_commit=git(self.repo, "rev-parse", "HEAD"),
            worktree=self.home / "worktrees" / "future-plan",
            branch="codex/future-plan",
            specs=[],
            plans=[self.plan(1, "completed"), self.plan(2, "completed")],
        )
        store.state["plans"][1]["attempt_count"] = 1
        self.assert_state_rejected(store, "future plan is not pristine")

    def test_worktree_creation_failure_never_leaves_running_state(self) -> None:
        runner = FailingCreateRunner(
            codex_home=self.home,
            launcher=self.runner().launcher,
        )
        result = runner.run(
            workspace=self.repo,
            specs=[],
            plans=[self.plan(1, "completed")],
            run_id="create-failure",
        )
        self.assertEqual(result["status"], "failed")
        state = json.loads(
            (
                self.home
                / "orchestrator"
                / "create-failure"
                / "state.json"
            ).read_text()
        )
        self.assertEqual(state["status"], "failed")
        self.assertFalse((self.home / "worktrees" / "create-failure").exists())

    def test_resume_reconciles_verified_initializing_worktree(self) -> None:
        runner = self.runner()
        store = runner._initialize_run(
            workspace=self.repo,
            specs=[],
            plans=[self.plan(1, "completed")],
            run_id="reconcile-create",
        )
        runner._add_new_worktree(store)
        self.assertEqual(store.state["status"], "initializing")
        result = runner.resume(run_id="reconcile-create")
        self.assertEqual(result["status"], "completed")

    def test_resume_recreates_absent_initializing_worktree(self) -> None:
        runner = self.runner()
        runner._initialize_run(
            workspace=self.repo,
            specs=[],
            plans=[self.plan(1, "completed")],
            run_id="recreate-initializing",
        )
        result = runner.resume(run_id="recreate-initializing")
        self.assertEqual(result["status"], "completed")

    def test_initializing_commit_mismatch_fails_closed_without_deletion(self) -> None:
        runner = self.runner()
        store = runner._initialize_run(
            workspace=self.repo,
            specs=[],
            plans=[self.plan(1, "completed")],
            run_id="mismatched-initializing",
        )
        runner._add_new_worktree(store)
        worktree = Path(store.state["worktree"])
        (worktree / "unexpected.txt").write_text("unexpected\n", encoding="utf-8")
        git(worktree, "add", "unexpected.txt")
        git(worktree, "commit", "-q", "-m", "unexpected initializing change")
        with self.assertRaisesRegex(ValueError, "source commit"):
            runner.resume(run_id="mismatched-initializing")
        self.assertTrue(worktree.is_dir())

    def test_existing_run_branch_is_rejected_before_state_creation(self) -> None:
        git(self.repo, "branch", "codex/branch-collision")
        with self.assertRaisesRegex(ValueError, "branch already exists"):
            self.runner().run(
                workspace=self.repo,
                specs=[],
                plans=[self.plan(1, "completed")],
                run_id="branch-collision",
            )
        self.assertFalse(
            (self.home / "orchestrator" / "branch-collision").exists()
        )

    def test_broken_worktree_symlink_is_rejected_before_state_creation(self) -> None:
        worktrees = self.home / "worktrees"
        worktrees.mkdir(mode=0o700)
        (worktrees / "symlink-worktree").symlink_to(
            self.root / "missing-external-target"
        )
        with self.assertRaisesRegex(ValueError, "worktree already exists"):
            self.runner().run(
                workspace=self.repo,
                specs=[],
                plans=[self.plan(1, "completed")],
                run_id="symlink-worktree",
            )
        self.assertFalse(
            (self.home / "orchestrator" / "symlink-worktree").exists()
        )

    def test_concurrent_resume_does_not_launch_a_second_child(self) -> None:
        ready = self.root / "blocking-ready"
        release = self.root / "blocking-release"
        environment = {
            "CPE_FAKE_READY": str(ready),
            "CPE_FAKE_RELEASE": str(release),
        }
        process = self.start_run_process(
            run_id="concurrent-resume",
            plan=self.plan(1, "blocking_completed"),
            extra_environment=environment,
        )
        try:
            self.wait_for_path(ready)
            state = json.loads(
                (
                    self.home
                    / "orchestrator"
                    / "concurrent-resume"
                    / "state.json"
                ).read_text()
            )
            self.assertEqual(state["plans"][0]["attempt_count"], 1)
            result_path = Path(state["plans"][0]["result_path"])
            self.assertTrue(result_path.is_file())

            second = self.runner(**environment).resume(
                run_id="concurrent-resume"
            )
            self.assertEqual(second["status"], "interrupted")
            self.assertEqual(second["error"], "run_busy")
            self.assertEqual(len(self.invocations()), 1)
            unchanged = json.loads(
                (
                    self.home
                    / "orchestrator"
                    / "concurrent-resume"
                    / "state.json"
                ).read_text()
            )
            self.assertEqual(unchanged["plans"][0]["attempt_count"], 1)
        finally:
            release.touch()
            stdout, stderr = process.communicate(timeout=4)
        self.assertEqual(process.returncode, 0, stderr)
        self.assertEqual(json.loads(stdout)["status"], "completed")

    def test_coordinator_loss_keeps_the_child_lock(self) -> None:
        ready = self.root / "loss-ready"
        release = self.root / "loss-release"
        environment = {
            "CPE_FAKE_READY": str(ready),
            "CPE_FAKE_RELEASE": str(release),
        }
        process = self.start_run_process(
            run_id="coordinator-loss",
            plan=self.plan(1, "blocking_completed"),
            extra_environment=environment,
        )
        self.wait_for_path(ready)
        child_pid = int(ready.read_text())
        os.kill(process.pid, signal.SIGKILL)
        process.communicate(timeout=2)

        second = self.runner(**environment).resume(run_id="coordinator-loss")
        self.assertEqual(second["status"], "interrupted")
        self.assertEqual(second["error"], "run_busy")
        self.assertEqual(len(self.invocations()), 1)

        release.touch()
        self.wait_for_process_exit(child_pid)
        recovered = self.runner(**environment).resume(run_id="coordinator-loss")
        self.assertEqual(recovered["status"], "completed")
        self.assertEqual(len(self.invocations()), 2)

    def test_attempts_above_ten_use_numeric_prior_log_identity(self) -> None:
        runner = self.runner()
        runner.run(
            workspace=self.repo,
            specs=[],
            plans=[self.plan(1, "failed")],
            run_id="numeric-attempts",
        )
        store = StateStore.open(
            self.home / "orchestrator" / "numeric-attempts"
        )
        result_path = store.root / "results" / "plan-01-attempt-10.json"
        result_path.write_text("{}", encoding="utf-8")
        result_path.chmod(0o600)
        for attempt in (9, 10):
            log_path = store.root / "logs" / f"plan-01-attempt-{attempt}.log"
            log_path.write_text(f"attempt {attempt}\n", encoding="utf-8")
            log_path.chmod(0o600)
        plan = store.state["plans"][0]
        plan["attempt_count"] = 10
        plan["result_path"] = str(result_path.resolve())
        store.save()

        runner.resume(run_id="numeric-attempts", retry_failed=True)
        prior_log = self.invocations()[-1]["prior_log"]
        self.assertTrue(str(prior_log).endswith("plan-01-attempt-10.log"))

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
        inputs[2]["document_id"] = "../plan-01"
        store.state["plans"][0]["plan_id"] = "../plan-01"
        with self.assertRaisesRegex(ValueError, "input identity"):
            store.save()

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
