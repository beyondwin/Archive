import dataclasses
import importlib.util
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
    def __init__(self, owner, helper, stop_requested):
        self.owner = owner
        self.helper = helper
        self.stop_requested = stop_requested

    def launch(self, request, _lease, on_session_id=None):
        self.owner.leases.append(_lease)
        packet = json.loads(request.prompt.split("\nEXECUTION_PACKET=", 1)[1])
        self.owner.packets.append(packet)
        self.owner.requests.append(request)
        launch = len(self.owner.packets)
        session_id = request.session_id or str(uuid.UUID(int=launch))
        skip_capture = (
            self.owner.skip_session_capture_once
            or (
                packet["mode"] == "final_review_fix"
                and self.owner.skip_review_fix_session_capture_once
            )
        )
        self.owner.skip_session_capture_once = False
        if packet["mode"] == "final_review_fix":
            self.owner.skip_review_fix_session_capture_once = False
        if on_session_id is not None and not skip_capture:
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
            }
            return ProviderOutcome(
                "implemented", 0, session_id, result, None, {}, (), ""
            )
        if packet["mode"] == "final_review_fix":
            marker = request.worktree / "review-fix.txt"
            if self.owner.block_review_fix_until_stop:
                marker.write_text("partial review fix\n", encoding="utf-8")
                deadline = time.monotonic() + 5
                while not self.stop_requested() and time.monotonic() < deadline:
                    time.sleep(0.01)
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
        self.skip_session_capture_once = False
        self.skip_review_fix_session_capture_once = False
        self.block_review_fix_until_stop = False
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
            return ScriptedAdapter(
                self, values["helper"], values["stop_requested"]
            )

        return PlanRunner(
            self.paths,
            runtime_checker=runtime_checker,
            adapter_factory=adapter_factory,
            output=self.output.append,
            environment={"PATH": os.environ["PATH"]},
            event_hook=self.engine_event_hook,
        )

    def state(self):
        run_roots = list(self.paths.state_home.iterdir())
        self.assertEqual(len(run_roots), 1)
        return json.loads((run_roots[0] / "state.json").read_text(encoding="utf-8"))

    def test_runtime_paths_are_immutable(self):
        with self.assertRaises(dataclasses.FrozenInstanceError):
            self.paths.state_home = self.root / "other"

    def test_signal_gate_is_repeat_safe_and_restores_process_handlers(self):
        from plan_runner.engine import _SignalGate

        before = {
            signum: signal.getsignal(signum)
            for signum in (signal.SIGINT, signal.SIGTERM)
        }
        for signum in (signal.SIGINT, signal.SIGTERM):
            gate = _SignalGate()
            with gate:
                os.kill(os.getpid(), signum)
                os.kill(os.getpid(), signum)
                self.assertTrue(gate.requested())
            self.assertEqual(signal.getsignal(signum), before[signum])

    def _assert_graceful_signal_checkpoint(self, signum, *, drift=False):
        home = self.root / "home"
        fake_bin = self.root / "fake-bin"
        fake_bin.mkdir()
        fake = SKILL_ROOT / "evals" / "fake_claude.py"
        fake.chmod(fake.stat().st_mode | 0o100)
        (fake_bin / "claude").symlink_to(fake)
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
        command = [
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
        ]
        process = subprocess.Popen(
            command,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        state_path = None
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            roots = list((home / ".claude" / "plan-runner").glob("*/state.json"))
            if launch_log.exists() and roots:
                candidate = json.loads(roots[0].read_text(encoding="utf-8"))
                partial = (
                    Path(candidate["repository"]["worktree"])
                    / "partial-provider-edit.txt"
                )
                if candidate["sessions"] and partial.is_file():
                    state_path = roots[0]
                    break
            time.sleep(0.02)
        self.assertIsNotNone(state_path, "provider session was not captured")
        process.send_signal(signum)
        stdout, stderr = process.communicate(timeout=10)
        self.assertEqual(process.returncode, ExitCode.RESUMABLE, stderr)
        self.assertEqual(stderr, "")
        self.assertEqual(json.loads(stdout.splitlines()[-1])["status"], "resumable")
        checkpoint = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(checkpoint["status"], "resumable")
        self.assertEqual(checkpoint["plans"][0]["status"], "running")
        self.assertEqual(checkpoint["sessions"][-1]["health"], "healthy")
        sealed = checkpoint["failure"]["partial_worktree"]
        self.assertEqual(sealed["attempt_id"], checkpoint["attempts"][-1]["attempt_id"])
        self.assertEqual(sealed["mode"], "implementation")
        self.assertEqual(sealed["plan_index"], 0)
        self.assertEqual(sealed["branch"], checkpoint["repository"]["branch"])
        self.assertEqual(
            sealed["head"],
            git("rev-parse", "HEAD", cwd=Path(checkpoint["repository"]["worktree"])),
        )
        self.assertFalse(sealed["clean"])
        self.assertEqual(len(sealed["porcelain_digest"]), 64)
        self.assertEqual(len(sealed["tree_digest"]), 64)
        captured = checkpoint["sessions"][-1]["session_id"]
        first_launch = json.loads(launch_log.read_text().splitlines()[0])
        with self.assertRaises(ProcessLookupError):
            os.kill(first_launch["pid"], 0)

        if drift:
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
        if drift:
            self.assertEqual(resumed.returncode, ExitCode.INTEGRITY, resumed.stderr)
            self.assertEqual(len(launch_log.read_text().splitlines()), 1)
            return
        self.assertEqual(resumed.returncode, ExitCode.READY, resumed.stderr)
        launches = [
            json.loads(line)
            for line in launch_log.read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(launches[1]["session_action"], "resume")
        self.assertEqual(launches[1]["session_id"], captured)

    def test_dirty_resume_rejects_worktree_drift_before_provider_launch(self):
        self._assert_graceful_signal_checkpoint(signal.SIGINT, drift=True)

    def test_sigint_leaves_bounded_resumable_checkpoint(self):
        self._assert_graceful_signal_checkpoint(signal.SIGINT)

    def test_sigterm_leaves_bounded_resumable_checkpoint(self):
        self._assert_graceful_signal_checkpoint(signal.SIGTERM)

    def test_public_cli_defaults_are_claude_private_and_minimal(self):
        module_spec = importlib.util.spec_from_file_location(
            "claude_plan_runner_cli",
            SKILL_ROOT / "scripts" / "runner.py",
        )
        self.assertIsNotNone(module_spec)
        self.assertIsNotNone(module_spec.loader)
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)
        defaults = module._paths()
        self.assertEqual(
            defaults.state_home,
            Path.home() / ".claude" / "plan-runner",
        )
        self.assertEqual(
            defaults.worktree_home,
            Path.home() / ".claude" / "worktrees" / "plan-runner",
        )
        run_help = subprocess.run(
            [sys.executable, str(SKILL_ROOT / "scripts" / "runner.py"), "run", "--help"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        self.assertIn("--stall-seconds", run_help)
        for forbidden in (
            "--sandbox",
            "--timeout",
            "--token-budget",
            "--model-routing",
        ):
            self.assertNotIn(forbidden, run_help)

    def test_absolute_launcher_is_self_locating_from_unrelated_directory(self):
        completed = subprocess.run(
            [str(SKILL_ROOT / "scripts" / "runner"), "--help"],
            cwd=self.root,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("{run,resume,inspect}", completed.stdout)

    def test_multiple_specs_and_plans_are_ordered_and_finalization_is_fresh(self):
        code = self.runner().create_run(
            specs=self.specs,
            plans=self.plans,
            workspace=self.source,
            stall_seconds=30,
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
        self.assertEqual(
            state["immutable_config"]["permission_mode"],
            "bypassPermissions",
        )
        self.assertRegex(
            state["immutable_config"]["deny_tools_digest"],
            r"^[0-9a-f]{64}$",
        )
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
        self.assertFalse(fix_request.resume)
        self.assertIsInstance(uuid.UUID(fix_request.session_id), uuid.UUID)
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

    def test_sigint_during_review_fix_resumes_same_session_and_dirty_partial_fix(self):
        self.review_findings_once = True
        self.block_review_fix_until_stop = True
        signaled = False

        def signal_review_fix(_adapter, _request, packet, _session_id):
            nonlocal signaled
            if packet["mode"] == "final_review_fix" and not signaled:
                signaled = True
                threading.Timer(
                    0.05, lambda: os.kill(os.getpid(), signal.SIGINT)
                ).start()
            return None

        self.outcome_hook = signal_review_fix
        code = self.runner().create_run(
            specs=self.specs,
            plans=self.plans[:1],
            workspace=self.source,
            stall_seconds=30,
            model=None,
        )
        self.assertEqual(code, ExitCode.RESUMABLE)
        paused = self.state()
        self.assertEqual(paused["failure"]["pending_mode"], "final_review_fix")
        self.assertEqual(
            paused["finalization"]["pending_mode"], "final_review_fix"
        )
        self.assertEqual(paused["finalization"]["review_findings"][0]["id"], "R1")
        captured = paused["sessions"][-1]["session_id"]
        worktree = Path(paused["repository"]["worktree"])
        self.assertTrue(git("status", "--porcelain", cwd=worktree))

        self.block_review_fix_until_stop = False
        self.outcome_hook = None
        code = self.runner().resume(
            paused["run_id"],
            retry_blocked=False,
            retry_failed=False,
            strategy_note=None,
        )
        self.assertEqual(code, ExitCode.READY)
        fix_requests = [
            request
            for request, packet in zip(self.requests, self.packets, strict=True)
            if packet["mode"] == "final_review_fix"
        ]
        self.assertEqual(len(fix_requests), 2)
        self.assertTrue(fix_requests[-1].resume)
        self.assertEqual(fix_requests[-1].session_id, captured)
        self.assertFalse(git("status", "--porcelain", cwd=worktree))

    def test_review_fix_resume_uses_fresh_session_when_signal_capture_is_missing(self):
        self.review_findings_once = True
        self.block_review_fix_until_stop = True
        self.skip_review_fix_session_capture_once = True
        signaled = False

        def signal_review_fix(_adapter, _request, packet, _session_id):
            nonlocal signaled
            if packet["mode"] == "final_review_fix" and not signaled:
                signaled = True
                threading.Timer(
                    0.05, lambda: os.kill(os.getpid(), signal.SIGTERM)
                ).start()
            return None

        self.outcome_hook = signal_review_fix
        code = self.runner().create_run(
            specs=self.specs,
            plans=self.plans[:1],
            workspace=self.source,
            stall_seconds=30,
            model=None,
        )
        self.assertEqual(code, ExitCode.RESUMABLE)
        paused = self.state()
        first_fix_request = next(
            request
            for request, packet in zip(self.requests, self.packets, strict=True)
            if packet["mode"] == "final_review_fix"
        )
        self.assertEqual(paused["failure"]["next_session_action"], "fresh_session")

        self.block_review_fix_until_stop = False
        self.outcome_hook = None
        code = self.runner().resume(
            paused["run_id"],
            retry_blocked=False,
            retry_failed=False,
            strategy_note=None,
        )
        self.assertEqual(code, ExitCode.READY)
        fix_requests = [
            request
            for request, packet in zip(self.requests, self.packets, strict=True)
            if packet["mode"] == "final_review_fix"
        ]
        self.assertEqual(len(fix_requests), 2)
        self.assertFalse(fix_requests[-1].resume)
        self.assertNotEqual(
            fix_requests[-1].session_id, first_fix_request.session_id
        )

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
                        "argv": [sys.executable, "-c", "import time; time.sleep(0.15)"],
                        "cwd": ".",
                        "input_digest": "b" * 64,
                        "deadline_seconds": 1,
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
            time.sleep(0.08)
            self.assertFalse(self.leases[-1].expired(time.monotonic()))
            thread.join(2)
            self.assertEqual(errors, [])
            return None

        self.outcome_hook = run_silent_command
        code = self.runner().create_run(
            specs=self.specs,
            plans=self.plans[:1],
            workspace=self.source,
            stall_seconds=0.03,
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
            model=None,
        )
        self.assertEqual(code, ExitCode.READY)
        final_requests = [
            request
            for request, packet in zip(self.requests, self.packets, strict=True)
            if packet["mode"] == "finalization"
        ]
        self.assertEqual(len(final_requests), 3)
        self.assertFalse(final_requests[0].resume)
        self.assertTrue(final_requests[1].resume)
        self.assertEqual(
            final_requests[1].session_id, final_requests[0].session_id
        )
        self.assertFalse(final_requests[2].resume)
        self.assertNotEqual(
            final_requests[2].session_id, final_requests[1].session_id
        )

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
            model=None,
        )
        self.assertEqual(code, ExitCode.READY)
        finals = [
            (request, packet)
            for request, packet in zip(self.requests, self.packets, strict=True)
            if packet["mode"] == "finalization"
        ]
        self.assertEqual(len(finals), 2)
        self.assertTrue(finals[1][0].resume)
        self.assertEqual(
            finals[1][0].session_id, finals[0][0].session_id
        )
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
            model=None,
        )
        self.assertEqual(code, ExitCode.READY)
        final_requests = [
            request
            for request, packet in zip(self.requests, self.packets, strict=True)
            if packet["mode"] == "finalization"
        ]
        self.assertEqual(len(final_requests), 3)
        self.assertTrue(all(not request.resume for request in final_requests))
        self.assertEqual(
            len({request.session_id for request in final_requests}), 3
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

    def test_abnormal_compaction_and_session_damage_never_resume_context(self):
        failures = ["abnormal_compaction", "session_damage"]

        def contaminated(_adapter, _request, packet, session_id):
            if packet["mode"] == "implementation" and failures:
                kind = failures.pop(0)
                return ProviderOutcome(
                    kind, 1, session_id, None, "session_invalid", {}, (), ""
                )
            return None

        self.outcome_hook = contaminated
        code = self.runner().create_run(
            specs=self.specs,
            plans=self.plans[:1],
            workspace=self.source,
            stall_seconds=30,
            model=None,
        )
        self.assertEqual(code, ExitCode.READY)
        implementations = [
            (request, packet)
            for request, packet in zip(self.requests, self.packets, strict=True)
            if packet["mode"] == "implementation"
        ]
        self.assertEqual(len(implementations), 3)
        self.assertTrue(all(not request.resume for request, _ in implementations))
        self.assertEqual(
            len({request.session_id for request, _ in implementations}), 3
        )
        self.assertTrue(
            all(
                packet["required_strategy_change"]
                for _, packet in implementations[1:]
            )
        )
        self.assertTrue(
            all(
                "fresh provider session"
                in packet["operator_strategy_notes"][-1]["strategy_note"]
                for _, packet in implementations[1:]
            )
        )

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

    def test_missing_uncaptured_session_crash_recovers_without_phantom_resume(self):
        self.skip_session_capture_once = True
        missing_once = True

        def session_missing(_adapter, request, packet, _session_id):
            nonlocal missing_once
            if packet["mode"] == "implementation" and missing_once:
                missing_once = False
                return ProviderOutcome(
                    "session_missing",
                    1,
                    request.session_id,
                    None,
                    "session_invalid",
                    {},
                    (),
                    "",
                )
            return None

        runner = self.runner()
        self.outcome_hook = session_missing

        def crash_after_checkpoint(*_args, **_kwargs):
            raise SimulatedCrash("after non-implemented checkpoint")

        runner._recover = crash_after_checkpoint
        with self.assertRaises(SimulatedCrash):
            runner.create_run(
                specs=self.specs,
                plans=self.plans[:1],
                workspace=self.source,
                stall_seconds=30,
                model=None,
            )
        crashed = self.state()
        self.assertTrue(crashed["attempts"][-1]["completed"])
        self.assertEqual(crashed["attempts"][-1]["outcome"], "session_missing")
        self.assertEqual(crashed["sessions"], [])
        phantom = self.requests[0].session_id

        code = self.runner().resume(
            crashed["run_id"],
            retry_blocked=False,
            retry_failed=False,
            strategy_note=None,
        )
        self.assertEqual(code, ExitCode.READY)
        retry_request = self.requests[1]
        retry_packet = self.packets[1]
        self.assertFalse(retry_request.resume)
        self.assertNotEqual(retry_request.session_id, phantom)
        self.assertTrue(retry_packet["required_strategy_change"])
        self.assertTrue(retry_packet["operator_strategy_notes"])
        self.assertIn(
            "fresh provider session",
            retry_packet["operator_strategy_notes"][-1]["strategy_note"],
        )

    def test_session_capture_survives_controller_crash_and_resumes_explicitly(self):
        self.crash_after_session = True
        with self.assertRaises(SimulatedCrash):
            self.runner().create_run(
                specs=self.specs,
                plans=self.plans[:1],
                workspace=self.source,
                stall_seconds=30,
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
        self.assertTrue(self.requests[-2].resume)

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
        self.assertFalse(self.requests[launch_count].resume)
        self.assertNotEqual(
            self.requests[launch_count].session_id,
            self.requests[launch_count - 1].session_id,
        )
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
            model=None,
        )
        self.assertEqual(code, ExitCode.READY)
        implementations = [
            request
            for request, packet in zip(self.requests, self.packets, strict=True)
            if packet["mode"] == "implementation"
        ]
        self.assertEqual(len(implementations), 2)
        self.assertTrue(implementations[1].resume)
        self.assertEqual(
            implementations[1].session_id, implementations[0].session_id
        )

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
                "provider": "claude",
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

    def test_implemented_schema_uses_reported_done_only_task_ledger(self):
        schema = json.loads(
            (
                SKILL_ROOT / "templates" / "plan-result.schema.json"
            ).read_text(encoding="utf-8")
        )
        implemented = next(
            branch
            for branch in schema["oneOf"]
            if branch["properties"]["status"].get("const") == "implemented"
        )
        self.assertEqual(
            implemented["properties"]["task_ledger"]["$ref"],
            "#/$defs/implementedTaskLedger",
        )
        status = schema["$defs"]["implementedTaskLedger"]["items"][
            "properties"
        ]["status"]
        self.assertEqual(status, {"const": "reported_done"})

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

    def test_cli_parse_failures_are_structured_contract_errors(self):
        cases = (
            ["resume"],
            ["resume", "--unknown"],
            ["run", "--workspace", str(self.source)],
        )
        for arguments in cases:
            with self.subTest(arguments=arguments):
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
                payload = json.loads(completed.stdout)
                self.assertEqual(payload["status"], "failed")
                self.assertEqual(
                    payload["reason_code"], "invalid_invocation"
                )

    def test_inspect_is_read_only_and_concise(self):
        self.runner().create_run(
            specs=self.specs,
            plans=self.plans,
            workspace=self.source,
            stall_seconds=30,
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
