"""Public JSON CLI contract for the format-5 CPE runtime."""

from __future__ import annotations

import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import cpe
from cpe import CliUsageError, EXIT_CODES, build_parser


class CliContractTests(unittest.TestCase):
    def run_arguments(self, *extra: str) -> list[str]:
        return [
            "run",
            "--document",
            "/tmp/design.md",
            "--workspace",
            "/tmp/repository",
            "--superpowers-skill",
            "subagent-driven-development",
            *extra,
        ]

    def invoke(self, arguments: list[str]) -> tuple[int, dict[str, object]]:
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = cpe.main(arguments)
        lines = output.getvalue().splitlines()
        self.assertEqual(len(lines), 1, output.getvalue())
        return exit_code, json.loads(lines[0])

    def test_run_accepts_repeated_documents_in_cli_order(self) -> None:
        parsed = build_parser().parse_args(
            [
                "run",
                "--document",
                "/tmp/design.md",
                "--document",
                "/tmp/implementation.md",
                "--document",
                "/tmp/incident.txt",
                "--document",
                "/tmp/execution-contract",
                "--workspace",
                "/tmp/repository",
                "--superpowers-skill",
                "subagent-driven-development",
            ]
        )
        self.assertEqual(
            parsed.document,
            [
                "/tmp/design.md",
                "/tmp/implementation.md",
                "/tmp/incident.txt",
                "/tmp/execution-contract",
            ],
        )
        self.assertEqual(parsed.sandbox, "workspace-write")

    def test_run_delegates_opaque_documents_to_runtime_in_cli_order(self) -> None:
        arguments = self.run_arguments(
            "--document",
            "/tmp/implementation.md",
            "--document",
            "/tmp/incident.txt",
            "--sandbox",
            "danger-full-access",
        )
        with patch.object(cpe, "CpeRuntime") as runtime_type:
            runtime_type.return_value.run.return_value = {
                "status": "handed_off",
                "run_id": "cpe-test",
            }
            exit_code, payload = self.invoke(arguments)

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "handed_off")
        call = runtime_type.return_value.run.call_args
        self.assertEqual(
            [str(source.path) for source in call.kwargs["documents"]],
            [
                "/tmp/design.md",
                "/tmp/implementation.md",
                "/tmp/incident.txt",
            ],
        )
        self.assertEqual(call.kwargs["workspace"], Path("/tmp/repository"))
        self.assertEqual(call.kwargs["sandbox"], "danger-full-access")

    def test_run_requires_at_least_one_document(self) -> None:
        with self.assertRaises(CliUsageError):
            build_parser().parse_args(
                [
                    "run",
                    "--workspace",
                    "/tmp/repository",
                    "--superpowers-skill",
                    "executing-plans",
                ]
            )

    def test_all_run_paths_must_be_absolute(self) -> None:
        invalid_arguments = (
            [
                "run",
                "--document",
                "relative.md",
                "--workspace",
                "/tmp/repository",
                "--superpowers-skill",
                "executing-plans",
            ],
            [
                "run",
                "--document",
                "/tmp/design.md",
                "--workspace",
                "repository",
                "--superpowers-skill",
                "executing-plans",
            ],
            self.run_arguments("--adopt-worktree", "relative", "--base", "HEAD"),
        )
        for arguments in invalid_arguments:
            with self.subTest(arguments=arguments):
                with self.assertRaises(CliUsageError):
                    build_parser().parse_args(arguments)

    def test_adopt_worktree_and_base_must_appear_together(self) -> None:
        for arguments in (
            self.run_arguments("--adopt-worktree", "/tmp/adopted"),
            self.run_arguments("--base", "HEAD"),
        ):
            with self.subTest(arguments=arguments):
                with self.assertRaises(CliUsageError):
                    build_parser().parse_args(arguments)

        parsed = build_parser().parse_args(
            self.run_arguments(
                "--adopt-worktree",
                "/tmp/adopted",
                "--base",
                "0123456789abcdef0123456789abcdef01234567",
            )
        )
        self.assertEqual(parsed.adopt_worktree, "/tmp/adopted")
        self.assertEqual(
            parsed.base,
            "0123456789abcdef0123456789abcdef01234567",
        )

    def test_resume_accepts_only_run_id(self) -> None:
        parsed = build_parser().parse_args(["resume", "--run-id", "cpe-test"])
        self.assertEqual(vars(parsed), {"command": "resume", "run_id": "cpe-test"})
        for extra in (
            ("--sandbox", "workspace-write"),
            ("--document", "/tmp/design.md"),
            ("--retry-blocked",),
            ("unexpected",),
        ):
            with self.subTest(extra=extra):
                with self.assertRaises(CliUsageError):
                    build_parser().parse_args(
                        ["resume", "--run-id", "cpe-test", *extra]
                    )

    def test_removed_commands_are_rejected(self) -> None:
        removed_invocations = (
            [
                "verify",
                "--run-id",
                "cpe-test",
                "--command-id",
                "unit",
                "--phase",
                "task",
                "--input-digest",
                "digest",
                "--mutable-input-policy",
                "immutable",
                "--cwd",
                "/tmp",
                "--",
                "true",
            ],
            [
                "recover-ledger",
                "--run-id",
                "cpe-test",
                "--sha256",
                "a" * 64,
                "--authority-profile",
                "local-implementation-with-evidence-approvals",
            ],
            ["migrate-run"],
        )
        for arguments in removed_invocations:
            with self.subTest(command=arguments[0]):
                with self.assertRaises(CliUsageError):
                    build_parser().parse_args(arguments)

    def test_exit_codes_match_truthful_terminal_states(self) -> None:
        self.assertEqual(
            EXIT_CODES,
            {
                "handed_off": 0,
                "failed": 1,
                "blocked": 2,
                "interrupted": 3,
            },
        )

    def test_inspect_success_always_exits_zero(self) -> None:
        results = (
            {"format_version": 5, "run_id": "cpe-test", "status": "failed"},
            {
                "status": "legacy_read_only",
                "format_version": 3,
                "run_root": "/tmp/legacy",
            },
        )
        for result in results:
            with self.subTest(result=result):
                with patch.object(cpe, "CpeRuntime") as runtime_type:
                    runtime_type.return_value.inspect.return_value = result
                    exit_code, payload = self.invoke(
                        ["inspect", "--run-id", "cpe-test"]
                    )
                self.assertEqual(exit_code, 0)
                self.assertEqual(payload, result)

    def test_json_errors_are_bounded_to_two_thousand_characters(self) -> None:
        with patch.object(cpe, "CpeRuntime") as runtime_type:
            runtime_type.return_value.resume.side_effect = ValueError("x" * 5000)
            exit_code, payload = self.invoke(
                ["resume", "--run-id", "cpe-test"]
            )

        self.assertEqual(exit_code, 1)
        self.assertEqual(payload["status"], "failed")
        self.assertGreater(len(str(payload["error"])), 0)
        self.assertLessEqual(len(str(payload["error"])), 2000)

    def test_ctrl_c_returns_interrupted_not_checkpointed(self) -> None:
        with patch.object(cpe, "CpeRuntime") as runtime_type:
            runtime_type.return_value.resume.side_effect = KeyboardInterrupt
            exit_code, payload = self.invoke(
                ["resume", "--run-id", "cpe-test"]
            )

        self.assertEqual(exit_code, 3)
        self.assertEqual(payload["status"], "interrupted")
        self.assertNotEqual(payload["status"], "checkpointed")

    def test_completed_runtime_status_is_never_exposed_as_cpe_status(self) -> None:
        with patch.object(cpe, "CpeRuntime") as runtime_type:
            runtime_type.return_value.run.return_value = {"status": "completed"}
            exit_code, payload = self.invoke(self.run_arguments())

        self.assertEqual(exit_code, 1)
        self.assertEqual(payload["status"], "failed")
        self.assertNotEqual(payload["status"], "completed")


class ArchitectureGuardTests(unittest.TestCase):
    CURRENT_PUBLIC_PHRASES = (
        "The active CPE commands are exactly `run`, `resume`, and `inspect`.",
        "`run` defaults to `workspace-write`.",
        "`danger-full-access` is an explicit immutable run-creation opt-in.",
        "Superpowers owns engineering completion; CPE only reports a mechanical "
        "`handed_off`, `failed`, `blocked`, or `interrupted` status.",
        "CPE has no public retry, recovery, or verification command.",
    )

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="cpe-architecture-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.runtime = self.root / "scripts" / "cpe_runtime"
        self.templates = self.root / "templates"
        self.evals = self.root / "evals"
        self.runtime.mkdir(parents=True)
        self.templates.mkdir()
        self.evals.mkdir()
        (self.root / "scripts" / "cpe.py").write_text(
            "import subprocess\n"
            "def invoke():\n"
            "    return subprocess.run(['true'], shell=False)\n",
            encoding="utf-8",
        )
        for name in (
            "__init__.py",
            "state.py",
            "git.py",
            "controller.py",
            "runtime.py",
        ):
            (self.runtime / name).write_text(
                '"""Expected fixture module."""\n',
                encoding="utf-8",
            )
        (self.templates / "terminal-envelope.schema.json").write_text(
            json.dumps(
                {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["value"],
                    "properties": {"value": {"type": "string"}},
                }
            )
            + "\n",
            encoding="utf-8",
        )
        self.write_public_docs()

    def write_public_docs(self, *, omit: str | None = None) -> None:
        statements = [
            phrase for phrase in self.CURRENT_PUBLIC_PHRASES if phrase != omit
        ]
        commands = (
            "```bash\n"
            "python3 scripts/cpe.py run --document /abs/doc "
            "--workspace /abs/repo --superpowers-skill executing-plans\n"
            "python3 scripts/cpe.py resume --run-id RUN_ID\n"
            "python3 scripts/cpe.py inspect --run-id RUN_ID\n"
            "python3 -m py_compile scripts/cpe.py scripts/cpe_runtime/*.py\n"
            "python3 -m py_compile "
            "skills/kws-codex-plan-executor/scripts/cpe.py\n"
            "```\n"
        )
        inventory = (
            "```text\n"
            "scripts/cpe.py\n"
            "scripts/cpe_runtime/runtime.py\n"
            "```\n"
        )
        text = (
            "# Fixture\n\n"
            + "\n\n".join(statements)
            + "\n\n"
            + commands
            + "\n"
            + inventory
        )
        text = text.replace(
            "reports a mechanical `handed_off`",
            "reports a mechanical\n`handed_off`",
        )
        for name in ("SKILL.md", "README.md"):
            (self.root / name).write_text(text, encoding="utf-8")

    def run_guard(self) -> subprocess.CompletedProcess[str]:
        shutil.copyfile(
            ROOT / "evals" / "check_architecture.py",
            self.evals / "check_architecture.py",
        )
        return subprocess.run(
            [sys.executable, str(self.evals / "check_architecture.py")],
            cwd=self.root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def assert_guard_fails(self, *markers: str) -> None:
        result = self.run_guard()
        self.assertEqual(
            result.returncode,
            1,
            f"guard unexpectedly passed\nstdout={result.stdout}\nstderr={result.stderr}",
        )
        for marker in markers:
            self.assertIn(marker, result.stdout)

    def test_expected_inventory_and_literal_shell_false_pass(self) -> None:
        for name in ("SKILL.md", "README.md"):
            with (self.root / name).open("a", encoding="utf-8") as document:
                document.write(
                    "\nHistorical releases had broader workflow commands, "
                    "but no callable example is retained here.\n"
                )

        result = self.run_guard()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_guard_rejects_structured_output_optional_properties(self) -> None:
        (self.templates / "terminal-envelope.schema.json").write_text(
            json.dumps(
                {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["claim", "blocker"],
                    "properties": {
                        "claim": {"type": "string"},
                        "resume_capsule": {"type": "object"},
                        "blocker": {
                            "type": ["object", "null"],
                            "additionalProperties": False,
                            "required": ["code"],
                            "properties": {
                                "code": {"type": "string"},
                                "provider_code": {"type": "string"},
                            },
                        },
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )

        self.assert_guard_fails(
            "structured output object must require every property",
            "structured output optional field must allow null: resume_capsule",
            "structured output optional field must allow null: provider_code",
        )

    def test_guard_rejects_broad_semantic_tokens_case_and_quote_robustly(self) -> None:
        cases = (
            "task_id = 'T1'",
            "taskId = 'T2'",
            "COMPLETED_TASK = True",
            "completedTask = True",
            "currentPlanIndex = 1",
            "fixRound = 1",
            "final_review = {}",
            "finalReview = {}",
            "Finding = 'important'",
            "openFindingIds = []",
            "OBLIGATION = 'open'",
            "openObligationIds = []",
            "mode = 'verification'",
            'mode = "Verification"',
        )
        path = self.runtime / "runtime.py"
        baseline = path.read_text(encoding="utf-8")
        for source in cases:
            with self.subTest(source=source):
                path.write_text(baseline + source + "\n", encoding="utf-8")
                self.assert_guard_fails("forbidden semantic token")
        path.write_text(baseline, encoding="utf-8")

    def test_guard_rejects_verification_and_migration_authority_aliases(self) -> None:
        cases = (
            "verification = []",
            "VERIFICATION = []",
            "verificationResult = []",
            "def migrate_run():\n    pass",
            "def migrateRun():\n    pass",
            "route = 'migrate-run'",
        )
        path = self.runtime / "runtime.py"
        baseline = path.read_text(encoding="utf-8")
        for source in cases:
            with self.subTest(source=source):
                path.write_text(baseline + source + "\n", encoding="utf-8")
                self.assert_guard_fails("forbidden semantic token")
        path.write_text(baseline, encoding="utf-8")

    def test_guard_recurses_and_applies_all_checks_to_nested_production(self) -> None:
        nested = self.runtime / "nested"
        nested.mkdir()
        (nested / "escape.py").write_text(
            "import third_party\n"
            "from cpe_runtime import runner\n"
            "TASK_ID = 'nested'\n"
            + "# padding\n" * 448,
            encoding="utf-8",
        )
        schema = self.templates / "nested" / "escape.json"
        schema.parent.mkdir()
        schema.write_text('{"Finding": "hidden"}\n', encoding="utf-8")

        self.assert_guard_fails(
            "runtime inventory mismatch",
            "template inventory mismatch",
            "forbidden semantic token",
            "non-stdlib import",
            "deleted-module import",
            "module line limit exceeded",
        )

    def test_guard_enforces_the_complete_recursive_script_inventory(self) -> None:
        extra = self.root / "scripts" / "escape.py"
        extra.write_text(
            "import third_party\n"
            "import subprocess\n"
            "TASK_ID = 'outside-runtime'\n"
            "subprocess.run(['true'], shell=1)\n",
            encoding="utf-8",
        )
        self.assert_guard_fails(
            "production Python inventory mismatch",
            "forbidden semantic token",
            "non-stdlib import",
            "shell keyword must be literal False",
        )

        extra.unlink()
        (self.root / "scripts" / "cpe.py").unlink()
        self.assert_guard_fails("production Python inventory mismatch")

    def test_guard_rejects_inline_and_console_old_cpe_commands(self) -> None:
        with (self.root / "SKILL.md").open("a", encoding="utf-8") as skill:
            skill.write(
                "\nDo not call `python3 scripts/cpe.py verify --run-id OLD`.\n"
            )
        with (self.root / "README.md").open("a", encoding="utf-8") as readme:
            readme.write(
                "\n```console\n"
                "$ python3 scripts/cpe.py recover-ledger --run-id OLD\n"
                "```\n"
            )

        self.assert_guard_fails(
            "active commands mismatch in SKILL.md",
            "active commands mismatch in README.md",
        )

    def test_guard_rejects_repo_prefixed_and_absolute_old_cpe_commands(self) -> None:
        with (self.root / "SKILL.md").open("a", encoding="utf-8") as skill:
            skill.write(
                "\nDo not call `python3 "
                "skills/kws-codex-plan-executor/scripts/cpe.py verify`.\n"
            )
        with (self.root / "README.md").open("a", encoding="utf-8") as readme:
            readme.write(
                "\n```console\n"
                "$ /tmp/repo/skills/kws-codex-plan-executor/"
                "scripts/cpe.py verify\n"
                "```\n"
            )

        self.assert_guard_fails(
            "active commands mismatch in SKILL.md",
            "active commands mismatch in README.md",
        )

    def test_guard_rejects_all_prefixed_old_cpe_command_forms(self) -> None:
        invocations = (
            "$ /tmp/repo/skills/kws-codex-plan-executor/"
            "scripts/cpe.py verify",
            'python3 "skills/kws-codex-plan-executor/'
            'scripts/cpe.py" verify',
            "/usr/bin/python3 skills/kws-codex-plan-executor/"
            "scripts/cpe.py verify",
            "python3 -I skills/kws-codex-plan-executor/"
            "scripts/cpe.py verify",
            "$ env X=1 /tmp/repo/skills/kws-codex-plan-executor/"
            "scripts/cpe.py verify",
        )
        for invocation in invocations:
            with self.subTest(invocation=invocation):
                self.write_public_docs()
                with (self.root / "README.md").open(
                    "a",
                    encoding="utf-8",
                ) as readme:
                    readme.write(f"\n```console\n{invocation}\n```\n")
                self.assert_guard_fails(
                    "active commands mismatch in README.md",
                )

    def test_guard_allows_prefixed_current_cpe_command_forms(self) -> None:
        invocations = (
            "$ /tmp/repo/skills/kws-codex-plan-executor/"
            "scripts/cpe.py run",
            'python3 "skills/kws-codex-plan-executor/'
            'scripts/cpe.py" resume',
            "/usr/bin/python3 skills/kws-codex-plan-executor/"
            "scripts/cpe.py inspect",
            "python3 -I skills/kws-codex-plan-executor/"
            "scripts/cpe.py run",
            "$ env X=1 /tmp/repo/skills/kws-codex-plan-executor/"
            "scripts/cpe.py resume",
        )
        block = "\n```console\n" + "\n".join(invocations) + "\n```\n"
        for name in ("SKILL.md", "README.md"):
            with (self.root / name).open("a", encoding="utf-8") as document:
                document.write(block)

        result = self.run_guard()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_guard_rejects_any_nonliteral_false_shell_keyword(self) -> None:
        (self.root / "scripts" / "cpe.py").write_text(
            "import subprocess\n"
            "def invoke(shell_mode):\n"
            "    subprocess.run(['true'], shell=1)\n"
            "    subprocess.run(['true'], shell=shell_mode)\n",
            encoding="utf-8",
        )

        result = self.run_guard()

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(
            result.stdout.count("shell keyword must be literal False"),
            2,
            result.stdout,
        )

    def test_guard_requires_current_public_cutover_statements(self) -> None:
        missing = self.CURRENT_PUBLIC_PHRASES[1]
        self.write_public_docs(omit=missing)

        self.assert_guard_fails("current contract missing in SKILL.md")

    def test_guard_rejects_stale_active_v2_contract_statements(self) -> None:
        stale = (
            "\nThe run defaults to `danger-full-access` with "
            "`--controller-slice-seconds 1200`. Use `--retry-blocked`, "
            "`--retry-failed`, and `recover-ledger`; CPE statuses are "
            "`completed` and `checkpointed`.\n"
        )
        for name in ("SKILL.md", "README.md"):
            with (self.root / name).open("a", encoding="utf-8") as document:
                document.write(stale)

        self.assert_guard_fails(
            "stale active contract in SKILL.md",
            "stale active contract in README.md",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
