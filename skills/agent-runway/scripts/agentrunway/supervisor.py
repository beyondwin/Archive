from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .adapters.base import RuntimeAdapter
from .db import AgentRunwayDb
from .file_claims import validate_changed_files
from .git_ops import Git, changed_files_between, commits_between
from .models import TaskSpec, WorkerSpec
from .result_validation import validate_review_result, validate_verification_result, validate_worker_result
from .worktrees import create_worker_worktree


def _allowed_globs(task: TaskSpec) -> tuple[str, ...]:
    return tuple(claim.path for claim in task.file_claims if claim.mode in {"owned", "shared_append"})


def gate_review_result(review_json: dict[str, object]) -> str:
    result = validate_review_result(review_json)
    return str(result["status"])


def gate_verification_result(verification_json: dict[str, object]) -> str:
    result = validate_verification_result(verification_json)
    return str(result["status"])


def run_implementer_attempt(
    *,
    db: AgentRunwayDb,
    run_id: str,
    git: Git,
    main_worktree: Path,
    worktree_root: Path,
    run_dir: Path,
    task: TaskSpec,
    packet_path: Path,
    prompt_path: Path,
    adapter: RuntimeAdapter,
    runtime: str,
    model: str,
    reasoning_effort: str,
    attempt: int,
    timeout_seconds: int,
) -> int:
    worker_id = f"{task.task_id}-implementer-{attempt:03d}"
    branch = f"agentrunway/{run_id}/{worker_id}"
    base_ref = f"agentrunway/{run_id}/main"
    worker_tree = create_worker_worktree(git, worktree_root / "workers" / worker_id, branch, base_ref)
    artifact_dir = run_dir / "artifacts" / task.task_id / worker_id
    output_path = artifact_dir / "worker_result.json"
    spec = WorkerSpec(
        run_id=run_id,
        task_id=task.task_id,
        worker_id=worker_id,
        role="implementer",
        runtime=runtime,
        model=model,
        reasoning_effort=reasoning_effort,
        prompt_path=str(prompt_path),
        packet_path=str(packet_path),
        output_path=str(output_path),
        worktree_path=str(worker_tree),
        artifact_dir=str(artifact_dir),
        timeout_seconds=timeout_seconds,
        attempt=attempt,
    )
    db.create_worker_attempt(
        worker_id=worker_id,
        task_id=task.task_id,
        role="implementer",
        runtime=runtime,
        model=model,
        reasoning_effort=reasoning_effort,
        attempt=attempt,
        worktree_path=str(worker_tree),
        branch=branch,
        state="worktree_created",
        handle_json={},
    )
    handle = adapter.start(adapter.prepare(spec))
    db.set_worker_state(worker_id, "running")
    db.update_worker_handle(worker_id, handle.to_json())
    envelope = adapter.collect(handle)
    db.set_worker_state(worker_id, "result_collected")
    if envelope.result_json is None:
        db.set_worker_state(worker_id, "malformed_result")
        raise RuntimeError(envelope.error or "missing_worker_result")
    validate_worker_result(envelope.result_json)
    commits = commits_between(Git(worker_tree), base_ref, "HEAD")
    changed_files = changed_files_between(Git(worker_tree), base_ref, "HEAD")
    validate_changed_files(changed_files, _allowed_globs(task))
    db.set_worker_state(worker_id, "validated")
    candidate_id = db.enqueue_merge_candidate(
        task_id=task.task_id,
        worker_id=worker_id,
        commits=commits,
        changed_files=changed_files,
        status="merge_ready",
    )
    artifact_dir.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(envelope.result_json, indent=2, sort_keys=True), encoding="utf-8")
    (artifact_dir / "envelope.json").write_text(json.dumps(asdict(envelope), indent=2, sort_keys=True), encoding="utf-8")
    return candidate_id
