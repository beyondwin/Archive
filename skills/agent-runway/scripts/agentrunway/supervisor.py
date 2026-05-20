from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .adapters.base import RuntimeAdapter
from .db import AgentRunwayDb
from .file_claims import validate_changed_files
from .git_ops import Git, changed_files_between, commits_between
from .models import TaskSpec, WorkerResultEnvelope, WorkerSpec
from .packetizer import materialize_role_prompt
from .result_validation import validate_review_result, validate_verification_result, validate_worker_result
from .worktrees import create_worker_worktree


@dataclass(frozen=True)
class WorkerAttemptResult:
    envelope: WorkerResultEnvelope
    base_commit: str


def _allowed_globs(task: TaskSpec) -> tuple[str, ...]:
    return tuple(claim.path for claim in task.file_claims if claim.mode in {"owned", "shared_append"})


def gate_review_result(review_json: dict[str, object]) -> str:
    result = validate_review_result(review_json)
    return str(result["status"])


def gate_verification_result(verification_json: dict[str, object]) -> str:
    result = validate_verification_result(verification_json)
    return str(result["status"])


def next_worker_id(*, db: AgentRunwayDb, task_id: str, role: str) -> tuple[str, int]:
    prefix = f"{task_id}-{role}-"
    attempts: list[int] = []
    for worker in db.list_workers():
        worker_id = str(worker["worker_id"])
        if not worker_id.startswith(prefix):
            continue
        try:
            attempts.append(int(worker_id.removeprefix(prefix)))
        except ValueError:
            continue
    attempt = max(attempts, default=0) + 1
    return f"{prefix}{attempt:03d}", attempt


def run_worker_attempt(
    *,
    db: AgentRunwayDb,
    run_id: str,
    git: Git,
    worktree_root: Path,
    run_dir: Path,
    task: TaskSpec,
    packet_path: Path,
    prompt_path: Path,
    output_path: Path,
    adapter: RuntimeAdapter,
    runtime: str,
    model: str,
    reasoning_effort: str,
    role: str,
    base_ref: str,
    attempt: int,
    timeout_seconds: int,
    metadata: dict[str, str] | None = None,
) -> WorkerAttemptResult:
    worker_id = f"{task.task_id}-{role}-{attempt:03d}"
    branch = f"agentrunway/{run_id}/{worker_id}"
    base_commit = git.rev_parse(base_ref)
    worker_tree = create_worker_worktree(git, worktree_root / "workers" / worker_id, branch, base_commit)
    spec = WorkerSpec(
        run_id=run_id,
        task_id=task.task_id,
        worker_id=worker_id,
        role=role,
        runtime=runtime,
        model=model,
        reasoning_effort=reasoning_effort,
        prompt_path=str(prompt_path),
        packet_path=str(packet_path),
        output_path=str(output_path),
        worktree_path=str(worker_tree),
        artifact_dir=str(output_path.parent),
        timeout_seconds=timeout_seconds,
        attempt=attempt,
        metadata=dict(metadata or {}),
    )
    db.create_worker_attempt(
        worker_id=worker_id,
        task_id=task.task_id,
        role=role,
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
    return WorkerAttemptResult(envelope=envelope, base_commit=base_commit)


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
    base_ref = f"agentrunway/{run_id}/main"
    artifact_dir = run_dir / "artifacts" / task.task_id / worker_id
    output_path = artifact_dir / "worker_result.json"
    attempt_result = run_worker_attempt(
        db=db,
        run_id=run_id,
        git=git,
        worktree_root=worktree_root,
        run_dir=run_dir,
        task=task,
        packet_path=packet_path,
        prompt_path=prompt_path,
        output_path=output_path,
        adapter=adapter,
        runtime=runtime,
        model=model,
        reasoning_effort=reasoning_effort,
        role="implementer",
        base_ref=base_ref,
        attempt=attempt,
        timeout_seconds=timeout_seconds,
    )
    envelope = attempt_result.envelope
    if envelope.result_json is None:
        db.set_worker_state(worker_id, "malformed_result")
        raise RuntimeError(envelope.error or "missing_worker_result")
    validate_worker_result(envelope.result_json)
    worker_tree = Path(str(db.get_worker(worker_id)["worktree_path"]))
    commits = commits_between(Git(worker_tree), attempt_result.base_commit, "HEAD")
    changed_files = changed_files_between(Git(worker_tree), attempt_result.base_commit, "HEAD")
    validate_changed_files(changed_files, _allowed_globs(task))
    db.set_worker_state(worker_id, "validated")
    candidate_id = db.enqueue_merge_candidate(
        task_id=task.task_id,
        worker_id=worker_id,
        commits=commits,
        changed_files=changed_files,
        status="pending_review",
    )
    artifact_dir.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(envelope.result_json, indent=2, sort_keys=True), encoding="utf-8")
    (artifact_dir / "envelope.json").write_text(json.dumps(asdict(envelope), indent=2, sort_keys=True), encoding="utf-8")
    return candidate_id


def run_reviewer_attempt(
    *,
    db: AgentRunwayDb,
    run_id: str,
    git: Git,
    worktree_root: Path,
    run_dir: Path,
    task: TaskSpec,
    adapter: RuntimeAdapter,
    runtime: str,
    model: str,
    reasoning_effort: str,
    reviewed_worker_id: str,
    candidate_diff: str,
    candidate_commits: tuple[str, ...],
    attempt: int,
    timeout_seconds: int,
    fake_review_status: str | None = None,
) -> dict[str, object]:
    worker_id = f"{task.task_id}-reviewer-{attempt:03d}"
    output_path = run_dir / "artifacts" / task.task_id / worker_id / "review_result.json"
    prompt_path = materialize_role_prompt(
        role="reviewer",
        task=task,
        worker_id=worker_id,
        packet_path=run_dir / "packets" / f"{task.task_id}.json",
        output_path=output_path,
        prompt_dir=run_dir / "prompts",
        context={"reviewed_worker_id": reviewed_worker_id, "diff": candidate_diff},
    )
    metadata = {"AGENTRUNWAY_REVIEWED_WORKER_ID": reviewed_worker_id}
    if fake_review_status:
        metadata["AGENTRUNWAY_FAKE_REVIEW_STATUS"] = fake_review_status
    candidate_head = candidate_commits[-1] if candidate_commits else f"agentrunway/{run_id}/main"
    attempt_result = run_worker_attempt(
        db=db,
        run_id=run_id,
        git=git,
        worktree_root=worktree_root,
        run_dir=run_dir,
        task=task,
        packet_path=run_dir / "packets" / f"{task.task_id}.json",
        prompt_path=prompt_path,
        output_path=output_path,
        adapter=adapter,
        runtime=runtime,
        model=model,
        reasoning_effort=reasoning_effort,
        role="reviewer",
        base_ref=candidate_head,
        attempt=attempt,
        timeout_seconds=timeout_seconds,
        metadata=metadata,
    )
    envelope = attempt_result.envelope
    if envelope.result_json is None:
        db.set_worker_state(worker_id, "malformed_result")
        raise RuntimeError("missing_review_result")
    result = validate_review_result(envelope.result_json)
    db.set_worker_state(worker_id, "validated")
    return result


def run_verifier_attempt(
    *,
    db: AgentRunwayDb,
    run_id: str,
    git: Git,
    worktree_root: Path,
    run_dir: Path,
    task: TaskSpec,
    adapter: RuntimeAdapter,
    runtime: str,
    model: str,
    reasoning_effort: str,
    commits: tuple[str, ...],
    changed_files: tuple[str, ...],
    review_status: str,
    attempt: int,
    timeout_seconds: int,
    fake_verify_status: str | None = None,
) -> dict[str, object]:
    worker_id = f"{task.task_id}-verifier-{attempt:03d}"
    output_path = run_dir / "artifacts" / task.task_id / worker_id / "verification_result.json"
    prompt_path = materialize_role_prompt(
        role="verifier",
        task=task,
        worker_id=worker_id,
        packet_path=run_dir / "packets" / f"{task.task_id}.json",
        output_path=output_path,
        prompt_dir=run_dir / "prompts",
        context={
            "commits": list(commits),
            "changed_files": list(changed_files),
            "acceptance_commands": list(task.acceptance_commands),
            "review_status": review_status,
        },
    )
    metadata: dict[str, str] = {}
    if fake_verify_status:
        metadata["AGENTRUNWAY_FAKE_VERIFY_STATUS"] = fake_verify_status
    candidate_head = commits[-1] if commits else f"agentrunway/{run_id}/main"
    attempt_result = run_worker_attempt(
        db=db,
        run_id=run_id,
        git=git,
        worktree_root=worktree_root,
        run_dir=run_dir,
        task=task,
        packet_path=run_dir / "packets" / f"{task.task_id}.json",
        prompt_path=prompt_path,
        output_path=output_path,
        adapter=adapter,
        runtime=runtime,
        model=model,
        reasoning_effort=reasoning_effort,
        role="verifier",
        base_ref=candidate_head,
        attempt=attempt,
        timeout_seconds=timeout_seconds,
        metadata=metadata,
    )
    envelope = attempt_result.envelope
    if envelope.result_json is None:
        db.set_worker_state(worker_id, "malformed_result")
        raise RuntimeError("missing_verification_result")
    result = validate_verification_result(envelope.result_json)
    db.set_worker_state(worker_id, "validated")
    return result
