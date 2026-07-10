from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .packets import PACKET_ROLE_POLICY

if TYPE_CHECKING:
    from .worker import WorkerRequest


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
