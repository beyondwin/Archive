from __future__ import annotations

import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]


class SkillContractTests(unittest.TestCase):
    def test_skill_frontmatter_is_discoverable_and_versioned(self) -> None:
        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")

        self.assertTrue(skill.startswith("---\nname: kws-codex-plan-runner\n"))
        self.assertIn(
            "description: Use when approved Superpowers specifications and one or more "
            "ordered implementation plans must run autonomously through Codex with "
            "durable recovery and fail-closed ready-for-integration evidence.",
            skill,
        )
        self.assertIn('version: "1.1.0"', skill)
        self.assertIn('updated_at: "2026-07-25"', skill)

    def test_skill_closes_the_baseline_pressure_failures(self) -> None:
        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")

        for required in (
            "Do not merge, rewrite, or positionally pair",
            "current plan only",
            "durable state, Git HEAD, ledger, and receipts",
            "same-plan session resume",
            "fresh-session fallback",
            "A live controller continues the bounded recovery loop itself",
            "`recovering`",
            "`resumable`",
            "candidate HEAD",
            "`implemented`",
            "`ready_for_integration`",
            "Do not merge, push, or deploy",
            "`integration=not_observed`",
            "same-UID",
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

    def test_subtree_guidance_preserves_runtime_independence(self) -> None:
        guidance = (SKILL_ROOT / "AGENTS.md").read_text(encoding="utf-8")

        for required in (
            "CPython `>=3.13,<3.14`",
            "normal-GIL",
            "standard library only",
            "independent runtime",
            "focused evals",
            "full deterministic eval",
            "real Codex CLI contract",
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

    def test_public_contract_documents_the_thin_superpowers_boundary(self) -> None:
        documents = {
            name: (SKILL_ROOT / name).read_text(encoding="utf-8")
            for name in ("SKILL.md", "README.md", "CHANGELOG.md")
        }
        combined = "\n".join(documents.values())

        for required in (
            "subagent-driven-development",
            "thin wrapper",
            "Superpowers v6.2.0",
            "strategic recovery shell",
            "danger-full-access",
            'approval_policy="never"',
            "--ignore-rules",
            "matching_run_exists",
            "volatile-codex-turn-refs",
            "unsealed-provider-partial",
            "bun run agent:verify -- --base",
        ):
            with self.subTest(required=required):
                self.assertIn(required, combined)

        for document in ("SKILL.md", "README.md"):
            text = " ".join(documents[document].split())
            with self.subTest(document=document, ownership="superpowers"):
                self.assertIn(
                    "Superpowers owns task decomposition, SDD dispatch, TDD, task review, "
                    "and its ledger",
                    text,
                )
            with self.subTest(document=document, ownership="runner"):
                self.assertIn(
                    "does not mirror individual subagent state",
                    text,
                )
            with self.subTest(document=document, ownership="workspace"):
                self.assertIn(
                    "does not parse or migrate those internals",
                    text,
                )

    def test_readme_documents_exact_repair_and_admission_actions(self) -> None:
        readme = (SKILL_ROOT / "README.md").read_text(encoding="utf-8")

        for required in (
            "./scripts/runner repair --run-id",
            "--expected-revision",
            "--repair-kind volatile-codex-turn-refs",
            "--repair-kind unsealed-provider-partial",
            "refs/codex/turn-diffs/captures/",
            "refs/codex/turn-diffs/checkpoints/",
            "host_permission_blocked",
            "effective `CODEX_HOME`",
        ):
            with self.subTest(required=required):
                self.assertIn(required, readme)

    def test_public_contract_documents_audited_recovery_and_v62_helpers(self) -> None:
        documents = {
            name: (SKILL_ROOT / name).read_text(encoding="utf-8")
            for name in ("SKILL.md", "README.md", "CHANGELOG.md")
        }
        combined = " ".join("\n".join(documents.values()).split())

        for required in (
            "--retry-blocked --sandbox danger-full-access",
            "--retry-failed --strategy-note",
            "--model MODEL",
            "execution_profile_transition",
            "provider_capability_blocked",
            "recorded process group and descendant PIDs are quiescent",
            "prior plan handoff HEAD is an ancestor",
            "sdd-workspace",
            "task-brief",
            "review-package",
        ):
            with self.subTest(required=required):
                self.assertIn(required, combined)


if __name__ == "__main__":
    unittest.main()
