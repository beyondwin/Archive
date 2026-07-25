from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path
from unittest import mock


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from plan_runner import engine as engine_module  # noqa: E402
from plan_runner import storage as storage_module  # noqa: E402
from plan_runner.contracts import ExitCode  # noqa: E402
from plan_runner.git_ops import GitIdentity, GitWorkspace  # noqa: E402
from plan_runner.helper import helper_client  # noqa: E402
from plan_runner.provider import ProviderOutcome  # noqa: E402
from plan_runner.runtime import RuntimeIdentity  # noqa: E402
from plan_runner.storage import StateStore  # noqa: E402
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
        self.engine_event_hook = None

    def tearDown(self):
        self.temporary.cleanup()

    def runner(self):
        return PlanRunner(
            self.paths, runtime_checker=runtime_identity,
            adapter_factory=lambda **values: ScriptedAdapter(self, values["helper"]),
            output=self.output.append, environment={"PATH": os.environ["PATH"]},
            event_hook=self.engine_event_hook,
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

    def create_paused_run(
        self,
        *,
        specs=None,
        plans=None,
        sandbox="workspace-write",
        model=None,
    ):
        with mock.patch.object(
            PlanRunner, "_execute", return_value=int(ExitCode.RESUMABLE)
        ):
            code = self.runner().create_run(
                specs=self.specs if specs is None else specs,
                plans=self.plans[:1] if plans is None else plans,
                workspace=self.source,
                stall_seconds=30,
                sandbox=sandbox,
                model=model,
            )
        self.assertEqual(code, ExitCode.RESUMABLE)
        return self.state()

    def matching_response(self):
        response = json.loads(self.output[-1])
        self.assertIn(
            response["reason"],
            {"matching_run_exists", "matching_run_unproven"},
        )
        return response

    def admission_record_path(self, state):
        lock_home = self.paths.state_home.with_name(
            f".{self.paths.state_home.name}-intent-locks"
        )
        return lock_home / (
            state["immutable_config"]["execution_intent_digest"] + ".json"
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

    def test_two_plans_use_two_root_controllers_and_final_plan_closes_run(self):
        self.plans[0].write_text("# Task 1\n# Task 2\n", encoding="utf-8")
        self.plans[1].write_text("# Task 1\n# Task 2\n", encoding="utf-8")
        self.assertEqual(self.create(), ExitCode.READY)
        self.assertEqual([packet["mode"] for packet in self.packets], ["implementation", "implementation"])
        state = self.state()
        self.assertEqual(state["status"], "ready_for_integration")
        self.assertNotIn("task_ledger", state)
        self.assertNotIn("finalization", state)
        self.assertTrue(all(session["mode"] == "implementation" for session in state["sessions"]))
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
        self.output.clear()
        self.assertEqual(self.runner().resume(state["run_id"], retry_blocked=False, retry_failed=False, strategy_note=None), ExitCode.INVALID)
        self.assertEqual(
            json.loads(self.output[-1])["reason_code"],
            "legacy_contract_requires_v1_runner",
        )
        self.output.clear()
        self.assertEqual(
            self.runner().repair(
                state["run_id"],
                expected_revision=state["revision"],
                repair_kind="volatile-codex-turn-refs",
                strategy_note="read-only legacy refusal",
                attempt_id=None,
            ),
            ExitCode.INVALID,
        )
        self.assertEqual(
            json.loads(self.output[-1])["reason_code"],
            "legacy_contract_requires_v1_runner",
        )

    def test_same_inputs_with_different_profile_are_one_execution_intent(self):
        first = self.create_paused_run(
            sandbox="workspace-write", model="model-a"
        )
        self.output.clear()

        with mock.patch.object(
            PlanRunner, "_execute", return_value=int(ExitCode.RESUMABLE)
        ):
            code = self.runner().create_run(
                specs=self.specs,
                plans=self.plans[:1],
                workspace=self.source,
                stall_seconds=999,
                sandbox="danger-full-access",
                model="model-b",
            )

        self.assertEqual(code, ExitCode.RESUMABLE)
        response = self.matching_response()
        self.assertEqual(response["reason"], "matching_run_exists")
        self.assertEqual(response["run_id"], first["run_id"])
        self.assertEqual(response["status"], "resumable")
        self.assertEqual(
            response["recommended_action"],
            "./skills/kws-codex-plan-runner/scripts/runner resume "
            f"--run-id {first['run_id']}",
        )
        self.assertEqual(len(list(self.paths.state_home.iterdir())), 1)
        self.assertEqual(len(list(self.paths.worktree_home.iterdir())), 1)

    def test_same_files_in_different_order_are_distinct_execution_intents(self):
        first = self.create_paused_run(plans=self.plans)

        with mock.patch.object(
            PlanRunner, "_execute", return_value=int(ExitCode.RESUMABLE)
        ):
            code = self.runner().create_run(
                specs=self.specs,
                plans=list(reversed(self.plans)),
                workspace=self.source,
                stall_seconds=30,
                sandbox="workspace-write",
                model=None,
            )

        self.assertEqual(code, ExitCode.RESUMABLE)
        states = [
            StateStore.open(path).snapshot()
            for path in self.paths.state_home.iterdir()
        ]
        self.assertEqual(len(states), 2)
        intents = {
            state["immutable_config"]["execution_intent_digest"]
            for state in states
        }
        self.assertEqual(len(intents), 2)
        self.assertIn(
            first["immutable_config"]["execution_intent_digest"], intents
        )

    def test_concurrent_equivalent_creation_admits_exactly_one_run(self):
        barrier = threading.Barrier(2)

        def synchronize(stage):
            if stage == "intent_admission_ready":
                barrier.wait(timeout=5)

        self.engine_event_hook = synchronize
        results = []
        failures = []

        def invoke():
            try:
                results.append(
                    self.runner().create_run(
                        specs=self.specs,
                        plans=self.plans[:1],
                        workspace=self.source,
                        stall_seconds=30,
                        sandbox="workspace-write",
                        model=None,
                    )
                )
            except BaseException as error:
                failures.append(error)

        with mock.patch.object(
            PlanRunner, "_execute", return_value=int(ExitCode.RESUMABLE)
        ):
            threads = [threading.Thread(target=invoke) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10)

        self.assertFalse(failures, failures)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(sorted(results), [ExitCode.RESUMABLE, ExitCode.RESUMABLE])
        run_roots = list(self.paths.state_home.iterdir())
        self.assertEqual(len(run_roots), 1)
        state = StateStore.open(run_roots[0]).snapshot()
        self.assertEqual(len(list(self.paths.worktree_home.iterdir())), 1)
        self.assertEqual(
            git(
                "for-each-ref",
                "--format=%(refname)",
                "refs/heads/codex-plan/",
                cwd=self.source,
            ).splitlines(),
            [f"refs/heads/{state['repository']['branch']}"],
        )
        refusals = [
            json.loads(line)
            for line in self.output
            if json.loads(line).get("reason") == "matching_run_exists"
        ]
        self.assertEqual(len(refusals), 1)

    def test_refusal_reports_exact_state_specific_action(self):
        initial = self.create_paused_run()
        run_root = self.paths.state_home / initial["run_id"]
        runner_path = "./skills/kws-codex-plan-runner/scripts/runner"
        cases = (
            ("running", None, ExitCode.RESUMABLE, "inspect"),
            ("recovering", None, ExitCode.RESUMABLE, "inspect"),
            ("resumable", None, ExitCode.RESUMABLE, "resume"),
            (
                "blocked",
                {"reason_code": "host_permission_blocked"},
                ExitCode.BLOCKED,
                "blocked",
            ),
            (
                "failed",
                {
                    "reason_code": "recovery_exhausted",
                    "next_strategy": "block",
                },
                ExitCode.FAILED,
                "retry_failed",
            ),
            ("ready_for_integration", None, ExitCode.READY, "inspect"),
        )

        for status, failure, expected_code, action_kind in cases:
            with self.subTest(status=status):
                store = StateStore.open(run_root)
                state = store.snapshot()
                state["status"] = status
                state["failure"] = failure
                state = store.commit(state)
                run_id = state["run_id"]
                expected = {
                    "inspect": f"{runner_path} inspect --run-id {run_id}",
                    "resume": f"{runner_path} resume --run-id {run_id}",
                    "blocked": (
                        "fix the named blocker, then "
                        f"{runner_path} resume --run-id {run_id} "
                        "--retry-blocked"
                    ),
                    "retry_failed": (
                        f"{runner_path} resume --run-id {run_id} "
                        "--retry-failed --strategy-note TEXT"
                    ),
                }
                self.output.clear()

                code = self.runner().create_run(
                    specs=self.specs,
                    plans=self.plans[:1],
                    workspace=self.source,
                    stall_seconds=30,
                    sandbox="danger-full-access",
                    model="different-model",
                )

                self.assertEqual(code, expected_code)
                response = self.matching_response()
                self.assertEqual(response["reason"], "matching_run_exists")
                self.assertEqual(response["status"], status)
                self.assertEqual(
                    response["recommended_action"], expected[action_kind]
                )

    def test_failed_or_ready_execution_intent_is_never_replayed(self):
        initial = self.create_paused_run()
        run_root = self.paths.state_home / initial["run_id"]
        cases = (
            (
                "failed",
                {
                    "reason_code": "recovery_exhausted",
                    "next_strategy": "block",
                },
                ExitCode.FAILED,
            ),
            ("ready_for_integration", None, ExitCode.READY),
        )

        for status, failure, expected_code in cases:
            with self.subTest(status=status):
                store = StateStore.open(run_root)
                state = store.snapshot()
                state["status"] = status
                state["failure"] = failure
                store.commit(state)
                before_refs = git(
                    "for-each-ref",
                    "--format=%(refname) %(objectname)",
                    cwd=self.source,
                )
                self.output.clear()

                code = self.runner().create_run(
                    specs=self.specs,
                    plans=self.plans[:1],
                    workspace=self.source,
                    stall_seconds=30,
                    sandbox="workspace-write",
                    model=None,
                )

                self.assertEqual(code, expected_code)
                self.assertEqual(
                    self.matching_response()["reason"], "matching_run_exists"
                )
                self.assertEqual(len(list(self.paths.state_home.iterdir())), 1)
                self.assertEqual(
                    git(
                        "for-each-ref",
                        "--format=%(refname) %(objectname)",
                        cwd=self.source,
                    ),
                    before_refs,
                )

    def assert_matching_intent_evidence_fails_closed(self, mutate):
        initial = self.create_paused_run()
        run_root = self.paths.state_home / initial["run_id"]
        mutate(run_root / "intent.json", initial)
        self.output.clear()

        with (
            mock.patch.object(StateStore, "create") as create_state,
            mock.patch.object(GitWorkspace, "create") as create_worktree,
        ):
            code = self.runner().create_run(
                specs=self.specs,
                plans=self.plans[:1],
                workspace=self.source,
                stall_seconds=30,
                sandbox="danger-full-access",
                model="different-model",
            )

        self.assertEqual(code, ExitCode.INTEGRITY)
        response = self.matching_response()
        self.assertEqual(response["reason"], "matching_run_unproven")
        self.assertEqual(response["run_id"], initial["run_id"])
        self.assertEqual(response["recommended_action"], "preserve evidence and stop")
        create_state.assert_not_called()
        create_worktree.assert_not_called()

    def test_missing_matching_intent_envelope_fails_closed(self):
        self.assert_matching_intent_evidence_fails_closed(
            lambda path, _state: path.unlink(missing_ok=True)
        )

    def test_tampered_matching_intent_envelope_fails_closed(self):
        def tamper(path, state):
            envelope = json.loads(path.read_text(encoding="utf-8"))
            envelope["run_id"] = state["run_id"] + "-substituted"
            envelope["envelope_digest"] = (
                storage_module._intent_envelope_digest(envelope)
            )
            path.write_bytes(storage_module.canonical_json(envelope))

        self.assert_matching_intent_evidence_fails_closed(tamper)

    def test_tampered_digest_keyed_admission_record_fails_closed(self):
        initial = self.create_paused_run()
        record_path = self.admission_record_path(initial)
        record = json.loads(record_path.read_text(encoding="utf-8"))
        record["execution_intent_digest"] = "b" * 64
        record["record_digest"] = storage_module._admission_record_digest(record)
        record_path.write_bytes(storage_module.canonical_json(record))
        self.output.clear()

        with (
            mock.patch.object(StateStore, "create") as create_state,
            mock.patch.object(GitWorkspace, "create") as create_worktree,
        ):
            code = self.runner().create_run(
                specs=self.specs,
                plans=self.plans[:1],
                workspace=self.source,
                stall_seconds=30,
                sandbox="danger-full-access",
                model="different-model",
            )

        self.assertEqual(code, ExitCode.INTEGRITY)
        self.assertEqual(
            self.matching_response()["reason"], "matching_run_unproven"
        )
        create_state.assert_not_called()
        create_worktree.assert_not_called()

    def test_missing_digest_keyed_admission_record_fails_closed(self):
        initial = self.create_paused_run()
        self.admission_record_path(initial).unlink()
        self.output.clear()

        with (
            mock.patch.object(StateStore, "create") as create_state,
            mock.patch.object(GitWorkspace, "create") as create_worktree,
        ):
            code = self.runner().create_run(
                specs=self.specs,
                plans=self.plans[:1],
                workspace=self.source,
                stall_seconds=30,
                sandbox="workspace-write",
                model=None,
            )

        self.assertEqual(code, ExitCode.INTEGRITY)
        response = self.matching_response()
        self.assertEqual(response["reason"], "matching_run_unproven")
        self.assertEqual(response["run_id"], initial["run_id"])
        create_state.assert_not_called()
        create_worktree.assert_not_called()

    def test_matching_state_digest_tamper_fails_closed_without_new_run(self):
        initial = self.create_paused_run()
        state_path = self.paths.state_home / initial["run_id"] / "state.json"
        tampered = json.loads(state_path.read_text(encoding="utf-8"))
        tampered["state_digest"] = "0" * 64
        state_path.write_bytes(storage_module.canonical_json(tampered))
        self.output.clear()

        with (
            mock.patch.object(StateStore, "create") as create_state,
            mock.patch.object(GitWorkspace, "create") as create_worktree,
        ):
            code = self.runner().create_run(
                specs=self.specs,
                plans=self.plans[:1],
                workspace=self.source,
                stall_seconds=30,
                sandbox="workspace-write",
                model=None,
            )

        self.assertEqual(code, ExitCode.INTEGRITY)
        response = self.matching_response()
        self.assertEqual(response["reason"], "matching_run_unproven")
        self.assertEqual(response["run_id"], initial["run_id"])
        create_state.assert_not_called()
        create_worktree.assert_not_called()

    def test_oversized_matching_intent_envelope_fails_closed(self):
        self.assert_matching_intent_evidence_fails_closed(
            lambda path, _state: path.write_bytes(b"x" * (64 * 1024 + 1))
        )

    def test_admission_record_without_run_state_blocks_reallocation(self):
        with mock.patch.object(
            StateStore, "create", side_effect=OSError("simulated state crash")
        ):
            first_code = self.runner().create_run(
                specs=self.specs,
                plans=self.plans[:1],
                workspace=self.source,
                stall_seconds=30,
                sandbox="workspace-write",
                model=None,
            )
        self.assertEqual(first_code, ExitCode.INTEGRITY)
        self.output.clear()

        with (
            mock.patch.object(StateStore, "create") as create_state,
            mock.patch.object(GitWorkspace, "create") as create_worktree,
        ):
            second_code = self.runner().create_run(
                specs=self.specs,
                plans=self.plans[:1],
                workspace=self.source,
                stall_seconds=30,
                sandbox="workspace-write",
                model=None,
            )

        self.assertEqual(second_code, ExitCode.INTEGRITY)
        self.assertEqual(
            self.matching_response()["reason"], "matching_run_unproven"
        )
        create_state.assert_not_called()
        create_worktree.assert_not_called()


if __name__ == "__main__":
    unittest.main()
