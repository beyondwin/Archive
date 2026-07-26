import json
import sys
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from plan_runner.contracts import (  # noqa: E402
    CONTRACT_VERSION,
    FAILURE_TAXONOMY,
    FORMAT_VERSION,
    NEXT_STRATEGIES,
    PLAN_STATUSES,
    RUNNER_RUNTIME_CONTRACT,
    TASK_STATUSES,
    ExitCode,
    canonical_json,
    require_digest,
    require_full_sha,
    sha256_json,
)


class ContractPrimitivesTest(unittest.TestCase):
    def test_runtime_matches_versioned_test_contract(self):
        self.assertEqual(CONTRACT_VERSION, 2)
        self.assertEqual(FORMAT_VERSION, 2)
        self.assertEqual(
            PLAN_STATUSES,
            frozenset({"pending", "running", "implemented"}),
        )
        self.assertNotIn("reported_done", TASK_STATUSES)
        self.assertNotIn("review_failed", FAILURE_TAXONOMY)
        self.assertEqual(
            NEXT_STRATEGIES,
            frozenset({"resume_root", "fresh_root", "block"}),
        )
        self.assertEqual(
            RUNNER_RUNTIME_CONTRACT["requires_python"],
            ">=3.13,<3.14",
        )
        self.assertEqual(
            {item.name.lower(): int(item) for item in ExitCode}["ready"],
            0,
        )

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

    def test_json_digest_is_canonical_and_unicode_preserving(self):
        left = {"한글": [2, 1], "a": True}
        right = {"a": True, "한글": [2, 1]}
        self.assertEqual(canonical_json(left), canonical_json(right))
        self.assertEqual(sha256_json(left), sha256_json(right))
        self.assertIn("한글".encode(), canonical_json(left))

    def test_git_and_content_digests_are_strict(self):
        self.assertEqual(require_full_sha("a" * 40), "a" * 40)
        self.assertEqual(require_full_sha("b" * 64), "b" * 64)
        self.assertEqual(require_digest("c" * 64), "c" * 64)
        for invalid in ("", "a" * 39, "A" * 40, "g" * 64, 64):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    require_digest(invalid)

    def test_exit_values_are_stable(self):
        self.assertEqual(
            [int(item) for item in ExitCode],
            [0, 2, 3, 4, 64, 65, 70],
        )


if __name__ == "__main__":
    unittest.main()
