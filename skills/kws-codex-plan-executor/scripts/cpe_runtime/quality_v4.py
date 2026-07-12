from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence


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
    privacy_verdict: Mapping[str, object],
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
        "release_gate": aggregate.get("release_gate"),
        "envelope_sha256": envelope_map,
    }
    privacy = {
        "schema_version": "cpe.privacy-audit.v4",
        "implementation_commit": commit,
        "implementation_tree": tree,
        "passed": privacy_verdict.get("passed") is True,
        "findings": list(privacy_verdict.get("failures", ())),
    }
    dogfood_result = {
        **dict(dogfood),
        "implementation_commit": commit,
        "implementation_tree": tree,
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
    return {
        "manifest.json": release_manifest,
        "result.json": release_result,
        "privacy-audit.json": privacy,
        "dogfood-result.json": dogfood_result,
        "checkpoint.json": checkpoint,
    }
