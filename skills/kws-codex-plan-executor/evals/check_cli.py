#!/usr/bin/env python3
"""Public CLI contract evals for the sequential runner."""

from __future__ import annotations

import json
import hashlib
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
from cpe_runtime.verification import materialize_helper_descriptor


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

    def only_run_state(self) -> dict[str, object]:
        runs = list((self.home / "orchestrator").iterdir())
        self.assertEqual(1, len(runs))
        return json.loads((runs[0] / "state.json").read_text(encoding="utf-8"))

    def use_home(self, name: str) -> None:
        self.home = self.root / name
        self.home.mkdir(mode=0o700)
        self.environment["CODEX_HOME"] = str(self.home)

    def test_help_exposes_public_commands_and_internal_verify(self) -> None:
        source = CLI.read_text(encoding="utf-8")
        self.assertNotIn("export", source)
        result = self.command("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("{run,resume,inspect,verify}", result.stdout)
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

    def test_run_runtime_configuration_defaults_bounds_and_persistence(self) -> None:
        def run_and_state(home: str, *options: str) -> dict[str, object]:
            self.use_home(home)
            result = self.command(
                "run", "--workspace", str(self.repo), "--plan", str(self.plans[0]),
                *options,
            )
            self.assertEqual(0, result.returncode, result.stderr + result.stdout)
            return self.only_run_state()

        default = run_and_state("default")
        self.assertEqual("danger-full-access", default["run_config"]["sandbox_mode"])
        self.assertEqual(1200, default["run_config"]["controller_slice_seconds"])

        explicit = run_and_state(
            "explicit", "--sandbox", "workspace-write", "--controller-slice-seconds", "1800",
        )
        self.assertEqual("workspace-write", explicit["run_config"]["sandbox_mode"])
        self.assertEqual(1800, explicit["run_config"]["controller_slice_seconds"])

        for value in (1200, 3600):
            state = run_and_state("slice-" + str(value), "--controller-slice-seconds", str(value))
            self.assertEqual(value, state["run_config"]["controller_slice_seconds"])

        for value in (1199, 3601):
            self.use_home("invalid-" + str(value))
            result = self.command(
                "run", "--workspace", str(self.repo), "--plan", str(self.plans[0]),
                "--controller-slice-seconds", str(value),
            )
            self.assertEqual(1, result.returncode, result.stderr + result.stdout)
            self.assertEqual("failed", json.loads(result.stdout)["status"])
            self.assertIn("controller slice", json.loads(result.stdout)["error"])

        resume_help = self.command("resume", "--help")
        self.assertEqual(0, resume_help.returncode, resume_help.stderr)
        self.assertNotIn("--sandbox", resume_help.stdout)
        self.assertNotIn("--controller-slice-seconds", resume_help.stdout)

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

    def test_resume_retry_flags_are_mutually_exclusive_and_state_specific(self) -> None:
        self.plans[0].write_text("scenario:blocked\n", encoding="utf-8")
        blocked = self.command(
            "run", "--plan", str(self.plans[0]), "--workspace", str(self.repo),
        )
        blocked_id = str(json.loads(blocked.stdout)["run_id"])
        mutually_exclusive = self.command(
            "resume", "--run-id", blocked_id, "--retry-blocked", "--retry-failed",
        )
        self.assertEqual(1, mutually_exclusive.returncode)
        wrong_blocked_flag = self.command(
            "resume", "--run-id", blocked_id, "--retry-failed",
        )
        self.assertEqual(1, wrong_blocked_flag.returncode)
        self.assertIn("retry-failed requires a failed run", json.loads(wrong_blocked_flag.stdout)["error"])

        self.use_home("failed-retry-state")
        self.plans[0].write_text("scenario:failed\n", encoding="utf-8")
        failed = self.command(
            "run", "--plan", str(self.plans[0]), "--workspace", str(self.repo),
        )
        failed_id = str(json.loads(failed.stdout)["run_id"])
        wrong_failed_flag = self.command(
            "resume", "--run-id", failed_id, "--retry-blocked",
        )
        self.assertEqual(1, wrong_failed_flag.returncode)
        self.assertIn("retry-blocked requires a blocked run", json.loads(wrong_failed_flag.stdout)["error"])

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
        ownership = (
            "CPE maintains one execution environment and verifies submitted facts.\n"
            "Superpowers decides what work and verification are correct."
        )
        for name, document in (("SKILL.md", skill), ("README.md", readme)):
            with self.subTest(document=name):
                self.assertIn(ownership, document)
                normalized = " ".join(document.split()).lower()
                for phrase in (
                    "Version 2.1.0",
                    "format 3",
                    "direct Superpowers launch",
                    "one reused isolated worktree",
                    "1200 seconds",
                    "1200 through 3600 seconds",
                    "danger-full-access",
                    "writes outside the worktree are not fully observable or reversible",
                    "zero controller launches",
                    "caller-selected verification",
                    "same HEAD",
                    "fail closed",
                    "integration=not_observed",
                ):
                    self.assertIn(phrase.lower(), normalized)
                self.assertIn(
                    "cpe never selects or runs a full suite by itself.", normalized,
                )
                self.assertIn(
                    "executes the exact submitted argv", normalized,
                )
                for stale in (
                    "compiled index",
                    "compiled-index",
                    "compiler call",
                    "first_no_progress_slice",
                    "second_no_progress_slice",
                    "confirmation slice",
                    "allowlist",
                    "format-version-2",
                    "format-version-2",
                    "Version 2.0.1",
                ):
                    self.assertNotIn(stale, document)

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

    def test_thin_audit_docs_and_release_inventory_match_runtime(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        normalized_skill = " ".join(skill.split())
        normalized_readme = " ".join(readme.split())
        ownership = (
            "CPE maintains one execution environment and verifies submitted facts. "
            "Superpowers decides what work and verification are correct."
        )

        for name, normalized in (
            ("SKILL.md", normalized_skill),
            ("README.md", normalized_readme),
        ):
            with self.subTest(document=name):
                self.assertIn(ownership, normalized)
                normalized_lower = normalized.lower()
                for phrase in (
                    "same-HEAD cross-phase reuse",
                    "exact submitted argv",
                    "dirty worktree",
                    "changed input digest",
                    "final_review_path",
                    "final_review_head",
                    "open_finding_ids",
                    "open_obligation_ids",
                    "integration=not_observed",
                    "provider_usage_blocked",
                    "provider_auth_blocked",
                    "provider_unavailable",
                    "controller_transport_failed",
                ):
                    self.assertIn(phrase.lower(), normalized_lower)

        inventory = readme[readme.index("## Tracked Inventory"):]
        inventory_block = inventory.split("```text\n", 1)[1].split("\n```", 1)[0]
        documented = {
            line.strip() for line in inventory_block.splitlines() if line.strip()
        }
        actual = {"README.md", "SKILL.md"}
        for pattern in (
            "evals/*.py",
            "evals/*.sh",
            "evals/fixtures/*.json",
            "scripts/*.py",
            "scripts/cpe_runtime/*.py",
            "templates/*.json",
        ):
            actual.update(
                path.relative_to(ROOT).as_posix() for path in ROOT.glob(pattern)
                if path.is_file()
            )
        self.assertEqual(actual, documented)

    def test_readme_documents_only_the_submitted_thin_completion_gates(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        start = readme.index("## Completion And Handoff")
        end = readme.index("## Verify", start)
        completion = " ".join(readme[start:end].split())

        for phrase in (
            "`ledger_path`",
            "`final_review_path`",
            "`final_review_head`",
            "empty `open_finding_ids` and `open_obligation_ids`",
            "successful verification outcomes",
            "valid ancestry",
        ):
            self.assertIn(phrase, completion)
        self.assertNotIn("strict ledger projection", completion)
        self.assertNotIn("branch-final evidence", completion)


class VerificationCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="cpe-verify-cli-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.home = self.root / "codex-home"
        self.repo = self.root / "repo"
        self.home.mkdir(mode=0o700)
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(
            ["git", "-C", str(self.repo), "config", "user.email", "cpe@example.invalid"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(self.repo), "config", "user.name", "CPE Eval"],
            check=True,
        )
        (self.repo / "seed.txt").write_text("seed\n", encoding="utf-8")
        (self.repo / ".gitignore").write_text(".superpowers/\n", encoding="utf-8")
        subprocess.run(
            ["git", "-C", str(self.repo), "add", "seed.txt", ".gitignore"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(self.repo), "commit", "-q", "-m", "seed"],
            check=True,
        )
        self.run_id = "verify-active"
        subprocess.run(
            ["git", "-C", str(self.repo), "checkout", "-q", "-b", f"codex/{self.run_id}"],
            check=True,
        )
        self.counter = self.root / "counter.txt"
        script = (
            "from pathlib import Path; "
            f"p=Path({str(self.counter)!r}); "
            "p.write_text(p.read_text() + 'x' if p.exists() else 'x')"
        )
        self.argv = (sys.executable, "-c", script)
        plan = self.repo / "plan.md"
        plan.write_text("Run the declared verification command.\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repo), "add", "plan.md"], check=True)
        subprocess.run(
            ["git", "-C", str(self.repo), "commit", "-q", "-m", "plan"],
            check=True,
        )
        source_commit = subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        ).stdout.strip()
        self.store = StateStore.create(
            run_root=self.home / "orchestrator" / self.run_id,
            run_id=self.run_id,
            source_repository=self.repo,
            source_commit=source_commit,
            worktree=self.repo,
            branch=f"codex/{self.run_id}",
            specs=[],
            plans=[plan],
        )
        self.store.state["status"] = "ready"
        self.store.save()
        materialize_helper_descriptor(self.store.root, CLI)
        self.environment = dict(os.environ, CODEX_HOME=str(self.home))

    def command(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CLI), *arguments],
            env=self.environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def verify_arguments(
        self,
        *,
        command_id: str = "unit",
        phase: str = "task",
        cwd: Path | None = None,
        argv: tuple[str, ...] | None = None,
    ) -> list[str]:
        return [
            "verify",
            "--run-id", self.run_id,
            "--command-id", command_id,
            "--phase", phase,
            "--input-digest", "immutable",
            "--mutable-input-policy", "immutable",
            "--cwd", str(cwd or self.repo),
            "--",
            *(argv or self.argv),
        ]

    def test_verify_requires_separator_nonempty_argv_and_known_enums(self) -> None:
        no_separator = self.command(*self.verify_arguments()[:-len(self.argv) - 1], *self.argv)
        empty = self.command(*self.verify_arguments()[:-len(self.argv)])
        bad_phase = self.verify_arguments()
        bad_phase[bad_phase.index("task")] = "merged_main"
        bad_policy = self.verify_arguments()
        policy_index = bad_policy.index("immutable", bad_policy.index("--mutable-input-policy"))
        bad_policy[policy_index] = "unknown"
        for result in (
            no_separator,
            empty,
            self.command(*bad_phase),
            self.command(*bad_policy),
        ):
            self.assertEqual(1, result.returncode, result.stdout + result.stderr)
            self.assertEqual("failed", json.loads(result.stdout)["status"])
        self.assertFalse(self.counter.exists())

    def test_verify_requires_the_parsed_separator_not_a_later_argv_token(self) -> None:
        arguments = self.verify_arguments()
        arguments[arguments.index("--")] = "not-a-separator"
        arguments.append("--")

        result = self.command(*arguments)

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertEqual("failed", json.loads(result.stdout)["status"])
        self.assertIn("requires --", json.loads(result.stdout)["error"])
        self.assertFalse(self.counter.exists())

    def test_verify_rejects_unknown_run_outside_cwd_and_parent_derived_flags(self) -> None:
        unknown = self.verify_arguments()
        unknown[unknown.index(self.run_id)] = "missing-run"
        outside = self.root / "outside"
        outside.mkdir()
        supplied_head = self.verify_arguments()
        supplied_head[supplied_head.index("--"):supplied_head.index("--")] = [
            "--head", "a" * 40,
        ]
        for arguments in (unknown, self.verify_arguments(cwd=outside), supplied_head):
            result = self.command(*arguments)
            self.assertEqual(1, result.returncode, result.stdout + result.stderr)
            self.assertEqual("failed", json.loads(result.stdout)["status"])
        self.assertFalse(self.counter.exists())

    def test_verify_accepts_superpowers_selected_command(self) -> None:
        result = self.command(*self.verify_arguments(command_id="undeclared"))
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual("passed", payload["status"])
        self.assertEqual("undeclared", payload["command_id"])
        self.assertEqual("task", payload["requested_phase"])
        self.assertEqual("task", payload["executed_phase"])
        self.assertFalse(payload["reused"])
        self.assertEqual("x", self.counter.read_text(encoding="utf-8"))

    def test_exact_second_invocation_reuses_first_receipt(self) -> None:
        first = self.command(*self.verify_arguments())
        second = self.command(*self.verify_arguments())
        self.assertEqual(0, first.returncode, first.stdout + first.stderr)
        self.assertEqual(0, second.returncode, second.stdout + second.stderr)
        first_payload, second_payload = json.loads(first.stdout), json.loads(second.stdout)
        self.assertFalse(first_payload["reused"])
        self.assertTrue(second_payload["reused"])
        self.assertEqual(first_payload["receipt_path"], second_payload["receipt_path"])
        self.assertEqual("x", self.counter.read_text(encoding="utf-8"))
        ledger = [
            json.loads(line)
            for line in (
                self.repo / ".superpowers" / "sdd" / "execution-ledger.jsonl"
            ).read_text(encoding="utf-8").splitlines()
        ]
        for event in ledger:
            self.assertEqual(3, len(event["evidence_refs"]))
            self.assertTrue(event["evidence_refs"][0].startswith("verification/receipts/"))
            self.assertTrue(event["evidence_refs"][1].startswith("verification/logs/"))
            self.assertTrue(event["evidence_refs"][2].startswith("verification/logs/"))

    def test_cross_phase_and_command_id_only_requests_reuse_original_execution(self) -> None:
        first = self.command(
            *self.verify_arguments(command_id="task-unit", phase="task")
        )
        second = self.command(
            *self.verify_arguments(command_id="final-unit", phase="branch_final")
        )

        self.assertEqual(0, first.returncode, first.stdout + first.stderr)
        self.assertEqual(0, second.returncode, second.stdout + second.stderr)
        first_payload = json.loads(first.stdout)
        second_payload = json.loads(second.stdout)
        self.assertFalse(first_payload["reused"])
        self.assertTrue(second_payload["reused"])
        self.assertEqual("branch_final", second_payload["requested_phase"])
        self.assertEqual("task", second_payload["executed_phase"])
        self.assertEqual(1, second_payload["avoided_executions"])
        self.assertEqual(first_payload["receipt_id"], second_payload["receipt_id"])
        self.assertEqual("x", self.counter.read_text(encoding="utf-8"))
        ledger = [
            json.loads(line)
            for line in (
                self.repo / ".superpowers" / "sdd" / "execution-ledger.jsonl"
            ).read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(1, sum(event["event_id"].startswith("verification.executed:") for event in ledger))
        self.assertEqual(1, sum(event["event_id"].startswith("verification.reused:") for event in ledger))
        self.assertEqual("task", ledger[-1]["executed_phase"])
        self.assertEqual("branch_final", ledger[-1]["requested_phase"])

    def test_changed_environment_executable_and_head_force_execution(self) -> None:
        first = self.command(*self.verify_arguments())
        self.assertEqual(0, first.returncode, first.stdout + first.stderr)

        self.environment["CPE_VERIFICATION_TEST_VALUE"] = "changed"
        changed_environment = self.command(*self.verify_arguments())
        self.assertFalse(json.loads(changed_environment.stdout)["reused"])

        executable = self.root / "verify-tool"
        executable.write_text(
            f"#!{sys.executable}\nfrom pathlib import Path\np=Path({str(self.counter)!r})\np.write_text(p.read_text() + 'e')\n",
            encoding="utf-8",
        )
        executable.chmod(0o755)
        executable_argv = (str(executable),)
        tool_first = self.command(*self.verify_arguments(argv=executable_argv))
        self.assertEqual(0, tool_first.returncode, tool_first.stdout + tool_first.stderr)
        executable.write_text(
            f"#!{sys.executable}\nfrom pathlib import Path\np=Path({str(self.counter)!r})\np.write_text(p.read_text() + 'r')\n",
            encoding="utf-8",
        )
        executable.chmod(0o755)
        replaced = self.command(*self.verify_arguments(argv=executable_argv))
        self.assertEqual(0, replaced.returncode, replaced.stdout + replaced.stderr)
        self.assertFalse(json.loads(replaced.stdout)["reused"])

        (self.repo / "head.txt").write_text("new head\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repo), "add", "head.txt"], check=True)
        subprocess.run(
            ["git", "-C", str(self.repo), "commit", "-q", "-m", "new head"],
            check=True,
        )
        changed_head = self.command(*self.verify_arguments())
        self.assertEqual(0, changed_head.returncode, changed_head.stdout + changed_head.stderr)
        self.assertFalse(json.loads(changed_head.stdout)["reused"])

    def test_corrupt_cache_fallback_is_uncached_and_never_reused(self) -> None:
        first = self.command(*self.verify_arguments())
        self.assertEqual(0, first.returncode, first.stdout + first.stderr)
        index = next(
            (self.repo / ".superpowers" / "sdd" / "verification" / "indexes").glob("*.json")
        )
        index.chmod(0o600)
        index.write_text("{}", encoding="utf-8")
        index.chmod(0o400)

        fallback = self.command(*self.verify_arguments())

        self.assertEqual(0, fallback.returncode, fallback.stdout + fallback.stderr)
        payload = json.loads(fallback.stdout)
        self.assertFalse(payload["reused"])
        self.assertEqual("verification_helper_fallback", payload["reason"])
        self.assertEqual("verification_helper_fallback", payload["reason_code"])
        self.assertIsNone(payload["receipt_path"])
        self.assertEqual("xx", self.counter.read_text(encoding="utf-8"))
        self.assertEqual(
            [],
            list(
                (self.repo / ".superpowers" / "sdd" / "verification" / "indexes")
                .glob("*.json")
            ),
        )
        ledger = [
            json.loads(line)
            for line in (
                self.repo / ".superpowers" / "sdd" / "execution-ledger.jsonl"
            ).read_text(encoding="utf-8").splitlines()
        ]
        fallback_event = ledger[-1]
        self.assertEqual("executed_uncached", fallback_event["action"])
        self.assertEqual("verification_helper_fallback", fallback_event["reason_code"])
        self.assertEqual([], fallback_event["evidence_refs"])
        self.assertIsNone(fallback_event["receipt_path"])
        self.assertEqual(0, fallback_event["exit_code"])

        after_fallback = self.command(*self.verify_arguments())

        self.assertEqual(0, after_fallback.returncode, after_fallback.stdout + after_fallback.stderr)
        self.assertFalse(json.loads(after_fallback.stdout)["reused"])
        self.assertEqual("xxx", self.counter.read_text(encoding="utf-8"))

    def test_corrupt_helper_with_exact_request_executes_once_uncached_without_receipt(self) -> None:
        descriptor = self.store.root / "tools" / "run-and-record.json"
        descriptor.chmod(0o600)
        descriptor.write_text("{}", encoding="utf-8")
        descriptor.chmod(0o400)

        result = self.command(*self.verify_arguments())

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["reused"])
        self.assertEqual("verification_helper_fallback", payload["reason"])
        self.assertIsNone(payload["receipt_path"])
        self.assertEqual("x", self.counter.read_text(encoding="utf-8"))
        verification_root = self.repo / ".superpowers" / "sdd" / "verification"
        self.assertEqual([], list((verification_root / "receipts").glob("*.json")))
        self.assertEqual([], list((verification_root / "indexes").glob("*.json")))
        ledger = [
            json.loads(line)
            for line in (
                self.repo / ".superpowers" / "sdd" / "execution-ledger.jsonl"
            ).read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(1, len(ledger))
        self.assertEqual("executed_uncached", ledger[0]["action"])
        self.assertEqual([], ledger[0]["evidence_refs"])
        self.assertIsNone(ledger[0]["receipt_path"])

    def test_dirty_source_tree_executes_every_time_instead_of_reusing_head(self) -> None:
        clean = self.command(*self.verify_arguments())
        self.assertEqual(0, clean.returncode, clean.stdout + clean.stderr)
        (self.repo / "seed.txt").write_text("dirty\n", encoding="utf-8")

        first_dirty = self.command(*self.verify_arguments())
        second_dirty = self.command(*self.verify_arguments())

        for result in (first_dirty, second_dirty):
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertFalse(payload["reused"])
            self.assertEqual("dirty_worktree_requires_execution", payload["reason"])
        self.assertEqual("xxx", self.counter.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
