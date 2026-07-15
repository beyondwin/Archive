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
sys.path.insert(0, str(ROOT / "scripts"))

from cpe_runtime.state import StateStore


class SequentialCliTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture_temporary = tempfile.TemporaryDirectory(prefix="cpe-cli-base-")
        cls.fixture_repo = Path(cls.fixture_temporary.name) / "repo"
        cls.fixture_repo.mkdir()
        subprocess.run(["git", "init", "-q", str(cls.fixture_repo)], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(cls.fixture_repo),
                "config",
                "user.email",
                "cpe@example.invalid",
            ],
            check=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(cls.fixture_repo),
                "config",
                "user.name",
                "CPE Eval",
            ],
            check=True,
        )
        for name in ("spec-b.md", "spec-a.md"):
            (cls.fixture_repo / name).write_text(
                f"# {Path(name).stem}\n",
                encoding="utf-8",
            )
        subprocess.run(
            ["git", "-C", str(cls.fixture_repo), "add", "."],
            check=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(cls.fixture_repo),
                "commit",
                "-q",
                "-m",
                "fixture",
            ],
            check=True,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.fixture_temporary.cleanup()

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="cpe-cli-")
        self.root = Path(self.temporary.name)
        self.home = self.root / "codex-home"
        self.repo = self.root / "repo"
        self.bin = self.root / "bin"
        self.real_codex = shutil.which("codex", path=os.environ["PATH"])
        self.home.mkdir(mode=0o700)
        self.bin.mkdir()
        shutil.copytree(self.fixture_repo, self.repo)
        self.specs = [self.repo / "spec-b.md", self.repo / "spec-a.md"]
        self.plans = [self.repo / "plan-b.md", self.repo / "plan-a.md"]
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

    def test_help_exposes_only_run_resume_and_inspect(self) -> None:
        source = CLI.read_text(encoding="utf-8")
        self.assertNotIn("export", source)
        result = self.command("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("{run,resume,inspect}", result.stdout)
        self.assertNotIn("export", result.stdout)

    def test_run_requires_absolute_workspace_and_at_least_one_plan(self) -> None:
        missing = self.command("run", "--workspace", str(self.repo))
        self.assertEqual(missing.returncode, 1)
        self.assertEqual(json.loads(missing.stdout)["status"], "failed")
        relative = self.command("run", "--workspace", "repo", "--plan", str(self.plans[0]))
        self.assertEqual(relative.returncode, 1)
        self.assertEqual(json.loads(relative.stdout)["status"], "failed")

    def test_repeated_spec_and_plan_flags_preserve_order(self) -> None:
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
        run_id = "inspect-only"
        source_commit = subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        ).stdout.strip()
        StateStore.create(
            run_root=self.home / "orchestrator" / run_id,
            run_id=run_id,
            source_repository=self.repo,
            source_commit=source_commit,
            worktree=self.home / "worktrees" / run_id,
            branch=f"codex/{run_id}",
            specs=[],
            plans=[self.plans[0]],
        )
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

    def test_installed_codex_exposes_every_launcher_flag(self) -> None:
        self.assertIsNotNone(self.real_codex, "codex is not installed on PATH")
        result = subprocess.run(
            [str(self.real_codex), "exec", "--help"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        help_text = result.stdout + result.stderr
        for flag in (
            "--ephemeral",
            "--ignore-user-config",
            "--json",
            "--output-schema",
            "--output-last-message",
        ):
            self.assertIn(flag, help_text)

    def test_skill_docs_match_hardened_public_contract(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn('version: "1.3.0"', skill)
        for phrase in (
            "process group",
            "bounded",
            "run_busy",
            "initializing",
            "workflow receipt",
            "recovery capsule",
            "focused",
            "final HEAD",
            "usage",
            "Change Protocol",
            "atomic recovery fields",
            "two-pipe drain",
            "linked",
        ):
            self.assertIn(phrase, skill + readme)
        root_index = (ROOT.parent / "README.md").read_text(encoding="utf-8")
        self.assertNotIn("내보내기", root_index)


if __name__ == "__main__":
    unittest.main(verbosity=2)
