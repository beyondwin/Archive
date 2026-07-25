from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from plan_runner import storage as storage_module  # noqa: E402
from plan_runner.contracts import ExitCode  # noqa: E402
from plan_runner.engine import PlanRunner, RuntimePaths  # noqa: E402
from plan_runner.helper import helper_client  # noqa: E402
from plan_runner.provider import ProviderOutcome  # noqa: E402
from plan_runner.runtime import RuntimeIdentity  # noqa: E402


class SimulatedCrash(BaseException):
    pass


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


class ScriptedClaudeAdapter:
    def __init__(self, owner, helper):
        self.owner = owner
        self.helper = helper

    def launch(
        self,
        request,
        lease,
        on_session_id=None,
    ):
        self.owner.leases.append(lease)
        packet = json.loads(
            request.prompt.split("\nEXECUTION_PACKET=", 1)[1]
        )
        self.owner.packets.append(packet)
        self.owner.requests.append(request)
        session_id = request.session_id
        if on_session_id is not None:
            on_session_id(session_id)
        if self.owner.crash_after_session_capture:
            self.owner.crash_after_session_capture = False
            raise SimulatedCrash("controller crashed after session capture")
        if self.owner.outcome_hook is not None:
            outcome = self.owner.outcome_hook(
                self,
                request,
                packet,
                session_id,
            )
            if outcome is not None:
                return outcome

        index = packet["current_plan"]["index"]
        marker = request.worktree / f"plan-{index}.txt"
        marker.write_text("implemented\n", encoding="utf-8")
        git("add", marker.name, cwd=request.worktree)
        git(
            "-c",
            "user.name=Engine Test",
            "-c",
            "user.email=engine@example.test",
            "commit",
            "-m",
            f"implement plan {index}",
            cwd=request.worktree,
        )
        head = git("rev-parse", "HEAD", cwd=request.worktree)
        prior_sets = packet["prior_verification_sets"]
        if self.owner.prior_set_override == "drop":
            prior_sets = []
        elif self.owner.prior_set_override == "reverse":
            prior_sets = list(reversed(prior_sets))
        verification = (
            {
                "kind": "no_applicable_verification",
                "candidate_head": head,
                "rationale": f"plan {index} has no executable verification",
            }
            if self.owner.rationale_only
            else {
                "kind": "commands",
                "candidate_head": head,
                "commands": [
                    {
                        "command_id": f"handoff-{index}",
                        "command_role": "handoff",
                        "argv": [sys.executable, "-c", "pass"],
                        "cwd": ".",
                        "input_digest": "a" * 64,
                        "deadline_seconds": 10,
                    }
                ],
            }
        )
        declaration = helper_client(
            self.helper.socket_path,
            self.helper.nonce,
            {
                "protocol_version": self.helper.protocol_version,
                "run_id": packet["run_id"],
                "nonce": self.helper.nonce,
                "operation": "declare_verification",
                "payload": {
                    "candidate_head": head,
                    "plan_index": index,
                    "verification": verification,
                    "prior_set_digests": prior_sets,
                    "is_final_plan": packet["is_final_plan"],
                },
            },
        )
        digest = declaration["artifact"]["digest"]
        if not self.owner.rationale_only:
            helper_client(
                self.helper.socket_path,
                self.helper.nonce,
                {
                    "protocol_version": self.helper.protocol_version,
                    "run_id": packet["run_id"],
                    "nonce": self.helper.nonce,
                    "operation": "run_verification",
                    "payload": {
                        "candidate_head": head,
                        "set_digest": digest,
                        "command_index": 0,
                        "deadline_seconds": 10,
                    },
                },
            )
        if self.owner.after_implementation_hook is not None:
            self.owner.after_implementation_hook(
                self,
                request,
                packet,
                session_id,
                head,
            )
        return ProviderOutcome(
            "implemented",
            0,
            session_id,
            {
                "status": "implemented",
                "head_commit": head,
                "summary": f"plan {index}",
                "verification_set_digest": digest,
                "blocker": None,
            },
            None,
            {},
            (),
            "",
        )


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
        self.requests = []
        self.leases = []
        self.output = []
        self.outcome_hook = None
        self.prior_set_override = None
        self.after_implementation_hook = None
        self.crash_after_session_capture = False
        self.rationale_only = False

    def tearDown(self):
        self.temporary.cleanup()

    def runner(self):
        return PlanRunner(
            self.paths,
            runtime_checker=runtime_identity,
            adapter_factory=lambda **values: ScriptedClaudeAdapter(
                self,
                values["helper"],
            ),
            output=self.output.append,
            environment={"PATH": os.environ["PATH"]},
        )

    def create_v2_run(self, plans=None):
        return self.runner().create_run(
            specs=self.specs,
            plans=self.plans if plans is None else plans,
            workspace=self.source,
            stall_seconds=30,
            model=None,
        )

    def current_state(self):
        roots = list(self.paths.state_home.iterdir())
        self.assertEqual(len(roots), 1)
        return json.loads(
            (roots[0] / "state.json").read_text(encoding="utf-8")
        )

    @staticmethod
    def packet_keys(value):
        if isinstance(value, dict):
            return set(value).union(
                *(
                    EngineTest.packet_keys(child)
                    for child in value.values()
                ),
                set(),
            )
        if isinstance(value, list):
            return set().union(
                *(EngineTest.packet_keys(child) for child in value),
                set(),
            )
        return set()

    def test_plan_result_validation_requires_minimal_handoff_evidence(self):
        valid = {
            "status": "implemented",
            "head_commit": "a" * 40,
            "summary": "implemented",
            "verification_set_digest": "b" * 64,
            "blocker": None,
        }
        self.assertEqual(
            PlanRunner._validated_plan_result(valid),
            valid,
        )
        for invalid in (
            {**valid, "summary": ""},
            {**valid, "verification_set_digest": None},
            {
                **valid,
                "blocker": {
                    "kind": "permission_required",
                    "detail": "x",
                },
            },
            {**valid, "unexpected": True},
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    PlanRunner._validated_plan_result(invalid)

    def test_two_plans_use_two_root_controllers_and_final_plan_closes_run(self):
        self.plans[0].write_text("# Task 1\n# Task 2\n", encoding="utf-8")
        self.plans[1].write_text("# Task 1\n# Task 2\n", encoding="utf-8")
        self.assertEqual(self.create_v2_run(), ExitCode.READY)
        self.assertEqual(
            [packet["mode"] for packet in self.packets],
            ["implementation", "implementation"],
        )
        state = self.current_state()
        self.assertEqual(state["status"], "ready_for_integration")
        self.assertNotIn("task_ledger", state)
        self.assertNotIn("finalization", state)
        self.assertTrue(
            all(
                session["mode"] == "implementation"
                for session in state["sessions"]
            )
        )
        forbidden = {
            "task",
            "tasks",
            "task_ledger",
            "finding",
            "findings",
            "finalization",
        }
        for packet in self.packets:
            self.assertTrue(forbidden.isdisjoint(self.packet_keys(packet)))
            self.assertNotIn("# Task 1", json.dumps(packet, sort_keys=True))
            self.assertNotIn("# Task 2", json.dumps(packet, sort_keys=True))
        self.assertNotIn("# Task 1", json.dumps(state, sort_keys=True))
        self.assertNotIn("# Task 2", json.dumps(state, sort_keys=True))

    def test_each_plan_gets_one_fresh_uuid(self):
        self.assertEqual(self.create_v2_run(), ExitCode.READY)
        sessions = [
            item["session_id"]
            for item in self.current_state()["sessions"]
            if item["mode"] == "implementation"
        ]
        self.assertEqual(len(sessions), 2)
        self.assertEqual(len(set(sessions)), 2)
        self.assertEqual(
            [request.resume for request in self.requests],
            [False, False],
        )

    def test_invented_verification_digest_is_rejected(self):
        def invented(_adapter, request, _packet, session_id):
            marker = request.worktree / "invented.txt"
            marker.write_text("implemented\n", encoding="utf-8")
            git("add", marker.name, cwd=request.worktree)
            git(
                "-c",
                "user.name=Engine Test",
                "-c",
                "user.email=engine@example.test",
                "commit",
                "-m",
                "invented handoff",
                cwd=request.worktree,
            )
            return ProviderOutcome(
                "implemented",
                0,
                session_id,
                {
                    "status": "implemented",
                    "head_commit": git(
                        "rev-parse",
                        "HEAD",
                        cwd=request.worktree,
                    ),
                    "summary": "invented",
                    "verification_set_digest": "a" * 64,
                    "blocker": None,
                },
                None,
                {},
                (),
                "",
            )

        self.outcome_hook = invented
        self.assertEqual(
            self.create_v2_run(self.plans[:1]),
            ExitCode.INTEGRITY,
        )

    def test_active_recovery_uses_only_v2_progress_facts(self):
        self.outcome_hook = (
            lambda _adapter, _request, _packet, session_id: ProviderOutcome(
                "failed",
                1,
                session_id,
                None,
                "controller_transport_failed",
                {},
                (),
                "",
            )
        )
        self.assertEqual(
            self.create_v2_run(self.plans[:1]),
            ExitCode.FAILED,
        )
        for packet in self.packets:
            keys = self.packet_keys(packet["recovery_context"])
            self.assertEqual(
                keys,
                {
                    "current_head",
                    "git_tree_digest",
                    "successful_receipt_digests",
                    "plan_handoff_digests",
                },
            )

    def test_active_recovery_resumes_then_uses_fresh_session_then_exhausts(self):
        self.outcome_hook = (
            lambda _adapter, _request, _packet, session_id: ProviderOutcome(
                "failed",
                1,
                session_id,
                None,
                "controller_transport_failed",
                {},
                (),
                "",
            )
        )
        self.assertEqual(
            self.create_v2_run(self.plans[:1]),
            ExitCode.FAILED,
        )
        self.assertEqual(
            [request.resume for request in self.requests],
            [False, True, False],
        )
        self.assertEqual(
            self.requests[0].session_id,
            self.requests[1].session_id,
        )
        self.assertNotEqual(
            self.requests[1].session_id,
            self.requests[2].session_id,
        )
        self.assertEqual(
            self.current_state()["failure"]["reason_code"],
            "recovery_exhausted",
        )

    def test_external_resume_uses_the_recorded_claude_uuid(self):
        def interrupt_once(_adapter, _request, _packet, session_id):
            if len(self.requests) == 1:
                return ProviderOutcome(
                    "controller_stopped",
                    None,
                    session_id,
                    None,
                    "controller_transport_failed",
                    {},
                    (),
                    "",
                )
            return None

        self.outcome_hook = interrupt_once
        self.assertEqual(
            self.create_v2_run(self.plans[:1]),
            ExitCode.RESUMABLE,
        )
        run_id = self.current_state()["run_id"]
        self.assertEqual(
            self.runner().resume(
                run_id,
                retry_blocked=False,
                retry_failed=False,
                strategy_note=None,
            ),
            ExitCode.READY,
        )
        self.assertEqual(
            [request.resume for request in self.requests],
            [False, True],
        )
        self.assertEqual(
            self.requests[0].session_id,
            self.requests[1].session_id,
        )

    def test_restart_after_session_capture_reuses_the_healthy_recorded_uuid(self):
        self.crash_after_session_capture = True
        with self.assertRaises(SimulatedCrash):
            self.create_v2_run(self.plans[:1])
        captured = self.current_state()["sessions"][0]["session_id"]

        self.assertEqual(
            self.runner().resume(
                self.current_state()["run_id"],
                retry_blocked=False,
                retry_failed=False,
                strategy_note=None,
            ),
            ExitCode.READY,
        )
        self.assertEqual(len(self.requests), 2)
        self.assertTrue(self.requests[1].resume)
        self.assertEqual(self.requests[1].session_id, captured)

    def test_restart_reconciles_completed_result_without_relaunch(self):
        with mock.patch.object(
            PlanRunner,
            "_accept_implemented",
            side_effect=SimulatedCrash(
                "controller crashed after durable provider completion"
            ),
        ):
            with self.assertRaises(SimulatedCrash):
                self.create_v2_run(self.plans[:1])
        state = self.current_state()
        self.assertTrue(state["attempts"][-1]["completed"])
        self.assertIsNotNone(state["attempts"][-1]["result_artifact"])

        self.assertEqual(
            self.runner().resume(
                state["run_id"],
                retry_blocked=False,
                retry_failed=False,
                strategy_note=None,
            ),
            ExitCode.READY,
        )
        self.assertEqual(len(self.requests), 1)

    def test_single_plan_all_rationale_run_closes_without_synthetic_command(self):
        self.rationale_only = True
        self.assertEqual(
            self.create_v2_run(self.plans[:1]),
            ExitCode.READY,
        )
        state = self.current_state()
        run_sets = [
            reference
            for reference in state["artifact_refs"]
            if reference["kind"] == "run_verification_set"
        ]
        self.assertEqual(len(run_sets), 1)
        run_set = json.loads(
            (
                self.paths.state_home
                / state["run_id"]
                / run_sets[0]["relative_path"]
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(run_set["kind"], "no_applicable_verification")
        self.assertNotIn("commands", run_set)
        self.assertEqual(len(run_set["rationales"]), 1)

    def test_multi_plan_all_rationale_run_preserves_ordered_provenance(self):
        self.rationale_only = True
        self.assertEqual(self.create_v2_run(), ExitCode.READY)
        state = self.current_state()
        run_ref = next(
            reference
            for reference in state["artifact_refs"]
            if reference["kind"] == "run_verification_set"
        )
        run_set = json.loads(
            (
                self.paths.state_home
                / state["run_id"]
                / run_ref["relative_path"]
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            run_set["plan_set_digests"],
            [
                json.loads(
                    (
                        self.paths.state_home
                        / state["run_id"]
                        / next(
                            reference["relative_path"]
                            for reference in state["artifact_refs"]
                            if reference["kind"] == "plan_handoff"
                            and reference["digest"]
                            == plan["handoff_digest"]
                        )
                    ).read_text(encoding="utf-8")
                )["verification_set_digest"]
                for plan in state["plans"][:-1]
            ]
            + [run_set["rationales"][-1]["plan_set_digest"]],
        )
        self.assertEqual(
            [item["plan_index"] for item in run_set["rationales"]],
            [0, 1],
        )

    def test_launch_lease_starts_at_current_monotonic_time(self):
        self.assertEqual(self.create_v2_run(), ExitCode.READY)
        self.assertTrue(
            all(
                not lease.expired(time.monotonic())
                for lease in self.leases
            )
        )

    def test_protected_ref_drift_after_provider_handoff_fails_closed(self):
        self.after_implementation_hook = (
            lambda _adapter, request, _packet, _session_id, head: git(
                "update-ref",
                "refs/tags/provider-drift",
                head,
                cwd=request.worktree,
            )
        )
        self.assertEqual(
            self.create_v2_run(self.plans[:1]),
            ExitCode.INTEGRITY,
        )

    def test_version_one_is_inspect_only(self):
        self.assertEqual(self.create_v2_run(), ExitCode.READY)
        state = self.current_state()
        root = self.paths.state_home / state["run_id"]
        state["format_version"] = 1
        state["contract_version"] = 1
        state["state_digest"] = storage_module._state_digest(state)
        state_path = root / "state.json"
        state_path.write_bytes(storage_module.canonical_json(state))
        before = state_path.read_bytes()
        metadata = state_path.stat()
        self.assertEqual(
            self.runner().inspect(state["run_id"]),
            ExitCode.READY,
        )
        self.assertEqual(state_path.read_bytes(), before)
        after = state_path.stat()
        self.assertEqual(
            (after.st_ino, after.st_size, after.st_mtime_ns),
            (metadata.st_ino, metadata.st_size, metadata.st_mtime_ns),
        )
        self.output.clear()
        self.assertEqual(
            self.runner().resume(
                state["run_id"],
                retry_blocked=False,
                retry_failed=False,
                strategy_note=None,
            ),
            ExitCode.INVALID,
        )
        self.assertEqual(
            json.loads(self.output[-1])["reason_code"],
            "legacy_contract_requires_v1_runner",
        )


if __name__ == "__main__":
    unittest.main()
