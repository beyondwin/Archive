"""Production-owned CPE v4 release finalization transaction."""

from __future__ import annotations

import json
from pathlib import Path

from cpe_runtime.dogfood_v4 import retain_v4_dogfood_run, verify_v4_dogfood_run
from cpe_runtime.manifest import load_verified_manifest
from cpe_runtime.release_policy_v4 import load_release_policy, validate_release_checkpoint
from cpe_runtime.release_policy_vnext import load_trust_root
from cpe_runtime.quality_v4 import (
    RELEASE_EVIDENCE_FILENAMES,
    build_v4_release_evidence_payloads,
)

from .contracts import canonical_json, sha256_bytes
from .compiler import require_trust_root
from .ledger import (
    LedgerError,
    finalize_release_generation,
    load_registered_release_manifest,
)


def _verify_implementation(manifest: dict[str, object], repository: Path):
    commit = str(manifest.get("implementation_commit") or "")
    base = str(manifest.get("implementation_base_commit") or "")
    tree = str(manifest.get("implementation_tree") or "")
    patch = str(manifest.get("implementation_patch_sha256") or "")
    if "trust_root_sha256" in manifest:
        try:
            trust_root = load_trust_root(repository, commit)
            require_trust_root(manifest, trust_root)
            if (
                base != trust_root.trusted_base_commit
                or tree != trust_root.reviewed_tree
                or patch != trust_root.patch_sha256
            ):
                raise ValueError("release trust root checkpoint differs")
            return trust_root
        except ValueError as exc:
            raise LedgerError("release_trust_root_mismatch") from exc
    try:
        policy = load_release_policy()
        if base != policy["trusted_base_commit"]:
            raise ValueError("release base differs from policy")
        validate_release_checkpoint(
            repository,
            commit,
            implementation_tree=tree,
            implementation_patch_sha256=patch,
            policy=policy,
        )
        if manifest.get("release_policy_sha256") != policy["policy_sha256"]:
            raise ValueError("release policy digest differs")
    except ValueError as exc:
        raise LedgerError("release implementation checkpoint violates tracked policy") from exc
    return None


def finalize_v4_release(
    *,
    evidence_root: Path,
    run_dir: Path,
    dogfood_run_dir: Path,
    repository: Path,
    crash_at: str | None = None,
) -> dict[str, object]:
    """Recompute all gates and publish the one terminal release generation."""

    from live_model_migration import aggregate_run

    root = evidence_root.expanduser().resolve()
    child = run_dir.expanduser().resolve()
    repo = repository.expanduser().resolve()
    if child.parent != root or not child.is_dir() or child.is_symlink():
        raise LedgerError("release child run is outside the evidence root")
    manifest = json.loads((child / "manifest.json").read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise LedgerError("release child manifest is invalid")
    registered = load_registered_release_manifest(root, str(manifest.get("run_id") or ""))
    if registered is None or canonical_json(registered) != canonical_json(manifest):
        raise LedgerError("release child manifest differs from registration")
    trust_root = _verify_implementation(manifest, repo)
    policy = load_release_policy() if trust_root is None else None
    aggregate = aggregate_run(child)
    profile = manifest.get("proof_profile", "full_paid_matrix")
    exact = (2, 7) if profile == "critical_path_live" else (17, 7)
    gate = aggregate.get("release_gate")
    if (
        profile not in {"critical_path_live", "full_paid_matrix"}
        or aggregate.get("credentialed_call_count") != exact[0]
        or aggregate.get("policy_outcome_count") != exact[1]
        or aggregate.get("pending_slot_count") != 0
        or aggregate.get("duplicate_slot_count") != 0
        or not isinstance(gate, dict)
        or gate.get("passed") is not True
        or gate.get("failures") != []
    ):
        raise LedgerError("release critical-path aggregate gate failed")
    dogfood_manifest = load_verified_manifest(
        dogfood_run_dir.expanduser().resolve() / "run_manifest.json"
    )
    tasks = dogfood_manifest.get("task_graph")
    if not isinstance(tasks, list) or len(tasks) != 1:
        raise LedgerError("release dogfood task contract is invalid")
    task_contract_sha256 = (
        str(policy["dogfood_task_contract_sha256"])
        if policy is not None
        else trust_root.dogfood_contract.sha256
    )
    if tasks[0].get("task_contract_sha256") != task_contract_sha256:
        raise LedgerError("release dogfood task contract is invalid")
    dogfood = verify_v4_dogfood_run(
        dogfood_run_dir,
        expected_implementation_commit=str(manifest["implementation_commit"]),
        expected_implementation_tree=str(manifest["implementation_tree"]),
        expected_task_contract_sha256=task_contract_sha256,
        expected_trust_root_sha256=(
            trust_root.trust_root_sha256 if trust_root is not None else None
        ),
    )
    dogfood_limit = (
        int(policy["dogfood_attempt_limit"])
        if policy is not None
        else int(trust_root.attempt_ceilings["dogfood"])
    )
    if int(dogfood.get("model_attempts") or 0) > dogfood_limit:
        raise LedgerError("release dogfood attempt budget exceeded")
    if profile == "critical_path_live":
        critical_limit = (
            int(policy["critical_matrix_attempt_limit"])
            if policy is not None
            else int(trust_root.attempt_ceilings["critical_matrix"])
        )
        combined_limit = (
            int(policy["combined_attempt_limit"])
            if policy is not None
            else int(trust_root.attempt_ceilings["combined"])
        )
        if int(aggregate.get("credentialed_call_count") or 0) > critical_limit:
            raise LedgerError("release critical matrix attempt budget exceeded")
        if int(aggregate.get("credentialed_call_count") or 0) + int(dogfood.get("model_attempts") or 0) > combined_limit:
            raise LedgerError("release combined attempt budget exceeded")
    retained = root / "dogfood" / str(dogfood_manifest["run_id"])
    retained_checkpoint = retain_v4_dogfood_run(
        dogfood_run_dir,
        retained,
        expected_implementation_commit=str(manifest["implementation_commit"]),
        expected_implementation_tree=str(manifest["implementation_tree"]),
        expected_task_contract_sha256=task_contract_sha256,
        task_contract_path=(
            Path(str(policy["dogfood_task_contract_absolute_path"]))
            if policy is not None
            else repo / trust_root.dogfood_contract.path
        ),
        expected_trust_root_sha256=(
            trust_root.trust_root_sha256 if trust_root is not None else None
        ),
    )
    dogfood = {
        **dogfood,
        "retained_run_id": str(dogfood_manifest["run_id"]),
        "retained_checkpoint_sha256": sha256_bytes(canonical_json(retained_checkpoint)),
    }
    dogfood_for_builder = {
        key: value for key, value in dogfood.items() if key != "trust_root_sha256"
    }
    payloads = build_v4_release_evidence_payloads(
        manifest, aggregate, dogfood_for_builder
    )
    if trust_root is not None:
        for name in ("manifest.json", "result.json", "dogfood-result.json"):
            payloads[name]["trust_root_sha256"] = trust_root.trust_root_sha256
        payloads["result.json"]["manifest_sha256"] = sha256_bytes(
            canonical_json(payloads["manifest.json"])
        )
        for key, name in (
            ("manifest_sha256", "manifest.json"),
            ("result_sha256", "result.json"),
            ("dogfood_sha256", "dogfood-result.json"),
        ):
            payloads["checkpoint.json"][key] = sha256_bytes(
                canonical_json(payloads[name])
            )
    payload_bytes = {
        name: canonical_json(payloads[name]) for name in RELEASE_EVIDENCE_FILENAMES
    }
    event = finalize_release_generation(
        root,
        run_id=str(manifest["run_id"]),
        payload_bytes=payload_bytes,
        child_manifest_sha256=str(manifest["manifest_sha256"]),
        aggregate_sha256=sha256_bytes(canonical_json(aggregate)),
        dogfood_sha256=sha256_bytes(payload_bytes["dogfood-result.json"]),
        checkpoint_sha256=sha256_bytes(payload_bytes["checkpoint.json"]),
        privacy_sha256=sha256_bytes(payload_bytes["privacy-audit.json"]),
        proof_profile=str(profile),
        trust_root=trust_root,
        crash_at=crash_at,
    )
    generation_sha256 = event["payload"]["generation_sha256"]
    return {
        "status": "critical-path-live verified"
        if profile == "critical_path_live"
        else "full paid-live certification verified",
        "proof_profile": profile,
        "run_id": manifest["run_id"],
        "generation_sha256": generation_sha256,
        "full_paid_matrix_status": (
            "full paid-live certification verified"
            if profile == "full_paid_matrix"
            else "full paid-live certification deferred"
        ),
    }
