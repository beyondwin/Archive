from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path

from .privacy import audit_sanitized_payload


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CASES = (
    "single-file implementation",
    "cross-package implementation",
    "root-cause repair",
    "defect review",
    "failed-test interpretation",
    "security/migration block",
    "resume/state repair",
    "large read-only exploration",
)
EXPECTED_V4_ENVELOPE_KEYS = frozenset(
    [f"sol_v31_control/{case_id}" for case_id in _CASES]
    + [f"sol_v4_candidate/{case_id}" for case_id in _CASES]
    + ["terra_v4/large read-only exploration"]
)

RELEASE_EVIDENCE_FILENAMES = (
    "checkpoint.json",
    "manifest.json",
    "result.json",
    "privacy-audit.json",
    "dogfood-result.json",
)
_CHECKPOINT_KEYS = frozenset(
    {
        "schema_version",
        "commit",
        "tree",
        "manifest_sha256",
        "result_sha256",
        "privacy_sha256",
        "dogfood_sha256",
    }
)
_MANIFEST_KEYS = frozenset(
    {
        "schema_version",
        "run_id",
        "implementation_commit",
        "implementation_tree",
        "implementation_patch_sha256",
        "ledger_manifest_sha256",
        "slot_count",
        "credentialed_call_count",
        "policy_outcome_count",
        "pending_slot_count",
        "duplicate_slot_count",
        "terminal",
        "envelope_sha256",
    }
)
_RESULT_KEYS = frozenset(
    {
        "schema_version",
        "run_id",
        "implementation_commit",
        "implementation_tree",
        "implementation_patch_sha256",
        "manifest_sha256",
        "credentialed_call_count",
        "policy_outcome_count",
        "pending_slot_count",
        "duplicate_slot_count",
        "release_gate",
        "envelope_sha256",
    }
)
_RELEASE_GATE_KEYS = frozenset(
    {"passed", "failures", "control_completed", "candidate_completed"}
)
_PRIVACY_KEYS = frozenset(
    {"schema_version", "implementation_commit", "implementation_tree", "passed", "findings"}
)
_DOGFOOD_INPUT_KEYS = frozenset(
    {
        "schema_version",
        "status",
        "run_ids_created",
        "model_attempts",
        "max_same_root_repairs",
        "verified_checkpoints",
        "elapsed_seconds",
        "source_checkout_unchanged",
        "runtime_patch_required",
    }
)
_DOGFOOD_KEYS = _DOGFOOD_INPUT_KEYS | {"implementation_commit", "implementation_tree"}


def _exact_keys(payload: Mapping[str, object], expected: frozenset[str], label: str) -> None:
    if set(payload) != expected or any(not isinstance(key, str) for key in payload):
        raise ValueError(f"quality_v4_{label}_schema_invalid")


def _is_int(value: object) -> bool:
    return type(value) is int


def _is_number(value: object) -> bool:
    return type(value) in {int, float}


def _sha256(value: object) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _git_oid(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value) is not None


def validate_v4_release_payloads(payloads: Mapping[str, Mapping[str, object]]) -> None:
    """Validate the exact five closed release schemas independently of their digests."""

    if set(payloads) != set(RELEASE_EVIDENCE_FILENAMES):
        raise ValueError("quality_v4_release_file_set_invalid")
    checkpoint = payloads["checkpoint.json"]
    manifest = payloads["manifest.json"]
    result = payloads["result.json"]
    privacy = payloads["privacy-audit.json"]
    dogfood = payloads["dogfood-result.json"]
    _exact_keys(checkpoint, _CHECKPOINT_KEYS, "checkpoint")
    _exact_keys(manifest, _MANIFEST_KEYS, "manifest")
    _exact_keys(result, _RESULT_KEYS, "result")
    _exact_keys(privacy, _PRIVACY_KEYS, "privacy")
    _exact_keys(dogfood, _DOGFOOD_KEYS, "dogfood")

    if (
        checkpoint["schema_version"] != "cpe.code-checkpoint.v4"
        or not _git_oid(checkpoint["commit"])
        or not _git_oid(checkpoint["tree"])
        or any(not _sha256(checkpoint[key]) for key in _CHECKPOINT_KEYS if key.endswith("_sha256"))
    ):
        raise ValueError("quality_v4_checkpoint_schema_invalid")
    if (
        manifest["schema_version"] != "cpe.release-manifest.v4"
        or not isinstance(manifest["run_id"], str)
        or not manifest["run_id"]
        or not _git_oid(manifest["implementation_commit"])
        or not _git_oid(manifest["implementation_tree"])
        or not _sha256(manifest["implementation_patch_sha256"])
        or not _sha256(manifest["ledger_manifest_sha256"])
        or manifest["slot_count"] != 24
        or manifest["credentialed_call_count"] != 17
        or manifest["policy_outcome_count"] != 7
        or not _is_int(manifest["pending_slot_count"])
        or manifest["pending_slot_count"] < 0
        or not _is_int(manifest["duplicate_slot_count"])
        or manifest["duplicate_slot_count"] < 0
        or type(manifest["terminal"]) is not bool
    ):
        raise ValueError("quality_v4_manifest_schema_invalid")
    canonical_v4_envelope_map(manifest)
    gate = result["release_gate"]
    if not isinstance(gate, Mapping):
        raise ValueError("quality_v4_result_schema_invalid")
    _exact_keys(gate, _RELEASE_GATE_KEYS, "release_gate")
    if (
        result["schema_version"] != "cpe.release-result.v4"
        or not isinstance(result["run_id"], str)
        or not result["run_id"]
        or not _git_oid(result["implementation_commit"])
        or not _git_oid(result["implementation_tree"])
        or not _sha256(result["implementation_patch_sha256"])
        or not _sha256(result["manifest_sha256"])
        or result["credentialed_call_count"] != 17
        or result["policy_outcome_count"] != 7
        or not _is_int(result["pending_slot_count"])
        or result["pending_slot_count"] < 0
        or not _is_int(result["duplicate_slot_count"])
        or result["duplicate_slot_count"] < 0
        or type(gate["passed"]) is not bool
        or not isinstance(gate["failures"], list)
        or any(not isinstance(item, str) for item in gate["failures"])
        or not _is_int(gate["control_completed"])
        or not _is_int(gate["candidate_completed"])
    ):
        raise ValueError("quality_v4_result_schema_invalid")
    canonical_v4_envelope_map(result)
    if (
        privacy["schema_version"] != "cpe.privacy-audit.v4"
        or not _git_oid(privacy["implementation_commit"])
        or not _git_oid(privacy["implementation_tree"])
        or type(privacy["passed"]) is not bool
        or not isinstance(privacy["findings"], list)
        or any(not isinstance(item, str) for item in privacy["findings"])
    ):
        raise ValueError("quality_v4_privacy_schema_invalid")
    status = dogfood["status"]
    if (
        dogfood["schema_version"] != "cpe.dogfood-result.v4"
        or status not in {"not_run", "passed", "failed"}
        or not _git_oid(dogfood["implementation_commit"])
        or not _git_oid(dogfood["implementation_tree"])
        or not _is_int(dogfood["run_ids_created"])
        or dogfood["run_ids_created"] < 0
        or not _is_int(dogfood["model_attempts"])
        or not 0 <= dogfood["model_attempts"] <= 6
        or not _is_int(dogfood["max_same_root_repairs"])
        or not 0 <= dogfood["max_same_root_repairs"] <= 2
        or not isinstance(dogfood["verified_checkpoints"], list)
        or any(not _git_oid(item) for item in dogfood["verified_checkpoints"])
        or not _is_number(dogfood["elapsed_seconds"])
        or not 0 <= dogfood["elapsed_seconds"] <= 3600
        or type(dogfood["source_checkout_unchanged"]) is not bool
        or type(dogfood["runtime_patch_required"]) is not bool
    ):
        raise ValueError("quality_v4_dogfood_schema_invalid")
    if status == "not_run" and any(
        (dogfood["run_ids_created"], dogfood["model_attempts"], dogfood["max_same_root_repairs"], dogfood["verified_checkpoints"], dogfood["elapsed_seconds"])
    ):
        raise ValueError("quality_v4_dogfood_schema_invalid")


def canonical_credentialed_semantic_verdict(result: Mapping[str, object]) -> bool:
    """Derive and verify the runner-owned hidden-oracle semantic verdict."""

    expected = result.get("review_accurate") is True
    supplied = result.get("semantic_verdict")
    if supplied is not None and supplied is not expected:
        raise ValueError("quality_v4_semantic_verdict_mismatch")
    return expected


def _canonical_sha256(payload: object) -> str:
    raw = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
    return hashlib.sha256(raw).hexdigest()


def canonical_v4_envelope_map(payload: Mapping[str, object]) -> dict[str, str]:
    """Validate and return the one sanitized envelope map for quality v4."""

    if not isinstance(payload, Mapping):
        raise ValueError("quality_v4_payload_invalid")
    supplied = payload.get("envelope_sha256")
    if not isinstance(supplied, Mapping):
        raise ValueError("quality_v4_envelope_map_missing")
    envelope_map = dict(supplied)
    if (
        set(envelope_map) != EXPECTED_V4_ENVELOPE_KEYS
        or any(not isinstance(key, str) for key in envelope_map)
        or any(not isinstance(value, str) or _SHA256.fullmatch(value) is None for value in envelope_map.values())
    ):
        raise ValueError("quality_v4_envelope_map_invalid")

    slots = payload.get("slots")
    if slots is not None:
        if not isinstance(slots, Sequence) or isinstance(slots, (str, bytes)):
            raise ValueError("quality_v4_slots_invalid")
        derived: dict[str, str] = {}
        for slot in slots:
            if not isinstance(slot, Mapping):
                raise ValueError("quality_v4_slot_invalid")
            key = f"{slot.get('treatment_id')}/{slot.get('case_id')}"
            if slot.get("credentialed") is True:
                digest = slot.get("envelope_sha256")
                if key in derived or not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
                    raise ValueError("quality_v4_credentialed_envelope_invalid")
                derived[key] = digest
            elif "envelope_sha256" in slot:
                raise ValueError("quality_v4_policy_envelope_forbidden")
        if derived != envelope_map:
            raise ValueError("quality_v4_envelope_map_mismatch")
    return {key: envelope_map[key] for key in sorted(envelope_map)}


def build_v4_release_evidence_payloads(
    manifest: Mapping[str, object],
    aggregate: Mapping[str, object],
    dogfood: Mapping[str, object],
) -> dict[str, dict[str, object]]:
    """Build the sanitized release package directly from compiled and aggregated evidence."""

    envelope_map = canonical_v4_envelope_map(manifest)
    if canonical_v4_envelope_map(aggregate) != envelope_map:
        raise ValueError("quality_v4_aggregate_envelope_mismatch")
    commit = manifest.get("implementation_commit")
    tree = manifest.get("implementation_tree")
    if not isinstance(commit, str) or not isinstance(tree, str):
        raise ValueError("quality_v4_checkpoint_missing")
    release_manifest = {
        "schema_version": "cpe.release-manifest.v4",
        "run_id": manifest.get("run_id"),
        "implementation_commit": commit,
        "implementation_tree": tree,
        "implementation_patch_sha256": manifest.get("implementation_patch_sha256"),
        "ledger_manifest_sha256": manifest.get("manifest_sha256"),
        "slot_count": len(manifest.get("slots", ())),
        "credentialed_call_count": manifest.get("credentialed_call_count"),
        "policy_outcome_count": manifest.get("expected_policy_failure_count"),
        "pending_slot_count": aggregate.get("pending_slot_count"),
        "duplicate_slot_count": aggregate.get("duplicate_slot_count"),
        "terminal": aggregate.get("pending_slot_count") == 0,
        "envelope_sha256": envelope_map,
    }
    canonical_v4_envelope_map(release_manifest)
    aggregate_gate = aggregate.get("release_gate")
    if not isinstance(aggregate_gate, Mapping):
        raise ValueError("quality_v4_aggregate_gate_invalid")
    _exact_keys(aggregate_gate, _RELEASE_GATE_KEYS, "aggregate_gate")
    release_result = {
        "schema_version": "cpe.release-result.v4",
        "run_id": manifest.get("run_id"),
        "implementation_commit": commit,
        "implementation_tree": tree,
        "implementation_patch_sha256": manifest.get("implementation_patch_sha256"),
        "manifest_sha256": _canonical_sha256(release_manifest),
        "credentialed_call_count": aggregate.get("credentialed_call_count"),
        "policy_outcome_count": aggregate.get("policy_outcome_count"),
        "pending_slot_count": aggregate.get("pending_slot_count"),
        "duplicate_slot_count": aggregate.get("duplicate_slot_count"),
        "release_gate": {
            "passed": aggregate_gate.get("passed"),
            "failures": list(aggregate_gate.get("failures", ())),
            "control_completed": aggregate_gate.get("control_completed"),
            "candidate_completed": aggregate_gate.get("candidate_completed"),
        },
        "envelope_sha256": envelope_map,
    }
    _exact_keys(dogfood, _DOGFOOD_INPUT_KEYS, "dogfood_input")
    dogfood_result = {
        "schema_version": dogfood.get("schema_version"),
        "status": dogfood.get("status"),
        "implementation_commit": commit,
        "implementation_tree": tree,
        "run_ids_created": dogfood.get("run_ids_created"),
        "model_attempts": dogfood.get("model_attempts"),
        "max_same_root_repairs": dogfood.get("max_same_root_repairs"),
        "verified_checkpoints": list(dogfood.get("verified_checkpoints", ())),
        "elapsed_seconds": dogfood.get("elapsed_seconds"),
        "source_checkout_unchanged": dogfood.get("source_checkout_unchanged"),
        "runtime_patch_required": dogfood.get("runtime_patch_required"),
    }
    pre_privacy = {
        "manifest.json": release_manifest,
        "result.json": release_result,
        "dogfood-result.json": dogfood_result,
    }
    privacy_verdict = audit_sanitized_payload(pre_privacy)
    privacy = {
        "schema_version": "cpe.privacy-audit.v4",
        "implementation_commit": commit,
        "implementation_tree": tree,
        "passed": privacy_verdict["passed"],
        "findings": list(privacy_verdict["failures"]),
    }
    checkpoint = {
        "schema_version": "cpe.code-checkpoint.v4",
        "commit": commit,
        "tree": tree,
        "manifest_sha256": _canonical_sha256(release_manifest),
        "result_sha256": _canonical_sha256(release_result),
        "privacy_sha256": _canonical_sha256(privacy),
        "dogfood_sha256": _canonical_sha256(dogfood_result),
    }
    payloads = {
        "manifest.json": release_manifest,
        "result.json": release_result,
        "privacy-audit.json": privacy,
        "dogfood-result.json": dogfood_result,
        "checkpoint.json": checkpoint,
    }
    final_privacy = audit_sanitized_payload(payloads)
    if final_privacy != privacy_verdict:
        privacy["passed"] = final_privacy["passed"]
        privacy["findings"] = list(final_privacy["failures"])
        checkpoint["privacy_sha256"] = _canonical_sha256(privacy)
    validate_v4_release_payloads(payloads)
    return payloads


def write_v4_release_evidence_payloads(
    root: Path, payloads: Mapping[str, Mapping[str, object]]
) -> None:
    """Atomically replace each member of the one closed release byte set."""

    validate_v4_release_payloads(payloads)
    root = root.expanduser().resolve()
    if not root.is_dir() or root.is_symlink():
        raise ValueError("quality_v4_release_root_invalid")
    staged = Path(tempfile.mkdtemp(prefix=".cpe-release-v4-", dir=root))
    try:
        for name in RELEASE_EVIDENCE_FILENAMES:
            (staged / name).write_bytes(
                (json.dumps(payloads[name], sort_keys=True, separators=(",", ":")) + "\n").encode()
            )
        for name in RELEASE_EVIDENCE_FILENAMES:
            os.replace(staged / name, root / name)
    finally:
        shutil.rmtree(staged, ignore_errors=True)
