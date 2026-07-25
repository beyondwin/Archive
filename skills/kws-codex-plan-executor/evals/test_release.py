"""Release-contract tests for the local CPE 3.0.0 source tree."""

from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = ROOT.parents[1]
VERSION = "3.0.0"
RELEASE_DATE = "2026-07-25"
RELEASE_INVENTORY = {
    "AGENTS.md",
    "CHANGELOG.md",
    "README.md",
    "SKILL.md",
    "evals/check_architecture.py",
    "evals/fake_codex.py",
    "evals/live_canary.py",
    "evals/run.sh",
    "evals/test_cli.py",
    "evals/test_controller.py",
    "evals/test_git.py",
    "evals/test_live_canary.py",
    "evals/test_release.py",
    "evals/test_runtime.py",
    "evals/test_state.py",
    "scripts/cpe.py",
    "scripts/cpe_runtime/__init__.py",
    "scripts/cpe_runtime/controller.py",
    "scripts/cpe_runtime/git.py",
    "scripts/cpe_runtime/runtime.py",
    "scripts/cpe_runtime/state.py",
    "templates/terminal-envelope.schema.json",
}


class ReleaseContractTests(unittest.TestCase):
    def test_release_documents_use_the_same_version_and_date(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

        self.assertIn(f'version: "{VERSION}"', skill)
        self.assertIn(f'updated_at: "{RELEASE_DATE}"', skill)
        self.assertIn(f"Version {VERSION} — {RELEASE_DATE}", readme)
        self.assertIn(f"## {VERSION} - {RELEASE_DATE}", changelog)

    def test_skills_catalog_advertises_cpe_as_its_own_local_contract(self) -> None:
        catalog = (REPOSITORY_ROOT / "skills" / "README.md").read_text(
            encoding="utf-8"
        )

        self.assertIn(
            "[`kws-codex-plan-executor`](./kws-codex-plan-executor/)",
            catalog,
        )
        self.assertIn(
            "CPE 3.0.0 source of truth is the tracked "
            "`skills/kws-codex-plan-executor/` directory.",
            catalog,
        )
        self.assertEqual(
            catalog.count(
                'ln -sfn "$ARCHIVE_REPO/skills/kws-codex-plan-executor"'
            ),
            2,
        )

    def test_readme_inventory_is_the_exact_tracked_release_tree(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        inventory = re.search(
            r"## Tracked Inventory\n\n```text\n(?P<files>.*?)\n```",
            readme,
            re.DOTALL,
        )
        self.assertIsNotNone(inventory)
        assert inventory is not None
        declared = set(inventory.group("files").splitlines())
        tracked = subprocess.run(
            ["git", "ls-files", "--", "skills/kws-codex-plan-executor"],
            cwd=REPOSITORY_ROOT,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        ).stdout.splitlines()
        actual = {
            Path(path).relative_to("skills/kws-codex-plan-executor").as_posix()
            for path in tracked
        }

        self.assertEqual(declared, RELEASE_INVENTORY)
        self.assertEqual(actual, RELEASE_INVENTORY)


if __name__ == "__main__":
    unittest.main(verbosity=2)
