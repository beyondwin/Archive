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
from .manifest import upstream_plan_graph_sha256
from .task_contracts import TaskContractV4
from .verification_workspace import (
    AcceptanceResult,
    acceptance_command_sha256,
)


CPE_GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "CPE Executor",
    "GIT_AUTHOR_EMAIL": "cpe@example.invalid",
    "GIT_COMMITTER_NAME": "CPE Executor",
    "GIT_COMMITTER_EMAIL": "cpe@example.invalid",
}


@dataclass(frozen=True)
class CandidateCheckpoint:
    task_id: str
    contract_sha256: str
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


@dataclass(frozen=True)
class ReviewEvidence:
    task_id: str
    candidate_commit: str
    contract_sha256: str
    decision: str
    review_content_sha256: str
    artifact_sha256: str


class _FrozenEvidence(dict[str, str]):
    def _reject_mutation(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        raise TypeError("PlanCheckpoint evidence is immutable")

    __setitem__ = _reject_mutation
    __delitem__ = _reject_mutation
    clear = _reject_mutation
    pop = _reject_mutation
    popitem = _reject_mutation
    setdefault = _reject_mutation
    update = _reject_mutation
    __ior__ = _reject_mutation


@dataclass(frozen=True)
class PlanCheckpoint:
    plan_id: str
    commit: str
    tree: str
    plan_sha256: str
    spec_sha256: str
    upstream_checkpoint: str | None
    upstream_graph_sha256: str
    evidence_refs: tuple[dict[str, str], ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "evidence_refs",
            tuple(_FrozenEvidence(dict(reference)) for reference in self.evidence_refs),
        )

    def body(self) -> dict[str, object]:
        return {
            "plan_id": self.plan_id,
            "commit": self.commit,
            "tree": self.tree,
            "plan_sha256": self.plan_sha256,
            "spec_sha256": self.spec_sha256,
            "upstream_checkpoint": self.upstream_checkpoint,
            "upstream_graph_sha256": self.upstream_graph_sha256,
            "evidence_refs": [dict(reference) for reference in self.evidence_refs],
        }

    def identity(self) -> str:
        raw = json.dumps(self.body(), sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(b"CPE-PLAN-CHECKPOINT-VNEXT\0" + raw).hexdigest()


def upstream_graph_sha256(graph: object, plan_id: str) -> str:
    """Digest only the graph prefix that can affect ``plan_id``."""
    return upstream_plan_graph_sha256(graph, plan_id)


def create_plan_checkpoint(
    *,
    plan_id: str,
    commit: str,
    tree: str,
    plan_sha256: str,
    spec_sha256: str,
    upstream_checkpoint: str | None,
    upstream_graph_sha256: str,
    evidence_refs: tuple[dict[str, str], ...],
) -> PlanCheckpoint:
    """Create an immutable checkpoint bound to exact Git, document, and graph evidence."""

    if not plan_id or "::" in plan_id:
        raise ValueError("plan_checkpoint_plan_invalid")
    if not _is_hex(commit, 40) or not _is_hex(tree, 40):
        raise ValueError("plan_checkpoint_git_invalid")
    if not all(_is_hex(value, 64) for value in (plan_sha256, spec_sha256, upstream_graph_sha256)):
        raise ValueError("plan_checkpoint_digest_invalid")
    if upstream_checkpoint is not None and not _is_hex(upstream_checkpoint, 64):
        raise ValueError("plan_checkpoint_upstream_invalid")
    if not evidence_refs:
        raise ValueError("plan_checkpoint_evidence_missing")
    for reference in evidence_refs:
        if (
            not isinstance(reference, dict)
            or not reference
            or any(not isinstance(key, str) or not isinstance(value, str) or not value for key, value in reference.items())
            or not _is_hex(reference.get("sha256"), 64)
        ):
            raise ValueError("plan_checkpoint_evidence_invalid")
    return PlanCheckpoint(
        plan_id=plan_id,
        commit=commit,
        tree=tree,
        plan_sha256=plan_sha256,
        spec_sha256=spec_sha256,
        upstream_checkpoint=upstream_checkpoint,
        upstream_graph_sha256=upstream_graph_sha256,
        evidence_refs=evidence_refs,
    )


def promote_plan_checkpoint(
    checkpoint: PlanCheckpoint,
    *,
    plan_id: str,
    plan_sha256: str,
    spec_sha256: str,
    upstream_checkpoint: str | None,
    upstream_graph_sha256: str,
) -> PlanCheckpoint:
    """Promote only a checkpoint current for its plan, documents, and upstream graph."""

    if not isinstance(checkpoint, PlanCheckpoint):
        raise ValueError("plan_checkpoint_invalid")
    try:
        validated = create_plan_checkpoint(
            plan_id=checkpoint.plan_id,
            commit=checkpoint.commit,
            tree=checkpoint.tree,
            plan_sha256=checkpoint.plan_sha256,
            spec_sha256=checkpoint.spec_sha256,
            upstream_checkpoint=checkpoint.upstream_checkpoint,
            upstream_graph_sha256=checkpoint.upstream_graph_sha256,
            evidence_refs=checkpoint.evidence_refs,
        )
    except ValueError as exc:
        raise ValueError("plan_checkpoint_invalid") from exc
    if validated.identity() != checkpoint.identity():
        raise ValueError("plan_checkpoint_invalid")
    if checkpoint.plan_id != plan_id:
        raise ValueError("plan_checkpoint_plan_mismatch")
    if checkpoint.plan_sha256 != plan_sha256:
        raise ValueError("plan_checkpoint_document_stale")
    if checkpoint.spec_sha256 != spec_sha256:
        raise ValueError("plan_checkpoint_spec_stale")
    if checkpoint.upstream_graph_sha256 != upstream_graph_sha256:
        raise ValueError("plan_checkpoint_upstream_graph_stale")
    if checkpoint.upstream_checkpoint != upstream_checkpoint:
        raise ValueError("plan_checkpoint_upstream_stale")
    return checkpoint


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
        "contract_sha256": candidate.contract_sha256,
        "predecessor": candidate.predecessor,
        "commit": candidate.commit,
        "tree": candidate.tree,
        "patch_sha256": candidate.patch_sha256,
        "changed_files": list(candidate.changed_files),
    }


def _review_artifact_sha256(
    *,
    task_id: str,
    candidate_commit: str,
    contract_sha256: str,
    decision: str,
    review_content_sha256: str,
) -> str:
    body = {
        "task_id": task_id,
        "candidate_commit": candidate_commit,
        "contract_sha256": contract_sha256,
        "decision": decision,
        "review_content_sha256": review_content_sha256,
    }
    raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(b"CPE-REVIEW-ARTIFACT-V1\0" + raw).hexdigest()


def create_review_evidence(
    *,
    task_id: str,
    candidate_commit: str,
    contract_sha256: str,
    decision: str,
    review_content_sha256: str,
) -> ReviewEvidence:
    """Create immutable, self-digesting review evidence for later promotion."""

    if (
        not task_id
        or not _is_hex(candidate_commit, 40)
        or not _is_hex(contract_sha256, 64)
        or decision not in {"approved", "changes_requested", "blocked"}
        or not _is_hex(review_content_sha256, 64)
    ):
        raise ValueError("review_evidence_invalid")
    artifact_sha256 = _review_artifact_sha256(
        task_id=task_id,
        candidate_commit=candidate_commit,
        contract_sha256=contract_sha256,
        decision=decision,
        review_content_sha256=review_content_sha256,
    )
    return ReviewEvidence(
        task_id=task_id,
        candidate_commit=candidate_commit,
        contract_sha256=contract_sha256,
        decision=decision,
        review_content_sha256=review_content_sha256,
        artifact_sha256=artifact_sha256,
    )


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
        contract_sha256=contract.contract_sha256,
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


def _acceptance_digest(
    results: Iterable[object],
    commands: tuple[str, ...],
    candidate_commit: str,
) -> tuple[tuple[AcceptanceResult, ...], str]:
    records = tuple(results)
    if not records:
        raise ValueError("acceptance_evidence_missing")
    if len(records) != len(commands):
        raise ValueError("acceptance_command_mismatch")
    payload: list[dict[str, object]] = []
    for result, command in zip(records, commands, strict=True):
        if not isinstance(result, AcceptanceResult):
            raise ValueError("acceptance_evidence_invalid")
        record = asdict(result)
        if record.get("exit_code") != 0:
            raise ValueError("acceptance_failed")
        if not all(
            _is_hex(record.get(field), 64)
            for field in ("command_sha256", "stdout_sha256", "stderr_sha256")
        ) or not _is_hex(record.get("revision"), 40):
            raise ValueError("acceptance_evidence_invalid")
        if result.command_sha256 != acceptance_command_sha256(command):
            raise ValueError("acceptance_command_mismatch")
        if result.revision != candidate_commit:
            raise ValueError("acceptance_revision_mismatch")
        payload.append(record)
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return records, hashlib.sha256(b"CPE-ACCEPTANCE-V1\0" + raw).hexdigest()


def _validated_review_sha256(
    review: ReviewEvidence | None,
    contract: TaskContractV4,
    candidate: CandidateCheckpoint,
) -> str:
    if review is None:
        raise ValueError("review_evidence_missing")
    if not isinstance(review, ReviewEvidence):
        raise ValueError("review_evidence_invalid")
    if (
        review.task_id != contract.task_id
        or review.candidate_commit != candidate.commit
        or review.contract_sha256 != contract.contract_sha256
    ):
        raise ValueError("review_evidence_mismatch")
    if review.decision != "approved":
        raise ValueError("review_not_approved")
    if not _is_hex(review.review_content_sha256, 64):
        raise ValueError("review_evidence_invalid")
    expected = _review_artifact_sha256(
        task_id=review.task_id,
        candidate_commit=review.candidate_commit,
        contract_sha256=review.contract_sha256,
        decision=review.decision,
        review_content_sha256=review.review_content_sha256,
    )
    if review.artifact_sha256 != expected:
        raise ValueError("review_evidence_invalid")
    return review.artifact_sha256


def promote_verified_checkpoint(
    kernel: object,
    contract: TaskContractV4,
    candidate: CandidateCheckpoint,
    acceptance_results: Iterable[object],
    review_evidence: ReviewEvidence | None = None,
) -> VerifiedCheckpoint:
    """Promote only the recorded passing direct child of the checkpoint head."""

    _validate_contract(contract)
    state = getattr(kernel, "state")
    if candidate.task_id != contract.task_id:
        raise ValueError("candidate_task_mismatch")
    if candidate.contract_sha256 != contract.contract_sha256:
        raise ValueError("candidate_contract_mismatch")
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
    _records, acceptance_sha256 = _acceptance_digest(
        acceptance_results,
        contract.acceptance_commands,
        candidate.commit,
    )
    review_sha256 = _validated_review_sha256(review_evidence, contract, candidate)
    verified = VerifiedCheckpoint(
        task_id=contract.task_id,
        predecessor=candidate.predecessor,
        commit=candidate.commit,
        tree=candidate.tree,
        contract_sha256=contract.contract_sha256,
        acceptance_sha256=acceptance_sha256,
        review_sha256=review_sha256,
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
