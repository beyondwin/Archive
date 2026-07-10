from __future__ import annotations

import hashlib
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .attempt_controller import (
    ROLE_POLICIES,
    AttemptController,
    WriteAttemptOutcome,
    canonical_role,
    validate_verdict,
)
from .evidence import put_json
from .kernel import Kernel, Transition
from .manifest import load_verified_manifest, resolve_ref
from .model_policy import CORE_ROUTE
from .packets import packet_entry, verify_packet
from .projector import project
from .events import read_events
from .worker import Worker, WorkerError, WorkerRequest, WorkerResult

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
    revision = project(manifest, read_events(run_dir / "events.jsonl"))["worktree_revision"]
    role = canonical_role(attempt_kind)
    policy = ROLE_POLICIES[role]
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
        worktree_revision=int(revision),
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
            digest = hashlib.sha256(str(exc).encode()).hexdigest()
            return WorkerResult("failed", {"status": "failed", "summary": str(exc), "changed_files": [], "findings": [], "evidence_refs": [], "missing_evidence": [str(exc)], "verification": [], "verdict": None, "failure_category": "transient"}, {"verified": False, "error": str(exc)}, {}, 0, digest, str(exc))
    with ThreadPoolExecutor(max_workers=min(4, len(requests)), thread_name_prefix="cpe-scout") as pool:
        return list(pool.map(run_one, requests))


def _topological(tasks: list[dict]) -> list[dict]:
    by_id = {str(task["id"]): task for task in tasks}
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
            if candidate_id not in seen and set(candidate.get("dependencies") or []).issubset(seen):
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


def _unexpected_worker_failure(error: Exception) -> WorkerResult:
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
        "failure_category": "unexpected_worker_error",
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


def _start_attempt(kernel: Kernel, task_id: str | None, kind: str, attempt_id: str) -> None:
    revision = project(
        load_verified_manifest(kernel.run_dir / "run_manifest.json"),
        read_events(kernel.run_dir / "events.jsonl"),
    )["worktree_revision"]
    kernel.transition(
        Transition(
            "attempt.started",
            {"kind": canonical_role(kind), "worktree_revision": revision},
            task_id=task_id,
            attempt_id=attempt_id,
        )
    )


def _complete_attempt(
    kernel: Kernel,
    task_id: str | None,
    kind: str,
    result: WorkerResult,
    attempt_id: str,
) -> None:
    result_ref = _attach(kernel, task_id, attempt_id, "worker_result", result.payload)
    completion_status = "completed" if result.status == "completed" else "failed"
    revision = project(
        load_verified_manifest(kernel.run_dir / "run_manifest.json"),
        read_events(kernel.run_dir / "events.jsonl"),
    )["worktree_revision"]
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
        normalized = validate_verdict(verdict, kind, int(revision))
        kernel.transition(
            Transition(
                "verdict.recorded",
                normalized,
                task_id=task_id,
                attempt_id=attempt_id,
            )
        )


def _attach(kernel: Kernel, task_id: str | None, attempt_id: str, kind: str, payload: object) -> dict:
    ref = put_json(kernel.run_dir, kind, payload)
    ref_dict = ref.as_dict()
    kernel.transition(
        Transition(
            "evidence.attached",
            {"kind": kind, "ref": ref_dict},
            task_id=task_id,
            attempt_id=attempt_id,
        )
    )
    return ref_dict


def _worker_attempt(
    worker: Worker,
    kernel: Kernel,
    task: dict | None,
    worktree: Path,
    kind: str,
    ordinal: int,
    prompt: str,
    packet_task_id: str | None = None,
) -> tuple[WorkerResult, WriteAttemptOutcome[WorkerResult] | None]:
    task_id = str(task["id"]) if task else None
    attempt_id = f"{task_id or 'run'}.{kind}.{ordinal}"
    manifest = load_verified_manifest(kernel.run_dir / "run_manifest.json")
    request_task_id = packet_task_id or task_id or str(
        (manifest.get("task_graph") or [{}])[0].get("id") or ""
    )
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
                worktree,
            )
            return worker.run(request)
        except WorkerError as exc:
            payload = {"status": "failed", "summary": str(exc), "changed_files": [], "findings": [], "evidence_refs": [], "missing_evidence": [str(exc)], "verification": [], "verdict": None, "failure_category": "transient"}
            return WorkerResult("failed", payload, {"verified": False, "error": str(exc)}, {}, 0, hashlib.sha256(str(exc).encode()).hexdigest(), str(exc))

    write_outcome = None
    policy = ROLE_POLICIES[canonical_role(kind)]
    if policy.product_write:
        contract = task.get("execution_contract") if task and isinstance(task.get("execution_contract"), dict) else {}
        allowed = list(contract.get("allowed_paths") or (task.get("file_claims") if task else []) or [])
        forbidden = list(contract.get("forbidden_paths") or [])
        write_outcome = AttemptController(kernel, worktree).run_write_attempt(
            task_id=str(task_id),
            attempt_id=attempt_id,
            role=kind,
            allowed=[str(path) for path in allowed],
            forbidden=[str(path) for path in forbidden],
            operation=invoke,
        )
        if write_outcome.error is not None:
            result = _unexpected_worker_failure(write_outcome.error)
        elif write_outcome.result is None:
            result = _unexpected_worker_failure(
                RuntimeError("write attempt returned no worker result")
            )
        else:
            result = write_outcome.result
    else:
        result = invoke()
    _complete_attempt(kernel, task_id, kind, result, attempt_id)
    return result, write_outcome


def run_final_reviews(
    tasks: list[dict],
    worker: Worker,
    kernel: Kernel,
    worktree: Path,
) -> list[WorkerResult]:
    results: list[WorkerResult] = []
    for ordinal, task in enumerate(_topological(tasks), 1):
        task_id = str(task["id"])
        result, _ = _worker_attempt(
            worker,
            kernel,
            None,
            worktree,
            "final_review",
            ordinal,
            f"Review the complete diff for cross-task regressions using task packet {task_id}.",
            packet_task_id=task_id,
        )
        results.append(result)
    return results


def _acceptance(task: dict, worktree: Path, kernel: Kernel, ordinal: int) -> tuple[bool, dict]:
    command = str(task.get("acceptance_command") or "").strip()
    if not command:
        payload = {"command": "", "returncode": 2, "passed": False, "output": "acceptance command missing"}
    else:
        try:
            result = subprocess.run(["/bin/sh", "-lc", command], cwd=worktree, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=600)
            payload = {"command": command, "returncode": result.returncode, "passed": result.returncode == 0, "output": result.stdout[-8000:]}
        except (subprocess.TimeoutExpired, OSError) as exc:
            payload = {"command": command, "returncode": 124, "passed": False, "output": str(exc)}
    attempt_id = f"{task['id']}.acceptance.{ordinal}"
    _attach(kernel, str(task["id"]), attempt_id, "acceptance", payload)
    return bool(payload["passed"]), payload


def _block(kernel: Kernel, task_id: str, phase: str, reason: str) -> dict:
    state = project(load_verified_manifest(kernel.run_dir / "run_manifest.json"), read_events(kernel.run_dir / "events.jsonl"))
    current = state["tasks"][task_id]["status"]
    if current not in {"blocked", "failed", "completed"}:
        kernel.transition(
            Transition("task.status_changed", {"from": current, "to": "blocked", "reason": reason}, task_id=task_id)
        )
    state = project(load_verified_manifest(kernel.run_dir / "run_manifest.json"), read_events(kernel.run_dir / "events.jsonl"))
    if state["lifecycle"] == "running":
        kernel.transition(Transition("run.status_changed", {"from": "running", "to": "blocked", "reason": reason}))
    return {"completed": [key for key, value in state["tasks"].items() if value["status"] == "completed"], "blocked": task_id, "status": "blocked", "reason": reason, "phase": phase}


def _scope_block(
    kernel: Kernel,
    task_id: str,
    phase: str,
    outcome: WriteAttemptOutcome[WorkerResult],
) -> dict:
    error = outcome.scope_errors[0]
    if error == "worktree_head_changed":
        root_cause_key = error
    else:
        _, path = error.split(":", 1)
        root_cause_key = f"task_scope:{task_id}:{path}"
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
    result["failure_category"] = "policy_violation"
    result["root_cause_key"] = root_cause_key
    result["scope_errors"] = list(outcome.scope_errors)
    return result


def run_tasks(tasks: list[dict], worker: Worker, kernel_or_run_dir: Kernel | Path) -> dict:
    kernel = kernel_or_run_dir if isinstance(kernel_or_run_dir, Kernel) else Kernel(kernel_or_run_dir)
    manifest = load_verified_manifest(kernel.run_dir / "run_manifest.json")
    if tasks != list(manifest.get("task_graph") or []):
        raise ValueError("task_graph_mismatch")
    worktree = resolve_ref(str(manifest["execution_worktree_ref"]))
    if worktree.resolve() == kernel.run_dir.resolve():
        raise ValueError("run directory must never be used as execution worktree")
    state = project(manifest, read_events(kernel.run_dir / "events.jsonl"))
    if state["lifecycle"] == "created":
        kernel.transition(Transition("run.status_changed", {"from": "created", "to": "ready"}))
        state = project(manifest, read_events(kernel.run_dir / "events.jsonl"))
    if state["lifecycle"] == "ready":
        kernel.transition(Transition("run.status_changed", {"from": "ready", "to": "running"}))
    elif state["lifecycle"] != "running":
        return {"completed": [], "blocked": None, "status": state["lifecycle"]}

    completed: list[str] = []
    for task in _topological(tasks):
        task_id = str(task["id"])
        state = project(manifest, read_events(kernel.run_dir / "events.jsonl"))
        if state["tasks"][task_id]["status"] == "completed":
            completed.append(task_id)
            continue
        dependencies = task.get("dependencies") or []
        if any(state["tasks"].get(dep, {}).get("status") != "completed" for dep in dependencies):
            return _block(kernel, task_id, state["tasks"][task_id]["status"], "dependency_not_completed")
        current = state["tasks"][task_id]["status"]
        if current == "pending":
            kernel.transition(Transition("task.status_changed", {"from": "pending", "to": "ready"}, task_id=task_id))

        scouts = list(task.get("scout_prompts") or [])
        if scouts:
            kernel.transition(Transition("task.status_changed", {"from": "ready", "to": "scouting"}, task_id=task_id))
            requests = [
                make_packet_request(
                    kernel.run_dir,
                    manifest,
                    task_id,
                    f"{task_id}.scout.{index}",
                    "scout",
                    prompt,
                    worktree,
                )
                for index, prompt in enumerate(scouts, 1)
            ]
            for index in range(1, len(requests) + 1):
                _start_attempt(kernel, task_id, "scout", f"{task_id}.scout.{index}")
            for index, result in enumerate(run_scouts(requests, worker), 1):
                _complete_attempt(kernel, task_id, "scout", result, f"{task_id}.scout.{index}")
                if result.status != "completed" or not result.attestation.get("verified"):
                    return _block(kernel, task_id, "scouting", "scout_failed_or_unattested")
            kernel.transition(Transition("task.status_changed", {"from": "scouting", "to": "implementing"}, task_id=task_id))
        else:
            kernel.transition(Transition("task.status_changed", {"from": "ready", "to": "implementing"}, task_id=task_id))

        implementation, implementation_write = _worker_attempt(
            worker,
            kernel,
            task,
            worktree,
            "implementation",
            1,
            f"Implement task {task_id} using only its verified packet and current revision.",
        )
        if implementation_write is not None and implementation_write.scope_errors:
            return _scope_block(kernel, task_id, "implementation", implementation_write)
        if implementation.status != "completed" or not _trusted(implementation):
            return _block(kernel, task_id, "implementation", "implementation_or_attestation_failed")
        kernel.transition(Transition("task.status_changed", {"from": "implementing", "to": "reviewing"}, task_id=task_id))

        repair_counts: dict[str, int] = {}
        cycle = 1
        while True:
            review, _ = _worker_attempt(worker, kernel, task, worktree, "task_review", cycle, f"Review task {task_id} against its packet and diff.")
            review_verdict = review.payload.get("verdict")
            if (
                review.status == "completed"
                and _trusted(review)
                and isinstance(review_verdict, dict)
                and review_verdict.get("status") == "passed"
            ):
                kernel.transition(Transition("task.status_changed", {"from": "reviewing", "to": "verifying"}, task_id=task_id))
                acceptance_ok, acceptance_payload = _acceptance(task, worktree, kernel, cycle)
                verification, _ = _worker_attempt(
                    worker,
                    kernel,
                    task,
                    worktree,
                    "verification",
                    cycle,
                    f"Judge acceptance evidence for {task_id}: {acceptance_payload}",
                )
                _attach(
                    kernel,
                    task_id,
                    f"{task_id}.verification.{cycle}",
                    "verification",
                    {"accepted": acceptance_ok and verification.status == "completed", "worker": verification.payload},
                )
                verification_verdict = verification.payload.get("verdict")
                if (
                    acceptance_ok
                    and verification.status == "completed"
                    and _trusted(verification)
                    and isinstance(verification_verdict, dict)
                    and verification_verdict.get("status") == "passed"
                ):
                    kernel.transition(Transition("task.status_changed", {"from": "verifying", "to": "completed"}, task_id=task_id))
                    completed.append(task_id)
                    break
                if (
                    isinstance(verification_verdict, dict)
                    and verification_verdict.get("status") in {"blocked", "inconclusive"}
                ):
                    return _block(
                        kernel,
                        task_id,
                        "verifying",
                        f"verification_verdict:{verification_verdict['status']}",
                    )
                phase = "verifying"
                root_key = str(
                    verification.payload.get("root_cause_key")
                    or (
                        f"verification:{verification_verdict.get('status')}"
                        if isinstance(verification_verdict, dict)
                        else f"acceptance:{acceptance_payload['returncode']}"
                    )
                )
            else:
                if (
                    isinstance(review_verdict, dict)
                    and review_verdict.get("status") in {"blocked", "inconclusive"}
                ):
                    return _block(
                        kernel,
                        task_id,
                        "reviewing",
                        f"review_verdict:{review_verdict['status']}",
                    )
                phase = "reviewing"
                root_key = str(
                    review.payload.get("root_cause_key")
                    or (
                        f"review:{review_verdict.get('status')}"
                        if isinstance(review_verdict, dict)
                        else "review_failed"
                    )
                )
            repair_counts[root_key] = repair_counts.get(root_key, 0) + 1
            if repair_counts[root_key] > 2:
                return _block(kernel, task_id, phase, f"repair_limit_exhausted:{root_key}")
            kernel.transition(Transition("task.status_changed", {"from": phase, "to": "repairing"}, task_id=task_id))
            repair, repair_write = _worker_attempt(
                worker,
                kernel,
                task,
                worktree,
                "repair",
                repair_counts[root_key],
                f"Repair {task_id} root cause {root_key}; remain inside file claims.",
            )
            if repair_write is not None and repair_write.scope_errors:
                return _scope_block(kernel, task_id, "repairing", repair_write)
            if repair.status != "completed" or not _trusted(repair):
                return _block(kernel, task_id, "repairing", f"repair_failed:{root_key}")
            kernel.transition(Transition("task.status_changed", {"from": "repairing", "to": "reviewing"}, task_id=task_id))
            cycle += 1

    final_reviews = run_final_reviews(tasks, worker, kernel, worktree)
    if any(
        result.status != "completed"
        or not _trusted(result)
        or not isinstance(result.payload.get("verdict"), dict)
        or result.payload["verdict"].get("status") != "passed"
        for result in final_reviews
    ):
        state = project(manifest, read_events(kernel.run_dir / "events.jsonl"))
        kernel.transition(Transition("run.status_changed", {"from": state["lifecycle"], "to": "blocked", "reason": "final_review_failed"}))
        return {"completed": completed, "blocked": "final_review"}
    evidence = [item["ref"] for item in project(manifest, read_events(kernel.run_dir / "events.jsonl"))["artifact_index"]]
    kernel.transition(
        Transition(
            "completion.recorded",
            {
                "passed": True,
                "prompt_to_artifact_checklist": ["manifest", "events", "task packets", "evidence", "snapshot"],
                "verification_evidence": evidence,
                "residual_risk": ["paid live migration gate pending"],
            },
        )
    )
    kernel.transition(Transition("run.status_changed", {"from": "running", "to": "completed"}))
    return {"completed": completed, "blocked": None, "status": "completed"}
