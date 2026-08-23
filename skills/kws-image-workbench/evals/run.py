#!/usr/bin/env python3
"""Offline decision-contract evaluator for kws-image-workbench."""

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


class EvaluatorTests(unittest.TestCase):
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

    def test_full_scope_requires_readme(self):
        with tempfile.TemporaryDirectory() as directory:
            errors = validate_skill_tree(pathlib.Path(directory), "full")
        self.assertIn("skill tree: missing README.md", errors)


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
EXPECTED_CATEGORY_COUNTS = {
    "routing": 8,
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
    if scope == "full":
        index_path = skill_root.parent / "README.md"
        if not index_path.is_file():
            errors.append("skill tree: missing skills/README.md")
        elif "kws-image-workbench" not in index_path.read_text(encoding="utf-8"):
            errors.append("skill tree: skills/README.md missing kws-image-workbench")
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
        errors.append(f"fixtures: expected 30 cases, found {len(cases)}")
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
        description="Evaluate kws-image-workbench offline decision fixtures."
    )
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--scope", choices=("fixtures", "core", "full"))
    args = parser.parse_args(argv)
    if args.self_test:
        return 0 if run_self_tests().wasSuccessful() else 1

    if args.scope is None:
        parser.error("one of --self-test or --scope is required")
    skill_root = pathlib.Path(__file__).resolve().parents[1]
    fixture_errors, _cases, counts = _validate_fixtures(skill_root / "evals" / "cases.json")
    errors = list(fixture_errors)
    if args.scope in {"core", "full"}:
        errors.extend(validate_skill_tree(skill_root, args.scope))
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print(
        "30 cases: "
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
