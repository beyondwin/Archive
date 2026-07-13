#!/usr/bin/env python3
"""Focused contract checks for the vNext transition kernel boundary."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from cpe_runtime.evidence_store import EvidenceStore  # noqa: E402
from cpe_runtime.events import read_events  # noqa: E402
from cpe_runtime.kernel import RunKernel, Transition, transition_run  # noqa: E402
from cpe_runtime.manifest import create_manifest  # noqa: E402
from cpe_runtime.packets import build_packet  # noqa: E402
from cpe_runtime.phase_executor import PhaseExecutor  # noqa: E402
from cpe_runtime.projector import project_kernel_event  # noqa: E402
from cpe_runtime.scheduler import (  # noqa: E402
    execute_transition,
    next_phase,
    promote_current_plan_checkpoint,
    route_verdict,
)
from cpe_runtime.transition_kernel import (  # noqa: E402
    IllegalTransition,
    KernelCommand,
    RunState,
    TypedOutcome,
    decide,
)


def _rejects(expected: str, operation) -> bool:
    try:
        operation()
    except (IllegalTransition, ValueError) as exc:
        return str(exc) == expected
    return False


def _state(phase: str, **values: object) -> RunState:
    return RunState(phase=phase, task_id="plan-a::T1", **values)


def _outcome(kind: str, **values: object) -> TypedOutcome:
    return TypedOutcome(kind=kind, task_id="plan-a::T1", **values)


def _runtime_fixture(root: Path) -> tuple[Path, RunKernel]:
    plan = root / "plan.md"
    pricing = root / "pricing.json"
    worktree = root / "worktree"
    plan.write_text("# transition plan\n", encoding="utf-8")
    pricing.write_text("{}\n", encoding="utf-8")
    worktree.mkdir()
    task = {
        "id": "T1",
        "title": "transition",
        "dependencies": [],
        "file_claims": ["owned.txt"],
        "acceptance_command": "true",
    }
    manifest = create_manifest(
        "transition-fixture", "interactive", root, worktree, plan, None, [task], pricing
    )
    packet = build_packet(SimpleNamespace(sources=(), spec_manifest=None), task)
    run_dir = root / "run"
    return run_dir, RunKernel.initialize(run_dir, manifest, [packet])


def main() -> int:
    checks: dict[str, bool] = {}

    legal = {
        ("ready", "start"): "implementation",
        ("implemented", "pass"): "acceptance",
        ("accepted", "pass"): "review",
        ("reviewed", "pass"): "verify",
        ("verified", "pass"): "plan_checkpoint",
        ("plan_complete", "pass"): "global_integration",
        ("integration_complete", "pass"): "complete_program",
        ("repairing", "pass"): "review",
        ("ready", "structural_redesign"): "structural_redesign",
        ("reviewed", "changes_requested"): "repair",
        ("verified", "fail"): "repair",
        ("ready", "blocked"): "block",
        ("ready", "wait_user"): "wait_user",
        ("ready", "wait_external"): "wait_external",
        ("waiting_user", "resume"): "implementation",
        ("waiting_external", "resume"): "implementation",
    }
    checks["every_declared_legal_transition"] = all(
        decide(_state(phase), _outcome(outcome)).kind == command
        for (phase, outcome), command in legal.items()
    )
    checks["illegal_transition_fails_closed"] = _rejects(
        "illegal_transition:ready:complete_program",
        lambda: decide(_state("ready"), _outcome("complete_program")),
    )
    checks["resume_phase_is_explicit"] = (
        decide(
            _state("waiting_external", resume_command="verify"),
            _outcome("resume"),
        ).kind
        == "verify"
    ) and _rejects(
        "resume_command_invalid",
        lambda: decide(
            _state("waiting_user", resume_command="complete_program"),
            _outcome("resume"),
        ),
    )
    command = decide(_state("ready"), _outcome("start"))
    checks["command_binds_qualified_task"] = command == KernelCommand(
        "implementation", "plan-a::T1"
    )
    try:
        command.kind = "repair"  # type: ignore[misc]
    except FrozenInstanceError:
        checks["commands_are_immutable"] = True
    else:
        checks["commands_are_immutable"] = False

    calls: list[str] = []

    def handler(item: KernelCommand) -> TypedOutcome:
        calls.append(item.kind)
        return TypedOutcome("pass", item.task_id, ({"sha256": "a" * 64},))

    executor = PhaseExecutor({"implementation": handler})
    executed = executor.execute(command)
    checks["executor_runs_exactly_one_handler"] = calls == ["implementation"]
    checks["executor_returns_typed_immutable_evidence"] = (
        executed.kind == "pass"
        and isinstance(executed.evidence_refs, tuple)
        and executed.evidence_refs[0]["sha256"] == "a" * 64
    )
    checks["executor_rejects_unbound_or_mismatched_outcome"] = _rejects(
        "phase_handler_outcome_task_mismatch",
        lambda: PhaseExecutor(
            {"implementation": lambda _item: TypedOutcome("pass", "plan-b::T2")}
        ).execute(command),
    )

    with tempfile.TemporaryDirectory(prefix="cpe-vnext-evidence-") as temp:
        run_dir = Path(temp)
        store = EvidenceStore(run_dir)
        raw = b"exact evidence bytes\n"
        crash_log: list[str] = []
        ref = store.put_bytes(
            "acceptance",
            raw,
            media_type="text/plain",
            crash_hook=crash_log.append,
        )
        checks["evidence_is_content_addressed"] = (
            ref.sha256 == hashlib.sha256(raw).hexdigest()
            and Path(ref.path).name == f"{ref.sha256}.bin"
        )
        checks["evidence_bytes_reopen_and_verify"] = store.read_verified(ref) == raw
        checks["evidence_persistence_crash_points"] = crash_log == [
            "before_evidence_persistence",
            "after_evidence_persistence",
        ]
        path = run_dir / ref.path
        path.write_bytes(b"tampered")
        checks["tampered_evidence_fails_closed"] = _rejects(
            "evidence_digest_mismatch", lambda: store.read_verified(ref)
        )
        patch_ref = store.put_patch(b"diff --git a/a b/a\n")
        checks["stable_patch_wire_path_is_verified_by_store"] = (
            patch_ref.path.startswith("artifacts/patches/")
            and store.read_verified(patch_ref) == b"diff --git a/a b/a\n"
        )

    projection = {
        "phase": "ready",
        "task_id": "plan-a::T1",
        "plan_checkpoints": [],
        "external_calls": [],
        "completed": False,
    }
    projected = project_kernel_event(
        projection,
        {
            "command": "plan_checkpoint",
            "task_id": "plan-a::T1",
            "outcome": "pass",
            "evidence_refs": [{"sha256": "b" * 64}],
            "checkpoint_identity": "c" * 64,
        },
    )
    checks["projector_replaces_without_mutating_input"] = (
        not projection["plan_checkpoints"]
        and projected["plan_checkpoints"] == ["c" * 64]
        and projected["phase"] == "plan_complete"
    )
    checks["global_completion_requires_all_checkpoints_and_gate"] = _rejects(
        "global_completion_prerequisites_missing",
        lambda: project_kernel_event(
            projection,
            {
                "command": "complete_program",
                "task_id": None,
                "outcome": "pass",
                "required_plan_checkpoints": ["c" * 64],
                "integration_gate_passed": False,
            },
        ),
    )
    globally_ready = {
        **projected,
        "phase": "integration_complete",
        "integration_gate_passed": True,
    }
    completed = project_kernel_event(
        globally_ready,
        {
            "command": "complete_program",
            "task_id": None,
            "outcome": "pass",
            "required_plan_checkpoints": ["c" * 64],
            "integration_gate_passed": True,
        },
    )
    checks["global_completion_projects_once"] = completed["completed"] is True
    checks["duplicate_global_completion_fails_closed"] = _rejects(
        "global_completion_already_recorded",
        lambda: project_kernel_event(
            completed,
            {
                "command": "complete_program",
                "task_id": None,
                "outcome": "pass",
                "required_plan_checkpoints": ["c" * 64],
                "integration_gate_passed": True,
            },
        ),
    )
    registered = project_kernel_event(
        projection,
        {
            "command": "register_external_call",
            "task_id": "plan-a::T1",
            "outcome": "registered",
            "external_call_id": "call-1",
        },
    )
    checks["external_registration_is_idempotent"] = _rejects(
        "external_call_already_registered",
        lambda: project_kernel_event(
            registered,
            {
                "command": "register_external_call",
                "task_id": "plan-a::T1",
                "outcome": "registered",
                "external_call_id": "call-1",
            },
        ),
    )

    projection_crash_cases = {
        "plan_checkpoint": (
            projection,
            {
                "command": "plan_checkpoint",
                "task_id": "plan-a::T1",
                "outcome": "pass",
                "checkpoint_identity": "f" * 64,
            },
            {
                "before_projection_replacement",
                "before_plan_checkpoint_publication",
                "after_plan_checkpoint_publication",
                "after_projection_replacement",
            },
        ),
        "external_call": (
            projection,
            {
                "command": "register_external_call",
                "task_id": "plan-a::T1",
                "outcome": "registered",
                "external_call_id": "call-crash",
            },
            {
                "before_projection_replacement",
                "before_external_call_registration",
                "after_external_call_registration",
                "after_projection_replacement",
            },
        ),
        "global_completion": (
            globally_ready,
            {
                "command": "complete_program",
                "task_id": None,
                "outcome": "pass",
                "required_plan_checkpoints": ["c" * 64],
                "integration_gate_passed": True,
            },
            {
                "before_projection_replacement",
                "before_global_completion",
                "after_global_completion",
                "after_projection_replacement",
            },
        ),
    }
    generated_points_ok = True
    for source, event, expected_points in projection_crash_cases.values():
        observed: list[str] = []
        project_kernel_event(source, event, crash_hook=observed.append)
        generated_points_ok &= set(observed) == expected_points
        for point in expected_points:
            before = json.dumps(source, sort_keys=True)

            def crash(current: str, target: str = point) -> None:
                if current == target:
                    raise RuntimeError(target)

            try:
                project_kernel_event(source, event, crash_hook=crash)
            except RuntimeError as exc:
                generated_points_ok &= str(exc) == point
            else:
                generated_points_ok = False
            generated_points_ok &= json.dumps(source, sort_keys=True) == before
    checks["generated_checkpoint_external_global_crash_points"] = generated_points_ok

    durable_crash_points_ok = True
    for point in (
        "before_event_append",
        "after_event_append",
        "before_projection_replacement",
        "after_projection_replacement",
    ):
        with tempfile.TemporaryDirectory(prefix="cpe-vnext-kernel-crash-") as temp:
            run_dir, _kernel = _runtime_fixture(Path(temp))

            def crash(current: str, target: str = point) -> None:
                if current == target:
                    raise RuntimeError(target)

            try:
                transition_run(
                    run_dir,
                    Transition("run.status_changed", {"from": "ready", "to": "running"}),
                    crash_hook=crash,
                )
            except RuntimeError as exc:
                durable_crash_points_ok &= str(exc) == point
            else:
                durable_crash_points_ok = False
            events = read_events(run_dir / "events.jsonl")
            expected_count = 1 if point == "before_event_append" else 2
            durable_crash_points_ok &= len(events) == expected_count
            durable_crash_points_ok &= RunKernel(run_dir).state["lifecycle"] == (
                "ready" if point == "before_event_append" else "running"
            )
    checks["generated_event_projection_crash_points"] = durable_crash_points_ok

    checks["scheduler_uses_transition_kernel_routes"] = (
        next_phase({"tasks": {"T1": {"status": "reviewing"}}}, "T1") == "acceptance"
        and route_verdict({"status": "passed"}) == "continue"
        and route_verdict({"status": "changes_requested"}) == "repair"
    )
    scheduled_calls: list[str] = []
    scheduled_command, scheduled_outcome = execute_transition(
        _state("ready"),
        _outcome("start"),
        {
            "implementation": lambda item: (
                scheduled_calls.append(item.kind)
                or TypedOutcome("pass", item.task_id)
            )
        },
    )
    checks["scheduler_executes_one_kernel_command"] = (
        scheduled_command.kind == "implementation"
        and scheduled_outcome.kind == "pass"
        and scheduled_calls == ["implementation"]
    )

    authoritative = {
        "plan_checkpoints": [
            {"plan_id": "first", "identity": "d" * 64},
        ]
    }
    candidate = type(
        "Checkpoint",
        (),
        {
            "plan_id": "second",
            "plan_sha256": "1" * 64,
            "spec_sha256": "2" * 64,
            "upstream_checkpoint": "d" * 64,
            "upstream_graph_sha256": "3" * 64,
        },
    )()
    accepted: list[str | None] = []
    result = promote_current_plan_checkpoint(
        candidate,
        state=authoritative,
        plan_id="second",
        plan_sha256="1" * 64,
        spec_sha256="2" * 64,
        upstream_graph_sha256="3" * 64,
        promote=lambda item, **kw: accepted.append(kw["upstream_checkpoint"]) or item,
    )
    checks["checkpoint_promotion_uses_authoritative_state"] = (
        result is candidate and accepted == ["d" * 64]
    )
    stale_state = {
        "plan_checkpoints": [{"plan_id": "first", "identity": "e" * 64}]
    }
    checks["stale_checkpoint_cannot_self_validate"] = _rejects(
        "plan_checkpoint_upstream_stale",
        lambda: promote_current_plan_checkpoint(
            candidate,
            state=stale_state,
            plan_id="second",
            plan_sha256="1" * 64,
            spec_sha256="2" * 64,
            upstream_graph_sha256="3" * 64,
            promote=lambda item, **_kw: item,
        ),
    )

    failed = [name for name, passed in checks.items() if not passed]
    print(json.dumps({"passed": not failed, "checks": checks, "failed": failed}, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
