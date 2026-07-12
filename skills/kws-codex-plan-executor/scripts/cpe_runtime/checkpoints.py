"""Candidate commit creation and verified-checkpoint promotion for CPE v4."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from .git_delta import (
    committed_patch_digest,
    matches_path,
    working_tree_changed_files,
)
from .kernel import Transition
from .task_contracts import TaskContractV4


CPE_GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "CPE Executor",
    "GIT_AUTHOR_EMAIL": "cpe@example.invalid",
    "GIT_COMMITTER_NAME": "CPE Executor",
    "GIT_COMMITTER_EMAIL": "cpe@example.invalid",
}


@dataclass(frozen=True)
class CandidateCheckpoint:
    task_id: str
    predecessor: str
    commit: str
    tree: str
    patch_sha256: str
    changed_files: tuple[str, ...]


@dataclass(frozen=True)
class VerifiedCheckpoint:
    task_id: str
    predecessor: str
    commit: str
    tree: str
    contract_sha256: str
    acceptance_sha256: str
    review_sha256: str


def _git(worktree: Path, *args: str, env: dict[str, str] | None = None) -> bytes:
    argv = ["git", *args]
    try:
        result = subprocess.run(
            argv,
            cwd=worktree,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        raise RuntimeError("git_candidate_command_failed") from exc
    if result.returncode:
        raise RuntimeError("git_candidate_command_failed")
    return result.stdout.rstrip(b"\r\n")


def _is_hex(value: object, length: int) -> bool:
    return (
        isinstance(value, str)
        and len(value) == length
        and all(character in "0123456789abcdef" for character in value)
    )


def _checkpoint_predecessor(state: dict) -> str:
    predecessor = state.get("checkpoint_head") or state.get("source_head")
    if not _is_hex(predecessor, 40):
        raise ValueError("checkpoint_predecessor_invalid")
    return str(predecessor)


def _validate_contract(contract: TaskContractV4) -> None:
    if not isinstance(contract, TaskContractV4) or not _is_hex(contract.contract_sha256, 64):
        raise ValueError("task_contract_invalid")
    if not contract.file_claims:
        raise ValueError("task_contract_claims_missing")


def _candidate_payload(candidate: CandidateCheckpoint) -> dict[str, object]:
    return {
        "predecessor": candidate.predecessor,
        "commit": candidate.commit,
        "tree": candidate.tree,
        "patch_sha256": candidate.patch_sha256,
        "changed_files": list(candidate.changed_files),
    }


def create_candidate_checkpoint(
    kernel: object,
    contract: TaskContractV4,
    product_worktree: Path,
) -> CandidateCheckpoint:
    """Commit exactly one task's claimed product delta and record the candidate."""

    _validate_contract(contract)
    worktree = product_worktree.expanduser().resolve()
    state = getattr(kernel, "state")
    predecessor = _git(worktree, "rev-parse", "--verify", "HEAD").decode("ascii")
    if predecessor != _checkpoint_predecessor(state):
        raise ValueError("non_direct_child_candidate")

    changed_files = working_tree_changed_files(worktree)
    if not changed_files:
        raise ValueError("candidate_has_no_changes")
    forbidden = [
        path for path in changed_files if matches_path(path, contract.forbidden_paths)
    ]
    if forbidden:
        raise ValueError(f"forbidden_candidate:{forbidden[0]}")
    unclaimed = [path for path in changed_files if not matches_path(path, contract.file_claims)]
    if unclaimed:
        raise ValueError(f"out_of_claim_candidate:{unclaimed[0]}")

    literal_pathspecs = tuple(f":(literal){path}" for path in changed_files)
    _git(worktree, "add", "-A", "--", *literal_pathspecs)
    environment = {**os.environ, **CPE_GIT_IDENTITY}
    _git(worktree, "commit", "-q", "-m", contract.checkpoint_message, env=environment)
    commit = _git(worktree, "rev-parse", "--verify", "HEAD").decode("ascii")
    parent = _git(worktree, "rev-parse", "--verify", f"{commit}^").decode("ascii")
    if parent != predecessor or not _is_hex(commit, 40):
        raise RuntimeError("candidate_commit_not_direct_child")
    tree = _git(worktree, "rev-parse", "--verify", f"{commit}^{{tree}}").decode("ascii")
    committed_files, patch_sha256 = committed_patch_digest(worktree, predecessor, commit)
    if committed_files != changed_files:
        raise RuntimeError("candidate_commit_delta_mismatch")
    if _git(worktree, "status", "--porcelain=v1", "-z", "--untracked-files=all"):
        raise RuntimeError("dirty_product_worktree_after_candidate_commit")

    candidate = CandidateCheckpoint(
        task_id=contract.task_id,
        predecessor=predecessor,
        commit=commit,
        tree=tree,
        patch_sha256=patch_sha256,
        changed_files=committed_files,
    )
    kernel.transition(
        Transition(
            "candidate.checkpoint_recorded",
            _candidate_payload(candidate),
            task_id=contract.task_id,
        )
    )
    return candidate


def _acceptance_digest(results: Iterable[object]) -> tuple[tuple[object, ...], str]:
    records = tuple(results)
    if not records:
        raise ValueError("acceptance_evidence_missing")
    payload: list[dict[str, object]] = []
    for result in records:
        try:
            record = asdict(result)
        except (TypeError, ValueError) as exc:
            raise ValueError("acceptance_evidence_invalid") from exc
        if record.get("exit_code") != 0:
            raise ValueError("acceptance_failed")
        if not all(
            _is_hex(record.get(field), 64)
            for field in ("command_sha256", "stdout_sha256", "stderr_sha256")
        ) or not _is_hex(record.get("revision"), 40):
            raise ValueError("acceptance_evidence_invalid")
        payload.append(record)
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return records, hashlib.sha256(b"CPE-ACCEPTANCE-V1\0" + raw).hexdigest()


def promote_verified_checkpoint(
    kernel: object,
    contract: TaskContractV4,
    candidate: CandidateCheckpoint,
    acceptance_results: Iterable[object],
) -> VerifiedCheckpoint:
    """Promote only the recorded passing direct child of the checkpoint head."""

    _validate_contract(contract)
    state = getattr(kernel, "state")
    if candidate.task_id != contract.task_id:
        raise ValueError("candidate_task_mismatch")
    if candidate.predecessor != _checkpoint_predecessor(state):
        raise ValueError("non_direct_child_candidate")
    fields = (candidate.predecessor, candidate.commit, candidate.tree)
    if not all(_is_hex(value, 40) for value in fields) or not _is_hex(
        candidate.patch_sha256, 64
    ):
        raise ValueError("candidate_checkpoint_invalid")
    recorded = [
        item
        for item in state.get("candidate_checkpoints", [])
        if item.get("task_id") == contract.task_id
        and all(item.get(key) == value for key, value in _candidate_payload(candidate).items())
    ]
    if len(recorded) != 1:
        raise ValueError("candidate_checkpoint_unrecorded")
    records, acceptance_sha256 = _acceptance_digest(acceptance_results)
    if any(getattr(record, "revision", None) != candidate.commit for record in records):
        raise ValueError("acceptance_revision_mismatch")
    verified = VerifiedCheckpoint(
        task_id=contract.task_id,
        predecessor=candidate.predecessor,
        commit=candidate.commit,
        tree=candidate.tree,
        contract_sha256=contract.contract_sha256,
        acceptance_sha256=acceptance_sha256,
        review_sha256=candidate.patch_sha256,
    )
    payload = asdict(verified)
    payload.pop("task_id")
    kernel.transition(
        Transition(
            "task.checkpoint_verified",
            payload,
            task_id=contract.task_id,
        )
    )
    return verified
