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


class ContractVocabularyTest(unittest.TestCase):
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
        self.assertEqual(sorted(FAILURE_TAXONOMY), sorted(fixture["failure_taxonomy"]))
        self.assertEqual(RUNNER_RUNTIME_CONTRACT, fixture["runner_runtime"])
        self.assertEqual(
            {item.name.lower(): int(item) for item in ExitCode},
            fixture["exit_codes"],
        )

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
