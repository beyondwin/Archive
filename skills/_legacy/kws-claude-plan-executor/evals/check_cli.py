#!/usr/bin/env python3
"""Public CLI contract evals for clpe.py, driven by fake_claude.py."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "clpe.py"
FAKE = ROOT / "evals" / "fake_claude.py"


class CliFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="clpe-cli-")
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.repo = base / "repo"
        self.repo.mkdir()
        self._git("init", "-b", "main")
        self._git("config", "user.email", "eval@example.com")
        self._git("config", "user.name", "Eval")
        (self.repo / "README.md").write_text("seed\n", encoding="utf-8")
        self._git("add", "-A")
        self._git("commit", "-m", "seed")
        self.plan = base / "demo plan.md"
        self.plan.write_text("# plan\n", encoding="utf-8")
        self.spec = base / "spec.md"
        self.spec.write_text("# spec\n", encoding="utf-8")
        self.home = base / "clpe-home"
        fakebin = base / "fakebin"
        fakebin.mkdir()
        wrapper = fakebin / "claude"
        wrapper.write_text(
            f"#!/usr/bin/env bash\nexec {sys.executable} '{FAKE}' \"$@\"\n",
            encoding="utf-8",
        )
        wrapper.chmod(0o755)
        self.argv_log = base / "argv.jsonl"
        self.env = dict(os.environ)
        self.env.update({
            "CLPE_HOME": str(self.home),
            "PATH": f"{fakebin}:{self.env['PATH']}",
            "CLPE_FAKE_ARGV_LOG": str(self.argv_log),
            "CLPE_TIMEOUT_FLOOR": "1",
            "CLAUDECODE": "1",
            "CLAUDE_CODE_ENTRYPOINT": "cli",
        })

    def _git(self, *args):
        subprocess.run(["git", *args], cwd=str(self.repo), check=True,
                       capture_output=True, text=True)

    def clpe(self, *extra, scenario="completed", resume_scenario=None,
             fake_sleep=None):
        env = dict(self.env)
        env["CLPE_FAKE_SCENARIO"] = scenario
        if resume_scenario:
            env["CLPE_FAKE_RESUME_SCENARIO"] = resume_scenario
        if fake_sleep:
            env["CLPE_FAKE_SLEEP"] = fake_sleep
        return subprocess.run([sys.executable, str(CLI), *extra],
                              env=env, capture_output=True, text=True)

    def run_plan(self, *extra, **kwargs):
        return self.clpe(
            "run", "--spec", str(self.spec), "--plan", str(self.plan),
            "--workspace", str(self.repo), "--timeout-seconds", "60",
            *extra, **kwargs,
        )

    def only_run_record(self):
        runs = list((self.home / "clpe").glob("*/run.json"))
        self.assertEqual(len(runs), 1)
        return json.loads(runs[0].read_text(encoding="utf-8"))

    def argv_lines(self):
        return [json.loads(line) for line in
                self.argv_log.read_text(encoding="utf-8").splitlines()]


class RunCommandTest(CliFixture):
    def test_completed_run(self):
        result = self.run_plan()
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        record = self.only_run_record()
        self.assertEqual(record["status"], "completed")
        self.assertEqual(record["session_id"], "sess-0001")
        self.assertEqual(record["launches"], 1)
        self.assertAlmostEqual(record["total_cost_usd"], 0.01)
        handoff = json.loads(
            (self.home / "clpe" / record["run_id"] / "handoff.json")
            .read_text(encoding="utf-8"))
        self.assertEqual(handoff["integration"], "not_observed")
        self.assertEqual(handoff["branch"], f"clpe/{record['run_id']}")

    def test_launch_contract_observed_by_child(self):
        self.run_plan()
        line = self.argv_lines()[0]
        argv = line["argv"]
        self.assertNotIn("--bare", argv)
        self.assertIn("stream-json", argv)
        for rule in ("Bash(git push*)", "Bash(git merge*)",
                     "Bash(rm -rf /*)", "Bash(git reset --hard origin*)"):
            self.assertIn(rule, argv)
        self.assertFalse(line["env_has_claudecode"])
        self.assertFalse(line["env_has_entrypoint"])
        record = self.only_run_record()
        # Compare canonical paths: on macOS the child's os.getcwd() resolves the
        # /var -> /private/var symlink while record["worktree"] (from
        # state_home().expanduser(), not .resolve()) does not. Resolving both
        # sides keeps the "child cwd IS the worktree" check exact and portable.
        self.assertEqual(str(Path(line["cwd"]).resolve()),
                         str(Path(record["worktree"]).resolve()))
        prompt = argv[argv.index("-p") + 1]
        self.assertIn("WORKTREE:", prompt)
        self.assertIn("superpowers:executing-plans", prompt)

    def test_exit_codes_by_scenario(self):
        for scenario, code, status in (
            ("failed", 1, "failed"),
            ("blocked", 2, "blocked"),
            ("success_no_structured", 1, "failed"),
            ("invalid", 1, "failed"),
            ("completed_dirty", 1, "failed"),
            ("completed_wrong_head", 1, "failed"),
            ("max_turns", 3, "resumable"),
            ("rate_limit", 2, "blocked"),
            ("auth", 2, "blocked"),
        ):
            with self.subTest(scenario=scenario):
                fixture = self.__class__("setUp")
                fixture.setUp()
                result = fixture.run_plan(scenario=scenario)
                self.assertEqual(result.returncode, code,
                                 f"{scenario}: {result.stdout}{result.stderr}")
                self.assertEqual(fixture.only_run_record()["status"], status)
                fixture.temp.cleanup()

    def test_dirty_workspace_halts_before_worktree(self):
        (self.repo / "dirty.txt").write_text("x\n", encoding="utf-8")
        result = self.run_plan()
        self.assertEqual(result.returncode, 2)
        self.assertIn("dirty_workspace", result.stdout)
        self.assertFalse((self.home / "worktrees").exists())


class ResumeCommandTest(CliFixture):
    def run_then_resume(self, scenario, resume_scenario, run_kwargs=None):
        result = self.run_plan(scenario=scenario, **(run_kwargs or {}))
        record = self.only_run_record()
        resume = self.clpe("resume", "--run-id", record["run_id"],
                           scenario=scenario, resume_scenario=resume_scenario)
        return result, resume, record["run_id"]

    def test_max_turns_then_resume_to_completion(self):
        first, resume, run_id = self.run_then_resume("max_turns", "completed")
        self.assertEqual(first.returncode, 3)
        self.assertEqual(resume.returncode, 0, resume.stdout + resume.stderr)
        record = self.only_run_record()
        self.assertEqual(record["status"], "completed")
        self.assertEqual(record["launches"], 2)
        lines = self.argv_lines()
        self.assertEqual(len(lines), 2)
        resume_argv = lines[1]["argv"]
        self.assertEqual(resume_argv[resume_argv.index("--resume") + 1],
                         "sess-0001")
        self.assertIn("Continue executing the plan",
                      resume_argv[resume_argv.index("-p") + 1])

    def test_timeout_then_resume(self):
        first = self.run_plan("--timeout-seconds", "2", scenario="timeout",
                              fake_sleep="30")
        self.assertEqual(first.returncode, 3, first.stdout + first.stderr)
        record = self.only_run_record()
        self.assertEqual(record["status"], "resumable")
        self.assertEqual(record["detail"], "timed_out")
        self.assertEqual(record["session_id"], "sess-0001")
        resume = self.clpe("resume", "--run-id", record["run_id"],
                           scenario="timeout", resume_scenario="completed")
        self.assertEqual(resume.returncode, 0, resume.stdout + resume.stderr)

    def test_resume_of_completed_run_is_noop(self):
        self.run_plan()
        run_id = self.only_run_record()["run_id"]
        resume = self.clpe("resume", "--run-id", run_id)
        self.assertEqual(resume.returncode, 0)
        self.assertIn("already_completed", resume.stdout)
        self.assertEqual(len(self.argv_lines()), 1)  # no second launch

    def test_resume_without_session_fails(self):
        self.run_plan(scenario="invalid")
        run_id = self.only_run_record()["run_id"]
        resume = self.clpe("resume", "--run-id", run_id)
        self.assertEqual(resume.returncode, 1)
        self.assertIn("no_session_to_resume", resume.stdout)

    def test_launch_budget_exhaustion_blocks(self):
        self.run_plan(scenario="max_turns")
        record = self.only_run_record()
        record["launches"] = 5
        run_json = self.home / "clpe" / record["run_id"] / "run.json"
        run_json.write_text(json.dumps(record), encoding="utf-8")
        resume = self.clpe("resume", "--run-id", record["run_id"])
        self.assertEqual(resume.returncode, 2)
        self.assertIn("launch_budget_exhausted", resume.stdout)

    def test_unknown_run_id_fails(self):
        resume = self.clpe("resume", "--run-id", "nope")
        self.assertEqual(resume.returncode, 1)
        self.assertIn("unknown_run", resume.stdout)


class InspectCommandTest(CliFixture):
    def test_inspect_prints_run_record(self):
        self.run_plan()
        run_id = self.only_run_record()["run_id"]
        argv_count_before = len(self.argv_lines())
        result = self.clpe("inspect", "--run-id", run_id)
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["run_id"], run_id)
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(len(self.argv_lines()), argv_count_before)  # read-only

    def test_inspect_unknown_run(self):
        result = self.clpe("inspect", "--run-id", "nope")
        self.assertEqual(result.returncode, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
