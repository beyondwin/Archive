#!/usr/bin/env python3
"""Public CLI contract evals for the sequential runner."""

from __future__ import annotations

import json
import os
import re
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

    def test_output_schema_is_strict_structured_output_compatible(self) -> None:
        schema = json.loads(
            (ROOT / "templates" / "plan-result-schema.json").read_text(
                encoding="utf-8"
            )
        )
        properties = schema["properties"]
        self.assertEqual(set(schema["required"]), set(properties))
        self.assertEqual(
            properties["status"]["enum"],
            ["completed", "checkpointed", "blocked", "failed"],
        )
        for name in ("checkpoint", "blocker", "workflow_receipt"):
            self.assertEqual(properties[name]["anyOf"][-1], {"type": "null"})
        verification = properties["verification"]["items"]
        self.assertEqual(
            set(verification["required"]),
            {
                "command_id",
                "argv_digest",
                "phase",
                "evidence_key",
                "exit_code",
                "receipt_path",
            },
        )

    def test_run_requires_absolute_workspace_and_at_least_one_plan(self) -> None:
        missing = self.command("run", "--workspace", str(self.repo))
        self.assertEqual(missing.returncode, 1)
        self.assertEqual(json.loads(missing.stdout)["status"], "failed")
        relative = self.command("run", "--workspace", "repo", "--plan", str(self.plans[0]))
        self.assertEqual(relative.returncode, 1)
        self.assertEqual(json.loads(relative.stdout)["status"], "failed")

    def test_checkpointed_run_uses_resume_exit_code(self) -> None:
        self.plans[0].write_text("scenario:interrupted\n", encoding="utf-8")

        result = self.command(
            "run",
            "--plan",
            str(self.plans[0]),
            "--workspace",
            str(self.repo),
        )

        self.assertEqual(result.returncode, 3, result.stderr + result.stdout)
        self.assertEqual(json.loads(result.stdout)["status"], "checkpointed")

    def test_repeated_spec_and_plan_flags_preserve_order(self) -> None:
        self.plans[0].write_text("scenario:blocked\n", encoding="utf-8")
        result = self.command(
            "run", "--spec", str(self.specs[0]), "--spec", str(self.specs[1]),
            "--plan", str(self.plans[0]), "--plan", str(self.plans[1]),
            "--workspace", str(self.repo),
        )
        self.assertEqual(result.returncode, 2, result.stderr + result.stdout)
        public = json.loads(result.stdout)
        self.assertEqual(public["status"], "blocked")
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

        for scenario, expected_status in (
            ("blocked", "blocked"),
            ("failed", "failed"),
            ("interrupted", "checkpointed"),
        ):
            with self.subTest(inspect_status=expected_status):
                self.plans[0].write_text(f"scenario:{scenario}\n", encoding="utf-8")
                created = self.command(
                    "run", "--plan", str(self.plans[0]), "--workspace", str(self.repo),
                )
                created_payload = json.loads(created.stdout)
                self.assertEqual(created_payload["status"], expected_status)
                inspected_terminal = self.command(
                    "inspect", "--run-id", created_payload["run_id"],
                )
                self.assertEqual(inspected_terminal.returncode, 0, inspected_terminal.stderr)
                self.assertEqual(
                    json.loads(inspected_terminal.stdout)["status"], expected_status,
                )

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
            "--add-dir",
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

        frontmatter_parts = skill.split("---", 2)
        self.assertEqual(len(frontmatter_parts), 3)
        metadata_lines = [
            line.strip() for line in frontmatter_parts[1].splitlines()
            if line.startswith("  version:")
        ]
        self.assertEqual(metadata_lines, ['version: "2.0.0"'])
        self.assertIn("Version 2.0.0", readme)

        def section(document: str, heading: str) -> str:
            start = document.index(heading)
            following = document.find("\n## ", start + len(heading))
            return document[start:following if following >= 0 else None]

        documents = (
            ("SKILL.md", skill, section(skill, "## Recovery Contract")),
            (
                "README.md",
                readme,
                section(readme, "## Completion, Failure, And Recovery"),
            ),
        )
        stale_patterns = (
            r"\bversion 1\.[0-9]",
            r"version:\s*[\"']1\.",
            r"format(?:-| )version(?:-| )1 (?:remains|is) authoritative",
            r"(?:public )?format-version-1 contract",
            r"recovery capsule",
            r"\binitializing\b",
            r"preserves legacy|legacy support",
        )
        for name, document, recovery in documents:
            normalized = " ".join(document.split())
            normalized_recovery = " ".join(recovery.split())
            with self.subTest(document=name):
                self.assertRegex(normalized, r"format(?:-version)?-2")
                self.assertRegex(
                    normalized,
                    r"(?:does not (?:read|support).*format-1|format-1.*neither read nor migrated)",
                )
                for phrase in (
                    "parent-observed", "environment fingerprint", "changed fingerprint",
                    "bounded", "progress fingerprint", "productive", "no-progress",
                    "checkpointed", "durable", "ledger_path", "final_review_path",
                    "original", "~/.codex/orchestrator/<run-id>/", "Superpowers owns",
                    "CPE owns",
                ):
                    self.assertIn(phrase, normalized_recovery if phrase not in {
                        "~/.codex/orchestrator/<run-id>/", "Superpowers owns", "CPE owns",
                    } else normalized)
                self.assertRegex(
                    normalized_recovery,
                    r"(?:zero|no) compiler.*model.*verification",
                )
                if name == "README.md":
                    for row in (
                        "controller slice timeout | 3600 seconds",
                        "productive progress checkpoints | 6",
                        "plan wall time | 21600 seconds",
                        "controller launches | 8",
                    ):
                        self.assertIn(row, normalized_recovery)
                else:
                    self.assertRegex(normalized_recovery, r"3600-second controller slice")
                    self.assertRegex(normalized_recovery, r"6 productive progress checkpoints")
                    self.assertRegex(normalized_recovery, r"21600 seconds of wall time")
                    self.assertRegex(normalized_recovery, r"8 controller launches")
                self.assertRegex(normalized_recovery, r"checkpointed.*not (?:a |a synonym for )?failure")
                self.assertRegex(normalized_recovery, r"zero model (?:turns|calls)")
                self.assertRegex(normalized, r"(?:justif.*slice|slice.*justif)")
                for phrase in (
                    "across `run`, `inspect`, and plain `resume`, the durable status is `blocked`",
                    "repeated failure consumes zero plan attempts, controller launches, or recompilation",
                    "after the environment recovers, plain `resume`",
                    "after plan execution has begun remains a fail-closed integrity error",
                    "never persists `failed` and never requires `--retry-failed`",
                    "exit mappings apply only to `run` and `resume`",
                    "successful read-only `inspect` exits 0 even when the stored status is `blocked`, `failed`, or `checkpointed`",
                ):
                    self.assertIn(phrase, normalized_recovery.lower())
                for contradiction in (
                    r"worktree.{0,240}(?<!never )persists? (?:durable )?(?:internal )?`failed`",
                    r"worktree.{0,240}(?<!never )requires `--retry-failed`",
                ):
                    self.assertIsNone(
                        re.search(contradiction, normalized_recovery, re.IGNORECASE),
                    )
                for stale in stale_patterns:
                    self.assertIsNone(re.search(stale, normalized, re.IGNORECASE))

        root_index = (ROOT.parent / "README.md").read_text(encoding="utf-8")
        self.assertNotIn("내보내기", root_index)

    def test_readme_inventory_covers_every_tracked_runtime_module(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        inventory = readme[readme.index("## Tracked Inventory"):]
        modules = sorted((ROOT / "scripts" / "cpe_runtime").glob("*.py"))
        self.assertTrue(modules)
        for module in modules:
            relative = module.relative_to(ROOT).as_posix()
            with self.subTest(module=relative):
                self.assertIn(relative, inventory)


if __name__ == "__main__":
    unittest.main(verbosity=2)
