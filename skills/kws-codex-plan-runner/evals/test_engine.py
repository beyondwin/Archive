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


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from plan_runner.contracts import ExitCode  # noqa: E402
from plan_runner.helper import helper_client  # noqa: E402
from plan_runner.provider import ProviderOutcome  # noqa: E402
from plan_runner.recovery import strategy_note_digest  # noqa: E402
from plan_runner.runtime import RuntimeIdentity, RuntimeUnavailable  # noqa: E402
from plan_runner.storage import StateStore  # noqa: E402
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

    def launch(self, request, _lease, on_session_id=None):
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

    def test_runtime_paths_are_immutable(self):
        with self.assertRaises(dataclasses.FrozenInstanceError):
            self.paths.state_home = self.root / "other"

    def _assert_graceful_dirty_signal_checkpoint(
        self, signum, *, drift=False, clean_drift=False
    ):
        home = self.root / "home"
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
        self.assertEqual(sealed["attempt_id"], checkpoint["attempts"][-1]["attempt_id"])
        self.assertEqual(sealed["mode"], "implementation")
        self.assertEqual(sealed["plan_index"], 0)
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
        self.assertEqual(launches[1]["session_action"], "resume")
        self.assertEqual(launches[1]["session_id"], checkpoint["sessions"][-1]["session_id"])

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
        self.assertEqual(code, ExitCode.INTEGRITY)
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
        self.assertFalse(state["attempts"][-1]["completed"])
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
        self.assertEqual(code, ExitCode.INTEGRITY)
        self.assertEqual(self.state()["failure"]["reason_code"], "state_integrity_failed")

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
        original_validate = runner._validate_final_result
        crashed = False

        def crash_after_review_checkpoint(*args, **kwargs):
            nonlocal crashed
            if not crashed:
                crashed = True
                raise SimulatedCrash("after reviewed checkpoint")
            return original_validate(*args, **kwargs)

        runner._validate_final_result = crash_after_review_checkpoint
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
