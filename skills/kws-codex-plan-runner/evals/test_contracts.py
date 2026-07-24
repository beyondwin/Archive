import json
import sys
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SKILL_ROOT.parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from plan_runner.contracts import (  # noqa: E402
    CONTRACT_VERSION,
    FAILURE_TAXONOMY,
    FORMAT_VERSION,
    NEXT_STRATEGIES,
    PLAN_STATUSES,
    RUNNER_RUNTIME_CONTRACT,
    RUN_STATUSES,
    TASK_STATUSES,
    ExitCode,
    canonical_json,
    require_digest,
    require_full_sha,
    sha256_json,
)
from plan_runner.git_ops import (  # noqa: E402
    VOLATILE_REF_POLICY_VERSION,
    is_volatile_ref,
)


class ContractVocabularyTest(unittest.TestCase):
    def test_permission_failures_have_distinct_terminal_reason_codes(self):
        self.assertIn("sandbox_capability_blocked", FAILURE_TAXONOMY)
        self.assertIn("host_permission_blocked", FAILURE_TAXONOMY)
        self.assertIn("provider_capability_blocked", FAILURE_TAXONOMY)

    def test_codex_output_schemas_use_supported_structured_output_subset(self):
        unsupported = {
            "allOf",
            "const",
            "dependentRequired",
            "dependentSchemas",
            "else",
            "if",
            "maxLength",
            "minLength",
            "not",
            "oneOf",
            "patternProperties",
            "then",
            "uniqueItems",
        }
        for name in ("plan-result.schema.json", "finalization-result.schema.json"):
            path = SKILL_ROOT / "templates" / name
            document = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(document.get("type"), "object", str(path))
            self.assertNotIn("anyOf", document, str(path))
            pending = [document]
            while pending:
                value = pending.pop()
                if isinstance(value, dict):
                    self.assertFalse(
                        unsupported.intersection(value),
                        f"{path}: {sorted(unsupported.intersection(value))}",
                    )
                    if value.get("type") == "object":
                        properties = value.get("properties")
                        if isinstance(properties, dict):
                            self.assertEqual(
                                set(value.get("required", [])),
                                set(properties),
                                str(path),
                            )
                            self.assertIs(value.get("additionalProperties"), False)
                    pending.extend(value.values())
                elif isinstance(value, list):
                    pending.extend(value)

    def test_provider_output_schemas_declare_items_for_every_array(self):
        for path in sorted((SKILL_ROOT / "templates").glob("*.schema.json")):
            document = json.loads(path.read_text(encoding="utf-8"))
            pending = [document]
            while pending:
                value = pending.pop()
                if isinstance(value, dict):
                    if value.get("type") == "array":
                        self.assertIn("items", value, str(path))
                    pending.extend(value.values())
                elif isinstance(value, list):
                    pending.extend(value)

    def test_runtime_matches_versioned_test_contract(self):
        fixture = json.loads(
            (REPO_ROOT / "scripts/agent/fixtures/plan-runner-contract-v1.json")
            .read_text(encoding="utf-8")
        )
        self.assertEqual(CONTRACT_VERSION, fixture["contract_version"])
        self.assertEqual(FORMAT_VERSION, fixture["state_format_version"])
        self.assertEqual(sorted(RUN_STATUSES), sorted(fixture["run_statuses"]))
        self.assertEqual(sorted(PLAN_STATUSES), sorted(fixture["plan_statuses"]))
        self.assertEqual(sorted(TASK_STATUSES), sorted(fixture["task_statuses"]))
        expected_failures = set(fixture["failure_taxonomy"])
        expected_failures.update(
            fixture["provider_failure_taxonomy_extensions"]["codex"]
        )
        self.assertEqual(sorted(FAILURE_TAXONOMY), sorted(expected_failures))
        self.assertEqual(sorted(NEXT_STRATEGIES), sorted(fixture["next_strategies"]))
        self.assertEqual(RUNNER_RUNTIME_CONTRACT, fixture["runner_runtime"])
        self.assertEqual(
            {item.name.lower(): int(item) for item in ExitCode},
            fixture["exit_codes"],
        )

    def test_versioned_contract_seals_the_volatile_ref_policy(self):
        fixture = json.loads(
            (REPO_ROOT / "scripts/agent/fixtures/plan-runner-contract-v1.json")
            .read_text(encoding="utf-8")
        )
        policy = fixture["volatile_ref_policy"]
        self.assertEqual(VOLATILE_REF_POLICY_VERSION, policy["version"])
        self.assertEqual(
            [
                "refs/codex/turn-diffs/captures/",
                "refs/codex/turn-diffs/checkpoints/",
            ],
            policy["prefixes"],
        )
        for prefix in policy["prefixes"]:
            with self.subTest(prefix=prefix):
                self.assertTrue(is_volatile_ref(f"{prefix}candidate"))
        for protected in (
            "refs/heads/main",
            "refs/tags/release",
            "refs/codex/other/candidate",
        ):
            with self.subTest(protected=protected):
                self.assertFalse(is_volatile_ref(protected))

    def test_canonical_digest_is_stable(self):
        left = {"b": [2, 1], "a": "value"}
        right = {"a": "value", "b": [2, 1]}
        self.assertEqual(canonical_json(left), canonical_json(right))
        self.assertEqual(sha256_json(left), sha256_json(right))

    def test_full_sha_and_digest_fail_closed(self):
        self.assertEqual(require_full_sha("a" * 40), "a" * 40)
        self.assertEqual(require_digest("b" * 64), "b" * 64)
        with self.assertRaisesRegex(ValueError, "full Git SHA"):
            require_full_sha("deadbeef")
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            require_digest("b" * 63)


if __name__ == "__main__":
    unittest.main()
