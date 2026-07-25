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
RELEASE_INVENTORY = (
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
)
CLAUDE_HEADING = "Claude Code (`~/.claude/skills/`)"
CODEX_HEADING = "Codex (`~/.codex/skills/`)"


def parse_frontmatter_metadata(skill: str) -> dict[str, str]:
    frontmatter = re.match(
        r"\A---\n(?P<body>.*?)^---\n",
        skill,
        re.DOTALL | re.MULTILINE,
    )
    if frontmatter is None:
        raise AssertionError("SKILL.md must begin with bounded frontmatter")
    frontmatter_lines = frontmatter.group("body").splitlines()
    metadata_indexes = [
        index
        for index, line in enumerate(frontmatter_lines)
        if re.match(r"^metadata\s*:", line)
    ]
    if len(metadata_indexes) != 1:
        raise AssertionError("SKILL.md frontmatter must contain one metadata mapping")
    fields = []
    for field in frontmatter_lines[metadata_indexes[0] + 1 :]:
        if not field.startswith("  "):
            break
        fields.append(field)
    parsed: dict[str, str] = {}
    for field in fields:
        match = re.fullmatch(r'  (version|updated_at): "([^"]+)"', field)
        if match is None or match.group(1) in parsed:
            raise AssertionError("SKILL.md metadata fields must be exact and unique")
        parsed[match.group(1)] = match.group(2)
    if set(parsed) != {"version", "updated_at"}:
        raise AssertionError("SKILL.md metadata must contain only release fields")
    return parsed


def markdown_section(document: str, level: str, heading: str) -> str:
    matches = list(
        re.finditer(rf"^{re.escape(level)} {re.escape(heading)}\n", document, re.MULTILINE)
    )
    if len(matches) != 1:
        raise AssertionError(f"expected one section: {heading}")
    start = matches[0].end()
    next_heading = re.search(rf"^{re.escape(level)} ", document[start:], re.MULTILINE)
    end = start + next_heading.start() if next_heading is not None else len(document)
    return document[start:end]


def without_html_comments(document: str) -> str:
    return re.sub(r"<!--.*?-->", "", document, flags=re.DOTALL)


def cpe_install_entries(section: str, home: str) -> list[str]:
    command = (
        'ln -sfn "$ARCHIVE_REPO/skills/kws-codex-plan-executor" \\\n'
        f"        {home}/kws-codex-plan-executor"
    )
    return re.findall(re.escape(command), section)


def cpe_install_entry(home: str) -> str:
    return (
        'ln -sfn "$ARCHIVE_REPO/skills/kws-codex-plan-executor" \\\n'
        f"        {home}/kws-codex-plan-executor"
    )


class ReleaseContractTests(unittest.TestCase):
    def assert_check_rejects_mutation(
        self,
        path: Path,
        replacement: tuple[str, str],
        check: object,
    ) -> None:
        original = path.read_text(encoding="utf-8")
        before, after = replacement
        self.assertIn(before, original)
        try:
            path.write_text(original.replace(before, after, 1), encoding="utf-8")
            with self.assertRaises(AssertionError):
                check()
        finally:
            path.write_text(original, encoding="utf-8")

    def assert_check_accepts_mutation(
        self,
        path: Path,
        replacement: tuple[str, str],
        check: object,
    ) -> None:
        original = path.read_text(encoding="utf-8")
        before, after = replacement
        self.assertIn(before, original)
        try:
            path.write_text(original.replace(before, after, 1), encoding="utf-8")
            check()
        finally:
            path.write_text(original, encoding="utf-8")

    def assert_check_rejects_transform(
        self,
        path: Path,
        transform: object,
        check: object,
    ) -> None:
        original = path.read_text(encoding="utf-8")
        try:
            path.write_text(transform(original), encoding="utf-8")
            with self.assertRaises(AssertionError):
                check()
        finally:
            path.write_text(original, encoding="utf-8")

    def test_release_check_rejects_body_version_comment_when_frontmatter_is_wrong(
        self,
    ) -> None:
        self.assert_check_rejects_mutation(
            ROOT / "SKILL.md",
            (
                '  version: "3.0.0"',
                '  version: "9.9.9"\n\n<!-- version: "3.0.0" -->',
            ),
            self.test_release_documents_use_the_same_version_and_date,
        )

    def test_release_check_rejects_second_frontmatter_metadata_mapping(self) -> None:
        self.assert_check_rejects_mutation(
            ROOT / "SKILL.md",
            (
                '  updated_at: "2026-07-25"',
                '  updated_at: "2026-07-25"\nmetadata:\n'
                '  version: "9.9.9"\n  updated_at: "2026-07-26"',
            ),
            self.test_release_documents_use_the_same_version_and_date,
        )

    def test_release_check_rejects_inline_frontmatter_metadata_mapping(self) -> None:
        self.assert_check_rejects_mutation(
            ROOT / "SKILL.md",
            (
                '  updated_at: "2026-07-25"',
                '  updated_at: "2026-07-25"\nmetadata: '
                '{version: "9.9.9", updated_at: "2026-07-26"}',
            ),
            self.test_release_documents_use_the_same_version_and_date,
        )

    def test_release_check_accepts_distinct_historical_changelog_heading(self) -> None:
        self.assert_check_accepts_mutation(
            ROOT / "CHANGELOG.md",
            (
                "# Changelog\n",
                "# Changelog\n\n## 2.9.0 - 2026-07-24\n\n- Historical release.\n",
            ),
            self.test_release_documents_use_the_same_version_and_date,
        )

    def test_inventory_check_rejects_duplicate_declared_release_file(self) -> None:
        self.assert_check_rejects_mutation(
            ROOT / "README.md",
            (
                "README.md\nSKILL.md",
                "README.md\nREADME.md\nSKILL.md",
            ),
            self.test_readme_inventory_is_the_exact_tracked_release_tree,
        )

    def test_catalog_check_rejects_missing_or_misbound_provider_sections(self) -> None:
        catalog = REPOSITORY_ROOT / "skills" / "README.md"
        cases = (
            (
                "missing Codex heading",
                "### Codex (`~/.codex/skills/`)",
                "### Other (`~/.codex/skills/`)",
            ),
            (
                "CPE entry moved from Claude to Codex",
                "ln -sfn \"$ARCHIVE_REPO/skills/kws-codex-plan-executor\" \\" + "\n"
                + "        ~/.claude/skills/kws-codex-plan-executor",
                "ln -sfn \"$ARCHIVE_REPO/skills/kws-codex-plan-runner\" \\" + "\n"
                + "        ~/.claude/skills/kws-codex-plan-runner\n"
                + "ln -sfn \"$ARCHIVE_REPO/skills/kws-codex-plan-executor\" \\" + "\n"
                + "        ~/.codex/skills/kws-codex-plan-executor",
            ),
        )
        for name, before, after in cases:
            with self.subTest(name=name):
                self.assert_check_rejects_mutation(
                    catalog,
                    (before, after),
                    self.test_skills_catalog_advertises_cpe_as_its_own_local_contract,
                )

    def test_catalog_check_rejects_duplicate_provider_section(self) -> None:
        self.assert_check_rejects_mutation(
            REPOSITORY_ROOT / "skills" / "README.md",
            (
                "\n### 확인\n",
                "\n### Codex (`~/.codex/skills/`)\n\n```bash\n"
                'ln -sfn "$ARCHIVE_REPO/skills/kws-codex-plan-executor" \\\n'
                "        ~/.codex/skills/kws-codex-plan-executor\n```\n\n"
                "### 확인\n",
            ),
            self.test_skills_catalog_advertises_cpe_as_its_own_local_contract,
        )

    def test_catalog_check_rejects_comment_only_catalog_or_source_claims(self) -> None:
        catalog = REPOSITORY_ROOT / "skills" / "README.md"
        cases = (
            (
                "catalog row",
                "| [`kws-codex-plan-executor`](./kws-codex-plan-executor/) | "
                "하나의 승인된 Superpowers 실행 계약을 위한 Codex local durability "
                "capsule. 순차 plan runner와 별도인 strict-thin "
                "`run`/`resume`/`inspect` 계약입니다. |",
                "<!-- [`kws-codex-plan-executor`](./kws-codex-plan-executor/) -->",
            ),
            (
                "source-of-truth prose",
                "CPE 3.0.0 source of truth is the tracked "
                "`skills/kws-codex-plan-executor/` directory.",
                "<!-- CPE 3.0.0 source of truth is the tracked "
                "`skills/kws-codex-plan-executor/` directory. -->",
            ),
        )
        for name, before, after in cases:
            with self.subTest(name=name):
                self.assert_check_rejects_mutation(
                    catalog,
                    (before, after),
                    self.test_skills_catalog_advertises_cpe_as_its_own_local_contract,
                )

    def test_catalog_check_rejects_multiline_comment_wrapped_sections(self) -> None:
        def wrap_sections(catalog: str) -> str:
            start = catalog.index("## 포함된 스킬")
            end = catalog.index("### 확인")
            return catalog[:start] + "<!--\n" + catalog[start:end] + "-->\n" + catalog[end:]

        self.assert_check_rejects_transform(
            REPOSITORY_ROOT / "skills" / "README.md",
            wrap_sections,
            self.test_skills_catalog_advertises_cpe_as_its_own_local_contract,
        )

    def test_catalog_check_rejects_global_duplicate_cpe_install_command(self) -> None:
        self.assert_check_rejects_mutation(
            REPOSITORY_ROOT / "skills" / "README.md",
            (
                "## 수정 워크플로",
                cpe_install_entry("~/.codex/skills") + "\n\n## 수정 워크플로",
            ),
            self.test_skills_catalog_advertises_cpe_as_its_own_local_contract,
        )

    def test_release_documents_use_the_same_version_and_date(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

        self.assertEqual(
            parse_frontmatter_metadata(skill),
            {"version": VERSION, "updated_at": RELEASE_DATE},
        )
        self.assertEqual(
            re.findall(
                r"^Version ([0-9]+\.[0-9]+\.[0-9]+) — (\d{4}-\d{2}-\d{2}) is ",
                readme,
                re.MULTILINE,
            ),
            [(VERSION, RELEASE_DATE)],
        )
        self.assertEqual(
            [
                heading
                for heading in re.findall(
                    r"^## ([0-9]+\.[0-9]+\.[0-9]+) - (\d{4}-\d{2}-\d{2})$",
                    changelog,
                    re.MULTILINE,
                )
                if heading[0] == VERSION
            ],
            [(VERSION, RELEASE_DATE)],
        )

    def test_skills_catalog_advertises_cpe_as_its_own_local_contract(self) -> None:
        catalog = (REPOSITORY_ROOT / "skills" / "README.md").read_text(
            encoding="utf-8"
        )
        live_catalog = without_html_comments(catalog)

        catalog_rows = re.findall(
            r"^\| \[`kws-codex-plan-executor`\]"
            r"\(\./kws-codex-plan-executor/\) \| (?P<purpose>.+) \|$",
            markdown_section(live_catalog, "##", "포함된 스킬"),
            re.MULTILINE,
        )
        self.assertEqual(
            catalog_rows,
            [
                "하나의 승인된 Superpowers 실행 계약을 위한 Codex local "
                "durability capsule. 순차 plan runner와 별도인 strict-thin "
                "`run`/`resume`/`inspect` 계약입니다."
            ],
        )
        self.assertEqual(
            re.findall(
                r"^`kws-codex-plan-executor`의 현재 릴리스는 `3\.0\.0`입니다\. "
                r"CPE 3\.0\.0 source of truth is the tracked "
                r"`skills/kws-codex-plan-executor/` directory\.$",
                markdown_section(live_catalog, "##", "버전과 릴리스 상태"),
                re.MULTILINE,
            ),
            [
                "`kws-codex-plan-executor`의 현재 릴리스는 `3.0.0`입니다. "
                "CPE 3.0.0 source of truth is the tracked "
                "`skills/kws-codex-plan-executor/` directory."
            ],
        )
        self.assertEqual(
            cpe_install_entries(
                markdown_section(live_catalog, "###", CLAUDE_HEADING),
                "~/.claude/skills",
            ),
            [cpe_install_entry("~/.claude/skills")],
        )
        self.assertEqual(
            cpe_install_entries(
                markdown_section(live_catalog, "###", CODEX_HEADING),
                "~/.codex/skills",
            ),
            [cpe_install_entry("~/.codex/skills")],
        )
        self.assertEqual(
            live_catalog.count(
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
        declared = inventory.group("files").splitlines()
        tracked = subprocess.run(
            ["git", "ls-files", "--", "skills/kws-codex-plan-executor"],
            cwd=REPOSITORY_ROOT,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        ).stdout.splitlines()
        actual = [
            Path(path).relative_to("skills/kws-codex-plan-executor").as_posix()
            for path in tracked
        ]

        self.assertEqual(len(declared), len(set(declared)))
        self.assertEqual(declared, list(RELEASE_INVENTORY))
        self.assertEqual(actual, list(RELEASE_INVENTORY))


if __name__ == "__main__":
    unittest.main(verbosity=2)
