import sys
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from plan_runner.contracts import (  # noqa: E402
    ExitCode,
    canonical_json,
    require_digest,
    require_full_sha,
    sha256_json,
)


class ContractPrimitivesTest(unittest.TestCase):
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
