from __future__ import annotations

import hashlib
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from .attempt_controller import (
    ROLE_POLICIES,
    AttemptController,
    WriteAttemptOutcome,
    canonical_role,
    validate_verdict,
)
from .evidence import EvidenceRef, put_json
from .events import read_events
from .kernel import Kernel, Transition
from .manifest import load_verified_manifest, resolve_ref
from .model_policy import CORE_ROUTE
from .packets import packet_entry, verify_packet
from .validation import COMPLETION_EVIDENCE_KINDS, validate_completion
from .worker import Worker, WorkerError, WorkerRequest, WorkerResult


@dataclass(frozen=True)
class TaskCycleResult:
    task_id: str
    status: str
    phase: str
    worktree_revision: int
    reason: str | None = None


def next_phase(state: dict, task_id: str) -> str:
    tasks = state.get("tasks")
    if not isinstance(tasks, dict) or task_id not in tasks:
        raise ValueError("unknown task")
    status = tasks[task_id].get("status")
    phases = {
        "pending": "implementation",
        "ready": "implementation",
        "scouting": "implementation",
        "implementing": "implementation",
        "reviewing": "acceptance",
        "verifying": "verification",
        "repairing": "repair",
        "completed": "repository_checks",
    }
    if status not in phases:
        raise ValueError(f"unknown or non-runnable task state: {status}")
    return phases[status]


def route_verdict(verdict: object) -> str:
    status = verdict.get("status") if isinstance(verdict, dict) else verdict
    routes = {
        "passed": "continue",
        "changes_requested": "repair",
        "blocked": "blocked",
        "inconclusive": "inconclusive",
    }
    if status not in routes:
        raise ValueError(f"unknown verdict: {status}")
    return routes[str(status)]


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
        packet_path=entry["path"],
        packet_sha256=entry["sha256"],
        worktree_revision=int(state["worktree_revision"]),
    )
    return WorkerRequest(**{**request.__dict__, "prompt": packet_prompt(request, instruction)})


def packet_prompt(request: WorkerRequest, instruction: str) -> str:
    return json.dumps(
        {
            "task_id": request.task_id,
            "packet_path": request.packet_path,
            "packet_sha256": request.packet_sha256,
            "worktree_revision": request.worktree_revision,
            "instruction": instruction,
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def run_scouts(requests: list[WorkerRequest], worker: Worker) -> list[WorkerResult]:
    if not requests:
        return []
    for request in requests:
        if not request.read_only or request.verdict_capable or request.attempt_kind != "scout":
            raise ValueError("unsafe scout request")

    def run_one(request: WorkerRequest) -> WorkerResult:
        try:
            return worker.run(request)
        except WorkerError as exc:
            return _worker_error_result(exc, "transient")

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


def _worker_error_result(error: Exception, category: str) -> WorkerResult:
    message = f"{type(error).__name__}: {error}"[:2000]
    payload = {
        "status": "failed",
        "summary": message,
        "changed_files": [],
        "findings": [],
        "evidence_refs": [],
        "missing_evidence": [message],
        "verification": [],
        "verdict": None,
        "failure_category": category,
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
    ref = put_json(kernel.run_dir, kind, payload)
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
        result = invoke()
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
) -> tuple[bool, dict]:
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
        try:
            result = subprocess.run(
                ["/bin/sh", "-lc", command],
                cwd=controller.worktree,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=600,
            )
            result_payload = {
                "command": command,
                "returncode": result.returncode,
                "output": result.stdout[-8000:],
            }
        except (subprocess.TimeoutExpired, OSError) as exc:
            result_payload = {"command": command, "returncode": 124, "output": str(exc)}
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
    _attach(kernel, task_id, attempt_id, "acceptance", payload)
    return passed, payload


def _block(kernel: Kernel, task_id: str, phase: str, reason: str) -> dict:
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
    kernel.transition(
        Transition(
            "blocker.opened",
            {
                "blocker_id": f"{task_id}.policy.{outcome.worktree_revision}",
                "category": "policy_violation",
                "root_cause_key": root_cause_key,
                "owner": "cpe",
                "resume_condition": "restore task scope and schedule an explicit retry",
                "scope_errors": list(outcome.scope_errors),
            },
            task_id=task_id,
        )
    )
    result = _block(kernel, task_id, phase, "policy_violation")
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
    kernel.transition(
        Transition(
            "blocker.opened",
            {
                "blocker_id": f"{task_id}.{status}.{attempt_id}",
                "category": status,
                "root_cause_key": f"{phase}:{status}",
                "owner": str(verdict.get("owner") or "cpe"),
                "resume_condition": str(
                    verdict.get("resume_condition")
                    or verdict.get("next_evidence_action")
                    or "satisfy the typed verdict and schedule an explicit retry"
                ),
                "evidence_refs": list(verdict.get("evidence_refs") or []),
            },
            task_id=task_id,
        )
    )
    _block(kernel, task_id, phase, f"{phase}_verdict:{status}")
    return TaskCycleResult(task_id, "blocked", phase, int(binding["worktree_revision"]), status)


def _repair(
    task: dict,
    controller: AttemptController,
    kernel: Kernel,
    root_key: str,
    *,
    preserve_completed: bool,
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
    repair, outcome, _ = _worker_attempt(
        controller,
        kernel,
        task,
        "repair",
        f"Repair {task_id} root cause {root_key}; remain inside file claims.",
    )
    if outcome is not None and outcome.scope_errors:
        _scope_block(kernel, task_id, "repair", outcome)
        return TaskCycleResult(task_id, "blocked", "repair", outcome.worktree_revision, "policy_violation")
    if repair.status != "completed" or not _trusted(repair):
        _block(kernel, task_id, "repair", f"repair_failed:{root_key}")
        return TaskCycleResult(task_id, "blocked", "repair", kernel.state["worktree_revision"], root_key)
    if outcome is None or (not outcome.delta.changed_files and not outcome.delta.head_changed):
        _block(kernel, task_id, "repair", f"repair_did_not_advance_revision:{root_key}")
        return TaskCycleResult(task_id, "blocked", "repair", kernel.state["worktree_revision"], root_key)
    if not preserve_completed:
        kernel.transition(
            Transition(
                "task.status_changed",
                {"from": "repairing", "to": "reviewing"},
                task_id=task_id,
            )
        )
    return None


def run_task_cycle(task: dict, controller: AttemptController, kernel: Kernel) -> TaskCycleResult:
    task_id = str(task["id"])
    if task_id not in kernel.state.get("tasks", {}):
        raise ValueError("unknown task")
    preserve_completed = kernel.state["tasks"][task_id]["status"] == "completed"
    if not preserve_completed:
        phase = next_phase(kernel.state, task_id)
        if phase != "implementation":
            raise ValueError(f"task cycle cannot start from phase {phase}")
        implementation, outcome, _ = _worker_attempt(
            controller,
            kernel,
            task,
            "implementation",
            f"Implement task {task_id} using only its verified packet and current revision.",
        )
        if outcome is not None and outcome.scope_errors:
            _scope_block(kernel, task_id, "implementation", outcome)
            return TaskCycleResult(task_id, "blocked", "implementation", outcome.worktree_revision, "policy_violation")
        if implementation.status != "completed" or not _trusted(implementation):
            _block(kernel, task_id, "implementation", "implementation_or_attestation_failed")
            return TaskCycleResult(task_id, "blocked", "implementation", kernel.state["worktree_revision"], "implementation failed")
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

    repair_counts: dict[str, int] = {}
    while True:
        acceptance_ok, acceptance = _acceptance(task, controller, kernel)
        if not acceptance_ok:
            root_key = f"acceptance:{acceptance['returncode']}"
            phase = "acceptance"
        else:
            review, _, review_attempt = _worker_attempt(
                controller,
                kernel,
                task,
                "task_review",
                f"Review task {task_id} against its packet, acceptance, and current diff.",
            )
            _semantic_verdict(kernel, task_id, review_attempt, "task_review", review)
            review_verdict = review.payload.get("verdict")
            if review.status != "completed" or not _trusted(review) or not isinstance(review_verdict, dict):
                root_key = "task_review:worker_failed"
                phase = "task_review"
            else:
                route = route_verdict(review_verdict)
                if route in {"blocked", "inconclusive"}:
                    return _verdict_block(kernel, task_id, "task_review", review_attempt, review_verdict)
                if route == "repair":
                    root_key = str(review.payload.get("root_cause_key") or "task_review:changes_requested")
                    phase = "task_review"
                else:
                    if not preserve_completed and kernel.state["tasks"][task_id]["status"] == "reviewing":
                        kernel.transition(
                            Transition(
                                "task.status_changed",
                                {"from": "reviewing", "to": "verifying"},
                                task_id=task_id,
                            )
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
                        root_key = "verification:worker_failed"
                        phase = "verification"
                    else:
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
                        phase = "verification"

        repair_counts[root_key] = repair_counts.get(root_key, 0) + 1
        if repair_counts[root_key] > 2:
            _block(kernel, task_id, phase, f"repair_limit_exhausted:{root_key}")
            return TaskCycleResult(
                task_id,
                "blocked",
                phase,
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
    for command in commands:
        try:
            completed = subprocess.run(
                ["/bin/sh", "-lc", command],
                cwd=worktree,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=900,
            )
            results.append(
                {
                    "command": command,
                    "returncode": completed.returncode,
                    "output": completed.stdout[-8000:],
                }
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            results.append({"command": command, "returncode": 124, "output": str(exc)})
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
        ref = put_json(kernel.run_dir, "repository_check", payload)
        kernel.transition(
            Transition(
                "evidence.attached",
                {"kind": "repository_check", "ref": ref.as_dict()},
                task_id=task_id,
                attempt_id=attempt_id,
            )
        )
        refs.append(ref)
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
            try:
                _initialize_task(kernel, task, controller)
            except ValueError as exc:
                return _block(kernel, task_id, "dependency", str(exc))
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
            kernel.transition(
                Transition(
                    "blocker.opened",
                    {
                        "blocker_id": f"run.scheduler_nonconvergence.{final_revision}",
                        "category": "scheduler_nonconvergence",
                        "root_cause_key": "current_revision_evidence_did_not_converge",
                        "owner": "cpe",
                        "resume_condition": "bound repeated repair writes and schedule an explicit retry",
                    },
                    task_id=task_id,
                )
            )
            return _block(
                kernel,
                task_id,
                "stabilization",
                "current_revision_evidence_did_not_converge",
            )

        runtime_manifest = dict(manifest)
        runtime_manifest["_runtime_run_dir"] = str(kernel.run_dir)
        run_repository_checks(runtime_manifest, final_revision)
        repository_report = validate_completion(kernel.run_dir)
        if "current_revision_repository_check_missing" in repository_report.errors:
            return _block(kernel, str(ordered[0]["id"]), "repository_checks", "repository_checks_failed")

        reviews = run_final_reviews(ordered, worker, kernel, worktree)
        repair_task_ids: list[str] = []
        for task, result in zip(ordered, reviews):
            task_id = str(task["id"])
            verdict = result.payload.get("verdict")
            if result.status != "completed" or not _trusted(result) or not isinstance(verdict, dict):
                return _block(kernel, task_id, "final_review", "final_review_failed")
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
                named = [
                    str(finding.get("task_id"))
                    for finding in findings
                    if isinstance(finding, dict) and finding.get("task_id") is not None
                ]
                known = {str(item["id"]) for item in ordered}
                if not named or any(item not in known for item in named):
                    return _block(kernel, task_id, "final_review", "final_review_finding_task_invalid")
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
