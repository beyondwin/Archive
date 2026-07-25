import hashlib
import json
import os
import socket
import stat
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from plan_runner.evidence import ExactCommand, VerificationReceipt  # noqa: E402
from plan_runner import helper as helper_module  # noqa: E402
from plan_runner.helper import (  # noqa: E402
    MAX_MESSAGE_BYTES,
    HelperServer,
    _ProtocolError,
    _read_line,
    helper_client,
)
from plan_runner.storage import ArtifactRef  # noqa: E402


RUN_ID = "helper-12345678-1234-4234-8234-123456789abc"
HEAD = "a" * 40
DIGEST = "b" * 64


class RecordingEvidence:
    def __init__(self):
        self.executed = []
        self.declarations = []
        self.liveness = []
        self.started = threading.Event()
        self.release = threading.Event()
        self.block = False

    def execute(self, command, *, candidate_head):
        self.started.set()
        if self.block:
            self.release.wait(2)
        self.executed.append((command, candidate_head))
        return VerificationReceipt(
            ArtifactRef("verification_receipt", DIGEST, f"artifacts/verification_receipt/{DIGEST}.json"),
            DIGEST,
            "success",
            0,
            False,
        )

    def declare_verification(self, payload, candidate_head, *, plan_index, prior_set_digests, is_final_plan):
        self.declarations.append((payload, candidate_head))
        return ArtifactRef("plan_verification_set", DIGEST, f"artifacts/plan_verification_set/{DIGEST}.json")

    def load_verification_command(self, set_digest, index):
        if set_digest != DIGEST or index != 0:
            raise ValueError("verification command index is unavailable")
        return ExactCommand("focused-1", "handoff", (sys.executable, "-c", "pass"), ".", DIGEST, 3)

    def record_liveness(self, sample):
        self.liveness.append(dict(sample))


class HelperProtocolTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.worktree = Path(self.temporary.name) / "worktree"
        self.worktree.mkdir(mode=0o700)
        self.evidence = RecordingEvidence()
        self.server = HelperServer(
            run_id=RUN_ID,
            worktree=self.worktree,
            evidence_store=self.evidence,
            client_argv=(sys.executable,),
        )

    def tearDown(self):
        self.temporary.cleanup()

    def envelope(self, operation, payload):
        return {
            "protocol_version": 1,
            "run_id": RUN_ID,
            "nonce": self.server.descriptor.nonce,
            "operation": operation,
            "payload": payload,
        }

    def focused_payload(self):
        return {
            "candidate_head": HEAD,
            "command": {
                "command_id": "focused-1",
                "command_role": "focused",
                "argv": [sys.executable, "-c", "pass"],
                "cwd": ".",
                "input_digest": DIGEST,
                "deadline_seconds": 3,
            },
        }

    def raw_request(self, document, *, disconnect=False):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.connect(str(self.server.descriptor.socket_path))
            client.sendall(json.dumps(document, sort_keys=True, separators=(",", ":")).encode() + b"\n")
            client.shutdown(socket.SHUT_WR)
            if disconnect:
                return None
            response = b""
            while not response.endswith(b"\n"):
                block = client.recv(4096)
                if not block:
                    break
                response += block
            return json.loads(response)

    def test_context_creates_private_direct_child_socket_and_descriptor(self):
        with self.server:
            descriptor = self.server.descriptor
            self.assertEqual(descriptor.socket_path, self.worktree / ".kws-plan-runner.sock")
            self.assertTrue(descriptor.socket_path.is_socket())
            self.assertEqual(stat.S_IMODE(descriptor.socket_path.stat().st_mode), 0o600)
            self.assertEqual(len(descriptor.nonce), 64)
            self.assertEqual(int(descriptor.nonce, 16), int(descriptor.nonce, 16))
            self.assertTrue(all(Path(value).is_absolute() for value in descriptor.client_argv))
            self.assertEqual(self.server.active_command_deadline, None)
        self.assertFalse((self.worktree / ".kws-plan-runner.sock").exists())
        self.assertFalse(self.server.server_thread.is_alive())

    def test_rejects_invalid_envelopes_without_calling_evidence(self):
        cases = [
            (dict(self.envelope("verify_focused", self.focused_payload()), nonce="0" * 64), "forbidden"),
            (dict(self.envelope("verify_focused", self.focused_payload()), run_id="other-12345678-1234-4234-8234-123456789abc"), "forbidden"),
            (self.envelope("not_real", {}), "unknown_operation"),
            (dict(self.envelope("verify_focused", self.focused_payload()), extra=True), "invalid_request"),
            (self.envelope("verify_focused", {**self.focused_payload(), "command": {**self.focused_payload()["command"], "cwd": "../escape"}}), "invalid_request"),
        ]
        with self.server:
            for document, code in cases:
                with self.subTest(code=code):
                    response = self.raw_request(document)
                    self.assertFalse(response["ok"])
                    self.assertEqual(response["error_code"], code)
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.connect(str(self.server.descriptor.socket_path))
                client.sendall(b"{" + b"x" * MAX_MESSAGE_BYTES)
                self.assertEqual(json.loads(client.recv(4096))["error_code"], "request_too_large")
        self.assertEqual(self.evidence.executed, [])
        self.assertEqual(self.evidence.declarations, [])

    def test_verify_focused_executes_the_exact_submitted_argv(self):
        with self.server:
            response = helper_client(self.server.descriptor.socket_path, self.server.descriptor.nonce, self.envelope("verify_focused", self.focused_payload()))
        self.assertTrue(response["ok"])
        command, head = self.evidence.executed[0]
        self.assertEqual(command.argv, tuple(self.focused_payload()["command"]["argv"]))
        self.assertEqual(head, HEAD)
        self.assertEqual(response["artifact"]["digest"], DIGEST)

    def test_client_waits_through_declared_command_deadline_without_orphaning_server(self):
        self.evidence.block = True
        original_timeout = helper_module._CLIENT_TIMEOUT_SECONDS
        helper_module._CLIENT_TIMEOUT_SECONDS = 0.02
        releaser = threading.Thread(
            target=lambda: (time.sleep(0.08), self.evidence.release.set())
        )
        try:
            with self.server:
                releaser.start()
                response = helper_client(
                    self.server.descriptor.socket_path,
                    self.server.descriptor.nonce,
                    self.envelope("verify_focused", self.focused_payload()),
                )
                self.assertTrue(response["ok"])
            releaser.join(1)
            self.assertFalse(self.server.server_thread.is_alive())
        finally:
            helper_module._CLIENT_TIMEOUT_SECONDS = original_timeout
            self.evidence.release.set()
            releaser.join(1)

    def test_plan_and_run_verification_use_one_helper_path(self):
        declaration = {"candidate_head": HEAD, "kind": "commands", "commands": [{**self.focused_payload()["command"], "command_role": "handoff"}]}
        with self.server:
            first = self.raw_request(self.envelope("declare_verification", {"candidate_head": HEAD, "plan_index": 0, "verification": declaration, "prior_set_digests": [], "is_final_plan": False}))
            second = self.raw_request(self.envelope("declare_verification", {"candidate_head": HEAD, "plan_index": 0, "verification": declaration, "prior_set_digests": [], "is_final_plan": False}))
            mismatch = self.raw_request(self.envelope("run_verification", {"candidate_head": "c" * 40, "set_digest": DIGEST, "command_index": 0, "deadline_seconds": 3}))
            self.assertFalse(mismatch["ok"])
            self.assertEqual(mismatch["error_code"], "candidate_head_mismatch")
            self.assertEqual(self.evidence.executed, [])
            final = self.raw_request(self.envelope("run_verification", {"candidate_head": HEAD, "set_digest": DIGEST, "command_index": 0, "deadline_seconds": 3}))
        self.assertTrue(first["ok"])
        self.assertFalse(second["ok"])
        self.assertEqual(second["error_code"], "verification_set_sealed")
        self.assertTrue(final["ok"])
        self.assertEqual(len(self.evidence.declarations), 1)
        self.assertEqual(self.evidence.executed[-1][0].command_id, "focused-1")

    def test_trickled_request_has_one_total_deadline(self):
        class Clock:
            def __init__(self):
                self.values = iter((0.0, 0.5, 1.0, 1.5))

            def __call__(self):
                return next(self.values)

        class TricklingSocket:
            def __init__(self):
                self.timeouts = []

            def settimeout(self, value):
                self.timeouts.append(value)

            def recv(self, _size):
                return b"x"

        with self.assertRaises(_ProtocolError) as raised:
            _read_line(TricklingSocket(), deadline=1.0, clock=Clock())
        self.assertEqual(raised.exception.code, "request_timeout")

    def test_shutdown_join_is_bounded_when_command_is_stuck(self):
        self.evidence.block = True
        server = HelperServer(
            run_id=RUN_ID,
            worktree=self.worktree,
            evidence_store=self.evidence,
            client_argv=(sys.executable,),
            io_timeout_seconds=0.05,
            shutdown_timeout_seconds=0.01,
        )
        server.__enter__()
        try:
            request = self.envelope("verify_focused", self.focused_payload())
            request["nonce"] = server.descriptor.nonce
            request["payload"]["command"]["deadline_seconds"] = 0.05
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.connect(str(server.descriptor.socket_path))
                client.sendall(json.dumps(request, sort_keys=True, separators=(",", ":")).encode() + b"\n")
                client.shutdown(socket.SHUT_WR)
            self.assertTrue(self.evidence.started.wait(1))
            with self.assertRaisesRegex(RuntimeError, "shutdown timed out"):
                server.__exit__(None, None, None)
            self.assertFalse(server.descriptor.socket_path.exists())
        finally:
            self.evidence.release.set()
            server.__exit__(None, None, None)

    def test_liveness_is_observable_without_executing_verification(self):
        with self.server:
            response = self.raw_request(self.envelope("record_liveness", {"sample": {"session": "alive"}}))
        self.assertTrue(response["ok"])
        self.assertEqual(self.evidence.liveness, [{"session": "alive"}])
        self.assertEqual(self.evidence.executed, [])

    def test_client_disconnect_does_not_cancel_or_duplicate_running_command(self):
        self.evidence.block = True
        with self.server:
            self.raw_request(self.envelope("verify_focused", self.focused_payload()), disconnect=True)
            self.assertTrue(self.evidence.started.wait(1))
            self.assertIsNotNone(self.server.active_command_deadline)
            self.evidence.release.set()
            for _ in range(100):
                if self.evidence.executed:
                    break
                time.sleep(0.01)
        self.assertEqual(len(self.evidence.executed), 1)

    def test_idle_connection_gets_a_bounded_timeout_error(self):
        server = HelperServer(
            run_id=RUN_ID,
            worktree=self.worktree,
            evidence_store=self.evidence,
            client_argv=(sys.executable,),
            io_timeout_seconds=0.05,
        )
        with server, socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.connect(str(server.descriptor.socket_path))
            response = json.loads(client.recv(4096))
        self.assertFalse(response["ok"])
        self.assertEqual(response["error_code"], "request_timeout")

    def test_plan_result_schema_is_closed_and_requires_handoff_evidence(self):
        schema = json.loads((SKILL_ROOT / "templates" / "plan-result.schema.json").read_text(encoding="utf-8"))
        self.assertFalse(schema["additionalProperties"])
        self.assertIn("verification_set_digest", schema["properties"])
        self.assertIn("verification_set_digest", schema["required"])
        self.assertIn("head_commit", schema["required"])


if __name__ == "__main__":
    unittest.main()
