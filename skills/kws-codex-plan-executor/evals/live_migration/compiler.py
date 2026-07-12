"""Compile checked-in live-migration inputs without launching a model."""

from __future__ import annotations

import json
import math
import re
import sys
import base64
import hashlib
from numbers import Real
from pathlib import Path
from typing import Any

from .contracts import (
    CHATGPT_SUBSCRIPTION,
    CREDENTIALLED_CALL,
    EXPECTED_CASES,
    EXPECTED_POLICY_FAILURE,
    EXPECTED_PROMPT_SHA256,
    EXPECTED_PROMPT_SOURCE_SHA256,
    EXPECTED_TREATMENTS,
    EXPECTED_V4_TREATMENTS,
    MAX_METERED_BUDGET_USD,
    METERED_DOLLAR_MODE,
    CaseRef,
    LiveMigrationContractError,
    SlotKey,
    Treatment,
    QualityTreatmentV4,
    canonical_json,
    sha256_bytes,
    worker_prompt_bytes,
)
from .envelopes import seal_launch_envelope, seal_oracle_binding


_COMMIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_TERRA_PROMPT = b"bounded read-only scout prompt renderer v1\n"
_OUTPUT_SCHEMA_REF = "live-migration/worker-result-schema.json"
_DEFAULT_CREATED_AT = "1970-01-01T00:00:00Z"
QUALIFIED_SENTINEL = {
    "treatment_id": "sol_v4_candidate",
    "case_id": "security/migration block",
}


def _skill_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_v4_prompt_runtime():
    skill_root = str(_skill_root())
    if skill_root not in sys.path:
        sys.path.insert(0, skill_root)
    from scripts.cpe_runtime.prompt_bundles import (
        build_scout_bundle,
        paired_bundles,
        worker_output_schema,
    )
    from scripts.cpe_runtime.task_contracts import compile_task_contract

    return paired_bundles, build_scout_bundle, worker_output_schema, compile_task_contract


def v4_case_prompt_bundles(
    eval_dir: Path,
    case_id: str,
    case_slug: str,
) -> dict[str, object]:
    """Build the approved same-case control/candidate pair with no local paths."""

    root = Path(eval_dir)
    fixture_root = root / "live-migration" / "fixtures" / case_slug
    case = _load_object(fixture_root / "case.json")
    if case.get("case_id") != case_id or case.get("slug") != case_slug:
        raise LiveMigrationContractError("v4 prompt case does not match the registry")
    repo = fixture_root / "repo"
    bounded_context: list[dict[str, str]] = []
    try:
        for path in sorted(item for item in repo.rglob("*") if item.is_file()):
            if path.is_symlink():
                raise LiveMigrationContractError("v4 prompt context cannot contain symlinks")
            bounded_context.append(
                {
                    "path": path.relative_to(repo).as_posix(),
                    "content": path.read_text(encoding="utf-8"),
                }
            )
    except (OSError, UnicodeError) as exc:
        raise LiveMigrationContractError(f"cannot compile v4 prompt context: {exc}") from exc
    task_source = canonical_json(case).decode("utf-8")
    source_hash = sha256_bytes(task_source.encode("utf-8"))
    paired_bundles, build_scout_bundle, _worker_output_schema, compile_task_contract = (
        _load_v4_prompt_runtime()
    )
    contract = compile_task_contract(
        {
            "id": case_slug,
            "title": case_id,
            "task_type": (
                "tdd_implementation" if case.get("mode") == "write" else "verification"
            ),
            "risk_class": "high",
            "task_source": task_source,
            "file_claims": case.get("allowed_paths"),
            "forbidden_paths": case.get("forbidden_paths"),
            "acceptance_command": case.get("acceptance_command"),
            "checkpoint_message": f"Complete quality case: {case_id}",
        },
        source_hashes={"case": source_hash, "spec_sections": {}},
    )
    control, candidate = paired_bundles(
        contract,
        bounded_context=tuple(bounded_context),
    )
    scout = build_scout_bundle(
        contract,
        bounded_context=tuple(bounded_context),
        case_sha256=control.case_sha256,
    )
    return {"control": control, "candidate": candidate, "scout": scout}


def v4_worker_output_schema_bytes(eval_dir: Path) -> bytes:
    """Return the exact Task 7 output schema used by both v4 treatments."""

    _paired_bundles, _build_scout_bundle, worker_output_schema, _compile_task_contract = (
        _load_v4_prompt_runtime()
    )
    schema = worker_output_schema(
        Path(eval_dir) / "control-bundles" / "cpe-3.1.0-production.json"
    )
    return canonical_json(schema)


def _reference_sha256(reference: str) -> str:
    """Bind a planned repository-relative artifact reference without inventing bytes."""

    return sha256_bytes(reference.encode("utf-8"))


def _bound_tree_digest(root: Path, domain: bytes) -> str:
    digest = hashlib.sha256(domain)
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.is_symlink():
            raise LiveMigrationContractError(f"sealed input cannot contain symlinks: {path}")
        relative = path.relative_to(root).as_posix().encode("utf-8")
        raw = path.read_bytes()
        for value in (relative, raw):
            digest.update(len(value).to_bytes(8, "big"))
            digest.update(value)
    return digest.hexdigest()


def _load_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LiveMigrationContractError(f"cannot load contract input {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise LiveMigrationContractError(f"contract input must be an object: {path}")
    return payload


def load_registry(eval_dir: Path) -> tuple[tuple[Treatment, ...], tuple[CaseRef, ...]]:
    """Load the exact ordered treatment and case registries."""

    migration_dir = eval_dir / "live-migration"
    matrix = _load_object(migration_dir / "matrix.json")
    case_registry = _load_object(migration_dir / "cases.json")

    try:
        registered_treatments = tuple(
            Treatment(**item) for item in matrix.get("treatments", ())
        )
        cases = tuple(CaseRef(**item) for item in case_registry.get("case_refs", ()))
    except (TypeError, AttributeError) as exc:
        raise LiveMigrationContractError("registry entries must match canonical fields") from exc

    legacy_prompts = tuple(treatment.prompt for treatment in registered_treatments)
    compatible_prompts = (
        "current-v2-prompt.txt",
        "current-v2-prompt.txt",
        "../../templates/fresh-session-prompt.txt",
        "terra-scout-generated",
    )
    route_fields_match = len(registered_treatments) == len(EXPECTED_TREATMENTS) and all(
        (actual.id, actual.model, actual.reasoning)
        == (expected.id, expected.model, expected.reasoning)
        for actual, expected in zip(registered_treatments, EXPECTED_TREATMENTS)
    )
    if (
        matrix.get("schema_version") != "1"
        or not route_fields_match
        or legacy_prompts != compatible_prompts
    ):
        raise LiveMigrationContractError("matrix must match the exact four-treatment contract")
    legacy_case_ids = tuple(case_registry.get("cases", ()))
    if (
        case_registry.get("schema_version") != "2"
        or cases != EXPECTED_CASES
        or legacy_case_ids != tuple(case.id for case in EXPECTED_CASES)
    ):
        raise LiveMigrationContractError("case registry must match the exact eight-case contract")
    return EXPECTED_TREATMENTS, cases


def load_v4_registry(
    eval_dir: Path,
) -> tuple[tuple[QualityTreatmentV4, ...], tuple[CaseRef, ...]]:
    """Load the exact clean-cut v4 treatments and shared ordered cases."""

    migration_dir = eval_dir / "live-migration"
    matrix = _load_object(migration_dir / "matrix-v4.json")
    case_registry = _load_object(migration_dir / "cases.json")
    try:
        treatments = tuple(
            QualityTreatmentV4(**item) for item in matrix.get("treatments", ())
        )
        cases = tuple(CaseRef(**item) for item in case_registry.get("case_refs", ()))
    except (TypeError, AttributeError) as exc:
        raise LiveMigrationContractError(
            "v4 registry entries must match canonical fields"
        ) from exc
    if matrix.get("schema_version") != "4" or treatments != EXPECTED_V4_TREATMENTS:
        raise LiveMigrationContractError(
            "matrix-v4 must match the exact three-treatment contract"
        )
    if case_registry.get("schema_version") != "2" or cases != EXPECTED_CASES:
        raise LiveMigrationContractError("case registry must match the exact eight-case contract")
    return treatments, cases


def compile_v4_manifest(
    commit: str,
    run_id: str,
    *,
    eval_dir: Path | None = None,
    created_at: str = _DEFAULT_CREATED_AT,
) -> dict[str, object]:
    """Compile the immutable 24-slot, 17-call CPE v4 quality manifest."""

    if not _COMMIT_SHA.fullmatch(commit):
        raise LiveMigrationContractError("commit must be a 40-character SHA")
    if not run_id or not created_at:
        raise LiveMigrationContractError("run_id and created_at are required")
    root = Path(eval_dir) if eval_dir is not None else Path(__file__).resolve().parent.parent
    treatments, cases = load_v4_registry(root)
    migration_dir = root / "live-migration"
    inputs = {
        "matrix-v4.json": sha256_bytes((migration_dir / "matrix-v4.json").read_bytes()),
        "cases.json": sha256_bytes((migration_dir / "cases.json").read_bytes()),
    }
    case_by_id = {case.id: case for case in cases}
    terra_read_only = EXPECTED_CASES[-1]
    slots: list[dict[str, object]] = []
    slot_keys: set[SlotKey] = set()
    launch_artifacts: dict[str, str] = {}
    oracle_artifacts: dict[str, str] = {}

    ordered_cases = {
        "sol_v31_control": cases,
        "sol_v4_candidate": cases,
        "terra_v4": (terra_read_only, *cases[:-1]),
    }
    bundles_by_case = {
        case.id: v4_case_prompt_bundles(root, case.id, case.slug) for case in cases
    }
    launched_output_schema_sha256 = sha256_bytes(v4_worker_output_schema_bytes(root))
    for treatment in treatments:
        for case in ordered_cases[treatment.id]:
            canonical_case = case_by_id[case.id]
            key = SlotKey(treatment.id, canonical_case.id)
            if key in slot_keys:
                raise LiveMigrationContractError(f"duplicate v4 slot: {key}")
            slot_keys.add(key)
            credentialed = treatment.id != "terra_v4" or canonical_case == terra_read_only
            policy_failure = not credentialed
            bundle_kind = (
                "control"
                if treatment.id == "sol_v31_control"
                else "scout" if treatment.id == "terra_v4" else "candidate"
            )
            bundle = bundles_by_case[canonical_case.id][bundle_kind]
            fixture_ref = f"live-migration/fixtures/{canonical_case.slug}/repo"
            oracle_ref = f"live-migration/fixtures/{canonical_case.slug}/oracle"
            slot: dict[str, object] = {
                "treatment_id": treatment.id,
                "case_id": canonical_case.id,
                "case_slug": canonical_case.slug,
                "model": treatment.model,
                "reasoning": treatment.reasoning,
                "prompt_renderer": f"paired-bundles:{bundle_kind}",
                "prompt_sha256": bundle.prompt_sha256,
                "task_contract_sha256": bundle.task_contract_sha256,
                "case_sha256": bundle.case_sha256,
                "prompt_output_schema_sha256": bundle.output_schema_sha256,
                "output_schema_sha256": launched_output_schema_sha256,
                "prompt_role": bundle.role,
                "verdict_capable": False if bundle.role == "scout" else None,
                "credentialed": credentialed,
                "outcome_kind": CREDENTIALLED_CALL if credentialed else EXPECTED_POLICY_FAILURE,
                "expected_policy_failure": policy_failure,
            }
            if credentialed:
                fixture_root = migration_dir / "fixtures" / canonical_case.slug
                case_source_sha256 = sha256_bytes((fixture_root / "case.json").read_bytes())
                fixture_source_sha256 = _bound_tree_digest(
                    fixture_root / "repo", b"cpe.fixture-source.v4\0"
                )
                oracle_source_sha256 = _bound_tree_digest(
                    fixture_root / "oracle", b"cpe.oracle-source.v4\0"
                )
                sandbox = "read-only" if bundle.role == "scout" else (
                    "workspace-write" if _load_object(fixture_root / "case.json").get("mode") == "write" else "read-only"
                )
                route_binding = {
                    "model": treatment.model,
                    "reasoning": treatment.reasoning,
                    "role": bundle.role,
                    "sandbox": sandbox,
                }
                route_binding_sha256 = sha256_bytes(canonical_json(route_binding))
                envelope = seal_launch_envelope(
                    {
                        "treatment_id": treatment.id,
                        "model": treatment.model,
                        "reasoning": treatment.reasoning,
                        "role": bundle.role,
                        "sandbox": sandbox,
                        "task_id": canonical_case.slug,
                        "case_id": canonical_case.id,
                        "case_slug": canonical_case.slug,
                        "fixture_source_sha256": fixture_source_sha256,
                        "input_source_sha256": case_source_sha256,
                        "case_sha256": bundle.case_sha256,
                        "task_contract_sha256": bundle.task_contract_sha256,
                        "prompt_output_schema_sha256": bundle.output_schema_sha256,
                        "route_binding": route_binding,
                        "route_binding_sha256": route_binding_sha256,
                    },
                    bundle.prompt.encode("utf-8"),
                    v4_worker_output_schema_bytes(root),
                )
                oracle_binding = seal_oracle_binding(
                    {
                        "treatment_id": treatment.id,
                        "case_id": canonical_case.id,
                        "case_slug": canonical_case.slug,
                        "envelope_sha256": str(envelope["envelope_sha256"]),
                        "oracle_ref": oracle_ref,
                        "oracle_source_sha256": oracle_source_sha256,
                    }
                )
                envelope_sha256 = str(envelope["envelope_sha256"])
                oracle_binding_sha256 = str(oracle_binding["oracle_binding_sha256"])
                launch_artifacts[envelope_sha256] = base64.b64encode(
                    canonical_json(envelope)
                ).decode("ascii")
                oracle_artifacts[oracle_binding_sha256] = base64.b64encode(
                    canonical_json(oracle_binding)
                ).decode("ascii")
                slot.update(
                    {
                        "fixture": fixture_ref,
                        "fixture_ref_sha256": _reference_sha256(fixture_ref),
                        "oracle": oracle_ref,
                        "oracle_ref_sha256": _reference_sha256(oracle_ref),
                        "output_schema": _OUTPUT_SCHEMA_REF,
                        "output_schema_ref_sha256": _reference_sha256(_OUTPUT_SCHEMA_REF),
                        "fixture_source_sha256": fixture_source_sha256,
                        "input_source_sha256": case_source_sha256,
                        "route_binding_sha256": route_binding_sha256,
                        "envelope_sha256": envelope_sha256,
                        "oracle_binding_sha256": oracle_binding_sha256,
                    }
                )
            else:
                policy_reason = {
                    "code": "terra_write_capability_forbidden",
                    "required_role": "read_only_scout",
                }
                slot["policy_reason"] = policy_reason
                slot["matrix_policy_sha256"] = sha256_bytes(canonical_json(policy_reason))
            slots.append(slot)

    credentialed_count = sum(bool(slot["credentialed"]) for slot in slots)
    policy_count = sum(bool(slot["expected_policy_failure"]) for slot in slots)
    if len(slots) != 24 or len(slot_keys) != 24 or (credentialed_count, policy_count) != (17, 7):
        raise LiveMigrationContractError(
            "compiled v4 matrix must contain 17 calls and seven policy outcomes"
        )
    body: dict[str, object] = {
        "schema_version": "cpe-quality-manifest.v4",
        "run_id": run_id,
        "created_at": created_at,
        "implementation_commit": commit,
        "billing_mode": CHATGPT_SUBSCRIPTION,
        "treatment_count": 3,
        "case_count": 8,
        "credentialed_call_count": credentialed_count,
        "expected_policy_failure_count": policy_count,
        "qualified_sentinel": QUALIFIED_SENTINEL,
        "inputs": inputs,
        "sealed_artifacts": {
            "launch_envelopes": launch_artifacts,
            "oracle_bindings": oracle_artifacts,
        },
        "slots": slots,
    }
    return {**body, "manifest_sha256": sha256_bytes(canonical_json(body))}


def _prompt_source_bytes(eval_dir: Path, prompt_ref: str) -> bytes:
    if prompt_ref == "terra-scout-generated":
        return _TERRA_PROMPT
    try:
        return (eval_dir / "live-migration" / prompt_ref).resolve().read_bytes()
    except OSError as exc:
        raise LiveMigrationContractError(f"missing prompt template: {prompt_ref}") from exc


def _input_digests(
    eval_dir: Path,
    treatments: tuple[Treatment, ...],
) -> tuple[dict[str, str], dict[str, str]]:
    migration_dir = eval_dir / "live-migration"
    try:
        inputs = {
            "matrix.json": sha256_bytes((migration_dir / "matrix.json").read_bytes()),
            "cases.json": sha256_bytes((migration_dir / "cases.json").read_bytes()),
        }
    except OSError as exc:
        raise LiveMigrationContractError(f"cannot digest compiler input: {exc}") from exc

    prompt_digests: dict[str, str] = {}
    for treatment in treatments:
        source = _prompt_source_bytes(eval_dir, treatment.prompt)
        source_digest = sha256_bytes(source)
        if source_digest != EXPECTED_PROMPT_SOURCE_SHA256[treatment.prompt]:
            raise LiveMigrationContractError(
                f"prompt template source digest drifted: {treatment.prompt}"
            )
        digest = sha256_bytes(worker_prompt_bytes(source, treatment.prompt))
        if digest != EXPECTED_PROMPT_SHA256[treatment.prompt]:
            raise LiveMigrationContractError(
                f"prompt template digest drifted: {treatment.prompt}"
            )
        prompt_digests[treatment.id] = digest
        inputs[f"prompt:{treatment.id}"] = digest
        inputs[f"prompt_source:{treatment.id}"] = source_digest
    return inputs, prompt_digests


def compile_manifest(
    eval_dir: Path,
    billing_mode: str,
    implementation_commit: str,
    created_at: str,
    run_id: str,
    *,
    budget_usd: float | None = None,
) -> dict[str, object]:
    """Compile the immutable treatment-major, case-minor 4x8 manifest."""

    if billing_mode not in {CHATGPT_SUBSCRIPTION, METERED_DOLLAR_MODE}:
        raise LiveMigrationContractError(f"unsupported billing mode: {billing_mode}")
    if billing_mode == CHATGPT_SUBSCRIPTION and budget_usd is not None:
        raise LiveMigrationContractError("subscription compilation does not accept a dollar budget")
    if billing_mode == METERED_DOLLAR_MODE:
        if (
            isinstance(budget_usd, bool)
            or not isinstance(budget_usd, Real)
            or not math.isfinite(float(budget_usd))
        ):
            raise LiveMigrationContractError(
                "metered compilation requires a finite numeric budget_usd"
            )
        if budget_usd <= 0 or budget_usd > MAX_METERED_BUDGET_USD:
            raise LiveMigrationContractError("metered budget must be positive and at most $50.00")
    if not _COMMIT_SHA.fullmatch(implementation_commit):
        raise LiveMigrationContractError("implementation_commit must be a 40-character SHA")
    if not created_at or not run_id:
        raise LiveMigrationContractError("created_at and run_id are required")

    treatments, cases = load_registry(eval_dir)
    input_digests, prompt_digests = _input_digests(eval_dir, treatments)
    slots: list[dict[str, object]] = []
    slot_keys: set[SlotKey] = set()

    for treatment in treatments:
        for case in cases:
            key = SlotKey(treatment.id, case.id)
            if key in slot_keys:
                raise LiveMigrationContractError(f"duplicate slot: {key}")
            slot_keys.add(key)
            policy_failure = treatment.id == "terra_scout" and case.id != EXPECTED_CASES[-1].id
            fixture_ref = f"live-migration/fixtures/{case.slug}/repo"
            oracle_ref = f"live-migration/fixtures/{case.slug}/oracle"
            slot: dict[str, object] = {
                "treatment_id": treatment.id,
                "case_id": case.id,
                "case_slug": case.slug,
                "model": treatment.model,
                "reasoning": treatment.reasoning,
                "prompt_renderer": treatment.prompt,
                "prompt_sha256": prompt_digests[treatment.id],
                "outcome_kind": (
                    EXPECTED_POLICY_FAILURE if policy_failure else CREDENTIALLED_CALL
                ),
                "expected_policy_failure": policy_failure,
            }
            if policy_failure:
                policy_reason = {
                    "code": "terra_write_capability_forbidden",
                    "required_role": "read_only_scout",
                }
                slot["policy_reason"] = policy_reason
                slot["matrix_policy_sha256"] = sha256_bytes(
                    canonical_json(policy_reason)
                )
            else:
                slot.update(
                    {
                        "fixture": fixture_ref,
                        "fixture_ref_sha256": _reference_sha256(fixture_ref),
                        "oracle": oracle_ref,
                        "oracle_ref_sha256": _reference_sha256(oracle_ref),
                        "output_schema": _OUTPUT_SCHEMA_REF,
                        "output_schema_ref_sha256": _reference_sha256(
                            _OUTPUT_SCHEMA_REF
                        ),
                    }
                )
            slots.append(slot)

    credentialed_count = sum(
        slot["outcome_kind"] == CREDENTIALLED_CALL for slot in slots
    )
    policy_count = sum(
        slot["outcome_kind"] == EXPECTED_POLICY_FAILURE for slot in slots
    )
    if len(slots) != 32 or len(slot_keys) != 32 or (credentialed_count, policy_count) != (25, 7):
        raise LiveMigrationContractError("compiled matrix must contain 25 calls and seven policy outcomes")

    body: dict[str, object] = {
        "schema_version": "cpe-live-manifest.v2",
        "run_id": run_id,
        "created_at": created_at,
        "implementation_commit": implementation_commit,
        "billing_mode": billing_mode,
        "treatment_count": 4,
        "case_count": 8,
        "credentialed_call_count": credentialed_count,
        "expected_policy_failure_count": policy_count,
        "inputs": input_digests,
        "slots": slots,
    }
    if billing_mode == METERED_DOLLAR_MODE:
        body["budget_usd"] = float(budget_usd)
    return {**body, "manifest_sha256": sha256_bytes(canonical_json(body))}
