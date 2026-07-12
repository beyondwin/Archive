"""Validated, digest-only cross-root predecessor lineage import."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from urllib.parse import quote

from live_model_migration import aggregate_run

from .contracts import canonical_json, sha256_bytes
from .ledger import (
    LedgerError,
    PREDECESSOR_ATTESTATION_DOMAIN,
    PREDECESSOR_ATTESTATION_SCHEMA,
    _commit_predecessor_attestation,
    load_registered_release_manifest,
    validate_release_lineage,
)
from .privacy import audit_sanitized_payload


_SHA256 = re.compile(r"[0-9a-f]{64}")
_GIT_OID = re.compile(r"[0-9a-f]{40}")


def _read_object(
    path: Path, label: str, *, canonical_required: bool = False
) -> dict[str, object]:
    if not path.is_file() or path.is_symlink():
        raise LedgerError(f"predecessor {label} is missing")
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LedgerError(f"predecessor {label} is invalid") from exc
    if not isinstance(value, dict):
        raise LedgerError(f"predecessor {label} must be an object")
    if canonical_required and raw != canonical_json(value):
        raise LedgerError(f"predecessor {label} is not canonical")
    return value


def _digest_file(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise LedgerError("predecessor digest artifact is missing")
    return sha256_bytes(path.read_bytes())


def _require_sha(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise LedgerError(f"predecessor {label} is invalid")
    return value


def _validate_git_identity(
    repository: Path, commit: str, tree: str, patch_sha256: str
) -> None:
    if _GIT_OID.fullmatch(commit) is None or _GIT_OID.fullmatch(tree) is None:
        raise LedgerError("predecessor implementation Git identity is invalid")
    resolved_commit = subprocess.run(
        ["git", "rev-parse", "--verify", f"{commit}^{{commit}}"],
        cwd=repository,
        text=True,
        capture_output=True,
        check=False,
    )
    resolved_tree = subprocess.run(
        ["git", "rev-parse", "--verify", f"{commit}^{{tree}}"],
        cwd=repository,
        text=True,
        capture_output=True,
        check=False,
    )
    patch = subprocess.run(
        ["git", "show", "--format=", "--binary", commit],
        cwd=repository,
        capture_output=True,
        check=False,
    )
    if (
        resolved_commit.returncode
        or resolved_tree.returncode
        or patch.returncode
        or resolved_commit.stdout.strip() != commit
        or resolved_tree.stdout.strip() != tree
        or sha256_bytes(patch.stdout) != patch_sha256
    ):
        raise LedgerError("predecessor implementation identity does not match Git")


def _validate_predecessor_root(
    predecessor_root: Path, repository_root: Path
) -> dict[str, object]:
    """Validate a real predecessor root in place and return only safe digests."""

    root = predecessor_root.expanduser().resolve()
    repository = repository_root.expanduser().resolve()
    if not root.is_dir() or root.is_symlink() or not repository.is_dir():
        raise LedgerError("predecessor evidence root is invalid")
    try:
        lineage = validate_release_lineage(root)
        runs = lineage.get("runs")
        if (
            lineage.get("event_count") != 2
            or lineage.get("terminal_full_runs") != 1
            or lineage.get("terminal_full_failures") != 1
            or lineage.get("release_passed") is not False
            or lineage.get("release_blocked") is not False
            or not isinstance(runs, list)
            or len(runs) != 1
        ):
            raise LedgerError("predecessor must contain exactly one terminal failed release")
        terminal = runs[0]
        if terminal.get("terminal") is not True or terminal.get("passed") is not False:
            raise LedgerError("predecessor release terminal verdict is ambiguous")
        run_id = terminal.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            raise LedgerError("predecessor run identity is invalid")
        registered_manifest = load_registered_release_manifest(root, run_id)
        if registered_manifest is None:
            raise LedgerError("predecessor registered manifest is missing")
        manifest_path = root / "quality-release-manifests" / f"{quote(run_id, safe='-._~')}.json"
        manifest_files = list((root / "quality-release-manifests").glob("*.json"))
        if manifest_files != [manifest_path]:
            raise LedgerError("predecessor manifest artifact set is invalid")
        if manifest_path.read_bytes() != canonical_json(registered_manifest):
            raise LedgerError("predecessor registered manifest bytes differ")
        child_manifest = _read_object(
            root / run_id / "manifest.json", "child manifest", canonical_required=True
        )
        if canonical_json(child_manifest) != canonical_json(registered_manifest):
            raise LedgerError("predecessor child and release manifests differ")

        aggregate = aggregate_run(root / run_id, repair_state=False)
        privacy = audit_sanitized_payload(aggregate)
        aggregate_payload = {**aggregate, "privacy_audit": privacy}
        stored_aggregate = _read_object(
            root / "aggregate.json", "aggregate", canonical_required=True
        )
        if canonical_json(stored_aggregate) != canonical_json(aggregate_payload):
            raise LedgerError("predecessor aggregate differs from the immutable ledger")
        aggregate_sha256 = sha256_bytes(canonical_json(aggregate))
        privacy_sha256 = sha256_bytes(canonical_json(privacy))
        manifest_sha256 = _require_sha(registered_manifest.get("manifest_sha256"), "manifest digest")
        if (
            terminal.get("manifest_sha256") != manifest_sha256
            or terminal.get("terminal_manifest_sha256") != manifest_sha256
            or terminal.get("aggregate_sha256") != aggregate_sha256
            or terminal.get("privacy_sha256") != privacy_sha256
            or aggregate.get("manifest_sha256") != manifest_sha256
            or not isinstance(aggregate.get("release_gate"), dict)
            or aggregate["release_gate"].get("passed") is not False
            or privacy != {"passed": True, "failures": []}
        ):
            raise LedgerError("predecessor terminal digest or verdict binding is invalid")

        release_manifest = _read_object(root / "manifest.json", "release manifest")
        release_result = _read_object(root / "result.json", "release result")
        external_privacy = _read_object(root / "privacy-audit.json", "privacy audit")
        dogfood = _read_object(root / "dogfood-result.json", "dogfood result")
        checkpoint = _read_object(root / "checkpoint.json", "release checkpoint")
        public_privacy = audit_sanitized_payload(
            {
                "release_manifest": release_manifest,
                "release_result": release_result,
                "privacy_audit": external_privacy,
                "dogfood_result": dogfood,
                "release_checkpoint": checkpoint,
            }
        )
        if public_privacy != {"passed": True, "failures": []}:
            raise LedgerError("predecessor sanitized release artifacts violate privacy")
        if (
            release_manifest.get("schema_version") != "cpe.release-manifest.v4"
            or release_result.get("schema_version") != "cpe.release-result.v4"
            or external_privacy.get("schema_version") != "cpe.privacy-audit.v4"
            or dogfood.get("schema_version") != "cpe.dogfood-result.v4"
            or checkpoint.get("schema_version") != "cpe.release-checkpoint.v4"
        ):
            raise LedgerError("predecessor sanitized release schema is invalid")
        commit = str(registered_manifest.get("implementation_commit") or "")
        tree = str(registered_manifest.get("implementation_tree") or "")
        patch_sha256 = _require_sha(
            registered_manifest.get("implementation_patch_sha256"), "implementation patch"
        )
        _validate_git_identity(repository, commit, tree, patch_sha256)
        identities = (release_manifest, release_result, aggregate)
        if any(
            item.get("implementation_commit") != commit
            or item.get("implementation_tree") != tree
            or item.get("implementation_patch_sha256") != patch_sha256
            for item in identities
        ):
            raise LedgerError("predecessor implementation bindings differ")
        if (
            checkpoint.get("commit") != commit
            or checkpoint.get("tree") != tree
            or external_privacy.get("implementation_commit") != commit
            or external_privacy.get("implementation_tree") != tree
            or external_privacy.get("passed") is not True
            or external_privacy.get("findings") != []
            or release_manifest.get("ledger_manifest_sha256") != manifest_sha256
            or release_manifest.get("terminal") is not True
            or release_result.get("release_gate") != aggregate.get("release_gate")
            or release_result.get("manifest_sha256")
            != sha256_bytes(canonical_json(release_manifest))
        ):
            raise LedgerError("predecessor sanitized release contract is invalid")
        for payload in (release_manifest, release_result, aggregate):
            if (
                payload.get("credentialed_call_count") != 17
                or payload.get("policy_outcome_count") != 7
                or payload.get("pending_slot_count") != 0
                or payload.get("duplicate_slot_count") != 0
            ):
                raise LedgerError("predecessor release counts are invalid")
        checkpoint_bindings = {
            "manifest_sha256": sha256_bytes(canonical_json(release_manifest)),
            "result_sha256": sha256_bytes(canonical_json(release_result)),
            "privacy_sha256": sha256_bytes(canonical_json(external_privacy)),
            "dogfood_sha256": sha256_bytes(canonical_json(dogfood)),
        }
        if any(checkpoint.get(key) != value for key, value in checkpoint_bindings.items()):
            raise LedgerError("predecessor release checkpoint digests are invalid")

        events_path = root / "quality-release-events.jsonl"
        state_path = root / "quality-release-state.json"
        body: dict[str, object] = {
            "schema_version": PREDECESSOR_ATTESTATION_SCHEMA,
            "domain": PREDECESSOR_ATTESTATION_DOMAIN,
            "predecessor_event_sha256": lineage["last_event_sha256"],
            "predecessor_events_sha256": _digest_file(events_path),
            "predecessor_state_sha256": _digest_file(state_path),
            "predecessor_manifest_sha256": manifest_sha256,
            "predecessor_manifest_artifact_sha256": _digest_file(manifest_path),
            "predecessor_aggregate_sha256": aggregate_sha256,
            "predecessor_aggregate_artifact_sha256": _digest_file(root / "aggregate.json"),
            "predecessor_privacy_sha256": privacy_sha256,
            "predecessor_privacy_artifact_sha256": _digest_file(root / "privacy-audit.json"),
            "terminal_full_runs": 1,
            "terminal_full_failures": 1,
            "prior_checkpoint": patch_sha256,
            "implementation_commit": commit,
            "implementation_tree": tree,
            "implementation_patch_sha256": patch_sha256,
        }
        return {
            **body,
            "attestation_sha256": sha256_bytes(
                canonical_json({"domain": PREDECESSOR_ATTESTATION_DOMAIN, "body": body})
            ),
        }
    except (LedgerError, OSError, ValueError, subprocess.SubprocessError) as exc:
        raise LedgerError("predecessor evidence validation failed") from exc


def attest_predecessor_release(
    new_root: Path,
    predecessor_root: Path,
    repository_root: Path,
    *,
    append_event_fn=None,
    write_state_fn=None,
) -> dict[str, object]:
    """Validate the source root first; callers cannot supply an invented summary."""

    target = new_root.expanduser().resolve()
    source = predecessor_root.expanduser().resolve()
    if target == source:
        raise LedgerError("predecessor and corrected evidence roots must differ")
    artifact = _validate_predecessor_root(source, repository_root)
    if audit_sanitized_payload(artifact) != {"passed": True, "failures": []}:
        raise LedgerError("predecessor attestation violates the privacy contract")
    event = _commit_predecessor_attestation(
        target,
        artifact,
        append_event_fn=append_event_fn,
        write_state_fn=write_state_fn,
    )
    return {
        "status": "predecessor_attested",
        "attestation_sha256": artifact["attestation_sha256"],
        "event_sha256": event["event_sha256"],
        "terminal_full_runs": 1,
        "terminal_full_failures": 1,
    }
