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
CLI = SKILL_ROOT / "scripts" / "cpe.py"
PUBLIC_FIELDS = {
    "status",
    "run_id",
    "state_path",
    "summary",
    "next_action",
    "failure_code",
    "authority_items",
    "terminal_artifact",
}
from fake_codex import LeanEvalCase  # noqa: E402


class LeanCliTest(LeanEvalCase):
    fixture_prefix = "cpe-lean-cli-"

    def setUp(self) -> None:
        super().setUp()
        self.env = {**os.environ, "CODEX_HOME": str(self.home)}

    def cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CLI), *arguments],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self.env,
            check=False,
        )

    @staticmethod
    def inventory(root: Path) -> tuple[tuple[str, int, int], ...]:
        if not root.exists():
            return ()
        return tuple(
            (str(path.relative_to(root)), path.stat().st_mode, path.stat().st_size)
            for path in sorted(root.rglob("*"))
        )

    def test_help_lists_only_four_public_commands(self) -> None:
        result = self.cli("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        usage = result.stdout.split("\n", 2)[0]
        self.assertIn("{run,resume,inspect,export}", usage)
        for removed in ("supervise", "maintenance", "repair", "release"):
            self.assertNotIn(removed, result.stdout)

    def test_argument_shape_rejects_missing_plan_and_invalid_resume_combinations(self) -> None:
        missing_plan = self.cli("run", "--workspace", str(self.repo))
        self.assertEqual(missing_plan.returncode, 2)
        missing_answer = self.cli(
            "resume", "--run-id", "missing", "--authority-id", "A0001"
        )
        self.assertEqual(missing_answer.returncode, 2)
        combined = self.cli(
            "resume",
            "--run-id",
            "missing",
            "--authority-id",
            "A0001",
            "--authority-answer",
            "yes",
            "--refresh-inputs",
        )
        self.assertEqual(combined.returncode, 2)
        removed = self.cli(
            "run",
            "--plan",
            str(self.repo / "plan-a.md"),
            "--workspace",
            str(self.repo),
            "--mode",
            "interactive",
        )
        self.assertEqual(removed.returncode, 2)
        for command in ("run", "export"):
            duplicate_program = self.cli(
                command,
                "--plan",
                str(self.repo / "plan-a.md"),
                "--program-plan",
                str(self.repo / "program.md"),
                "--program-plan",
                str(self.repo / "spec-a.md"),
                "--workspace",
                str(self.repo),
            )
            self.assertEqual(duplicate_program.returncode, 2)
        duplicate_cases = [
            ("run", "--workspace", str(self.repo)),
            ("resume", "--run-id", "missing"),
            ("resume", "--authority-id", "A0001"),
            ("resume", "--authority-answer", "yes"),
            ("resume", "--refresh-inputs", None),
            ("inspect", "--run-id", "missing"),
            ("export", "--workspace", str(self.repo)),
            ("export", "--mode", "prompt"),
        ]
        for command, flag, value in duplicate_cases:
            base = [command]
            if command in {"run", "export"}:
                base.extend(("--plan", str(self.repo / "plan-a.md")))
                if flag != "--workspace":
                    base.extend(("--workspace", str(self.repo)))
            elif command == "resume" and flag != "--run-id":
                base.extend(("--run-id", "missing"))
            repeated = [flag, *( [] if value is None else [value] )] * 2
            self.assertEqual(self.cli(*base, *repeated).returncode, 2)

    def test_export_preserves_order_hashes_and_creates_no_state(self) -> None:
        home_before = self.inventory(self.home)
        repo_before = self.inventory(self.repo)
        ordered = [
            self.repo / "spec-b.md",
            self.repo / "spec-a.md",
            self.repo / "plan-b.md",
            self.repo / "plan-a.md",
            self.repo / "program.md",
        ]
        result = self.cli(
            "export",
            "--spec",
            str(ordered[0]),
            "--spec",
            str(ordered[1]),
            "--plan",
            str(ordered[2]),
            "--plan",
            str(ordered[3]),
            "--program-plan",
            str(ordered[4]),
            "--workspace",
            str(self.repo),
            "--mode",
            "handoff",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        positions = [result.stdout.index(str(path.resolve())) for path in ordered]
        self.assertEqual(positions, sorted(positions))
        for path in ordered:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertIn(digest, result.stdout)
        self.assertIn("No CPE run started", result.stdout)
        self.assertIn("scripts/cpe.py run", result.stdout)
        self.assertEqual(self.inventory(self.home), home_before)
        self.assertEqual(self.inventory(self.repo), repo_before)

    def test_public_failure_json_has_exact_fields_and_exit_one(self) -> None:
        result = self.cli("resume", "--run-id", "missing-run")
        self.assertEqual(result.returncode, 1, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(set(payload), PUBLIC_FIELDS)
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["failure_code"], "run_not_found")

    def test_eval_runner_timeout_kills_sigterm_ignoring_descendant(self) -> None:
        descendant_pid = self.root / "runner-descendant.pid"
        env = {
            **os.environ,
            "CPE_EVAL_RUNNER_SELF_TEST": "hang-descendant",
            "CPE_EVAL_SELF_TEST_PID": str(descendant_pid),
            "CPE_EVAL_CASE_TIMEOUT": "0.4",
            "CPE_EVAL_TERM_GRACE": "0.1",
            "CPE_EVAL_JOBS": "1",
        }
        started = time.monotonic()
        result = subprocess.run(
            ["bash", str(SKILL_ROOT / "evals" / "run.sh")],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            timeout=5,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertLess(time.monotonic() - started, 4)
        self.assertIn("TIMEOUT synthetic::hang-descendant", result.stderr)
        self.assertTrue(descendant_pid.is_file())
        pid = int(descendant_pid.read_text(encoding="utf-8"))
        for _ in range(80):
            status = subprocess.run(
                ["ps", "-p", str(pid), "-o", "stat="],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            if status.returncode != 0 or status.stdout.strip().startswith("Z"):
                break
            time.sleep(0.025)
        else:
            self.fail(f"runner descendant survived timeout: {pid}")

        for variable, invalid in (
            ("CPE_EVAL_JOBS", "9"),
            ("CPE_EVAL_CASE_TIMEOUT", "31"),
            ("CPE_EVAL_TERM_GRACE", "6"),
        ):
            rejected = subprocess.run(
                ["bash", str(SKILL_ROOT / "evals" / "run.sh")],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env={**env, variable: invalid},
                timeout=2,
                check=False,
            )
            self.assertNotEqual(rejected.returncode, 0)

    def test_active_skill_inventory_is_exact(self) -> None:
        expected = {
            "ARCHITECTURE.md",
            "HISTORY.md",
            "README.md",
            "SKILL.md",
            "docs/doc-update-protocol.md",
            "docs/evals-and-verification.md",
            "docs/risks-limitations-deferrals.md",
            "docs/user-guide.ko.md",
            "evals/check_lean_cli.py",
            "evals/check_lean_contracts.py",
            "evals/check_lean_final.py",
            "evals/check_lean_mapping.py",
            "evals/check_lean_queue.py",
            "evals/check_lean_recovery.py",
            "evals/fake_codex.py",
            "evals/lean-fixtures/plan-a.md",
            "evals/lean-fixtures/plan-b.md",
            "evals/lean-fixtures/program.md",
            "evals/lean-fixtures/spec-a.md",
            "evals/lean-fixtures/spec-b.md",
            "evals/run.sh",
            "references/change-protocol.md",
            "references/common-mistakes.md",
            "references/execution-cycle.md",
            "references/prompt-export-checklist.md",
            "references/state-schema.md",
            "scripts/cpe.py",
            "scripts/cpe_runtime/__init__.py",
            "scripts/cpe_runtime/contracts.py",
            "scripts/cpe_runtime/launcher.py",
            "scripts/cpe_runtime/legacy.py",
            "scripts/cpe_runtime/prompt_export.py",
            "scripts/cpe_runtime/queue.py",
            "scripts/cpe_runtime/store.py",
            "scripts/cpe_runtime/worktree.py",
            "templates/child-result-schema.json",
        }
        actual = {
            path.relative_to(SKILL_ROOT).as_posix()
            for path in SKILL_ROOT.rglob("*")
            if path.is_file() and "__pycache__" not in path.parts
        }
        self.assertEqual(actual, expected)
        self.assertFalse(
            any(
                path
                for name in ("agents", "data")
                for path in (SKILL_ROOT / name).glob("*")
            )
        )


if __name__ == "__main__":
    unittest.main()
