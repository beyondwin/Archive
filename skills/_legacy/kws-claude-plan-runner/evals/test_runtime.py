import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from plan_runner.runtime import (  # noqa: E402
    UV_FIND_ARGV,
    RuntimeIdentity,
    RuntimeUnavailable,
    probe_runtime,
    require_compatible_runtime,
)


class ManagedRuntimeTest(unittest.TestCase):
    def test_lookup_is_managed_and_never_downloads(self):
        self.assertEqual(
            UV_FIND_ARGV,
            (
                "uv", "python", "find", "--managed-python",
                "--no-python-downloads", "--no-project", "--no-config",
                "--resolve-links", "3.13",
            ),
        )

    def test_probe_records_exact_running_interpreter(self):
        calls = []

        def fake(argv):
            calls.append(tuple(argv))
            return "uv 1.2.3" if argv == ["uv", "--version"] else sys.executable

        with patch("plan_runner.runtime._invoke_uv", side_effect=fake):
            identity = probe_runtime()
        self.assertEqual(identity.executable, str(Path(sys.executable).resolve()))
        self.assertEqual(identity.uv_version, "uv 1.2.3")
        self.assertEqual(calls[-1], UV_FIND_ARGV)
        self.assertFalse(identity.gil_disabled)

    def test_probe_fails_closed_when_uv_or_managed_python_is_missing(self):
        with patch("plan_runner.runtime._invoke_uv", side_effect=RuntimeUnavailable("runtime_missing")):
            with self.assertRaisesRegex(RuntimeUnavailable, "runtime_missing"):
                probe_runtime()
        with patch("plan_runner.runtime._invoke_uv", side_effect=["uv 1", ""]):
            with self.assertRaisesRegex(RuntimeUnavailable, "runtime_missing"):
                probe_runtime()

    def test_runtime_contract_rejects_wrong_builds(self):
        good = RuntimeIdentity("uv", "cpython", "3.13.14", "/managed/python", "arm64", False)
        self.assertIs(require_compatible_runtime(good), good)
        bad = [
            RuntimeIdentity("uv", "cpython", "3.12.9", "/p", "arm64", False),
            RuntimeIdentity("uv", "pypy", "3.13.1", "/p", "arm64", False),
            RuntimeIdentity("uv", "cpython", "3.13.1", "/p", "arm64", True),
        ]
        for identity in bad:
            with self.subTest(identity=identity):
                with self.assertRaisesRegex(RuntimeUnavailable, "runtime_incompatible"):
                    require_compatible_runtime(identity)

    def test_runtime_identity_does_not_claim_target_environment(self):
        self.assertNotIn(
            "environment",
            RuntimeIdentity("uv", "cpython", "3.13.14", "/p", "arm64", False).as_dict(),
        )


if __name__ == "__main__":
    unittest.main()
