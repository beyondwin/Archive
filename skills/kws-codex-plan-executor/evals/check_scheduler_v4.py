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
            "backlog": [],
            "repair_roots": {},
            "tasks": {task_id: {"status": "ready"} for task_id in task_ids},
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
        elif event_type == "attempt.completed":
            attempt = next(
                item for item in self._state["attempts"]
                if item["attempt_id"] == command.attempt_id
            )
            attempt.update(command.payload)
        elif event_type == "candidate.checkpoint_recorded":
            self._state["candidate_checkpoints"].append(record)
        elif event_type == "task.checkpoint_verified":
            self._state["verified_checkpoints"].append(record)
            self._state["checkpoint_head"] = command.payload["commit"]
            self._state["tasks"][str(command.task_id)]["status"] = "completed"
        elif event_type == "verdict.recorded":
            self._state["verdicts"].append(record)
        elif event_type == "decision.recorded":
            self._state["decisions"].append(command.payload)
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


def contract(task_id: str = "T1", *, dependencies: tuple[str, ...] = ()) -> TaskContractV4:
    return compile_task_contract(
        {
            "id": task_id,
            "title": f"bounded lifecycle {task_id}",
            "task_type": "tdd_implementation",
            "dependencies": list(dependencies),
            "task_source": f"### Task {task_id}\nBound the lifecycle.\n",
            "file_claims": ["product.py"],
            "acceptance_commands": [TEST_COMMAND],
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

    def before_model_turn(self, _phase: str, _attempt_id: str) -> None:
        if self.pre_turn_failures:
            raise self.pre_turn_failures.pop(0)

    def implementation(self, task: TaskContractV4, _attempt_id: str) -> WorkerResult:
        if self.implementation_failures:
            raise self.implementation_failures.pop(0)
        self.serial += 1
        (self.repo / "product.py").write_text(
            f"VALUE = {self.serial!r}\nTASK = {task.task_id!r}\n", encoding="utf-8"
        )
        return result(
            method_evidence_ref=method_ref(
                self.run_dir, task, self.packet_sha256, self.serial
            )
        )

    def repair(self, task: TaskContractV4, _finding: dict, _attempt_id: str) -> WorkerResult:
        self.repair_calls += 1
        self.serial += 1
        (self.repo / "product.py").write_text(
            f"VALUE = {self.serial!r}\nTASK = {task.task_id!r}\n", encoding="utf-8"
        )
        return result(
            method_evidence_ref=method_ref(
                self.run_dir, task, self.packet_sha256, self.serial
            )
        )

    def review(self, _task: TaskContractV4, scope: ReviewScope, _attempt_id: str) -> WorkerResult:
        self.review_scopes.append(scope)
        verdict = self.reviews.pop(0)
        return result(verdict=verdict)

    def deterministic_verification(self, *_args) -> tuple[bool, str]:
        return True, "fixture deterministic verification passed"

    def semantic_verification(self, *_args) -> WorkerResult:
        self.semantic_calls += 1
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
    cycle = run_task_cycle_v4(task, fixture.lifecycle(), kernel, repo, run_dir)
    assert cycle.status == "completed", cycle
    assert kernel.state["attempt_budget"] == {"limit": 40, "used": 2}
    assert len(kernel.state["verified_checkpoints"]) == 1
    assert len(kernel.state["verdicts"]) == 1
    assert any(item["kind"] == "method_evidence" for item in kernel.state["artifact_index"])


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="cpe-scheduler-v4-") as raw:
        root = Path(raw)
        assert_first_pass(root / "first-pass")
        assert_repairs(root / "repairs")
        assert_scope_policy(root / "scope")
        assert_resume_and_budget(root / "resume")
        assert_runtime_upgrade_resume(root / "upgrade")
        assert_task_local_external_wait(root / "task-local-wait")
        assert_real_kernel_first_pass(root / "real-kernel")
    print(json.dumps({"passed": True}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
