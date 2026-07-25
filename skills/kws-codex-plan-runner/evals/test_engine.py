from __future__ import annotations

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

from plan_runner import storage as storage_module  # noqa: E402
from plan_runner.contracts import ExitCode  # noqa: E402
from plan_runner.git_ops import GitIdentity  # noqa: E402
from plan_runner.helper import helper_client  # noqa: E402
from plan_runner.provider import ProviderOutcome  # noqa: E402
from plan_runner.runtime import RuntimeIdentity  # noqa: E402
from plan_runner.engine import PlanRunner, RuntimePaths  # noqa: E402


def git(*arguments: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *arguments], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def init_repository(path: Path) -> str:
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True)
    git("config", "user.name", "Engine Test", cwd=path)
    git("config", "user.email", "engine@example.test", cwd=path)
    (path / "README.md").write_text("base\n", encoding="utf-8")
    git("add", "README.md", cwd=path)
    git("commit", "-m", "base", cwd=path)
    return git("rev-parse", "HEAD", cwd=path)


def runtime_identity() -> RuntimeIdentity:
    return RuntimeIdentity(
        uv_version="uv test", implementation="cpython", python_version="3.13.9",
        executable=str(Path(sys.executable).resolve()), architecture="test", gil_disabled=False,
    )


class ScriptedAdapter:
    def __init__(self, owner, helper):
        self.owner = owner
        self.helper = helper

    def launch(self, request, lease, on_session_id=None, on_process_observation=None):
        self.owner.leases.append(lease)
        packet = json.loads(request.prompt.split("\nEXECUTION_PACKET=", 1)[1])
        self.owner.packets.append(packet)
        self.owner.requests.append(request)
        session_id = request.session_id or str(uuid.UUID(int=len(self.owner.requests)))
        if on_session_id is not None:
            on_session_id(session_id)
        if self.owner.outcome_hook is not None:
            outcome = self.owner.outcome_hook(self, request, packet, session_id)
            if outcome is not None:
                return outcome

        marker = request.worktree / f"plan-{packet['current_plan']['index']}.txt"
        marker.write_text("implemented\n", encoding="utf-8")
        git("add", marker.name, cwd=request.worktree)
        git("-c", "user.name=Engine Test", "-c", "user.email=engine@example.test", "commit", "-m", "implementation", cwd=request.worktree)
        head = git("rev-parse", "HEAD", cwd=request.worktree)
        prior = packet["prior_verification_sets"]
        if self.owner.prior_set_override == "drop":
            prior = []
        elif self.owner.prior_set_override == "reverse":
            prior = list(reversed(prior))
        declaration = helper_client(
            self.helper.socket_path, self.helper.nonce,
            {
                "protocol_version": self.helper.protocol_version,
                "run_id": packet["run_id"], "nonce": self.helper.nonce,
                "operation": "declare_verification",
                "payload": {
                    "candidate_head": head, "plan_index": packet["current_plan"]["index"],
                    "verification": {
                        "kind": "commands", "candidate_head": head,
                        "commands": [{
                            "command_id": f"handoff-{packet['current_plan']['index']}",
                            "command_role": "handoff", "argv": [sys.executable, "-c", "pass"],
                            "cwd": ".", "input_digest": "a" * 64, "deadline_seconds": 10,
                        }],
                    },
                    "prior_set_digests": prior, "is_final_plan": packet["is_final_plan"],
                },
            },
        )
        digest = declaration["artifact"]["digest"]
        helper_client(
            self.helper.socket_path, self.helper.nonce,
            {
                "protocol_version": self.helper.protocol_version,
                "run_id": packet["run_id"], "nonce": self.helper.nonce,
                "operation": "run_verification",
                "payload": {"candidate_head": head, "set_digest": digest, "command_index": 0, "deadline_seconds": 10},
            },
        )
        if self.owner.after_implementation_hook is not None:
            self.owner.after_implementation_hook(self, request, packet, session_id, head)
        return ProviderOutcome("implemented", 0, session_id, {
            "status": "implemented", "head_commit": head,
            "summary": f"plan {packet['current_plan']['index']}",
            "verification_set_digest": digest, "blocker": None,
        }, None, {}, (), "")


class EngineTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.source = self.root / "source"
        self.starting_head = init_repository(self.source)
        self.specs = [self.root / "spec.md"]
        self.plans = [self.root / "plan-a.md", self.root / "plan-b.md"]
        for path in (*self.specs, *self.plans):
            path.write_text(path.name + "\n", encoding="utf-8")
        self.paths = RuntimePaths(
            state_home=self.root / "state", worktree_home=self.root / "worktrees",
            runner_script=SKILL_ROOT / "scripts" / "runner.py", skill_root=SKILL_ROOT,
        )
        self.packets, self.requests, self.leases, self.output = [], [], [], []
        self.outcome_hook = None
        self.prior_set_override = None
        self.after_implementation_hook = None

    def tearDown(self):
        self.temporary.cleanup()

    def runner(self):
        return PlanRunner(
            self.paths, runtime_checker=runtime_identity,
            adapter_factory=lambda **values: ScriptedAdapter(self, values["helper"]),
            output=self.output.append, environment={"PATH": os.environ["PATH"]},
        )

    def create(self, plans=None):
        return self.runner().create_run(
            specs=self.specs, plans=plans or self.plans, workspace=self.source,
            stall_seconds=30, sandbox="workspace-write", model=None,
        )

    def state(self):
        roots = list(self.paths.state_home.iterdir())
        self.assertEqual(len(roots), 1)
        return json.loads((roots[0] / "state.json").read_text(encoding="utf-8"))

    def test_two_plans_use_two_root_controllers_and_final_plan_closes_run(self):
        self.assertEqual(self.create(), ExitCode.READY)
        self.assertEqual([packet["mode"] for packet in self.packets], ["implementation", "implementation"])
        state = self.state()
        self.assertEqual(state["status"], "ready_for_integration")
        self.assertNotIn("task_ledger", state)
        self.assertNotIn("finalization", state)
        self.assertTrue(all(session["mode"] == "implementation" for session in state["sessions"]))

    def test_invented_verification_digest_is_rejected(self):
        def invented(_adapter, request, _packet, session_id):
            marker = request.worktree / "invented.txt"
            marker.write_text("implemented\n", encoding="utf-8")
            git("add", marker.name, cwd=request.worktree)
            git("-c", "user.name=Engine Test", "-c", "user.email=engine@example.test", "commit", "-m", "invented", cwd=request.worktree)
            return ProviderOutcome("implemented", 0, session_id, {
                "status": "implemented", "head_commit": git("rev-parse", "HEAD", cwd=request.worktree),
                "summary": "invented", "verification_set_digest": "a" * 64, "blocker": None,
            }, None, {}, (), "")

        self.outcome_hook = invented
        self.assertEqual(self.create(self.plans[:1]), ExitCode.INTEGRITY)

    def test_active_recovery_uses_only_v2_progress_facts(self):
        self.outcome_hook = lambda _a, _r, _p, session: ProviderOutcome("failed", 1, session, None, "transport_closed", {}, (), "")
        self.assertEqual(self.create(self.plans[:1]), ExitCode.FAILED)
        self.assertNotIn("task_ledger", self.state())

    def test_active_recovery_resumes_then_uses_fresh_session_then_exhausts(self):
        self.outcome_hook = lambda _a, _r, _p, session: ProviderOutcome("failed", 1, session, None, "transport_closed", {}, (), "")
        self.assertEqual(self.create(self.plans[:1]), ExitCode.FAILED)
        self.assertEqual([request.session_id for request in self.requests], [None, str(uuid.UUID(int=1)), None])
        self.assertEqual(self.state()["failure"]["reason_code"], "recovery_exhausted")

    def test_launch_lease_starts_at_current_monotonic_time(self):
        self.assertEqual(self.create(), ExitCode.READY)
        self.assertTrue(all(not lease.expired(time.monotonic()) for lease in self.leases))

    def test_final_union_rejects_incomplete_runner_owned_prior_sets(self):
        self.prior_set_override = "drop"
        self.assertEqual(self.create(), ExitCode.INTEGRITY)
        self.assertEqual(self.state()["plans"][0]["status"], "implemented")

    def test_final_union_rejects_reordered_runner_owned_prior_sets(self):
        third = self.root / "plan-c.md"
        third.write_text("plan-c\n", encoding="utf-8")
        self.prior_set_override = "reverse"
        self.assertEqual(self.create([*self.plans, third]), ExitCode.INTEGRITY)
        self.assertEqual([plan["status"] for plan in self.state()["plans"][:2]], ["implemented", "implemented"])

    def test_protected_ref_drift_after_provider_handoff_fails_closed(self):
        self.after_implementation_hook = lambda _a, request, _p, _s, head: git("update-ref", "refs/tags/provider-drift", head, cwd=request.worktree)
        self.assertEqual(self.create(self.plans[:1]), ExitCode.INTEGRITY)

    def test_version_one_is_inspect_only(self):
        self.assertEqual(self.create(), ExitCode.READY)
        state = self.state()
        root = self.paths.state_home / state["run_id"]
        state["format_version"] = 1
        state["contract_version"] = 1
        state["state_digest"] = storage_module._state_digest(state)
        state_path = root / "state.json"
        state_path.write_bytes(storage_module.canonical_json(state))
        before, metadata = state_path.read_bytes(), state_path.stat()
        self.assertEqual(self.runner().inspect(state["run_id"]), ExitCode.READY)
        self.assertEqual(state_path.read_bytes(), before)
        after = state_path.stat()
        self.assertEqual((after.st_ino, after.st_size, after.st_mtime_ns), (metadata.st_ino, metadata.st_size, metadata.st_mtime_ns))
        self.assertEqual(self.runner().resume(state["run_id"], retry_blocked=False, retry_failed=False, strategy_note=None), ExitCode.INVALID)


if __name__ == "__main__":
    unittest.main()
