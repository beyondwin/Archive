from __future__ import annotations

import hashlib
import json
import shlex
import sys
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal, Mapping

from .attempt_controller import (
    ROLE_POLICIES,
    AttemptController,
    ModelAttemptController,
    WriteAttemptOutcome,
    canonical_role,
    validate_verdict,
)
from .evidence import EvidenceRef
from .evidence_store import EvidenceStore
from .events import read_events
from .git_delta import INVALID_GIT_HEAD, GitDelta, capture_snapshot, diff_snapshots, matches_path
from .kernel import Kernel, Transition
from .manifest import load_verified_manifest, resolve_ref
from .model_policy import CORE_ROUTE
from .operator_decisions import approved_cleanup_claims, approved_scope_claims
from .packets import packet_entry, verify_packet
from .phase_executor import PhaseExecutor, PhaseHandler
from .projector import project_kernel_event
from .validation import COMPLETION_EVIDENCE_KINDS, validate_completion, validate_integrity
from .worker import Worker, WorkerError, WorkerRequest, WorkerResult
from .transition_kernel import RunState, TypedOutcome, decide


TaskPhase = Literal[
    "preflight",
    "implementation",
    "candidate",
    "acceptance",
    "task_review",
    "verification",
    "verified_checkpoint",
    "repair",
    "waiting_external",
    "waiting_user",
    "blocked",
]


@dataclass(frozen=True)
class ReviewScope:
    kind: Literal["task_diff", "repair_delta"]
    base_commit: str
    candidate_commit: str
    previous_findings: tuple[dict[str, object], ...] = ()
    reopen_full_task_diff: bool = False
    boundary_changes: tuple[str, ...] = ()


@dataclass(frozen=True)
class LifecycleOperations:
    packet_sha256: str
    before_model_turn: Callable[[str, str], None]
    implementation: Callable[[object, str], WorkerResult]
    repair: Callable[[object, dict[str, object], str], WorkerResult]
    review: Callable[[object, ReviewScope, str], WorkerResult]
    deterministic_verification: Callable[..., tuple[bool, str]]
    semantic_verification: Callable[..., WorkerResult] | None
    repair_boundary_changes: Callable[..., tuple[str, ...]]
    acceptance_environment: Mapping[str, str]


class PreTurnInterruption(RuntimeError):
    """External interruption observed before a provider turn exists."""


class ExternalModelInterruption(RuntimeError):
    def __init__(self, category: str, root_cause_key: str):
        super().__init__(category)
        self.category = category
        self.root_cause_key = root_cause_key


class RuntimeUpgradeInterruption(RuntimeError):
    def __init__(self, root_cause_key: str, target_version: str, target_build_id: str):
        super().__init__("runtime_upgrade_required")
        self.root_cause_key = root_cause_key
        self.target_version = target_version
        self.target_build_id = target_build_id


@dataclass(frozen=True)
class TaskCycleResult:
    task_id: str
    status: str
    phase: str
    worktree_revision: int
    reason: str | None = None
    phases: tuple[TaskPhase, ...] = ()
    model_attempts: int = 0
    state: dict[str, object] = field(default_factory=dict)
    review_scopes: tuple[ReviewScope, ...] = ()


@dataclass(frozen=True)
class ReadOnlyGuardResult:
    value: object | None
    delta: GitDelta | None
    error: Exception | None
    mutation_root: str | None


def next_phase(state: dict, task_id: str) -> str:
    tasks = state.get("tasks")
    if not isinstance(tasks, dict) or task_id not in tasks:
        raise ValueError("unknown task")
    retry_queue = state.get("retry_queue") or []
    for retry in reversed(retry_queue):
        if isinstance(retry, dict) and retry.get("task_id") == task_id:
            phase = retry.get("phase")
            if phase not in {
                "implementation", "repair", "acceptance", "task_review", "verification"
            }:
                raise ValueError(f"unknown retry phase: {phase}")
            return str(phase)
    status = tasks[task_id].get("status")
    kernel_phases = {
        "pending": "ready",
        "ready": "ready",
        "scouting": "ready",
        "implementing": "ready",
        "reviewing": "implemented",
        "verifying": "reviewed",
        "repairing": "repairing",
        "completed": "completed",
    }
    if status not in kernel_phases:
        raise ValueError(f"unknown or non-runnable task state: {status}")
    command = decide(
        RunState(kernel_phases[str(status)], task_id),
        TypedOutcome("dispatch", task_id),
    )
    return "verification" if command.kind == "verify" else command.kind


def route_verdict(verdict: object) -> str:
    status = verdict.get("status") if isinstance(verdict, dict) else verdict
    if status not in {"passed", "changes_requested", "blocked", "inconclusive"}:
        raise ValueError(f"unknown verdict: {status}")
    command = decide(RunState("verdict"), TypedOutcome(str(status)))
    return {"block": "blocked", "wait": "inconclusive"}.get(
        command.kind, command.kind
    )


def execute_transition(
    state: RunState,
    outcome: TypedOutcome,
    handlers: Mapping[str, PhaseHandler],
):
    """Choose and execute one vNext command; durable recording stays in Kernel."""

    command = decide(state, outcome)
    return command, PhaseExecutor(handlers).execute(command)


_PRODUCTION_PHASE_COMMANDS = frozenset(
    {"implementation", "acceptance", "review", "repair", "verify"}
)


def _next_scheduler_phase(
    phase: str,
    outcome: str,
    task_id: str,
) -> str:
    """Translate one kernel decision to the retained scheduler loop label."""

    command = decide(RunState(phase, task_id), TypedOutcome(outcome, task_id))
    labels = {
        "implementation": "implementation",
        "acceptance": "acceptance",
        "review": "task_review",
        "repair": "repair",
        "verify": "verification",
    }
    if command.kind not in labels:
        raise ValueError(f"task_phase_not_executable:{command.kind}")
    return labels[command.kind]


def _execute_phase_operation(
    state: RunState,
    trigger: TypedOutcome,
    operation: Callable[[], object],
    *,
    outcome_kind: Callable[[object], str] | None = None,
) -> tuple[object, dict]:
    """Execute one active scheduler operation through all vNext boundaries."""

    def handler(command):
        value = operation()
        kind = outcome_kind(value) if outcome_kind is not None else "pass"
        return TypedOutcome(kind, command.task_id, details={"value": value})

    command, executed = execute_transition(
        state,
        trigger,
        {kind: handler for kind in _PRODUCTION_PHASE_COMMANDS},
    )
    if command.kind not in _PRODUCTION_PHASE_COMMANDS:
        raise ValueError(f"production_phase_command_invalid:{command.kind}")
    projected = project_kernel_event(
        {"phase": state.phase, "task_id": state.task_id},
        {
            "command": command.kind,
            "task_id": command.task_id,
            "outcome": executed.kind,
            "evidence_refs": [dict(ref) for ref in executed.evidence_refs],
        },
    )
    return executed.details["value"], projected


def promote_current_plan_checkpoint(
    checkpoint: object,
    *,
    kernel: object,
    plan_id: str,
    plan_sha256: str,
    spec_sha256: str,
    upstream_graph_sha256: str,
    promote=None,
):
    """Promote against the authoritative projected checkpoint chain.

    Never trust the candidate's own upstream string as the current identity.
    """

    state = getattr(kernel, "state", None)
    if not isinstance(state, dict):
        raise ValueError("plan_checkpoint_state_invalid")
    checkpoints = state.get("plan_checkpoints")
    if not isinstance(checkpoints, list):
        raise ValueError("plan_checkpoint_state_invalid")
    if any(
        not isinstance(item, dict)
        or not isinstance(item.get("plan_id"), str)
        or not isinstance(item.get("identity"), str)
        for item in checkpoints
    ):
        raise ValueError("plan_checkpoint_state_invalid")
    upstream = checkpoints[-1]["identity"] if checkpoints else None
    if getattr(checkpoint, "upstream_checkpoint", None) != upstream:
        raise ValueError("plan_checkpoint_upstream_stale")
    if promote is None:
        from .checkpoints import promote_plan_checkpoint

        promote = promote_plan_checkpoint
    return promote(
        checkpoint,
        plan_id=plan_id,
        plan_sha256=plan_sha256,
        spec_sha256=spec_sha256,
        upstream_checkpoint=upstream,
        upstream_graph_sha256=upstream_graph_sha256,
    )


def _put_json(run_dir: Path, kind: str, payload: object) -> EvidenceRef:
    return EvidenceStore(run_dir).put_json(kind, payload)


def make_packet_request(
    run_dir: Path,
    manifest: dict,
    task_id: str,
    attempt_id: str,
    attempt_kind: str,
    instruction: str,
    worktree: Path,
) -> WorkerRequest:
    verify_packet(run_dir, manifest, task_id)
    entry = packet_entry(manifest, task_id)
    state = Kernel(run_dir).state
    role = canonical_role(attempt_kind)
    policy = ROLE_POLICIES.get(role)
    if policy is None:
        raise ValueError(f"unknown worker role: {role}")
    request = WorkerRequest(
        attempt_id=attempt_id,
        attempt_kind=role,
        prompt="",
        worktree=worktree,
        read_only=policy.read_only,
        verdict_capable=policy.verdict_capable,
        task_id=task_id,
        packet_path=str((run_dir / entry["path"]).resolve()),
        packet_sha256=entry["sha256"],
        worktree_revision=int(state["worktree_revision"]),
    )
    prior_task_evidence = _prior_task_evidence(run_dir, state, task_id)
    return WorkerRequest(
        **{
            **request.__dict__,
            "prompt": packet_prompt(
                request,
                instruction,
                run_dir=run_dir,
                prior_task_evidence=prior_task_evidence,
            ),
        }
    )


def _prior_task_evidence(run_dir: Path, state: dict, task_id: str) -> list[dict[str, object]]:
    root = run_dir.expanduser().resolve()
    evidence: list[dict[str, object]] = []
    for attempt in state.get("attempts", []):
        if not isinstance(attempt, dict) or attempt.get("task_id") != task_id:
            continue
        refs: list[dict[str, str]] = []
        for ref in attempt.get("evidence_refs") or []:
            if not isinstance(ref, dict) or not isinstance(ref.get("path"), str):
                continue
            path = (root / str(ref["path"])).resolve()
            try:
                path.relative_to(root)
            except ValueError:
                continue
            refs.append(
                {
                    "kind": str(ref.get("kind") or ""),
                    "path": str(path),
                    "sha256": str(ref.get("sha256") or ""),
                }
            )
        if refs:
            evidence.append(
                {
                    "attempt_id": str(attempt.get("attempt_id") or ""),
                    "kind": str(attempt.get("kind") or ""),
                    "status": str(attempt.get("status") or ""),
                    "worktree_revision": attempt.get("worktree_revision"),
                    "evidence_refs": refs,
                }
            )
    return evidence


def packet_prompt(
    request: WorkerRequest,
    instruction: str,
    *,
    run_dir: Path,
    prior_task_evidence: list[dict[str, object]],
) -> str:
    payload: dict[str, object] = {
        "task_id": request.task_id,
        "packet_path": request.packet_path,
        "packet_sha256": request.packet_sha256,
        "worktree_revision": request.worktree_revision,
        "instruction": instruction,
        "result_contract": {
            "verdict_must_be_null": not request.verdict_capable,
            "top_level_findings_must_equal_verdict_findings": request.verdict_capable,
            "top_level_missing_evidence_must_equal_verdict_missing_evidence": request.verdict_capable,
            "guidance": (
                "For verdict-capable roles, copy verdict.findings and "
                "verdict.missing_evidence exactly into the matching top-level arrays."
                if request.verdict_capable
                else "This role cannot issue a verdict; return verdict=null."
            ),
        },
    }
    validator = Path(__file__).resolve().parents[1] / "validate_state.py"
    payload["canonical_runtime_validation"] = {
        "authority": "current_host_cpe_runtime",
        "command": shlex.join([sys.executable, str(validator), str(run_dir.resolve())]),
        "guidance": (
            "Use this current host-runtime command for canonical run validation. "
            "Do not substitute a validator copied into the execution worktree."
        ),
    }
    payload["prior_task_evidence"] = prior_task_evidence
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def run_scouts(requests: list[WorkerRequest], worker: Worker) -> list[WorkerResult]:
    if not requests:
        return []
    for request in requests:
        if not request.read_only or request.verdict_capable or request.attempt_kind != "scout":
            raise ValueError("unsafe scout request")

    def run_one(request: WorkerRequest) -> WorkerResult:
        return _guarded_worker(request, worker)

    with ThreadPoolExecutor(
        max_workers=min(4, len(requests)), thread_name_prefix="cpe-scout"
    ) as pool:
        return list(pool.map(run_one, requests))


def _topological(tasks: list[dict]) -> list[dict]:
    by_id = {str(task["id"]): task for task in tasks}
    if len(by_id) != len(tasks):
        raise ValueError("task graph requires unique task ids")
    ordered: list[dict] = []
    ready = [task_id for task_id, task in by_id.items() if not task.get("dependencies")]
    seen: set[str] = set()
    while ready:
        task_id = ready.pop(0)
        if task_id in seen:
            continue
        seen.add(task_id)
        ordered.append(by_id[task_id])
        for candidate_id, candidate in by_id.items():
            dependencies = [str(item) for item in candidate.get("dependencies") or []]
            if candidate_id not in seen and set(dependencies).issubset(seen):
                ready.append(candidate_id)
    if len(ordered) != len(tasks):
        raise ValueError("task dependency cycle or unknown dependency")
    return ordered


def _trusted(result: WorkerResult) -> bool:
    return (
        result.attestation.get("verified") is True
        and result.attestation.get("actual_model") == CORE_ROUTE.model
        and result.attestation.get("actual_reasoning") == CORE_ROUTE.reasoning
    )


def _worker_error_result(
    error: Exception,
    category: str,
    *,
    root_cause_key: str | None = None,
    changed_files: tuple[str, ...] = (),
) -> WorkerResult:
    message = f"{type(error).__name__}: {error}"[:2000]
    payload = {
        "status": "failed",
        "summary": message,
        "changed_files": list(changed_files),
        "findings": [],
        "evidence_refs": [],
        "missing_evidence": [message],
        "verification": [],
        "verdict": None,
        "failure_category": category,
        "root_cause_key": root_cause_key or f"{category}:{type(error).__name__}",
    }
    return WorkerResult(
        "failed",
        payload,
        {"verified": False, "error": message},
        {},
        0,
        hashlib.sha256(message.encode()).hexdigest(),
        message,
    )


def _guard_read_only(worktree: Path, operation) -> ReadOnlyGuardResult:
    try:
        before = capture_snapshot(worktree, tolerate_invalid_git=True)
    except Exception as exc:
        return ReadOnlyGuardResult(None, None, exc, "read_only_guard:baseline")
    if not before._filesystem_valid:
        return ReadOnlyGuardResult(
            None, None, RuntimeError("read-only baseline is unreadable"),
            "read_only_guard:baseline",
        )
    value: object | None = None
    error: Exception | None = None
    try:
        value = operation()
    except Exception as exc:
        error = exc
    try:
        after = capture_snapshot(worktree, tolerate_invalid_git=True)
        delta = diff_snapshots(before, after, worktree)
    except Exception as exc:
        return ReadOnlyGuardResult(value, None, error or exc, "read_only_mutation:unreadable")
    invalid = (
        not after._filesystem_valid
        or before._git_metadata_valid != after._git_metadata_valid
        or (before.head == INVALID_GIT_HEAD) != (after.head == INVALID_GIT_HEAD)
    )
    mutated = bool(delta.changed_files or delta.head_changed or invalid)
    if mutated:
        path = delta.changed_files[0] if delta.changed_files else "git_metadata"
        return ReadOnlyGuardResult(value, delta, error, f"read_only_mutation:{path}")
    return ReadOnlyGuardResult(value, delta, error, None)


def _guarded_worker(request: WorkerRequest, worker: object) -> WorkerResult:
    guarded = _guard_read_only(request.worktree, lambda: worker.run(request))
    if guarded.mutation_root is not None:
        changed = guarded.delta.changed_files if guarded.delta is not None else ()
        return _worker_error_result(
            RuntimeError("read-only phase mutated the execution worktree"),
            "read_only_mutation",
            root_cause_key=guarded.mutation_root,
            changed_files=changed,
        )
    if guarded.error is not None:
        category = "transient" if isinstance(guarded.error, WorkerError) else "unexpected_worker_error"
        return _worker_error_result(guarded.error, category)
    if not isinstance(guarded.value, WorkerResult):
        return _worker_error_result(
            TypeError("read-only worker returned an invalid result"),
            "unexpected_worker_error",
        )
    return guarded.value


def _guarded_shell(command: str, worktree: Path, timeout: int) -> dict[str, object]:
    guarded = _guard_read_only(
        worktree,
        lambda: subprocess.run(
            ["/bin/sh", "-lc", command],
            cwd=worktree,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        ),
    )
    if guarded.mutation_root is not None:
        changed = list(guarded.delta.changed_files) if guarded.delta is not None else []
        return {
            "command": command,
            "returncode": 125,
            "output": "read-only command mutated the execution worktree",
            "failure_category": "read_only_mutation",
            "root_cause_key": guarded.mutation_root,
            "actual_changed_files": changed,
        }
    if guarded.error is not None:
        return {
            "command": command,
            "returncode": 124,
            "output": str(guarded.error),
            "failure_category": "read_only_guard_failure",
            "root_cause_key": f"read_only_guard:{type(guarded.error).__name__}",
            "actual_changed_files": [],
        }
    completed = guarded.value
    if not isinstance(completed, subprocess.CompletedProcess):
        return {
            "command": command,
            "returncode": 124,
            "output": "read-only command produced no result",
            "failure_category": "read_only_guard_failure",
            "root_cause_key": "read_only_guard:invalid_result",
            "actual_changed_files": [],
        }
    return {
        "command": command,
        "returncode": completed.returncode,
        "output": str(completed.stdout)[-8000:],
    }


def _next_ordinal(kernel: Kernel, task_id: str | None, kind: str) -> int:
    return 1 + sum(
        1
        for attempt in kernel.state.get("attempts", [])
        if attempt.get("task_id") == task_id and attempt.get("kind") == canonical_role(kind)
    )


def _binding(kernel: Kernel, packet_task_id: str) -> dict[str, object]:
    manifest = load_verified_manifest(kernel.run_dir / "run_manifest.json")
    entry = packet_entry(manifest, packet_task_id)
    state = kernel.state
    return {
        "packet_task_id": packet_task_id,
        "packet_sha256": entry["sha256"],
        "worktree_revision": state["worktree_revision"],
        "worktree_patch_sha256": state["worktree_patch_sha256"],
    }


def _attach(
    kernel: Kernel,
    task_id: str | None,
    attempt_id: str | None,
    kind: str,
    payload: object,
) -> dict[str, str]:
    ref = _put_json(kernel.run_dir, kind, payload)
    kernel.transition(
        Transition(
            "evidence.attached",
            {"kind": kind, "ref": ref.as_dict()},
            task_id=task_id,
            attempt_id=attempt_id,
        )
    )
    return ref.as_dict()


def _start_attempt(kernel: Kernel, task_id: str | None, kind: str, attempt_id: str) -> None:
    kernel.transition(
        Transition(
            "attempt.started",
            {"kind": canonical_role(kind), "worktree_revision": kernel.state["worktree_revision"]},
            task_id=task_id,
            attempt_id=attempt_id,
        )
    )


def _complete_attempt(
    kernel: Kernel,
    task_id: str | None,
    packet_task_id: str,
    kind: str,
    result: WorkerResult,
    attempt_id: str,
) -> None:
    result_ref = _attach(
        kernel,
        task_id,
        attempt_id,
        "worker_result",
        {
            "attempt_id": attempt_id,
            "task_id": task_id,
            "packet_task_id": packet_task_id,
            "result": result.payload,
        },
    )
    completion_status = "completed" if result.status == "completed" else "failed"
    revision = int(kernel.state["worktree_revision"])
    kernel.transition(
        Transition(
            "attempt.completed",
            {
                "status": completion_status,
                "attestation": result.attestation,
                "usage": result.usage,
                "latency_ms": result.latency_ms,
                "evidence_refs": [result_ref],
                "raw_event_digest": result.raw_event_digest,
                "summary": result.payload.get("summary", ""),
                "failure_category": result.payload.get("failure_category"),
                "root_cause_key": result.payload.get("root_cause_key"),
                "changed_files": list(result.payload.get("changed_files") or []),
                "worktree_revision": revision,
            },
            task_id=task_id,
            attempt_id=attempt_id,
        )
    )
    verdict = result.payload.get("verdict")
    if isinstance(verdict, dict):
        normalized = validate_verdict(verdict, kind, revision)
        normalized.update(_binding(kernel, packet_task_id))
        kernel.transition(
            Transition(
                "verdict.recorded",
                normalized,
                task_id=task_id,
                attempt_id=attempt_id,
            )
        )


def _worker_attempt(
    controller: AttemptController,
    kernel: Kernel,
    task: dict | None,
    kind: str,
    prompt: str,
    *,
    packet_task_id: str | None = None,
) -> tuple[WorkerResult, WriteAttemptOutcome[WorkerResult] | None, str]:
    if controller.worker is None or not callable(getattr(controller.worker, "run", None)):
        raise TypeError("attempt controller requires a Worker")
    task_id = str(task["id"]) if task else None
    manifest = load_verified_manifest(kernel.run_dir / "run_manifest.json")
    request_task_id = packet_task_id or task_id
    if request_task_id is None:
        raise ValueError("worker attempt requires a packet task")
    ordinal = _next_ordinal(kernel, task_id, kind)
    attempt_id = f"{task_id or 'run'}.{kind}.{ordinal}"
    _start_attempt(kernel, task_id, kind, attempt_id)

    def invoke() -> WorkerResult:
        try:
            request = make_packet_request(
                kernel.run_dir,
                manifest,
                request_task_id,
                attempt_id,
                kind,
                prompt,
                controller.worktree,
            )
            return controller.worker.run(request)
        except WorkerError as exc:
            return _worker_error_result(exc, "transient")

    write_outcome = None
    policy = ROLE_POLICIES[canonical_role(kind)]
    if policy.product_write:
        contract = (
            task.get("execution_contract")
            if task and isinstance(task.get("execution_contract"), dict)
            else {}
        )
        allowed = list(contract.get("allowed_paths") or (task.get("file_claims") if task else []) or [])
        if task is not None:
            extra = approved_scope_claims(
                kernel.run_dir,
                kernel.state,
                str(task_id),
                int(kernel.state["worktree_revision"]),
            )
            cleanup = approved_cleanup_claims(
                kernel.run_dir,
                kernel.state,
                str(task_id),
                int(kernel.state["worktree_revision"]),
            )
            global_claims = [
                str(path)
                for candidate in manifest.get("task_graph") or []
                if isinstance(candidate, dict)
                for path in candidate.get("file_claims") or []
            ]
            allowed.extend(
                path for path in extra if path in cleanup or matches_path(path, global_claims)
            )
        forbidden = list(contract.get("forbidden_paths") or [])
        try:
            write_outcome = controller.run_write_attempt(
                task_id=str(task_id),
                attempt_id=attempt_id,
                role=kind,
                allowed=[str(path) for path in allowed],
                forbidden=[str(path) for path in forbidden],
                operation=invoke,
            )
        except Exception as exc:
            result = _worker_error_result(exc, "unexpected_worker_error")
        else:
            if write_outcome.error is not None:
                result = _worker_error_result(write_outcome.error, "unexpected_worker_error")
            elif write_outcome.result is None:
                result = _worker_error_result(
                    RuntimeError("write attempt returned no worker result"),
                    "unexpected_worker_error",
                )
            else:
                result = write_outcome.result
    else:
        request = make_packet_request(
            kernel.run_dir,
            manifest,
            request_task_id,
            attempt_id,
            kind,
            prompt,
            controller.worktree,
        )
        result = _guarded_worker(request, controller.worker)
    _complete_attempt(kernel, task_id, request_task_id, kind, result, attempt_id)
    return result, write_outcome, attempt_id


def _semantic_verdict(
    kernel: Kernel,
    task_id: str,
    attempt_id: str,
    kind: str,
    result: WorkerResult,
) -> dict[str, str]:
    verdict = result.payload.get("verdict")
    if not isinstance(verdict, dict):
        verdict = {
            "status": "inconclusive",
            "findings": [],
            "missing_evidence": ["worker verdict missing"],
        }
    payload = {
        "kind": kind,
        "task_id": task_id,
        "attempt_id": attempt_id,
        "status": verdict.get("status"),
        "passed": verdict.get("status") == "passed",
        "findings": list(verdict.get("findings") or []),
        "missing_evidence": list(verdict.get("missing_evidence") or []),
        **_binding(kernel, task_id),
    }
    return _attach(kernel, task_id, attempt_id, kind, payload)


def _acceptance(
    task: dict,
    controller: AttemptController,
    kernel: Kernel,
) -> tuple[bool, dict, dict[str, str]]:
    task_id = str(task["id"])
    ordinal = 1 + sum(
        1
        for item in kernel.state.get("artifact_index", [])
        if item.get("task_id") == task_id and item.get("kind") == "acceptance"
    )
    attempt_id = f"{task_id}.acceptance.{ordinal}"
    command = str(task.get("acceptance_command") or "").strip()
    if not command:
        result_payload = {
            "command": "",
            "returncode": 2,
            "output": "acceptance command missing",
        }
    else:
        result_payload = _guarded_shell(command, controller.worktree, 600)
    passed = result_payload["returncode"] == 0
    payload = {
        "kind": "acceptance",
        "task_id": task_id,
        "attempt_id": attempt_id,
        "status": "passed" if passed else "changes_requested",
        "passed": passed,
        "findings": [] if passed else [{"severity": "high", "summary": "acceptance failed", "action": "repair acceptance failure"}],
        "missing_evidence": [],
        **_binding(kernel, task_id),
        **result_payload,
    }
    ref = _attach(kernel, task_id, attempt_id, "acceptance", payload)
    return passed, payload, ref


def _attempt_evidence(kernel: Kernel, attempt_id: str) -> list[dict]:
    matches = [
        attempt for attempt in kernel.state.get("attempts", [])
        if attempt.get("attempt_id") == attempt_id
    ]
    return list(matches[-1].get("evidence_refs") or []) if matches else []


def _block(
    kernel: Kernel,
    task_id: str,
    phase: str,
    reason: str,
    *,
    category: str | None = None,
    root_cause_key: str | None = None,
    owner: str = "cpe",
    resume_condition: str | None = None,
    evidence_refs: list[dict] | None = None,
    details: dict[str, object] | None = None,
) -> dict:
    category = category or "runtime_blocked"
    root_cause_key = root_cause_key or f"{phase}:{reason}"
    refs = list(evidence_refs or [])
    if not refs:
        ref = _attach(
            kernel,
            task_id,
            None,
            "blocker_evidence",
            {
                "kind": "blocker_evidence",
                "task_id": task_id,
                "phase": phase,
                "reason": reason,
                "category": category,
                "root_cause_key": root_cause_key,
                **_binding(kernel, task_id),
            },
        )
        refs = [ref]
    state = kernel.state
    active = [
        blocker for blocker in state.get("active_blockers", [])
        if blocker.get("task_id") == task_id
        and blocker.get("category") == category
        and blocker.get("root_cause_key") == root_cause_key
    ]
    if not active:
        payload: dict[str, object] = {
            "blocker_id": f"{task_id}.{category}.{len(state.get('blocker_history', [])) + 1}",
            "category": category,
            "root_cause_key": root_cause_key,
            "owner": owner,
            "resume_condition": resume_condition
            or "resolve the typed blocker and schedule an explicit retry",
            "evidence_refs": refs,
        }
        payload.update(details or {})
        kernel.transition(Transition("blocker.opened", payload, task_id=task_id))
    state = kernel.state
    current = state["tasks"][task_id]["status"]
    if current not in {"blocked", "failed", "completed"}:
        kernel.transition(
            Transition(
                "task.status_changed",
                {"from": current, "to": "blocked", "reason": reason},
                task_id=task_id,
            )
        )
    if kernel.state["lifecycle"] == "running":
        kernel.transition(
            Transition(
                "run.status_changed",
                {"from": "running", "to": "blocked", "reason": reason},
            )
        )
    return {
        "completed": [
            key for key, value in kernel.state["tasks"].items() if value["status"] == "completed"
        ],
        "blocked": task_id,
        "status": "blocked",
        "reason": reason,
        "phase": phase,
    }


def _scope_block(
    kernel: Kernel,
    task_id: str,
    phase: str,
    outcome: WriteAttemptOutcome[WorkerResult],
) -> dict:
    error = outcome.scope_errors[0]
    root_cause_key = (
        error
        if error == "worktree_head_changed"
        else f"task_scope:{task_id}:{error.split(':', 1)[1]}"
    )
    result = _block(
        kernel,
        task_id,
        phase,
        "policy_violation",
        category="policy_violation",
        root_cause_key=root_cause_key,
        resume_condition="restore task scope and schedule an explicit retry",
        details={"scope_errors": list(outcome.scope_errors)},
    )
    result.update(
        failure_category="policy_violation",
        root_cause_key=root_cause_key,
        scope_errors=list(outcome.scope_errors),
    )
    return result


def _verdict_block(
    kernel: Kernel,
    task_id: str,
    phase: str,
    attempt_id: str,
    verdict: dict,
) -> TaskCycleResult:
    status = str(verdict["status"])
    binding = _binding(kernel, task_id)
    _block(
        kernel,
        task_id,
        phase,
        f"{phase}_verdict:{status}",
        category=status,
        root_cause_key=f"{phase}:{status}",
        owner=str(verdict.get("owner") or "cpe"),
        resume_condition=str(
            verdict.get("resume_condition")
            or verdict.get("next_evidence_action")
            or "satisfy the typed verdict and schedule an explicit retry"
        ),
        evidence_refs=_attempt_evidence(kernel, attempt_id),
    )
    return TaskCycleResult(task_id, "blocked", phase, int(binding["worktree_revision"]), status)


def _repair(
    task: dict,
    controller: AttemptController,
    kernel: Kernel,
    root_key: str,
    *,
    preserve_completed: bool,
    recovery_context: str | None = None,
) -> TaskCycleResult | None:
    task_id = str(task["id"])
    current = kernel.state["tasks"][task_id]["status"]
    if not preserve_completed:
        if current not in {"reviewing", "verifying", "implementing", "repairing"}:
            raise ValueError(f"cannot repair task from {current}")
        if current != "repairing":
            kernel.transition(
                Transition(
                    "task.status_changed",
                    {"from": current, "to": "repairing"},
                    task_id=task_id,
                )
            )
    operator_decision = _latest_operator_decision(kernel, task_id)
    operator_context = (
        " User-approved operator decision evidence applies: "
        + json.dumps(operator_decision, ensure_ascii=False, sort_keys=True)
        if operator_decision is not None
        else ""
    )
    prompt = (
        f"Repair {task_id} root cause {root_key}; remain inside file claims."
        f"{operator_context}"
    )
    if recovery_context:
        prompt += f" Evidence-backed delegated recovery context: {recovery_context}"
    repair, outcome, attempt_id = _worker_attempt(
        controller,
        kernel,
        task,
        "repair",
        prompt,
    )
    if outcome is not None and outcome.scope_errors:
        _scope_block(kernel, task_id, "repair", outcome)
        return TaskCycleResult(task_id, "blocked", "repair", outcome.worktree_revision, "policy_violation")
    if repair.status != "completed" or not _trusted(repair):
        category = str(repair.payload.get("failure_category") or "repair_failed")
        _block(
            kernel,
            task_id,
            "repair",
            f"repair_failed:{root_key}",
            category=category,
            root_cause_key=str(repair.payload.get("root_cause_key") or root_key),
            evidence_refs=_attempt_evidence(kernel, attempt_id),
        )
        return TaskCycleResult(task_id, "blocked", "repair", kernel.state["worktree_revision"], root_key)
    if outcome is None or (not outcome.delta.changed_files and not outcome.delta.head_changed):
        no_change_retry_is_valid = (
            outcome is not None
            and root_key == "scheduled_retry:repair"
            and validate_integrity(kernel.run_dir).passed
        )
        if not no_change_retry_is_valid:
            _block(kernel, task_id, "repair", f"repair_did_not_advance_revision:{root_key}")
            return TaskCycleResult(
                task_id, "blocked", "repair", kernel.state["worktree_revision"], root_key
            )
    if not preserve_completed:
        kernel.transition(
            Transition(
                "task.status_changed",
                {"from": "repairing", "to": "reviewing"},
                task_id=task_id,
            )
        )
    return None


def run_delegated_dependency_repair(
    owner_task: dict,
    target_task_id: str,
    root_key: str,
    recovery_context: str,
    worker: Worker,
    kernel: Kernel,
) -> TaskCycleResult:
    """Repair a cross-task integration defect through one completed dependency packet."""

    owner_id = str(owner_task["id"])
    if kernel.state["tasks"].get(owner_id, {}).get("status") != "completed":
        raise ValueError("delegated repair owner must be completed")
    worktree = resolve_ref(
        str(load_verified_manifest(kernel.run_dir / "run_manifest.json")["execution_worktree_ref"])
    )
    controller = AttemptController(kernel, worktree, worker)
    blocked = _repair(
        owner_task,
        controller,
        kernel,
        root_key,
        preserve_completed=True,
        recovery_context=(
            f"Target task {target_task_id} is blocked by a claim boundary. "
            f"Use only this dependency packet's claims. {recovery_context}"
        ),
    )
    if blocked is not None:
        return blocked
    return run_task_cycle(owner_task, controller, kernel)


def _latest_task_payload(kernel: Kernel, task_id: str, kind: str) -> dict | None:
    for artifact in reversed(kernel.state.get("artifact_index", [])):
        if artifact.get("task_id") != task_id or artifact.get("kind") != kind:
            continue
        ref = artifact.get("ref")
        if not isinstance(ref, dict):
            continue
        try:
            payload = json.loads(
                (kernel.run_dir / str(ref["path"])).read_text(encoding="utf-8")
            )
        except (KeyError, OSError, json.JSONDecodeError):
            continue
        binding = _binding(kernel, task_id)
        if all(payload.get(key) == binding.get(key) for key in binding):
            return payload
    return None


def _latest_operator_decision(kernel: Kernel, task_id: str) -> dict | None:
    for artifact in reversed(kernel.state.get("artifact_index", [])):
        if artifact.get("task_id") != task_id or artifact.get("kind") != "operator_decision":
            continue
        ref = artifact.get("ref")
        if not isinstance(ref, dict):
            continue
        try:
            payload = json.loads(
                (kernel.run_dir / str(ref["path"])).read_text(encoding="utf-8")
            )
        except (KeyError, OSError, json.JSONDecodeError):
            continue
        if (
            isinstance(payload, dict)
            and payload.get("kind") == "operator_decision"
            and payload.get("task_id") == task_id
            and payload.get("worktree_revision") == kernel.state.get("worktree_revision")
            and payload.get("approved") is True
        ):
            return payload
    return None


def _worker_block_cycle(
    kernel: Kernel,
    task_id: str,
    phase: str,
    result: WorkerResult,
    attempt_id: str,
) -> TaskCycleResult:
    category = str(result.payload.get("failure_category") or f"{phase}_failed")
    root = str(result.payload.get("root_cause_key") or f"{phase}:worker_failed")
    if category == "transient":
        category = f"{phase}_interrupted"
        root = f"{phase}:interrupted"
    _block(
        kernel,
        task_id,
        phase,
        f"{phase}_worker_failed",
        category=category,
        root_cause_key=root,
        evidence_refs=_attempt_evidence(kernel, attempt_id),
    )
    return TaskCycleResult(
        task_id, "blocked", phase, int(kernel.state["worktree_revision"]), category
    )


def run_task_cycle(task: dict, controller: AttemptController, kernel: Kernel) -> TaskCycleResult:
    task_id = str(task["id"])
    if task_id not in kernel.state.get("tasks", {}):
        raise ValueError("unknown task")
    preserve_completed = kernel.state["tasks"][task_id]["status"] == "completed"
    phase = "acceptance" if preserve_completed else next_phase(kernel.state, task_id)
    if phase == "implementation":
        operator_decision = _latest_operator_decision(kernel, task_id)
        operator_context = (
            " User-approved operator decision evidence applies: "
            + json.dumps(operator_decision, ensure_ascii=False, sort_keys=True)
            if operator_decision is not None
            else ""
        )
        implementation, outcome, implementation_attempt = _worker_attempt(
            controller,
            kernel,
            task,
            "implementation",
            f"Implement task {task_id} using only its verified packet and current revision."
            f"{operator_context}",
        )
        if outcome is not None and outcome.scope_errors:
            _scope_block(kernel, task_id, "implementation", outcome)
            return TaskCycleResult(task_id, "blocked", "implementation", outcome.worktree_revision, "policy_violation")
        if implementation.status != "completed" or not _trusted(implementation):
            return _worker_block_cycle(
                kernel, task_id, "implementation", implementation, implementation_attempt
            )
        current = kernel.state["tasks"][task_id]["status"]
        if current != "implementing":
            raise ValueError(f"implementation completed from unexpected state {current}")
        kernel.transition(
            Transition(
                "task.status_changed",
                {"from": "implementing", "to": "reviewing"},
                task_id=task_id,
            )
        )
        phase = "acceptance"
    elif phase == "repair":
        blocked = _repair(
            task,
            controller,
            kernel,
            "scheduled_retry:repair",
            preserve_completed=False,
        )
        if blocked is not None:
            return blocked
        phase = "acceptance"
    elif phase not in {"acceptance", "task_review", "verification"}:
        raise ValueError(f"task cycle cannot start from phase {phase}")

    repair_counts: dict[str, int] = {}
    acceptance: dict | None = None
    while True:
        root_key: str | None = None
        failed_phase = phase
        if phase == "acceptance":
            acceptance_ok, acceptance, acceptance_ref = _acceptance(task, controller, kernel)
            failure_category = acceptance.get("failure_category")
            if failure_category in {"read_only_mutation", "read_only_guard_failure"}:
                _block(
                    kernel,
                    task_id,
                    "acceptance",
                    str(failure_category),
                    category=str(failure_category),
                    root_cause_key=str(
                        acceptance.get("root_cause_key") or "acceptance:read_only_guard"
                    ),
                    evidence_refs=[acceptance_ref],
                )
                return TaskCycleResult(
                    task_id,
                    "blocked",
                    "acceptance",
                    int(kernel.state["worktree_revision"]),
                    str(failure_category),
                )
            if not acceptance_ok:
                root_key = f"acceptance:{acceptance['returncode']}"
                failed_phase = "acceptance"
            else:
                phase = "task_review"
        if phase == "task_review" and root_key is None:
            acceptance = acceptance or _latest_task_payload(kernel, task_id, "acceptance")
            if acceptance is None:
                _block(
                    kernel,
                    task_id,
                    "task_review",
                    "current_acceptance_evidence_missing",
                    category="missing_evidence",
                    root_cause_key="task_review:current_acceptance_evidence_missing",
                )
                return TaskCycleResult(
                    task_id, "blocked", "task_review",
                    int(kernel.state["worktree_revision"]), "missing_evidence"
                )
            operator_decision = _latest_operator_decision(kernel, task_id)
            operator_context = (
                " User-approved operator decision evidence applies: "
                + json.dumps(operator_decision, ensure_ascii=False, sort_keys=True)
                if operator_decision is not None
                else ""
            )
            review, _, review_attempt = _worker_attempt(
                controller,
                kernel,
                task,
                "task_review",
                f"Review task {task_id} against its packet, acceptance, and current diff."
                f"{operator_context}",
            )
            _semantic_verdict(kernel, task_id, review_attempt, "task_review", review)
            review_verdict = review.payload.get("verdict")
            if review.status != "completed" or not _trusted(review) or not isinstance(review_verdict, dict):
                return _worker_block_cycle(
                    kernel, task_id, "task_review", review, review_attempt
                )
            else:
                route = route_verdict(review_verdict)
                if route in {"blocked", "inconclusive"}:
                    return _verdict_block(kernel, task_id, "task_review", review_attempt, review_verdict)
                if route == "repair":
                    root_key = str(review.payload.get("root_cause_key") or "task_review:changes_requested")
                    failed_phase = "task_review"
                else:
                    if not preserve_completed and kernel.state["tasks"][task_id]["status"] == "reviewing":
                        kernel.transition(
                            Transition(
                                "task.status_changed",
                                {"from": "reviewing", "to": "verifying"},
                                task_id=task_id,
                            )
                        )
                    phase = "verification"
        if phase == "verification" and root_key is None:
            acceptance = acceptance or _latest_task_payload(kernel, task_id, "acceptance")
            if acceptance is None:
                _block(
                    kernel,
                    task_id,
                    "verification",
                    "current_acceptance_evidence_missing",
                    category="missing_evidence",
                    root_cause_key="verification:current_acceptance_evidence_missing",
                )
                return TaskCycleResult(
                    task_id, "blocked", "verification",
                    int(kernel.state["worktree_revision"]), "missing_evidence"
                )
            verification, _, verification_attempt = _worker_attempt(
                controller,
                kernel,
                task,
                "verification",
                f"Verify acceptance and task-review evidence for {task_id}: {acceptance}",
            )
            _semantic_verdict(
                kernel, task_id, verification_attempt, "verification", verification
            )
            verification_verdict = verification.payload.get("verdict")
            if (
                verification.status != "completed"
                or not _trusted(verification)
                or not isinstance(verification_verdict, dict)
            ):
                return _worker_block_cycle(
                    kernel, task_id, "verification", verification, verification_attempt
                )
            route = route_verdict(verification_verdict)
            if route in {"blocked", "inconclusive"}:
                return _verdict_block(
                    kernel,
                    task_id,
                    "verification",
                    verification_attempt,
                    verification_verdict,
                )
            if route == "continue":
                if not preserve_completed:
                    kernel.transition(
                        Transition(
                            "task.status_changed",
                            {"from": "verifying", "to": "completed"},
                            task_id=task_id,
                        )
                    )
                return TaskCycleResult(
                    task_id,
                    "passed",
                    "verification",
                    int(kernel.state["worktree_revision"]),
                )
            root_key = str(
                verification.payload.get("root_cause_key")
                or "verification:changes_requested"
            )
            failed_phase = "verification"

        assert root_key is not None
        repair_counts[root_key] = repair_counts.get(root_key, 0) + 1
        if repair_counts[root_key] > 2:
            _block(kernel, task_id, failed_phase, f"repair_limit_exhausted:{root_key}")
            return TaskCycleResult(
                task_id,
                "blocked",
                failed_phase,
                int(kernel.state["worktree_revision"]),
                root_key,
            )
        blocked = _repair(
            task,
            controller,
            kernel,
            root_key,
            preserve_completed=preserve_completed,
        )
        if blocked is not None:
            return blocked
        acceptance = None
        phase = "acceptance"


def _v4_state(kernel: Kernel) -> dict:
    from .repair import scheduler_bookkeeping

    return scheduler_bookkeeping(kernel.state)


def _v4_result(
    kernel: Kernel,
    task_id: str,
    status: str,
    phase: TaskPhase,
    phases: list[TaskPhase],
    budget_before: int,
    scopes: list[ReviewScope],
    reason: str | None = None,
) -> TaskCycleResult:
    state = _v4_state(kernel)
    used = int((state.get("attempt_budget") or {}).get("used", 0))
    return TaskCycleResult(
        task_id=task_id,
        status=status,
        phase=phase,
        worktree_revision=len(state.get("candidate_checkpoints") or []),
        reason=reason,
        phases=tuple(phases),
        model_attempts=used - budget_before,
        state=state,
        review_scopes=tuple(scopes),
    )


def _v4_preflight_failure(
    contract: object,
    operations: object,
    kernel: Kernel,
    run_dir: Path,
) -> str | None:
    """Bind dispatch to the canonical manifest task and immutable packet."""

    from .manifest import load_verified_manifest
    from .packets import verify_packet
    from .task_contracts import TaskContractV4

    if not isinstance(contract, TaskContractV4) or not isinstance(
        operations, LifecycleOperations
    ):
        return "contract_invalid"
    kernel_run_dir = getattr(kernel, "run_dir", None)
    if (
        not isinstance(kernel_run_dir, Path)
        or run_dir.resolve() != kernel_run_dir.resolve()
    ):
        return "run_binding_invalid"
    task_id = contract.task_id
    tasks = kernel.state.get("tasks")
    task_state = tasks.get(task_id) if isinstance(tasks, dict) else None
    if not isinstance(task_state, dict):
        return "contract_binding_invalid"
    canonical_id = task_state.get("id", task_id)
    canonical_contract = task_state.get("task_contract_sha256")
    if canonical_id != task_id or (
        canonical_contract is not None
        and canonical_contract != contract.contract_sha256
    ):
        return "contract_binding_invalid"
    if (
        not isinstance(operations.packet_sha256, str)
        or len(operations.packet_sha256) != 64
        or any(
            character not in "0123456789abcdef"
            for character in operations.packet_sha256
        )
    ):
        return "packet_binding_invalid"
    canonical_packet = task_state.get("task_packet_sha256")
    if canonical_packet is not None and canonical_packet != operations.packet_sha256:
        return "packet_binding_invalid"

    manifest_path = run_dir.resolve() / "run_manifest.json"
    if not manifest_path.is_file():
        return "run_binding_invalid"
    try:
        manifest = load_verified_manifest(manifest_path)
        entries = [
            item
            for item in manifest.get("task_graph", [])
            if isinstance(item, dict) and item.get("id") == task_id
        ]
        if len(entries) != 1:
            return "contract_binding_invalid"
        entry = entries[0]
        if (
            entry.get("task_contract_sha256") != contract.contract_sha256
            or entry.get("task_contract") != contract.body()
        ):
            return "contract_binding_invalid"
        packet = verify_packet(run_dir, manifest, task_id)
        if packet.sha256 != operations.packet_sha256:
            return "packet_binding_invalid"
        payload = json.loads(packet.content)
        if (
            payload.get("task_id") != task_id
            or payload.get("task_contract_sha256") != contract.contract_sha256
            or payload.get("task_contract") != contract.body()
        ):
            return "packet_binding_invalid"
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return "packet_binding_invalid"
    return None


def _require_v4_worker_result(result: object) -> WorkerResult:
    if not isinstance(result, WorkerResult) or result.status != "completed" or not _trusted(result):
        raise ValueError("untrusted_model_result")
    return result


def _verify_v4_method_evidence(
    run_dir: Path,
    contract: object,
    packet_sha256: str,
    result: WorkerResult,
) -> None:
    from .evidence import verify_method_evidence_ref
    from .task_contracts import TaskContractV4

    if not isinstance(contract, TaskContractV4):
        raise ValueError("task_contract_invalid")
    if contract.task_type != "tdd_implementation":
        return
    ref = result.payload.get("method_evidence_ref")
    problems = verify_method_evidence_ref(
        run_dir,
        ref,
        task_id=contract.task_id,
        packet_sha256=packet_sha256,
        contract_sha256=contract.contract_sha256,
    )
    if problems:
        raise ValueError(f"method_evidence_invalid:{problems[0]}")


def _attach_v4_method_evidence(
    kernel: Kernel, task_id: str, attempt_id: str, result: WorkerResult
) -> None:
    ref = result.payload.get("method_evidence_ref")
    if not isinstance(ref, dict):
        return
    kernel.transition(
        Transition(
            "evidence.attached",
            {"kind": "method_evidence", "ref": dict(ref)},
            task_id=task_id,
            attempt_id=attempt_id,
        )
    )


def review_scope_payload(scope: ReviewScope) -> dict[str, object]:
    return {
        "kind": scope.kind,
        "base_commit": scope.base_commit,
        "candidate_commit": scope.candidate_commit,
        "previous_findings": [dict(item) for item in scope.previous_findings],
        "reopen_full_task_diff": scope.reopen_full_task_diff,
        "boundary_changes": list(scope.boundary_changes),
    }


def review_scope_sha256(scope: ReviewScope) -> str:
    raw = json.dumps(
        review_scope_payload(scope),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(b"CPE-REVIEW-SCOPE-V4\0" + raw).hexdigest()


def _review_verdict(result: WorkerResult) -> dict[str, object]:
    verdict = result.payload.get("verdict")
    if not isinstance(verdict, dict) or verdict.get("status") not in {
        "passed", "changes_requested", "blocked", "inconclusive"
    }:
        raise ValueError("review_verdict_invalid")
    if not isinstance(verdict.get("findings"), list) or not isinstance(
        verdict.get("missing_evidence"), list
    ):
        raise ValueError("review_verdict_invalid")
    return dict(verdict)


def _bound_review_verdict(
    result: WorkerResult,
    contract: object,
    candidate: object,
    scope: ReviewScope,
    kernel: Kernel,
) -> dict[str, object]:
    from .task_contracts import TaskContractV4

    verdict = _review_verdict(result)
    if not isinstance(contract, TaskContractV4):
        raise ValueError("task_contract_invalid")
    binding = verdict.get("review_binding")
    expected = {
        "task_id": contract.task_id,
        "candidate_commit": getattr(candidate, "commit", None),
        "candidate_tree": getattr(candidate, "tree", None),
        "contract_sha256": contract.contract_sha256,
        "worktree_revision": len(kernel.state.get("candidate_checkpoints", [])),
        "review_scope_sha256": review_scope_sha256(scope),
        "requested_scope": review_scope_payload(scope),
    }
    if not isinstance(binding, dict) or binding != expected:
        raise ValueError("review_binding_mismatch")
    return verdict


def _record_v4_verdict(
    kernel: Kernel, task_id: str, attempt_id: str, verdict: dict[str, object]
) -> None:
    from .repair import require_privacy_safe_review_payload

    payload = _recorded_v4_verdict(verdict)
    require_privacy_safe_review_payload(payload)
    kernel.transition(
        Transition(
            "verdict.recorded",
            payload,
            task_id=task_id,
            attempt_id=attempt_id,
        )
    )


def _recorded_v4_verdict(verdict: dict[str, object]) -> dict[str, object]:
    return {
        "status": verdict["status"],
        "findings": list(verdict["findings"]),
        "missing_evidence": list(verdict["missing_evidence"]),
        **(
            {"review_binding": dict(verdict["review_binding"])}
            if isinstance(verdict.get("review_binding"), dict)
            else {}
        ),
    }


def _approved_review_evidence(
    contract: object,
    candidate: object,
    verdict: dict[str, object],
    *,
    adjudication: str,
):
    from .checkpoints import create_review_evidence
    from .task_contracts import TaskContractV4

    if not isinstance(contract, TaskContractV4):
        raise ValueError("task_contract_invalid")
    content = {
        "verdict": verdict,
        "scheduler_adjudication": adjudication,
    }
    digest = hashlib.sha256(
        json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return create_review_evidence(
        task_id=contract.task_id,
        candidate_commit=str(getattr(candidate, "commit")),
        contract_sha256=contract.contract_sha256,
        decision="approved",
        review_content_sha256=digest,
    )


def _initial_review_scope(candidate: object) -> ReviewScope:
    return ReviewScope(
        kind="task_diff",
        base_commit=str(getattr(candidate, "predecessor")),
        candidate_commit=str(getattr(candidate, "commit")),
    )


def _repair_review_scope(
    rejected: object,
    repaired: object,
    findings: tuple[dict[str, object], ...],
    boundary_changes: tuple[str, ...],
) -> ReviewScope:
    reopen = bool(
        {"security", "state_integrity", "evidence"}.intersection(boundary_changes)
    )
    return ReviewScope(
        kind="task_diff" if reopen else "repair_delta",
        base_commit=(
            str(getattr(repaired, "predecessor"))
            if reopen
            else str(getattr(rejected, "commit"))
        ),
        candidate_commit=str(getattr(repaired, "commit")),
        previous_findings=findings,
        reopen_full_task_diff=reopen,
        boundary_changes=boundary_changes,
    )


def _task_transition(
    kernel: Kernel,
    task_id: str,
    target: str,
    *,
    wait_reason: str | None = None,
    resume_phase: str | None = None,
    attempt_id: str | None = None,
) -> None:
    current = str(kernel.state["tasks"][task_id]["status"])
    if current == target:
        return
    payload: dict[str, object] = {"from": current, "to": target}
    if target in {"waiting_external", "waiting_user"}:
        payload.update(
            {
                "wait_reason": wait_reason,
                "resume_phase": resume_phase,
                "active_attempt_id": attempt_id,
            }
        )
    elif target == "blocked":
        payload["wait_reason"] = wait_reason
    elif current in {"waiting_external", "waiting_user"}:
        task = kernel.state["tasks"][task_id]
        payload.update(
            {
                "resume_phase": task.get("resume_phase"),
                "active_attempt_id": attempt_id,
            }
        )
    kernel.transition(
        Transition(
            "task.status_changed",
            payload,
            task_id=task_id,
            attempt_id=attempt_id,
        )
    )


def _active_attempt_id(kernel: Kernel, task_id: str, kind: str) -> str | None:
    active = [
        item
        for item in kernel.state.get("attempts", [])
        if item.get("task_id") == task_id
        and item.get("kind") == kind
        and item.get("status") == "started"
    ]
    if len(active) > 1:
        raise ValueError("active_model_attempt_ambiguous")
    return str(active[0]["attempt_id"]) if active else None


def _wait_for_phase(
    kernel: Kernel,
    task_id: str,
    phase: str,
    reason: str,
    attempt_id: str | None,
) -> None:
    current = kernel.state["tasks"][task_id]["status"]
    if current in {"waiting_external", "waiting_user"}:
        return
    _task_transition(
        kernel,
        task_id,
        "waiting_external",
        wait_reason=reason,
        resume_phase=phase,
        attempt_id=attempt_id,
    )


def _block_task(kernel: Kernel, task_id: str, reason: str) -> None:
    current = kernel.state["tasks"][task_id]["status"]
    if current == "blocked":
        return
    _task_transition(kernel, task_id, "blocked", wait_reason=reason)
    kernel.transition(
        Transition(
            "decision.recorded",
            {
                "decision_kind": "task_blocked",
                "selected_action": "block_release",
                "basis": reason,
                "approval_basis": "standing_autonomy_policy",
                "failure_category": reason,
            },
            task_id=task_id,
        )
    )


def _checkpoint_base(kernel: Kernel) -> str:
    base = kernel.state.get("checkpoint_head") or kernel.state.get("source_head")
    if not isinstance(base, str):
        raise ValueError("checkpoint_predecessor_invalid")
    return base


def _restore_phase_base(
    contract: object,
    product_worktree: Path,
    target_commit: str,
) -> None:
    from .repair import restore_interrupted_worktree
    from .task_contracts import TaskContractV4

    if not isinstance(contract, TaskContractV4):
        raise ValueError("task_contract_invalid")
    restore_interrupted_worktree(
        product_worktree,
        target_commit,
        file_claims=contract.file_claims,
        forbidden_paths=contract.forbidden_paths,
    )


def _candidate_from_state(kernel: Kernel, task_id: str, index: int = -1):
    from .checkpoints import CandidateCheckpoint

    records = [
        item
        for item in kernel.state.get("candidate_checkpoints", [])
        if item.get("task_id") == task_id
    ]
    if not records:
        raise ValueError("candidate_checkpoint_missing")
    record = records[index]
    return CandidateCheckpoint(
        task_id=task_id,
        contract_sha256=str(record["contract_sha256"]),
        predecessor=str(record["predecessor"]),
        commit=str(record["commit"]),
        tree=str(record["tree"]),
        patch_sha256=str(record["patch_sha256"]),
        changed_files=tuple(record["changed_files"]),
    )


def _run_v4_acceptance(
    contract: object,
    operations: LifecycleOperations,
    product_worktree: Path,
    run_dir: Path,
    candidate: object,
):
    from .verification_workspace import run_acceptance, verification_worktree

    with verification_worktree(
        product_worktree,
        str(getattr(candidate, "commit")),
        run_dir,
        str(getattr(contract, "task_id")),
    ) as checkout:
        results = run_acceptance(
            getattr(contract, "acceptance_commands"),
            checkout,
            operations.acceptance_environment,
        )
    if any(item.exit_code != 0 for item in results):
        raise ValueError("acceptance_failed")
    return results


def _latest_findings(kernel: Kernel, task_id: str) -> tuple[dict[str, object], ...]:
    for verdict in reversed(kernel.state.get("verdicts", [])):
        if verdict.get("task_id") == task_id and verdict.get("status") == "changes_requested":
            return tuple(
                dict(item)
                for item in verdict.get("findings", [])
                if isinstance(item, dict)
            )
    raise ValueError("repair_findings_missing")


def _deterministic_evidence(
    kernel: Kernel,
    contract: object,
    candidate: object,
    review_evidence: object,
    summary: str,
) -> None:
    ref = _put_json(
        kernel.run_dir,
        "deterministic_verification",
        {
            "task_id": getattr(contract, "task_id"),
            "contract_sha256": getattr(contract, "contract_sha256"),
            "candidate_commit": getattr(candidate, "commit"),
            "review_sha256": getattr(review_evidence, "artifact_sha256"),
            "summary_sha256": hashlib.sha256(summary.encode()).hexdigest(),
            "passed": True,
        },
    ).as_dict()
    kernel.transition(
        Transition(
            "evidence.attached",
            {
                "kind": "deterministic_verification",
                "ref": ref,
                "candidate_commit": getattr(candidate, "commit"),
                "contract_sha256": getattr(contract, "contract_sha256"),
                "passed": True,
            },
            task_id=str(getattr(contract, "task_id")),
        )
    )


def _store_review_evidence(
    kernel: Kernel,
    contract: object,
    review_evidence: object,
) -> None:
    from dataclasses import asdict
    from .checkpoints import ReviewEvidence

    if not isinstance(review_evidence, ReviewEvidence):
        raise ValueError("review_evidence_invalid")
    ref = _put_json(
        kernel.run_dir, "review_evidence", asdict(review_evidence)
    ).as_dict()
    kernel.transition(
        Transition(
            "evidence.attached",
            {"kind": "review_evidence", "ref": ref},
            task_id=str(getattr(contract, "task_id")),
        )
    )


def _load_review_evidence(
    kernel: Kernel,
    contract: object,
    candidate: object,
):
    from .checkpoints import create_review_evidence
    from .evidence import verify_ref

    for item in reversed(kernel.state.get("artifact_index", [])):
        if (
            item.get("task_id") != getattr(contract, "task_id")
            or item.get("kind") != "review_evidence"
            or not isinstance(item.get("ref"), dict)
        ):
            continue
        ref = item["ref"]
        if verify_ref(kernel.run_dir, ref):
            continue
        try:
            payload = json.loads(
                (kernel.run_dir / str(ref["path"])).read_text(encoding="utf-8")
            )
            evidence = create_review_evidence(
                task_id=str(payload["task_id"]),
                candidate_commit=str(payload["candidate_commit"]),
                contract_sha256=str(payload["contract_sha256"]),
                decision=str(payload["decision"]),
                review_content_sha256=str(payload["review_content_sha256"]),
            )
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
            continue
        if (
            evidence.artifact_sha256 == payload.get("artifact_sha256")
            and evidence.task_id == getattr(contract, "task_id")
            and evidence.contract_sha256 == getattr(contract, "contract_sha256")
            and evidence.candidate_commit == getattr(candidate, "commit")
        ):
            return evidence
    raise ValueError("review_evidence_missing")


def run_task_cycle_v4(
    contract: object,
    operations: LifecycleOperations,
    kernel: Kernel,
    product_worktree: Path,
    run_dir: Path,
) -> TaskCycleResult:
    """Run or exactly resume one bounded v4 task lifecycle."""

    from .checkpoints import create_candidate_checkpoint, promote_verified_checkpoint
    from .failure_policy import classify_failure
    from .reconciliation import select_v4_resume
    from .repair import (
        prepare_repaired_candidate,
        record_backlog,
        record_repair_root,
        record_selected_repair,
        reopen_selected_repair,
        resolve_selected_repair,
    )
    task_id = str(getattr(contract, "task_id", ""))
    phases: list[TaskPhase] = ["preflight"]
    scopes: list[ReviewScope] = []
    budget_before = int((kernel.state.get("attempt_budget") or {}).get("used", 0))

    def finish(
        status: str,
        phase: TaskPhase,
        reason: str | None = None,
    ) -> TaskCycleResult:
        return _v4_result(
            kernel,
            task_id,
            status,
            phase,
            phases,
            budget_before,
            scopes,
            reason,
        )

    preflight_failure = _v4_preflight_failure(
        contract, operations, kernel, run_dir
    )
    if preflight_failure is not None:
        phases.append("blocked")
        return finish("blocked", "blocked", preflight_failure)
    if any(
        item.get("task_id") == task_id
        and item.get("contract_sha256") == contract.contract_sha256
        for item in kernel.state.get("verified_checkpoints", [])
    ):
        return finish("completed", "verified_checkpoint")

    task_state = kernel.state["tasks"][task_id]
    if task_state["status"] == "waiting_user":
        return finish(
            "waiting_user",
            "waiting_user",
            str(task_state.get("wait_reason") or "authority_resolution_required"),
        )
    if task_state["status"] == "pending":
        _task_transition(kernel, task_id, "ready")
    resume = select_v4_resume(kernel.state, task_id)
    phase = resume.phase or "implementation"
    if phase not in {"implementation", "task_review", "repair", "verification"}:
        phase = "implementation"
    controller = ModelAttemptController(kernel)
    candidate = None
    acceptance = None
    review_evidence = None
    scope = None
    selected_repair: dict[str, object] | None = None

    def restore_or_block(target: str, abandon_kind: str | None = None) -> bool:
        try:
            _restore_phase_base(contract, product_worktree, target)
            return True
        except (RuntimeError, ValueError):
            if abandon_kind is not None:
                controller.interrupt_active(
                    task_id=task_id,
                    kind=abandon_kind,
                    reason="evidence_integrity_failure",
                )
            _block_task(kernel, task_id, "evidence_integrity_failure")
            phases.append("blocked")
            return False

    def wait_after(
        wait_phase: str,
        reason: str,
        target: str,
        kind: str,
    ) -> TaskCycleResult:
        if not restore_or_block(target, kind):
            return finish("blocked", "blocked", "evidence_integrity_failure")
        attempt_id = _active_attempt_id(kernel, task_id, kind)
        _wait_for_phase(kernel, task_id, wait_phase, reason, attempt_id)
        phases.append("waiting_external")
        return finish("waiting_external", "waiting_external", reason)

    def on_started(target_status: str, repair: tuple[str, int] | None = None):
        def callback(_kind: str, attempt_id: str, _started_new: bool) -> None:
            if repair is not None:
                current_count = int(
                    _v4_state(kernel).get("repair_roots", {}).get(repair[0], 0)
                )
                if current_count < repair[1]:
                    record_repair_root(
                        kernel,
                        task_id=task_id,
                        root_cause_key=repair[0],
                        count=repair[1],
                    )
            current = kernel.state["tasks"][task_id]["status"]
            if current != target_status:
                _task_transition(
                    kernel,
                    task_id,
                    target_status,
                    attempt_id=attempt_id,
                )

        return callback

    if phase == "implementation":
        phases.append("implementation")
        base = _checkpoint_base(kernel)
        try:
            turn, _phase_projection = _execute_phase_operation(
                RunState("ready", task_id),
                TypedOutcome("start", task_id),
                lambda: controller.run_model_turn(
                    task_id=task_id,
                    kind="implementation",
                    before_turn=operations.before_model_turn,
                    operation=lambda attempt_id: operations.implementation(
                        contract, attempt_id
                    ),
                    preserve_attempt_on=(ExternalModelInterruption,),
                    on_turn_started=on_started("implementing"),
                ),
            )
        except PreTurnInterruption as exc:
            _wait_for_phase(kernel, task_id, "implementation", str(exc), None)
            phases.append("waiting_external")
            return finish("waiting_external", "waiting_external", str(exc))
        except ExternalModelInterruption as exc:
            return wait_after(
                "implementation", exc.root_cause_key, base, "implementation"
            )
        except RuntimeUpgradeInterruption as exc:
            return wait_after(
                "implementation", exc.root_cause_key, base, "implementation"
            )
        except (RuntimeError, ValueError) as exc:
            if not restore_or_block(base):
                return finish("blocked", "blocked", "evidence_integrity_failure")
            _block_task(kernel, task_id, "implementation_failed")
            phases.append("blocked")
            return finish("blocked", "blocked", str(exc))
        try:
            implementation = _require_v4_worker_result(turn.result)
            _verify_v4_method_evidence(
                run_dir, contract, operations.packet_sha256, implementation
            )
            _attach_v4_method_evidence(
                kernel, task_id, turn.attempt_id, implementation
            )
        except (RuntimeError, ValueError) as exc:
            if not restore_or_block(base):
                return finish("blocked", "blocked", "evidence_integrity_failure")
            _block_task(kernel, task_id, "method_contract_failed")
            phases.append("blocked")
            return finish("blocked", "blocked", str(exc))
        phases.append("candidate")
        try:
            candidate = create_candidate_checkpoint(kernel, contract, product_worktree)
            phases.append("acceptance")
            acceptance, _phase_projection = _execute_phase_operation(
                RunState("implemented", task_id),
                TypedOutcome("pass", task_id),
                lambda: _run_v4_acceptance(
                    contract, operations, product_worktree, run_dir, candidate
                ),
            )
        except (RuntimeError, ValueError) as exc:
            _block_task(kernel, task_id, "evidence_integrity_failure")
            phases.append("blocked")
            return finish("blocked", "blocked", str(exc))
        scope = _initial_review_scope(candidate)
        phase = _next_scheduler_phase("accepted", "pass", task_id)
    else:
        try:
            candidate = _candidate_from_state(kernel, task_id)
            acceptance, _phase_projection = _execute_phase_operation(
                RunState("implemented", task_id),
                TypedOutcome("pass", task_id),
                lambda: _run_v4_acceptance(
                    contract, operations, product_worktree, run_dir, candidate
                ),
            )
            records = [
                item
                for item in kernel.state.get("candidate_checkpoints", [])
                if item.get("task_id") == task_id
            ]
            if len(records) > 1:
                rejected = _candidate_from_state(kernel, task_id, -2)
                findings = _latest_findings(kernel, task_id)
                boundaries = tuple(
                    operations.repair_boundary_changes(contract, rejected, candidate)
                )
                scope = _repair_review_scope(
                    rejected, candidate, findings, boundaries
                )
            else:
                scope = _initial_review_scope(candidate)
        except (RuntimeError, ValueError) as exc:
            _block_task(kernel, task_id, "evidence_integrity_failure")
            phases.append("blocked")
            return finish("blocked", "blocked", str(exc))

    while True:
        if phase == "task_review":
            assert candidate is not None and acceptance is not None and scope is not None
            phases.append("task_review")
            scopes.append(scope)
            try:
                review_turn, _phase_projection = _execute_phase_operation(
                    RunState("accepted", task_id),
                    TypedOutcome("pass", task_id),
                    lambda: controller.run_model_turn(
                        task_id=task_id,
                        kind="task_review",
                        before_turn=operations.before_model_turn,
                        operation=lambda attempt_id: operations.review(
                            contract, scope, attempt_id
                        ),
                        preserve_attempt_on=(ExternalModelInterruption,),
                        on_turn_started=on_started("reviewing"),
                    ),
                )
                verdict = _bound_review_verdict(
                    _require_v4_worker_result(review_turn.result),
                    contract,
                    candidate,
                    scope,
                    kernel,
                )
                _record_v4_verdict(
                    kernel, task_id, review_turn.attempt_id, verdict
                )
            except PreTurnInterruption as exc:
                _wait_for_phase(kernel, task_id, "task_review", str(exc), None)
                phases.append("waiting_external")
                return finish("waiting_external", "waiting_external", str(exc))
            except ExternalModelInterruption as exc:
                return wait_after(
                    "task_review",
                    exc.root_cause_key,
                    str(getattr(candidate, "commit")),
                    "task_review",
                )
            except RuntimeUpgradeInterruption as exc:
                return wait_after(
                    "task_review",
                    exc.root_cause_key,
                    str(getattr(candidate, "commit")),
                    "task_review",
                )
            except (RuntimeError, ValueError) as exc:
                if not restore_or_block(str(getattr(candidate, "commit"))):
                    return finish("blocked", "blocked", "evidence_integrity_failure")
                reason = (
                    "evidence_integrity_failure"
                    if str(exc) == "review_privacy_unsafe"
                    else "review_evidence_invalid"
                )
                _block_task(kernel, task_id, reason)
                phases.append("blocked")
                return finish("blocked", "blocked", reason)

            status = str(verdict["status"])
            if status == "passed":
                try:
                    review_evidence = _approved_review_evidence(
                        contract, candidate, verdict, adjudication="review_passed"
                    )
                    _store_review_evidence(kernel, contract, review_evidence)
                except (RuntimeError, ValueError) as exc:
                    _block_task(kernel, task_id, "review_evidence_invalid")
                    phases.append("blocked")
                    return finish("blocked", "blocked", str(exc))
                phase = _next_scheduler_phase("reviewed", "pass", task_id)
                continue
            if status in {"blocked", "inconclusive"}:
                _block_task(kernel, task_id, status)
                phases.append("blocked")
                return finish("blocked", "blocked", status)

            findings = [
                dict(item)
                for item in verdict.get("findings", [])
                if isinstance(item, dict)
            ]
            if not findings:
                _block_task(kernel, task_id, "review_finding_invalid")
                phases.append("blocked")
                return finish("blocked", "blocked", "review_finding_invalid")
            decisions: list[tuple[dict[str, object], object]] = []
            try:
                roots = _v4_state(kernel).get("repair_roots", {})
                for finding in findings:
                    category = str(
                        finding.get("failure_category") or "product_defect"
                    )
                    root = str(
                        finding.get("root_cause_key") or f"{category}:{task_id}"
                    )
                    decision = classify_failure(
                        category,
                        root_cause_key=root,
                        release_impact=bool(
                            finding.get("release_impact", False)
                        ),
                        impact_class=(
                            str(finding["impact_class"])
                            if finding.get("impact_class") is not None
                            else None
                        ),
                        repair_roots=roots,
                    )
                    decisions.append((finding, decision))
            except (TypeError, ValueError) as exc:
                _block_task(kernel, task_id, "review_finding_invalid")
                phases.append("blocked")
                return finish("blocked", "blocked", str(exc))

            for finding, decision in decisions:
                if getattr(decision, "action") == "backlog_and_continue":
                    record_backlog(
                        kernel,
                        task_id=task_id,
                        category=getattr(decision, "category"),
                        root_cause_key=getattr(decision, "root_cause_key"),
                        finding=finding,
                    )
            blockers = [
                decision
                for _finding, decision in decisions
                if getattr(decision, "action") == "block_release"
            ]
            if blockers:
                _block_task(kernel, task_id, blockers[0].root_cause_key)
                phases.append("blocked")
                return finish("blocked", "blocked", blockers[0].root_cause_key)
            repairs = [
                (finding, decision)
                for finding, decision in decisions
                if getattr(decision, "action") == "repair"
            ]
            if repairs:
                finding, decision = repairs[0]
                if decision.repair_root_update is None:
                    _block_task(kernel, task_id, "repair_policy_invalid")
                    phases.append("blocked")
                    return finish("blocked", "blocked", "repair_policy_invalid")
                root, count = decision.repair_root_update
                try:
                    selected_repair = record_selected_repair(
                        kernel,
                        task_id=task_id,
                        contract_sha256=contract.contract_sha256,
                        rejected_candidate=candidate,
                        review_attempt_id=review_turn.attempt_id,
                        verdict=_recorded_v4_verdict(verdict),
                        finding=finding,
                        root_cause_key=root,
                        repair_count=count,
                        review_scope=review_scope_payload(scope),
                        review_scope_sha256=review_scope_sha256(scope),
                    )
                except (OSError, RuntimeError, ValueError):
                    _block_task(kernel, task_id, "evidence_integrity_failure")
                    phases.append("blocked")
                    return finish(
                        "blocked", "blocked", "evidence_integrity_failure"
                    )
                phase = _next_scheduler_phase(
                    "reviewed", "changes_requested", task_id
                )
                continue
            try:
                review_evidence = _approved_review_evidence(
                    contract,
                    candidate,
                    verdict,
                    adjudication="all_findings_backlogged",
                )
                _store_review_evidence(kernel, contract, review_evidence)
            except (RuntimeError, ValueError) as exc:
                _block_task(kernel, task_id, "review_evidence_invalid")
                phases.append("blocked")
                return finish("blocked", "blocked", str(exc))
            phase = _next_scheduler_phase("reviewed", "pass", task_id)
            continue

        if phase == "repair":
            assert candidate is not None
            rejected = candidate
            if selected_repair is None:
                try:
                    selected_repair = reopen_selected_repair(
                        kernel,
                        task_id=task_id,
                        contract_sha256=contract.contract_sha256,
                        rejected_candidate=rejected,
                        review_scope=review_scope_payload(scope),
                        review_scope_sha256=review_scope_sha256(scope),
                    )
                except (OSError, RuntimeError, ValueError):
                    _block_task(kernel, task_id, "evidence_integrity_failure")
                    phases.append("blocked")
                    return finish(
                        "blocked", "blocked", "evidence_integrity_failure"
                    )
            finding = dict(selected_repair["finding"])
            root = str(selected_repair["root_cause_key"])
            count = int(selected_repair["repair_count"])
            phases.append("repair")
            try:
                repair_turn, _phase_projection = _execute_phase_operation(
                    RunState("reviewed", task_id),
                    TypedOutcome("changes_requested", task_id),
                    lambda: controller.run_model_turn(
                        task_id=task_id,
                        kind="repair",
                        before_turn=operations.before_model_turn,
                        operation=lambda attempt_id: operations.repair(
                            contract, finding, attempt_id
                        ),
                        preserve_attempt_on=(ExternalModelInterruption,),
                        on_turn_started=on_started("repairing", (root, count)),
                    ),
                )
            except PreTurnInterruption as exc:
                _wait_for_phase(kernel, task_id, "repair", str(exc), None)
                phases.append("waiting_external")
                return finish("waiting_external", "waiting_external", str(exc))
            except ExternalModelInterruption as exc:
                return wait_after(
                    "repair", exc.root_cause_key, rejected.commit, "repair"
                )
            except RuntimeUpgradeInterruption as exc:
                return wait_after(
                    "repair", exc.root_cause_key, rejected.commit, "repair"
                )
            except (RuntimeError, ValueError) as exc:
                if not restore_or_block(rejected.commit):
                    return finish("blocked", "blocked", "evidence_integrity_failure")
                _block_task(kernel, task_id, "repair_failed")
                phases.append("blocked")
                return finish("blocked", "blocked", str(exc))
            try:
                repaired = _require_v4_worker_result(repair_turn.result)
                _verify_v4_method_evidence(
                    run_dir, contract, operations.packet_sha256, repaired
                )
                _attach_v4_method_evidence(
                    kernel, task_id, repair_turn.attempt_id, repaired
                )
            except (RuntimeError, ValueError) as exc:
                if not restore_or_block(rejected.commit):
                    return finish("blocked", "blocked", "evidence_integrity_failure")
                _block_task(kernel, task_id, "method_contract_failed")
                phases.append("blocked")
                return finish("blocked", "blocked", str(exc))
            try:
                prepare_repaired_candidate(product_worktree, rejected)
                phases.append("candidate")
                candidate = create_candidate_checkpoint(
                    kernel, contract, product_worktree
                )
                phases.append("acceptance")
                acceptance, _phase_projection = _execute_phase_operation(
                    RunState("implemented", task_id),
                    TypedOutcome("pass", task_id),
                    lambda: _run_v4_acceptance(
                        contract, operations, product_worktree, run_dir, candidate
                    ),
                )
                boundaries = tuple(
                    operations.repair_boundary_changes(
                        contract, rejected, candidate
                    )
                )
                scope = _repair_review_scope(
                    rejected,
                    candidate,
                    tuple(_latest_findings(kernel, task_id)),
                    boundaries,
                )
                _task_transition(kernel, task_id, "reviewing")
                resolve_selected_repair(
                    kernel,
                    task_id=task_id,
                    selected_repair_ref=dict(
                        selected_repair["selected_repair_ref"]
                    ),
                )
            except (RuntimeError, ValueError) as exc:
                _block_task(kernel, task_id, "evidence_integrity_failure")
                phases.append("blocked")
                return finish("blocked", "blocked", str(exc))
            selected_repair = None
            phase = _next_scheduler_phase("accepted", "pass", task_id)
            continue

        if phase == "verification":
            assert candidate is not None and acceptance is not None
            if review_evidence is None:
                try:
                    review_evidence = _load_review_evidence(
                        kernel, contract, candidate
                    )
                except ValueError:
                    _block_task(kernel, task_id, "review_evidence_missing")
                    phases.append("blocked")
                    return finish("blocked", "blocked", "review_evidence_missing")
            phases.append("verification")
            current = kernel.state["tasks"][task_id]["status"]
            if current != "verifying" and current not in {
                "waiting_external",
                "waiting_user",
            }:
                _task_transition(kernel, task_id, "verifying")
            try:
                verification_result, _phase_projection = _execute_phase_operation(
                    RunState("reviewed", task_id),
                    TypedOutcome("pass", task_id),
                    lambda: operations.deterministic_verification(
                        contract, candidate, acceptance, review_evidence
                    ),
                )
                deterministic_passed, deterministic_summary = verification_result
                if (
                    deterministic_passed is not True
                    or not isinstance(deterministic_summary, str)
                ):
                    raise ValueError("deterministic_verification_failed")
                _deterministic_evidence(
                    kernel,
                    contract,
                    candidate,
                    review_evidence,
                    deterministic_summary,
                )
            except Exception:
                if not restore_or_block(candidate.commit):
                    return finish("blocked", "blocked", "evidence_integrity_failure")
                _block_task(kernel, task_id, "evidence_integrity_failure")
                phases.append("blocked")
                return finish("blocked", "blocked", "evidence_integrity_failure")

            if "semantic_verification" in contract.required_evidence:
                if operations.semantic_verification is None:
                    _block_task(kernel, task_id, "semantic_verification_missing")
                    phases.append("blocked")
                    return finish("blocked", "blocked", "semantic_verification_missing")
                try:
                    semantic_turn = controller.run_model_turn(
                        task_id=task_id,
                        kind="verification",
                        before_turn=operations.before_model_turn,
                        operation=lambda attempt_id: operations.semantic_verification(
                            contract, candidate, acceptance, attempt_id
                        ),
                        preserve_attempt_on=(ExternalModelInterruption,),
                        on_turn_started=on_started("verifying"),
                    )
                    semantic_verdict = _review_verdict(
                        _require_v4_worker_result(semantic_turn.result)
                    )
                    _record_v4_verdict(
                        kernel,
                        task_id,
                        semantic_turn.attempt_id,
                        semantic_verdict,
                    )
                    if semantic_verdict["status"] != "passed":
                        raise ValueError("semantic_verification_failed")
                except PreTurnInterruption as exc:
                    _wait_for_phase(
                        kernel, task_id, "verification", str(exc), None
                    )
                    phases.append("waiting_external")
                    return finish(
                        "waiting_external", "waiting_external", str(exc)
                    )
                except ExternalModelInterruption as exc:
                    return wait_after(
                        "verification",
                        exc.root_cause_key,
                        candidate.commit,
                        "verification",
                    )
                except RuntimeUpgradeInterruption as exc:
                    return wait_after(
                        "verification",
                        exc.root_cause_key,
                        candidate.commit,
                        "verification",
                    )
                except (RuntimeError, ValueError) as exc:
                    if not restore_or_block(candidate.commit):
                        return finish(
                            "blocked", "blocked", "evidence_integrity_failure"
                        )
                    _block_task(kernel, task_id, "semantic_verification_failed")
                    phases.append("blocked")
                    return finish("blocked", "blocked", str(exc))
            try:
                promote_verified_checkpoint(
                    kernel, contract, candidate, acceptance, review_evidence
                )
                _task_transition(kernel, task_id, "completed")
            except (RuntimeError, ValueError) as exc:
                _block_task(kernel, task_id, "evidence_integrity_failure")
                phases.append("blocked")
                return finish("blocked", "blocked", str(exc))
            phases.append("verified_checkpoint")
            return finish("completed", "verified_checkpoint")


def run_tasks_v4(
    contracts: tuple[object, ...],
    operations: Mapping[str, LifecycleOperations],
    kernel: Kernel,
    product_worktree: Path,
    run_dir: Path,
) -> tuple[TaskCycleResult, ...]:
    """Run dependency-ordered v4 tasks, resuming after verified checkpoints."""

    from .task_contracts import TaskContractV4

    typed = [item for item in contracts if isinstance(item, TaskContractV4)]
    if len(typed) != len(contracts) or len({item.task_id for item in typed}) != len(typed):
        raise ValueError("task_contract_set_invalid")
    by_id = {item.task_id: item for item in typed}
    ordered: list[TaskContractV4] = []
    remaining = dict(by_id)
    while remaining:
        ready = sorted(
            task_id
            for task_id, item in remaining.items()
            if all(dependency in {task.task_id for task in ordered} for dependency in item.dependencies)
        )
        if not ready:
            raise ValueError("task_contract_dependency_invalid")
        for task_id in ready:
            ordered.append(remaining.pop(task_id))

    results: list[TaskCycleResult] = []
    externally_waiting: set[str] = set()
    awaiting_user: set[str] = {
        task_id
        for task_id, task in kernel.state.get("tasks", {}).items()
        if isinstance(task, dict) and task.get("status") == "waiting_user"
    }
    for contract in ordered:
        if any(
            kernel.state.get("tasks", {}).get(dependency, {}).get("status")
            != "completed"
            for dependency in contract.dependencies
        ):
            continue
        if set(contract.dependencies).intersection(externally_waiting | awaiting_user):
            continue
        if contract.task_id in awaiting_user:
            continue
        if any(
            item.get("task_id") == contract.task_id
            and item.get("contract_sha256") == contract.contract_sha256
            for item in kernel.state.get("verified_checkpoints", [])
        ):
            continue
        lifecycle = operations.get(contract.task_id)
        if lifecycle is None:
            raise ValueError(f"task_operations_missing:{contract.task_id}")
        result = run_task_cycle_v4(
            contract, lifecycle, kernel, product_worktree, run_dir
        )
        results.append(result)
        if result.status == "waiting_external":
            externally_waiting.add(contract.task_id)
            continue
        if result.status != "completed":
            break
    return tuple(results)


def run_repository_checks(manifest: dict, revision: int) -> tuple[EvidenceRef, ...]:
    runtime_run_dir = manifest.get("_runtime_run_dir")
    if not isinstance(runtime_run_dir, str) or not runtime_run_dir:
        raise ValueError("repository checks require runtime run directory")
    kernel = Kernel(resolve_ref(runtime_run_dir))
    if kernel.state["worktree_revision"] != revision:
        raise ValueError("repository checks revision is stale")
    worktree = resolve_ref(str(manifest["execution_worktree_ref"]))
    commands = list(
        dict.fromkeys(
            str(task.get("acceptance_command") or "").strip()
            for task in manifest.get("task_graph") or []
            if str(task.get("acceptance_command") or "").strip()
        )
    )
    results: list[dict[str, object]] = []
    command_failure: dict[str, object] | None = None
    for command in commands:
        command_result = _guarded_shell(command, worktree, 900)
        results.append(command_result)
        if command_result.get("returncode") != 0:
            command_failure = command_result
            break
    bundle_passed = bool(commands) and all(item["returncode"] == 0 for item in results)
    refs: list[EvidenceRef] = []
    for ordinal, task in enumerate(_topological(list(manifest.get("task_graph") or [])), 1):
        task_id = str(task["id"])
        attempt_id = f"run.repository_checks.{revision}.{ordinal}"
        payload = {
            "kind": "repository_check",
            "task_id": task_id,
            "attempt_id": attempt_id,
            "status": "passed" if bundle_passed else "changes_requested",
            "passed": bundle_passed,
            "findings": [] if bundle_passed else [{"severity": "critical", "summary": "repository command failed", "action": "repair repository check"}],
            "missing_evidence": [],
            "commands": commands,
            "results": results,
            **_binding(kernel, task_id),
        }
        ref = _put_json(kernel.run_dir, "repository_check", payload)
        kernel.transition(
            Transition(
                "evidence.attached",
                {"kind": "repository_check", "ref": ref.as_dict()},
                task_id=task_id,
                attempt_id=attempt_id,
            )
        )
        refs.append(ref)
    if command_failure is not None:
        owner_task = str((manifest.get("task_graph") or [{}])[0].get("id") or "")
        category = str(command_failure.get("failure_category") or "repository_check_failed")
        _block(
            kernel,
            owner_task,
            "repository_checks",
            category,
            category=category,
            root_cause_key=str(
                command_failure.get("root_cause_key") or "repository_checks:command_failed"
            ),
            evidence_refs=[ref.as_dict() for ref in refs],
        )
    return tuple(refs)


def run_final_reviews(
    tasks: list[dict],
    worker: Worker,
    kernel: Kernel,
    worktree: Path,
) -> list[WorkerResult]:
    controller = AttemptController(kernel, worktree, worker)
    results: list[WorkerResult] = []
    for task in _topological(tasks):
        task_id = str(task["id"])
        result, _, attempt_id = _worker_attempt(
            controller,
            kernel,
            None,
            "final_review",
            f"Review the complete diff for cross-task regressions using task packet {task_id}.",
            packet_task_id=task_id,
        )
        _semantic_verdict(kernel, task_id, attempt_id, "final_review", result)
        results.append(result)
    return results


def _current_completion_records(kernel: Kernel) -> tuple[list[dict], list[dict]]:
    state = kernel.state
    manifest = load_verified_manifest(kernel.run_dir / "run_manifest.json")
    checklist: list[dict] = []
    refs: list[dict] = []
    for item in state.get("artifact_index", []):
        if item.get("kind") not in COMPLETION_EVIDENCE_KINDS:
            continue
        ref = item.get("ref")
        if not isinstance(ref, dict):
            continue
        try:
            payload = json.loads((kernel.run_dir / str(ref["path"])).read_text(encoding="utf-8"))
        except (KeyError, OSError, json.JSONDecodeError):
            continue
        packet_task_id = str(payload.get("packet_task_id") or item.get("task_id") or "")
        try:
            expected_packet = packet_entry(manifest, packet_task_id)["sha256"]
        except ValueError:
            continue
        if (
            payload.get("worktree_revision") != state["worktree_revision"]
            or payload.get("worktree_patch_sha256") != state["worktree_patch_sha256"]
            or payload.get("packet_sha256") != expected_packet
        ):
            continue
        checklist.append({"kind": item["kind"], "task_id": item.get("task_id"), "ref": ref})
        refs.append(ref)
    return checklist, refs


def _initialize_task(
    kernel: Kernel,
    task: dict,
    controller: AttemptController,
) -> None:
    task_id = str(task["id"])
    state = kernel.state
    dependencies = [str(item) for item in task.get("dependencies") or []]
    if any(state["tasks"].get(item, {}).get("status") != "completed" for item in dependencies):
        raise ValueError("dependency_not_completed")
    current = state["tasks"][task_id]["status"]
    if current == "pending":
        kernel.transition(
            Transition("task.status_changed", {"from": "pending", "to": "ready"}, task_id=task_id)
        )
        current = "ready"
    scouts = list(task.get("scout_prompts") or [])
    if scouts:
        kernel.transition(
            Transition("task.status_changed", {"from": current, "to": "scouting"}, task_id=task_id)
        )
        manifest = load_verified_manifest(kernel.run_dir / "run_manifest.json")
        base = _next_ordinal(kernel, task_id, "scout")
        requests = [
            make_packet_request(
                kernel.run_dir,
                manifest,
                task_id,
                f"{task_id}.scout.{base + index}",
                "scout",
                str(prompt),
                controller.worktree,
            )
            for index, prompt in enumerate(scouts)
        ]
        for request in requests:
            _start_attempt(kernel, task_id, "scout", request.attempt_id)
        if controller.worker is None:
            raise ValueError("scout_failed_or_unattested")
        for request, result in zip(requests, run_scouts(requests, controller.worker)):
            _complete_attempt(
                kernel,
                task_id,
                task_id,
                "scout",
                result,
                request.attempt_id,
            )
            if result.status != "completed" or not result.attestation.get("verified"):
                raise ValueError("scout_failed_or_unattested")
        current = "scouting"
    kernel.transition(
        Transition("task.status_changed", {"from": current, "to": "implementing"}, task_id=task_id)
    )


def _cycle_block_result(kernel: Kernel, cycle: TaskCycleResult) -> dict:
    result = {
        "completed": [
            key for key, value in kernel.state["tasks"].items() if value["status"] == "completed"
        ],
        "blocked": cycle.task_id,
        "status": "blocked",
        "reason": cycle.reason,
        "phase": cycle.phase,
    }
    if cycle.reason == "policy_violation":
        blockers = [
            item
            for item in kernel.state.get("active_blockers", [])
            if item.get("task_id") == cycle.task_id
            and item.get("category") == "policy_violation"
        ]
        if blockers:
            result.update(
                failure_category="policy_violation",
                root_cause_key=blockers[-1].get("root_cause_key"),
                scope_errors=list(blockers[-1].get("scope_errors") or []),
            )
    return result


def _map_final_findings(findings: object, known: set[str]) -> list[str] | None:
    if not isinstance(findings, list) or not findings:
        return None
    mapped: list[str] = []
    identifier_keys = ("task_id", "affected_task_id", "target_task_id", "packet_task_id")
    for finding in findings:
        if not isinstance(finding, dict):
            return None
        identifiers: list[str] = []
        for key in identifier_keys:
            if key not in finding:
                continue
            value = finding.get(key)
            if not isinstance(value, str) or not value:
                return None
            identifiers.append(value)
        if "task_ids" in finding:
            values = finding.get("task_ids")
            if (
                not isinstance(values, list)
                or not values
                or any(not isinstance(value, str) or not value for value in values)
            ):
                return None
            identifiers.extend(values)
        unique = set(identifiers)
        if len(unique) != 1:
            return None
        task_id = next(iter(unique))
        if task_id not in known:
            return None
        mapped.append(task_id)
    return mapped


def run_tasks(tasks: list[dict], worker: Worker, kernel_or_run_dir: Kernel | Path) -> dict:
    kernel = kernel_or_run_dir if isinstance(kernel_or_run_dir, Kernel) else Kernel(kernel_or_run_dir)
    manifest = load_verified_manifest(kernel.run_dir / "run_manifest.json")
    if tasks != list(manifest.get("task_graph") or []):
        raise ValueError("task_graph_mismatch")
    worktree = resolve_ref(str(manifest["execution_worktree_ref"]))
    if worktree.resolve() == kernel.run_dir.resolve():
        raise ValueError("run directory must never be used as execution worktree")
    if kernel.state["lifecycle"] == "created":
        kernel.transition(Transition("run.status_changed", {"from": "created", "to": "ready"}))
    if kernel.state["lifecycle"] == "ready":
        kernel.transition(Transition("run.status_changed", {"from": "ready", "to": "running"}))
    elif kernel.state["lifecycle"] != "running":
        return {"completed": [], "blocked": None, "status": kernel.state["lifecycle"]}

    ordered = _topological(tasks)
    controller = AttemptController(kernel, worktree, worker)
    cycle_revisions: dict[str, int] = {}
    for task in ordered:
        task_id = str(task["id"])
        if kernel.state["tasks"][task_id]["status"] != "completed":
            dependencies = [str(item) for item in task.get("dependencies") or []]
            if any(
                kernel.state["tasks"].get(item, {}).get("status") != "completed"
                for item in dependencies
            ):
                return _block(
                    kernel,
                    task_id,
                    "dependency",
                    "dependency_not_completed",
                    category="dependency_not_completed",
                )
            status = kernel.state["tasks"][task_id]["status"]
            if status in {"pending", "ready"}:
                try:
                    _initialize_task(kernel, task, controller)
                except ValueError as exc:
                    return _block(kernel, task_id, "initialization", str(exc))
            elif status == "scouting":
                kernel.transition(
                    Transition(
                        "task.status_changed",
                        {"from": "scouting", "to": "implementing"},
                        task_id=task_id,
                    )
                )
            elif status not in {"implementing", "reviewing", "verifying", "repairing"}:
                return _block(
                    kernel,
                    task_id,
                    "resume",
                    f"task_not_runnable:{status}",
                    category="resume_state_invalid",
                )
            cycle = run_task_cycle(task, controller, kernel)
            if cycle.status != "passed":
                return _cycle_block_result(kernel, cycle)
            cycle_revisions[task_id] = cycle.worktree_revision
        else:
            cycle_revisions[task_id] = -1

    final_repair_counts: dict[str, int] = {}
    while True:
        final_revision = int(kernel.state["worktree_revision"])
        stabilization_limit = max(4, len(ordered) * 4)
        converged = False
        for _stabilization_pass in range(stabilization_limit):
            for task in ordered:
                task_id = str(task["id"])
                current_revision = int(kernel.state["worktree_revision"])
                if cycle_revisions.get(task_id) != current_revision:
                    refreshed = run_task_cycle(task, controller, kernel)
                    if refreshed.status != "passed":
                        return _cycle_block_result(kernel, refreshed)
                    cycle_revisions[task_id] = refreshed.worktree_revision
            final_revision = int(kernel.state["worktree_revision"])
            if all(
                cycle_revisions.get(str(task["id"])) == final_revision
                for task in ordered
            ):
                converged = True
                break
        if not converged:
            task_id = str(ordered[0]["id"])
            return _block(
                kernel,
                task_id,
                "stabilization",
                "current_revision_evidence_did_not_converge",
                category="scheduler_nonconvergence",
                root_cause_key="current_revision_evidence_did_not_converge",
                resume_condition="bound repeated repair writes and schedule an explicit retry",
            )

        runtime_manifest = dict(manifest)
        runtime_manifest["_runtime_run_dir"] = str(kernel.run_dir)
        run_repository_checks(runtime_manifest, final_revision)
        if kernel.state["lifecycle"] == "blocked":
            blocker = kernel.state["active_blockers"][-1]
            return {
                "completed": [
                    key for key, value in kernel.state["tasks"].items()
                    if value["status"] == "completed"
                ],
                "blocked": blocker.get("task_id"),
                "status": "blocked",
                "reason": blocker.get("category"),
                "phase": "repository_checks",
            }
        repository_report = validate_completion(kernel.run_dir)
        if "current_revision_repository_check_missing" in repository_report.errors:
            return _block(kernel, str(ordered[0]["id"]), "repository_checks", "repository_checks_failed")

        reviews = run_final_reviews(ordered, worker, kernel, worktree)
        repair_task_ids: list[str] = []
        for task, result in zip(ordered, reviews):
            task_id = str(task["id"])
            verdict = result.payload.get("verdict")
            if result.status != "completed" or not _trusted(result) or not isinstance(verdict, dict):
                verdict_attempt = next(
                    (
                        attempt for attempt in reversed(kernel.state["attempts"])
                        if attempt.get("task_id") is None
                        and attempt.get("kind") == "final_review"
                        and attempt.get("status") != "started"
                    ),
                    {},
                )
                category = str(result.payload.get("failure_category") or "final_review_failed")
                return _block(
                    kernel,
                    task_id,
                    "final_review",
                    category,
                    category=category,
                    root_cause_key=str(
                        result.payload.get("root_cause_key") or "final_review:worker_failed"
                    ),
                    evidence_refs=list(verdict_attempt.get("evidence_refs") or []),
                )
            route = route_verdict(verdict)
            if route in {"blocked", "inconclusive"}:
                attempt_id = next(
                    item["attempt_id"]
                    for item in reversed(kernel.state["verdicts"])
                    if item.get("task_id") is None
                    and item.get("packet_task_id") == task_id
                )
                blocked = _verdict_block(kernel, task_id, "final_review", attempt_id, verdict)
                return {
                    "completed": [key for key, value in kernel.state["tasks"].items() if value["status"] == "completed"],
                    "blocked": task_id,
                    "status": "blocked",
                    "reason": blocked.reason,
                    "phase": blocked.phase,
                }
            if route == "repair":
                findings = verdict.get("findings") or []
                known = {str(item["id"]) for item in ordered}
                named = _map_final_findings(findings, known)
                if named is None:
                    return _block(
                        kernel,
                        task_id,
                        "final_review",
                        "final_review_finding_task_invalid",
                        category="final_review_mapping_invalid",
                        root_cause_key="final_review:ambiguous_finding_task",
                    )
                repair_task_ids.extend(named)

        if not repair_task_ids:
            checklist, evidence = _current_completion_records(kernel)
            audit = {
                "passed": True,
                "prompt_to_artifact_checklist": checklist,
                "verification_evidence": evidence,
                "residual_risk": ["paid live migration gate pending"],
            }
            kernel.transition(Transition("completion.recorded", audit))
            pre_terminal = validate_completion(kernel.run_dir)
            if not pre_terminal.passed:
                raise ValueError(f"completion validation failed: {','.join(pre_terminal.errors)}")
            kernel.transition(Transition("run.status_changed", {"from": "running", "to": "completed"}))
            final_report = validate_completion(kernel.run_dir)
            if not final_report.passed:
                raise ValueError(f"terminal completion validation failed: {','.join(final_report.errors)}")
            return {
                "completed": [str(task["id"]) for task in ordered],
                "blocked": None,
                "status": "completed",
            }

        before_revision = int(kernel.state["worktree_revision"])
        for task_id in dict.fromkeys(repair_task_ids):
            root_key = f"final_review:{task_id}"
            final_repair_counts[root_key] = final_repair_counts.get(root_key, 0) + 1
            if final_repair_counts[root_key] > 2:
                return _block(kernel, task_id, "final_review", f"repair_limit_exhausted:{root_key}")
            task = next(item for item in ordered if str(item["id"]) == task_id)
            blocked = _repair(
                task,
                controller,
                kernel,
                root_key,
                preserve_completed=True,
            )
            if blocked is not None:
                return {
                    "completed": [key for key, value in kernel.state["tasks"].items() if value["status"] == "completed"],
                    "blocked": task_id,
                    "status": "blocked",
                    "reason": blocked.reason,
                    "phase": blocked.phase,
                }
        if int(kernel.state["worktree_revision"]) == before_revision:
            return _block(kernel, repair_task_ids[0], "final_review", "final_review_repair_did_not_advance_revision")
        cycle_revisions = {str(task["id"]): -1 for task in ordered}
