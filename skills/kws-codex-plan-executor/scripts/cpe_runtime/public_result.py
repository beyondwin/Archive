from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .privacy import audit_sanitized_payload
from .dogfood_v4 import verify_retained_v4_dogfood_run
from .release_policy_v4 import load_release_policy, validate_release_checkpoint
from .quality_v4 import (
    canonical_v4_envelope_map,
    validate_v4_release_payloads,
)


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


def _canonical_sha256(payload: object) -> str:
    raw = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
    return hashlib.sha256(raw).hexdigest()


def trusted_release_repository_root(validator_path: Path) -> Path:
    """Derive the tracked Git checkout that contains the public validator."""

    validator = validator_path.expanduser().resolve()
    if not validator.is_file():
        raise ValueError("release_validator_path_invalid")
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=validator.parent,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode:
        raise ValueError("release_validator_repository_invalid")
    root = Path(result.stdout.strip()).resolve()
    try:
        relative = validator.relative_to(root)
    except ValueError as exc:
        raise ValueError("release_validator_repository_invalid") from exc
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", relative.as_posix()],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if tracked.returncode or tracked.stdout.strip() != relative.as_posix():
        raise ValueError("release_validator_repository_invalid")
    return root


def validate_release_evidence_root(
    root: Path, implementation_commit: str, workspace: Path
) -> dict[str, object]:
    """Validate the immutable Task 10 evidence against its reviewed checkpoint."""

    root = root.expanduser().resolve()
    names = {
        "checkpoint": "checkpoint.json",
        "manifest": "manifest.json",
        "result": "result.json",
        "privacy": "privacy-audit.json",
        "dogfood": "dogfood-result.json",
    }
    if not root.is_dir():
        return {"passed": False, "errors": ["release_evidence_missing"]}
    try:
        from live_migration.ledger import LedgerError, terminal_release_generation

        terminal, generation = terminal_release_generation(root)
    except (ImportError, LedgerError, OSError, ValueError):
        return {"passed": False, "errors": ["release_evidence_missing"]}
    payloads: dict[str, dict[str, object]] = {}
    release_payloads: dict[str, dict[str, object]] = {}

    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate JSON key")
            value[key] = item
        return value

    try:
        for key, name in names.items():
            raw = (generation / name).read_bytes()
            value = json.loads(raw, object_pairs_hook=reject_duplicate_keys)
            if not isinstance(value, dict):
                raise ValueError
            if raw != (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode():
                raise ValueError("non-canonical release bytes")
            payloads[key] = value
            release_payloads[name] = value
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return {"passed": False, "errors": ["release_evidence_invalid"]}

    checkpoint = payloads["checkpoint"]
    manifest = payloads["manifest"]
    result = payloads["result"]
    privacy = payloads["privacy"]
    dogfood = payloads["dogfood"]
    errors: list[str] = []

    run_id = str(manifest.get("run_id") or "")
    retained_run_id = str(dogfood.get("retained_run_id") or "")
    allowed_root_entries = {
        "quality-release-events.jsonl",
        "quality-release-state.json",
        "quality-release-manifests",
        "quality-release-predecessor.json",
        "release-generations",
        "dogfood",
        run_id,
    }
    root_entries = {path.name for path in root.iterdir()}
    if (
        not run_id
        or root_entries - allowed_root_entries
        or any(name in root_entries for name in {"checkpoint.json", "manifest.json", "result.json", "privacy-audit.json", "dogfood-result.json", "aggregate.json"})
    ):
        errors.append("release_root_file_set_invalid")
    dogfood_root = root / "dogfood"
    if (
        not retained_run_id
        or not dogfood_root.is_dir()
        or dogfood_root.is_symlink()
        or {path.name for path in dogfood_root.iterdir()} != {retained_run_id}
    ):
        errors.append("release_root_file_set_invalid")

    privacy_reaudit = audit_sanitized_payload(release_payloads)
    try:
        validate_v4_release_payloads(release_payloads)
    except ValueError:
        errors.append("release_evidence_schema_invalid")
    if privacy_reaudit.get("passed") is not True:
        errors.append("privacy_audit_failed")
    if errors:
        return {"passed": False, "errors": errors}

    def lower_hex(value: object, length: int) -> bool:
        return isinstance(value, str) and len(value) == length and all(
            character in "0123456789abcdef" for character in value
        )

    reviewed_tree: str | None = None
    if not lower_hex(implementation_commit, 40) or not workspace.expanduser().resolve().is_dir():
        errors.append("implementation_commit_invalid")
    else:
        repository = workspace.expanduser().resolve()
        commit_result = subprocess.run(
            ["git", "rev-parse", "--verify", f"{implementation_commit}^{{commit}}"],
            cwd=repository,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        tree_result = subprocess.run(
            ["git", "rev-parse", "--verify", f"{implementation_commit}^{{tree}}"],
            cwd=repository,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if (
            commit_result.returncode
            or tree_result.returncode
            or commit_result.stdout.strip() != implementation_commit
            or not lower_hex(tree_result.stdout.strip(), 40)
        ):
            errors.append("implementation_commit_invalid")
        else:
            reviewed_tree = tree_result.stdout.strip()

    if not lower_hex(checkpoint.get("commit"), 40) or not lower_hex(checkpoint.get("tree"), 40):
        errors.append("reviewed_checkpoint_invalid")
    if (
        checkpoint.get("commit") != implementation_commit
        or reviewed_tree is None
        or checkpoint.get("tree") != reviewed_tree
    ):
        errors.append("reviewed_checkpoint_mismatch")
    if any(
        payload.get("implementation_commit") != checkpoint.get("commit")
        or payload.get("implementation_tree") != checkpoint.get("tree")
        for payload in (manifest, result, privacy, dogfood)
    ):
        errors.append("reviewed_checkpoint_binding_invalid")
    if (
        manifest.get("implementation_base_commit")
        != result.get("implementation_base_commit")
        or manifest.get("proof_profile") != result.get("proof_profile")
    ):
        errors.append("reviewed_checkpoint_binding_invalid")
    if reviewed_tree is not None:
        try:
            policy = load_release_policy()
            validate_release_checkpoint(
                workspace.expanduser().resolve(),
                implementation_commit,
                implementation_tree=reviewed_tree,
                implementation_patch_sha256=str(manifest.get("implementation_patch_sha256") or ""),
                policy=policy,
            )
            if manifest.get("implementation_base_commit") != policy["trusted_base_commit"]:
                errors.append("implementation_patch_invalid")
        except ValueError:
            errors.append("implementation_patch_invalid")
    bindings = {
        "manifest_sha256": _canonical_sha256(manifest),
        "result_sha256": _canonical_sha256(result),
        "privacy_sha256": _canonical_sha256(privacy),
        "dogfood_sha256": _canonical_sha256(dogfood),
    }
    if any(checkpoint.get(key) != digest for key, digest in bindings.items()):
        errors.append("release_evidence_binding_invalid")
    if result.get("manifest_sha256") != bindings["manifest_sha256"]:
        errors.append("result_manifest_binding_invalid")
    if (
        manifest.get("run_id") != result.get("run_id")
        or manifest.get("implementation_patch_sha256")
        != result.get("implementation_patch_sha256")
        or manifest.get("credentialed_call_count")
        != result.get("credentialed_call_count")
        or manifest.get("policy_outcome_count") != result.get("policy_outcome_count")
        or manifest.get("pending_slot_count") != result.get("pending_slot_count")
        or manifest.get("duplicate_slot_count") != result.get("duplicate_slot_count")
        or manifest.get("terminal") is not (manifest.get("pending_slot_count") == 0)
    ):
        errors.append("release_evidence_cross_binding_invalid")
    expected_counts = (
        (2, 7)
        if manifest.get("proof_profile") == "critical_path_live"
        else (17, 7)
        if manifest.get("proof_profile") == "full_paid_matrix"
        else None
    )
    for payload in (manifest, result):
        if expected_counts is None or (
            payload.get("credentialed_call_count"), payload.get("policy_outcome_count")
        ) != expected_counts:
            errors.append("quality_matrix_count_invalid")
            break
    try:
        manifest_envelopes = canonical_v4_envelope_map(manifest)
        result_envelopes = canonical_v4_envelope_map(result)
        envelope_binding_valid = manifest_envelopes == result_envelopes
    except ValueError:
        envelope_binding_valid = False
    if not envelope_binding_valid:
        errors.append("launch_envelope_binding_invalid")
    if not isinstance(result.get("release_gate"), dict) or result["release_gate"].get("passed") is not True:
        errors.append("release_gate_failed")
    elif result["release_gate"].get("failures") != []:
        errors.append("release_gate_failed")
    if (
        privacy.get("passed") is not True
        or privacy.get("findings") != []
        or privacy_reaudit != {"passed": True, "failures": []}
    ):
        errors.append("privacy_audit_failed")
    dogfood_valid = (
        dogfood.get("status") == "passed"
        and dogfood.get("run_ids_created") == 1
        and type(dogfood.get("model_attempts")) is int
        and 1 <= dogfood["model_attempts"] <= 4
        and type(dogfood.get("max_same_root_repairs")) is int
        and 0 <= dogfood["max_same_root_repairs"] <= 2
        and isinstance(dogfood.get("verified_checkpoints"), list)
        and type(dogfood.get("elapsed_seconds")) in {int, float}
        and 0 <= dogfood["elapsed_seconds"] <= 3600
        and dogfood.get("source_checkout_unchanged") is True
        and dogfood.get("runtime_patch_required") is False
    )
    dogfood_valid = dogfood_valid and len(dogfood.get("verified_checkpoints", [])) == 1
    try:
        policy = load_release_policy()
        retained = verify_retained_v4_dogfood_run(
            root / "dogfood" / retained_run_id,
            expected_implementation_commit=implementation_commit,
            expected_implementation_tree=str(checkpoint.get("tree") or ""),
            expected_task_contract_sha256=str(policy["dogfood_task_contract_sha256"]),
        )
        retained_checkpoint = root / "dogfood" / retained_run_id / "checkpoint.json"
        if (
            not retained_run_id
            or dogfood.get("retained_checkpoint_sha256") != hashlib.sha256(retained_checkpoint.read_bytes()).hexdigest()
            or int(retained.get("model_attempts") or 0) > int(policy["dogfood_attempt_limit"])
            or (
                manifest.get("proof_profile") == "critical_path_live"
                and (
                    int(manifest.get("credentialed_call_count") or 0) > int(policy["critical_matrix_attempt_limit"])
                    or int(manifest.get("credentialed_call_count") or 0) + int(retained.get("model_attempts") or 0) > int(policy["combined_attempt_limit"])
                )
            )
        ):
            dogfood_valid = False
    except (OSError, ValueError):
        dogfood_valid = False
    if not dogfood_valid:
        errors.append("dogfood_limits_invalid")
    try:
        from live_model_migration import aggregate_run
        from live_migration.contracts import canonical_json, sha256_bytes

        child_aggregate = aggregate_run(root / str(manifest.get("run_id")))
        if (
            sha256_bytes(canonical_json(child_aggregate)) != terminal.get("aggregate_sha256")
            or child_aggregate.get("credentialed_call_count") != manifest.get("credentialed_call_count")
            or child_aggregate.get("policy_outcome_count") != manifest.get("policy_outcome_count")
            or child_aggregate.get("pending_slot_count") != 0
            or child_aggregate.get("duplicate_slot_count") != 0
            or child_aggregate.get("release_gate") != result.get("release_gate")
            or child_aggregate.get("envelope_sha256") != result.get("envelope_sha256")
        ):
            errors.append("authoritative_child_gate_invalid")
    except (ImportError, OSError, ValueError):
        errors.append("authoritative_child_gate_invalid")
    event_bindings = {
        "generation_sha256": generation.name,
        "checkpoint_sha256": hashlib.sha256((generation / "checkpoint.json").read_bytes()).hexdigest(),
        "privacy_sha256": hashlib.sha256((generation / "privacy-audit.json").read_bytes()).hexdigest(),
        "dogfood_sha256": hashlib.sha256((generation / "dogfood-result.json").read_bytes()).hexdigest(),
        "child_manifest_sha256": manifest.get("ledger_manifest_sha256"),
        "proof_profile": manifest.get("proof_profile"),
    }
    if any(terminal.get(key) != value for key, value in event_bindings.items()):
        errors.append("release_terminal_binding_invalid")
    return {
        "passed": not errors,
        "errors": errors,
        "commit": checkpoint.get("commit"),
        "tree": checkpoint.get("tree"),
        "credentialed_call_count": manifest.get("credentialed_call_count"),
        "policy_outcome_count": manifest.get("policy_outcome_count"),
    }


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
    schema_version: str = "cpe.public-result.v4"
    current_task: str | None = None
    checkpoint_head: str | None = None
    attempt_limit: int | None = None
    attempt_used: int | None = None
    next_safe_action: str | None = None
    user_input_required: bool = False

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
            "schema_version": self.schema_version,
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
            "current_task": self.current_task,
            "checkpoint_head": self.checkpoint_head,
            "attempt_limit": self.attempt_limit,
            "attempt_used": self.attempt_used,
            "next_safe_action": self.next_safe_action or self.next_action,
            "user_input_required": self.user_input_required,
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
