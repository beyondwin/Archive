import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from plan_runner.contracts import canonical_json, sha256_json  # noqa: E402
from plan_runner.evidence import EvidenceStore  # noqa: E402
from plan_runner.git_ops import GitWorkspace  # noqa: E402
from plan_runner.helper import HelperServer, helper_client  # noqa: E402
from plan_runner.storage import StateStore  # noqa: E402


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class ParentHelperTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name).resolve()
        self.source = self.base / "source"
        self.source.mkdir()
        git(self.source, "init")
        git(self.source, "config", "user.email", "tests@example.invalid")
        git(self.source, "config", "user.name", "Claude Runner")
        (self.source / "file").write_text("x")
        git(self.source, "add", ".")
        git(self.source, "commit", "-m", "base")
        self.head = git(self.source, "rev-parse", "HEAD")
        self.run_id = f"helper-{uuid.uuid4()}"
        self.worktree = self.base / "worktree"
        self.workspace = GitWorkspace.create(self.source, self.worktree, f"claude-plan/{self.run_id}")
        spec, plan = self.base / "spec.md", self.base / "plan.md"
        spec.write_text("s")
        plan.write_text("p")
        state_root = self.base / "state" / self.run_id
        state_root.parent.mkdir(mode=0o700)
        self.state = StateStore.create(
            root=state_root, provider="claude", run_id=self.run_id,
            source_repository=self.source, source_commit=self.head,
            worktree=self.worktree, branch=f"claude-plan/{self.run_id}",
            specs=[spec], plans=[plan], immutable_config={}, runner_runtime={},
        )
        self.evidence = EvidenceStore(
            self.state, self.workspace, {"PATH": os.environ.get("PATH", "")}
        )

    def tearDown(self):
        self.temp.cleanup()

    def envelope(self, descriptor, operation, payload):
        return {
            "protocol_version": descriptor.protocol_version,
            "run_id": self.run_id,
            "nonce": descriptor.nonce,
            "operation": operation,
            "payload": payload,
        }

    def command(self, role):
        return {
            "command_id": f"{role}-1",
            "command_role": role,
            "argv": [sys.executable, "-c", "print('verified')"],
            "cwd": ".",
            "input_digest": sha256_json({"role": role}),
            "deadline_seconds": 3,
        }

    def test_private_socket_executes_focused_command_and_tracks_deadline_callbacks(self):
        started, finished = [], []
        with HelperServer(
            run_id=self.run_id, worktree=self.worktree,
            evidence_store=self.evidence,
            client_argv=(sys.executable, str((SKILL_ROOT / "scripts" / "runner.py").absolute())),
            state_store=self.state,
            on_command_started=started.append,
            on_command_finished=finished.append,
        ) as server:
            descriptor = server.descriptor
            self.assertEqual(descriptor.socket_path.parent, self.worktree)
            self.assertEqual(descriptor.socket_path.stat().st_mode & 0o777, 0o600)
            response = helper_client(
                descriptor.socket_path,
                descriptor.nonce,
                self.envelope(
                    descriptor,
                    "verify_focused",
                    {"candidate_head": self.head, "command": self.command("focused")},
                ),
            )
            self.assertTrue(response["ok"])
        self.assertEqual(len(started), 1)
        self.assertEqual(len(finished), 1)
        self.assertFalse(descriptor.socket_path.exists())

    def test_final_declaration_seals_exact_set_and_index(self):
        with HelperServer(
            run_id=self.run_id, worktree=self.worktree,
            evidence_store=self.evidence,
            client_argv=(sys.executable, "/absolute/runner.py"),
            state_store=self.state,
        ) as server:
            d = server.descriptor
            final_set = {
                "kind": "commands",
                "candidate_head": self.head,
                "commands": [self.command("final")],
            }
            declared = helper_client(
                d.socket_path, d.nonce,
                self.envelope(d, "declare_final_set", {"candidate_head": self.head, "final_set": final_set}),
            )
            digest = declared["artifact"]["digest"]
            verified = helper_client(
                d.socket_path, d.nonce,
                self.envelope(
                    d, "verify_final",
                    {
                        "candidate_head": self.head,
                        "set_digest": digest,
                        "command_index": 0,
                        "deadline_seconds": 3,
                    },
                ),
            )
            self.assertTrue(verified["ok"])
            with self.assertRaises(RuntimeError):
                helper_client(
                    d.socket_path, d.nonce,
                    self.envelope(d, "declare_final_set", {"candidate_head": self.head, "final_set": final_set}),
                )

    def test_wrong_nonce_noncanonical_and_heartbeat_do_not_execute_commands(self):
        with HelperServer(
            run_id=self.run_id, worktree=self.worktree,
            evidence_store=self.evidence,
            client_argv=(sys.executable, "/absolute/runner.py"),
            state_store=self.state,
        ) as server:
            d = server.descriptor
            request = self.envelope(d, "record_liveness", {"sample": {"pid": 42, "phase": "alive"}})
            response = helper_client(d.socket_path, d.nonce, request)
            self.assertTrue(response["ok"])
            refs = self.state.snapshot()["artifact_refs"]
            self.assertEqual([r["kind"] for r in refs], ["liveness_sample"])
            bad = dict(request)
            bad["nonce"] = "0" * 64
            with self.assertRaises(RuntimeError):
                helper_client(d.socket_path, "0" * 64, bad)

    def test_schema_is_closed_and_supports_commands_or_rationale(self):
        schema = json.loads(
            (SKILL_ROOT / "templates" / "final-verification-set.schema.json").read_text()
        )
        self.assertFalse(schema["additionalProperties"])
        kinds = {
            branch["properties"]["kind"]["const"]
            for branch in schema["oneOf"]
        }
        self.assertEqual(kinds, {"commands", "no_applicable_verification"})


if __name__ == "__main__":
    unittest.main()
