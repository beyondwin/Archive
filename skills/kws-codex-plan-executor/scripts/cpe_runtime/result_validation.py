"""Shared strict format-2 result-envelope validation."""

from __future__ import annotations

import json
import re
from typing import Any


RESULT_REQUIRED_FIELDS = {
    "plan_id", "status", "head_commit", "verification", "summary",
}
RESULT_OPTIONAL_FIELDS = {"checkpoint", "blocker", "workflow_receipt"}
RESULT_WIRE_FIELDS = RESULT_REQUIRED_FIELDS | RESULT_OPTIONAL_FIELDS
WORKFLOW_RECEIPT_FIELDS = {
    "ledger_path", "final_review_path", "final_review_head",
    "open_finding_ids", "open_obligation_ids",
}
VERIFICATION_FIELDS = {
    "command_id", "argv_digest", "phase", "evidence_key", "exit_code",
    "receipt_path",
}
_SHA = re.compile(r"^[0-9a-f]{40}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


def strict_json_object(payload: bytes) -> dict[str, object] | None:
    """Decode one JSON object while rejecting duplicate keys at every depth."""
    def object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON property")
            result[key] = value
        return result

    try:
        decoded = json.loads(payload, object_pairs_hook=object_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return None
    return decoded if isinstance(decoded, dict) else None


def _bounded_identifiers(value: object) -> bool:
    return (
        isinstance(value, list)
        and len(value) <= 1024
        and all(
            isinstance(item, str) and 0 < len(item) <= 128
            for item in value
        )
    )


def normalize_result_v2(
    payload: object,
) -> tuple[dict[str, Any] | None, str | None]:
    """Validate canonical format-2 shape without worktree semantics."""
    if not isinstance(payload, dict):
        return None, "invalid_result"
    normalized = dict(payload)
    for name in RESULT_OPTIONAL_FIELDS:
        if normalized.get(name) is None:
            normalized.pop(name, None)
    fields = set(normalized)
    if (
        not RESULT_REQUIRED_FIELDS.issubset(fields)
        or fields - RESULT_WIRE_FIELDS
    ):
        return None, "invalid_result"
    status = normalized.get("status")
    if status not in {"completed", "checkpointed", "blocked", "failed"}:
        return None, "invalid_result"
    if status == "completed" and "workflow_receipt" not in normalized:
        return None, "invalid_workflow_receipt"
    if status == "checkpointed" and "checkpoint" not in normalized:
        return None, "invalid_checkpoint"
    if status == "blocked" and "blocker" not in normalized:
        return None, "invalid_blocker"
    if status != "completed" and "workflow_receipt" in normalized:
        return None, "invalid_result"
    head = normalized.get("head_commit")
    summary = normalized.get("summary")
    verification = normalized.get("verification")
    if (
        not isinstance(normalized.get("plan_id"), str)
        or not isinstance(head, str)
        or not _SHA.fullmatch(head)
        or not isinstance(summary, str)
        or not summary.strip()
        or len(summary) > 2000
        or not isinstance(verification, list)
    ):
        return None, "invalid_result"
    for item in verification:
        if not isinstance(item, dict) or set(item) != VERIFICATION_FIELDS:
            return None, "invalid_result"
        receipt_path = item.get("receipt_path")
        if (
            not isinstance(item.get("command_id"), str)
            or not str(item["command_id"]).strip()
            or not isinstance(item.get("argv_digest"), str)
            or not _DIGEST.fullmatch(str(item["argv_digest"]))
            or not isinstance(item.get("evidence_key"), str)
            or not _DIGEST.fullmatch(str(item["evidence_key"]))
            or not isinstance(item.get("exit_code"), int)
            or isinstance(item.get("exit_code"), bool)
            or (
                receipt_path is not None
                and (
                    not isinstance(receipt_path, str)
                    or not receipt_path
                    or len(receipt_path) > 500
                )
            )
        ):
            return None, "invalid_result"
        if item.get("phase") not in {"task", "affected", "branch_final"}:
            return None, "invalid_verification_phase"
    receipt = normalized.get("workflow_receipt")
    if status == "completed":
        if not isinstance(receipt, dict) or set(receipt) != WORKFLOW_RECEIPT_FIELDS:
            return None, "invalid_workflow_receipt"
        if (
            not all(
                isinstance(receipt.get(name), str)
                and bool(receipt[name])
                and len(str(receipt[name])) <= 500
                for name in ("ledger_path", "final_review_path")
            )
            or not isinstance(receipt.get("final_review_head"), str)
            or not _SHA.fullmatch(str(receipt["final_review_head"]))
            or not _bounded_identifiers(receipt.get("open_finding_ids"))
            or not _bounded_identifiers(receipt.get("open_obligation_ids"))
        ):
            return None, "invalid_workflow_receipt"
    return normalized, None
