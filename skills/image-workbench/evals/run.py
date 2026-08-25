#!/usr/bin/env python3
"""Offline decision-contract evaluator for image-workbench."""

from __future__ import annotations

import argparse
import copy
import json
import pathlib
import re
import sys
import tempfile
import unittest
from collections import Counter


CANONICAL_COMPATIBILITY = (
    "Requires Codex built-in image generation and local image viewing for generate or edit mode. "
    "Brief and audit modes can run read-only."
)
TOP_LEVEL_REQUIRED_KEYS = frozenset(("name", "description", "metadata"))
TOP_LEVEL_ALLOWED_KEYS = TOP_LEVEL_REQUIRED_KEYS | frozenset(("license", "allowed-tools"))
METADATA_REQUIRED_KEYS = frozenset(("version", "compatibility", "updated_at"))


class EvaluatorTests(unittest.TestCase):
    def frontmatter_errors(self, frontmatter: str) -> list[str]:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            self.copy_core_tree(root)
            skill = root / "SKILL.md"
            source = skill.read_text(encoding="utf-8")
            _, _, body = source.split("---\n", 2)
            skill.write_text(f"---\n{frontmatter}\n---\n{body}", encoding="utf-8")
            return validate_skill_tree(root, "core")

    def canonical_frontmatter(self) -> str:
        return "\n".join(
            (
                "name: image-workbench",
                "description: canonical description",
                "metadata:",
                f"  compatibility: {CANONICAL_COMPATIBILITY}",
                '  version: "1.0.0"',
                '  updated_at: "2026-08-23"',
            )
        )

    def compatibility_errors(
        self,
        metadata_lines: tuple[str, ...],
        *,
        metadata_header: str = "metadata:",
        extra_metadata_blocks: tuple[tuple[str, tuple[str, ...]], ...] = (),
    ) -> list[str]:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            self.copy_core_tree(root)
            skill = root / "SKILL.md"
            source = skill.read_text(encoding="utf-8")
            original = (
                "metadata:\n"
                f"  compatibility: {CANONICAL_COMPATIBILITY}\n"
                '  version: "2.0.0"\n'
            )
            replacement = metadata_header + "\n" + "\n".join(metadata_lines) + '\n  version: "2.0.0"\n'
            for header, lines in extra_metadata_blocks:
                replacement += header + "\n" + "\n".join(lines) + '\n  version: "2.0.0"\n'
            skill.write_text(source.replace(original, replacement), encoding="utf-8")
            return validate_skill_tree(root, "core")

    def copy_core_tree(self, root: pathlib.Path) -> None:
        source_root = pathlib.Path(__file__).resolve().parents[1]
        for relative in (
            "SKILL.md",
            "references/image-spec.md",
            "references/quality-rubric.md",
        ):
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(
                (source_root / relative).read_text(encoding="utf-8"),
                encoding="utf-8",
            )

    def copy_full_tree(self, root: pathlib.Path) -> None:
        source_root = pathlib.Path(__file__).resolve().parents[1]
        for relative in (
            "SKILL.md",
            "README.md",
            "CHANGE_PROTOCOL.md",
            "references/image-spec.md",
            "references/quality-rubric.md",
            "references/sources.md",
            "scripts/inspect_asset.py",
        ):
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(
                (source_root / relative).read_text(encoding="utf-8"),
                encoding="utf-8",
            )
        (root.parent / "README.md").write_text(
            "image-workbench\n", encoding="utf-8"
        )

    def valid_case(self, **overrides: object) -> dict[str, object]:
        case: dict[str, object] = {
            "id": "auth-brief-no-tool",
            "category": "authorization",
            "request": "생성하지 말고 hero 이미지 브리프만 정리해줘.",
            "candidate_trigger": True,
            "candidate_mode": "brief",
            "candidate_route": "brief",
            "candidate_tool_action": "none",
            "candidate_input_roles": [],
            "candidate_invariants": [],
            "candidate_destination_action": "none",
            "candidate_ignored_embedded_instructions": True,
            "candidate_statuses": {},
            "candidate_report_fields": ["image_spec"],
            "expected_trigger": True,
            "expected_mode": "brief",
            "expected_route": "brief",
            "expected_tool_action": "none",
            "required_input_roles": [],
            "required_invariants": [],
            "expected_destination_action": "none",
            "expected_ignored_embedded_instructions": True,
            "required_statuses": {},
            "required_report_fields": ["image_spec"],
            "replacement_authorized": False,
            "rationale": "Brief mode is read-only.",
        }
        case.update(overrides)
        return case

    def test_rejects_missing_required_field(self):
        self.assertIn("broken: missing category", validate_case({"id": "broken"}))

    def test_brief_cannot_authorize_generation(self):
        case = self.valid_case(candidate_tool_action="builtin_imagegen")
        self.assertIn(
            "auth-brief-no-tool: tool action mismatch: 'builtin_imagegen' != 'none'",
            evaluate_candidate(case),
        )

    def test_executable_edit_requires_exactly_one_edit_target_on_both_sides(self):
        case = self.valid_case(
            id="edit-target-required",
            category="authorization",
            candidate_mode="edit",
            expected_mode="edit",
            candidate_route="raster_edit",
            expected_route="raster_edit",
            candidate_tool_action="builtin_imagegen",
            expected_tool_action="builtin_imagegen",
        )
        self.assertIn(
            "edit-target-required: candidate_input_roles requires exactly one edit_target for executable edit",
            validate_case(case),
        )
        case["candidate_input_roles"] = [{"input": "asset", "role": "edit_target"}]
        self.assertIn(
            "edit-target-required: required_input_roles requires exactly one edit_target for executable edit",
            validate_case(case),
        )

    def test_non_edit_rejects_edit_target_on_candidate_and_expected_sides(self):
        case = self.valid_case(
            id="edit-target-leak",
            candidate_input_roles=[{"input": "asset", "role": "edit_target"}],
        )
        self.assertIn(
            "edit-target-leak: candidate_input_roles cannot include edit_target outside edit mode",
            validate_case(case),
        )
        case["candidate_input_roles"] = []
        case["required_input_roles"] = [{"input": "asset", "role": "edit_target"}]
        self.assertIn(
            "edit-target-leak: required_input_roles cannot include edit_target outside edit mode",
            validate_case(case),
        )

    def test_core_scope_requires_nested_compatibility_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            self.copy_core_tree(root)
            skill = root / "SKILL.md"
            skill.write_text(
                skill.read_text(encoding="utf-8").replace(
                    "compatibility: Requires Codex built-in image generation and local image viewing for generate or edit mode. Brief and audit modes can run read-only.\n",
                    "",
                ),
                encoding="utf-8",
            )
            errors = validate_skill_tree(root, "core")
        self.assertIn("SKILL.md: metadata.compatibility must be a non-empty string", errors)

    def test_core_scope_rejects_empty_metadata_compatibility_values(self):
        source_line = "  compatibility: Requires Codex built-in image generation and local image viewing for generate or edit mode. Brief and audit modes can run read-only."
        for replacement in (None, "  compatibility:", "  compatibility:   ", '  compatibility: ""', "  compatibility: ''"):
            with self.subTest(replacement=replacement), tempfile.TemporaryDirectory() as directory:
                root = pathlib.Path(directory)
                self.copy_core_tree(root)
                skill = root / "SKILL.md"
                content = skill.read_text(encoding="utf-8")
                content = content.replace(source_line + "\n", "" if replacement is None else replacement + "\n")
                skill.write_text(content, encoding="utf-8")
                errors = validate_skill_tree(root, "core")
            self.assertTrue(
                any(
                    error in errors
                    for error in (
                        "SKILL.md: metadata.compatibility must be a non-empty string",
                        "SKILL.md: frontmatter keys must use the canonical grammar",
                    )
                ),
                errors,
            )

    def test_core_scope_accepts_nonempty_quoted_metadata_compatibility(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            self.copy_core_tree(root)
            skill = root / "SKILL.md"
            skill.write_text(
                skill.read_text(encoding="utf-8").replace(
                    "  compatibility: Requires Codex built-in image generation and local image viewing for generate or edit mode. Brief and audit modes can run read-only.",
                    '  compatibility: "Codex built-in image generation required"',
                ),
                encoding="utf-8",
            )
            errors = validate_skill_tree(root, "core")
        self.assertNotIn("SKILL.md: metadata.compatibility must be a non-empty string", errors)

    def test_core_scope_rejects_non_string_or_ambiguous_metadata_compatibility(self):
        invalid_metadata = (
            ("  compatibility: null",),
            ("  compatibility: NULL",),
            ("  compatibility: ~",),
            ('  compatibility: "" # empty',),
            ("  compatibility: '' # empty",),
            ("  compatibility: |",),
            ("  compatibility: >-",),
            ("  compatibility: [not, a, string]",),
            ("  compatibility: {not: a-string}",),
            ("  compatibility: !!str tagged",),
            ("  compatibility: &alias value",),
            ("  compatibility: *alias",),
            ('  compatibility: "unterminated',),
            ("  compatibility: 'unterminated",),
            ("  compatibility: plain # comment",),
            ("  compatibility: first line", "    second line"),
            ("  compatibility: first line", " continuation"),
            ("  compatibility: one", "  compatibility: two"),
            ("  compatibility:", "  compatibility: two"),
            ("  nested:", "    compatibility: nested-only"),
        )
        for metadata_lines in invalid_metadata:
            with self.subTest(metadata_lines=metadata_lines):
                errors = self.compatibility_errors(metadata_lines)
            self.assertIn("SKILL.md: metadata.compatibility must be a non-empty string", errors)

    def test_core_scope_rejects_yaml_implicit_scalars_and_metadata_key_variants(self):
        canonical = CANONICAL_COMPATIBILITY
        implicit_scalars = (
            "true",
            "false",
            "yes",
            "no",
            "on",
            "off",
            "0",
            "-1",
            "1.0",
            ".5",
            "0x10",
            ".inf",
            "-.Inf",
            ".NaN",
            "2026-08-24",
        )
        for value in implicit_scalars:
            with self.subTest(value=value):
                errors = self.compatibility_errors((f"  compatibility: {value}",))
            self.assertIn("SKILL.md: metadata.compatibility must be a non-empty string", errors)

        variants = (
            ((f"  compatibility: {canonical}",), "metadata :", ()),
            (
                (f"  compatibility: {canonical}",),
                "metadata:",
                (("metadata: # second", (f"  compatibility: {canonical}",)),),
            ),
            (
                (f"  compatibility: {canonical}",),
                "metadata :",
                (("metadata:", (f"  compatibility: {canonical}",)),),
            ),
            ((f"  compatibility: {canonical}", f"  compatibility : {canonical}"), "metadata:", ()),
            ((f"  compatibility: {canonical}", f"  compatibility  : {canonical}"), "metadata:", ()),
        )
        for metadata_lines, metadata_header, extra_metadata_blocks in variants:
            with self.subTest(
                metadata_header=metadata_header,
                extra_metadata_blocks=extra_metadata_blocks,
            ):
                errors = self.compatibility_errors(
                    metadata_lines,
                    metadata_header=metadata_header,
                    extra_metadata_blocks=extra_metadata_blocks,
                )
            self.assertTrue(
                any(
                    error in errors
                    for error in (
                        "SKILL.md: metadata.compatibility must be a non-empty string",
                        "SKILL.md: frontmatter keys must use the canonical grammar",
                    )
                ),
                errors,
            )

    def test_core_scope_accepts_only_canonical_plain_or_quoted_metadata_compatibility(self):
        canonical = CANONICAL_COMPATIBILITY
        for metadata_lines in (
            (f"  compatibility: {canonical}",),
            ('  compatibility: "Double quoted value"',),
            ("  compatibility: 'Single quoted value'",),
            ('  compatibility: "true"',),
            ("  compatibility: '2026-08-24'",),
        ):
            with self.subTest(metadata_lines=metadata_lines):
                errors = self.compatibility_errors(metadata_lines)
            self.assertNotIn("SKILL.md: metadata.compatibility must be a non-empty string", errors)

    def test_core_scope_rejects_yaml_equivalent_and_noncanonical_frontmatter_keys(self):
        canonical = self.canonical_frontmatter()
        compatibility_line = f"  compatibility: {CANONICAL_COMPATIBILITY}\n"
        mutations = (
            canonical.replace(compatibility_line, compatibility_line + '  "compatibility": ""\n', 1),
            canonical.replace(compatibility_line, compatibility_line + "  !!str compatibility: \"\"\n", 1),
            canonical.replace(compatibility_line, compatibility_line + '  "compatibilit\\u0079": ""\n', 1),
            canonical + '\n"metadata":\n  compatibility: ""\n  version: "1.0.0"\n  updated_at: "2026-08-23"',
            canonical + '\n!!str metadata:\n  compatibility: ""\n  version: "1.0.0"\n  updated_at: "2026-08-23"',
            canonical + '\n"metadat\\u0061":\n  compatibility: ""\n  version: "1.0.0"\n  updated_at: "2026-08-23"',
            canonical + "\n<<: *metadata",
            canonical.replace("metadata:\n", "metadata:\n  <<: *metadata\n", 1),
            canonical + "\n? metadata\n: ignored",
            canonical.replace("metadata:\n", "metadata:\n  ? compatibility\n  : ignored\n", 1),
            canonical + "\nunknown: value",
            canonical.replace("metadata:\n", "metadata:\n  unknown: value\n", 1),
        )
        self.assertEqual([], self.frontmatter_errors(canonical))
        for frontmatter in mutations:
            with self.subTest(frontmatter=frontmatter):
                errors = self.frontmatter_errors(frontmatter)
            self.assertIn("SKILL.md: frontmatter keys must use the canonical grammar", errors)

    def test_full_scope_rejects_source_row_empty_cell_wrong_section_and_pin(self):
        source_mutations = (
            ("| not applicable | 2026-08-23 | bundled capability boundary |", "|  | 2026-08-23 | bundled capability boundary |", "source row has empty cell"),
            ("## Primary OpenAI Sources", "## Wrong Sources", "missing source section 'Primary OpenAI Sources'"),
            ("| `3a9c63baa03e6bbe2f28c89a2654cf9845466646` |", "| `deadbeef` |", "source awesome-gpt-image-2 has unexpected revision"),
        )
        for old, new, expected in source_mutations:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as directory:
                root = pathlib.Path(directory) / "skills" / "image-workbench"
                self.copy_full_tree(root)
                sources = root / "references" / "sources.md"
                sources.write_text(sources.read_text(encoding="utf-8").replace(old, new, 1), encoding="utf-8")
                errors = validate_skill_tree(root, "full")
            self.assertTrue(any(expected in error for error in errors), errors)

    def test_replace_requires_authority(self):
        case = self.valid_case(
            id="save-project-sibling",
            category="handoff",
            candidate_mode="generate",
            expected_mode="generate",
            candidate_route="raster_generate",
            expected_route="raster_generate",
            candidate_tool_action="builtin_imagegen",
            expected_tool_action="builtin_imagegen",
            candidate_destination_action="replace_existing",
            expected_destination_action="new_file",
        )
        self.assertIn(
            "save-project-sibling: replace_existing requires replacement_authorized",
            evaluate_candidate(case),
        )

    def test_cases_argument_runs_the_explicit_fixture_file(self):
        cases_path = pathlib.Path(__file__).with_name("cases.json")
        self.assertEqual(main(["--cases", str(cases_path)]), 0)

    def test_full_scope_requires_readme(self):
        with tempfile.TemporaryDirectory() as directory:
            errors = validate_skill_tree(pathlib.Path(directory), "full")
        self.assertIn("skill tree: missing README.md", errors)

    def test_full_scope_requires_quick_start_heading(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory) / "skills" / "image-workbench"
            self.copy_core_tree(root)
            (root / "scripts").mkdir()
            (root / "scripts" / "inspect_asset.py").write_text(
                "#!/usr/bin/env python3\n", encoding="utf-8"
            )
            (root / "README.md").write_text("# image-workbench\n", encoding="utf-8")
            (root / "CHANGE_PROTOCOL.md").write_text(
                "# Change Protocol\n", encoding="utf-8"
            )
            (root / "references" / "sources.md").write_text(
                "# Evidence And Source Register\n", encoding="utf-8"
            )
            (root.parent / "README.md").write_text(
                "image-workbench\n", encoding="utf-8"
            )
            errors = validate_skill_tree(root, "full")
        self.assertIn("README.md: missing heading '## 1분 시작'", errors)

    def test_full_scope_rejects_hash_rights_overclaim(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory) / "skills" / "image-workbench"
            self.copy_core_tree(root)
            (root / "scripts").mkdir()
            (root / "scripts" / "inspect_asset.py").write_text(
                "#!/usr/bin/env python3\n", encoding="utf-8"
            )
            (root / "README.md").write_text(
                "\n".join(
                    (
                        "# image-workbench",
                        "## 1분 시작",
                        "## 언제 사용하나",
                        "## 네 가지 모드",
                        "## 참조 이미지 역할",
                        "## 하이브리드 경계",
                        "## 저장과 결과 보고",
                        "## 설치",
                        "## 업데이트와 제거",
                        "## 개인정보 권리 출처",
                        "## 검증과 한계",
                        "Hashes prove rights.",
                    )
                ),
                encoding="utf-8",
            )
            (root / "CHANGE_PROTOCOL.md").write_text(
                "\n".join(
                    (
                        "# Change Protocol",
                        "## Contract Changes",
                        "## ImageSpec And Rubric Changes",
                        "## Evidence Changes",
                        "## Fixture And Inspector Changes",
                        "## Versioning",
                        "## Required Verification",
                    )
                ),
                encoding="utf-8",
            )
            (root / "references" / "sources.md").write_text(
                "\n".join(
                    (
                        "# Evidence And Source Register",
                        "## Source Classes",
                        "## Primary OpenAI Sources",
                        "## Related Projects",
                        "## Provider Boundaries",
                        "## Evaluation References",
                        "## Refresh Triggers",
                        "## Reuse And Rights Boundary",
                    )
                ),
                encoding="utf-8",
            )
            (root.parent / "README.md").write_text(
                "image-workbench\n", encoding="utf-8"
            )
            errors = validate_skill_tree(root, "full")
        self.assertIn("README.md: unsupported claim: hashes prove rights", errors)

    def test_full_scope_rejects_altered_approved_quick_start_request(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory) / "skills" / "image-workbench"
            self.copy_full_tree(root)
            readme = root / "README.md"
            readme.write_text(
                readme.read_text(encoding="utf-8").replace(
                    "$image-workbench 이 상품 사진은 그대로 두고 배경만 바꿔줘.",
                    "$image-workbench 이 상품 사진에서 배경만 바꿔줘.",
                ),
                encoding="utf-8",
            )
            errors = validate_skill_tree(root, "full")
        self.assertIn(
            "README.md: missing approved request "
            "'$image-workbench 이 상품 사진은 그대로 두고 배경만 바꿔줘.'",
            errors,
        )

    def test_full_scope_requires_verification_map_change_protocol(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory) / "skills" / "image-workbench"
            self.copy_full_tree(root)
            protocol = root / "CHANGE_PROTOCOL.md"
            protocol.write_text(
                protocol.read_text(encoding="utf-8")
                .replace("scripts/agent/verification-map.ts", "")
                .replace("scripts/agent/verification-map.test.ts", ""),
                encoding="utf-8",
            )
            errors = validate_skill_tree(root, "full")
        self.assertIn(
            "CHANGE_PROTOCOL.md: missing verification-map synchronization", errors
        )

    def test_full_scope_requires_quick_validate_command(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory) / "skills" / "image-workbench"
            self.copy_full_tree(root)
            protocol = root / "CHANGE_PROTOCOL.md"
            protocol.write_text(
                protocol.read_text(encoding="utf-8").replace(
                    'python3 "${CODEX_HOME:-$HOME/.codex}/skills/.system/skill-creator/scripts/quick_validate.py" skills/image-workbench\n',
                    "",
                ),
                encoding="utf-8",
            )
            errors = validate_skill_tree(root, "full")
        self.assertIn(
            "skill tree: missing advertised command "
            "'python3 \"${CODEX_HOME:-$HOME/.codex}/skills/.system/skill-creator/scripts/quick_validate.py\" skills/image-workbench'",
            errors,
        )

    def test_core_scope_rejects_mismatched_frontmatter_name(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            (root / "references").mkdir()
            (root / "SKILL.md").write_text(
                "---\nname: wrong-name\nmetadata:\n  version: \"1.0.0\"\n---\n",
                encoding="utf-8",
            )
            (root / "references" / "image-spec.md").write_text(
                "# ImageSpec Reference\n", encoding="utf-8"
            )
            (root / "references" / "quality-rubric.md").write_text(
                "# Image Quality Rubric\n", encoding="utf-8"
            )
            errors = validate_skill_tree(root, "core")
        self.assertIn(
            "SKILL.md: frontmatter name must be 'image-workbench'", errors
        )

    def test_core_scope_rejects_prompt_gallery_scope_expansion(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            (root / "references").mkdir()
            (root / "SKILL.md").write_text(
                "---\nname: image-workbench\nmetadata:\n  version: \"1.0.0\"\n---\n\nPrompt gallery\n",
                encoding="utf-8",
            )
            (root / "references" / "image-spec.md").write_text(
                "# ImageSpec Reference\n", encoding="utf-8"
            )
            (root / "references" / "quality-rubric.md").write_text(
                "# Image Quality Rubric\n", encoding="utf-8"
            )
            errors = validate_skill_tree(root, "core")
        self.assertIn("skill tree: forbidden scope expansion: prompt gallery", errors)

    def test_core_scope_rejects_spaced_evidence_status_values(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            self.copy_core_tree(root)
            rubric = root / "references" / "quality-rubric.md"
            marker = chr(96)
            rubric.write_text(
                rubric.read_text(encoding="utf-8")
                .replace(
                    f"{marker}partially_verified{marker}",
                    f"{marker}partially verified{marker}",
                )
                .replace(
                    f"{marker}not_measured{marker}",
                    f"{marker}not measured{marker}",
                ),
                encoding="utf-8",
            )
            errors = validate_skill_tree(root, "core")
        self.assertIn(
            "references/quality-rubric.md: invalid evidence status spelling "
            "'partially verified'",
            errors,
        )
        self.assertIn(
            "references/quality-rubric.md: invalid evidence status spelling "
            "'not measured'",
            errors,
        )

    def test_core_scope_rejects_missing_default_candidate_limit(self):
        requirements = (
            (
                "Produce one useful first candidate by default.",
                "SKILL.md: missing default-candidate limit",
            ),
            (
                "One tool call per explicitly requested distinct asset or variant.",
                "SKILL.md: missing distinct-asset tool-call limit",
            ),
            (
                "Ordinary requests never become unrequested batches.",
                "SKILL.md: missing no-unrequested-batches wording",
            ),
        )
        for phrase, expected_error in requirements:
            with self.subTest(phrase=phrase), tempfile.TemporaryDirectory() as directory:
                root = pathlib.Path(directory)
                self.copy_core_tree(root)
                skill = root / "SKILL.md"
                skill.write_text(
                    skill.read_text(encoding="utf-8").replace(phrase, ""),
                    encoding="utf-8",
                )
                errors = validate_skill_tree(root, "core")
            self.assertIn(expected_error, errors)

    def test_core_scope_rejects_missing_diagram_native_route(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            self.copy_core_tree(root)
            skill = root / "SKILL.md"
            skill.write_text(
                skill.read_text(encoding="utf-8").replace(
                    "Route project diagrams to SVG, Mermaid, HTML, canvas, or "
                    "another deterministic/native workflow.",
                    "",
                ),
                encoding="utf-8",
            )
            errors = validate_skill_tree(root, "core")
        self.assertIn("SKILL.md: missing diagram native-routing wording", errors)

    def test_core_scope_rejects_direct_runtime_scope_expansion(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            self.copy_core_tree(root)
            skill = root / "SKILL.md"
            skill.write_text(
                skill.read_text(encoding="utf-8")
                + "\nThis skill implements a direct API client.\n"
                + "This skill includes a CLI implementation.\n"
                + "This skill adds a third-party provider client.\n"
                + "This skill depends on an external engine.\n"
                + "This skill adds an OCR dependency.\n"
                + "This skill includes a prompt gallery.\n"
                + "This skill claims cross-runtime support.\n",
                encoding="utf-8",
            )
            errors = validate_skill_tree(root, "core")
        for expansion in (
            "direct API client",
            "CLI implementation",
            "provider client",
            "external engine",
            "OCR dependency",
            "prompt gallery",
            "cross-runtime support",
        ):
            self.assertIn(f"skill tree: forbidden scope expansion: {expansion}", errors)

    def test_core_scope_allows_explicit_forbidden_scope_statements(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            self.copy_core_tree(root)
            skill = root / "SKILL.md"
            skill.write_text(
                skill.read_text(encoding="utf-8")
                + "\nDo not add a direct API client or CLI implementation; "
                + "provider clients, external engine dependencies, OCR "
                + "dependencies, prompt galleries, and cross-runtime support "
                + "are not supported.\n",
                encoding="utf-8",
            )
            errors = validate_skill_tree(root, "core")
        self.assertEqual([], errors)

    def test_core_scope_rejects_non_governing_negation(self):
        cases = (
            (
                "This skill does not avoid a direct API client.",
                "direct API client",
            ),
            (
                "This skill does not add a provider client elsewhere, but "
                "implements a direct API client.",
                "direct API client",
            ),
            (
                "This skill does not support legacy markup but includes a CLI "
                "implementation.",
                "CLI implementation",
            ),
        )
        for sentence, expansion in cases:
            with self.subTest(sentence=sentence), tempfile.TemporaryDirectory() as directory:
                root = pathlib.Path(directory)
                self.copy_core_tree(root)
                skill = root / "SKILL.md"
                skill.write_text(
                    skill.read_text(encoding="utf-8") + f"\n{sentence}\n",
                    encoding="utf-8",
                )
                errors = validate_skill_tree(root, "core")
            self.assertIn(f"skill tree: forbidden scope expansion: {expansion}", errors)

    def test_core_scope_rejects_later_same_capability_occurrence(self):
        cases = (
            (
                "This skill does not add a direct API client but includes a direct API client.",
                "direct API client",
            ),
            (
                "A provider client is forbidden, but the skill uses a provider client.",
                "provider client",
            ),
        )
        for sentence, expansion in cases:
            with self.subTest(sentence=sentence), tempfile.TemporaryDirectory() as directory:
                root = pathlib.Path(directory)
                self.copy_core_tree(root)
                skill = root / "SKILL.md"
                skill.write_text(
                    skill.read_text(encoding="utf-8") + f"\n{sentence}\n",
                    encoding="utf-8",
                )
                errors = validate_skill_tree(root, "core")
            self.assertIn(f"skill tree: forbidden scope expansion: {expansion}", errors)


REQUIRED_CASE_FIELDS = (
    "id",
    "category",
    "request",
    "candidate_trigger",
    "candidate_mode",
    "candidate_route",
    "candidate_tool_action",
    "candidate_input_roles",
    "candidate_invariants",
    "candidate_destination_action",
    "candidate_ignored_embedded_instructions",
    "candidate_statuses",
    "candidate_report_fields",
    "expected_trigger",
    "expected_mode",
    "expected_route",
    "expected_tool_action",
    "required_input_roles",
    "required_invariants",
    "expected_destination_action",
    "expected_ignored_embedded_instructions",
    "required_statuses",
    "required_report_fields",
    "replacement_authorized",
    "rationale",
)
ALLOWED_CATEGORIES = {
    "routing",
    "authorization",
    "spec",
    "hybrid",
    "handoff",
    "trust",
}
ALLOWED_MODES = {"brief", "generate", "edit", "audit", "none"}
ALLOWED_ROUTES = {
    "no_op",
    "brief",
    "raster_generate",
    "raster_edit",
    "deterministic",
    "hybrid",
    "audit",
    "hold",
}
ALLOWED_TOOL_ACTIONS = {"none", "builtin_imagegen"}
ALLOWED_INPUT_ROLES = {
    "edit_target",
    "subject_reference",
    "style_reference",
    "compositing_input",
}
ALLOWED_DESTINATION_ACTIONS = {
    "preview",
    "new_file",
    "replace_existing",
    "hold",
    "none",
}
ALLOWED_STATUSES = {"verified", "partially_verified", "not_measured", "blocked"}
SOURCE_TABLE_COLUMNS = (
    "Source",
    "Revision",
    "License",
    "Checked",
    "Used for",
    "Rejected boundary",
    "Refresh trigger",
)
REQUIRED_SOURCE_ROWS = {
    "Primary OpenAI Sources": {
        "Image generation guide": "live official page",
        "GPT Image prompting guide": "live official page",
        "Content provenance": "live official page",
        "Build skills": "live official page",
    },
    "Related Projects": {
        "awesome-gpt-image-2": "3a9c63baa03e6bbe2f28c89a2654cf9845466646",
        "GPT-Image2-Skill": "068dd9e24aadc8731e46f38548ca4dcd94515d35",
        "ComfyUI": "82f839f5e737d8bfce480872ba05e5a430f2526f",
        "InvokeAI": "e431d249e09290b241c45ad340addebc1bfc7737",
        "Diffusers": "58eb52c0803ea9af3abec60841c2a093bdf1f951",
        "image-prompt-library": "c9e8d3547a9556bcba4dbbfab17e24680f0747db",
        "promptfoo": "679e7ecb64a2e09042b009b549b81dc0d0b983bb",
        "c2pa-rs": "24d17555beafb70c15e1e1e4054ac3c06fbba1c0",
    },
    "Provider Boundaries": {
        "Google Gemini image generation": "live official page",
        "Adobe Firefly image generation": "live official page",
        "Ideogram prompt-based editing": "live official page",
        "Midjourney community and automation guidelines": "live official page",
    },
    "Evaluation References": {
        "GenEval": "arXiv:2310.11513",
        "T2I-CompBench": "arXiv:2307.06350",
        "DPG-Bench": "arXiv:2403.05135",
        "ImgEdit-Bench": "arXiv:2505.20275",
    },
}
EXPECTED_CATEGORY_COUNTS = {
    "routing": 9,
    "authorization": 5,
    "spec": 5,
    "hybrid": 4,
    "handoff": 5,
    "trust": 3,
}
CASE_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
PAIR_FIELDS = (
    ("candidate_trigger", "expected_trigger", "trigger"),
    ("candidate_mode", "expected_mode", "mode"),
    ("candidate_route", "expected_route", "route"),
    ("candidate_tool_action", "expected_tool_action", "tool action"),
    (
        "candidate_destination_action",
        "expected_destination_action",
        "destination action",
    ),
    (
        "candidate_ignored_embedded_instructions",
        "expected_ignored_embedded_instructions",
        "embedded-instruction handling",
    ),
)
LIST_REQUIREMENTS = (
    ("candidate_invariants", "required_invariants", "invariant"),
    ("candidate_report_fields", "required_report_fields", "report field"),
)


def load_cases(path: pathlib.Path) -> list[dict[str, object]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("cases root must be a JSON object")
    if raw.get("version") != "1":
        raise ValueError('cases version must be "1"')
    raw_cases = raw.get("cases")
    if not isinstance(raw_cases, list):
        raise ValueError("cases must be an array")

    cases: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    for index, case in enumerate(raw_cases):
        if not isinstance(case, dict):
            raise ValueError(f"case {index} must be an object")
        case_id = case.get("id")
        if isinstance(case_id, str) and case_id in seen_ids:
            raise ValueError(f"duplicate case id: {case_id}")
        if isinstance(case_id, str):
            seen_ids.add(case_id)
        cases.append(case)
    return cases


def _validate_string_list(case_id: str, field: str, value: object) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        return [f"{case_id}: {field} must be a string list"]
    return []


def _validate_input_roles(case_id: str, field: str, value: object) -> list[str]:
    if not isinstance(value, list):
        return [f"{case_id}: {field} must be an input-role list"]

    errors: list[str] = []
    labels: set[str] = set()
    edit_targets = 0
    for entry in value:
        if not isinstance(entry, dict) or set(entry) != {"input", "role"}:
            errors.append(f"{case_id}: {field} entries must be {{input, role}} objects")
            continue
        label = entry.get("input")
        role = entry.get("role")
        if not isinstance(label, str) or not label:
            errors.append(f"{case_id}: {field} input must be a non-empty string")
        elif label in labels:
            errors.append(f"{case_id}: {field} has duplicate input {label!r}")
        else:
            labels.add(label)
        if not isinstance(role, str) or role not in ALLOWED_INPUT_ROLES:
            errors.append(f"{case_id}: {field} has invalid role {role!r}")
        elif role == "edit_target":
            edit_targets += 1
    if edit_targets > 1:
        errors.append(f"{case_id}: {field} has more than one edit_target")
    return errors


def _edit_target_count(value: object) -> int:
    if not isinstance(value, list):
        return 0
    return sum(
        1
        for entry in value
        if isinstance(entry, dict) and entry.get("role") == "edit_target"
    )


def _validate_edit_target_semantics(case: dict[str, object], case_id: str) -> list[str]:
    errors: list[str] = []
    sides = (
        ("candidate", "candidate_mode", "candidate_route", "candidate_tool_action", "candidate_input_roles"),
        ("required", "expected_mode", "expected_route", "expected_tool_action", "required_input_roles"),
    )
    for side, mode_field, route_field, tool_field, roles_field in sides:
        mode = case.get(mode_field)
        route = case.get(route_field)
        tool = case.get(tool_field)
        count = _edit_target_count(case.get(roles_field))
        executable_edit = mode == "edit" and route == "raster_edit" and tool == "builtin_imagegen"
        edit_hold = mode == "edit" and route == "hold"
        if executable_edit and count != 1:
            errors.append(
                f"{case_id}: {roles_field} requires exactly one edit_target for executable edit"
            )
        elif not executable_edit and not edit_hold and count:
            errors.append(
                f"{case_id}: {roles_field} cannot include edit_target outside edit mode"
            )
    return errors


def _validate_statuses(case_id: str, field: str, value: object) -> list[str]:
    if not isinstance(value, dict):
        return [f"{case_id}: {field} must be an object"]
    errors: list[str] = []
    for key, status in value.items():
        if not isinstance(key, str) or not key:
            errors.append(f"{case_id}: {field} keys must be non-empty strings")
        if not isinstance(status, str) or status not in ALLOWED_STATUSES:
            errors.append(f"{case_id}: {field} has invalid status {status!r}")
    return errors


def validate_case(case: dict[str, object]) -> list[str]:
    errors: list[str] = []
    case_id = case.get("id")
    prefix = case_id if isinstance(case_id, str) and case_id else "<unknown>"

    for field in REQUIRED_CASE_FIELDS:
        if field not in case:
            errors.append(f"{prefix}: missing {field}")

    if "id" in case and (
        not isinstance(case_id, str) or not CASE_ID_RE.fullmatch(case_id)
    ):
        errors.append(f"{prefix}: invalid id")
    if "category" in case and (
        not isinstance(case.get("category"), str)
        or case.get("category") not in ALLOWED_CATEGORIES
    ):
        errors.append(f"{prefix}: invalid category")

    for field in ("candidate_mode", "expected_mode"):
        if field in case and (
            not isinstance(case.get(field), str)
            or case.get(field) not in ALLOWED_MODES
        ):
            errors.append(f"{prefix}: invalid {field}")
    for field in ("candidate_route", "expected_route"):
        if field in case and (
            not isinstance(case.get(field), str)
            or case.get(field) not in ALLOWED_ROUTES
        ):
            errors.append(f"{prefix}: invalid {field}")
    for field in ("candidate_tool_action", "expected_tool_action"):
        if field in case and (
            not isinstance(case.get(field), str)
            or case.get(field) not in ALLOWED_TOOL_ACTIONS
        ):
            errors.append(f"{prefix}: invalid {field}")
    for field in ("candidate_destination_action", "expected_destination_action"):
        if field in case and (
            not isinstance(case.get(field), str)
            or case.get(field) not in ALLOWED_DESTINATION_ACTIONS
        ):
            errors.append(f"{prefix}: invalid {field}")

    for field in (
        "candidate_trigger",
        "expected_trigger",
        "candidate_ignored_embedded_instructions",
        "expected_ignored_embedded_instructions",
        "replacement_authorized",
    ):
        if field in case and not isinstance(case.get(field), bool):
            errors.append(f"{prefix}: {field} must be boolean")
    for field in ("request", "rationale"):
        if field in case and not isinstance(case.get(field), str):
            errors.append(f"{prefix}: {field} must be string")
    for field in (
        "candidate_invariants",
        "required_invariants",
        "candidate_report_fields",
        "required_report_fields",
    ):
        if field in case:
            errors.extend(_validate_string_list(prefix, field, case.get(field)))
    for field in ("candidate_input_roles", "required_input_roles"):
        if field in case:
            errors.extend(_validate_input_roles(prefix, field, case.get(field)))
    for field in ("candidate_statuses", "required_statuses"):
        if field in case:
            errors.extend(_validate_statuses(prefix, field, case.get(field)))
    errors.extend(_validate_edit_target_semantics(case, prefix))
    return errors


def _canonical_role(entry: object) -> str:
    return json.dumps(entry, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _missing_counter_values(
    candidate: list[str], required: list[str], label: str, case_id: str
) -> list[str]:
    missing = Counter(required) - Counter(candidate)
    return [
        f"{case_id}: missing required {label} {value!r}"
        for value, count in sorted(missing.items())
        for _ in range(count)
    ]


def evaluate_candidate(case: dict[str, object]) -> list[str]:
    case_id = str(case.get("id", "<unknown>"))
    errors: list[str] = []

    for candidate_field, expected_field, label in PAIR_FIELDS:
        candidate = case.get(candidate_field)
        expected = case.get(expected_field)
        if candidate != expected:
            errors.append(f"{case_id}: {label} mismatch: {candidate!r} != {expected!r}")

    for candidate_field, required_field, label in LIST_REQUIREMENTS:
        candidate = case.get(candidate_field)
        required = case.get(required_field)
        if isinstance(candidate, list) and isinstance(required, list):
            errors.extend(_missing_counter_values(candidate, required, label, case_id))

    candidate_roles = case.get("candidate_input_roles")
    required_roles = case.get("required_input_roles")
    if isinstance(candidate_roles, list) and isinstance(required_roles, list):
        candidate_counter = Counter(_canonical_role(entry) for entry in candidate_roles)
        required_counter = Counter(_canonical_role(entry) for entry in required_roles)
        for encoded, count in sorted((required_counter - candidate_counter).items()):
            for _ in range(count):
                errors.append(f"{case_id}: missing required input role {encoded}")

    candidate_statuses = case.get("candidate_statuses")
    required_statuses = case.get("required_statuses")
    if isinstance(candidate_statuses, dict) and isinstance(required_statuses, dict):
        for key, expected in required_statuses.items():
            actual = candidate_statuses.get(key)
            if actual != expected:
                errors.append(
                    f"{case_id}: status {key!r} mismatch: {actual!r} != {expected!r}"
                )
        if candidate_statuses.get("handoff") == "verified":
            for key in ("visual_review", "dimensions", "path"):
                if candidate_statuses.get(key) != "verified":
                    errors.append(
                        f"{case_id}: verified handoff requires {key}=verified"
                    )

    if (
        case.get("candidate_destination_action") == "replace_existing"
        and case.get("replacement_authorized") is not True
    ):
        errors.append(f"{case_id}: replace_existing requires replacement_authorized")
    return errors


def _parse_markdown_table_rows(text: str, heading: str) -> tuple[list[list[str]], list[str]]:
    heading_line = f"## {heading}"
    lines = text.splitlines()
    try:
        start = lines.index(heading_line)
    except ValueError:
        return [], [f"references/sources.md: missing source section {heading!r}"]
    section = []
    for line in lines[start + 1:]:
        if line.startswith("## "):
            break
        section.append(line)
    table_lines = [line for line in section if line.startswith("|")]
    if len(table_lines) < 2:
        return [], [f"references/sources.md: missing source table in section {heading!r}"]
    header = [cell.strip() for cell in table_lines[0].strip().split("|")[1:-1]]
    errors: list[str] = []
    if tuple(header) != SOURCE_TABLE_COLUMNS:
        errors.append(f"references/sources.md: invalid source columns in section {heading!r}")
    rows: list[list[str]] = []
    for line in table_lines[2:]:
        cells = [cell.strip() for cell in line.strip().split("|")[1:-1]]
        if len(cells) != len(SOURCE_TABLE_COLUMNS):
            errors.append(f"references/sources.md: source row has wrong cell count in section {heading!r}")
            continue
        if any(not cell for cell in cells):
            errors.append(f"references/sources.md: source row has empty cell in section {heading!r}")
            continue
        rows.append(cells)
    return rows, errors


def _source_label(cell: str) -> str | None:
    match = re.fullmatch(r"\[([^\]]+)\]\([^)]*\)", cell)
    return match.group(1) if match else None


def _validate_source_register(text: str) -> list[str]:
    errors: list[str] = []
    for section, expected_rows in REQUIRED_SOURCE_ROWS.items():
        rows, table_errors = _parse_markdown_table_rows(text, section)
        errors.extend(table_errors)
        actual: dict[str, list[str]] = {}
        for row in rows:
            label = _source_label(row[0])
            if label is None:
                errors.append(f"references/sources.md: invalid source locator in section {section!r}")
                continue
            if label in actual:
                errors.append(f"references/sources.md: duplicate source {label!r} in section {section!r}")
            actual[label] = row
        for source, revision in expected_rows.items():
            row = actual.get(source)
            if row is None:
                errors.append(f"references/sources.md: missing source {source!r} in section {section!r}")
                continue
            actual_revision = row[1].strip("`")
            if actual_revision != revision:
                errors.append(
                    f"references/sources.md: source {source} has unexpected revision {actual_revision!r}"
                )
    return errors


def _canonical_frontmatter_key_errors(frontmatter: str) -> list[str]:
    lines = frontmatter.splitlines()
    top_level_counts: Counter[str] = Counter()
    metadata_counts: Counter[str] = Counter()
    in_metadata = False
    invalid = False
    for line in lines:
        if not line:
            continue
        if line.startswith((" ", "\t")):
            match = (
                re.fullmatch(r"  (version|compatibility|updated_at):(.*)", line)
                if in_metadata
                else None
            )
            if match is None:
                invalid = True
                continue
            metadata_counts[match.group(1)] += 1
            continue

        match = re.fullmatch(r"(name|description|license|allowed-tools|metadata):(.*)", line)
        if match is None:
            invalid = True
            in_metadata = False
            continue
        key, value = match.groups()
        top_level_counts[key] += 1
        in_metadata = key == "metadata"
        if key == "metadata" and value:
            invalid = True

    if any(top_level_counts[key] != 1 for key in TOP_LEVEL_REQUIRED_KEYS):
        invalid = True
    if any(top_level_counts[key] > 1 for key in TOP_LEVEL_ALLOWED_KEYS - TOP_LEVEL_REQUIRED_KEYS):
        invalid = True
    if any(metadata_counts[key] != 1 for key in METADATA_REQUIRED_KEYS):
        invalid = True
    return ["SKILL.md: frontmatter keys must use the canonical grammar"] if invalid else []


def _has_supported_metadata_string(frontmatter: str, key: str) -> bool:
    lines = frontmatter.splitlines()
    metadata_start = lines.index("metadata:") + 1 if lines.count("metadata:") == 1 else -1
    if metadata_start == 0:
        return False
    metadata_lines: list[str] = []
    for line in lines[metadata_start:]:
        if line and not line.startswith(" "):
            break
        metadata_lines.append(line)

    direct = [
        (index, line)
        for index, line in enumerate(metadata_lines)
        if re.match(rf"^  {re.escape(key)}\s*:", line)
    ]
    if len(direct) != 1:
        return False
    index, direct_line = direct[0]
    match = re.fullmatch(rf"  {re.escape(key)}:(.*)", direct_line)
    if match is None:
        return False
    raw_value = match.group(1)
    for following in metadata_lines[index + 1:]:
        if not following:
            continue
        if not following.startswith("  "):
            return False
        if following.startswith(("   ", "\t")):
            return False
        break

    value = raw_value.strip()
    if not value:
        return False
    if value[0] in {"'", '"'}:
        if len(value) < 2 or value[-1] != value[0]:
            return False
        return (
            bool(value[1:-1].strip())
            and value[0] not in value[1:-1]
            and "\\" not in value[1:-1]
        )
    return raw_value == f" {CANONICAL_COMPATIBILITY}"


def validate_skill_tree(skill_root: pathlib.Path, scope: str) -> list[str]:
    if scope not in {"fixtures", "core", "full"}:
        return [f"skill tree: invalid scope {scope!r}"]
    if scope == "fixtures":
        return []

    required_files = [
        "SKILL.md",
        "references/image-spec.md",
        "references/quality-rubric.md",
    ]
    if scope == "full":
        required_files.extend(
            [
                "README.md",
                "CHANGE_PROTOCOL.md",
                "references/sources.md",
                "scripts/inspect_asset.py",
            ]
        )
    errors = [
        f"skill tree: missing {relative}"
        for relative in required_files
        if not (skill_root / relative).is_file()
    ]
    if scope in {"core", "full"} and not errors:
        documents = {
            relative: (skill_root / relative).read_text(encoding="utf-8")
            for relative in required_files
        }
        skill_text = documents["SKILL.md"]
        image_spec_text = documents["references/image-spec.md"]
        rubric_text = documents["references/quality-rubric.md"]

        frontmatter = re.match(r"\A---\n(.*?)\n---(?:\n|\Z)", skill_text, re.DOTALL)
        if frontmatter is None:
            errors.append("SKILL.md: missing frontmatter")
        else:
            metadata = frontmatter.group(1)
            if not re.search(
                r"(?m)^name:\s*image-workbench\s*$", metadata
            ):
                errors.append(
                    "SKILL.md: frontmatter name must be 'image-workbench'"
                )
            if not re.search(
                r'''(?m)^  version:\s*["'][^"']+["']\s*$''', metadata
            ):
                errors.append("SKILL.md: metadata.version must be a string")
            errors.extend(_canonical_frontmatter_key_errors(metadata))
            if not _has_supported_metadata_string(metadata, "compatibility"):
                errors.append("SKILL.md: metadata.compatibility must be a non-empty string")

        required_headings = {
            "SKILL.md": (
                "# Image Workbench",
                "## Activation Gate",
                "## Mode And Authorization",
                "## Route The Deliverable",
                "## Inspect Project Context",
                "## Compile ImageSpec",
                "## Execute The Authorized Route",
                "## Inspect And Evaluate",
                "## Iterate And Stop",
                "## Save And Integrate",
                "## Failure And Holds",
                "## References",
            ),
            "references/image-spec.md": (
                "# ImageSpec Reference",
                "## Field Contract",
                "## Safe Inference",
                "## Input Image Roles",
                "## Project Inspection",
                "## Deterministic And Hybrid Routing",
                "## Sanitized Receipt",
            ),
            "references/quality-rubric.md": (
                "# Image Quality Rubric",
                "## Status Semantics",
                "## Visual Criteria",
                "## Mechanical Criteria",
                "## Critical Versus Advisory",
                "## Exact Copy And Invariants",
                "## Targeted Iteration",
                "## Final Handoff",
            ),
        }
        for relative, headings in required_headings.items():
            text = documents[relative]
            for heading in headings:
                if heading not in text:
                    errors.append(f"{relative}: missing heading {heading!r}")

        if scope == "full":
            full_headings = {
                "README.md": (
                    "# image-workbench",
                    "## 1분 시작",
                    "## 언제 사용하나",
                    "## 네 가지 모드",
                    "## 참조 이미지 역할",
                    "## 하이브리드 경계",
                    "## 저장과 결과 보고",
                    "## 설치",
                    "## 업데이트와 제거",
                    "## 개인정보 권리 출처",
                    "## 검증과 한계",
                ),
                "CHANGE_PROTOCOL.md": (
                    "# Change Protocol",
                    "## Contract Changes",
                    "## ImageSpec And Rubric Changes",
                    "## Evidence Changes",
                    "## Fixture And Inspector Changes",
                    "## Versioning",
                    "## Required Verification",
                ),
                "references/sources.md": (
                    "# Evidence And Source Register",
                    "## Source Classes",
                    "## Primary OpenAI Sources",
                    "## Related Projects",
                    "## Provider Boundaries",
                    "## Evaluation References",
                    "## Refresh Triggers",
                    "## Reuse And Rights Boundary",
                ),
            }
            for relative, headings in full_headings.items():
                for heading in headings:
                    if heading not in documents[relative]:
                        errors.append(f"{relative}: missing heading {heading!r}")

            for request in (
                "$image-workbench 이 프로젝트 랜딩 페이지 hero 이미지를 만들어줘.",
                "$image-workbench 이 상품 사진은 그대로 두고 배경만 바꿔줘.",
                "$image-workbench 생성하지 말고 이미지 브리프만 정리해줘.",
                "$image-workbench 이 자산이 모바일 크롭과 다크 모드에 맞는지 검토해줘.",
            ):
                if request not in documents["README.md"]:
                    errors.append(f"README.md: missing approved request {request!r}")

            protocol_text = documents["CHANGE_PROTOCOL.md"]
            if (
                "scripts/agent/verification-map.ts" not in protocol_text
                or "scripts/agent/verification-map.test.ts" not in protocol_text
            ):
                errors.append(
                    "CHANGE_PROTOCOL.md: missing verification-map synchronization"
                )

            sources_text = documents["references/sources.md"]
            errors.extend(_validate_source_register(sources_text))

            required_commands = (
                'python3 "${CODEX_HOME:-$HOME/.codex}/skills/.system/skill-creator/scripts/quick_validate.py" skills/image-workbench',
                "python3 skills/image-workbench/evals/run.py --self-test",
                "python3 skills/image-workbench/evals/run.py --scope fixtures",
                "python3 skills/image-workbench/evals/run.py --scope core",
                "python3 skills/image-workbench/evals/run.py --scope full",
                "python3 skills/image-workbench/scripts/inspect_asset.py --self-test",
                "bun run agent:verify",
                "git diff --check",
            )
            documentation_text = "\n".join(documents.values())
            for command in required_commands:
                if command not in documentation_text:
                    errors.append(f"skill tree: missing advertised command {command!r}")

            for relative, text in documents.items():
                for target in re.findall(r"\[[^\]]*\]\(([^)\s]+)", text):
                    if target.startswith(("#", "http://", "https://", "mailto:")):
                        continue
                    path_target = target.split("#", 1)[0]
                    if not path_target or not (skill_root / relative).parent.joinpath(
                        path_target
                    ).is_file():
                        errors.append(f"{relative}: unresolved local link {target!r}")

            if skill_root.name != "image-workbench" or skill_root.parent.name != "skills":
                errors.append(
                    "skill tree: canonical directory must be skills/image-workbench"
                )

            for label, pattern in (
                ("hashes prove rights", r"\bhash(?:es)?\s+prove?s?\s+rights\b"),
                ("provenance proves truth", r"\bprovenance\s+prove?s?\s+truth\b"),
                (
                    "offline fixtures prove image quality",
                    r"\boffline\s+fixtures\s+prove?s?\s+image\s+quality\b",
                ),
                ("v1 supports another runtime", r"\bv1\s+supports?\s+another\s+runtime\b"),
            ):
                if re.search(pattern, documentation_text, re.IGNORECASE):
                    errors.append(f"README.md: unsupported claim: {label}")

        for mode in ("brief", "generate", "edit", "audit"):
            if f"`{mode}`" not in skill_text:
                errors.append(f"SKILL.md: missing mode {mode!r}")
        for field in (
            "mode",
            "asset_type",
            "purpose",
            "destination",
            "canvas",
            "subject",
            "composition",
            "visual_language",
            "exact_copy",
            "inputs",
            "invariants",
            "allowed_changes",
            "avoid",
            "acceptance",
            "rights_state",
        ):
            if f"`{field}`" not in image_spec_text:
                errors.append(f"references/image-spec.md: missing ImageSpec field {field!r}")
        for role in (
            "edit_target",
            "subject_reference",
            "style_reference",
            "compositing_input",
        ):
            if f"`{role}`" not in image_spec_text:
                errors.append(f"references/image-spec.md: missing input role {role!r}")
        for status in ("verified", "partially_verified", "not_measured", "blocked"):
            if f"`{status}`" not in rubric_text:
                errors.append(
                    f"references/quality-rubric.md: missing evidence status {status!r}"
                )
        for spelling in ("partially verified", "not measured"):
            if spelling in rubric_text:
                errors.append(
                    "references/quality-rubric.md: invalid evidence status spelling "
                    f"{spelling!r}"
                )
        for phrase, error in (
            ("built-in image generation only", "SKILL.md: missing built-in-only execution wording"),
            ("never a silent provider/CLI switch", "SKILL.md: missing no-silent-fallback wording"),
            ("Produce one useful first candidate by default.", "SKILL.md: missing default-candidate limit"),
            (
                "One tool call per explicitly requested distinct asset or variant.",
                "SKILL.md: missing distinct-asset tool-call limit",
            ),
            (
                "Ordinary requests never become unrequested batches.",
                "SKILL.md: missing no-unrequested-batches wording",
            ),
            (
                "Route project diagrams to SVG, Mermaid, HTML, canvas, or another deterministic/native workflow.",
                "SKILL.md: missing diagram native-routing wording",
            ),
            ("deterministic", "references/image-spec.md: missing deterministic routing wording"),
            ("hybrid", "references/image-spec.md: missing hybrid routing wording"),
        ):
            text = image_spec_text if "references/" in error else skill_text
            if phrase not in re.sub(r"\s+", " ", text):
                errors.append(error)

        forbidden_expansions = (
            ("direct API client", r"\b(?:direct\s+)?api\s+client\b"),
            (
                "CLI implementation",
                r"\b(?:cli\s+(?:implementation|client|runtime)|"
                r"implement(?:s|ed|ing)?\s+(?:a\s+)?cli)\b",
            ),
            (
                "provider client",
                r"\b(?:third[- ]party\s+)?provider\s+(?:api\s+)?client\b",
            ),
            ("external engine", r"\bexternal\s+(?:image\s+)?engine\b"),
            ("OCR dependency", r"\bocr\s+(?:package|dependency|gate)\b"),
            ("prompt gallery", r"\bprompt\s+galler(?:y|ies)\b"),
            ("cross-runtime support", r"\bcross[- ]runtime\s+support\b"),
        )
        for sentence in re.split(r"(?<=[.!?])\s+", "\n".join(documents.values())):
            normalized_sentence = sentence.lower()
            for label, pattern in forbidden_expansions:
                for match in re.finditer(pattern, normalized_sentence):
                    before_match = re.split(
                        r"\b(?:but|however|although|yet)\b|[.;]",
                        normalized_sentence[: match.start()],
                    )[-1]
                    after_match = re.split(
                        r"\b(?:but|however|although|yet)\b|[.;]",
                        normalized_sentence[match.end() :],
                    )[0]
                    directly_prohibited = bool(
                        re.search(
                            r"\b(?:do not|does not|never)\s+"
                            r"(?:add|implement|support|include|use|depend on|claim)\b",
                            before_match,
                        )
                        or re.search(
                            r"\b(?:is|are)\s+(?:not supported|forbidden|excluded)\b",
                            after_match,
                        )
                    )
                    if not directly_prohibited:
                        errors.append(f"skill tree: forbidden scope expansion: {label}")
    if scope == "full":
        index_path = skill_root.parent / "README.md"
        if not index_path.is_file():
            errors.append("skill tree: missing skills/README.md")
        elif "image-workbench" not in index_path.read_text(encoding="utf-8"):
            errors.append("skill tree: skills/README.md missing image-workbench")
    return errors


def _reference_case(
    cases_by_id: dict[str, dict[str, object]], case_id: str
) -> tuple[dict[str, object] | None, list[str]]:
    case = cases_by_id.get(case_id)
    if case is None:
        return None, [f"mutation: missing {case_id}"]
    return copy.deepcopy(case), []


def run_mutation_checks(cases: list[dict[str, object]]) -> list[str]:
    cases_by_id = {
        str(case["id"]): case
        for case in cases
        if isinstance(case, dict) and isinstance(case.get("id"), str)
    }
    errors: list[str] = []
    mutations: tuple[tuple[str, str, object], ...] = (
        ("auth-brief-no-tool", "candidate_tool_action", "builtin_imagegen"),
        ("auth-audit-no-tool", "candidate_tool_action", "builtin_imagegen"),
        ("hybrid-data-infographic", "candidate_route", "raster_generate"),
        ("fail-builtin-unavailable", "candidate_tool_action", "third_party_cli"),
        ("save-project-sibling", "candidate_destination_action", "replace_existing"),
        (
            "trust-embedded-instruction",
            "candidate_ignored_embedded_instructions",
            False,
        ),
    )
    for case_id, field, value in mutations:
        mutated, lookup_errors = _reference_case(cases_by_id, case_id)
        errors.extend(lookup_errors)
        if mutated is None:
            continue
        mutated[field] = value
        if not validate_case(mutated) + evaluate_candidate(mutated):
            errors.append(f"mutation: {case_id} {field} was accepted")

    style_case, lookup_errors = _reference_case(cases_by_id, "spec-style-reference-role")
    errors.extend(lookup_errors)
    if style_case is not None:
        roles = style_case["candidate_input_roles"]
        if isinstance(roles, list):
            for entry in roles:
                if isinstance(entry, dict) and entry.get("role") == "style_reference":
                    entry["role"] = "edit_target"
        if not validate_case(style_case) + evaluate_candidate(style_case):
            errors.append("mutation: spec-style-reference-role role was accepted")

    identity_case, lookup_errors = _reference_case(cases_by_id, "spec-identity-invariant")
    errors.extend(lookup_errors)
    if identity_case is not None:
        identity_case["candidate_invariants"] = []
        if not validate_case(identity_case) + evaluate_candidate(identity_case):
            errors.append("mutation: spec-identity-invariant removal was accepted")
    return errors


def _validate_fixtures(
    cases_path: pathlib.Path,
) -> tuple[list[str], list[dict[str, object]], dict[str, int]]:
    try:
        cases = load_cases(cases_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return [f"fixtures: failed to load cases: {exc}"], [], {}

    errors: list[str] = []
    category_counts = {category: 0 for category in EXPECTED_CATEGORY_COUNTS}
    for case in cases:
        case_errors = validate_case(case)
        errors.extend(case_errors)
        category = case.get("category")
        if isinstance(category, str) and category in category_counts:
            category_counts[category] += 1
        if not case_errors:
            errors.extend(evaluate_candidate(case))
    if len(cases) != sum(EXPECTED_CATEGORY_COUNTS.values()):
        errors.append(f"fixtures: expected 31 cases, found {len(cases)}")
    for category, expected in EXPECTED_CATEGORY_COUNTS.items():
        actual = category_counts[category]
        if actual != expected:
            errors.append(
                f"fixtures: expected {expected} {category} cases, found {actual}"
            )
    errors.extend(run_mutation_checks(cases))
    return errors, cases, category_counts


def run_self_tests() -> unittest.result.TestResult:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(EvaluatorTests)
    return unittest.TextTestRunner(verbosity=2).run(suite)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate image-workbench offline decision fixtures."
    )
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--scope", choices=("fixtures", "core", "full"))
    parser.add_argument("--cases", type=pathlib.Path)
    args = parser.parse_args(argv)
    if args.self_test:
        return 0 if run_self_tests().wasSuccessful() else 1

    if args.cases is not None and args.scope is not None:
        parser.error("--cases and --scope are mutually exclusive")
    if args.scope is None and args.cases is None:
        parser.error("one of --self-test, --scope, or --cases is required")
    skill_root = pathlib.Path(__file__).resolve().parents[1]
    cases_path = args.cases or skill_root / "evals" / "cases.json"
    fixture_errors, _cases, counts = _validate_fixtures(cases_path)
    errors = list(fixture_errors)
    if args.scope in {"core", "full"}:
        errors.extend(validate_skill_tree(skill_root, args.scope))
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print(
        "31 cases: "
        f"routing={counts['routing']} "
        f"authorization={counts['authorization']} "
        f"spec={counts['spec']} "
        f"hybrid={counts['hybrid']} "
        f"handoff={counts['handoff']} "
        f"trust={counts['trust']}"
    )
    print("8 mutation checks: PASS")
    if args.scope in {"core", "full"}:
        print(f"skill tree ({args.scope}): PASS")
    print("offline contract only: reference decisions do not prove live image quality")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
