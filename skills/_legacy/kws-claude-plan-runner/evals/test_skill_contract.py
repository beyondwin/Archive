from __future__ import annotations

import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]


class SkillContractTests(unittest.TestCase):
    def test_release_metadata_is_synchronized(self) -> None:
        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        package = (
            SKILL_ROOT / "scripts" / "plan_runner" / "__init__.py"
        ).read_text(encoding="utf-8")
        readme = (SKILL_ROOT / "README.md").read_text(encoding="utf-8")
        changelog = (SKILL_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        catalog = (SKILL_ROOT.parents[1] / "README.md").read_text(encoding="utf-8")

        self.assertIn('version: "2.0.0"', skill)
        self.assertIn('__version__ = "2.0.0"', package)
        self.assertIn("Current release: `2.0.0`", readme)
        self.assertIn("## 2.0.0 - 2026-07-25", changelog)
        self.assertIn("[`korean-writing-editor`](./korean-writing-editor/)", catalog)
        self.assertIn("[`image-workbench`](./image-workbench/)", catalog)
        self.assertNotIn("kws-claude-plan-runner", catalog)

    def test_skill_frontmatter_is_discoverable_and_versioned(self) -> None:
        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")

        self.assertTrue(skill.startswith("---\nname: kws-claude-plan-runner\n"))
        self.assertIn(
            "description: Use when approved Superpowers specifications and one or more "
            "ordered implementation plans must run autonomously through Claude Code "
            "with durable recovery and fail-closed ready-for-integration evidence.",
            skill,
        )
        self.assertIn('version: "2.0.0"', skill)
        self.assertIn('updated_at: "2026-07-25"', skill)

    def test_skill_closes_observed_recovery_and_status_gaps(self) -> None:
        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")

        for required in (
            "Do not merge, rewrite, or positionally pair",
            "current plan only",
            "durable state, Git HEAD, ledger, and receipts",
            "healthy same-plan session resume",
            "one fresh-root fallback",
            "A live controller continues the bounded recovery loop itself",
            "`recovering`",
            "`resumable`",
            "Plan status is `pending`, `running`, or `implemented`",
            "candidate HEAD",
            "`implemented`",
            "`ready_for_integration`",
            "Do not merge, push, or deploy",
            "`integration=not_observed`",
            "`integration_policy=keep`",
        ):
            with self.subTest(required=required):
                self.assertIn(required, skill)

    def test_skill_documents_claude_native_contract(self) -> None:
        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")

        for required in (
            "`stream-json`",
            "inline JSON schema",
            "new UUID",
            "`--resume`",
            "nested-session",
            "one variadic `--disallowedTools`",
            "not a security boundary",
            "normal-GIL CPython `>=3.13,<3.14`",
            "deadline",
            "receipt",
        ):
            with self.subTest(required=required):
                self.assertIn(required, skill)

    def test_readme_documents_public_commands_and_exit_codes(self) -> None:
        readme = (SKILL_ROOT / "README.md").read_text(encoding="utf-8")

        for required in (
            "./scripts/runner run",
            "./scripts/runner resume",
            "./scripts/runner inspect",
            "--retry-blocked",
            "--retry-failed --strategy-note",
            "`run`/`resume`: 0",
            "| 2 |",
            "| 3 |",
            "| 4 |",
            "| 64 |",
            "| 65 |",
            "| 70 |",
            "uv python install 3.13",
            "no positional pairing",
            "Version 1 state is inspect-only",
        ):
            with self.subTest(required=required):
                self.assertIn(required, readme)

    def test_exit_zero_is_command_specific(self) -> None:
        for document in ("SKILL.md", "README.md"):
            text = (SKILL_ROOT / document).read_text(encoding="utf-8")
            with self.subTest(document=document, contract="run"):
                self.assertIn(
                    "`run` and `resume` exit 0 only for `ready_for_integration`",
                    text,
                )
            with self.subTest(document=document, contract="inspect-success"):
                self.assertIn(
                    "`inspect` exits 0 for any valid, readable run state",
                    text,
                )
            with self.subTest(document=document, contract="inspect-errors"):
                self.assertIn(
                    "`inspect` exits 64 for an unknown run and 65 for invalid state",
                    text,
                )

    def test_subtree_guidance_preserves_runtime_and_provider_checks(self) -> None:
        guidance = (SKILL_ROOT / "AGENTS.md").read_text(encoding="utf-8")

        for required in (
            "CPython `>=3.13,<3.14`",
            "normal-GIL",
            "standard library only",
            "independent runtime",
            "focused evals",
            "full deterministic eval",
            "real `claude --help`",
            "stream event",
        ):
            with self.subTest(required=required):
                self.assertIn(required, guidance)
        for forbidden in ("`uv run`", "system Python fallback"):
            with self.subTest(forbidden=forbidden):
                self.assertIn(f"Do not use {forbidden}", guidance)

    def test_changelog_preserves_v1_history_and_publishes_v2(self) -> None:
        changelog = (SKILL_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

        self.assertIn("## 2.0.0 - 2026-07-25", changelog)
        self.assertIn("## 1.0.0 - 2026-07-23", changelog)
        self.assertIn("greenfield", changelog.lower())
        self.assertIn("Version 1 state is inspect-only", changelog)
        self.assertIn("durable session-aware recovery", changelog)

    def test_public_contract_documents_the_thin_superpowers_boundary(self) -> None:
        documents = {
            name: (SKILL_ROOT / name).read_text(encoding="utf-8")
            for name in ("SKILL.md", "README.md", "CHANGELOG.md")
        }
        combined = " ".join("\n".join(documents.values()).split())

        for required in (
            "immutable inputs handed unchanged to Superpowers",
            "Superpowers owns task decomposition, SDD dispatch, TDD, task review, "
            "fixes, and the final whole-branch review",
            "exact external facts",
            "one healthy root resume",
            "one fresh-root fallback",
            "final plan carries all immutable requirements",
            "single final whole-branch review",
            "`integration_policy=keep`",
            "Version 1 state is inspect-only",
            "drift detection",
            "cannot restore",
        ):
            with self.subTest(required=required):
                self.assertIn(required, combined)

        for forbidden in (
            "Task status is",
            "finalization",
            "final_review_receipt",
            "unsealed-provider-partial",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, combined)

    def test_public_contract_binds_the_final_run_verification_union(self) -> None:
        for document in ("SKILL.md", "README.md"):
            text = " ".join(
                (SKILL_ROOT / document).read_text(encoding="utf-8").split()
            )
            with self.subTest(document=document):
                self.assertIn(
                    "exact ordered duplicate-free union of all sealed plan "
                    "verification declarations at the final HEAD",
                    text,
                )
                self.assertIn(
                    "final handoff and accepted verification digest bind that "
                    "run-level union",
                    text,
                )

    def test_readme_documents_release_canaries(self) -> None:
        readme = " ".join(
            (SKILL_ROOT / "README.md")
            .read_text(encoding="utf-8")
            .replace("\\\n", "")
            .split()
        )

        self.assertIn("--provider all --mode ownership", readme)
        self.assertIn("--provider all --mode interruption", readme)


if __name__ == "__main__":
    unittest.main()
