#!/usr/bin/env python3
"""Public CLI contract evals for the sequential runner."""

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
CLI = ROOT / "scripts" / "cpe.py"


class SequentialCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="cpe-cli-")
        self.root = Path(self.temporary.name)
        self.home = self.root / "codex-home"
        self.repo = self.root / "repo"
        self.bin = self.root / "bin"
        self.home.mkdir(mode=0o700)
        self.repo.mkdir()
        self.bin.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.email", "cpe@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.name", "CPE Eval"], check=True)
        self.specs = [self.repo / "spec-b.md", self.repo / "spec-a.md"]
        self.plans = [self.repo / "plan-b.md", self.repo / "plan-a.md"]
        for path in self.specs:
            path.write_text(f"# {path.stem}\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-q", "-m", "fixture"], check=True)
        for path in self.plans:
            path.write_text("scenario:completed\n", encoding="utf-8")
        fake = self.bin / "codex"
        shutil.copyfile(ROOT / "evals" / "fake_codex.py", fake)
        fake.chmod(0o700)
        self.environment = dict(os.environ)
        self.environment.update({"CODEX_HOME": str(self.home), "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}"})

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def command(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CLI), *arguments], env=self.environment,
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )

    def require_cutover(self) -> None:
        if "export" in CLI.read_text(encoding="utf-8"):
            self.skipTest("sequential CLI cutover not implemented")

    def test_help_exposes_only_run_resume_and_inspect(self) -> None:
        source = CLI.read_text(encoding="utf-8")
        self.assertNotIn("export", source)
        result = self.command("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("{run,resume,inspect}", result.stdout)
        self.assertNotIn("export", result.stdout)

    def test_run_requires_absolute_workspace_and_at_least_one_plan(self) -> None:
        self.require_cutover()
        missing = self.command("run", "--workspace", str(self.repo))
        self.assertEqual(missing.returncode, 1)
        self.assertEqual(json.loads(missing.stdout)["status"], "failed")
        relative = self.command("run", "--workspace", "repo", "--plan", str(self.plans[0]))
        self.assertEqual(relative.returncode, 1)
        self.assertEqual(json.loads(relative.stdout)["status"], "failed")

    def test_repeated_spec_and_plan_flags_preserve_order(self) -> None:
        self.require_cutover()
        result = self.command(
            "run", "--spec", str(self.specs[0]), "--spec", str(self.specs[1]),
            "--plan", str(self.plans[0]), "--plan", str(self.plans[1]),
            "--workspace", str(self.repo),
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        public = json.loads(result.stdout)
        state = json.loads((self.home / "orchestrator" / public["run_id"] / "state.json").read_text())
        self.assertEqual(
            [record["source_path"] for record in state["inputs"]],
            [str(path.resolve()) for path in self.specs + self.plans],
        )

    def test_inspect_is_read_only_and_historical_format_is_rejected(self) -> None:
        self.require_cutover()
        created = self.command("run", "--plan", str(self.plans[0]), "--workspace", str(self.repo))
        self.assertEqual(created.returncode, 0, created.stderr + created.stdout)
        run_id = json.loads(created.stdout)["run_id"]
        state_path = self.home / "orchestrator" / run_id / "state.json"
        before = (state_path.read_bytes(), state_path.stat().st_mtime_ns)
        inspected = self.command("inspect", "--run-id", run_id)
        self.assertEqual(inspected.returncode, 0, inspected.stderr)
        self.assertEqual(before, (state_path.read_bytes(), state_path.stat().st_mtime_ns))

        legacy = self.home / "orchestrator" / "legacy"
        legacy.mkdir(mode=0o700)
        (legacy / "state.json").write_text('{"format_version":4}', encoding="utf-8")
        rejected = self.command("inspect", "--run-id", "legacy")
        self.assertEqual(rejected.returncode, 1)
        self.assertIn("unsupported_run_format", json.loads(rejected.stdout)["error"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
