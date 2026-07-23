from __future__ import annotations

import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]


class SkillContractTests(unittest.TestCase):
    def test_skill_frontmatter_is_discoverable_and_versioned(self) -> None:
        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")

        self.assertTrue(skill.startswith("---\nname: kws-claude-plan-runner\n"))
        self.assertIn(
            "description: Use when approved Superpowers specifications and one or more "
            "ordered implementation plans must run autonomously through Claude Code "
            "with durable recovery and fail-closed ready-for-integration evidence.",
            skill,
        )
        self.assertIn('version: "1.0.0"', skill)
        self.assertIn('updated_at: "2026-07-23"', skill)

    def test_skill_closes_observed_recovery_and_status_gaps(self) -> None:
        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")

        for required in (
            "Do not merge, rewrite, or positionally pair",
            "current plan only",
            "durable state, Git HEAD, ledger, and receipts",
            "healthy same-plan session resume",
            "fresh-session fallback",
            "A live controller continues the bounded recovery loop itself",
            "`recovering`",
            "`resumable`",
            "Task status is `pending`, `running`, or `reported_done`",
            "Plan status is `pending`, `running`, or `implemented`",
            "candidate HEAD",
            "`implemented`",
            "`ready_for_integration`",
            "Do not merge, push, or deploy",
            "`integration=not_observed`",
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
            "helper",
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
            "no legacy run-state compatibility",
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

    def test_changelog_describes_a_greenfield_release(self) -> None:
        changelog = (SKILL_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

        self.assertIn("## 1.0.0 - 2026-07-23", changelog)
        self.assertIn("greenfield", changelog.lower())
        self.assertIn("does not claim compatibility with legacy run state", changelog)


if __name__ == "__main__":
    unittest.main()
