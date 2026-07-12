"""Production-faithful control and candidate prompt bundles for CPE v4."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable, Mapping

from .model_policy import CORE_ROUTE
from .task_contracts import TaskContractV4


CONTROL_SOURCE_COMMIT = "344f6112a7254b87cfa25fe0f6d6f3acbc964487"
CONTROL_SCHEDULER_SHA256 = "de9897c9956748355c78625dde1b6adddb511afa332f3937bb3e509ff10f6990"
CONTROL_PACKET_SOURCE_SHA256 = "8ec8a837d509af23143da0f18bb45318fc00e8ea90b6d5e0ee4addf6cbdf26b7"
CONTROL_OUTPUT_SCHEMA_SHA256 = "9101db72c34a58b3fbc68235cb5a6ea80e6b464dd98f83d7c7dc8cec3960beb5"
CONTROL_OUTPUT_SCHEMA_CANONICAL_SHA256 = "824d7b298f10a4263286f70d6393fdcffc73d8f7d21c344d785001c11cbc6da4"
CANDIDATE_PREFIX_SHA256 = "d931fc1020b46212ed589400fdaa12f6d04e3fe0a10da6607e260ee0f625b68b"
BUNDLE_SCHEMA_VERSION = "cpe.prompt-bundle.v4"
CONTROL_TREATMENT = "cpe-3.1.0-production-control"
CANDIDATE_TREATMENT = "cpe-4.0.0-task-contract-candidate"


class PromptBundleError(ValueError):
    pass


@dataclass(frozen=True)
class PromptBundle:
    schema_version: str
    treatment_id: str
    model: str
    reasoning: str
    role: str
    prompt: str
    prompt_sha256: str
    task_contract_sha256: str
    case_sha256: str
    output_schema_sha256: str


def _canonical_bytes(payload: object) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _json_copy(value: object) -> object:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _contains_absolute_path(value: object) -> bool:
    if isinstance(value, Mapping):
        return any(_contains_absolute_path(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_absolute_path(item) for item in value)
    if not isinstance(value, str):
        return False
    if value.startswith(("$WORKTREE", "$RUN_DIR")):
        return False
    return (
        PurePosixPath(value).is_absolute()
        or value.startswith("file:///")
        or re.search(r"(?<![\w$])/(?:Users|home|private|tmp|var/folders)/", value) is not None
    )


def _safe_json(value: object, label: str) -> object:
    copied = _json_copy(value)
    if _contains_absolute_path(copied):
        raise PromptBundleError(f"{label}_contains_absolute_path")
    return copied


def _skill_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _default_fixture_path() -> Path:
    return _skill_root() / "evals" / "control-bundles" / "cpe-3.1.0-production.json"


def _candidate_prefix(path: Path | None = None) -> str:
    try:
        content = (path or (_skill_root() / "templates" / "cpe-v4-worker-prefix.txt")).read_bytes()
    except OSError as exc:
        raise PromptBundleError("candidate_prompt_unavailable") from exc
    if _sha256(content) != CANDIDATE_PREFIX_SHA256:
        raise PromptBundleError("candidate_prompt_drift")
    return content.decode("utf-8")


def _control_fixture(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PromptBundleError("control_fixture_unavailable") from exc
    if not isinstance(payload, dict):
        raise PromptBundleError("control_fixture_invalid")
    exact = {
        "schema_version": "cpe.production-control.v1",
        "source_commit": CONTROL_SOURCE_COMMIT,
        "scheduler_sha256": CONTROL_SCHEDULER_SHA256,
        "packet_source_sha256": CONTROL_PACKET_SOURCE_SHA256,
        "output_schema_sha256": CONTROL_OUTPUT_SCHEMA_SHA256,
    }
    if any(payload.get(key) != value for key, value in exact.items()):
        raise PromptBundleError("control_source_drift")
    normalized = payload.get("normalized_production_input")
    if not isinstance(normalized, dict) or set(normalized) != {
        "scheduler_instruction",
        "worker_stdin",
        "packet_bytes",
        "selected_spec",
        "prior_evidence",
        "result_contract",
    }:
        raise PromptBundleError("control_input_is_not_production_shape")
    if _contains_absolute_path(normalized):
        raise PromptBundleError("control_input_contains_absolute_path")
    packet_bytes = normalized["packet_bytes"]
    if not isinstance(packet_bytes, str) or _sha256(packet_bytes.encode()) != payload.get(
        "packet_sha256"
    ):
        raise PromptBundleError("control_packet_drift")
    if _sha256(str(normalized["scheduler_instruction"]).encode()) != payload.get(
        "scheduler_instruction_sha256"
    ):
        raise PromptBundleError("control_scheduler_drift")
    output_schema = payload.get("output_schema")
    if not isinstance(output_schema, dict):
        raise PromptBundleError("control_output_schema_invalid")
    if _sha256(_canonical_bytes(output_schema)) != CONTROL_OUTPUT_SCHEMA_CANONICAL_SHA256:
        raise PromptBundleError("control_output_schema_drift")
    return payload


def _contract_body(contract: TaskContractV4) -> dict[str, object]:
    if not isinstance(contract, TaskContractV4):
        raise PromptBundleError("task_contract_v4_required")
    body = contract.body()
    if _contains_absolute_path(body):
        raise PromptBundleError("task_contract_contains_absolute_path")
    return body


def _v3_task(contract: TaskContractV4) -> dict[str, object]:
    body = _contract_body(contract)
    return {
        "id": contract.task_id,
        "title": contract.title,
        "dependencies": list(contract.dependencies),
        "task_type": contract.task_type,
        "task_source": contract.task_source,
        "spec_refs": [section["id"] for section in contract.spec_sections],
        "file_claims": list(contract.file_claims),
        "acceptance_command": "\n".join(contract.acceptance_commands),
        "source_hashes": body["source_hashes"],
        "execution_contract": {
            "allowed_paths": list(contract.file_claims),
            "forbidden_paths": list(contract.forbidden_paths),
            "acceptance_command": "\n".join(contract.acceptance_commands),
        },
    }


def _v3_packet(contract: TaskContractV4) -> dict[str, object]:
    task = _v3_task(contract)
    return {
        "schema_version": "3.1",
        "task_id": contract.task_id,
        "task": task,
        "spec_sections": _json_copy(list(contract.spec_sections)),
        "execution_contract": {
            "scope": "bounded task scope",
            "files_to_inspect": list(contract.file_claims),
            "allowed_edits": list(contract.file_claims),
            "forbidden_edits": list(contract.forbidden_paths),
            "acceptance_command_or_honest_substitute": "\n".join(contract.acceptance_commands),
        },
        "required_methods": ["using-superpowers", "test-driven-development"],
        "role_policy": {
            "scout": {"read_only": True, "verdict_capable": False, "product_write": False},
            "implementation": {"read_only": False, "verdict_capable": False, "product_write": True},
            "task_review": {"read_only": True, "verdict_capable": True, "product_write": False},
            "verification": {"read_only": True, "verdict_capable": True, "product_write": False},
            "repair": {"read_only": False, "verdict_capable": False, "product_write": True},
            "final_review": {"read_only": True, "verdict_capable": True, "product_write": False},
        },
        "evidence_requirements": [
            "changed_files", "findings", "evidence_refs", "missing_evidence", "verification"
        ],
        "source_hashes": _json_copy(contract.source_hashes),
    }


def _result_contract() -> dict[str, object]:
    return {
        "verdict_must_be_null": True,
        "top_level_findings_must_equal_verdict_findings": False,
        "top_level_missing_evidence_must_equal_verdict_missing_evidence": False,
        "guidance": "This role cannot issue a verdict; return verdict=null.",
    }


def _case_digest(
    contract: TaskContractV4,
    *,
    prior_findings: object = (),
    finding_delta: object = (),
    bounded_context: object = (),
) -> str:
    return _sha256(
        _canonical_bytes(
            {
                "task_contract": _contract_body(contract),
                "prior_findings": _safe_json(prior_findings, "prior_findings"),
                "finding_delta": _safe_json(finding_delta, "finding_delta"),
                "bounded_visible_context": _safe_json(bounded_context, "bounded_context"),
                "output_schema_sha256": CONTROL_OUTPUT_SCHEMA_SHA256,
            }
        )
    )


def _bundle(
    *, treatment_id: str, prompt: str, contract: TaskContractV4, case_sha256: str
) -> PromptBundle:
    return PromptBundle(
        schema_version=BUNDLE_SCHEMA_VERSION,
        treatment_id=treatment_id,
        model=CORE_ROUTE.model,
        reasoning=CORE_ROUTE.reasoning,
        role="implementation",
        prompt=prompt,
        prompt_sha256=_sha256(prompt.encode()),
        task_contract_sha256=contract.contract_sha256,
        case_sha256=case_sha256,
        output_schema_sha256=CONTROL_OUTPUT_SCHEMA_SHA256,
    )


def build_control_bundle(
    contract: TaskContractV4,
    *,
    prior_task_evidence: Iterable[Mapping[str, object]] = (),
    fixture_path: Path | None = None,
    case_sha256: str | None = None,
) -> PromptBundle:
    fixture = _control_fixture(fixture_path or _default_fixture_path())
    prior_evidence = _safe_json(tuple(prior_task_evidence), "prior_task_evidence")
    packet = _v3_packet(contract)
    packet_bytes = _canonical_bytes(packet).decode()
    packet_sha256 = _sha256(packet_bytes.encode())
    scheduler_instruction = (
        f"Implement task {contract.task_id} using only its verified packet and current revision."
    )
    worker_stdin = {
        "task_id": contract.task_id,
        "packet_path": f"$RUN_DIR/artifacts/task-packets/{contract.task_id}.json",
        "packet_sha256": packet_sha256,
        "worktree_revision": 0,
        "instruction": scheduler_instruction,
        "result_contract": _result_contract(),
        "canonical_runtime_validation": {
            "authority": "current_host_cpe_runtime",
            "command": "python3 $WORKTREE/skills/kws-codex-plan-executor/scripts/validate_state.py $RUN_DIR",
            "guidance": (
                "Use this current host-runtime command for canonical run validation. "
                "Do not substitute a validator copied into the execution worktree."
            ),
        },
        "prior_task_evidence": prior_evidence,
    }
    production_input = {
        "source_commit": CONTROL_SOURCE_COMMIT,
        "scheduler_instruction": scheduler_instruction,
        "worker_stdin": worker_stdin,
        "packet_bytes": packet_bytes,
        "spec_sections": _json_copy(list(contract.spec_sections)),
        "prior_task_evidence": prior_evidence,
        "result_contract": _result_contract(),
        "output_schema": fixture["output_schema"],
    }
    prompt = _canonical_bytes(production_input).decode()
    digest = case_sha256 or _case_digest(contract)
    return _bundle(
        treatment_id=CONTROL_TREATMENT, prompt=prompt, contract=contract, case_sha256=digest
    )


def build_candidate_bundle(
    contract: TaskContractV4,
    *,
    prior_findings: Iterable[Mapping[str, object]] = (),
    finding_delta: Iterable[Mapping[str, object]] = (),
    bounded_context: Iterable[Mapping[str, object]] = (),
    fixture_path: Path | None = None,
    prefix_path: Path | None = None,
    case_sha256: str | None = None,
) -> PromptBundle:
    fixture = _control_fixture(fixture_path or _default_fixture_path())
    prior = _safe_json(tuple(prior_findings), "prior_findings")
    delta = _safe_json(tuple(finding_delta), "finding_delta")
    context = _safe_json(tuple(bounded_context), "bounded_context")
    payload = {
        "role": "implementation",
        "task_contract": _contract_body(contract),
        "task_contract_sha256": contract.contract_sha256,
        "prior_findings": prior,
        "finding_delta": delta,
        "bounded_visible_context": context,
        "result_schema": fixture["output_schema"],
        "result_schema_sha256": CONTROL_OUTPUT_SCHEMA_SHA256,
    }
    prompt = _candidate_prefix(prefix_path) + _canonical_bytes(payload).decode()
    digest = case_sha256 or _case_digest(
        contract,
        prior_findings=prior,
        finding_delta=delta,
        bounded_context=context,
    )
    return _bundle(
        treatment_id=CANDIDATE_TREATMENT, prompt=prompt, contract=contract, case_sha256=digest
    )


def paired_bundles(
    contract: TaskContractV4,
    *,
    prior_task_evidence: Iterable[Mapping[str, object]] = (),
    prior_findings: Iterable[Mapping[str, object]] = (),
    finding_delta: Iterable[Mapping[str, object]] = (),
    bounded_context: Iterable[Mapping[str, object]] = (),
    fixture_path: Path | None = None,
) -> tuple[PromptBundle, PromptBundle]:
    evidence = tuple(prior_task_evidence)
    findings = tuple(prior_findings)
    delta = tuple(finding_delta)
    context = tuple(bounded_context)
    case_sha256 = _case_digest(
        contract,
        prior_findings=findings,
        finding_delta=delta,
        bounded_context=context,
    )
    return (
        build_control_bundle(
            contract,
            prior_task_evidence=evidence,
            fixture_path=fixture_path,
            case_sha256=case_sha256,
        ),
        build_candidate_bundle(
            contract,
            prior_findings=findings,
            finding_delta=delta,
            bounded_context=context,
            fixture_path=fixture_path,
            case_sha256=case_sha256,
        ),
    )
