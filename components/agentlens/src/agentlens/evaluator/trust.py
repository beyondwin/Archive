"""Trust report builder for Waygent projections."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from agentlens.constants import SCHEMA_TRUST_REPORT_V1


def _timeline_has(projection: Mapping[str, Any], event_type: str, *, status: str | None = None) -> bool:
    for item in projection.get("timeline", []):
        if not isinstance(item, Mapping) or item.get("type") != event_type:
            continue
        if status is None or item.get("status") == status:
            return True
    return False


def _missing_artifacts(projection: Mapping[str, Any]) -> list[dict[str, str]]:
    artifacts = projection.get("artifacts")
    if not isinstance(artifacts, Mapping):
        return [{"code": "missing_artifact_summary", "summary": "Artifact readiness was not projected."}]
    missing = []
    for key in ("contract", "artifact_graph", "coverage"):
        if artifacts.get(key) != "present":
            missing.append({"code": f"missing_{key}", "summary": f"{key} artifact was not present."})
    return missing


def build_trust_report(
    projection: Mapping[str, Any],
    *,
    claimed_outcome: str,
    residual_risks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    missing_evidence = _missing_artifacts(projection)
    projection_issues = list(projection.get("projection_issues") or [])
    operator_actions: list[dict[str, str]] = []
    blocking_evidence: list[dict[str, str]] = []
    status = str(projection.get("status") or "not_started")
    verification_passed = _timeline_has(
        projection, "runway.verification_result", status="passed"
    )

    if claimed_outcome == "success" and not verification_passed:
        missing_evidence.append(
            {
                "code": "missing_verification_pass",
                "summary": "Run claimed success without a passing verification result.",
            }
        )
        operator_actions.append(
            {
                "code": "rerun_verification",
                "summary": "Rerun Waygent verification before trusting the success claim.",
            }
        )

    emit_health = projection.get("agentlens_emit_health")
    if isinstance(emit_health, Mapping) and emit_health.get("last_status") in {
        "agentlens_disabled",
        "agentlens_failed",
    }:
        projection_issues.append(
            {
                "code": "agentlens_observability_degraded",
                "summary": f"AgentLens emission ended as {emit_health.get('last_status')}.",
            }
        )

    if status == "blocked":
        verdict = "blocked"
        strength = "weak"
        blocking_evidence.append({"code": "run_blocked", "summary": "Waygent reported a blocked run."})
    elif claimed_outcome == "success" and not verification_passed:
        verdict = "untrusted"
        strength = "insufficient"
    elif projection_issues:
        verdict = "degraded"
        strength = "weak" if missing_evidence else "adequate"
    elif missing_evidence:
        verdict = "partially_trusted"
        strength = "adequate"
    else:
        verdict = "trusted"
        strength = "strong"

    return {
        "schema": SCHEMA_TRUST_REPORT_V1,
        "run_id": str(projection.get("run_id") or ""),
        "waygent_run_id": projection.get("waygent_run_id"),
        "claimed_outcome": claimed_outcome,
        "trust_verdict": verdict,
        "evidence_strength": strength,
        "blocking_evidence": blocking_evidence,
        "missing_evidence": missing_evidence,
        "residual_risks": list(residual_risks or []),
        "operator_actions": operator_actions,
        "projection_issues": projection_issues,
    }


__all__ = ["build_trust_report"]
