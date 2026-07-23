import dataclasses
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

from plan_runner.contracts import ExitCode  # noqa: E402
from plan_runner.helper import helper_client  # noqa: E402
from plan_runner.provider import ProviderOutcome  # noqa: E402
from plan_runner.runtime import RuntimeIdentity, RuntimeUnavailable  # noqa: E402
from plan_runner.engine import PlanRunner, RuntimePaths  # noqa: E402


def git(*arguments: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def init_repository(path: Path) -> str:
    path.mkdir()
    git("init", "-q", cwd=path)
    git("config", "user.name", "Engine Test", cwd=path)
    git("config", "user.email", "engine@example.test", cwd=path)
    (path / "README.md").write_text("base\n", encoding="utf-8")
    git("add", "README.md", cwd=path)
    git("commit", "-m", "base", cwd=path)
    return git("rev-parse", "HEAD", cwd=path)


def runtime_identity() -> RuntimeIdentity:
    return RuntimeIdentity(
        uv_version="uv test",
        implementation="cpython",
        python_version="3.13.9",
        executable=str(Path(sys.executable).resolve()),
        architecture="test",
        gil_disabled=False,
    )


class ScriptedAdapter:
    def __init__(self, owner, helper):
        self.owner = owner
        self.helper = helper

    def launch(self, request, _lease):
        packet = json.loads(request.prompt.split("\nEXECUTION_PACKET=", 1)[1])
        self.owner.packets.append(packet)
        launch = len(self.owner.packets)
        session_id = str(uuid.UUID(int=launch))
        if packet["mode"] == "implementation":
            marker = request.worktree / f"plan-{packet['current_plan']['index']}.txt"
            marker.write_text("implemented\n", encoding="utf-8")
            git("add", marker.name, cwd=request.worktree)
            git(
                "-c",
                "user.name=Engine Test",
                "-c",
                "user.email=engine@example.test",
                "commit",
                "-m",
                f"implement plan {packet['current_plan']['index']}",
                cwd=request.worktree,
            )
            head = git("rev-parse", "HEAD", cwd=request.worktree)
            result = {
                "status": "implemented",
                "head_commit": head,
                "summary": f"plan {packet['current_plan']['index']}",
                "task_ledger": [],
                "open_obligation_ids": [],
                "failure_signature": None,
                "strategy_note": None,
            }
            return ProviderOutcome(
                "implemented", 0, session_id, result, None, {}, (), ""
            )

        head = packet["candidate_head"]
        final_set = {
            "kind": "commands",
            "candidate_head": head,
            "commands": [
                {
                    "command_id": "final-smoke",
                    "command_role": "final",
                    "argv": [sys.executable, "-c", "print('ok')"],
                    "cwd": ".",
                    "input_digest": "a" * 64,
                    "deadline_seconds": 10,
                }
            ],
        }
        envelope = {
            "protocol_version": self.helper.protocol_version,
            "run_id": packet["run_id"],
            "nonce": self.helper.nonce,
            "operation": "declare_final_set",
            "payload": {"candidate_head": head, "final_set": final_set},
        }
        declaration = helper_client(
            self.helper.socket_path, self.helper.nonce, envelope
        )
        digest = declaration["artifact"]["digest"]
        envelope = {
            "protocol_version": self.helper.protocol_version,
            "run_id": packet["run_id"],
            "nonce": self.helper.nonce,
            "operation": "verify_final",
            "payload": {
                "candidate_head": head,
                "set_digest": digest,
                "command_index": 0,
            },
        }
        helper_client(self.helper.socket_path, self.helper.nonce, envelope)
        result = {
            "status": "reviewed",
            "review_head": head,
            "verification_set_digest": digest,
            "open_findings": [],
            "open_obligation_ids": [],
            "no_applicable_verification_approved": False,
            "summary": "whole branch reviewed",
        }
        return ProviderOutcome("reviewed", 0, session_id, result, None, {}, (), "")


class EngineTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.source = self.root / "source"
        self.starting_head = init_repository(self.source)
        self.specs = [self.root / "spec-b.md", self.root / "spec-a.md"]
        self.plans = [self.root / "plan-b.md", self.root / "plan-a.md"]
        for path in (*self.specs, *self.plans):
            path.write_text(path.name + "\n", encoding="utf-8")
        self.paths = RuntimePaths(
            state_home=self.root / "state",
            worktree_home=self.root / "worktrees",
            runner_script=SKILL_ROOT / "scripts" / "runner.py",
            skill_root=SKILL_ROOT,
        )
        self.packets = []
        self.output = []

    def tearDown(self):
        self.temporary.cleanup()

    def runner(self, runtime_checker=runtime_identity):
        return PlanRunner(
            self.paths,
            runtime_checker=runtime_checker,
            adapter_factory=lambda **values: ScriptedAdapter(
                self, values["helper"]
            ),
            output=self.output.append,
            environment={"PATH": os.environ["PATH"]},
        )

    def state(self):
        run_roots = list(self.paths.state_home.iterdir())
        self.assertEqual(len(run_roots), 1)
        return json.loads((run_roots[0] / "state.json").read_text(encoding="utf-8"))

    def test_runtime_paths_are_immutable(self):
        with self.assertRaises(dataclasses.FrozenInstanceError):
            self.paths.state_home = self.root / "other"

    def test_multiple_specs_and_plans_are_ordered_and_finalization_is_fresh(self):
        code = self.runner().create_run(
            specs=self.specs,
            plans=self.plans,
            workspace=self.source,
            stall_seconds=30,
            sandbox="workspace-write",
            model=None,
        )
        self.assertEqual(code, ExitCode.READY)
        implementations = [
            packet for packet in self.packets if packet["mode"] == "implementation"
        ]
        finalizations = [
            packet for packet in self.packets if packet["mode"] == "finalization"
        ]
        self.assertEqual(
            [[Path(spec["snapshot_path"]).name for spec in packet["specifications"]]
             for packet in implementations],
            [["spec-01.md", "spec-02.md"], ["spec-01.md", "spec-02.md"]],
        )
        self.assertEqual(
            [packet["current_plan"]["index"] for packet in implementations],
            [0, 1],
        )
        self.assertEqual(
            [packet["current_plan"]["total"] for packet in implementations],
            [2, 2],
        )
        self.assertEqual(len(finalizations), 1)
        all_text = json.dumps(implementations[0])
        self.assertNotIn("plan-02.md", all_text)
        state = self.state()
        self.assertEqual([plan["status"] for plan in state["plans"]],
                         ["implemented", "implemented"])
        self.assertEqual(state["status"], "ready_for_integration")
        self.assertEqual(state["integration"], "not_observed")
        self.assertEqual(
            [session["mode"] for session in state["sessions"]],
            ["implementation", "implementation", "finalization"],
        )
        self.assertEqual(len({item["session_id"] for item in state["sessions"]}), 3)

    def test_runtime_failure_blocks_before_worktree_or_provider(self):
        def unavailable():
            raise RuntimeUnavailable("runtime_incompatible")

        code = self.runner(unavailable).create_run(
            specs=self.specs,
            plans=self.plans,
            workspace=self.source,
            stall_seconds=30,
            sandbox="workspace-write",
            model=None,
        )
        self.assertEqual(code, ExitCode.BLOCKED)
        self.assertEqual(self.packets, [])
        self.assertFalse(self.paths.worktree_home.exists())
        blocked = json.loads(self.output[-1])
        self.assertEqual(blocked["reason_code"], "runtime_incompatible")

    def test_cli_invalid_retry_combination_uses_contract_exit_code(self):
        completed = subprocess.run(
            [
                sys.executable,
                str(SKILL_ROOT / "scripts" / "runner.py"),
                "resume",
                "--run-id",
                "missing-run",
                "--strategy-note",
                "changed approach",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, ExitCode.INVALID)
        self.assertEqual(
            json.loads(completed.stdout)["reason_code"], "invalid_invocation"
        )

    def test_inspect_is_read_only_and_concise(self):
        self.runner().create_run(
            specs=self.specs,
            plans=self.plans,
            workspace=self.source,
            stall_seconds=30,
            sandbox="workspace-write",
            model=None,
        )
        state = self.state()
        before = (self.paths.state_home / state["run_id"] / "state.json").read_bytes()
        self.output.clear()
        code = self.runner().inspect(state["run_id"])
        after = (self.paths.state_home / state["run_id"] / "state.json").read_bytes()
        self.assertEqual(code, ExitCode.READY)
        self.assertEqual(before, after)
        summary = json.loads(self.output[-1])
        self.assertEqual(
            set(summary),
            {"run_id", "status", "integration", "current_plan_index", "plan_count"},
        )


if __name__ == "__main__":
    unittest.main()
