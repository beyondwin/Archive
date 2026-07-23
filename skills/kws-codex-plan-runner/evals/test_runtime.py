import dataclasses
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from plan_runner import runtime  # noqa: E402


class ManagedRuntimeTest(unittest.TestCase):
    def _identity(self, **overrides):
        values = {
            "uv_version": "uv 0.7.1",
            "implementation": "cpython",
            "python_version": "3.13.14",
            "executable": "/tmp/managed-python",
            "architecture": "arm64",
            "gil_disabled": False,
        }
        values.update(overrides)
        return runtime.RuntimeIdentity(**values)

    def test_probe_reports_runtime_missing_when_uv_is_unavailable(self):
        with mock.patch.object(runtime.subprocess, "run", side_effect=FileNotFoundError):
            with self.assertRaisesRegex(runtime.RuntimeUnavailable, "runtime_missing"):
                runtime.probe_runtime()

    def test_probe_reports_runtime_missing_when_uv_finds_no_interpreter(self):
        responses = [
            subprocess.CompletedProcess(["uv", "--version"], 0, "uv 0.7.1\n", ""),
            subprocess.CompletedProcess(["uv", "python", "find"], 0, "\n", ""),
        ]
        with mock.patch.object(runtime.subprocess, "run", side_effect=responses):
            with self.assertRaisesRegex(runtime.RuntimeUnavailable, "runtime_missing"):
                runtime.probe_runtime()

    def test_require_compatible_runtime_rejects_incompatible_interpreters(self):
        cases = (
            self._identity(implementation="pypy"),
            self._identity(python_version="3.12.9"),
            self._identity(python_version="3.14.0"),
            self._identity(gil_disabled=True),
        )
        for identity in cases:
            with self.subTest(identity=identity):
                with self.assertRaisesRegex(runtime.RuntimeUnavailable, "runtime_incompatible"):
                    runtime.require_compatible_runtime(identity)

    def test_probe_records_managed_cpython_runtime_and_exact_uv_find_argv(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "python3.13"
            executable.touch()
            find_argv = [
                "uv",
                "python",
                "find",
                "--managed-python",
                "--no-python-downloads",
                "--no-project",
                "--no-config",
                "--resolve-links",
                "3.13",
            ]
            responses = [
                subprocess.CompletedProcess(["uv", "--version"], 0, "uv 0.7.1\n", ""),
                subprocess.CompletedProcess(find_argv, 0, f"{executable}\n", ""),
            ]
            with (
                mock.patch.object(runtime.subprocess, "run", side_effect=responses) as run,
                mock.patch.object(runtime.sys, "executable", str(executable)),
                mock.patch.object(
                    runtime.sys,
                    "implementation",
                    SimpleNamespace(name="cpython"),
                ),
                mock.patch.object(
                    runtime.sys,
                    "version_info",
                    SimpleNamespace(major=3, minor=13, micro=14),
                ),
                mock.patch.object(runtime.platform, "machine", return_value="arm64"),
                mock.patch.object(runtime.sysconfig, "get_config_var", return_value=0),
            ):
                identity = runtime.require_compatible_runtime()

            self.assertEqual(
                identity,
                self._identity(executable=str(executable.resolve())),
            )
            self.assertEqual(
                [call.args[0] for call in run.call_args_list],
                [["uv", "--version"], find_argv],
            )
            self.assertTrue(all(call.kwargs.get("shell") is not True for call in run.call_args_list))

    def test_probe_rejects_a_managed_executable_other_than_running_python(self):
        responses = [
            subprocess.CompletedProcess(["uv", "--version"], 0, "uv 0.7.1\n", ""),
            subprocess.CompletedProcess(
                ["uv", "python", "find"], 0, "/tmp/other-python\n", ""
            ),
        ]
        with (
            mock.patch.object(runtime.subprocess, "run", side_effect=responses),
            mock.patch.object(runtime.sys, "executable", "/tmp/running-python"),
        ):
            with self.assertRaisesRegex(runtime.RuntimeUnavailable, "runtime_incompatible"):
                runtime.probe_runtime()

    def test_runtime_metadata_serializes_without_target_environment_fingerprint(self):
        metadata = dataclasses.asdict(self._identity())
        target_environment_fingerprint = {"python": "3.12", "dependencies": "other"}
        receipt = {
            "runtime": metadata,
            "verification_environment": target_environment_fingerprint,
        }

        self.assertEqual(metadata, dataclasses.asdict(self._identity()))
        self.assertNotIn("verification_environment", metadata)
        self.assertEqual(json.loads(json.dumps(receipt))["runtime"], metadata)


if __name__ == "__main__":
    unittest.main()
