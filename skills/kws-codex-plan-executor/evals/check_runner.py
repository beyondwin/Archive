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

from cpe_runtime.launcher import CodexLauncher, LaunchResult
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
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture_temporary = tempfile.TemporaryDirectory(
            prefix="cpe-sequential-base-"
        )
        cls.fixture_repo = Path(cls.fixture_temporary.name) / "repo"
        cls.fixture_repo.mkdir()
        subprocess.run(["git", "init", "-q", str(cls.fixture_repo)], check=True)
        git(cls.fixture_repo, "config", "user.email", "cpe@example.invalid")
        git(cls.fixture_repo, "config", "user.name", "CPE Eval")
        for index, name in enumerate(("spec-b.md", "spec-a.md"), 1):
            (cls.fixture_repo / name).write_text(
                f"spec {index}\n",
                encoding="utf-8",
            )
        git(cls.fixture_repo, "add", ".")
        git(cls.fixture_repo, "commit", "-q", "-m", "fixture base")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.fixture_temporary.cleanup()

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="cpe-sequential-")
        self.root = Path(self.temporary.name)
        self.home = self.root / "codex-home"
        self.repo = self.root / "repo"
        self.home.mkdir(mode=0o700)
        shutil.copytree(self.fixture_repo, self.repo)
        self.specs = [self.repo / "spec-b.md", self.repo / "spec-a.md"]
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

    def runner(
        self,
        *,
        timeout_seconds: float = 5,
        **extra_environment: str,
    ) -> SequentialRunner:
        environment = {
            "PATH": os.environ["PATH"],
            "CODEX_HOME": str(self.home),
            "CPE_FAKE_INVOCATION_LOG": str(self.log),
            **extra_environment,
        }
        launcher = CodexLauncher(
            schema_path=ROOT / "templates" / "plan-result-schema.json",
            codex_bin=str(self.fake),
            timeout_seconds=timeout_seconds,
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

    def cleanup_fixture_processes(self, pid_path: Path) -> None:
        if not pid_path.exists():
            return
        for line in pid_path.read_text().splitlines():
            try:
                os.kill(int(line), signal.SIGKILL)
            except (ProcessLookupError, ValueError):
                pass

    def start_cli_process(
        self,
        *,
        plan: Path,
        extra_environment: dict[str, str],
    ) -> subprocess.Popen[str]:
        environment = dict(os.environ)
        environment.update(
            {
                "CODEX_HOME": str(self.home),
                "PATH": f"{self.root}{os.pathsep}{os.environ['PATH']}",
                "CPE_FAKE_INVOCATION_LOG": str(self.log),
                **extra_environment,
            }
        )
        return subprocess.Popen(
            [
                sys.executable,
                str(ROOT / "scripts" / "cpe.py"),
                "run",
                "--plan",
                str(plan),
                "--workspace",
                str(self.repo),
            ],
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

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

        result_path = store.root / "results" / "plan-01-attempt-0.json"
        result_path.write_text("{}", encoding="utf-8")
        result_path.chmod(0o600)
        plan["result_path"] = str(result_path.resolve())
        self.assert_state_rejected(store, "completed plan attempt count")

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

    def test_late_interrupt_preserves_durable_terminal_state(self) -> None:
        for terminal in ("completed", "blocked"):
            with self.subTest(terminal=terminal):
                store = StateStore.create(
                    run_root=self.home / "orchestrator" / f"late-{terminal}",
                    run_id=f"late-{terminal}",
                    source_repository=self.repo,
                    source_commit=git(self.repo, "rev-parse", "HEAD"),
                    worktree=self.home / "worktrees" / f"late-{terminal}",
                    branch=f"codex/late-{terminal}",
                    specs=[],
                    plans=[self.plan(1, "completed")],
                )
                result_path = (
                    store.root / "results" / "plan-01-attempt-1.json"
                )
                result_path.write_text("{}", encoding="utf-8")
                result_path.chmod(0o600)
                plan = store.state["plans"][0]
                plan.update(
                    status=terminal,
                    starting_commit=store.state["source_commit"],
                    attempt_count=1,
                    result_path=str(result_path.resolve()),
                )
                if terminal == "completed":
                    plan["accepted_commit"] = store.state["source_commit"]
                    store.state["current_plan_index"] = 1
                store.state["status"] = terminal
                store.save()

                summary = self.runner()._record_interrupted(store)
                self.assertEqual(summary["status"], terminal)
                reopened = StateStore.open(store.root)
                self.assertEqual(reopened.state["status"], terminal)

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

    def test_timeout_kills_the_complete_process_group(self) -> None:
        pid_path = self.root / "timeout-grandchildren"
        try:
            result = self.runner(
                timeout_seconds=0.4,
                CPE_FAKE_GRANDCHILD_PID=str(pid_path),
            ).run(
                workspace=self.repo,
                specs=[],
                plans=[self.plan(1, "timeout_grandchild")],
                run_id="timeout-group",
            )
            self.assertEqual(result["status"], "failed")
            self.assertEqual(len(self.invocations()), 2)
            pids = [int(line) for line in pid_path.read_text().splitlines()]
            self.assertGreaterEqual(len(pids), 1)
            for pid in pids:
                with self.assertRaises(ProcessLookupError):
                    os.kill(pid, 0)
        finally:
            self.cleanup_fixture_processes(pid_path)

    def assert_signal_kills_complete_process_group(self, signum: int) -> None:
        pid_path = self.root / f"signal-grandchild-{signum}"
        process = self.start_cli_process(
            plan=self.plan(1, "timeout_grandchild"),
            extra_environment={"CPE_FAKE_GRANDCHILD_PID": str(pid_path)},
        )
        try:
            self.wait_for_path(pid_path)
            process.send_signal(signum)
            stdout, stderr = process.communicate(timeout=3)
            self.assertEqual(process.returncode, 3, stderr)
            self.assertEqual(json.loads(stdout)["status"], "interrupted")
            for line in pid_path.read_text().splitlines():
                with self.assertRaises(ProcessLookupError):
                    os.kill(int(line), 0)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=2)
            self.cleanup_fixture_processes(pid_path)

    def test_keyboard_interrupt_kills_the_complete_process_group(self) -> None:
        self.assert_signal_kills_complete_process_group(signal.SIGINT)

    def test_sigterm_kills_the_complete_process_group(self) -> None:
        self.assert_signal_kills_complete_process_group(signal.SIGTERM)

    def test_completed_child_with_live_descendant_is_rejected_and_cleaned(self) -> None:
        pid_path = self.root / "completed-grandchild"
        try:
            result = self.runner(
                CPE_FAKE_GRANDCHILD_PID=str(pid_path)
            ).run(
                workspace=self.repo,
                specs=[],
                plans=[self.plan(1, "completed_with_grandchild")],
                run_id="completed-descendant",
            )
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["error"], "forced_cleanup")
            pid = int(pid_path.read_text())
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)
        finally:
            self.cleanup_fixture_processes(pid_path)

    def test_large_log_retains_only_a_bounded_tail(self) -> None:
        result = self.runner().run(
            workspace=self.repo,
            specs=[],
            plans=[self.plan(1, "large_log")],
            run_id="large-log",
        )
        self.assertEqual(result["status"], "completed")
        log_path = (
            self.home
            / "orchestrator"
            / "large-log"
            / "logs"
            / "plan-01-attempt-1.log"
        )
        payload = log_path.read_bytes()
        self.assertLessEqual(len(payload), 1_048_576)
        self.assertIn(b"CPE_FINAL_LOG_MARKER", payload)
        self.assertIn(b"[cpe log truncated; discarded_bytes=", payload)

    def test_spawn_failure_is_recorded_as_a_durable_failed_attempt(self) -> None:
        launcher = CodexLauncher(
            schema_path=ROOT / "templates" / "plan-result-schema.json",
            codex_bin=str(self.root / "missing-codex"),
            timeout_seconds=1,
            environ={"PATH": os.environ["PATH"]},
        )
        runner = SequentialRunner(codex_home=self.home, launcher=launcher)
        result = runner.run(
            workspace=self.repo,
            specs=[],
            plans=[self.plan(1, "completed")],
            run_id="spawn-failure",
        )
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"], "invalid_result")
        self.assertEqual(result["plans"][0]["attempt_count"], 1)
        state = json.loads(
            (self.home / "orchestrator" / "spawn-failure" / "state.json").read_text()
        )
        self.assertEqual(state["status"], "failed")
        log_path = (
            self.home
            / "orchestrator"
            / "spawn-failure"
            / "logs"
            / "plan-01-attempt-1.log"
        )
        self.assertIn("[cpe spawn failed:", log_path.read_text())

    def test_launcher_command_and_prompt_are_minimal_and_ephemeral(self) -> None:
        launcher = self.runner().launcher
        result_path = self.root / "result.json"
        command = launcher._command(self.repo, result_path)
        prompt = launcher._prompt(
            worktree=self.repo,
            plan_id="plan-01",
            plan_path=self.plan(1, "completed"),
            spec_paths=[],
            starting_commit=git(self.repo, "rev-parse", "HEAD"),
            current_commit=git(self.repo, "rev-parse", "HEAD"),
            prior_result=None,
            prior_log=None,
        )
        self.assertIn("--ephemeral", command)
        self.assertNotIn("--json", command)
        self.assertNotIn("--add-dir", command)
        self.assertEqual(command.count("--output-last-message"), 1)
        self.assertNotIn("REPOSITORY:", prompt)
        self.assertIn("WORKTREE:", prompt)
        self.assertNotIn(
            "Write only the fixed schema result to RESULT_PATH",
            prompt,
        )

    def test_handoff_acceptance_and_result_isolation(self) -> None:
        runner = self.runner()
        result = runner.run(
            workspace=self.repo,
            specs=[],
            plans=[
                self.plan(1, "completed"),
                self.plan(2, "mutate_prior_nonzero_completed"),
            ],
            run_id="handoff-contract",
        )
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"], "nonzero_exit")
        first_result = Path(result["plans"][0]["result_path"])
        first_payload = json.loads(first_result.read_text())
        self.assertEqual(first_payload["plan_id"], "plan-01")
        self.assertEqual(first_result.stat().st_mode & 0o777, 0o400)

        store = StateStore.open(
            self.home / "orchestrator" / "handoff-contract"
        )
        plan = store.state["plans"][1]
        result_path = Path(plan["result_path"])
        payload = json.loads(result_path.read_text())
        log_path = store.root / "logs" / "plan-02-attempt-1.log"

        def outcome(
            candidate: dict[str, object],
            *,
            returncode: int = 0,
        ) -> LaunchResult:
            return LaunchResult(
                payload=candidate,
                returncode=returncode,
                timed_out=False,
                forced_cleanup=False,
                discarded_log_bytes=0,
                result_path=result_path,
                log_path=log_path,
            )

        self.assertIsNone(runner._handoff_error(store, plan, outcome(payload)))

        wrong_head = dict(payload, head_commit="0" * 40)
        self.assertEqual(
            runner._handoff_error(store, plan, outcome(wrong_head)),
            "wrong_head",
        )
        wrong_incomplete = dict(
            wrong_head,
            status="interrupted",
            verification=[],
        )
        self.assertEqual(
            runner._handoff_error(store, plan, outcome(wrong_incomplete)),
            "wrong_head",
        )

        failed_verification = dict(
            payload,
            verification=[{"command": "fake verify", "exit_code": 1}],
        )
        self.assertEqual(
            runner._handoff_error(
                store,
                plan,
                outcome(failed_verification),
            ),
            "verification_failed",
        )
        self.assertEqual(
            runner._handoff_error(store, plan, outcome(payload, returncode=1)),
            "nonzero_exit",
        )

        worktree = Path(store.state["worktree"])
        dirty = worktree / "untracked-handoff.txt"
        dirty.write_text("dirty\n", encoding="utf-8")
        self.assertEqual(
            runner._handoff_error(store, plan, outcome(payload)),
            "dirty_handoff",
        )
        dirty.unlink()

        git(worktree, "checkout", "-q", "--orphan", "handoff-unrelated")
        git(worktree, "rm", "-q", "-rf", ".")
        unrelated = worktree / "unrelated.txt"
        unrelated.write_text("unrelated\n", encoding="utf-8")
        git(worktree, "add", "unrelated.txt")
        git(worktree, "commit", "-q", "-m", "unrelated handoff")
        unrelated_payload = dict(payload, head_commit=git(worktree, "rev-parse", "HEAD"))
        self.assertEqual(
            runner._handoff_error(
                store,
                plan,
                outcome(unrelated_payload),
            ),
            "broken_ancestry",
        )

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
