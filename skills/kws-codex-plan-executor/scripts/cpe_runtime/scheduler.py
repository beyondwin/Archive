from __future__ import annotations

import subprocess
import hashlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from .evidence import put_json
from .kernel import Kernel, Transition
from .manifest import load_verified_manifest, resolve_ref
from .model_policy import CORE_ROUTE
from .packets import PACKET_ROLE_POLICY, packet_entry, verify_packet
from .projector import project
from .events import read_events
from .worker import Worker, WorkerError, WorkerRequest, WorkerResult


@dataclass(frozen=True)
class PacketBoundWorkerRequest(WorkerRequest):
    task_id: str
    packet_path: str
    packet_sha256: str


def make_packet_request(
    run_dir: Path,
    manifest: dict,
    task_id: str,
    attempt_id: str,
    attempt_kind: str,
    prompt: str,
    worktree: Path,
) -> PacketBoundWorkerRequest:
    verify_packet(run_dir, manifest, task_id)
    entry = packet_entry(manifest, task_id)
    packet_prompt = (
        f"{prompt}\n\n"
        "VERIFIED TASK PACKET (immutable runtime input)\n"
        f"task_id={task_id}\n"
        f"packet_path={entry['path']}\n"
        f"packet_sha256={entry['sha256']}"
    )
    role = PACKET_ROLE_POLICY[attempt_kind]
    return PacketBoundWorkerRequest(
        attempt_id,
        attempt_kind,
        packet_prompt,
        worktree,
        role["read_only"],
        role["verdict_capable"],
        task_id,
        entry["path"],
        entry["sha256"],
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
            return WorkerResult("failed", {"status": "failed", "summary": str(exc), "changed_files": [], "findings": [], "evidence_refs": [], "missing_evidence": [str(exc)], "verification": [], "failure_category": "transient"}, {"verified": False, "error": str(exc)}, {}, 0, digest, str(exc))
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


def _record_attempt(kernel: Kernel, task_id: str | None, kind: str, result: WorkerResult, attempt_id: str) -> None:
    kernel.transition(
        Transition(
            "attempt.recorded",
            {
                "kind": kind,
                "status": result.status,
                "attestation": result.attestation,
                "usage": result.usage,
                "latency_ms": result.latency_ms,
                "read_only": kind == "scout",
                "verdict_capable": kind != "scout",
                "raw_event_digest": result.raw_event_digest,
                "summary": result.payload.get("summary", ""),
                "failure_category": result.payload.get("failure_category"),
                "root_cause_key": result.payload.get("root_cause_key"),
            },
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
) -> WorkerResult:
    task_id = str(task["id"]) if task else None
    attempt_id = f"{task_id or 'run'}.{kind}.{ordinal}"
    manifest = load_verified_manifest(kernel.run_dir / "run_manifest.json")
    packet_task_id = task_id or str((manifest.get("task_graph") or [{}])[0].get("id") or "")
    try:
        request = make_packet_request(
            kernel.run_dir,
            manifest,
            packet_task_id,
            attempt_id,
            kind,
            prompt,
            worktree,
        )
        result = worker.run(request)
    except WorkerError as exc:
        payload = {"status": "failed", "summary": str(exc), "changed_files": [], "findings": [], "evidence_refs": [], "missing_evidence": [str(exc)], "verification": [], "failure_category": "transient"}
        result = WorkerResult("failed", payload, {"verified": False, "error": str(exc)}, {}, 0, hashlib.sha256(str(exc).encode()).hexdigest(), str(exc))
    _record_attempt(kernel, task_id, kind, result, attempt_id)
    _attach(kernel, task_id, attempt_id, "worker_result", result.payload)
    return result


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
            for index, result in enumerate(run_scouts(requests, worker), 1):
                _record_attempt(kernel, task_id, "scout", result, f"{task_id}.scout.{index}")
                _attach(kernel, task_id, f"{task_id}.scout.{index}", "scout", result.payload)
                if result.status != "completed" or not result.attestation.get("verified"):
                    return _block(kernel, task_id, "scouting", "scout_failed_or_unattested")
            kernel.transition(Transition("task.status_changed", {"from": "scouting", "to": "implementing"}, task_id=task_id))
        else:
            kernel.transition(Transition("task.status_changed", {"from": "ready", "to": "implementing"}, task_id=task_id))

        implementation = _worker_attempt(
            worker,
            kernel,
            task,
            worktree,
            "implementation",
            1,
            str(task.get("prompt") or task.get("packet") or task_id),
        )
        changed = set(implementation.payload.get("changed_files") or [])
        claims = set(task.get("file_claims") or [])
        if implementation.status != "completed" or not _trusted(implementation) or not changed.issubset(claims):
            return _block(kernel, task_id, "implementation", "implementation_or_attestation_failed")
        kernel.transition(Transition("task.status_changed", {"from": "implementing", "to": "reviewing"}, task_id=task_id))

        repair_counts: dict[str, int] = {}
        cycle = 1
        while True:
            review = _worker_attempt(worker, kernel, task, worktree, "task_review", cycle, f"Review task {task_id} against its packet and diff.")
            if review.status == "completed" and _trusted(review):
                kernel.transition(Transition("task.status_changed", {"from": "reviewing", "to": "verifying"}, task_id=task_id))
                acceptance_ok, acceptance_payload = _acceptance(task, worktree, kernel, cycle)
                verification = _worker_attempt(
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
                if acceptance_ok and verification.status == "completed" and _trusted(verification):
                    kernel.transition(Transition("task.status_changed", {"from": "verifying", "to": "completed"}, task_id=task_id))
                    completed.append(task_id)
                    break
                phase = "verifying"
                root_key = str(verification.payload.get("root_cause_key") or f"acceptance:{acceptance_payload['returncode']}")
            else:
                phase = "reviewing"
                root_key = str(review.payload.get("root_cause_key") or "review_failed")
            repair_counts[root_key] = repair_counts.get(root_key, 0) + 1
            if repair_counts[root_key] > 2:
                return _block(kernel, task_id, phase, f"repair_limit_exhausted:{root_key}")
            kernel.transition(Transition("task.status_changed", {"from": phase, "to": "repairing"}, task_id=task_id))
            repair = _worker_attempt(
                worker,
                kernel,
                task,
                worktree,
                "repair",
                repair_counts[root_key],
                f"Repair {task_id} root cause {root_key}; remain inside file claims.",
            )
            if repair.status != "completed" or not _trusted(repair):
                return _block(kernel, task_id, "repairing", f"repair_failed:{root_key}")
            kernel.transition(Transition("task.status_changed", {"from": "repairing", "to": "reviewing"}, task_id=task_id))
            cycle += 1

    final_review = _worker_attempt(worker, kernel, None, worktree, "final_review", 1, "Review the complete diff for cross-task regressions.")
    if final_review.status != "completed" or not _trusted(final_review):
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
