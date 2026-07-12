#!/usr/bin/env python3
"""Focused, production-interface checks for the bounded CPE v4 scheduler."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace


SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))

from cpe_runtime.command_evidence import build_method_evidence, normalize_codex_items
from cpe_runtime.evidence import put_method_evidence
from cpe_runtime.kernel import RunKernel, Transition
from cpe_runtime.manifest import create_manifest
from cpe_runtime.packets import build_packet
from cpe_runtime.scheduler import (
    ExternalModelInterruption,
    LifecycleOperations,
    PreTurnInterruption,
    ReviewScope,
    RuntimeUpgradeInterruption,
    run_task_cycle_v4,
    run_tasks_v4,
)
from cpe_runtime.task_contracts import TaskContractV4, compile_task_contract
from cpe_runtime.worker import WorkerResult


TEST_COMMAND = "python3 verify.py"
CORE_ATTESTATION = {
    "verified": True,
    "actual_model": "gpt-5.6-sol",
    "actual_reasoning": "high",
}


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode:
        raise AssertionError(result.stderr)
    return result.stdout.strip()


class MemoryKernel:
    """Faithful projection subset; checkpoint helpers remain production code."""

    def __init__(self, run_dir: Path, source_head: str, task_ids: tuple[str, ...]):
        self.run_dir = run_dir
        self._state = {
            "schema_version": "4",
            "run_id": "scheduler-v4-fixture",
            "lifecycle": "running",
            "source_head": source_head,
            "checkpoint_head": None,
            "candidate_checkpoints": [],
            "verified_checkpoints": [],
            "attempts": [],
            "verdicts": [],
            "attempt_budget": {"limit": 40, "used": 0},
            "decisions": [],
            "artifact_index": [],
            "backlog": [],
            "repair_roots": {},
            "tasks": {
                task_id: {
                    "status": "ready",
                    "wait_reason": None,
                    "resume_phase": None,
                    "active_attempt_id": None,
                }
                for task_id in task_ids
            },
            "runtime": {"version": "4.0.0-dev", "build_id": "fixture-a"},
        }
        self.transitions: list[Transition] = []

    @property
    def state(self) -> dict:
        return self._state

    def transition(self, command: Transition) -> dict:
        self.transitions.append(command)
        event_type = command.event_type
        record = {"task_id": command.task_id, **command.payload}
        if event_type == "attempt.started":
            assert self._state["attempt_budget"]["used"] < 40
            self._state["attempt_budget"]["used"] += 1
            self._state["attempts"].append(
                {
                    "task_id": command.task_id,
                    "attempt_id": command.attempt_id,
                    "status": "started",
                    **command.payload,
                }
            )
            self._state["tasks"][str(command.task_id)]["active_attempt_id"] = command.attempt_id
        elif event_type == "attempt.completed":
            attempt = next(
                item for item in self._state["attempts"]
                if item["attempt_id"] == command.attempt_id
            )
            attempt.update(command.payload)
            self._state["tasks"][str(command.task_id)]["active_attempt_id"] = None
        elif event_type == "task.status_changed":
            task = self._state["tasks"][str(command.task_id)]
            task["status"] = command.payload["to"]
            if command.payload["to"] in {"waiting_external", "waiting_user"}:
                task["wait_reason"] = command.payload["wait_reason"]
                task["resume_phase"] = command.payload["resume_phase"]
                task["active_attempt_id"] = command.payload.get("active_attempt_id")
            elif command.payload["to"] == "blocked":
                task["wait_reason"] = command.payload["wait_reason"]
                task["resume_phase"] = None
                task["active_attempt_id"] = None
            elif command.payload["from"] in {"waiting_external", "waiting_user"}:
                task["wait_reason"] = None
                task["resume_phase"] = None
                task["active_attempt_id"] = None
        elif event_type == "candidate.checkpoint_recorded":
            self._state["candidate_checkpoints"].append(record)
        elif event_type == "task.checkpoint_verified":
            self._state["verified_checkpoints"].append(record)
            self._state["checkpoint_head"] = command.payload["commit"]
        elif event_type == "verdict.recorded":
            self._state["verdicts"].append(record)
        elif event_type == "decision.recorded":
            self._state["decisions"].append(command.payload)
        elif event_type == "evidence.attached":
            self._state["artifact_index"].append(record)
        elif event_type == "runtime.upgraded":
            self._state["runtime"] = dict(command.payload["to"])
        return self._state


def init_repo(root: Path) -> tuple[Path, str]:
    repo = root / "product"
    repo.mkdir(parents=True)
    (repo / "product.py").write_text("VALUE = 0\n", encoding="utf-8")
    (repo / "verify.py").write_text(
        "from pathlib import Path\n"
        "Path('build-output.txt').write_text('disposable\\n')\n"
        "raise SystemExit(0)\n",
        encoding="utf-8",
    )
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "fixture@example.invalid")
    git(repo, "config", "user.name", "Fixture")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "baseline")
    return repo, git(repo, "rev-parse", "HEAD")


def contract(
    task_id: str = "T1",
    *,
    dependencies: tuple[str, ...] = (),
    semantic: bool = False,
) -> TaskContractV4:
    return compile_task_contract(
        {
            "id": task_id,
            "title": f"bounded lifecycle {task_id}",
            "task_type": "tdd_implementation",
            "dependencies": list(dependencies),
            "task_source": f"### Task {task_id}\nBound the lifecycle.\n",
            "file_claims": ["product.py", "*-partial.tmp"],
            "acceptance_commands": [TEST_COMMAND],
            "required_evidence": ["red", "green"]
            + (["semantic_verification"] if semantic else []),
            "checkpoint_message": f"feat: complete {task_id}",
        },
        source_hashes={"plan": "f" * 64, "spec_sections": {}},
    )


def command_event(exit_code: int, status: str, output: str) -> dict[str, object]:
    return {
        "type": "item.completed",
        "item": {
            "id": f"command-{exit_code}-{status}",
            "type": "command_execution",
            "command": TEST_COMMAND,
            "aggregated_output": output,
            "exit_code": exit_code,
            "status": status,
        },
    }


def mutation_event() -> dict[str, object]:
    return {
        "type": "item.completed",
        "item": {
            "id": "mutation",
            "type": "file_change",
            "changes": [{"path": "product.py", "kind": "update"}],
            "status": "completed",
        },
    }


def method_ref(run_dir: Path, task: TaskContractV4, packet_sha256: str, serial: int) -> dict:
    observations = normalize_codex_items(
        (
            command_event(1, "failed", f"RED-{serial}"),
            mutation_event(),
            command_event(0, "completed", f"GREEN-{serial}"),
        ),
        test_commands=task.acceptance_commands,
    )
    evidence = build_method_evidence(task.task_type, observations)
    return put_method_evidence(
        run_dir,
        evidence,
        task_id=task.task_id,
        packet_sha256=packet_sha256,
        contract_sha256=task.contract_sha256,
    )


def result(
    *,
    verdict: dict[str, object] | None = None,
    method_evidence_ref: dict | None = None,
) -> WorkerResult:
    payload = {
        "status": "completed",
        "summary": "fixture result",
        "changed_files": [],
        "findings": list((verdict or {}).get("findings", [])),
        "evidence_refs": [],
        "missing_evidence": list((verdict or {}).get("missing_evidence", [])),
        "verification": [],
        "verdict": verdict,
        "method_evidence_ref": method_evidence_ref,
    }
    return WorkerResult("completed", payload, CORE_ATTESTATION, {}, 1, "0" * 64)


def fixture_scope_payload(scope: ReviewScope) -> dict[str, object]:
    return {
        "kind": scope.kind,
        "base_commit": scope.base_commit,
        "candidate_commit": scope.candidate_commit,
        "previous_findings": list(scope.previous_findings),
        "reopen_full_task_diff": scope.reopen_full_task_diff,
        "boundary_changes": list(scope.boundary_changes),
    }


def fixture_scope_sha256(scope: ReviewScope) -> str:
    raw = json.dumps(
        fixture_scope_payload(scope), sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(b"CPE-REVIEW-SCOPE-V4\0" + raw).hexdigest()


class FixtureOperations:
    def __init__(
        self,
        repo: Path,
        run_dir: Path,
        task: TaskContractV4,
        reviews: list[dict[str, object]],
        *,
        boundary_changes: tuple[str, ...] = (),
    ):
        self.repo = repo
        self.run_dir = run_dir
        self.task = task
        self.reviews = list(reviews)
        self.boundary_changes = boundary_changes
        self.packet_sha256 = hashlib.sha256(task.contract_sha256.encode()).hexdigest()
        self.serial = 0
        self.repair_calls = 0
        self.review_scopes: list[ReviewScope] = []
        self.semantic_calls = 0
        self.pre_turn_failures: list[BaseException] = []
        self.implementation_failures: list[BaseException] = []
        self.pre_turn_by_phase: dict[str, list[BaseException]] = {}
        self.review_failures: list[BaseException] = []
        self.repair_failures: list[BaseException] = []
        self.semantic_failures: list[BaseException] = []
        self.partial_failure_phase: dict[str, BaseException] = {}
        self.out_of_claim_partial_phases: set[str] = set()
        self.invalid_method_evidence_phases: set[str] = set()
        self.review_binding_tamper: dict[str, object] = {}
        self.deterministic_exception: BaseException | None = None
        self.kernel: object | None = None

    def before_model_turn(self, phase: str, _attempt_id: str) -> None:
        phase_failures = self.pre_turn_by_phase.get(phase, [])
        if phase_failures:
            raise phase_failures.pop(0)
        if self.pre_turn_failures:
            raise self.pre_turn_failures.pop(0)

    def _partial_failure(self, phase: str) -> None:
        failure = self.partial_failure_phase.pop(phase, None)
        if failure is None:
            return
        if phase in self.out_of_claim_partial_phases:
            (self.repo / "outside.txt").write_text("unsafe partial\n")
            raise failure
        (self.repo / "product.py").write_text(
            f"PARTIAL = {phase!r}\n", encoding="utf-8"
        )
        (self.repo / f"{phase}-partial.tmp").write_text(
            "partial\n", encoding="utf-8"
        )
        raise failure

    def implementation(self, task: TaskContractV4, _attempt_id: str) -> WorkerResult:
        self._partial_failure("implementation")
        if self.implementation_failures:
            raise self.implementation_failures.pop(0)
        self.serial += 1
        (self.repo / "product.py").write_text(
            f"VALUE = {self.serial!r}\nTASK = {task.task_id!r}\n", encoding="utf-8"
        )
        ref = method_ref(self.run_dir, task, self.packet_sha256, self.serial)
        if "implementation" in self.invalid_method_evidence_phases:
            ref = {**ref, "contract_sha256": "0" * 64}
        return result(method_evidence_ref=ref)

    def repair(self, task: TaskContractV4, _finding: dict, _attempt_id: str) -> WorkerResult:
        self.repair_calls += 1
        self._partial_failure("repair")
        if self.repair_failures:
            raise self.repair_failures.pop(0)
        self.serial += 1
        (self.repo / "product.py").write_text(
            f"VALUE = {self.serial!r}\nTASK = {task.task_id!r}\n", encoding="utf-8"
        )
        ref = method_ref(self.run_dir, task, self.packet_sha256, self.serial)
        if "repair" in self.invalid_method_evidence_phases:
            ref = {**ref, "contract_sha256": "0" * 64}
        return result(method_evidence_ref=ref)

    def review(self, task: TaskContractV4, scope: ReviewScope, _attempt_id: str) -> WorkerResult:
        self._partial_failure("task_review")
        if self.review_failures:
            raise self.review_failures.pop(0)
        self.review_scopes.append(scope)
        verdict = dict(self.reviews.pop(0))
        candidate_tree = git(self.repo, "rev-parse", f"{scope.candidate_commit}^{{tree}}")
        revision = 0
        if self.kernel is not None:
            revision = len(getattr(self.kernel, "state")["candidate_checkpoints"])
        binding = {
            "task_id": task.task_id,
            "candidate_commit": scope.candidate_commit,
            "candidate_tree": candidate_tree,
            "contract_sha256": task.contract_sha256,
            "worktree_revision": revision,
            "review_scope_sha256": fixture_scope_sha256(scope),
            "requested_scope": fixture_scope_payload(scope),
        }
        binding.update(self.review_binding_tamper)
        verdict["review_binding"] = binding
        return result(verdict=verdict)

    def deterministic_verification(self, *_args) -> tuple[bool, str]:
        if self.deterministic_exception is not None:
            (self.repo / "product.py").write_text("VERIFIER_PARTIAL = 1\n")
            (self.repo / "verifier-partial.tmp").write_text("partial\n")
            raise self.deterministic_exception
        return True, "fixture deterministic verification passed"

    def semantic_verification(self, *_args) -> WorkerResult:
        self.semantic_calls += 1
        self._partial_failure("verification")
        if self.semantic_failures:
            raise self.semantic_failures.pop(0)
        return result(verdict=passed())

    def repair_boundary_changes(self, *_args) -> tuple[str, ...]:
        return self.boundary_changes

    def lifecycle(self) -> LifecycleOperations:
        return LifecycleOperations(
            packet_sha256=self.packet_sha256,
            before_model_turn=self.before_model_turn,
            implementation=self.implementation,
            repair=self.repair,
            review=self.review,
            deterministic_verification=self.deterministic_verification,
            semantic_verification=self.semantic_verification,
            repair_boundary_changes=self.repair_boundary_changes,
            acceptance_environment=os.environ,
        )


def passed() -> dict[str, object]:
    return {
        "status": "passed",
        "findings": [],
        "missing_evidence": [],
        "worktree_revision": 0,
    }


def changes(
    root: str = "defect:parser",
    *,
    category: str = "product_defect",
    release_impact: bool = False,
    impact_class: str | None = None,
) -> dict[str, object]:
    finding = {
        "severity": "major",
        "action": "repair the bounded defect",
        "root_cause_key": root,
        "failure_category": category,
        "release_impact": release_impact,
    }
    if impact_class:
        finding["impact_class"] = impact_class
    return {
        "status": "changes_requested",
        "findings": [finding],
        "missing_evidence": [],
        "worktree_revision": 0,
    }


def run_fixture(
    root: Path,
    reviews: list[dict[str, object]],
    *,
    boundary_changes: tuple[str, ...] = (),
) -> tuple[object, MemoryKernel, FixtureOperations, Path]:
    repo, source_head = init_repo(root)
    task = contract()
    run_dir = root / "run"
    kernel = MemoryKernel(run_dir, source_head, (task.task_id,))
    fixture = FixtureOperations(
        repo, run_dir, task, reviews, boundary_changes=boundary_changes
    )
    fixture.kernel = kernel
    cycle = run_task_cycle_v4(task, fixture.lifecycle(), kernel, repo, run_dir)
    return cycle, kernel, fixture, repo


def assert_first_pass(root: Path) -> None:
    cycle, kernel, fixture, repo = run_fixture(root, [passed()])
    assert cycle.phases == (
        "preflight",
        "implementation",
        "candidate",
        "acceptance",
        "task_review",
        "verification",
        "verified_checkpoint",
    ), cycle
    assert cycle.model_attempts == 2, cycle
    assert cycle.state["attempt_budget"] == {"limit": 40, "used": 2}
    assert cycle.status == "completed"
    assert fixture.semantic_calls == 0
    assert fixture.review_scopes[0].kind == "task_diff"
    assert fixture.review_scopes[0].base_commit == kernel.state["source_head"]
    assert any(
        transition.event_type == "evidence.attached"
        and transition.payload.get("kind") == "method_evidence"
        for transition in kernel.transitions
    )
    assert len(kernel.state["verdicts"]) == 1
    assert kernel.state["verdicts"][0]["status"] == "passed"
    assert git(repo, "status", "--porcelain=v1", "--untracked-files=all") == ""
    assert not (repo / "build-output.txt").exists()


def assert_repairs(root: Path) -> None:
    one, _kernel, one_fixture, _repo = run_fixture(
        root / "one", [changes(), passed()]
    )
    assert one.phases.count("repair") == 1 and one.model_attempts == 4, one
    assert one_fixture.repair_calls == 1
    assert one_fixture.review_scopes[-1].kind == "repair_delta"
    assert len(one_fixture.review_scopes[-1].previous_findings) == 1
    assert one_fixture.review_scopes[-1].reopen_full_task_diff is False

    two, _kernel, two_fixture, _repo = run_fixture(
        root / "two", [changes(), changes(), passed()]
    )
    assert two.phases.count("repair") == 2 and two.model_attempts == 6, two
    assert two_fixture.repair_calls == 2

    third, _kernel, third_fixture, _repo = run_fixture(
        root / "third", [changes(), changes(), changes()]
    )
    assert third.status == "completed", third
    assert third_fixture.repair_calls == 2, "a third same-root repair is forbidden"
    assert third.state["repair_roots"] == {"defect:parser": 2}
    assert [item["root_cause_key"] for item in third.state["backlog"]] == [
        "defect:parser"
    ]

    release, _kernel, release_fixture, _repo = run_fixture(
        root / "release-impact",
        [
            changes(
                release_impact=True,
                impact_class="security_privacy_or_state_integrity",
            ),
            changes(
                release_impact=True,
                impact_class="security_privacy_or_state_integrity",
            ),
            changes(
                release_impact=True,
                impact_class="security_privacy_or_state_integrity",
            ),
        ],
    )
    assert release.status == "blocked", release
    assert release_fixture.repair_calls == 2
    assert release.state["backlog"] == []


def assert_scope_policy(root: Path) -> None:
    expanded, _kernel, fixture, _repo = run_fixture(
        root / "expanded",
        [changes("review:new-check", category="review_scope_expansion")],
    )
    assert expanded.status == "completed"
    assert fixture.repair_calls == 0
    assert expanded.state["backlog"][0]["category"] == "review_scope_expansion"

    reopened, _kernel, reopened_fixture, _repo = run_fixture(
        root / "reopened",
        [changes(), passed()],
        boundary_changes=("security",),
    )
    scope = reopened_fixture.review_scopes[-1]
    assert scope.reopen_full_task_diff is True
    assert scope.kind == "task_diff"
    assert scope.boundary_changes == ("security",)


def assert_resume_and_budget(root: Path) -> None:
    repo, source_head = init_repo(root / "quota")
    task = contract()
    run_dir = root / "quota" / "run"
    kernel = MemoryKernel(run_dir, source_head, (task.task_id,))
    fixture = FixtureOperations(repo, run_dir, task, [passed()])
    fixture.kernel = kernel
    fixture.pre_turn_failures.append(PreTurnInterruption("provider not entered"))
    first = run_task_cycle_v4(task, fixture.lifecycle(), kernel, repo, run_dir)
    assert first.status == "waiting_external" and first.model_attempts == 0, first
    assert kernel.state["attempt_budget"]["used"] == 0

    fixture.implementation_failures.append(
        ExternalModelInterruption("quota_transient", "provider:quota")
    )
    second = run_task_cycle_v4(task, fixture.lifecycle(), kernel, repo, run_dir)
    assert second.status == "waiting_external" and second.model_attempts == 1, second
    attempt_id = kernel.state["attempts"][0]["attempt_id"]
    third = run_task_cycle_v4(task, fixture.lifecycle(), kernel, repo, run_dir)
    assert third.status == "completed" and third.model_attempts == 1, third
    assert kernel.state["attempt_budget"]["used"] == 2
    assert kernel.state["attempts"][0]["attempt_id"] == attempt_id

    blocked_root = root / "budget"
    blocked_repo, blocked_head = init_repo(blocked_root)
    blocked_task = contract()
    blocked_kernel = MemoryKernel(
        blocked_root / "run", blocked_head, (blocked_task.task_id,)
    )
    blocked_kernel.state["attempt_budget"]["used"] = 40
    blocked_fixture = FixtureOperations(
        blocked_repo, blocked_root / "run", blocked_task, [passed()]
    )
    blocked_fixture.kernel = blocked_kernel
    blocked = run_task_cycle_v4(
        blocked_task,
        blocked_fixture.lifecycle(),
        blocked_kernel,
        blocked_repo,
        blocked_root / "run",
    )
    assert blocked.status == "blocked" and blocked.model_attempts == 0, blocked


def assert_runtime_upgrade_resume(root: Path) -> None:
    repo, source_head = init_repo(root)
    first_task = contract("T1")
    second_task = contract("T2", dependencies=("T1",))
    run_dir = root / "run"
    kernel = MemoryKernel(run_dir, source_head, ("T1", "T2"))
    first_ops = FixtureOperations(repo, run_dir, first_task, [passed()])
    second_ops = FixtureOperations(repo, run_dir, second_task, [passed()])
    first_ops.kernel = kernel
    second_ops.kernel = kernel
    second_ops.implementation_failures.append(
        RuntimeUpgradeInterruption("runtime:adapter", "4.0.1", "fixture-b")
    )
    operations = {"T1": first_ops.lifecycle(), "T2": second_ops.lifecycle()}
    initial = run_tasks_v4(
        (first_task, second_task), operations, kernel, repo, run_dir
    )
    assert [item.status for item in initial] == ["completed", "waiting_external"]
    assert any(
        transition.event_type == "evidence.attached"
        and transition.payload.get("kind") == "model_interruption"
        for transition in kernel.transitions
    )
    checkpoint = kernel.state["checkpoint_head"]
    assert checkpoint == kernel.state["verified_checkpoints"][0]["commit"]
    kernel.transition(
        Transition(
            "runtime.upgraded",
            {
                "from": dict(kernel.state["runtime"]),
                "to": {"version": "4.0.1", "build_id": "fixture-b"},
                "checkpoint_head": checkpoint,
            },
        )
    )
    resumed = run_tasks_v4(
        (first_task, second_task), operations, kernel, repo, run_dir
    )
    assert len(resumed) == 1 and resumed[0].task_id == "T2"
    assert resumed[0].status == "completed", resumed[0]
    assert kernel.state["run_id"] == "scheduler-v4-fixture"


def assert_task_local_external_wait(root: Path) -> None:
    repo, source_head = init_repo(root)
    first_task = contract("T1")
    independent_task = contract("T2")
    run_dir = root / "run"
    kernel = MemoryKernel(run_dir, source_head, ("T1", "T2"))
    first_ops = FixtureOperations(repo, run_dir, first_task, [passed()])
    first_ops.implementation_failures.append(
        ExternalModelInterruption("quota_transient", "provider:quota:T1")
    )
    independent_ops = FixtureOperations(repo, run_dir, independent_task, [passed()])
    first_ops.kernel = kernel
    independent_ops.kernel = kernel
    outcomes = run_tasks_v4(
        (first_task, independent_task),
        {"T1": first_ops.lifecycle(), "T2": independent_ops.lifecycle()},
        kernel,
        repo,
        run_dir,
    )
    assert [item.status for item in outcomes] == ["waiting_external", "completed"], outcomes
    assert kernel.state["attempts"][0]["status"] == "started"
    assert kernel.state["verified_checkpoints"][0]["task_id"] == "T2"


def assert_real_kernel_first_pass(root: Path) -> None:
    repo, source_head = init_repo(root)
    task = contract()
    plan = root / "plan.md"
    pricing = root / "pricing.json"
    plan.write_text("# plan\n", encoding="utf-8")
    pricing.write_text("{}\n", encoding="utf-8")
    task_record = {
        "id": task.task_id,
        "title": task.title,
        "dependencies": list(task.dependencies),
        "file_claims": list(task.file_claims),
        "spec_refs": [],
        "acceptance_command": "\n".join(task.acceptance_commands),
        "task_contract": task.body(),
        "task_contract_sha256": task.contract_sha256,
    }
    draft = build_packet(SimpleNamespace(sources=(), spec_manifest=None), task_record)
    manifest = create_manifest(
        "scheduler-real-kernel",
        "interactive",
        root,
        repo,
        plan,
        None,
        [task_record],
        pricing,
        source_head=source_head,
    )
    run_dir = root / "run"
    kernel = RunKernel.initialize(run_dir, manifest, [draft])
    fixture = FixtureOperations(repo, run_dir, task, [passed()])
    fixture.packet_sha256 = draft.sha256
    fixture.kernel = kernel
    cycle = run_task_cycle_v4(task, fixture.lifecycle(), kernel, repo, run_dir)
    assert cycle.status == "completed", cycle
    assert kernel.state["attempt_budget"] == {"limit": 40, "used": 2}
    assert len(kernel.state["verified_checkpoints"]) == 1
    assert len(kernel.state["verdicts"]) == 1
    assert any(item["kind"] == "method_evidence" for item in kernel.state["artifact_index"])
    assert kernel.state["tasks"]["T1"]["status"] == "completed"


def initialize_real_runtime(
    root: Path,
    tasks: tuple[TaskContractV4, ...],
    reviews: dict[str, list[dict[str, object]]],
) -> tuple[Path, Path, RunKernel, dict[str, FixtureOperations]]:
    repo, source_head = init_repo(root)
    plan = root / "plan.md"
    pricing = root / "pricing.json"
    plan.write_text("# plan\n", encoding="utf-8")
    pricing.write_text("{}\n", encoding="utf-8")
    records = [
        {
            "id": task.task_id,
            "title": task.title,
            "dependencies": list(task.dependencies),
            "file_claims": list(task.file_claims),
            "spec_refs": [],
            "acceptance_command": "\n".join(task.acceptance_commands),
            "task_contract": task.body(),
            "task_contract_sha256": task.contract_sha256,
        }
        for task in tasks
    ]
    compiled = SimpleNamespace(sources=(), spec_manifest=None)
    drafts = [build_packet(compiled, record) for record in records]
    manifest = create_manifest(
        f"scheduler-real-{root.name}",
        "interactive",
        root,
        repo,
        plan,
        None,
        records,
        pricing,
        source_head=source_head,
    )
    run_dir = root / "run"
    kernel = RunKernel.initialize(run_dir, manifest, drafts)
    operations: dict[str, FixtureOperations] = {}
    for task, draft in zip(tasks, drafts, strict=True):
        fixture = FixtureOperations(repo, run_dir, task, reviews[task.task_id])
        fixture.packet_sha256 = draft.sha256
        fixture.kernel = kernel
        operations[task.task_id] = fixture
    return repo, run_dir, kernel, operations


def assert_real_kernel_exact_phase_resume(root: Path) -> None:
    task = contract()
    repo, run_dir, kernel, fixtures = initialize_real_runtime(
        root / "implementation", (task,), {"T1": [passed()]}
    )
    fixture = fixtures["T1"]
    fixture.partial_failure_phase["implementation"] = ExternalModelInterruption(
        "quota_transient", "provider:quota:implementation"
    )
    first = run_task_cycle_v4(task, fixture.lifecycle(), kernel, repo, run_dir)
    assert first.status == "waiting_external", first
    implementation_attempt = kernel.state["tasks"]["T1"]["active_attempt_id"]
    assert kernel.state["tasks"]["T1"]["resume_phase"] == "implementation"
    assert git(repo, "rev-parse", "HEAD") == kernel.state["source_head"]
    assert git(repo, "status", "--porcelain=v1", "--untracked-files=all") == ""
    resumed = run_task_cycle_v4(task, fixture.lifecycle(), kernel, repo, run_dir)
    assert resumed.status == "completed", resumed
    assert kernel.state["attempt_budget"]["used"] == 2
    assert any(
        item["attempt_id"] == implementation_attempt and item["status"] == "completed"
        for item in kernel.state["attempts"]
    )

    task = contract()
    repo, run_dir, kernel, fixtures = initialize_real_runtime(
        root / "review", (task,), {"T1": [passed()]}
    )
    fixture = fixtures["T1"]
    fixture.review_failures.append(
        ExternalModelInterruption("quota_transient", "provider:quota:review")
    )
    first = run_task_cycle_v4(task, fixture.lifecycle(), kernel, repo, run_dir)
    assert first.status == "waiting_external", first
    waiting = kernel.state["tasks"]["T1"]
    assert waiting["status"] == "waiting_external", waiting
    assert waiting["resume_phase"] == "task_review", waiting
    review_attempt = next(
        item["attempt_id"]
        for item in kernel.state["attempts"]
        if item["kind"] == "task_review"
    )
    resumed = run_task_cycle_v4(task, fixture.lifecycle(), kernel, repo, run_dir)
    assert resumed.status == "completed", resumed
    assert kernel.state["attempt_budget"]["used"] == 2
    assert len(
        [item for item in kernel.state["attempts"] if item["attempt_id"] == review_attempt]
    ) == 1
    assert kernel.state["tasks"]["T1"]["status"] == "completed"

    semantic_task = contract("T1", semantic=True)
    repo, run_dir, kernel, fixtures = initialize_real_runtime(
        root / "semantic", (semantic_task,), {"T1": [passed()]}
    )
    semantic = fixtures["T1"]
    semantic.semantic_failures.append(
        ExternalModelInterruption("provider_transient", "provider:semantic")
    )
    first = run_task_cycle_v4(
        semantic_task, semantic.lifecycle(), kernel, repo, run_dir
    )
    assert first.status == "waiting_external", first
    assert any(
        item.get("kind") == "review_evidence"
        for item in kernel.state["artifact_index"]
    )
    assert kernel.state["tasks"]["T1"]["resume_phase"] == "verification"
    verification_attempt = next(
        item["attempt_id"]
        for item in kernel.state["attempts"]
        if item["kind"] == "verification"
    )
    resumed = run_task_cycle_v4(
        semantic_task, semantic.lifecycle(), kernel, repo, run_dir
    )
    assert resumed.status == "completed", resumed
    assert kernel.state["attempt_budget"]["used"] == 3
    assert any(
        item["attempt_id"] == verification_attempt and item["status"] == "completed"
        for item in kernel.state["attempts"]
    )


def assert_review_binding_and_all_findings(root: Path) -> None:
    for name, tamper in (
        ("stale-candidate", {"candidate_commit": "0" * 40}),
        ("substituted-contract", {"contract_sha256": "1" * 64}),
        ("scope-mismatch", {"review_scope_sha256": "2" * 64}),
    ):
        task = contract()
        repo, run_dir, kernel, fixtures = initialize_real_runtime(
            root / name, (task,), {"T1": [passed()]}
        )
        fixtures["T1"].review_binding_tamper = tamper
        cycle = run_task_cycle_v4(
            task, fixtures["T1"].lifecycle(), kernel, repo, run_dir
        )
        assert cycle.status == "blocked", (name, cycle)
        assert kernel.state["verified_checkpoints"] == []

    generic = changes("review:extra", category="review_scope_expansion")["findings"][0]
    security = changes(
        "security:boundary",
        release_impact=True,
        impact_class="security_privacy_or_state_integrity",
    )["findings"][0]
    evidence = changes(
        "evidence:authenticity", category="evidence_integrity_failure"
    )["findings"][0]
    for name, blocker in (("mixed-security", security), ("mixed-evidence", evidence)):
        task = contract()
        verdict = {
            "status": "changes_requested",
            "findings": [generic, blocker],
            "missing_evidence": [],
            "worktree_revision": 0,
        }
        repo, run_dir, kernel, fixtures = initialize_real_runtime(
            root / name, (task,), {"T1": [verdict]}
        )
        if name == "mixed-security":
            for count in (1, 2):
                kernel.transition(
                    Transition(
                        "decision.recorded",
                        {
                            "decision_kind": "repair_root_updated",
                            "selected_action": "repair",
                            "basis": "fixture exhausted prior same-root repairs",
                            "approval_basis": "standing_autonomy_policy",
                            "root_cause_key": "security:boundary",
                            "repair_count": count,
                        },
                        task_id="T1",
                    )
                )
        cycle = run_task_cycle_v4(
            task, fixtures["T1"].lifecycle(), kernel, repo, run_dir
        )
        assert cycle.status == "blocked", (name, cycle)
        assert kernel.state["verified_checkpoints"] == []
        assert any(
            decision.get("decision_kind") == "backlog_added"
            for decision in kernel.state["decisions"]
        )


def assert_repair_timing_and_rollback(root: Path) -> None:
    task = contract()
    repo, run_dir, kernel, fixtures = initialize_real_runtime(
        root / "pre-turn", (task,), {"T1": [changes(), passed()]}
    )
    fixture = fixtures["T1"]
    fixture.pre_turn_by_phase["repair"] = [PreTurnInterruption("repair not entered")]
    waiting = run_task_cycle_v4(task, fixture.lifecycle(), kernel, repo, run_dir)
    assert waiting.status == "waiting_external", waiting
    assert kernel.state["repair_roots"] == {}
    assert kernel.state["attempt_budget"]["used"] == 2
    assert kernel.state["tasks"]["T1"]["resume_phase"] == "repair"

    task = contract()
    repo, run_dir, kernel, fixtures = initialize_real_runtime(
        root / "quota-partial", (task,), {"T1": [changes(), passed()]}
    )
    fixture = fixtures["T1"]
    fixture.partial_failure_phase["repair"] = ExternalModelInterruption(
        "quota_transient", "provider:quota:repair"
    )
    waiting = run_task_cycle_v4(task, fixture.lifecycle(), kernel, repo, run_dir)
    assert waiting.status == "waiting_external", waiting
    rejected = kernel.state["candidate_checkpoints"][-1]["commit"]
    assert git(repo, "rev-parse", "HEAD") == rejected
    assert git(repo, "status", "--porcelain=v1", "--untracked-files=all") == ""
    assert kernel.state["repair_roots"] == {"defect:parser": 1}
    repair_attempt = next(
        item["attempt_id"] for item in kernel.state["attempts"] if item["kind"] == "repair"
    )
    resumed = run_task_cycle_v4(task, fixture.lifecycle(), kernel, repo, run_dir)
    assert resumed.status == "completed", resumed
    assert kernel.state["repair_roots"] == {"defect:parser": 1}
    assert any(
        item["attempt_id"] == repair_attempt and item["status"] == "completed"
        for item in kernel.state["attempts"]
    )

    task = contract()
    repo, run_dir, kernel, fixtures = initialize_real_runtime(
        root / "invalid-method", (task,), {"T1": [passed()]}
    )
    fixture = fixtures["T1"]
    fixture.invalid_method_evidence_phases.add("implementation")
    blocked = run_task_cycle_v4(task, fixture.lifecycle(), kernel, repo, run_dir)
    assert blocked.status == "blocked", blocked
    assert git(repo, "rev-parse", "HEAD") == kernel.state["source_head"]
    assert git(repo, "status", "--porcelain=v1", "--untracked-files=all") == ""

    task = contract()
    repo, run_dir, kernel, fixtures = initialize_real_runtime(
        root / "unsafe-restore", (task,), {"T1": [passed()]}
    )
    fixture = fixtures["T1"]
    fixture.out_of_claim_partial_phases.add("implementation")
    fixture.partial_failure_phase["implementation"] = ExternalModelInterruption(
        "quota_transient", "provider:unsafe-partial"
    )
    blocked = run_task_cycle_v4(task, fixture.lifecycle(), kernel, repo, run_dir)
    assert blocked.status == "blocked", blocked
    assert blocked.reason == "evidence_integrity_failure", blocked
    assert kernel.state["tasks"]["T1"]["status"] == "blocked"
    assert all(
        attempt["status"] != "started" for attempt in kernel.state["attempts"]
    )


def assert_runtime_wait_independent_and_verifier_exception(root: Path) -> None:
    runtime_task = contract("T1")
    independent = contract("T2")
    repo, run_dir, kernel, fixtures = initialize_real_runtime(
        root / "runtime",
        (runtime_task, independent),
        {"T1": [passed()], "T2": [passed()]},
    )
    fixtures["T1"].partial_failure_phase["implementation"] = (
        RuntimeUpgradeInterruption("runtime:adapter", "4.0.1", "fixture-b")
    )
    results = run_tasks_v4(
        (runtime_task, independent),
        {key: value.lifecycle() for key, value in fixtures.items()},
        kernel,
        repo,
        run_dir,
    )
    assert [item.status for item in results] == ["waiting_external", "completed"], results
    assert kernel.state["tasks"]["T1"]["resume_phase"] == "implementation"
    assert kernel.state["tasks"]["T2"]["status"] == "completed"
    checkpoint = kernel.state["checkpoint_head"]
    prior_runtime = dict(kernel.state["runtime"])
    kernel.transition(
        Transition(
            "runtime.upgraded",
            {
                "old_runtime_commit": prior_runtime["runtime_commit"],
                "new_runtime_commit": "f" * 40,
                "reason": "resume Task 1 after runtime repair",
                "compatibility_epoch": prior_runtime["compatibility_epoch"],
                "worktree_clean": True,
                "verified_checkpoint": checkpoint,
            },
        )
    )
    run_id = kernel.state["run_id"]
    resumed = run_tasks_v4(
        (runtime_task, independent),
        {key: value.lifecycle() for key, value in fixtures.items()},
        kernel,
        repo,
        run_dir,
    )
    assert len(resumed) == 1 and resumed[0].task_id == "T1", resumed
    assert resumed[0].status == "completed", resumed
    assert kernel.state["run_id"] == run_id
    assert kernel.state["runtime"]["runtime_commit"] == "f" * 40

    task = contract()
    repo, run_dir, kernel, fixtures = initialize_real_runtime(
        root / "verifier", (task,), {"T1": [passed()]}
    )
    fixtures["T1"].deterministic_exception = RuntimeError("verifier exploded")
    cycle = run_task_cycle_v4(
        task, fixtures["T1"].lifecycle(), kernel, repo, run_dir
    )
    assert cycle.status == "blocked", cycle
    assert cycle.reason == "evidence_integrity_failure", cycle
    assert kernel.state["tasks"]["T1"]["status"] == "blocked"
    assert kernel.state["tasks"]["T1"]["wait_reason"] == "evidence_integrity_failure"
    candidate = kernel.state["candidate_checkpoints"][-1]["commit"]
    assert git(repo, "rev-parse", "HEAD") == candidate
    assert git(repo, "status", "--porcelain=v1", "--untracked-files=all") == ""


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="cpe-scheduler-v4-") as raw:
        root = Path(raw)
        checks = {
            "legacy-first-pass": lambda: assert_first_pass(root / "first-pass"),
            "legacy-repairs": lambda: assert_repairs(root / "repairs"),
            "legacy-scope": lambda: assert_scope_policy(root / "scope"),
            "legacy-budget": lambda: assert_resume_and_budget(root / "resume"),
            "legacy-upgrade": lambda: assert_runtime_upgrade_resume(root / "upgrade"),
            "legacy-task-local": lambda: assert_task_local_external_wait(root / "task-local-wait"),
            "A-real-status": lambda: assert_real_kernel_first_pass(root / "real-kernel"),
            "A-exact-phase-resume": lambda: assert_real_kernel_exact_phase_resume(root / "exact-resume"),
            "B-review-binding-all-findings": lambda: assert_review_binding_and_all_findings(root / "review-binding"),
            "C-repair-timing-rollback": lambda: assert_repair_timing_and_rollback(root / "repair-rollback"),
            "D-verifier-runtime-boundary": lambda: assert_runtime_wait_independent_and_verifier_exception(root / "verifier-runtime"),
        }
        failures: dict[str, str] = {}
        for name, check in checks.items():
            try:
                check()
            except BaseException as exc:
                failures[name] = f"{type(exc).__name__}:{exc}"
        assert not failures, json.dumps(failures, sort_keys=True)
    print(json.dumps({"passed": True}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
