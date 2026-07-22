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


if __name__ == "__main__":
    unittest.main(verbosity=2)
