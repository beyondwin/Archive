"""Production-faithful control and candidate prompt bundles for CPE v4."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable, Mapping

from .model_policy import CORE_ROUTE, SCOUT_ROUTE, Route
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
SCOUT_TREATMENT = "cpe-4.0.0-bounded-read-only-scout"


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
        return any(
            _contains_absolute_path(key) or _contains_absolute_path(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_absolute_path(item) for item in value)
    if not isinstance(value, str):
        return False
    inspected = value
    for approved_root in ("$WORKTREE", "$RUN_DIR"):
        if value == approved_root:
            return False
        prefix = approved_root + "/"
        if value.startswith(prefix):
            inspected = value[len(prefix) :]
            break
    return (
        PurePosixPath(inspected).is_absolute()
        or inspected.startswith("file:///")
        or inspected.startswith(("~/", "$HOME/", "${HOME}/"))
        or re.search(r"(?<![\w$])/(?:Users|home|private|tmp|var/folders)/", inspected)
        is not None
        or re.search(
            r"(?:^|[\\/\s'\"])(?:secrets?|oracle|transcripts?)/",
            inspected,
            re.IGNORECASE,
        )
        is not None
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
        "normalized_production_input_sha256": (
            "00bf67a13ca907cec3cf8389d1536a5d497b262e0290396e2e414dff9f3b8009"
        ),
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
    if _sha256(_canonical_bytes(normalized)) != payload.get(
        "normalized_production_input_sha256"
    ):
        raise PromptBundleError("control_input_drift")
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


def _bound_spec_sections(
    template: object, contract: TaskContractV4
) -> list[dict[str, object]]:
    if not isinstance(template, list) or not template or not isinstance(template[0], dict):
        raise PromptBundleError("control_selected_spec_invalid")
    keys = set(template[0])
    if keys != {"id", "sha256", "text"}:
        raise PromptBundleError("control_selected_spec_invalid")
    return [
        {key: section[key] for key in ("id", "sha256", "text")}
        for section in contract.spec_sections
    ]


def _bound_control_packet(
    packet_bytes: object,
    contract: TaskContractV4,
    spec_sections: list[dict[str, object]],
) -> dict[str, object]:
    if not isinstance(packet_bytes, str):
        raise PromptBundleError("control_packet_invalid")
    try:
        packet = json.loads(packet_bytes)
    except json.JSONDecodeError as exc:
        raise PromptBundleError("control_packet_invalid") from exc
    if not isinstance(packet, dict) or not isinstance(packet.get("task"), dict):
        raise PromptBundleError("control_packet_invalid")
    body = _contract_body(contract)
    task = dict(packet["task"])
    task.update(
        {
            "id": contract.task_id,
            "title": contract.title,
            "dependencies": list(contract.dependencies),
            "task_type": contract.task_type,
            "task_source": contract.task_source,
            "spec_refs": [section["id"] for section in contract.spec_sections],
            "file_claims": list(contract.file_claims),
            "acceptance_command": "\n".join(contract.acceptance_commands),
            "source_hashes": body["source_hashes"],
        }
    )
    task_execution = dict(task.get("execution_contract") or {})
    task_execution.update(
        {
            "allowed_paths": list(contract.file_claims),
            "forbidden_paths": list(contract.forbidden_paths),
            "acceptance_command": "\n".join(contract.acceptance_commands),
        }
    )
    task["execution_contract"] = task_execution
    execution = dict(packet.get("execution_contract") or {})
    execution.update(
        {
            "files_to_inspect": list(contract.file_claims),
            "allowed_edits": list(contract.file_claims),
            "forbidden_edits": list(contract.forbidden_paths),
            "acceptance_command_or_honest_substitute": "\n".join(
                contract.acceptance_commands
            ),
        }
    )
    packet.update(
        {
            "task_id": contract.task_id,
            "task": task,
            "spec_sections": spec_sections,
            "execution_contract": execution,
            "source_hashes": _json_copy(contract.source_hashes),
        }
    )
    return packet


def _bind_fixture_tokens(value: object, replacements: Mapping[str, object]) -> object:
    if isinstance(value, dict):
        return {key: _bind_fixture_tokens(item, replacements) for key, item in value.items()}
    if isinstance(value, list):
        return [_bind_fixture_tokens(item, replacements) for item in value]
    if not isinstance(value, str):
        return value
    if value in replacements:
        return _json_copy(replacements[value])
    rendered = value
    for token, replacement in replacements.items():
        if isinstance(replacement, str):
            rendered = rendered.replace(token, replacement)
    return rendered


def _case_digest(
    contract: TaskContractV4,
    *,
    prior_task_evidence: object = (),
    prior_findings: object = (),
    finding_delta: object = (),
    bounded_context: object = (),
) -> str:
    return _sha256(
        _canonical_bytes(
            {
                "task_contract": _contract_body(contract),
                "prior_task_evidence": _safe_json(
                    prior_task_evidence, "prior_task_evidence"
                ),
                "prior_findings": _safe_json(prior_findings, "prior_findings"),
                "finding_delta": _safe_json(finding_delta, "finding_delta"),
                "bounded_visible_context": _safe_json(bounded_context, "bounded_context"),
                "output_schema_sha256": CONTROL_OUTPUT_SCHEMA_SHA256,
            }
        )
    )


def _bundle(
    *,
    treatment_id: str,
    prompt: str,
    contract: TaskContractV4,
    case_sha256: str,
    route: Route = CORE_ROUTE,
    role: str = "implementation",
) -> PromptBundle:
    return PromptBundle(
        schema_version=BUNDLE_SCHEMA_VERSION,
        treatment_id=treatment_id,
        model=route.model,
        reasoning=route.reasoning,
        role=role,
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
    normalized = fixture["normalized_production_input"]
    if not isinstance(normalized, dict):
        raise PromptBundleError("control_input_is_not_production_shape")
    prior_evidence = _safe_json(tuple(prior_task_evidence), "prior_task_evidence")
    spec_sections = _bound_spec_sections(normalized["selected_spec"], contract)
    packet = _bound_control_packet(normalized["packet_bytes"], contract, spec_sections)
    packet_bytes = _canonical_bytes(packet).decode()
    packet_sha256 = _sha256(packet_bytes.encode())
    scheduler_template = normalized["scheduler_instruction"]
    if not isinstance(scheduler_template, str):
        raise PromptBundleError("control_scheduler_invalid")
    scheduler_instruction = scheduler_template.format(task_id=contract.task_id)
    worker_stdin = _bind_fixture_tokens(
        normalized["worker_stdin"],
        {
            "$TASK_ID": contract.task_id,
            "$PACKET_SHA256": packet_sha256,
            "$SCHEDULER_INSTRUCTION": scheduler_instruction,
            "$PRIOR_TASK_EVIDENCE": prior_evidence,
        },
    )
    result_contract = _json_copy(normalized["result_contract"])
    production_input = {
        "source_commit": CONTROL_SOURCE_COMMIT,
        "scheduler_instruction": scheduler_instruction,
        "worker_stdin": worker_stdin,
        "packet_bytes": packet_bytes,
        "spec_sections": spec_sections,
        "prior_task_evidence": prior_evidence,
        "result_contract": result_contract,
        "output_schema": fixture["output_schema"],
    }
    prompt = _canonical_bytes(production_input).decode()
    digest = case_sha256 or _case_digest(
        contract, prior_task_evidence=prior_evidence
    )
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


def build_scout_bundle(
    contract: TaskContractV4,
    *,
    bounded_context: Iterable[Mapping[str, object]] = (),
    fixture_path: Path | None = None,
    case_sha256: str | None = None,
) -> PromptBundle:
    """Build the bounded Terra read-only, non-verdict quality treatment."""

    fixture = _control_fixture(fixture_path or _default_fixture_path())
    context = _safe_json(tuple(bounded_context), "bounded_context")
    payload = {
        "role": "scout",
        "authority": {
            "read_only": True,
            "writes_allowed": False,
            "verdict_capable": False,
            "guidance": "Bounded read-only scout. Make no writes and issue no verdict.",
        },
        "task_contract": _contract_body(contract),
        "task_contract_sha256": contract.contract_sha256,
        "bounded_visible_context": context,
        "result_schema": fixture["output_schema"],
        "result_schema_sha256": CONTROL_OUTPUT_SCHEMA_SHA256,
    }
    prompt = (
        "You are a bounded read-only scout. Make no writes and issue no verdict.\n"
        + _canonical_bytes(payload).decode()
    )
    digest = case_sha256 or _case_digest(contract, bounded_context=context)
    return _bundle(
        treatment_id=SCOUT_TREATMENT,
        prompt=prompt,
        contract=contract,
        case_sha256=digest,
        route=SCOUT_ROUTE,
        role="scout",
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
        prior_task_evidence=evidence,
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
