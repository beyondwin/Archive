"""Public JSON CLI contract for the format-5 CPE runtime."""

from __future__ import annotations

import io
import json
import sys
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
