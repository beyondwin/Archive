import dataclasses
import json
import os
import signal
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
from plan_runner.recovery import strategy_note_digest  # noqa: E402
from plan_runner.runtime import RuntimeIdentity, RuntimeUnavailable  # noqa: E402
from plan_runner.storage import StateStore  # noqa: E402
from plan_runner.engine import PlanRunner, RuntimePaths  # noqa: E402


SDD_RELATIVE_PATHS = (
    Path("skills/subagent-driven-development/SKILL.md"),
    Path("skills/subagent-driven-development/scripts/sdd-workspace"),
    Path("skills/subagent-driven-development/scripts/task-brief"),
    Path("skills/subagent-driven-development/scripts/review-package"),
    Path("skills/subagent-driven-development/implementer-prompt.md"),
    Path("skills/subagent-driven-development/task-reviewer-prompt.md"),
    Path("skills/subagent-driven-development/re-review-prompt.md"),
    Path("skills/requesting-code-review/code-reviewer.md"),
)


def make_codex_home(path: Path) -> None:
    path.mkdir()
    (path / "auth.json").write_text(
        json.dumps(
            {
                "auth_mode": "apikey",
                "last_refresh": None,
                "OPENAI_API_KEY": "fake-file-api-key",
                "tokens": None,
            }
        ),
        encoding="utf-8",
    )
    for relative in SDD_RELATIVE_PATHS:
        target = path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("fake-sdd-entrypoint\n", encoding="utf-8")


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

    def launch(
        self,
        request,
        _lease,
        on_session_id=None,
        on_process_observation=None,
    ):
        self.owner.leases.append(_lease)
        packet = json.loads(request.prompt.split("\nEXECUTION_PACKET=", 1)[1])
        self.owner.packets.append(packet)
        self.owner.requests.append(request)
        launch = len(self.owner.packets)
        session_id = request.session_id or str(uuid.UUID(int=launch))
        if on_session_id is not None:
            on_session_id(session_id)
        if self.owner.crash_after_session:
            self.owner.crash_after_session = False
            raise SimulatedCrash("session captured")
        if self.owner.outcome_hook is not None:
            outcome = self.owner.outcome_hook(
                self, request, packet, session_id
            )
            if outcome is not None:
                return outcome
        if packet["mode"] == "implementation":
            marker = request.worktree / f"plan-{packet['current_plan']['index']}.txt"
            if not marker.exists():
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
                "task_ledger": list(self.owner.implementation_ledger),
                "open_obligation_ids": [],
                "failure_signature": None,
                "strategy_note": None,
                "blocker": None,
            }
            return ProviderOutcome(
                "implemented", 0, session_id, result, None, {}, (), ""
            )
        if packet["mode"] == "final_review_fix":
            marker = request.worktree / "review-fix.txt"
            if not marker.exists():
                marker.write_text("review fixed\n", encoding="utf-8")
                git("add", marker.name, cwd=request.worktree)
                git(
                    "-c",
                    "user.name=Engine Test",
                    "-c",
                    "user.email=engine@example.test",
                    "commit",
                    "-m",
                    "fix final review findings",
                    cwd=request.worktree,
                )
            head = git("rev-parse", "HEAD", cwd=request.worktree)
            return ProviderOutcome(
                "implemented",
                0,
                session_id,
                {
                    "status": "implemented",
                    "head_commit": head,
                    "summary": "review findings fixed",
                    "task_ledger": (
                        packet["task_ledger"]
                        if self.owner.review_fix_ledger_override is None
                        else list(self.owner.review_fix_ledger_override)
                    ),
                    "open_obligation_ids": [],
                    "failure_signature": None,
                    "strategy_note": "fix only bundled review findings",
                    "blocker": None,
                },
                None,
                {},
                (),
                "",
            )

        head = packet["candidate_head"]
        digest = packet.get("sealed_verification_set_digest")
        if digest is None:
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
                    "deadline_seconds": 10,
                },
            }
            helper_client(self.helper.socket_path, self.helper.nonce, envelope)
        if self.owner.after_final_hook is not None:
            outcome = self.owner.after_final_hook(
                self, request, packet, session_id, digest
            )
            if outcome is not None:
                return outcome
        findings = []
        if self.owner.review_findings_once:
            self.owner.review_findings_once = False
            findings = [
                {
                    "id": "R1",
                    "severity": "Important",
                    "summary": "fix final review issue",
                    "evidence": "review evidence",
                }
            ]
        elif self.owner.minor_findings_once:
            self.owner.minor_findings_once = False
            findings = [
                {
                    "id": "R-minor",
                    "severity": "Minor",
                    "summary": "allowed polish item",
                    "evidence": "review evidence",
                }
            ]
        result = {
            "status": "reviewed",
            "review_head": head,
            "verification_set_digest": digest,
            "open_findings": findings,
            "open_obligation_ids": [],
            "no_applicable_verification_approved": False,
            "summary": "whole branch reviewed",
        }
        return ProviderOutcome("reviewed", 0, session_id, result, None, {}, (), "")


class SimulatedCrash(BaseException):
    pass


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
        self.adapter_values = []
        self.output = []
        self.crash_after_session = False
        self.outcome_hook = None
        self.review_findings_once = False
        self.minor_findings_once = False
        self.implementation_ledger = []
        self.review_fix_ledger_override = None
        self.after_final_hook = None
        self.engine_event_hook = None

    def tearDown(self):
        self.temporary.cleanup()

    def runner(self, runtime_checker=runtime_identity):
        def adapter_factory(**values):
            self.adapter_values.append(values)
            return ScriptedAdapter(self, values["helper"])

        return PlanRunner(
            self.paths,
            runtime_checker=runtime_checker,
            adapter_factory=adapter_factory,
            output=self.output.append,
            environment={"PATH": os.environ["PATH"]},
            event_hook=self.engine_event_hook,
        )

    def test_plan_result_validation_preserves_constraints_not_in_provider_schema(self):
        valid = {
            "status": "implemented",
            "head_commit": "a" * 40,
            "summary": "implemented",
            "task_ledger": [
                {
                    "task_id": "T1",
                    "status": "reported_done",
                    "evidence_digests": ["b" * 64],
                }
            ],
            "open_obligation_ids": [],
            "failure_signature": None,
            "strategy_note": None,
            "blocker": None,
        }
        self.assertEqual(
            "T1",
            PlanRunner._validated_plan_result(valid)[0]["task_id"],
        )
        invalid_values = [
            {**valid, "summary": ""},
            {
                **valid,
                "task_ledger": [
                    {
                        **valid["task_ledger"][0],
                        "evidence_digests": ["b" * 64, "b" * 64],
                    }
                ],
            },
            {**valid, "blocker": {"kind": "permission_required", "detail": "x"}},
            {
                **valid,
                "status": "failed",
                "failure_signature": "c" * 64,
                "strategy_note": None,
            },
        ]
        for value in invalid_values:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    PlanRunner._validated_plan_result(value)

    def test_final_review_rejects_empty_strings_not_enforced_by_provider_schema(self):
        def empty_review(_adapter, _request, packet, session_id, digest):
            return ProviderOutcome(
                "reviewed",
                0,
                session_id,
                {
                    "status": "reviewed",
                    "review_head": packet["candidate_head"],
                    "verification_set_digest": digest,
                    "open_findings": [],
                    "open_obligation_ids": [],
                    "no_applicable_verification_approved": False,
                    "summary": "",
                },
                None,
                {},
                (),
                "",
            )

        self.after_final_hook = empty_review
        code = self.runner().create_run(
            specs=self.specs,
            plans=self.plans[:1],
            workspace=self.source,
            stall_seconds=30,
            sandbox="workspace-write",
            model=None,
        )
        self.assertEqual(
            code,
            ExitCode.INTEGRITY,
            [self.output, self.state().get("failure")],
        )

    def state(self):
        run_roots = list(self.paths.state_home.iterdir())
        self.assertEqual(len(run_roots), 1)
        return json.loads((run_roots[0] / "state.json").read_text(encoding="utf-8"))

    def worktree_observation(self, state=None):
        state = self.state() if state is None else state
        repository = state["repository"]
        workspace = GitWorkspace.open(
            Path(repository["source_repository"]),
            Path(repository["worktree"]),
            repository["branch"],
        )
        return dataclasses.asdict(workspace.observe())

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

    def rewrite_run_state(self, mutate):
        state = self.state()
        mutate(state)
        state["state_digest"] = storage_module._state_digest(state)
        run_root = self.paths.state_home / state["run_id"]
        (run_root / "state.json").write_bytes(storage_module.canonical_json(state))
        return StateStore.open(run_root).snapshot()

    def git_surface(self, state):
        worktree = Path(state["repository"]["worktree"])
        return {
            "head": git("rev-parse", "HEAD", cwd=worktree),
            "refs": git(
                "for-each-ref", "--format=%(refname)%09%(objectname)", cwd=worktree
            ),
            "index": git("ls-files", "--stage", cwd=worktree),
            "worktree": self.worktree_observation(state),
        }

    def make_volatile_repair_state(self):
        state = self.create_paused_run()
        worktree = Path(state["repository"]["worktree"])
        volatile_ref = "refs/codex/turn-diffs/captures/task-4"
        git("update-ref", volatile_ref, self.starting_head, cwd=worktree)
        recorded_refs = {
            line.split("\t", 1)[0]: line.split("\t", 1)[1]
            for line in git(
                "for-each-ref", "--format=%(refname)%09%(objectname)", cwd=worktree
            ).splitlines()
            if line and not line.startswith(
                f"refs/heads/{state['repository']['branch']}\t"
            )
        }
        observation = self.worktree_observation(state)

        def historical_failure(candidate):
            config = candidate["immutable_config"]
            config.pop("volatile_ref_policy_version", None)
            config["protected_refs"] = recorded_refs
            candidate["status"] = "failed"
            candidate["failure"] = {
                "reason_code": "state_integrity_failed",
                "detail": "historical protected ref mutation",
                "worktree_observation": observation,
            }

        state = self.rewrite_run_state(historical_failure)
        changed = subprocess.run(
            ["git", "hash-object", "-w", "--stdin"],
            cwd=worktree,
            input="volatile replacement\n",
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        git("update-ref", volatile_ref, changed, cwd=worktree)
        return state, volatile_ref

    def make_partial_repair_state(
        self,
        *,
        attempt_id="attempt-partial",
        mode="implementation",
        completed=False,
    ):
        state = self.create_paused_run()
        worktree = Path(state["repository"]["worktree"])
        (worktree / "partial.txt").write_text("untrusted partial\n", encoding="utf-8")

        def historical_failure(candidate):
            candidate["status"] = "failed"
            candidate["plans"][0]["status"] = "running"
            candidate["attempts"].append(
                {
                    "attempt_id": attempt_id,
                    "mode": mode,
                    "plan_index": 0,
                    "completed": completed,
                    "result_artifact": {"untrusted": True},
                    "result_validated": True,
                }
            )
            candidate["failure"] = {
                "reason_code": "state_integrity_failed",
                "detail": "historical unsealed provider partial",
            }

        return self.rewrite_run_state(historical_failure)

    def make_overlapping_repair_state(self):
        state = self.make_partial_repair_state()
        worktree = Path(state["repository"]["worktree"])
        volatile_ref = "refs/codex/turn-diffs/checkpoints/overlap"
        git("update-ref", volatile_ref, self.starting_head, cwd=worktree)
        recorded_refs = {
            line.split("\t", 1)[0]: line.split("\t", 1)[1]
            for line in git(
                "for-each-ref", "--format=%(refname)%09%(objectname)", cwd=worktree
            ).splitlines()
            if line and not line.startswith(
                f"refs/heads/{state['repository']['branch']}\t"
            )
        }
        observation = self.worktree_observation(state)

        def make_legacy_overlap(candidate):
            candidate["immutable_config"].pop("volatile_ref_policy_version", None)
            candidate["immutable_config"]["protected_refs"] = recorded_refs
            candidate["failure"]["worktree_observation"] = observation

        state = self.rewrite_run_state(make_legacy_overlap)
        changed = subprocess.run(
            ["git", "hash-object", "-w", "--stdin"],
            cwd=worktree,
            input="overlap replacement\n",
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        git("update-ref", volatile_ref, changed, cwd=worktree)
        return state

    @staticmethod
    def artifact_files(run_root):
        return sorted(
            path.relative_to(run_root).as_posix()
            for path in (run_root / "artifacts").rglob("*")
            if path.is_file()
        )

    def matching_response(self):
        response = json.loads(self.output[-1])
        self.assertIn(
            response["reason"],
            {"matching_run_exists", "matching_run_unproven"},
        )
        return response

    def test_same_inputs_with_different_sandbox_or_model_are_equivalent(self):
        first = self.create_paused_run(sandbox="workspace-write", model="model-a")

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
        self.assertEqual(response["branch"], first["repository"]["branch"])
        self.assertEqual(response["worktree"], first["repository"]["worktree"])
        self.assertEqual(
            response["recommended_action"],
            "./skills/kws-codex-plan-runner/scripts/runner resume "
            f"--run-id {first['run_id']}",
        )
        self.assertEqual(len(list(self.paths.state_home.iterdir())), 1)
        self.assertEqual(len(list(self.paths.worktree_home.iterdir())), 1)

    def test_same_files_in_different_order_are_not_equivalent(self):
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
        self.assertEqual(len({state["run_id"] for state in states}), 2)
        self.assertEqual(
            len(
                {
                    state["immutable_config"]["execution_intent_digest"]
                    for state in states
                }
            ),
            2,
        )
        self.assertNotEqual(
            first["immutable_config"]["execution_intent_digest"],
            next(
                state["immutable_config"]["execution_intent_digest"]
                for state in states
                if state["run_id"] != first["run_id"]
            ),
        )

    def test_concurrent_equivalent_creation_admits_at_most_one_run(self):
        barrier = threading.Barrier(2)

        def synchronize(stage):
            if stage == "intent_admission_ready":
                barrier.wait(timeout=5)

        self.engine_event_hook = synchronize
        runners = [self.runner(), self.runner()]
        results = []
        failures = []

        def invoke(runner):
            try:
                results.append(
                    runner.create_run(
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
            threads = [threading.Thread(target=invoke, args=(runner,)) for runner in runners]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10)

        self.assertFalse(failures, failures)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(results, [ExitCode.RESUMABLE, ExitCode.RESUMABLE])
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
        matching = [
            json.loads(line)
            for line in self.output
            if json.loads(line).get("reason") == "matching_run_exists"
        ]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]["run_id"], state["run_id"])

    def test_refusal_names_existing_run_and_exact_next_command(self):
        initial = self.create_paused_run()
        run_root = self.paths.state_home / initial["run_id"]
        runner_path = "./skills/kws-codex-plan-runner/scripts/runner"
        cases = (
            ("running", None, ExitCode.RESUMABLE, "inspect"),
            ("recovering", None, ExitCode.RESUMABLE, "inspect"),
            ("resumable", None, ExitCode.RESUMABLE, "resume"),
            (
                "blocked",
                {"reason_code": "host_permission_blocked", "detail": "filesystem"},
                ExitCode.BLOCKED,
                "blocked",
            ),
            (
                "failed",
                {
                    "reason_code": "recovery_exhausted",
                    "detail": "strategies exhausted",
                    "failure_sequence": [],
                    "strategy_digests": [],
                    "next_strategy": "fresh_root_full_diff",
                },
                ExitCode.FAILED,
                "retry_failed",
            ),
            ("ready_for_integration", None, ExitCode.READY, "inspect"),
        )

        for status, failure, expected_code, action_kind in cases:
            with self.subTest(status=status, action_kind=action_kind):
                store = StateStore.open(run_root)
                state = store.snapshot()
                state["status"] = status
                state["failure"] = failure
                state = store.commit(state)
                run_id = state["run_id"]
                expected_actions = {
                    "inspect": f"{runner_path} inspect --run-id {run_id}",
                    "resume": f"{runner_path} resume --run-id {run_id}",
                    "blocked": (
                        "fix the named blocker, then "
                        f"{runner_path} resume --run-id {run_id} --retry-blocked"
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
                self.assertEqual(response["run_id"], run_id)
                self.assertEqual(response["status"], status)
                self.assertEqual(response["branch"], state["repository"]["branch"])
                self.assertEqual(response["worktree"], state["repository"]["worktree"])
                self.assertEqual(
                    response["recommended_action"],
                    expected_actions[action_kind],
                )

    def test_failed_or_ready_equivalent_run_is_not_replayed(self):
        initial = self.create_paused_run()
        run_root = self.paths.state_home / initial["run_id"]
        cases = (
            (
                {
                    "reason_code": "recovery_exhausted",
                    "detail": "retryable",
                    "failure_sequence": [],
                    "strategy_digests": [],
                    "next_strategy": "fresh_root_full_diff",
                },
                ExitCode.FAILED,
                "matching_run_exists",
            ),
            (
                {
                    "reason_code": "state_integrity_failed",
                    "detail": "known volatile ref drift",
                    "repair_kind": "volatile-codex-turn-refs",
                },
                ExitCode.INTEGRITY,
                "matching_run_unproven",
            ),
            (
                {"reason_code": "state_integrity_failed", "detail": "unknown drift"},
                ExitCode.INTEGRITY,
                "matching_run_unproven",
            ),
            (None, ExitCode.READY, "matching_run_exists"),
        )

        for failure, expected_code, reason in cases:
            with self.subTest(failure=failure):
                store = StateStore.open(run_root)
                state = store.snapshot()
                state["status"] = (
                    "ready_for_integration" if failure is None else "failed"
                )
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
                self.assertEqual(self.matching_response()["reason"], reason)
                self.assertEqual(len(list(self.paths.state_home.iterdir())), 1)
                self.assertEqual(len(list(self.paths.worktree_home.iterdir())), 1)
                self.assertEqual(
                    git(
                        "for-each-ref",
                        "--format=%(refname) %(objectname)",
                        cwd=self.source,
                    ),
                    before_refs,
                )

    def test_matching_tampered_root_fails_closed(self):
        initial = self.create_paused_run()
        run_root = self.paths.state_home / initial["run_id"]
        state_path = run_root / "state.json"
        tampered = json.loads(state_path.read_text(encoding="utf-8"))
        tampered["state_digest"] = "0" * 64
        state_path.write_text(
            json.dumps(tampered, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        before_refs = git(
            "for-each-ref", "--format=%(refname) %(objectname)", cwd=self.source
        )
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
        self.assertEqual(response["status"], "invalid")
        self.assertEqual(response["branch"], initial["repository"]["branch"])
        self.assertEqual(response["worktree"], initial["repository"]["worktree"])
        self.assertEqual(
            response["recommended_action"], "preserve evidence and stop"
        )
        create_state.assert_not_called()
        create_worktree.assert_not_called()
        self.assertEqual(len(list(self.paths.state_home.iterdir())), 1)
        self.assertEqual(len(list(self.paths.worktree_home.iterdir())), 1)
        self.assertEqual(
            git("for-each-ref", "--format=%(refname) %(objectname)", cwd=self.source),
            before_refs,
        )

    def test_large_valid_matching_state_is_discovered_without_duplicate_admission(self):
        initial = self.create_paused_run()
        run_root = self.paths.state_home / initial["run_id"]
        store = StateStore.open(run_root)
        state = store.snapshot()
        state["failure"] = {"detail": "x" * (2 * 1024 * 1024 + 4096)}
        store.commit(state)
        self.assertGreater((run_root / "state.json").stat().st_size, 2 * 1024 * 1024)
        self.output.clear()

        with (
            mock.patch(
                "plan_runner.engine._run_id", wraps=engine_module._run_id
            ) as allocate_id,
            mock.patch.object(
                PlanRunner, "_execute", return_value=int(ExitCode.RESUMABLE)
            ),
        ):
            code = self.runner().create_run(
                specs=self.specs,
                plans=self.plans[:1],
                workspace=self.source,
                stall_seconds=30,
                sandbox="danger-full-access",
                model="different-model",
            )

        self.assertEqual(code, ExitCode.RESUMABLE)
        self.assertEqual(self.matching_response()["run_id"], initial["run_id"])
        allocate_id.assert_not_called()
        self.assertEqual(len(list(self.paths.state_home.iterdir())), 1)
        self.assertEqual(len(list(self.paths.worktree_home.iterdir())), 1)

    def admission_record_path(self, state):
        lock_home = self.paths.state_home.with_name(
            f".{self.paths.state_home.name}-intent-locks"
        )
        return lock_home / (
            state["immutable_config"]["execution_intent_digest"] + ".json"
        )

    def test_recomputed_envelope_substitution_cannot_hide_original_intent(self):
        initial = self.create_paused_run()
        run_root = self.paths.state_home / initial["run_id"]
        envelope_path = run_root / "intent.json"
        envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
        envelope["execution_intent_digest"] = "b" * 64
        envelope["envelope_digest"] = storage_module._intent_envelope_digest(
            envelope
        )
        envelope_path.write_bytes(storage_module.canonical_json(envelope))
        self.output.clear()

        with (
            mock.patch("plan_runner.engine._run_id") as allocate_id,
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
        allocate_id.assert_not_called()
        create_state.assert_not_called()
        create_worktree.assert_not_called()
        self.assertFalse(self.adapter_values)

    def assert_matching_admission_record_fails_closed(self, mutate):
        initial = self.create_paused_run()
        record_path = self.admission_record_path(initial)
        mutate(record_path)
        self.output.clear()

        with (
            mock.patch("plan_runner.engine._run_id") as allocate_id,
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
        allocate_id.assert_not_called()
        create_state.assert_not_called()
        create_worktree.assert_not_called()
        self.assertFalse(self.adapter_values)

    def test_missing_digest_keyed_admission_record_fails_closed(self):
        self.assert_matching_admission_record_fails_closed(
            lambda path: path.unlink(missing_ok=True)
        )

    def test_tampered_digest_keyed_admission_record_fails_closed(self):
        def substitute(path):
            record = json.loads(path.read_text(encoding="utf-8"))
            record["execution_intent_digest"] = "b" * 64
            record["record_digest"] = storage_module._admission_record_digest(
                record
            )
            path.write_bytes(storage_module.canonical_json(record))

        self.assert_matching_admission_record_fails_closed(
            substitute
        )

    def test_admission_record_pointing_to_missing_state_fails_closed(self):
        self.output.clear()
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
        lock_home = self.paths.state_home.with_name(
            f".{self.paths.state_home.name}-intent-locks"
        )
        records = list(lock_home.glob("*.json"))
        self.assertEqual(len(records), 1)
        self.output.clear()

        with (
            mock.patch("plan_runner.engine._run_id") as allocate_id,
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
        response = self.matching_response()
        self.assertEqual(response["reason"], "matching_run_unproven")
        allocate_id.assert_not_called()
        create_state.assert_not_called()
        create_worktree.assert_not_called()
        self.assertFalse(self.paths.worktree_home.exists())
        self.assertFalse(self.adapter_values)

    def test_unrelated_oversized_legacy_state_does_not_match_arbitrary_intent(self):
        legacy_id = "legacy-12345678-1234-4234-8234-123456789abc"
        store = StateStore.create(
            root=self.paths.state_home / legacy_id,
            provider="codex",
            run_id=legacy_id,
            source_repository=self.source,
            source_commit=self.starting_head,
            worktree=self.root / "legacy-worktree",
            branch=f"codex-plan/{legacy_id}",
            specs=self.specs,
            plans=self.plans[:1],
            immutable_config={
                "git_identity": {
                    "name": "Engine Test",
                    "email": "engine@example.test",
                }
            },
            runner_runtime=dataclasses.asdict(runtime_identity()),
        )
        legacy = store.snapshot()
        legacy["failure"] = {"detail": "x" * (2 * 1024 * 1024 + 4096)}
        store.commit(legacy)

        with mock.patch.object(
            PlanRunner, "_execute", return_value=int(ExitCode.RESUMABLE)
        ):
            code = self.runner().create_run(
                specs=self.specs,
                plans=self.plans[:1],
                workspace=self.source,
                stall_seconds=30,
                sandbox="workspace-write",
                model=None,
            )

        self.assertEqual(code, ExitCode.RESUMABLE)
        self.assertEqual(len(list(self.paths.state_home.iterdir())), 2)
        self.assertEqual(len(list(self.paths.worktree_home.iterdir())), 1)

    def test_unrelated_oversized_invalid_root_does_not_match_arbitrary_intent(self):
        invalid_root = (
            self.paths.state_home
            / "invalid-12345678-1234-4234-8234-123456789abc"
        )
        invalid_root.mkdir(mode=0o700, parents=True)
        (invalid_root / "state.json").write_bytes(
            b"x" * (2 * 1024 * 1024 + 4096)
        )

        with mock.patch.object(
            PlanRunner, "_execute", return_value=int(ExitCode.RESUMABLE)
        ):
            code = self.runner().create_run(
                specs=self.specs,
                plans=self.plans[:1],
                workspace=self.source,
                stall_seconds=30,
                sandbox="workspace-write",
                model=None,
            )

        self.assertEqual(code, ExitCode.RESUMABLE)
        self.assertEqual(len(list(self.paths.state_home.iterdir())), 2)
        self.assertEqual(len(list(self.paths.worktree_home.iterdir())), 1)

    def assert_matching_intent_evidence_fails_closed(self, mutate):
        initial = self.create_paused_run()
        run_root = self.paths.state_home / initial["run_id"]
        mutate(run_root / "intent.json", initial)
        self.output.clear()

        with (
            mock.patch(
                "plan_runner.engine._run_id", wraps=engine_module._run_id
            ) as allocate_id,
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
        allocate_id.assert_not_called()
        create_state.assert_not_called()
        create_worktree.assert_not_called()
        self.assertEqual(len(list(self.paths.state_home.iterdir())), 1)
        self.assertEqual(len(list(self.paths.worktree_home.iterdir())), 1)

    def test_missing_matching_intent_envelope_fails_closed(self):
        self.assert_matching_intent_evidence_fails_closed(
            lambda path, _state: path.unlink(missing_ok=True)
        )

    def test_tampered_matching_intent_envelope_fails_closed(self):
        def tamper(path, state):
            path.write_text(
                json.dumps(
                    {
                        "execution_intent_digest": state["immutable_config"][
                            "execution_intent_digest"
                        ],
                        "run_id": state["run_id"],
                        "envelope_digest": "0" * 64,
                    }
                ),
                encoding="utf-8",
            )

        self.assert_matching_intent_evidence_fails_closed(tamper)

    def test_oversized_matching_intent_envelope_fails_closed(self):
        self.assert_matching_intent_evidence_fails_closed(
            lambda path, _state: path.write_bytes(b"x" * (64 * 1024 + 1))
        )

    def test_unknown_or_nonretryable_failed_state_is_not_offered_retry(self):
        initial = self.create_paused_run()
        run_root = self.paths.state_home / initial["run_id"]
        cases = (
            None,
            {"reason_code": "recovery_exhausted"},
            {
                "reason_code": "input_changed_requires_new_run",
                "failure_sequence": [],
                "strategy_digests": [],
                "next_strategy": "fresh_root_full_diff",
            },
            {
                "reason_code": "recovery_exhausted",
                "failure_sequence": [],
                "strategy_digests": [],
                "next_strategy": "block",
            },
        )

        for failure in cases:
            with self.subTest(failure=failure):
                store = StateStore.open(run_root)
                state = store.snapshot()
                state["status"] = "failed"
                state["failure"] = failure
                store.commit(state)
                self.output.clear()

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
                self.assertEqual(
                    response["recommended_action"], "preserve evidence and stop"
                )

    def test_dirty_invalid_result_is_checkpointed_before_failure(self):
        implementation_launches = 0

        def invalid_then_block(_adapter, request, packet, session_id):
            nonlocal implementation_launches
            if packet["mode"] != "implementation":
                return None
            implementation_launches += 1
            if implementation_launches == 1:
                (request.worktree / "partial.txt").write_text(
                    "partial implementation\n", encoding="utf-8"
                )
                return ProviderOutcome(
                    "implemented",
                    0,
                    session_id,
                    {"status": "implemented"},
                    None,
                    {},
                    (),
                    "",
                )
            return ProviderOutcome(
                "blocked",
                1,
                session_id,
                {
                    "status": "blocked",
                    "head_commit": git("rev-parse", "HEAD", cwd=request.worktree),
                    "summary": "external authority required",
                    "task_ledger": [],
                    "open_obligation_ids": [],
                    "failure_signature": None,
                    "strategy_note": None,
                    "blocker": {
                        "kind": "external_authority_required",
                        "detail": "host permission is required",
                    },
                },
                "external_authority_required",
                {},
                (),
                "",
            )

        self.outcome_hook = invalid_then_block
        code = self.runner().create_run(
            specs=self.specs,
            plans=self.plans[:1],
            workspace=self.source,
            stall_seconds=30,
            sandbox="workspace-write",
            model=None,
        )

        self.assertEqual(code, ExitCode.BLOCKED)
        state = self.state()
        first = next(
            item
            for item in state["attempts"]
            if item["mode"] == "implementation"
        )
        self.assertEqual(
            first["post_provider_worktree"],
            self.worktree_observation(state),
        )
        self.assertFalse(first["post_provider_worktree"]["clean"])
        self.assertEqual(first["provider_code"], "provider_result_invalid")
        self.assertEqual(first["next_strategy"], "fresh_root_full_diff")
        implementation_requests = [
            request
            for request, packet in zip(self.requests, self.packets, strict=True)
            if packet["mode"] == "implementation"
        ]
        self.assertEqual(len(implementation_requests), 2)
        self.assertIsNone(implementation_requests[1].session_id)

    def test_clean_invalid_result_retries_from_fresh_root_after_checkpoint(self):
        implementation_launches = 0

        def invalid_then_succeed(_adapter, _request, packet, session_id):
            nonlocal implementation_launches
            if packet["mode"] != "implementation":
                return None
            implementation_launches += 1
            if implementation_launches == 1:
                return ProviderOutcome(
                    "implemented",
                    0,
                    session_id,
                    {"status": "implemented"},
                    None,
                    {},
                    (),
                    "",
                )
            return None

        self.outcome_hook = invalid_then_succeed
        code = self.runner().create_run(
            specs=self.specs,
            plans=self.plans[:1],
            workspace=self.source,
            stall_seconds=30,
            sandbox="workspace-write",
            model=None,
        )

        self.assertEqual(code, ExitCode.READY)
        attempts = [
            item for item in self.state()["attempts"]
            if item["mode"] == "implementation"
        ]
        self.assertTrue(attempts[0]["post_provider_worktree"]["clean"])
        self.assertEqual(attempts[0]["provider_code"], "provider_result_invalid")
        self.assertEqual(attempts[0]["next_strategy"], "fresh_root_full_diff")
        requests = [
            request
            for request, packet in zip(self.requests, self.packets, strict=True)
            if packet["mode"] == "implementation"
        ]
        self.assertEqual(len(requests), 2)
        self.assertIsNone(requests[1].session_id)

    def test_dirty_malformed_stream_is_checkpointed_before_failure(self):
        self._assert_dirty_stream_checkpoint(
            "provider_stream_malformed",
            "failed",
        )

    def test_dirty_oversized_stream_is_checkpointed_before_failure(self):
        self._assert_dirty_stream_checkpoint(
            "provider_stream_oversized",
            "failed",
        )

    def _assert_dirty_stream_checkpoint(self, provider_code, outcome_kind):
        def dirty_failure_then_block(_adapter, request, packet, session_id):
            if packet["mode"] != "implementation":
                return None
            prior = [
                item
                for item in self.state()["attempts"]
                if item["mode"] == "implementation"
            ]
            if len(prior) == 1:
                (request.worktree / "partial.txt").write_text(
                    "partial implementation\n", encoding="utf-8"
                )
                return ProviderOutcome(
                    outcome_kind,
                    1,
                    session_id,
                    None,
                    provider_code,
                    {},
                    (),
                    "",
                )
            return ProviderOutcome(
                "blocked",
                1,
                session_id,
                {
                    "status": "blocked",
                    "head_commit": git("rev-parse", "HEAD", cwd=request.worktree),
                    "summary": "external authority required",
                    "task_ledger": [],
                    "open_obligation_ids": [],
                    "failure_signature": None,
                    "strategy_note": None,
                    "blocker": {
                        "kind": "external_authority_required",
                        "detail": "host permission is required",
                    },
                },
                "external_authority_required",
                {},
                (),
                "",
            )

        self.outcome_hook = dirty_failure_then_block
        code = self.runner().create_run(
            specs=self.specs,
            plans=self.plans[:1],
            workspace=self.source,
            stall_seconds=30,
            sandbox="workspace-write",
            model=None,
        )
        self.assertEqual(code, ExitCode.BLOCKED)
        state = self.state()
        first = next(
            item
            for item in state["attempts"]
            if item["mode"] == "implementation"
        )
        self.assertEqual(first["provider_code"], provider_code)
        self.assertEqual(first["post_provider_worktree"], self.worktree_observation(state))
        self.assertFalse(first["post_provider_worktree"]["clean"])

    def test_final_review_fix_failure_uses_the_same_checkpoint_order(self):
        self.review_findings_once = True
        fix_launches = 0
        checkpoint = []

        def invalid_then_fix(_adapter, request, packet, session_id):
            nonlocal fix_launches
            if packet["mode"] != "final_review_fix":
                return None
            fix_launches += 1
            partial = request.worktree / "partial.txt"
            if fix_launches == 1:
                partial.write_text("partial review fix\n", encoding="utf-8")
                return ProviderOutcome(
                    "implemented",
                    0,
                    session_id,
                    {"status": "implemented"},
                    None,
                    {},
                    (),
                    "",
                )
            git("add", partial.name, cwd=request.worktree)
            return None

        def capture_checkpoint(stage):
            if (
                stage == "provider_outcome_received"
                and self.packets
                and self.packets[-1]["mode"] == "final_review_fix"
                and not checkpoint
            ):
                checkpoint.append(self.worktree_observation())

        self.outcome_hook = invalid_then_fix
        self.engine_event_hook = capture_checkpoint
        code = self.runner().create_run(
            specs=self.specs,
            plans=self.plans[:1],
            workspace=self.source,
            stall_seconds=30,
            sandbox="workspace-write",
            model=None,
        )
        self.assertEqual(code, ExitCode.READY)
        fixes = [
            item for item in self.state()["attempts"]
            if item["mode"] == "final_review_fix"
        ]
        self.assertEqual(fixes[0]["post_provider_worktree"], checkpoint[0])
        self.assertFalse(checkpoint[0]["clean"])
        self.assertEqual(fixes[0]["provider_code"], "provider_result_invalid")
        self.assertEqual(fixes[0]["next_strategy"], "fresh_root_full_diff")
        fix_requests = [
            request
            for request, packet in zip(self.requests, self.packets, strict=True)
            if packet["mode"] == "final_review_fix"
        ]
        self.assertEqual(len(fix_requests), 2)
        self.assertIsNone(fix_requests[1].session_id)

    def test_clean_final_review_fix_invalid_result_uses_fresh_root(self):
        self.review_findings_once = True
        fix_launches = 0

        def invalid_then_fix(_adapter, _request, packet, session_id):
            nonlocal fix_launches
            if packet["mode"] != "final_review_fix":
                return None
            fix_launches += 1
            if fix_launches == 1:
                return ProviderOutcome(
                    "implemented",
                    0,
                    session_id,
                    {"status": "implemented"},
                    None,
                    {},
                    (),
                    "",
                )
            return None

        self.outcome_hook = invalid_then_fix
        code = self.runner().create_run(
            specs=self.specs,
            plans=self.plans[:1],
            workspace=self.source,
            stall_seconds=30,
            sandbox="workspace-write",
            model=None,
        )

        self.assertEqual(code, ExitCode.READY)
        attempts = [
            item for item in self.state()["attempts"]
            if item["mode"] == "final_review_fix"
        ]
        self.assertTrue(attempts[0]["post_provider_worktree"]["clean"])
        self.assertEqual(attempts[0]["provider_code"], "provider_result_invalid")
        self.assertEqual(attempts[0]["next_strategy"], "fresh_root_full_diff")
        requests = [
            request
            for request, packet in zip(self.requests, self.packets, strict=True)
            if packet["mode"] == "final_review_fix"
        ]
        self.assertEqual(len(requests), 2)
        self.assertIsNone(requests[1].session_id)

    def test_dirty_finalization_attempt_is_durable_before_blocking(self):
        checkpoint_revision = []

        def dirty_finalization(_adapter, request, _packet, _session_id, _digest):
            (request.worktree / "finalization-drift.txt").write_text(
                "forbidden finalization mutation\n", encoding="utf-8"
            )
            return None

        def capture_revision(stage):
            if (
                stage == "provider_outcome_received"
                and self.packets
                and self.packets[-1]["mode"] == "finalization"
            ):
                checkpoint_revision.append(self.state()["revision"])

        self.after_final_hook = dirty_finalization
        self.engine_event_hook = capture_revision
        code = self.runner().create_run(
            specs=self.specs,
            plans=self.plans[:1],
            workspace=self.source,
            stall_seconds=30,
            sandbox="workspace-write",
            model=None,
        )

        self.assertEqual(code, ExitCode.INTEGRITY)
        state = self.state()
        attempt = next(
            item for item in reversed(state["attempts"])
            if item["mode"] == "finalization"
        )
        self.assertTrue(attempt["completed"])
        self.assertEqual(
            attempt["post_provider_worktree"],
            self.worktree_observation(state),
        )
        self.assertFalse(attempt["post_provider_worktree"]["clean"])
        self.assertGreaterEqual(state["revision"], checkpoint_revision[0] + 2)
        self.assertEqual(state["failure"]["next_strategy"], "block")
        self.assertNotIn("partial_worktree", state["failure"])

    def test_dirty_checkpoint_rejects_branch_or_product_ref_drift(self):
        def drift_branch(_adapter, request, packet, session_id):
            if packet["mode"] != "implementation":
                return None
            (request.worktree / "partial.txt").write_text(
                "partial implementation\n", encoding="utf-8"
            )
            git("switch", "-c", "provider-drift", cwd=request.worktree)
            return ProviderOutcome(
                "failed",
                1,
                session_id,
                None,
                "provider_stream_malformed",
                {},
                (),
                "",
            )

        self.outcome_hook = drift_branch
        code = self.runner().create_run(
            specs=self.specs,
            plans=self.plans[:1],
            workspace=self.source,
            stall_seconds=30,
            sandbox="workspace-write",
            model=None,
        )
        self.assertEqual(code, ExitCode.INTEGRITY)
        failure = self.state()["failure"]
        self.assertEqual(failure["reason_code"], "state_integrity_failed")
        self.assertEqual(failure["next_strategy"], "block")
        self.assertNotIn("partial_worktree", failure)

    def test_volatile_churn_does_not_break_resume_or_acceptance(self):
        mutated = False

        def churn_turn_diff_refs(_adapter, request, packet, _session_id):
            nonlocal mutated
            if packet["mode"] != "implementation" or mutated:
                return None
            mutated = True
            head = git("rev-parse", "HEAD", cwd=request.worktree)
            git(
                "update-ref",
                "refs/codex/turn-diffs/checkpoints/acceptance",
                head,
                cwd=request.worktree,
            )
            return None

        self.crash_after_session = True
        self.outcome_hook = churn_turn_diff_refs
        with self.assertRaises(SimulatedCrash):
            self.runner().create_run(
                specs=self.specs,
                plans=self.plans[:1],
                workspace=self.source,
                stall_seconds=30,
                sandbox="workspace-write",
                model=None,
            )
        state = self.state()
        worktree = Path(state["repository"]["worktree"])
        git(
            "update-ref",
            "refs/codex/turn-diffs/captures/resume",
            git("rev-parse", "HEAD", cwd=worktree),
            cwd=worktree,
        )

        code = self.runner().resume(
            state["run_id"],
            retry_blocked=False,
            retry_failed=False,
            strategy_note=None,
        )

        self.assertEqual(code, ExitCode.READY, [self.output, self.state().get("failure")])
        state = self.state()
        self.assertEqual(
            state["immutable_config"].get("volatile_ref_policy_version"),
            1,
        )

    def test_unknown_codex_ref_and_product_ref_mutation_still_fail_closed(self):
        for index, refname in enumerate(
            ("refs/codex/other/abc", "refs/tags/product-test")
        ):
            if index:
                self.tearDown()
                self.setUp()
            with self.subTest(refname=refname):
                def mutate_protected_ref(_adapter, request, packet, _session_id):
                    if packet["mode"] == "implementation":
                        git(
                            "update-ref",
                            refname,
                            git("rev-parse", "HEAD", cwd=request.worktree),
                            cwd=request.worktree,
                        )
                    return None

                self.outcome_hook = mutate_protected_ref
                code = self.runner().create_run(
                    specs=self.specs,
                    plans=self.plans[:1],
                    workspace=self.source,
                    stall_seconds=30,
                    sandbox="workspace-write",
                    model=None,
                )

                self.assertEqual(code, ExitCode.INTEGRITY)
                failure = self.state()["failure"]
                self.assertEqual(failure["reason_code"], "state_integrity_failed")
                self.assertEqual(failure["next_strategy"], "block")

    def test_legacy_ref_snapshot_without_policy_version_remains_readable(self):
        self.crash_after_session = True
        with self.assertRaises(SimulatedCrash):
            self.runner().create_run(
                specs=self.specs,
                plans=self.plans[:1],
                workspace=self.source,
                stall_seconds=30,
                sandbox="workspace-write",
                model=None,
            )
        state = self.state()
        state["immutable_config"].pop("volatile_ref_policy_version")
        state["immutable_config"]["protected_refs"][
            "refs/codex/turn-diffs/captures/legacy"
        ] = state["repository"]["source_commit"]
        state["state_digest"] = storage_module._state_digest(state)
        state_path = (
            self.paths.state_home / state["run_id"] / "state.json"
        )
        state_path.write_text(json.dumps(state), encoding="utf-8")

        code = self.runner().resume(
            state["run_id"],
            retry_blocked=False,
            retry_failed=False,
            strategy_note=None,
        )

        self.assertEqual(code, ExitCode.READY, [self.output, self.state().get("failure")])

    def test_present_volatile_ref_policy_version_requires_exact_integer(self):
        invalid_versions = (None, False, True, 1.0, "1", 2)
        for index, invalid_version in enumerate(invalid_versions):
            if index:
                self.tearDown()
                self.setUp()
            with self.subTest(invalid_version=invalid_version):
                self.crash_after_session = True
                with self.assertRaises(SimulatedCrash):
                    self.runner().create_run(
                        specs=self.specs,
                        plans=self.plans[:1],
                        workspace=self.source,
                        stall_seconds=30,
                        sandbox="workspace-write",
                        model=None,
                    )
                state = self.state()
                state["immutable_config"][
                    "volatile_ref_policy_version"
                ] = invalid_version
                state["state_digest"] = storage_module._state_digest(state)
                state_path = (
                    self.paths.state_home / state["run_id"] / "state.json"
                )
                state_path.write_text(json.dumps(state), encoding="utf-8")
                launch_count = len(self.requests)

                code = self.runner().resume(
                    state["run_id"],
                    retry_blocked=False,
                    retry_failed=False,
                    strategy_note=None,
                )

                self.assertEqual(code, ExitCode.INTEGRITY)
                self.assertEqual(len(self.requests), launch_count)
                self.assertEqual(
                    self.state()["failure"]["reason_code"],
                    "state_integrity_failed",
                )

    def test_clean_transport_loss_resumes_root_once_then_changes_strategy(self):
        failures = 0

        def fail_twice(_adapter, _request, packet, session_id):
            nonlocal failures
            if packet["mode"] == "implementation" and failures < 2:
                failures += 1
                return ProviderOutcome(
                    "transport_failed",
                    1,
                    session_id,
                    None,
                    "controller_transport_failed",
                    {},
                    (),
                    "",
                )
            return None

        self.outcome_hook = fail_twice
        code = self.runner().create_run(
            specs=self.specs,
            plans=self.plans[:1],
            workspace=self.source,
            stall_seconds=30,
            sandbox="workspace-write",
            model=None,
        )
        self.assertEqual(code, ExitCode.READY)
        attempts = [
            item for item in self.state()["attempts"]
            if item["mode"] == "implementation"
        ]
        self.assertEqual(attempts[0]["next_strategy"], "resume_root")
        self.assertEqual(attempts[1]["previous_failed_strategy"], "resume_root")
        self.assertEqual(attempts[1]["next_strategy"], "fresh_root_full_diff")
        requests = [
            request
            for request, packet in zip(self.requests, self.packets, strict=True)
            if packet["mode"] == "implementation"
        ]
        self.assertIsNone(requests[0].session_id)
        self.assertIsNotNone(requests[1].session_id)
        self.assertIsNone(requests[2].session_id)

    def test_safe_dirty_failure_uses_fresh_root_without_user_checkpoint(self):
        observed_requests = []

        def dirty_then_complete(_adapter, request, packet, session_id):
            if packet["mode"] != "implementation":
                return None
            observed_requests.append(request)
            partial = request.worktree / "partial.txt"
            if len(observed_requests) == 1:
                partial.write_text("partial implementation\n", encoding="utf-8")
                return ProviderOutcome(
                    "failed",
                    1,
                    session_id,
                    None,
                    "provider_stream_malformed",
                    {},
                    (),
                    "",
                )
            git("add", partial.name, cwd=request.worktree)
            return None

        self.outcome_hook = dirty_then_complete
        code = self.runner().create_run(
            specs=self.specs,
            plans=self.plans[:1],
            workspace=self.source,
            stall_seconds=30,
            sandbox="workspace-write",
            model=None,
        )
        self.assertEqual(code, ExitCode.READY)
        attempts = [
            item for item in self.state()["attempts"]
            if item["mode"] == "implementation"
        ]
        self.assertEqual(attempts[0]["next_strategy"], "fresh_root_full_diff")
        self.assertIsNone(observed_requests[1].session_id)
        self.assertNotIn("approval", json.dumps(attempts[0]).lower())
        retry_packet = [
            packet for packet in self.packets
            if packet["mode"] == "implementation"
        ][1]
        self.assertEqual(
            retry_packet["recovery_context"]["checkpoint"][
                "post_provider_worktree"
            ],
            attempts[0]["post_provider_worktree"],
        )
        self.assertEqual(
            retry_packet["recovery_context"]["next_strategy"],
            "fresh_root_full_diff",
        )

    def test_safe_dirty_transport_failure_launches_fresh_root_from_exact_checkpoint(self):
        observed_requests = []

        def dirty_transport_then_complete(
            _adapter, request, packet, session_id
        ):
            if packet["mode"] != "implementation":
                return None
            observed_requests.append(request)
            partial = request.worktree / "partial.txt"
            if len(observed_requests) == 1:
                partial.write_text(
                    "partial implementation\n", encoding="utf-8"
                )
                return ProviderOutcome(
                    "transport_failed",
                    1,
                    session_id,
                    None,
                    "controller_transport_failed",
                    {},
                    (),
                    "",
                )
            git("add", partial.name, cwd=request.worktree)
            return None

        self.outcome_hook = dirty_transport_then_complete
        code = self.runner().create_run(
            specs=self.specs,
            plans=self.plans[:1],
            workspace=self.source,
            stall_seconds=30,
            sandbox="workspace-write",
            model=None,
        )

        self.assertEqual(code, ExitCode.READY)
        attempts = [
            item
            for item in self.state()["attempts"]
            if item["mode"] == "implementation"
        ]
        self.assertFalse(attempts[0]["post_provider_worktree"]["clean"])
        self.assertEqual(
            attempts[0]["next_strategy"], "fresh_root_full_diff"
        )
        self.assertIsNone(observed_requests[1].session_id)
        retry_packet = [
            packet
            for packet in self.packets
            if packet["mode"] == "implementation"
        ][1]
        self.assertEqual(
            retry_packet["recovery_context"]["checkpoint"][
                "post_provider_worktree"
            ],
            attempts[0]["post_provider_worktree"],
        )

    def test_safe_dirty_resumed_session_failure_launches_fresh_root(self):
        observed_requests = []

        def transport_then_dirty_session_loss(
            _adapter, request, packet, session_id
        ):
            if packet["mode"] != "implementation":
                return None
            observed_requests.append(request)
            partial = request.worktree / "partial.txt"
            if len(observed_requests) == 1:
                return ProviderOutcome(
                    "transport_failed",
                    1,
                    session_id,
                    None,
                    "controller_transport_failed",
                    {},
                    (),
                    "",
                )
            if len(observed_requests) == 2:
                partial.write_text(
                    "partial implementation\n", encoding="utf-8"
                )
                return ProviderOutcome(
                    "resume_failed",
                    1,
                    session_id,
                    None,
                    "session_resume_failed",
                    {},
                    (),
                    "",
                )
            git("add", partial.name, cwd=request.worktree)
            return None

        self.outcome_hook = transport_then_dirty_session_loss
        code = self.runner().create_run(
            specs=self.specs,
            plans=self.plans[:1],
            workspace=self.source,
            stall_seconds=30,
            sandbox="workspace-write",
            model=None,
        )

        self.assertEqual(code, ExitCode.READY)
        attempts = [
            item
            for item in self.state()["attempts"]
            if item["mode"] == "implementation"
        ]
        self.assertEqual(attempts[0]["next_strategy"], "resume_root")
        self.assertFalse(attempts[1]["post_provider_worktree"]["clean"])
        self.assertEqual(
            attempts[1]["next_strategy"], "fresh_root_full_diff"
        )
        self.assertIsNone(observed_requests[0].session_id)
        self.assertIsNotNone(observed_requests[1].session_id)
        self.assertIsNone(observed_requests[2].session_id)

    def test_external_authority_or_unsafe_identity_blocks(self):
        cases = [
            (
                {
                    "clean": True,
                    "session_id": str(uuid.uuid4()),
                    "reason_code": "provider_auth_blocked",
                    "previous_failed_strategy": None,
                    "safe": True,
                },
                ("block", "provider_auth_blocked"),
            ),
            (
                {
                    "clean": True,
                    "session_id": str(uuid.uuid4()),
                    "reason_code": "provider_capability_blocked",
                    "previous_failed_strategy": None,
                    "safe": True,
                },
                ("block", "provider_capability_blocked"),
            ),
            (
                {
                    "clean": True,
                    "session_id": str(uuid.uuid4()),
                    "reason_code": "sandbox_capability_blocked",
                    "previous_failed_strategy": None,
                    "safe": True,
                },
                ("block", "sandbox_capability_blocked"),
            ),
            (
                {
                    "clean": True,
                    "session_id": str(uuid.uuid4()),
                    "reason_code": "host_permission_blocked",
                    "previous_failed_strategy": None,
                    "safe": True,
                },
                ("block", "host_permission_blocked"),
            ),
            (
                {
                    "clean": False,
                    "session_id": None,
                    "reason_code": "state_integrity_failed",
                    "previous_failed_strategy": None,
                    "safe": False,
                },
                ("block", "state_integrity_failed"),
            ),
        ]
        for inputs, expected in cases:
            with self.subTest(inputs=inputs):
                decision = PlanRunner._select_root_strategy(**inputs)
                self.assertEqual(
                    (decision["action"], decision["reason_code"]),
                    expected,
                )

    def test_permission_failure_after_edit_retains_task3_checkpoint(self):
        launches = 0

        def dirty_then_permission_blocked(
            _adapter, request, packet, session_id
        ):
            nonlocal launches
            if packet["mode"] != "implementation":
                return None
            launches += 1
            (request.worktree / "permission-partial.txt").write_text(
                "durable partial implementation\n",
                encoding="utf-8",
            )
            return ProviderOutcome(
                "blocked",
                1,
                session_id,
                None,
                "host_permission_blocked",
                {},
                (),
                "",
            )

        self.outcome_hook = dirty_then_permission_blocked
        code = self.runner().create_run(
            specs=self.specs,
            plans=self.plans[:1],
            workspace=self.source,
            stall_seconds=30,
            sandbox="danger-full-access",
            model=None,
        )

        self.assertEqual(code, ExitCode.BLOCKED)
        self.assertEqual(launches, 1)
        state = self.state()
        attempt = state["attempts"][-1]
        observation = self.worktree_observation(state)
        self.assertEqual(attempt["post_provider_worktree"], observation)
        self.assertEqual(state["failure"]["partial_worktree"], observation)
        self.assertEqual(state["failure"]["reason_code"], "host_permission_blocked")
        self.assertEqual(state["failure"]["next_strategy"], "block")
        self.assertEqual(state["failure"]["next_session_action"], "none")
        self.assertNotIn("approval", json.dumps(state).lower())

    def test_retry_blocked_permission_failure_forces_fresh_session(self):
        launches = 0

        def permission_blocked_twice(
            _adapter, request, packet, session_id
        ):
            nonlocal launches
            if packet["mode"] != "implementation":
                return None
            launches += 1
            if launches == 1:
                (request.worktree / "permission-partial.txt").write_text(
                    "durable partial implementation\n",
                    encoding="utf-8",
                )
            return ProviderOutcome(
                "blocked",
                1,
                session_id,
                None,
                "host_permission_blocked",
                {},
                (),
                "",
            )

        self.outcome_hook = permission_blocked_twice
        runner = self.runner()
        initial_code = runner.create_run(
            specs=self.specs,
            plans=self.plans[:1],
            workspace=self.source,
            stall_seconds=30,
            sandbox="danger-full-access",
            model=None,
        )
        initial_state = self.state()
        initial_checkpoint = initial_state["failure"]["partial_worktree"]
        captured_session = initial_state["sessions"][-1]["session_id"]

        retry_code = self.runner().resume(
            initial_state["run_id"],
            retry_blocked=True,
            retry_failed=False,
            strategy_note=None,
        )

        self.assertEqual(initial_code, ExitCode.BLOCKED)
        self.assertEqual(retry_code, ExitCode.BLOCKED)
        self.assertEqual(launches, 2)
        self.assertIsNone(self.requests[-1].session_id)
        retried_state = self.state()
        self.assertEqual(
            retried_state["failure"]["partial_worktree"],
            initial_checkpoint,
        )
        self.assertNotEqual(
            retried_state["sessions"][-1]["session_id"],
            captured_session,
        )

    def test_top_level_auth_error_blocks_without_retry_or_worktree_mutation(self):
        codex_home = self.root / "auth-error-codex-home"
        make_codex_home(codex_home)
        fake_bin = self.root / "auth-error-bin"
        fake_bin.mkdir()
        fake = SKILL_ROOT / "evals" / "fake_codex.py"
        fake.chmod(fake.stat().st_mode | 0o100)
        (fake_bin / "codex").symlink_to(fake)
        sequence = self.root / "auth-error-sequence.json"
        sequence.write_text(
            json.dumps(
                {
                    "protocol_version": 1,
                    "actions": ["top-level-auth-error"],
                    "next_index": 0,
                }
            ),
            encoding="utf-8",
        )
        launch_log = self.root / "auth-error-launches.jsonl"
        environment = {
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            "CODEX_HOME": str(codex_home),
            "OPENAI_API_KEY": "test-token",
            "PLAN_RUNNER_FAKE_SEQUENCE": str(sequence),
            "PLAN_RUNNER_FAKE_LOG": str(launch_log),
        }
        runner = PlanRunner(
            self.paths,
            runtime_checker=runtime_identity,
            output=self.output.append,
            environment=environment,
        )

        code = runner.create_run(
            specs=self.specs,
            plans=self.plans[:1],
            workspace=self.source,
            stall_seconds=30,
            sandbox="workspace-write",
            model=None,
        )

        self.assertEqual(code, ExitCode.BLOCKED)
        self.assertEqual(git("rev-parse", "HEAD", cwd=self.source), self.starting_head)
        self.assertEqual(git("status", "--porcelain", cwd=self.source), "")
        launches = launch_log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(launches), 1)
        state = self.state()
        self.assertEqual(state["failure"]["reason_code"], "provider_auth_blocked")
        self.assertEqual(
            git("status", "--porcelain", cwd=Path(state["repository"]["worktree"])),
            "",
        )

    def test_runtime_paths_are_immutable(self):
        with self.assertRaises(dataclasses.FrozenInstanceError):
            self.paths.state_home = self.root / "other"

    def test_missing_git_identity_blocks_before_state_worktree_or_provider(self):
        git("config", "--unset", "user.email", cwd=self.source)
        isolated_home = self.root / "isolated-home"
        isolated_home.mkdir()
        with mock.patch.dict(
            os.environ,
            {"HOME": str(isolated_home), "GIT_CONFIG_NOSYSTEM": "1"},
        ):
            code = self.runner().create_run(
                specs=self.specs,
                plans=self.plans[:1],
                workspace=self.source,
                stall_seconds=30,
                sandbox="workspace-write",
                model=None,
            )

        self.assertEqual(code, ExitCode.INVALID)
        self.assertEqual(self.adapter_values, [])
        self.assertFalse(self.paths.state_home.exists())
        self.assertFalse(self.paths.worktree_home.exists())
        self.assertEqual(
            git(
                "for-each-ref",
                "--format=%(refname)",
                "refs/heads/codex-plan",
                cwd=self.source,
            ),
            "",
        )

    def test_identity_is_sealed_and_passed_to_every_provider_request(self):
        self.crash_after_session = True
        self.review_findings_once = True
        runner = self.runner()
        with self.assertRaises(SimulatedCrash):
            runner.create_run(
                specs=self.specs,
                plans=self.plans[:1],
                workspace=self.source,
                stall_seconds=30,
                sandbox="workspace-write",
                model=None,
            )
        state = self.state()
        self.assertEqual(
            state["immutable_config"].get("git_identity"),
            {"name": "Engine Test", "email": "engine@example.test"},
        )

        code = self.runner().resume(
            state["run_id"],
            retry_blocked=False,
            retry_failed=False,
            strategy_note=None,
        )

        self.assertEqual(code, ExitCode.READY)
        implementation_requests = [
            request
            for request, packet in zip(self.requests, self.packets, strict=True)
            if packet["mode"] == "implementation"
        ]
        review_fix_request = next(
            request
            for request, packet in zip(self.requests, self.packets, strict=True)
            if packet["mode"] == "final_review_fix"
        )
        self.assertEqual(len(implementation_requests), 2)
        self.assertIsNone(implementation_requests[0].session_id)
        self.assertIsNotNone(implementation_requests[1].session_id)
        expected = GitIdentity("Engine Test", "engine@example.test")
        self.assertEqual(
            [
                getattr(request, "git_identity", None)
                for request in (*implementation_requests, review_fix_request)
            ],
            [expected, expected, expected],
        )

    def test_candidate_with_wrong_committer_identity_fails_closed(self):
        def commit_with_wrong_identity(
            _adapter, request, packet, session_id
        ):
            if packet["mode"] != "implementation":
                return None
            marker = request.worktree / "wrong-identity.txt"
            marker.write_text("wrong identity\n", encoding="utf-8")
            git("add", marker.name, cwd=request.worktree)
            git(
                "-c",
                "user.name=Wrong",
                "-c",
                "user.email=wrong@example.test",
                "commit",
                "-m",
                "commit with wrong identity",
                cwd=request.worktree,
            )
            head = git("rev-parse", "HEAD", cwd=request.worktree)
            return ProviderOutcome(
                "implemented",
                0,
                session_id,
                {
                    "status": "implemented",
                    "head_commit": head,
                    "summary": "wrong identity",
                    "task_ledger": [],
                    "open_obligation_ids": [],
                    "failure_signature": None,
                    "strategy_note": None,
                    "blocker": None,
                },
                None,
                {},
                (),
                "",
            )

        self.outcome_hook = commit_with_wrong_identity
        code = self.runner().create_run(
            specs=self.specs,
            plans=self.plans[:1],
            workspace=self.source,
            stall_seconds=30,
            sandbox="workspace-write",
            model=None,
        )

        self.assertEqual(code, ExitCode.INTEGRITY)
        state = self.state()
        self.assertEqual(state["failure"]["reason_code"], "state_integrity_failed")
        self.assertNotEqual(state["plans"][0]["status"], "implemented")
        self.assertFalse(
            any(item["kind"] == "plan_handoff" for item in state["artifact_refs"])
        )

    def _assert_graceful_dirty_signal_checkpoint(
        self, signum, *, drift=False, clean_drift=False
    ):
        home = self.root / "home"
        codex_home = self.root / "codex-home"
        make_codex_home(codex_home)
        fake_bin = self.root / "fake-bin"
        fake_bin.mkdir()
        fake = SKILL_ROOT / "evals" / "fake_codex.py"
        fake.chmod(fake.stat().st_mode | 0o100)
        (fake_bin / "codex").symlink_to(fake)
        sequence = self.root / "signal-sequence.json"
        sequence.write_text(
            json.dumps(
                {
                    "protocol_version": 1,
                    "actions": [
                        "dirty-stalled",
                        "resume-dirty-implemented",
                        "finalized",
                    ],
                    "next_index": 0,
                }
            ),
            encoding="utf-8",
        )
        launch_log = self.root / "signal-launches.jsonl"
        environment = dict(os.environ)
        environment.update(
            {
                "HOME": str(home),
                "CODEX_HOME": str(codex_home),
                "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                "UV_PYTHON_INSTALL_DIR": str(Path(sys.executable).parents[2]),
                "PLAN_RUNNER_FAKE_SEQUENCE": str(sequence),
                "PLAN_RUNNER_FAKE_LOG": str(launch_log),
            }
        )
        process = subprocess.Popen(
            [
                sys.executable,
                str(SKILL_ROOT / "scripts" / "runner.py"),
                "run",
                "--spec",
                str(self.specs[0]),
                "--plan",
                str(self.plans[0]),
                "--workspace",
                str(self.source),
                "--stall-seconds",
                "30",
            ],
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        state_path = None
        partial = None
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            roots = list((home / ".codex" / "plan-runner").glob("*/state.json"))
            if roots:
                candidate = json.loads(roots[0].read_text(encoding="utf-8"))
                partial = (
                    Path(candidate["repository"]["worktree"])
                    / "partial-provider-edit.txt"
                )
                if candidate["sessions"] and partial.is_file():
                    state_path = roots[0]
                    break
            time.sleep(0.02)
        self.assertIsNotNone(state_path, "dirty provider session was not captured")
        process.send_signal(signum)
        stdout, stderr = process.communicate(timeout=10)
        self.assertEqual(
            process.returncode,
            ExitCode.RESUMABLE,
            [
                stdout,
                stderr,
                json.loads(state_path.read_text(encoding="utf-8")).get("failure"),
            ],
        )
        self.assertEqual(stderr, "")
        self.assertEqual(json.loads(stdout.splitlines()[-1])["status"], "resumable")
        checkpoint = json.loads(state_path.read_text(encoding="utf-8"))
        sealed = checkpoint["failure"]["partial_worktree"]
        self.assertEqual(
            checkpoint["failure"]["partial_attempt_id"],
            checkpoint["attempts"][-1]["attempt_id"],
        )
        self.assertEqual(checkpoint["failure"]["partial_mode"], "implementation")
        self.assertEqual(sealed["branch"], checkpoint["repository"]["branch"])
        self.assertEqual(sealed["head"], git("rev-parse", "HEAD", cwd=partial.parent))
        self.assertFalse(sealed["clean"])
        self.assertEqual(len(sealed["porcelain_digest"]), 64)
        self.assertEqual(len(sealed["tree_digest"]), 64)
        first_launch = json.loads(launch_log.read_text().splitlines()[0])
        with self.assertRaises(ProcessLookupError):
            os.kill(first_launch["pid"], 0)

        if clean_drift:
            partial.unlink()
        elif drift:
            partial.write_text("operator drift\n", encoding="utf-8")
        resumed = subprocess.run(
            [
                sys.executable,
                str(SKILL_ROOT / "scripts" / "runner.py"),
                "resume",
                "--run-id",
                checkpoint["run_id"],
            ],
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
        if drift or clean_drift:
            self.assertEqual(resumed.returncode, ExitCode.INTEGRITY, resumed.stderr)
            self.assertEqual(len(launch_log.read_text().splitlines()), 1)
            return
        self.assertEqual(
            resumed.returncode,
            ExitCode.READY,
            [
                resumed.stdout,
                resumed.stderr,
                json.loads(state_path.read_text(encoding="utf-8")).get("failure"),
            ],
        )
        launches = [
            json.loads(line)
            for line in launch_log.read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(launches[1]["session_action"], "fresh")
        self.assertNotEqual(
            launches[1]["session_id"],
            checkpoint["sessions"][-1]["session_id"],
        )

    def test_sigint_seals_dirty_worktree_and_resumes_after_provider_cleanup(self):
        self._assert_graceful_dirty_signal_checkpoint(signal.SIGINT)

    def test_sigterm_seals_dirty_worktree_and_resumes_after_provider_cleanup(self):
        self._assert_graceful_dirty_signal_checkpoint(signal.SIGTERM)

    def test_dirty_resume_rejects_worktree_drift_before_provider_launch(self):
        self._assert_graceful_dirty_signal_checkpoint(signal.SIGINT, drift=True)

    def test_dirty_resume_rejects_dirty_to_clean_drift_before_provider_launch(self):
        self._assert_graceful_dirty_signal_checkpoint(
            signal.SIGINT, clean_drift=True
        )

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

    def test_later_plan_cannot_drop_prior_plan_handoff_commit(self):
        first_handoff = None

        def reset_second_plan(_adapter, request, packet, _session_id):
            nonlocal first_handoff
            if packet["mode"] != "implementation":
                return None
            if packet["current_plan"]["index"] == 0:
                return None
            first_handoff = git("rev-parse", "HEAD", cwd=request.worktree)
            git("reset", "--hard", self.starting_head, cwd=request.worktree)
            marker = request.worktree / "replacement-plan-1.txt"
            marker.write_text("replacement only\n", encoding="utf-8")
            git("add", marker.name, cwd=request.worktree)
            git(
                "-c",
                "user.name=Engine Test",
                "-c",
                "user.email=engine@example.test",
                "commit",
                "-m",
                "replace prior plan history",
                cwd=request.worktree,
            )
            head = git("rev-parse", "HEAD", cwd=request.worktree)
            return ProviderOutcome(
                "implemented",
                0,
                _session_id,
                {
                    "status": "implemented",
                    "head_commit": head,
                    "summary": "replacement",
                    "task_ledger": [],
                    "open_obligation_ids": [],
                    "failure_signature": None,
                    "strategy_note": None,
                    "blocker": None,
                },
                None,
                {},
                (),
                "",
            )

        self.outcome_hook = reset_second_plan
        code = self.runner().create_run(
            specs=self.specs,
            plans=self.plans,
            workspace=self.source,
            stall_seconds=30,
            sandbox="workspace-write",
            model=None,
        )

        self.assertEqual(code, ExitCode.INTEGRITY)
        self.assertIsNotNone(first_handoff)
        state = self.state()
        self.assertEqual(state["plans"][0]["status"], "implemented")
        self.assertNotEqual(state["plans"][1]["status"], "implemented")
        self.assertEqual(state["failure"]["reason_code"], "state_integrity_failed")
        self.assertIn("plan handoff", state["failure"]["detail"])

    def test_review_findings_use_distinct_fresh_fix_packet_then_new_final_head(self):
        self.review_findings_once = True
        code = self.runner().create_run(
            specs=self.specs,
            plans=self.plans,
            workspace=self.source,
            stall_seconds=30,
            sandbox="workspace-write",
            model="fixed-model",
        )
        self.assertEqual(code, ExitCode.READY)
        fix_packets = [
            packet
            for packet in self.packets
            if packet["mode"] == "final_review_fix"
        ]
        self.assertEqual(len(fix_packets), 1)
        packet = fix_packets[0]
        self.assertEqual(packet["review_findings"][0]["id"], "R1")
        self.assertEqual(len(packet["specifications"]), 2)
        self.assertEqual(len(packet["implemented_plans"]), 2)
        self.assertEqual(
            {item["status"] for item in packet["implemented_plans"]},
            {"implemented"},
        )
        first_final_packet = next(
            item for item in self.packets if item["mode"] == "finalization"
        )
        self.assertEqual(packet["candidate_head"], first_final_packet["candidate_head"])
        self.assertRegex(
            packet["invalidated_final_verification_set_digest"],
            r"^[0-9a-f]{64}$",
        )
        fix_request = next(
            request
            for request, item in zip(self.requests, self.packets, strict=True)
            if item["mode"] == "final_review_fix"
        )
        self.assertIsNone(fix_request.session_id)
        self.assertIn(
            "do not invent plans, tasks, or\nverification requirements",
            fix_request.prompt,
        )
        for request, request_packet in zip(
            self.requests, self.packets, strict=True
        ):
            if request_packet["mode"] == "finalization":
                continue
            lowered = request.prompt.lower()
            self.assertIn("do not merge, push, deploy", lowered)
        self.assertEqual(
            {request.model for request in self.requests}, {"fixed-model"}
        )
        final_heads = [
            packet["candidate_head"]
            for packet in self.packets
            if packet["mode"] == "finalization"
        ]
        self.assertEqual(len(final_heads), 2)
        self.assertNotEqual(final_heads[0], final_heads[1])
        state = self.state()
        self.assertEqual(
            state["finalization"]["candidate_head"], final_heads[-1]
        )
        self.assertNotEqual(
            state["finalization"]["verification_set_digest"],
            packet["invalidated_final_verification_set_digest"],
        )
        context = packet["recovery_context"]
        self.assertEqual(
            context["scope"], {"mode": "final_review_fix", "plan_index": 1}
        )
        self.assertEqual(context["failure_reason"], "review_failed")
        self.assertTrue(context["required_strategy_change"])
        self.assertEqual(context["attempted_strategies"], [])

    def test_review_fix_interruption_retries_review_fix_without_normal_plan_routing(self):
        self.review_findings_once = True
        interrupted = False

        def interrupt_once(_adapter, _request, packet, session_id):
            nonlocal interrupted
            if packet["mode"] == "final_review_fix" and not interrupted:
                interrupted = True
                return ProviderOutcome(
                    "transport_failed",
                    1,
                    session_id,
                    None,
                    "controller_transport_failed",
                    {},
                    (),
                    "",
                )
            return None

        self.outcome_hook = interrupt_once
        code = self.runner().create_run(
            specs=self.specs,
            plans=self.plans[:1],
            workspace=self.source,
            stall_seconds=30,
            sandbox="workspace-write",
            model=None,
        )
        self.assertEqual(code, ExitCode.READY)
        modes = [packet["mode"] for packet in self.packets]
        first_fix = modes.index("final_review_fix")
        self.assertEqual(
            modes[first_fix:first_fix + 3],
            ["final_review_fix", "final_review_fix", "finalization"],
        )
        self.assertNotIn("implementation", modes[first_fix:])

    def test_review_fix_rejects_task_not_reported_done_before_finalization(self):
        self.review_findings_once = True
        self.review_fix_ledger_override = [
            {
                "task_id": "review-fix-unfinished",
                "status": "running",
                "evidence_digests": [],
            }
        ]
        code = self.runner().create_run(
            specs=self.specs,
            plans=self.plans[:1],
            workspace=self.source,
            stall_seconds=30,
            sandbox="workspace-write",
            model=None,
        )
        self.assertEqual(code, ExitCode.FAILED)
        self.assertEqual(
            self.state()["failure"]["reason_code"],
            "recovery_exhausted",
        )
        self.assertEqual(
            sum(packet["mode"] == "finalization" for packet in self.packets),
            1,
        )

    def test_declared_helper_command_extends_provider_activity_lease(self):
        observed = False

        def run_silent_command(adapter, _request, packet, _session_id):
            nonlocal observed
            if packet["mode"] != "implementation" or observed:
                return None
            observed = True
            started = self.root / "silent-focused.started"
            release = self.root / "silent-focused.release"
            envelope = {
                "protocol_version": adapter.helper.protocol_version,
                "run_id": packet["run_id"],
                "nonce": adapter.helper.nonce,
                "operation": "verify_focused",
                "payload": {
                    "candidate_head": packet["current_head"],
                    "command": {
                        "command_id": "silent-focused",
                        "command_role": "focused",
                        "argv": [
                            sys.executable,
                            "-c",
                            (
                                "import pathlib, sys, time; "
                                "started = pathlib.Path(sys.argv[1]); "
                                "release = pathlib.Path(sys.argv[2]); "
                                "started.write_text('started', encoding='utf-8'); "
                                "exec(\"while not release.exists():\\n time.sleep(0.005)\")"
                            ),
                            str(started),
                            str(release),
                        ],
                        "cwd": ".",
                        "input_digest": "b" * 64,
                        "deadline_seconds": 5,
                    },
                },
            }
            errors = []

            def invoke():
                try:
                    helper_client(
                        adapter.helper.socket_path,
                        adapter.helper.nonce,
                        envelope,
                    )
                except Exception as error:
                    errors.append(error)

            thread = threading.Thread(target=invoke)
            thread.start()
            try:
                started_deadline = time.monotonic() + 2
                while (
                    not started.exists()
                    and thread.is_alive()
                    and time.monotonic() < started_deadline
                ):
                    time.sleep(0.005)
                self.assertTrue(started.exists())
                time.sleep(0.06)
                self.assertTrue(thread.is_alive())
                self.assertFalse(self.leases[-1].expired(time.monotonic()))
            finally:
                release.write_text("release\n", encoding="utf-8")
                thread.join(2)
            self.assertEqual(errors, [])
            return None

        self.outcome_hook = run_silent_command
        code = self.runner().create_run(
            specs=self.specs,
            plans=self.plans[:1],
            workspace=self.source,
            stall_seconds=0.03,
            sandbox="workspace-write",
            model=None,
        )
        self.assertEqual(code, ExitCode.READY)

    def test_finalization_transport_resumes_healthy_session_and_context_loss_is_fresh(self):
        final_failures = ["transport_failed", "context_overflow"]

        def fail_then_succeed(_adapter, _request, packet, session_id):
            if packet["mode"] == "finalization" and final_failures:
                kind = final_failures.pop(0)
                return ProviderOutcome(
                    kind,
                    1,
                    session_id,
                    None,
                    (
                        "controller_transport_failed"
                        if kind == "transport_failed"
                        else "session_invalid"
                    ),
                    {},
                    (),
                    "",
                )
            return None

        self.outcome_hook = fail_then_succeed
        code = self.runner().create_run(
            specs=self.specs,
            plans=self.plans[:1],
            workspace=self.source,
            stall_seconds=30,
            sandbox="workspace-write",
            model=None,
        )
        self.assertEqual(code, ExitCode.READY)
        final_requests = [
            request
            for request, packet in zip(self.requests, self.packets, strict=True)
            if packet["mode"] == "finalization"
        ]
        self.assertEqual(len(final_requests), 3)
        self.assertIsNone(final_requests[0].session_id)
        self.assertEqual(
            final_requests[1].session_id,
            str(uuid.UUID(int=2)),
        )
        self.assertIsNone(final_requests[2].session_id)

    def test_finalization_resume_is_bound_to_same_candidate_and_declaration(self):
        interrupted = False

        def interrupt_after_verification(
            _adapter, _request, _packet, session_id, _digest
        ):
            nonlocal interrupted
            if not interrupted:
                interrupted = True
                return ProviderOutcome(
                    "transport_failed",
                    1,
                    session_id,
                    None,
                    "controller_transport_failed",
                    {},
                    (),
                    "",
                )
            return None

        self.after_final_hook = interrupt_after_verification
        code = self.runner().create_run(
            specs=self.specs,
            plans=self.plans[:1],
            workspace=self.source,
            stall_seconds=30,
            sandbox="workspace-write",
            model=None,
        )
        self.assertEqual(code, ExitCode.READY)
        finals = [
            (request, packet)
            for request, packet in zip(self.requests, self.packets, strict=True)
            if packet["mode"] == "finalization"
        ]
        self.assertEqual(len(finals), 2)
        self.assertEqual(finals[1][0].session_id, str(uuid.UUID(int=2)))
        self.assertEqual(
            finals[0][1]["candidate_head"], finals[1][1]["candidate_head"]
        )
        self.assertRegex(
            finals[1][1]["sealed_verification_set_digest"],
            r"^[0-9a-f]{64}$",
        )

    def test_finalization_stall_and_session_loss_each_force_fresh_context(self):
        failures = ["stalled", "resume_failed"]

        def fail_then_succeed(
            _adapter, _request, packet, session_id, _digest
        ):
            if failures:
                kind = failures.pop(0)
                return ProviderOutcome(
                    kind,
                    None,
                    session_id,
                    None,
                    (
                        "stall_expired"
                        if kind == "stalled"
                        else "session_resume_failed"
                    ),
                    {},
                    (),
                    "",
                )
            return None

        self.after_final_hook = fail_then_succeed
        code = self.runner().create_run(
            specs=self.specs,
            plans=self.plans[:1],
            workspace=self.source,
            stall_seconds=30,
            sandbox="workspace-write",
            model=None,
        )
        self.assertEqual(code, ExitCode.READY)
        final_requests = [
            request
            for request, packet in zip(self.requests, self.packets, strict=True)
            if packet["mode"] == "finalization"
        ]
        self.assertEqual(len(final_requests), 3)
        self.assertTrue(
            all(request.session_id is None for request in final_requests)
        )
        final_packets = [
            packet for packet in self.packets if packet["mode"] == "finalization"
        ]
        self.assertTrue(
            all(
                packet["sealed_verification_set_digest"] is None
                for packet in final_packets[1:]
            )
        )
        self.assertTrue(
            all(
                packet["required_strategy_change"]
                for packet in final_packets[1:]
            )
        )
        self.assertEqual(
            final_packets[0]["recovery_context"]["attempted_strategies"], []
        )
        for packet in final_packets[1:]:
            context = packet["recovery_context"]
            self.assertEqual(
                context["scope"], {"mode": "finalization", "plan_index": None}
            )
            self.assertRegex(context["failure_signature"], r"^[0-9a-f]{64}$")
            self.assertEqual(len(context["attempted_strategies"]), 1)
            self.assertEqual(len(packet["operator_strategy_notes"]), 1)


    def test_session_capture_survives_controller_crash_and_resumes_explicitly(self):
        self.crash_after_session = True
        with self.assertRaises(SimulatedCrash):
            self.runner().create_run(
                specs=self.specs,
                plans=self.plans[:1],
                workspace=self.source,
                stall_seconds=30,
                sandbox="workspace-write",
                model=None,
            )
        state = self.state()
        self.assertEqual(state["plans"][0]["status"], "running")
        self.assertEqual(state["sessions"][-1]["phase"], "captured")
        captured = state["sessions"][-1]["session_id"]
        code = self.runner().resume(
            state["run_id"],
            retry_blocked=False,
            retry_failed=False,
            strategy_note=None,
        )
        self.assertEqual(code, ExitCode.READY)
        self.assertEqual(self.requests[-2].session_id, captured)

    def test_outcome_acceptance_is_atomic_and_resume_does_not_replay_commit(self):
        runner = self.runner()

        def crash_before_accept(*_args, **_kwargs):
            raise SimulatedCrash("accept boundary")

        runner._accept_implemented = crash_before_accept
        with self.assertRaises(SimulatedCrash):
            runner.create_run(
                specs=self.specs,
                plans=self.plans[:1],
                workspace=self.source,
                stall_seconds=30,
                sandbox="workspace-write",
                model=None,
            )
        state = self.state()
        self.assertEqual(state["plans"][0]["status"], "running")
        self.assertTrue(state["attempts"][-1]["completed"])
        self.assertTrue(state["attempts"][-1]["post_provider_worktree"]["clean"])
        committed_head = git(
            "rev-parse", "HEAD", cwd=Path(state["repository"]["worktree"])
        )
        self.engine_event_hook = None
        code = self.runner().resume(
            state["run_id"],
            retry_blocked=False,
            retry_failed=False,
            strategy_note=None,
        )
        self.assertEqual(code, ExitCode.READY)
        final_state = self.state()
        handoff = next(
            item
            for item in final_state["artifact_refs"]
            if item["kind"] == "plan_handoff"
        )
        self.assertEqual(
            json.loads(
                (
                    self.paths.state_home
                    / state["run_id"]
                    / handoff["relative_path"]
                ).read_text(encoding="utf-8")
            )["head_commit"],
            committed_head,
        )

    def test_reconcile_completed_implemented_attempt_without_provider_replay(self):
        self.crash_after_session = True
        with self.assertRaises(SimulatedCrash):
            self.runner().create_run(
                specs=self.specs,
                plans=self.plans[:1],
                workspace=self.source,
                stall_seconds=30,
                sandbox="workspace-write",
                model=None,
            )
        state = self.state()
        worktree = Path(state["repository"]["worktree"])
        marker = worktree / "reconciled.txt"
        marker.write_text("implemented before controller crash\n", encoding="utf-8")
        git("add", marker.name, cwd=worktree)
        git(
            "-c",
            "user.name=Engine Test",
            "-c",
            "user.email=engine@example.test",
            "commit",
            "-m",
            "completed provider attempt",
            cwd=worktree,
        )
        head = git("rev-parse", "HEAD", cwd=worktree)
        store = StateStore.open(self.paths.state_home / state["run_id"])
        result = {
            "status": "implemented",
            "head_commit": head,
            "summary": "completed before reconciliation",
            "task_ledger": [
                {
                    "task_id": "T1",
                    "status": "reported_done",
                    "evidence_digests": [],
                }
            ],
            "open_obligation_ids": [],
            "failure_signature": None,
            "strategy_note": None,
            "blocker": None,
        }
        artifact = store.put_artifact("provider_result", result)
        pending = store.snapshot()
        pending["artifact_refs"].append(artifact.as_dict())
        pending["attempts"][-1].update(
            {
                "completed": True,
                "outcome": "implemented",
                "result_artifact": artifact.as_dict(),
            }
        )
        store.commit(pending)
        prior_implementation_launches = len(self.requests)

        def forbid_implementation(_adapter, _request, packet, _session_id):
            if packet["mode"] == "implementation":
                raise AssertionError("completed plan was replayed")
            return None

        self.outcome_hook = forbid_implementation
        code = self.runner().resume(
            state["run_id"],
            retry_blocked=False,
            retry_failed=False,
            strategy_note=None,
        )
        self.assertEqual(code, ExitCode.READY)
        implementation_launches = [
            packet
            for packet in self.packets[prior_implementation_launches:]
            if packet["mode"] == "implementation"
        ]
        self.assertEqual(implementation_launches, [])
        self.assertEqual(self.state()["plans"][0]["status"], "implemented")

    def test_material_progress_discards_pre_progress_recovery_strategies(self):
        failures = 0

        def progressive_failures(_adapter, request, packet, session_id):
            nonlocal failures
            if packet["mode"] != "implementation" or failures >= 4:
                return None
            failures += 1
            if failures == 2:
                marker = request.worktree / "material-progress.txt"
                marker.write_text("progress\n", encoding="utf-8")
                git("add", marker.name, cwd=request.worktree)
                git(
                    "-c",
                    "user.name=Engine Test",
                    "-c",
                    "user.email=engine@example.test",
                    "commit",
                    "-m",
                    "material progress",
                    cwd=request.worktree,
                )
            return ProviderOutcome(
                "transport_failed",
                1,
                session_id,
                None,
                f"controller_transport_failed",
                {},
                (),
                "",
            )

        self.outcome_hook = progressive_failures
        code = self.runner().create_run(
            specs=self.specs,
            plans=self.plans[:1],
            workspace=self.source,
            stall_seconds=30,
            sandbox="workspace-write",
            model=None,
        )
        self.assertEqual(code, ExitCode.READY)
        implementation_requests = [
            request
            for request, packet in zip(self.requests, self.packets, strict=True)
            if packet["mode"] == "implementation"
        ]
        self.assertGreaterEqual(len(implementation_requests), 5)

    def test_tampered_input_snapshot_is_invalid_without_provider_launch(self):
        self.crash_after_session = True
        with self.assertRaises(SimulatedCrash):
            self.runner().create_run(
                specs=self.specs,
                plans=self.plans[:1],
                workspace=self.source,
                stall_seconds=30,
                sandbox="workspace-write",
                model=None,
            )
        state = self.state()
        snapshot = Path(state["inputs"][0]["snapshot_path"])
        snapshot.write_text("tampered\n", encoding="utf-8")
        launch_count = len(self.requests)
        code = self.runner().resume(
            state["run_id"],
            retry_blocked=False,
            retry_failed=False,
            strategy_note=None,
        )
        self.assertEqual(code, ExitCode.INVALID)
        self.assertEqual(len(self.requests), launch_count)

    def test_retry_failed_requires_a_unique_nonempty_strategy_and_starts_fresh(self):
        self.crash_after_session = True
        with self.assertRaises(SimulatedCrash):
            self.runner().create_run(
                specs=self.specs,
                plans=self.plans[:1],
                workspace=self.source,
                stall_seconds=30,
                sandbox="workspace-write",
                model="fixed-model",
            )
        state = self.state()
        store = StateStore.open(self.paths.state_home / state["run_id"])
        failed = store.snapshot()
        prior_note = "use a distinct transport"
        failed["status"] = "failed"
        failed["failure"] = {
            "reason_code": "recovery_exhausted",
            "failure_sequence": [],
            "strategy_digests": [strategy_note_digest(prior_note)],
        }
        store.commit(failed)
        launch_count = len(self.requests)
        prior_failure = dict(failed["failure"])
        observed_active_audits = []

        def observe_fresh_audit(_adapter, _request, packet, _session_id):
            if packet["mode"] == "implementation":
                observed_active_audits.append(
                    list(self.state()["failure"]["failure_sequence"])
                )
            return None

        self.outcome_hook = observe_fresh_audit
        duplicate = self.runner().resume(
            state["run_id"],
            retry_blocked=False,
            retry_failed=True,
            strategy_note=f"  {prior_note}  ",
        )
        self.assertEqual(duplicate, ExitCode.INVALID)
        self.assertEqual(len(self.requests), launch_count)
        accepted = self.runner().resume(
            state["run_id"],
            retry_blocked=False,
            retry_failed=True,
            strategy_note="rebuild the affected boundary from repository evidence",
        )
        self.assertEqual(accepted, ExitCode.READY)
        self.assertIsNone(self.requests[launch_count].session_id)
        self.assertEqual(
            {request.model for request in self.requests}, {"fixed-model"}
        )
        final_state = self.state()
        strategy_ref = next(
            item
            for item in final_state["artifact_refs"]
            if item["kind"] == "strategy_note"
        )
        strategy_payload = json.loads(
            (
                self.paths.state_home
                / state["run_id"]
                / strategy_ref["relative_path"]
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            strategy_payload["strategy_note"],
            "rebuild the affected boundary from repository evidence",
        )
        resumed_packet = self.packets[launch_count]
        self.assertTrue(resumed_packet["required_strategy_change"])
        self.assertEqual(
            resumed_packet["operator_strategy_notes"][0]["digest"],
            strategy_ref["digest"],
        )
        self.assertEqual(observed_active_audits, [[]])
        audit_ref = next(
            item
            for item in final_state["artifact_refs"]
            if item["kind"] == "recovery_audit"
        )
        audit_payload = json.loads(
            (
                self.paths.state_home
                / state["run_id"]
                / audit_ref["relative_path"]
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(audit_payload["failure"], prior_failure)

    def test_repository_remotes_are_passed_to_every_adapter(self):
        git("remote", "add", "origin", "https://example.invalid/archive.git", cwd=self.source)
        code = self.runner().create_run(
            specs=self.specs,
            plans=self.plans[:1],
            workspace=self.source,
            stall_seconds=30,
            sandbox="workspace-write",
            model=None,
        )
        self.assertEqual(code, ExitCode.READY)
        self.assertTrue(self.adapter_values)
        self.assertTrue(
            all(values["remotes"] == ("origin",) for values in self.adapter_values)
        )

    def test_transient_provider_unavailable_resumes_before_blocking(self):
        unavailable = True

        def unavailable_once(_adapter, _request, packet, session_id):
            nonlocal unavailable
            if packet["mode"] == "implementation" and unavailable:
                unavailable = False
                return ProviderOutcome(
                    "transport_failed",
                    1,
                    session_id,
                    None,
                    "provider_unavailable",
                    {},
                    (),
                    "",
                )
            return None

        self.outcome_hook = unavailable_once
        code = self.runner().create_run(
            specs=self.specs,
            plans=self.plans[:1],
            workspace=self.source,
            stall_seconds=30,
            sandbox="workspace-write",
            model=None,
        )
        self.assertEqual(code, ExitCode.READY)
        implementations = [
            request
            for request, packet in zip(self.requests, self.packets, strict=True)
            if packet["mode"] == "implementation"
        ]
        self.assertEqual(len(implementations), 2)
        self.assertEqual(implementations[1].session_id, str(uuid.UUID(int=1)))

    def test_recovery_packet_carries_bounded_failure_context_and_checkpoint(self):
        failed_once = False
        strategy = (
            "replace the contaminated approach API_TOKEN=top-secret "
            + ("with repository evidence " * 300)
        )

        def fail_once(_adapter, _request, packet, session_id):
            nonlocal failed_once
            if packet["mode"] == "implementation" and not failed_once:
                failed_once = True
                return ProviderOutcome(
                    "context_overflow",
                    1,
                    session_id,
                    {"strategy_note": strategy},
                    "session_invalid",
                    {},
                    (),
                    "",
                )
            return None

        self.outcome_hook = fail_once
        code = self.runner().create_run(
            specs=self.specs,
            plans=self.plans[:1],
            workspace=self.source,
            stall_seconds=30,
            sandbox="workspace-write",
            model=None,
        )
        self.assertEqual(code, ExitCode.READY)
        retry_packet = [
            packet for packet in self.packets if packet["mode"] == "implementation"
        ][1]
        context = retry_packet["recovery_context"]
        self.assertEqual(context["failure_reason"], "session_invalid")
        self.assertRegex(context["failure_signature"], r"^[0-9a-f]{64}$")
        self.assertTrue(context["required_strategy_change"])
        self.assertEqual(context["next_session_action"], "fresh_session")
        self.assertEqual(
            context["checkpoint"],
            {
                "revision": retry_packet["checkpoint_revision"],
                "head": retry_packet["current_head"],
                "plan_index": retry_packet["current_plan"]["index"],
                "post_provider_worktree": next(
                    item["post_provider_worktree"]
                    for item in self.state()["attempts"]
                    if item["mode"] == "implementation"
                    and item.get("next_strategy") == "fresh_root_full_diff"
                ),
            },
        )
        attempted = context["attempted_strategies"]
        self.assertEqual(len(attempted), 1)
        self.assertEqual(
            attempted[0]["failure_signature"], context["failure_signature"]
        )
        self.assertRegex(attempted[0]["strategy_note_digest"], r"^[0-9a-f]{64}$")
        self.assertIn("API_TOKEN=[REDACTED]", attempted[0]["strategy_note"])
        self.assertLessEqual(len(attempted[0]["strategy_note"].encode()), 4096)
        self.assertNotIn("top-secret", json.dumps(context))

    def test_recovery_context_is_bounded_and_does_not_leak_to_next_plan_or_mode(self):
        failures = 0
        plan_one_failed = False

        def fail_plan_zero(_adapter, _request, packet, session_id):
            nonlocal failures, plan_one_failed
            if (
                packet["mode"] == "implementation"
                and packet["current_plan"]["index"] == 0
                and failures < 3
            ):
                failures += 1
                return ProviderOutcome(
                    "context_overflow",
                    1,
                    session_id,
                    {"strategy_note": f"plan-zero-strategy-{failures}"},
                    "session_invalid",
                    {},
                    (),
                    "",
                )
            if (
                packet["mode"] == "implementation"
                and packet["current_plan"]["index"] == 1
                and not plan_one_failed
            ):
                plan_one_failed = True
                return ProviderOutcome(
                    "context_overflow",
                    1,
                    session_id,
                    {"strategy_note": "plan-one-strategy"},
                    "session_invalid",
                    {},
                    (),
                    "",
                )
            return None

        self.outcome_hook = fail_plan_zero
        self.review_findings_once = True
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
        plan_zero = [
            packet
            for packet in implementations
            if packet["current_plan"]["index"] == 0
        ]
        self.assertEqual(
            [
                len(packet["recovery_context"]["attempted_strategies"])
                for packet in plan_zero
            ],
            [0, 1, 2, 3],
        )
        self.assertTrue(
            all(
                packet["recovery_context"]["scope"]
                == {"mode": "implementation", "plan_index": 0}
                for packet in plan_zero
            )
        )
        plan_one_packets = [
            packet
            for packet in implementations
            if packet["current_plan"]["index"] == 1
        ]
        self.assertEqual(len(plan_one_packets), 2)
        plan_one = plan_one_packets[0]
        finalization = next(
            packet for packet in self.packets if packet["mode"] == "finalization"
        )
        review_fix = next(
            packet for packet in self.packets if packet["mode"] == "final_review_fix"
        )
        for packet in (plan_one, finalization, review_fix):
            self.assertIsNone(packet["recovery_context"]["failure_signature"])
            self.assertEqual(packet["recovery_context"]["attempted_strategies"], [])
            self.assertEqual(packet["operator_strategy_notes"], [])
        self.assertFalse(plan_one["required_strategy_change"])
        self.assertFalse(finalization["required_strategy_change"])
        self.assertTrue(review_fix["required_strategy_change"])

    def test_durable_provider_unavailable_blocks_after_bounded_recovery(self):
        def always_unavailable(_adapter, _request, _packet, session_id):
            return ProviderOutcome(
                "transport_failed",
                1,
                session_id,
                None,
                "provider_unavailable",
                {},
                (),
                "",
            )

        self.outcome_hook = always_unavailable
        code = self.runner().create_run(
            specs=self.specs,
            plans=self.plans[:1],
            workspace=self.source,
            stall_seconds=30,
            sandbox="workspace-write",
            model=None,
        )
        self.assertEqual(code, ExitCode.BLOCKED)
        state = self.state()
        self.assertEqual(state["status"], "blocked")
        self.assertEqual(state["failure"]["reason_code"], "provider_unavailable")
        self.assertLessEqual(len(self.requests), 4)

    def test_final_review_receipt_seals_allowed_minor_findings_into_handoff(self):
        self.minor_findings_once = True
        code = self.runner().create_run(
            specs=self.specs,
            plans=self.plans[:1],
            workspace=self.source,
            stall_seconds=30,
            sandbox="workspace-write",
            model=None,
        )
        self.assertEqual(code, ExitCode.READY)
        state = self.state()
        receipt_ref = next(
            item
            for item in state["artifact_refs"]
            if item["kind"] == "final_review_receipt"
        )
        receipt = json.loads(
            (
                self.paths.state_home
                / state["run_id"]
                / receipt_ref["relative_path"]
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(receipt["open_findings"][0]["severity"], "Minor")
        handoff_ref = next(
            item for item in state["artifact_refs"] if item["kind"] == "branch_handoff"
        )
        handoff = json.loads(
            (
                self.paths.state_home
                / state["run_id"]
                / handoff_ref["relative_path"]
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(handoff["review_receipt"], receipt_ref)
        self.assertEqual(handoff["status"], "ready_for_integration")
        self.assertEqual(handoff["worktree"], state["repository"]["worktree"])
        self.assertEqual(handoff["runner_identity"], state["runner_runtime"])
        self.assertEqual(
            handoff["provider_identity"],
            {
                "provider": "codex",
                "model": state["immutable_config"]["model"],
            },
        )
        self.assertEqual(
            [item["plan_index"] for item in handoff["plan_implementations"]],
            [0],
        )
        self.assertEqual(
            handoff["non_blocking_observations"][0]["severity"], "Minor"
        )
        receipt_refs = [
            item
            for item in state["artifact_refs"]
            if item["kind"] == "verification_receipt"
        ]
        self.assertEqual(handoff["verification_receipts"], receipt_refs)
        self.assertEqual(len(handoff["verification_receipts"]), 1)

    def test_provider_schema_defers_implemented_ledger_condition_to_engine(self):
        schema = json.loads(
            (
                SKILL_ROOT / "templates" / "plan-result.schema.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            schema["properties"]["task_ledger"]["$ref"],
            "#/$defs/taskLedger",
        )
        self.assertEqual(
            schema["$defs"]["taskLedger"]["items"]["properties"]["status"],
            {"enum": ["pending", "running", "reported_done"]},
        )

    def test_implemented_result_rejects_any_task_not_reported_done(self):
        self.implementation_ledger = [
            {
                "task_id": "unfinished",
                "status": "running",
                "evidence_digests": [],
            }
        ]
        code = self.runner().create_run(
            specs=self.specs,
            plans=self.plans[:1],
            workspace=self.source,
            stall_seconds=30,
            sandbox="workspace-write",
            model=None,
        )
        self.assertEqual(code, ExitCode.FAILED)
        self.assertEqual(
            self.state()["failure"]["reason_code"],
            "recovery_exhausted",
        )

    def test_final_gate_rejects_persisted_task_not_reported_done(self):
        self.implementation_ledger = [
            {
                "task_id": "submitted",
                "status": "reported_done",
                "evidence_digests": [],
            }
        ]
        ready = self.runner().create_run(
            specs=self.specs,
            plans=self.plans[:1],
            workspace=self.source,
            stall_seconds=30,
            sandbox="workspace-write",
            model=None,
        )
        self.assertEqual(ready, ExitCode.READY)
        state = self.state()
        store = StateStore.open(self.paths.state_home / state["run_id"])
        changed = store.snapshot()
        changed["status"] = "resumable"
        changed["task_ledger"][0]["status"] = "pending"
        store.commit(changed)
        code = self.runner().resume(
            state["run_id"],
            retry_blocked=False,
            retry_failed=False,
            strategy_note=None,
        )
        self.assertEqual(code, ExitCode.INTEGRITY)
        self.assertIn("task", self.state()["failure"]["detail"])

    def test_completed_same_head_review_is_reconciled_without_provider_replay(self):
        runner = self.runner()
        original_mark_reusable = runner._mark_final_result_reusable
        crashed = False

        def crash_after_validated_review_checkpoint(*args, **kwargs):
            nonlocal crashed
            result = original_mark_reusable(*args, **kwargs)
            if not crashed:
                crashed = True
                raise SimulatedCrash("after validated reviewed checkpoint")
            return result

        runner._mark_final_result_reusable = (
            crash_after_validated_review_checkpoint
        )
        with self.assertRaises(SimulatedCrash):
            runner.create_run(
                specs=self.specs,
                plans=self.plans[:1],
                workspace=self.source,
                stall_seconds=30,
                sandbox="workspace-write",
                model=None,
            )
        state = self.state()
        final_launches = sum(
            packet["mode"] == "finalization" for packet in self.packets
        )
        self.assertEqual(final_launches, 1)
        attempt = state["attempts"][-1]
        self.assertEqual(attempt["outcome"], "reviewed")
        self.assertIn("result_artifact", attempt)
        self.assertTrue(attempt["result_validated"])

        code = self.runner().resume(
            state["run_id"],
            retry_blocked=False,
            retry_failed=False,
            strategy_note=None,
        )
        self.assertEqual(code, ExitCode.READY)
        self.assertEqual(
            sum(packet["mode"] == "finalization" for packet in self.packets),
            final_launches,
        )

    def test_invalid_final_result_retry_launches_fresh_root_after_changed_strategy(self):
        finalization_launches = 0

        def invalid_then_valid(
            _adapter, _request, packet, session_id, digest
        ):
            nonlocal finalization_launches
            finalization_launches += 1
            if finalization_launches != 1:
                return None
            return ProviderOutcome(
                "reviewed",
                0,
                session_id,
                {
                    "status": "reviewed",
                    "review_head": packet["candidate_head"],
                    "verification_set_digest": digest,
                    "open_findings": [],
                    "open_obligation_ids": [],
                    "no_applicable_verification_approved": False,
                    "summary": "",
                },
                None,
                {},
                (),
                "",
            )

        self.after_final_hook = invalid_then_valid
        runner = self.runner()
        first_code = runner.create_run(
            specs=self.specs,
            plans=self.plans[:1],
            workspace=self.source,
            stall_seconds=30,
            sandbox="workspace-write",
            model=None,
        )
        self.assertEqual(first_code, ExitCode.INTEGRITY)
        failed = self.state()
        first_final_attempt = next(
            item
            for item in failed["attempts"]
            if item["mode"] == "finalization"
        )
        self.assertIn("result_artifact", first_final_attempt)
        self.assertFalse(
            first_final_attempt.get("result_validated", False)
        )

        retry_code = runner.resume(
            failed["run_id"],
            retry_blocked=False,
            retry_failed=True,
            strategy_note="re-run finalization with corrected review output",
        )

        self.assertEqual(retry_code, ExitCode.READY)
        final_requests = [
            request
            for request, packet in zip(
                self.requests, self.packets, strict=True
            )
            if packet["mode"] == "finalization"
        ]
        self.assertEqual(len(final_requests), 2)
        self.assertIsNone(final_requests[1].session_id)
        final_attempts = [
            item
            for item in self.state()["attempts"]
            if item["mode"] == "finalization"
        ]
        self.assertFalse(
            final_attempts[0].get("result_validated", False)
        )
        self.assertTrue(final_attempts[1]["result_validated"])

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

    def test_volatile_and_partial_repairs_accept_only_the_recorded_evidence(self):
        volatile, _refname = self.make_volatile_repair_state()
        volatile_root = self.paths.state_home / volatile["run_id"]
        adapter_count = len(self.adapter_values)
        git_before = self.git_surface(volatile)
        self.output.clear()
        duplicate = self.runner().create_run(
            specs=self.specs,
            plans=self.plans[:1],
            workspace=self.source,
            stall_seconds=30,
            sandbox="danger-full-access",
            model=None,
        )
        self.assertEqual(duplicate, ExitCode.INTEGRITY)
        self.assertEqual(
            self.matching_response()["recommended_action"],
            "./skills/kws-codex-plan-runner/scripts/runner repair "
            f"--run-id {volatile['run_id']} "
            f"--expected-revision {volatile['revision']} "
            "--repair-kind volatile-codex-turn-refs --strategy-note TEXT",
        )
        self.output.clear()

        code = self.runner().repair(
            volatile["run_id"],
            expected_revision=volatile["revision"],
            repair_kind="volatile-codex-turn-refs",
            strategy_note="continue in a fresh root after validating volatile refs",
            attempt_id=None,
        )

        self.assertEqual(code, ExitCode.RESUMABLE, self.output)
        repaired = StateStore.open(volatile_root).snapshot()
        self.assertEqual(repaired["revision"], volatile["revision"] + 1)
        self.assertEqual(repaired["status"], "resumable")
        self.assertEqual(repaired["failure"]["next_session_action"], "fresh_session")
        audit = repaired["failure"]["repair_audit_artifact"]
        self.assertEqual(audit["kind"], "repair_audit")
        payload = json.loads(
            StateStore.open(volatile_root)
            .referenced_artifact(audit)
            .read_text(encoding="utf-8")
        )
        self.assertEqual(payload["repair_kind"], "volatile-codex-turn-refs")
        self.assertTrue(payload["ref_delta"])
        self.assertEqual(len(self.adapter_values), adapter_count)
        self.assertEqual(self.git_surface(repaired), git_before)

        state_bytes = (volatile_root / "state.json").read_bytes()
        artifacts = list((volatile_root / "artifacts").rglob("*.json"))
        retry = self.runner().repair(
            volatile["run_id"],
            expected_revision=volatile["revision"],
            repair_kind="volatile-codex-turn-refs",
            strategy_note="continue in a fresh root after validating volatile refs",
            attempt_id=None,
        )
        self.assertEqual(retry, ExitCode.INTEGRITY)
        self.assertIn(
            "revision proof failed",
            json.loads(self.output[-1])["detail"],
        )
        self.assertEqual((volatile_root / "state.json").read_bytes(), state_bytes)
        self.assertEqual(list((volatile_root / "artifacts").rglob("*.json")), artifacts)

    def test_partial_repair_adopts_dirty_observation_and_discards_claims(self):
        state = self.make_partial_repair_state()
        root = self.paths.state_home / state["run_id"]
        before_git = self.git_surface(state)
        adapter_count = len(self.adapter_values)
        self.output.clear()
        duplicate = self.runner().create_run(
            specs=self.specs,
            plans=self.plans[:1],
            workspace=self.source,
            stall_seconds=30,
            sandbox="danger-full-access",
            model=None,
        )
        self.assertEqual(duplicate, ExitCode.INTEGRITY)
        self.assertEqual(
            self.matching_response()["recommended_action"],
            "./skills/kws-codex-plan-runner/scripts/runner repair "
            f"--run-id {state['run_id']} "
            f"--expected-revision {state['revision']} "
            "--repair-kind unsealed-provider-partial --strategy-note TEXT "
            "--attempt-id attempt-partial",
        )
        self.output.clear()

        code = self.runner().repair(
            state["run_id"],
            expected_revision=state["revision"],
            repair_kind="unsealed-provider-partial",
            strategy_note="fresh root must inspect the complete untrusted diff",
            attempt_id="attempt-partial",
        )

        self.assertEqual(code, ExitCode.RESUMABLE, self.output)
        repaired = StateStore.open(root).snapshot()
        attempt = repaired["attempts"][-1]
        self.assertEqual(attempt["outcome"], "adopted_untrusted_partial")
        self.assertTrue(attempt["completed"])
        self.assertNotIn("result_artifact", attempt)
        self.assertNotIn("result_validated", attempt)
        self.assertEqual(
            repaired["failure"]["partial_worktree"],
            self.worktree_observation(repaired),
        )
        self.assertEqual(repaired["failure"]["next_session_action"], "fresh_session")
        self.assertEqual(len(self.adapter_values), adapter_count)
        self.assertEqual(self.git_surface(repaired), before_git)
        workspace = self.runner()._open_repair_workspace(repaired)
        self.runner()._require_git_contract(
            repaired,
            workspace,
            store=StateStore.open(root),
        )
        with mock.patch.object(
            PlanRunner,
            "_execute_current_plan",
            return_value=int(ExitCode.RESUMABLE),
        ) as execute_current:
            resumed = self.runner().resume(
                repaired["run_id"],
                retry_blocked=False,
                retry_failed=False,
                strategy_note=None,
            )
        self.assertEqual(resumed, ExitCode.RESUMABLE)
        execute_current.assert_called_once()

    def test_overlapping_repair_evidence_prefers_partial_and_rejects_volatile(self):
        state = self.make_overlapping_repair_state()
        root = self.paths.state_home / state["run_id"]
        state_before = (root / "state.json").read_bytes()
        artifacts_before = self.artifact_files(root)
        self.output.clear()

        duplicate = self.runner().create_run(
            specs=self.specs,
            plans=self.plans[:1],
            workspace=self.source,
            stall_seconds=30,
            sandbox="danger-full-access",
            model=None,
        )
        self.assertEqual(duplicate, ExitCode.INTEGRITY)
        self.assertIn(
            "--repair-kind unsealed-provider-partial",
            self.matching_response()["recommended_action"],
        )

        self.output.clear()
        refused = self.runner().repair(
            state["run_id"],
            expected_revision=state["revision"],
            repair_kind="volatile-codex-turn-refs",
            strategy_note="do not discard the eligible dirty partial",
            attempt_id=None,
        )
        self.assertEqual(refused, ExitCode.INTEGRITY)
        self.assertIn(
            "overlapping partial repair proof failed",
            json.loads(self.output[-1])["detail"],
        )
        self.assertEqual((root / "state.json").read_bytes(), state_before)
        self.assertEqual(self.artifact_files(root), artifacts_before)

        accepted = self.runner().repair(
            state["run_id"],
            expected_revision=state["revision"],
            repair_kind="unsealed-provider-partial",
            strategy_note="fresh root inspects the complete dirty diff",
            attempt_id="attempt-partial",
        )
        self.assertEqual(accepted, ExitCode.RESUMABLE)
        repaired_store = StateStore.open(root)
        repaired = repaired_store.snapshot()
        workspace = self.runner()._open_repair_workspace(repaired)
        self.runner()._require_git_contract(
            repaired,
            workspace,
            store=repaired_store,
        )

    def test_adopted_partial_rejects_a_different_valid_repair_audit(self):
        state = self.make_partial_repair_state()
        root = self.paths.state_home / state["run_id"]
        code = self.runner().repair(
            state["run_id"],
            expected_revision=state["revision"],
            repair_kind="unsealed-provider-partial",
            strategy_note="fresh root inspects the complete diff",
            attempt_id="attempt-partial",
        )
        self.assertEqual(code, ExitCode.RESUMABLE)
        store = StateStore.open(root)
        repaired = store.snapshot()
        observation = self.worktree_observation(repaired)
        substitute = store.put_artifact(
            "repair_audit",
            {
                "contract_version": 1,
                "run_id": repaired["run_id"],
                "expected_revision": repaired["failure"]["repaired_revision"] - 1,
                "repair_kind": "unsealed-provider-partial",
                "strategy_note": repaired["failure"]["operator_strategy_note"],
                "attempt_id": "different-attempt",
                "mode": "implementation",
                "plan_index": 0,
                "recorded_stable_refs": repaired["immutable_config"]["protected_refs"],
                "current_stable_refs": repaired["immutable_config"]["protected_refs"],
                "adopted_observation": observation,
                "discarded_semantic_claims": True,
            },
        )
        candidate = store.snapshot()
        candidate["artifact_refs"].append(substitute.as_dict())
        candidate["failure"]["repair_audit_artifact"] = substitute.as_dict()
        candidate["attempts"][-1]["repair_audit_artifact"] = substitute.as_dict()
        store.commit(candidate)
        tampered = StateStore.open(root)
        workspace = self.runner()._open_repair_workspace(tampered.snapshot())

        with self.assertRaisesRegex(ValueError, "repair audit attempt proof failed"):
            self.runner()._require_git_contract(
                tampered.snapshot(),
                workspace,
                store=tampered,
            )

    def test_adopted_partial_rejects_failure_kind_tamper(self):
        state = self.make_partial_repair_state()
        root = self.paths.state_home / state["run_id"]
        code = self.runner().repair(
            state["run_id"],
            expected_revision=state["revision"],
            repair_kind="unsealed-provider-partial",
            strategy_note="fresh root inspects the complete diff",
            attempt_id="attempt-partial",
        )
        self.assertEqual(code, ExitCode.RESUMABLE)
        store = StateStore.open(root)
        candidate = store.snapshot()
        candidate["failure"]["repair_kind"] = "volatile-codex-turn-refs"
        store.commit(candidate)
        tampered = StateStore.open(root)
        workspace = self.runner()._open_repair_workspace(tampered.snapshot())

        with self.assertRaisesRegex(ValueError, "repair audit kind proof failed"):
            self.runner()._require_git_contract(
                tampered.snapshot(),
                workspace,
                store=tampered,
            )

    def test_repair_rechecks_git_evidence_after_audit_preparation(self):
        state = self.make_partial_repair_state()
        root = self.paths.state_home / state["run_id"]
        state_before = (root / "state.json").read_bytes()
        artifacts_before = self.artifact_files(root)

        def mutate_after_audit(stage):
            if stage == "repair_audit_prepared":
                Path(state["repository"]["worktree"]).joinpath(
                    "late-drift.txt"
                ).write_text("late drift\n", encoding="utf-8")

        self.engine_event_hook = mutate_after_audit
        code = self.runner().repair(
            state["run_id"],
            expected_revision=state["revision"],
            repair_kind="unsealed-provider-partial",
            strategy_note="fresh root inspects the complete diff",
            attempt_id="attempt-partial",
        )

        self.assertEqual(code, ExitCode.INTEGRITY)
        self.assertIn(
            "repair evidence changed before state CAS",
            json.loads(self.output[-1])["detail"],
        )
        self.assertEqual((root / "state.json").read_bytes(), state_before)
        self.assertEqual(self.artifact_files(root), artifacts_before)

    def test_repair_commit_fault_rolls_back_only_new_audit_artifact(self):
        for preexisting in (False, True):
            with self.subTest(preexisting=preexisting):
                self.tearDown()
                self.setUp()
                state = self.make_partial_repair_state()
                root = self.paths.state_home / state["run_id"]
                runner = self.runner()
                store = StateStore.open(root)
                workspace = runner._open_repair_workspace(state)
                evidence = runner._repair_evidence(
                    state,
                    workspace,
                    repair_kind="unsealed-provider-partial",
                    attempt_id="attempt-partial",
                )
                payload = {
                    "contract_version": 1,
                    "run_id": state["run_id"],
                    "expected_revision": state["revision"],
                    "repair_kind": "unsealed-provider-partial",
                    "strategy_note": "fresh root inspects the complete diff",
                    **evidence["audit"],
                }
                prior = (
                    store.put_artifact("repair_audit", payload)
                    if preexisting
                    else None
                )
                state_before = (root / "state.json").read_bytes()
                artifacts_before = self.artifact_files(root)
                git_before = self.git_surface(state)
                real_open = StateStore.open

                def faulting_open(path):
                    opened = real_open(path)

                    def fail_before_replace(stage):
                        if stage == storage_module.BEFORE_STATE_REPLACE:
                            raise RuntimeError("injected repair CAS fault")

                    opened._fault_injector = fail_before_replace
                    return opened

                with mock.patch.object(
                    StateStore, "open", side_effect=faulting_open
                ):
                    code = runner.repair(
                        state["run_id"],
                        expected_revision=state["revision"],
                        repair_kind="unsealed-provider-partial",
                        strategy_note="fresh root inspects the complete diff",
                        attempt_id="attempt-partial",
                    )

                self.assertEqual(code, ExitCode.INTEGRITY)
                self.assertEqual((root / "state.json").read_bytes(), state_before)
                self.assertEqual(self.artifact_files(root), artifacts_before)
                self.assertEqual(self.git_surface(state), git_before)
                if prior is not None:
                    self.assertTrue(root.joinpath(prior.relative_path).is_file())

    def test_before_replace_git_mutation_is_refused_by_cas_precondition(self):
        state = self.make_partial_repair_state()
        root = self.paths.state_home / state["run_id"]
        state_before = (root / "state.json").read_bytes()
        artifacts_before = self.artifact_files(root)
        real_open = StateStore.open

        def faulting_open(path):
            opened = real_open(path)

            def mutate_before_replace(stage):
                if stage == storage_module.BEFORE_STATE_REPLACE:
                    Path(state["repository"]["worktree"]).joinpath(
                        "commit-entry-drift.txt"
                    ).write_text("commit entry drift\n", encoding="utf-8")

            opened._fault_injector = mutate_before_replace
            return opened

        with mock.patch.object(StateStore, "open", side_effect=faulting_open):
            code = self.runner().repair(
                state["run_id"],
                expected_revision=state["revision"],
                repair_kind="unsealed-provider-partial",
                strategy_note="fresh root inspects the complete diff",
                attempt_id="attempt-partial",
            )

        self.assertEqual(code, ExitCode.INTEGRITY)
        self.assertEqual((root / "state.json").read_bytes(), state_before)
        self.assertEqual(self.artifact_files(root), artifacts_before)

    def test_after_replace_fault_reconciles_exact_durable_repair(self):
        state = self.make_partial_repair_state()
        root = self.paths.state_home / state["run_id"]
        real_open = StateStore.open

        def faulting_open(path):
            opened = real_open(path)

            def fail_after_replace(stage):
                if stage == storage_module.AFTER_STATE_REPLACE:
                    raise RuntimeError("injected post-replace fault")

            opened._fault_injector = fail_after_replace
            return opened

        with mock.patch.object(StateStore, "open", side_effect=faulting_open):
            code = self.runner().repair(
                state["run_id"],
                expected_revision=state["revision"],
                repair_kind="unsealed-provider-partial",
                strategy_note="fresh root inspects the complete diff",
                attempt_id="attempt-partial",
            )

        self.assertEqual(code, ExitCode.RESUMABLE)
        repaired = real_open(root)
        self.assertEqual(repaired.snapshot()["revision"], state["revision"] + 1)
        workspace = self.runner()._open_repair_workspace(repaired.snapshot())
        self.runner()._require_git_contract(
            repaired.snapshot(),
            workspace,
            store=repaired,
        )

    def test_after_replace_fault_with_git_drift_refuses_but_keeps_referenced_audit(self):
        state = self.make_partial_repair_state()
        root = self.paths.state_home / state["run_id"]
        real_open = StateStore.open

        def faulting_open(path):
            opened = real_open(path)

            def drift_after_replace(stage):
                if stage == storage_module.AFTER_STATE_REPLACE:
                    Path(state["repository"]["worktree"]).joinpath(
                        "post-replace-drift.txt"
                    ).write_text("post replace drift\n", encoding="utf-8")
                    raise RuntimeError("injected post-replace drift")

            opened._fault_injector = drift_after_replace
            return opened

        with mock.patch.object(StateStore, "open", side_effect=faulting_open):
            code = self.runner().repair(
                state["run_id"],
                expected_revision=state["revision"],
                repair_kind="unsealed-provider-partial",
                strategy_note="fresh root inspects the complete diff",
                attempt_id="attempt-partial",
            )

        self.assertEqual(code, ExitCode.INTEGRITY)
        durable = real_open(root).snapshot()
        self.assertEqual(durable["revision"], state["revision"] + 1)
        audit = durable["failure"]["repair_audit_artifact"]
        self.assertIn(audit, durable["artifact_refs"])
        self.assertTrue(root.joinpath(audit["relative_path"]).is_file())

    def test_repair_rejects_stale_revision_without_state_or_artifact_write(self):
        state = self.make_partial_repair_state()
        root = self.paths.state_home / state["run_id"]
        state_before = (root / "state.json").read_bytes()
        artifacts_before = sorted(
            path.relative_to(root).as_posix()
            for path in (root / "artifacts").rglob("*")
            if path.is_file()
        )
        git_before = self.git_surface(state)

        code = self.runner().repair(
            state["run_id"],
            expected_revision=state["revision"] - 1,
            repair_kind="unsealed-provider-partial",
            strategy_note="fresh root inspects the complete diff",
            attempt_id="attempt-partial",
        )

        self.assertEqual(code, ExitCode.INTEGRITY)
        refusal = json.loads(self.output[-1])
        self.assertEqual(refusal["reason_code"], "repair_refused")
        self.assertIn("revision proof failed", refusal["detail"])
        self.assertEqual((root / "state.json").read_bytes(), state_before)
        self.assertEqual(
            sorted(
                path.relative_to(root).as_posix()
                for path in (root / "artifacts").rglob("*")
                if path.is_file()
            ),
            artifacts_before,
        )
        self.assertEqual(self.git_surface(state), git_before)

    def test_volatile_repair_rejects_product_and_unknown_ref_delta(self):
        for refname in ("refs/tags/product-test", "refs/codex/other/test"):
            with self.subTest(refname=refname):
                self.tearDown()
                self.setUp()
                state, _volatile = self.make_volatile_repair_state()
                root = self.paths.state_home / state["run_id"]
                git("update-ref", refname, self.starting_head, cwd=Path(state["repository"]["worktree"]))
                state_before = (root / "state.json").read_bytes()
                artifacts_before = list((root / "artifacts").rglob("*.json"))
                git_before = self.git_surface(state)

                code = self.runner().repair(
                    state["run_id"],
                    expected_revision=state["revision"],
                    repair_kind="volatile-codex-turn-refs",
                    strategy_note="validate only confirmed volatile refs",
                    attempt_id=None,
                )

                self.assertEqual(code, ExitCode.INTEGRITY)
                self.assertIn(
                    "stable ref proof failed",
                    json.loads(self.output[-1])["detail"],
                )
                self.assertEqual((root / "state.json").read_bytes(), state_before)
                self.assertEqual(list((root / "artifacts").rglob("*.json")), artifacts_before)
                self.assertEqual(self.git_surface(state), git_before)

    def test_partial_repair_rejects_clean_wrong_completed_and_mismatched_attempts(self):
        cases = ("clean", "unknown", "completed", "mode", "live")
        for case in cases:
            with self.subTest(case=case):
                self.tearDown()
                self.setUp()
                state = self.make_partial_repair_state(
                    completed=case == "completed",
                    mode="finalization" if case == "mode" else "implementation",
                )
                if case == "live":
                    state = self.rewrite_run_state(
                        lambda candidate: candidate["attempts"][-1].__setitem__(
                            "controller_pid", os.getpid()
                        )
                    )
                worktree = Path(state["repository"]["worktree"])
                if case == "clean":
                    (worktree / "partial.txt").unlink()
                root = self.paths.state_home / state["run_id"]
                state_before = (root / "state.json").read_bytes()
                git_before = self.git_surface(state)
                code = self.runner().repair(
                    state["run_id"],
                    expected_revision=state["revision"],
                    repair_kind="unsealed-provider-partial",
                    strategy_note="fresh root inspects the complete diff",
                    attempt_id="unknown" if case == "unknown" else "attempt-partial",
                )
                self.assertEqual(code, ExitCode.INTEGRITY)
                detail = json.loads(self.output[-1])["detail"]
                expected = {
                    "clean": "dirty worktree proof failed",
                    "unknown": "attempt proof failed",
                    "completed": "incomplete attempt proof failed",
                    "mode": "attempt mode proof failed",
                    "live": "live process proof failed",
                }[case]
                self.assertIn(expected, detail)
                self.assertEqual((root / "state.json").read_bytes(), state_before)
                self.assertEqual(self.git_surface(state), git_before)

    def test_partial_repair_rejects_branch_ancestry_and_input_drift_precisely(self):
        cases = ("branch", "ancestry", "input")
        for case in cases:
            with self.subTest(case=case):
                self.tearDown()
                self.setUp()
                state = self.make_partial_repair_state()
                root = self.paths.state_home / state["run_id"]
                worktree = Path(state["repository"]["worktree"])
                if case == "branch":
                    git("switch", "-c", "other-branch", cwd=worktree)
                elif case == "ancestry":
                    orphan = git(
                        "commit-tree",
                        "4b825dc642cb6eb9a060e54bf8d69288fbee4904",
                        "-m",
                        "orphan",
                        cwd=worktree,
                    )
                    git("reset", "--mixed", orphan, cwd=worktree)
                else:
                    snapshot = Path(state["inputs"][0]["snapshot_path"])
                    snapshot.write_text("drifted input\n", encoding="utf-8")
                state_before = (root / "state.json").read_bytes()
                artifacts_before = list((root / "artifacts").rglob("*.json"))
                git_before = self.git_surface(state) if case != "branch" else None

                code = self.runner().repair(
                    state["run_id"],
                    expected_revision=state["revision"],
                    repair_kind="unsealed-provider-partial",
                    strategy_note="fresh root inspects the complete diff",
                    attempt_id="attempt-partial",
                )

                self.assertEqual(code, ExitCode.INTEGRITY)
                detail = json.loads(self.output[-1])["detail"]
                self.assertIn(f"{case} proof failed", detail)
                self.assertEqual((root / "state.json").read_bytes(), state_before)
                self.assertEqual(list((root / "artifacts").rglob("*.json")), artifacts_before)
                if git_before is not None:
                    self.assertEqual(self.git_surface(state), git_before)

    def test_repair_cli_rejects_kind_specific_arguments_and_note_bounds(self):
        cases = (
            [
                "repair",
                "--run-id",
                "missing-run",
                "--expected-revision",
                "1",
                "--repair-kind",
                "volatile-codex-turn-refs",
                "--strategy-note",
                "note",
                "--attempt-id",
                "unexpected",
            ],
            [
                "repair",
                "--run-id",
                "missing-run",
                "--expected-revision",
                "1",
                "--repair-kind",
                "unsealed-provider-partial",
                "--strategy-note",
                "note",
            ],
            [
                "repair",
                "--run-id",
                "missing-run",
                "--expected-revision",
                "1",
                "--repair-kind",
                "volatile-codex-turn-refs",
                "--strategy-note",
                " ",
            ],
            [
                "repair",
                "--run-id",
                "missing-run",
                "--expected-revision",
                "1",
                "--repair-kind",
                "volatile-codex-turn-refs",
                "--strategy-note",
                "x" * 4097,
            ],
        )
        for arguments in cases:
            with self.subTest(arguments=arguments):
                completed = subprocess.run(
                    [sys.executable, str(SKILL_ROOT / "scripts" / "runner.py"), *arguments],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(completed.returncode, ExitCode.INVALID)
                self.assertEqual(
                    json.loads(completed.stdout)["reason_code"],
                    "invalid_invocation",
                )

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

    def test_cli_parse_failures_use_one_bounded_contract_response(self):
        cases = {
            "unknown argument": ["inspect", "--run-id", "missing-run", "--bogus"],
            "missing required argument": ["inspect"],
            "malformed argument": [
                "run",
                "--spec",
                "spec.md",
                "--plan",
                "plan.md",
                "--workspace",
                ".",
                "--stall-seconds",
                "not-a-number",
            ],
        }
        for name, arguments in cases.items():
            with self.subTest(name=name):
                completed = subprocess.run(
                    [
                        sys.executable,
                        str(SKILL_ROOT / "scripts" / "runner.py"),
                        *arguments,
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(completed.returncode, ExitCode.INVALID)
                self.assertEqual(completed.stderr, "")
                self.assertEqual(len(completed.stdout.splitlines()), 1)
                self.assertLessEqual(len(completed.stdout.encode("utf-8")), 1024)
                response = json.loads(completed.stdout)
                self.assertEqual(
                    set(response), {"status", "reason_code", "detail"}
                )
                self.assertEqual(response["status"], "failed")
                self.assertEqual(response["reason_code"], "invalid_invocation")
                self.assertLessEqual(len(response["detail"]), 512)

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
