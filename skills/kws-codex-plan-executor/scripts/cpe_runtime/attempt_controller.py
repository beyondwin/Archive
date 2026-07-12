from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Generic, TypeVar
from typing import TYPE_CHECKING

from .events import read_events
from .git_delta import (
    INVALID_GIT_HEAD,
    GitDelta,
    capture_snapshot,
    diff_snapshots,
    scope_errors,
)
from .manifest import load_verified_manifest
from .packets import PACKET_ROLE_POLICY
from .projector import project

if TYPE_CHECKING:
    from .kernel import Kernel
    from .worker import WorkerRequest


T = TypeVar("T")


@dataclass(frozen=True)
class RolePolicy:
    read_only: bool
    verdict_capable: bool
    product_write: bool


ROLE_POLICIES = {
    role: RolePolicy(
        bool(policy["read_only"]),
        bool(policy["verdict_capable"]),
        bool(policy["product_write"]),
    )
    for role, policy in PACKET_ROLE_POLICY.items()
}


@dataclass(frozen=True)
class WriteAttemptOutcome(Generic[T]):
    result: T | None
    delta: GitDelta
    scope_errors: tuple[str, ...]
    worktree_revision: int
    patch_ref: dict[str, str] | None
    error: Exception | None = None


class AttemptController:
    def __init__(self, kernel: Kernel, worktree: Path, worker: object | None = None):
        self.kernel = kernel
        self.worktree = worktree.expanduser().resolve()
        self.worker = worker

    def _revision(self) -> int:
        manifest = load_verified_manifest(self.kernel.run_dir / "run_manifest.json")
        state = project(manifest, read_events(self.kernel.run_dir / "events.jsonl"))
        return int(state["worktree_revision"])

    def run_write_attempt(
        self,
        *,
        task_id: str,
        attempt_id: str,
        role: str,
        allowed: list[str],
        forbidden: list[str],
        operation: Callable[[], T],
    ) -> WriteAttemptOutcome[T]:
        normalized = canonical_role(role)
        policy = ROLE_POLICIES.get(normalized)
        if policy is None or not policy.product_write or policy.read_only:
            raise ValueError("run_write_attempt requires a product-write role")
        before = capture_snapshot(self.worktree)
        result: T | None = None
        error: Exception | None = None
        try:
            result = operation()
        except Exception as exc:
            error = exc
        finally:
            after = capture_snapshot(self.worktree, tolerate_invalid_git=True)
            if (
                after.head == INVALID_GIT_HEAD or not after._git_metadata_valid
            ) and error is None:
                error = RuntimeError("post-write git metadata is invalid")
            if not after._filesystem_valid and error is None:
                error = RuntimeError("post-write filesystem content is not fully readable")
            delta = diff_snapshots(before, after, self.worktree)
            revision = self._revision()
            patch_ref = None
            if delta.changed_files or delta.head_changed:
                patch_ref = self.kernel.store_patch_evidence(delta.patch_bytes)
                worker_files: list[str] = []
                payload = getattr(result, "payload", None)
                if isinstance(payload, dict) and isinstance(payload.get("changed_files"), list):
                    worker_files = [str(path) for path in payload["changed_files"]]
                from .kernel import Transition

                self.kernel.transition(
                    Transition(
                        "worktree.revision_recorded",
                        {
                            "from": revision,
                            "to": revision + 1,
                            "task_id": task_id,
                            "attempt_id": attempt_id,
                            "changed_files": list(delta.changed_files),
                            "worker_reported_changed_files": worker_files,
                            "patch_sha256": delta.patch_sha256,
                            "patch_ref": patch_ref,
                        },
                        task_id=task_id,
                        attempt_id=attempt_id,
                    )
                )
                revision += 1
        errors = tuple(scope_errors(delta, allowed, forbidden))
        return WriteAttemptOutcome(result, delta, errors, revision, patch_ref, error)


@dataclass(frozen=True)
class ModelTurnOutcome(Generic[T]):
    result: T
    attempt_id: str
    started_new_attempt: bool


class ModelAttemptController:
    """Record model budget only across the actual provider-turn boundary."""

    def __init__(self, kernel: Kernel):
        self.kernel = kernel

    def _active_attempt(self, task_id: str, kind: str) -> str | None:
        matching = [
            item
            for item in self.kernel.state.get("attempts", [])
            if item.get("task_id") == task_id
            and item.get("kind") == kind
            and item.get("status") == "started"
        ]
        if len(matching) > 1:
            raise ValueError("active_model_attempt_ambiguous")
        return str(matching[0]["attempt_id"]) if matching else None

    def _next_attempt_id(self, task_id: str, kind: str) -> str:
        ordinal = 1 + sum(
            1
            for item in self.kernel.state.get("attempts", [])
            if item.get("task_id") == task_id and item.get("kind") == kind
        )
        return f"{task_id}.{kind}.{ordinal}"

    def interrupt_active(self, *, task_id: str, kind: str, reason: str) -> None:
        from .evidence import put_json
        from .kernel import Transition

        attempt_id = self._active_attempt(task_id, kind)
        if attempt_id is None:
            return
        digest = hashlib.sha256(reason.encode("utf-8", "replace")).hexdigest()
        ref = put_json(
            self.kernel.run_dir,
            "model_interruption",
            {
                "task_id": task_id,
                "attempt_id": attempt_id,
                "kind": kind,
                "error_type": "evidence_integrity_failure",
                "message_sha256": digest,
            },
        ).as_dict()
        self.kernel.transition(
            Transition(
                "evidence.attached",
                {"kind": "model_interruption", "ref": ref},
                task_id=task_id,
                attempt_id=attempt_id,
            )
        )
        self.kernel.transition(
            Transition(
                "attempt.completed",
                {
                    "status": "interrupted",
                    "attestation": {},
                    "usage": {},
                    "latency_ms": 0,
                    "evidence_refs": [ref],
                },
                task_id=task_id,
                attempt_id=attempt_id,
            )
        )

    def run_model_turn(
        self,
        *,
        task_id: str,
        kind: str,
        before_turn: Callable[[str, str], None],
        operation: Callable[[str], T],
        preserve_attempt_on: tuple[type[Exception], ...] = (),
        on_turn_started: Callable[[str, str, bool], None] | None = None,
    ) -> ModelTurnOutcome[T]:
        from .kernel import Transition

        active = self._active_attempt(task_id, kind)
        attempt_id = active or self._next_attempt_id(task_id, kind)
        before_turn(kind, attempt_id)
        started_new = active is None
        if started_new:
            budget = self.kernel.state.get("attempt_budget") or {}
            if int(budget.get("used", 0)) >= int(budget.get("limit", 40)):
                raise ValueError("attempt_budget_exhausted")
            self.kernel.transition(
                Transition(
                    "attempt.started",
                    {"kind": kind},
                    task_id=task_id,
                    attempt_id=attempt_id,
                )
            )
        try:
            if on_turn_started is not None:
                on_turn_started(kind, attempt_id, started_new)
            result = operation(attempt_id)
        except preserve_attempt_on:
            raise
        except Exception as exc:
            from .evidence import put_json

            digest = hashlib.sha256(
                f"{type(exc).__name__}:{exc}".encode("utf-8", "replace")
            ).hexdigest()
            run_dir = getattr(self.kernel, "run_dir", None)
            if not isinstance(run_dir, Path):
                raise RuntimeError("model_interruption_evidence_unavailable") from exc
            ref = put_json(
                run_dir,
                "model_interruption",
                {
                    "task_id": task_id,
                    "attempt_id": attempt_id,
                    "kind": kind,
                    "error_type": type(exc).__name__,
                    "message_sha256": digest,
                },
            ).as_dict()
            self.kernel.transition(
                Transition(
                    "evidence.attached",
                    {"kind": "model_interruption", "ref": ref},
                    task_id=task_id,
                    attempt_id=attempt_id,
                )
            )
            self.kernel.transition(
                Transition(
                    "attempt.completed",
                    {
                        "status": "interrupted",
                        "attestation": {},
                        "usage": {},
                        "latency_ms": 0,
                        "evidence_refs": [ref],
                    },
                    task_id=task_id,
                    attempt_id=attempt_id,
                )
            )
            raise

        attestation = getattr(result, "attestation", {})
        usage = getattr(result, "usage", {})
        latency_ms = getattr(result, "latency_ms", 0)
        payload = getattr(result, "payload", {})
        evidence_refs = payload.get("evidence_refs", []) if isinstance(payload, dict) else []
        self.kernel.transition(
            Transition(
                "attempt.completed",
                {
                    "status": "completed",
                    "attestation": dict(attestation) if isinstance(attestation, dict) else {},
                    "usage": dict(usage) if isinstance(usage, dict) else {},
                    "latency_ms": max(0, int(latency_ms or 0)),
                    "evidence_refs": list(evidence_refs) if isinstance(evidence_refs, list) else [],
                },
                task_id=task_id,
                attempt_id=attempt_id,
            )
        )
        return ModelTurnOutcome(result, attempt_id, started_new)


def canonical_role(role: str) -> str:
    """Normalize historical input without reviving it as an active role."""
    return "task_review" if role == "review" else role


def _worker_error(message: str):
    from .worker import WorkerError

    return WorkerError(message)


def validate_role_request(role: str, request: WorkerRequest) -> RolePolicy:
    normalized = canonical_role(role)
    policy = ROLE_POLICIES.get(normalized)
    if policy is None:
        raise _worker_error(f"unknown worker role: {role}")
    if request.read_only != policy.read_only or request.verdict_capable != policy.verdict_capable:
        raise _worker_error("worker request violates role policy")
    digest = request.packet_sha256
    digest_valid = (
        isinstance(digest, str)
        and len(digest) == 64
        and all(character in "0123456789abcdef" for character in digest)
    )
    if (
        not request.task_id
        or not request.packet_path
        or not digest_valid
        or not isinstance(request.worktree_revision, int)
        or isinstance(request.worktree_revision, bool)
        or request.worktree_revision < 0
    ):
        raise _worker_error("worker request is not packet-bound")
    return policy


def _nonempty_text(payload: dict[str, object], key: str) -> bool:
    return isinstance(payload.get(key), str) and bool(str(payload[key]).strip())


def validate_verdict(
    payload: object,
    role: str,
    revision: int,
) -> dict[str, object]:
    normalized_role = canonical_role(role)
    policy = ROLE_POLICIES.get(normalized_role)
    if policy is None:
        raise _worker_error(f"unknown worker role: {role}")
    if not policy.verdict_capable:
        raise _worker_error(f"role {normalized_role} cannot issue a verdict")
    if not isinstance(payload, dict):
        raise _worker_error("verdict-capable role requires a verdict")

    status = payload.get("status")
    if status not in {"passed", "changes_requested", "blocked", "inconclusive"}:
        raise _worker_error("verdict status is invalid")
    findings = payload.get("findings")
    missing_evidence = payload.get("missing_evidence")
    if not isinstance(findings, list) or not all(isinstance(item, dict) for item in findings):
        raise _worker_error("verdict findings are invalid")
    if not isinstance(missing_evidence, list):
        raise _worker_error("verdict missing_evidence is invalid")
    verdict_revision = payload.get("worktree_revision")
    if (
        not isinstance(verdict_revision, int)
        or isinstance(verdict_revision, bool)
        or verdict_revision != revision
    ):
        raise _worker_error("verdict revision is stale")

    if status == "passed":
        if any(str(item.get("severity", "")).lower() == "critical" for item in findings):
            raise _worker_error("passed verdict conflicts with critical findings")
        if missing_evidence:
            raise _worker_error("passed verdict conflicts with missing evidence")
    elif status == "changes_requested":
        actionable = any(
            any(
                isinstance(item.get(key), str) and bool(str(item[key]).strip())
                for key in ("action", "suggested_fix", "recommendation")
            )
            for item in findings
        )
        if not actionable:
            raise _worker_error("changes_requested verdict requires an actionable finding")
    elif status == "blocked":
        if not _nonempty_text(payload, "owner") or not _nonempty_text(payload, "resume_condition"):
            raise _worker_error("blocked verdict requires owner and resume_condition")
    elif status == "inconclusive" and not _nonempty_text(payload, "next_evidence_action"):
        raise _worker_error("inconclusive verdict requires next_evidence_action")

    return dict(payload)
