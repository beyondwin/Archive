from __future__ import annotations

from dataclasses import dataclass


ALLOWED_FAILURE_CATEGORIES = frozenset(
    {
        "preflight",
        "environment",
        "transient",
        "implementation",
        "review",
        "verification",
        "policy_violation",
        "state_integrity",
        "operator_review",
    }
)


@dataclass(frozen=True)
class PublicResult:
    """The single machine-readable result returned by public execution modes."""

    status: str
    run_id: str | None
    state_path: str | None
    summary: str
    changed_files: tuple[str, ...] = ()
    verification: tuple[dict[str, object], ...] = ()
    open_gaps: tuple[str, ...] = ()
    residual_risk: tuple[str, ...] = ()
    context_artifacts: dict[str, str | None] | None = None
    next_action: str = "Inspect the result."
    blocker: dict[str, object] | None = None
    failure_decision: dict[str, object] | None = None

    def __post_init__(self) -> None:
        if self.status not in {"success", "blocked", "failed"}:
            raise ValueError("invalid public result status")
        if not self.summary.strip() or not self.next_action.strip():
            raise ValueError("public result text must be non-empty")
        if self.status == "success" and (not self.run_id or not self.state_path):
            raise ValueError("successful public result requires run and state paths")
        if self.status == "success" and (self.blocker is not None or self.failure_decision is not None):
            raise ValueError("successful public result forbids failure details")
        if self.status == "blocked" and self.failure_decision is not None:
            raise ValueError("blocked public result forbids failure_decision")
        if self.status == "failed" and self.blocker is not None:
            raise ValueError("failed public result forbids blocker")
        required = self.blocker if self.status == "blocked" else self.failure_decision if self.status == "failed" else None
        if self.status != "success" and not isinstance(required, dict):
            raise ValueError(f"{self.status} public result requires structured failure details")
        if isinstance(required, dict) and required.get("category") not in ALLOWED_FAILURE_CATEGORIES:
            raise ValueError("invalid public failure category")

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "status": self.status,
            "run_id": self.run_id,
            "state_path": self.state_path,
            "summary": self.summary,
            "changed_files": list(self.changed_files),
            "verification": [dict(item) for item in self.verification],
            "open_gaps": list(self.open_gaps),
            "residual_risk": list(self.residual_risk),
            "context_artifacts": self.context_artifacts
            or {
                "spec_manifest_path": None,
                "task_packet_dir": None,
                "decisions_path": None,
            },
            "next_action": self.next_action,
        }
        if self.blocker is not None:
            payload["blocker"] = dict(self.blocker)
        if self.failure_decision is not None:
            payload["failure_decision"] = dict(self.failure_decision)
        return payload

    def exit_code(self) -> int:
        return 0 if self.status == "success" else 1 if self.status == "blocked" else 2


def blocked_result(
    summary: str,
    *,
    category: str,
    run_id: str | None = None,
    state_path: str | None = None,
    recoverable: bool = True,
    next_action: str = "Resolve the blocker and resume the run.",
    evidence_refs: tuple[dict[str, object], ...] = (),
) -> PublicResult:
    return PublicResult(
        status="blocked",
        run_id=run_id,
        state_path=state_path,
        summary=summary,
        open_gaps=(summary,),
        next_action=next_action,
        blocker={
            "category": category,
            "summary": summary,
            "recoverable": recoverable,
            "next_action": next_action,
            "evidence_refs": [dict(item) for item in evidence_refs],
        },
    )


def failed_result(
    summary: str,
    *,
    category: str,
    run_id: str | None = None,
    state_path: str | None = None,
    recoverable: bool = False,
    next_action: str = "Inspect evidence before retrying.",
    evidence_refs: tuple[dict[str, object], ...] = (),
) -> PublicResult:
    return PublicResult(
        status="failed",
        run_id=run_id,
        state_path=state_path,
        summary=summary,
        open_gaps=(summary,),
        next_action=next_action,
        failure_decision={
            "category": category,
            "decision": "failed",
            "reason": summary,
            "recoverable": recoverable,
            "next_action": next_action,
            "evidence_refs": [dict(item) for item in evidence_refs],
        },
    )
