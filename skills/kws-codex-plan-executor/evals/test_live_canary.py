"""Focused contract tests for bounded live-canary diagnostics."""

from __future__ import annotations

import hashlib
import unittest
from unittest import mock

from evals import live_canary


class LiveCanaryDiagnosticTests(unittest.TestCase):
    def test_prefixed_environment_assignments_are_redacted(self) -> None:
        output = (
            b"OPENAI_API_KEY=plain-secret-value-123456 "
            b"GITHUB_TOKEN=ghp_live-secret-value-987654\n"
        )

        message = live_canary.diagnostic_stream("stdout", output)

        self.assertNotIn("plain-secret-value-123456", message)
        self.assertNotIn("ghp_live-secret-value-987654", message)
        self.assertEqual(message.count("[REDACTED]"), 2)

    def test_secret_starting_before_diagnostic_tail_has_no_visible_suffix(
        self,
    ) -> None:
        secret_suffix = "boundary-secret-suffix-987654"
        output = (
            b"provider-error "
            + ("sk-" + "A" * 220 + secret_suffix).encode("ascii")
            + b"\n"
        )

        message = live_canary.diagnostic_stream("stderr", output)

        self.assertNotIn(secret_suffix, message)
        self.assertIn("[REDACTED]", message)

    def test_unexpected_exit_surfaces_bounded_redacted_process_evidence(self) -> None:
        stdout = (
            b"X" * 2_000
            + b'\nstdout-tail marker sk-live-secret-1234567890 '
            + b'"api_key": "json-secret-987654"\n'
        )
        stderr = (
            b"Y" * 2_000
            + b"\nstderr-tail marker Bearer live-bearer-secret\n"
        )
        result = live_canary.CommandResult(17, stdout, stderr)

        with mock.patch.object(live_canary, "run", return_value=result):
            with self.assertRaises(live_canary.CanaryError) as raised:
                live_canary.invoke_cpe({}, "run", expected_exit=0)

        message = str(raised.exception)
        self.assertIn("expected=0", message)
        self.assertIn("actual=17", message)
        self.assertIn(f"stdout_bytes={len(stdout)}", message)
        self.assertIn(
            f"stdout_sha256={hashlib.sha256(stdout).hexdigest()}",
            message,
        )
        self.assertIn("stdout-tail marker [REDACTED]", message)
        self.assertIn(f"stderr_bytes={len(stderr)}", message)
        self.assertIn(
            f"stderr_sha256={hashlib.sha256(stderr).hexdigest()}",
            message,
        )
        self.assertIn("stderr-tail marker [REDACTED]", message)
        self.assertNotIn("sk-live-secret-1234567890", message)
        self.assertNotIn("json-secret-987654", message)
        self.assertNotIn("live-bearer-secret", message)
        self.assertLessEqual(len(message.encode("utf-8")), 1_000)


if __name__ == "__main__":
    unittest.main(verbosity=2)
