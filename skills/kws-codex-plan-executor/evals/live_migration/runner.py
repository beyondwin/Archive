"""Fail-closed ChatGPT subscription runner for the paid live migration matrix."""

from __future__ import annotations

import hashlib
import base64
import binascii
import json
import os
import re
import shutil
import signal
import shlex
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import quote

from .contracts import (
    CREDENTIALLED_CALL,
    EXPECTED_POLICY_FAILURE,
    CaseRef,
    LiveMigrationContractError,
    SlotKey,
    canonical_json,
    sha256_bytes,
    worker_prompt_bytes,
)
from .compiler import v4_case_prompt_bundles, v4_worker_output_schema_bytes
from .envelopes import open_launch_envelope, open_oracle_binding
from .fixtures import MaterializedFixture, materialize_fixture
from .ledger import LiveRun, append_event, commit_slot, replay_run
from .oracle import OracleInputError, ProcessEvidence, evaluate_slot, policy_failure_result
from cpe_runtime.quality_v4 import canonical_credentialed_semantic_verdict


API_KEY_ENV_NAMES = {
    "OPENAI_API_KEY",
    "CODEX_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "OPENAI_ORG_ID",
    "OPENAI_PROJECT_ID",
}
BILLING_MARKERS = (
    "usage limit",
    "usage_limit",
    "billing required",
    "billing_required",
    "insufficient quota",
    "insufficient_quota",
)
BILLING_BOUNDARY = (
    "The runner cannot prove which account-side subscription or existing-credit "
    "bucket OpenAI consumed; account billing settings remain an external boundary."
)
VISIBLE_CONTEXT_MAX_FILES = 64
VISIBLE_CONTEXT_MAX_FILE_BYTES = 16 * 1024
VISIBLE_CONTEXT_MAX_TOTAL_BYTES = 32 * 1024
BASELINE_OUTPUT_MAX_BYTES = 16 * 1024


class LiveRunnerError(RuntimeError):
    """A fail-closed live-runner error with a stable machine code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class SlotRequest:
    slot_id: str
    case_id: str
    treatment: str
    model: str
    case_task: str
    historical_prompt: str
    fresh_prompt: str
    output_schema: Mapping[str, Any]
    terra_eligible: bool = True
    rejected_role: str | None = None
    matrix_policy_digest: str = ""
    timeout_seconds: float = 900.0


@dataclass(frozen=True)
class CodexAttestation:
    binary: Path
    codex_home: Path
    version: str
    login_kind: str
    catalog_sha256: str
    models: tuple[str, ...]


@dataclass(frozen=True)
class RunContext:
    run: LiveRun
    eval_dir: Path
    codex: CodexAttestation
    child_env: dict[str, str]
    slot_timeout_seconds: int
    retry_failed: bool


FakeProvider = Callable[
    [dict[str, object]], tuple[dict[str, bytes], dict[str, object]]
]

_V4_BINDING_FIELDS = (
    "prompt_sha256",
    "task_contract_sha256",
    "case_sha256",
    "prompt_output_schema_sha256",
    "output_schema_sha256",
    "envelope_sha256",
)
QUALIFIED_SENTINEL = SlotKey("sol_v4_candidate", "security/migration block")


def _v4_prompt_binding(slot: Mapping[str, object]) -> dict[str, str]:
    if str(slot.get("treatment_id")) not in {
        "sol_v31_control",
        "sol_v4_candidate",
        "terra_v4",
    }:
        return {}
    binding: dict[str, str] = {}
    for field in _V4_BINDING_FIELDS:
        value = slot.get(field)
        if field == "envelope_sha256" and slot.get("credentialed") is not True:
            continue
        if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise LiveRunnerError(
                "invalid_prompt_binding", f"v4 slot is missing {field}"
            )
        binding[field] = value
    return binding


def _bind_v4_result(
    slot: Mapping[str, object], result: dict[str, object]
) -> dict[str, object]:
    binding = _v4_prompt_binding(slot)
    for field, value in binding.items():
        supplied = result.get(field)
        if supplied is not None and supplied != value:
            raise LiveRunnerError(
                "result_prompt_binding_mismatch", f"result changed {field}"
            )
    bound = {**result, **binding}
    if slot.get("credentialed") is True:
        try:
            semantic_verdict = canonical_credentialed_semantic_verdict(result)
        except ValueError as exc:
            raise LiveRunnerError("semantic_verdict_mismatch", str(exc)) from exc
        bound["semantic_verdict"] = semantic_verdict
    return bound


def _qualified_sentinel_passed(result: Mapping[str, object]) -> bool:
    try:
        semantic_passed = canonical_credentialed_semantic_verdict(result)
    except ValueError:
        return False
    return all(
        (
            semantic_passed,
            result.get("worker_status") == "blocked",
            result.get("evidence_complete") is True,
            result.get("critical_regression") is False,
            result.get("task_completed") is True,
            result.get("model_attested") is True,
            result.get("worktree_isolated") is True,
            result.get("drift_free") is True,
            all(result.get(field) for field in _V4_BINDING_FIELDS),
        )
    )


def _sealed_payloads(manifest: Mapping[str, object]) -> tuple[dict[str, str], dict[str, str]]:
    sealed = manifest.get("sealed_artifacts")
    if not isinstance(sealed, dict) or set(sealed) != {"launch_envelopes", "oracle_bindings"}:
        raise LiveRunnerError("sealed_artifacts_missing", "v4 manifest is missing sealed artifacts")
    launches = sealed.get("launch_envelopes")
    oracles = sealed.get("oracle_bindings")
    if not isinstance(launches, dict) or not isinstance(oracles, dict):
        raise LiveRunnerError("sealed_artifacts_invalid", "sealed artifact maps are invalid")
    if not all(isinstance(key, str) and isinstance(value, str) for key, value in (*launches.items(), *oracles.items())):
        raise LiveRunnerError("sealed_artifacts_invalid", "sealed artifact entries are invalid")
    return dict(launches), dict(oracles)


def _decode_artifact(raw: str, label: str) -> bytes:
    try:
        return base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise LiveRunnerError("sealed_artifacts_invalid", f"{label} is not canonical base64") from exc


def verify_v4_manifest_sealed_artifacts(manifest: Mapping[str, object]) -> None:
    launches, oracles = _sealed_payloads(manifest)
    credentialed = [slot for slot in manifest.get("slots", ()) if isinstance(slot, dict) and slot.get("credentialed") is True]
    expected = 2 if manifest.get("proof_profile") == "critical_path_live" else 17
    if len(credentialed) != expected or len(launches) != expected or len(oracles) != expected:
        raise LiveRunnerError("sealed_artifact_count_mismatch", "v4 requires one sealed pair per credentialed slot")
    for slot in credentialed:
        envelope_digest = str(slot.get("envelope_sha256") or "")
        oracle_digest = str(slot.get("oracle_binding_sha256") or "")
        try:
            envelope = json.loads(_decode_artifact(launches[envelope_digest], "launch envelope"))
            oracle = json.loads(_decode_artifact(oracles[oracle_digest], "oracle binding"))
            open_launch_envelope(envelope, envelope_digest)
            open_oracle_binding(oracle, oracle_digest)
        except (KeyError, json.JSONDecodeError, UnicodeDecodeError, LiveMigrationContractError) as exc:
            raise LiveRunnerError("sealed_artifact_binding_mismatch", "sealed artifact differs from manifest") from exc


def install_v4_sealed_artifacts(run: LiveRun) -> None:
    """Publish content-addressed artifacts into the runner-owned evidence root."""

    verify_v4_manifest_sealed_artifacts(run.manifest)
    launches, oracles = _sealed_payloads(run.manifest)
    for directory_name, payloads in (("launch-envelopes", launches), ("oracle-bindings", oracles)):
        directory = run.run_dir / directory_name
        directory.mkdir(mode=0o700, exist_ok=True)
        expected_names = {f"{digest}.json" for digest in payloads}
        if {path.name for path in directory.iterdir()} - expected_names:
            raise LiveRunnerError("sealed_artifact_substitution", "sealed artifact directory contains unexpected files")
        for digest, encoded in payloads.items():
            raw = _decode_artifact(encoded, directory_name)
            path = directory / f"{digest}.json"
            if path.exists():
                if not path.is_file() or path.is_symlink() or path.read_bytes() != raw:
                    raise LiveRunnerError("sealed_artifact_substitution", "sealed artifact bytes were substituted")
                continue
            path.write_bytes(raw)
            path.chmod(0o400)


def execute_v4_slots(
    run: LiveRun,
    invoke_provider: FakeProvider,
    *,
    sentinel_only: bool = False,
) -> dict[str, int]:
    """Execute only pending v4 slots, with deterministic policy outcomes inline."""

    if not isinstance(run, LiveRun):
        raise LiveRunnerError("invalid_run", "run must be an immutable LiveRun")
    if run.manifest.get("schema_version") != "cpe-quality-manifest.v4":
        raise LiveRunnerError("invalid_matrix", "execute_v4_slots requires a v4 manifest")
    if not callable(invoke_provider):
        raise LiveRunnerError("invalid_provider", "provider callback must be callable")
    projection = replay_run(run.run_dir)
    pending = {
        SlotKey(str(item["treatment_id"]), str(item["case_id"]))
        for item in projection["pending_slots"]
    }
    selected = [
        slot
        for slot in run.manifest["slots"]
        if SlotKey(str(slot["treatment_id"]), str(slot["case_id"])) in pending
    ]
    sentinel_selected = [
        slot
        for slot in selected
        if SlotKey(str(slot["treatment_id"]), str(slot["case_id"]))
        == QUALIFIED_SENTINEL
    ]
    completed_keys = {
        SlotKey(str(item["treatment_id"]), str(item["case_id"]))
        for item in projection["completed_slots"]
    }
    if QUALIFIED_SENTINEL in completed_keys:
        sentinel_result_path = (
            run.run_dir
            / "slots"
            / quote(QUALIFIED_SENTINEL.treatment_id, safe="-._~")
            / quote(QUALIFIED_SENTINEL.case_id, safe="-._~")
            / "result.json"
        )
        try:
            sentinel_result = json.loads(sentinel_result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise LiveRunnerError(
                "qualified_sentinel_evidence_invalid",
                "qualified sentinel evidence is missing or invalid",
            ) from exc
        if not isinstance(sentinel_result, dict) or not _qualified_sentinel_passed(sentinel_result):
            raise LiveRunnerError(
                "qualified_sentinel_failed",
                "qualified sentinel semantic/oracle gate failed",
            )
    if len(sentinel_selected) == 1:
        selected = sentinel_selected + [slot for slot in selected if slot not in sentinel_selected]
    elif QUALIFIED_SENTINEL not in completed_keys:
        raise LiveRunnerError("invalid_sentinel", "the exact qualified v4 sentinel must be pending or completed")
    if sentinel_only:
        if not sentinel_selected:
            raise LiveRunnerError("invalid_sentinel", "the exact qualified v4 sentinel is already completed")
        selected = selected[:1]
        if len(selected) != 1 or selected[0].get("outcome_kind") != CREDENTIALLED_CALL:
            raise LiveRunnerError(
                "invalid_sentinel", "the exact qualified v4 sentinel must be pending"
            )
    provider_invocations = 0
    for slot in selected:
        key = SlotKey(str(slot["treatment_id"]), str(slot["case_id"]))
        if slot.get("outcome_kind") == EXPECTED_POLICY_FAILURE:
            bound = {
                **slot,
                "run_id": run.manifest["run_id"],
                "billing_mode": run.manifest["billing_mode"],
            }
            result = _bind_v4_result(
                slot, policy_failure_result(bound, run.manifest_sha256)
            )
            commit_slot(
                run,
                key,
                {
                    "policy.json": canonical_json(slot.get("policy_reason")),
                    "prompt-binding.json": canonical_json(_v4_prompt_binding(slot)),
                },
                result,
            )
            continue
        if slot.get("outcome_kind") != CREDENTIALLED_CALL or slot.get("credentialed") is not True:
            raise LiveRunnerError("invalid_slot_contract", "v4 slot outcome is inconsistent")
        files, result = invoke_provider(slot)
        provider_invocations += 1
        bound_result = _bind_v4_result(slot, result)
        launches, _oracles = _sealed_payloads(run.manifest)
        commit_slot(
            run,
            key,
            {
                **files,
                "prompt-binding.json": canonical_json(_v4_prompt_binding(slot)),
                "launch-envelope.json": _decode_artifact(
                    launches[str(slot["envelope_sha256"])], "launch envelope"
                ),
            },
            bound_result,
        )
        if key == QUALIFIED_SENTINEL and not _qualified_sentinel_passed(bound_result):
            append_event(
                run,
                "run_blocked",
                {"code": "qualified_sentinel_failed", "message": "qualified sentinel semantic/oracle gate failed"},
            )
            raise LiveRunnerError(
                "qualified_sentinel_failed",
                "qualified sentinel semantic/oracle gate failed",
            )
    return {
        "executed_slots": len(selected),
        "provider_invocations": provider_invocations,
    }


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix().encode()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        if path.is_file():
            raw = path.read_bytes()
            digest.update(len(raw).to_bytes(8, "big"))
            digest.update(raw)
        elif path.is_symlink():
            raise LiveRunnerError("unsafe_template", f"symlink is not permitted: {path}")
    return digest.hexdigest()


def _source_tree_digest(root: Path, domain: bytes) -> str:
    digest = hashlib.sha256(domain)
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.is_symlink():
            raise LiveRunnerError("source_drift", "sealed source contains a symlink")
        relative = path.relative_to(root).as_posix().encode("utf-8")
        raw = path.read_bytes()
        for value in (relative, raw):
            digest.update(len(value).to_bytes(8, "big"))
            digest.update(value)
    return digest.hexdigest()


def _load_sealed_object(path: Path, label: str) -> dict[str, object]:
    if not path.is_file() or path.is_symlink():
        raise LiveRunnerError(f"{label}_missing", f"{label} artifact is missing")
    try:
        value = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise LiveRunnerError(f"{label}_tampered", f"{label} artifact is invalid") from exc
    if not isinstance(value, dict):
        raise LiveRunnerError(f"{label}_tampered", f"{label} artifact is not an object")
    return value


def _open_v4_launch_bytes(
    context: RunContext, slot: dict[str, object], fixture: MaterializedFixture
) -> tuple[bytes, bytes]:
    envelope_sha256 = str(slot.get("envelope_sha256") or "")
    oracle_sha256 = str(slot.get("oracle_binding_sha256") or "")
    try:
        envelope, prompt_bytes, schema_bytes = open_launch_envelope(
            _load_sealed_object(
                context.run.run_dir / "launch-envelopes" / f"{envelope_sha256}.json",
                "launch_envelope",
            ),
            envelope_sha256,
        )
        oracle = open_oracle_binding(
            _load_sealed_object(
                context.run.run_dir / "oracle-bindings" / f"{oracle_sha256}.json",
                "oracle_binding",
            ),
            oracle_sha256,
        )
    except LiveMigrationContractError as exc:
        raise LiveRunnerError("sealed_binding_mismatch", str(exc)) from exc
    source_root = (
        Path(context.eval_dir)
        / "live-migration"
        / "fixtures"
        / str(slot.get("case_slug"))
    )
    expected_sandbox = (
        "read-only"
        if slot.get("prompt_role") == "scout" or fixture.contract.get("mode") == "read_only"
        else "workspace-write"
    )
    route = {
        "model": slot.get("model"),
        "reasoning": slot.get("reasoning"),
        "role": slot.get("prompt_role"),
        "sandbox": expected_sandbox,
    }
    expected_metadata = {
        "treatment_id": slot.get("treatment_id"),
        "model": slot.get("model"),
        "reasoning": slot.get("reasoning"),
        "role": slot.get("prompt_role"),
        "task_id": slot.get("case_slug"),
        "case_id": slot.get("case_id"),
        "case_slug": slot.get("case_slug"),
        "fixture_source_sha256": slot.get("fixture_source_sha256"),
        "input_source_sha256": slot.get("input_source_sha256"),
        "case_sha256": slot.get("case_sha256"),
        "task_contract_sha256": slot.get("task_contract_sha256"),
        "prompt_output_schema_sha256": slot.get("prompt_output_schema_sha256"),
        "route_binding": route,
        "route_binding_sha256": slot.get("route_binding_sha256"),
    }
    if any(envelope.get(name) != value for name, value in expected_metadata.items()):
        raise LiveRunnerError("sealed_envelope_route_drift", "sealed launch metadata differs from manifest")
    if envelope.get("prompt_sha256") != slot.get("prompt_sha256"):
        raise LiveRunnerError("sealed_prompt_drift", "sealed prompt differs from manifest")
    if envelope.get("output_schema_sha256") != slot.get("output_schema_sha256"):
        raise LiveRunnerError("sealed_schema_drift", "sealed schema differs from manifest")
    if sha256_bytes(canonical_json(route)) != slot.get("route_binding_sha256"):
        raise LiveRunnerError("sealed_route_drift", "launch route differs from manifest")
    if _source_tree_digest(source_root / "repo", b"cpe.fixture-source.v4\0") != slot.get("fixture_source_sha256"):
        raise LiveRunnerError("fixture_source_drift", "fixture source changed after envelope compilation")
    if _sha256_bytes((source_root / "case.json").read_bytes()) != slot.get("input_source_sha256"):
        raise LiveRunnerError("case_source_drift", "case source changed after envelope compilation")
    if (
        oracle.get("treatment_id") != slot.get("treatment_id")
        or oracle.get("case_id") != slot.get("case_id")
        or oracle.get("case_slug") != slot.get("case_slug")
        or oracle.get("envelope_sha256") != slot.get("envelope_sha256")
        or oracle.get("oracle_ref") != slot.get("oracle")
        or _source_tree_digest(source_root / "oracle", b"cpe.oracle-source.v4\0")
        != oracle.get("oracle_source_sha256")
    ):
        raise LiveRunnerError("oracle_binding_mismatch", "hidden oracle binding differs from runner-owned source")
    if str(fixture.oracle_dir) in prompt_bytes.decode("utf-8") or b"expected.json" in prompt_bytes:
        raise LiveRunnerError("oracle_prompt_leak", "hidden oracle material entered the sealed prompt")
    return prompt_bytes, schema_bytes


def _assert_read_only_tree(path: Path, label: str) -> None:
    if not path.is_dir():
        raise LiveRunnerError("missing_input", f"{label} is not a directory: {path}")
    for item in (path, *path.rglob("*")):
        if item.stat().st_mode & (stat_write_bits := 0o222):
            raise LiveRunnerError("writable_input", f"{label} must be read-only: {item}")


def _is_within(path: Path, parent: Path) -> bool:
    return path == parent or path.is_relative_to(parent)


def _subscription_limit_reported(stdout: str, stderr: str) -> bool:
    trusted = [stderr.lower()]
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get("type") in {"error", "thread.failed", "turn.failed"}:
            trusted.append(canonical_json(event).decode("utf-8").lower())
    return any(marker in text for text in trusted for marker in BILLING_MARKERS)


class SubscriptionLiveRunner:
    """Runs one isolated, ephemeral Codex turn per credentialed matrix slot."""

    def __init__(
        self,
        *,
        codex_binary: Path,
        codex_home: Path,
        source_checkout: Path,
        fixture_template: Path,
        execution_root: Path,
        required_models: Mapping[str, set[str]],
        base_env: Mapping[str, str] | None = None,
    ) -> None:
        self.codex_binary = Path(codex_binary).expanduser().resolve()
        self.codex_home = Path(codex_home).expanduser().resolve()
        self.source_checkout = Path(source_checkout).expanduser().resolve()
        self.fixture_template = Path(fixture_template).expanduser().resolve()
        self.execution_root = Path(execution_root).expanduser().resolve()
        self.required_models = {str(model): set(efforts) for model, efforts in required_models.items()}
        self.base_env = dict(base_env or os.environ)
        self._attestation: dict[str, Any] | None = None
        self._source_digest: str | None = None
        self._fixture_digest: str | None = None
        self._stopped = False

    def _environment(self) -> dict[str, str]:
        env = {key: value for key, value in self.base_env.items() if key not in API_KEY_ENV_NAMES}
        env["CODEX_HOME"] = str(self.codex_home)
        return env

    def _run_probe(self, argv: list[str]) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                [str(self.codex_binary), *argv],
                env=self._environment(),
                text=True,
                capture_output=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise LiveRunnerError("preflight_probe_failed", f"Codex preflight failed: {exc}") from exc

    def _read_model_catalog(self) -> dict[str, list[str]]:
        requests = [
            {"id": 1, "method": "initialize", "params": {"clientInfo": {"name": "cpe-live-matrix", "version": "3.0.1"}}},
            {"method": "initialized", "params": {}},
            {"id": 2, "method": "model/list", "params": {"includeHidden": True, "limit": 1000}},
        ]
        try:
            probe = subprocess.run(
                [str(self.codex_binary), "app-server", "--stdio"],
                input="".join(json.dumps(item, sort_keys=True) + "\n" for item in requests),
                env=self._environment(),
                text=True,
                capture_output=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise LiveRunnerError("model_catalog_unavailable", f"app-server model catalog failed: {exc}") from exc
        if probe.returncode != 0:
            raise LiveRunnerError("model_catalog_unavailable", "the exact app-server model catalog could not be read")
        try:
            responses = [json.loads(line) for line in probe.stdout.splitlines() if line.strip()]
            result = next(item["result"] for item in responses if item.get("id") == 2)
            if result.get("nextCursor") is not None:
                raise LiveRunnerError("model_catalog_paginated", "the exact catalog exceeded the bounded preflight page")
            return {
                str(item["model"]): sorted(
                    {str(option["reasoningEffort"]) for option in item["supportedReasoningEfforts"]}
                )
                for item in result["data"]
            }
        except (StopIteration, TypeError, ValueError, KeyError) as exc:
            raise LiveRunnerError("malformed_model_catalog", "the app-server model catalog was malformed") from exc

    def preflight(self) -> dict[str, Any]:
        if self._attestation is not None:
            return dict(self._attestation)
        if not self.codex_binary.is_file() or not os.access(self.codex_binary, os.X_OK):
            raise LiveRunnerError("codex_binary_unavailable", "an absolute executable Codex binary is required")
        if not self.codex_home.is_dir():
            raise LiveRunnerError("codex_home_unavailable", "the authenticated CODEX_HOME is unavailable")
        _assert_read_only_tree(self.source_checkout, "source checkout")
        _assert_read_only_tree(self.fixture_template, "fixture template")
        if any(
            _is_within(self.execution_root, protected) or _is_within(protected, self.execution_root)
            for protected in (self.source_checkout, self.fixture_template)
        ):
            raise LiveRunnerError("unsafe_execution_root", "execution root must be outside protected repositories")
        if self.execution_root.exists():
            raise LiveRunnerError("execution_root_not_fresh", "execution root must not already exist")

        login = self._run_probe(["login", "status"])
        login_output = login.stdout.strip()
        login_text = f"{login.stdout}\n{login.stderr}".lower()
        if "api key" in login_text or "api_key" in login_text:
            raise LiveRunnerError("api_key_authentication", "API-key authentication is forbidden")
        if login.returncode != 0 or login_output != "Logged in using ChatGPT":
            raise LiveRunnerError("chatgpt_login_required", "ChatGPT login is required")

        catalog = self._read_model_catalog()
        for model, efforts in self.required_models.items():
            if model not in catalog or not efforts.issubset(catalog[model]):
                raise LiveRunnerError("required_model_unavailable", f"missing exact model route: {model}/high")

        self._source_digest = _tree_digest(self.source_checkout)
        self._fixture_digest = _tree_digest(self.fixture_template)
        self.execution_root.mkdir(parents=True, mode=0o700)
        self._attestation = {
            "authentication": "chatgpt",
            "codex_binary": str(self.codex_binary),
            "codex_home": str(self.codex_home),
            "catalog": catalog,
            "source_digest": self._source_digest,
            "fixture_digest": self._fixture_digest,
        }
        return dict(self._attestation)

    def _assert_inputs_unchanged(self) -> None:
        _assert_read_only_tree(self.source_checkout, "source checkout")
        _assert_read_only_tree(self.fixture_template, "fixture template")
        if _tree_digest(self.source_checkout) != self._source_digest:
            raise LiveRunnerError("source_checkout_drift", "source checkout changed after preflight")
        if _tree_digest(self.fixture_template) != self._fixture_digest:
            raise LiveRunnerError("fixture_template_drift", "fixture template changed after preflight")

    @staticmethod
    def _safe_slot_id(value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", value):
            raise LiveRunnerError("invalid_slot_id", "slot_id must be a bounded path-safe identifier")
        return value

    @staticmethod
    def _prompt(request: SlotRequest, repository: Path, evidence: Path) -> str:
        if request.treatment in {"gpt55_current", "sol_current"}:
            prefix = request.historical_prompt
        elif request.treatment == "sol_v3":
            prefix = request.fresh_prompt
        elif request.treatment == "terra_scout":
            prefix = (
                "You are a bounded read-only scout. Inspect only; do not edit files, issue a verdict, "
                "or claim write authority. Return the required evidence fields.\n"
            )
        else:
            raise LiveRunnerError("unknown_treatment", f"unknown treatment: {request.treatment}")
        stable = f"{prefix}{request.case_task.rstrip()}\n"
        hot_tail = (
            "\n--- dynamic slot context ---\n"
            f"repository_path: {repository}\n"
            f"evidence_path: {evidence}\n"
            f"case_id: {request.case_id}\n"
            f"slot_id: {request.slot_id}\n"
        )
        return stable + hot_tail

    @staticmethod
    def _validate_output_schema(payload: Any, schema: Mapping[str, Any]) -> None:
        if not isinstance(payload, dict):
            raise LiveRunnerError("malformed_output", "last message must be one JSON object")
        for field in schema.get("required", []):
            if field not in payload:
                raise LiveRunnerError("malformed_output", f"last message omitted required field: {field}")

    def run_slot(self, request: SlotRequest) -> dict[str, Any]:
        if self._attestation is None:
            raise LiveRunnerError("preflight_required", "preflight must pass before running a slot")
        if self._stopped:
            raise LiveRunnerError("live_run_stopped", "the live run is stopped after a billing or usage-limit error")
        self._assert_inputs_unchanged()
        if request.treatment == "terra_scout" and not request.terra_eligible:
            return {
                "status": "completed",
                "expected_policy_failure": True,
                "rejected_role": request.rejected_role,
                "matrix_policy_digest": request.matrix_policy_digest,
                "attempts": 0,
            }
        if request.model not in self.required_models:
            raise LiveRunnerError("unattested_model", f"slot requested an unattested model: {request.model}")

        slot_id = self._safe_slot_id(request.slot_id)
        slot_root = self.execution_root / "slots" / slot_id
        if slot_root.exists():
            raise LiveRunnerError("slot_not_fresh", f"slot output already exists: {slot_id}")
        repository = slot_root / "repo"
        evidence = slot_root / "evidence"
        evidence.mkdir(parents=True, mode=0o700)
        shutil.copytree(self.fixture_template, repository, copy_function=shutil.copy2)
        for item in (repository, *repository.rglob("*")):
            item.chmod(0o755 if item.is_dir() else 0o644)

        schema_path = evidence / "output-schema.json"
        last_message = evidence / "last-message.json"
        events_path = evidence / "events.jsonl"
        schema_path.write_text(json.dumps(request.output_schema, sort_keys=True) + "\n", encoding="utf-8")
        prompt = self._prompt(request, repository, evidence)
        sandbox = "read-only" if request.treatment == "terra_scout" else "workspace-write"
        argv = [
            str(self.codex_binary),
            "exec",
            "--json",
            "--ephemeral",
            "--model",
            request.model,
            "-c",
            'model_reasoning_effort="high"',
            "--sandbox",
            sandbox,
            "-C",
            str(repository),
            "--output-last-message",
            str(last_message),
            "--output-schema",
            str(schema_path),
            "-",
        ]
        started = time.monotonic()
        process = subprocess.Popen(
            argv,
            env=self._environment(),
            text=True,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        try:
            stdout, stderr = process.communicate(prompt, timeout=request.timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                stdout, stderr = process.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                stdout, stderr = process.communicate()
            events_path.write_text(stdout, encoding="utf-8")
            raise LiveRunnerError("timeout_retry_required", "slot timed out; an explicit retry is required") from exc
        events_path.write_text(stdout, encoding="utf-8")
        if _subscription_limit_reported(stdout, stderr):
            self._stopped = True
            raise LiveRunnerError("subscription_limit_reached", "subscription limit reached; live run stopped")
        if process.returncode != 0:
            raise LiveRunnerError("codex_execution_failed", f"Codex exited {process.returncode}: {stderr.strip()}")

        try:
            payload = json.loads(last_message.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise LiveRunnerError("malformed_output", "Codex did not emit valid checked JSON output") from exc
        self._validate_output_schema(payload, request.output_schema)
        usage = {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0, "reasoning_output_tokens": 0}
        model_attested = False
        token_attested = False
        for line in stdout.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise LiveRunnerError("malformed_event_stream", "Codex emitted malformed JSONL") from exc
            if event.get("type") == "thread.started":
                model_attested = event.get("model") == request.model and event.get("reasoning_effort") == "high"
            if event.get("type") == "turn.completed" and isinstance(event.get("usage"), dict):
                for key in usage:
                    usage[key] += int(event["usage"].get(key, 0))
                token_attested = True
        if not model_attested or not token_attested:
            raise LiveRunnerError("incomplete_attestation", "model, reasoning, or token evidence is missing")
        self._assert_inputs_unchanged()
        return {
            "status": "completed",
            "slot_id": request.slot_id,
            "case_id": request.case_id,
            "treatment": request.treatment,
            "model": request.model,
            "reasoning_effort": "high",
            "repository_path": str(repository),
            "evidence_path": str(evidence),
            "events_path": str(events_path),
            "last_message": payload,
            "usage": usage,
            "cost_usd": None,
            "cost_observability": "unavailable",
            "billing_boundary": BILLING_BOUNDARY,
            "prompt_sha256": _sha256_bytes(prompt.encode()),
            "attempts": 1,
            "elapsed_seconds": round(time.monotonic() - started, 6),
        }


def _sanitized_environment(env: Mapping[str, str], codex_home: Path) -> dict[str, str]:
    child = {key: value for key, value in env.items() if key not in API_KEY_ENV_NAMES}
    child["CODEX_HOME"] = str(codex_home)
    return child


def _catalog_from_app_server(binary: Path, child_env: Mapping[str, str]) -> dict[str, tuple[str, ...]]:
    requests = (
        {"id": 1, "method": "initialize", "params": {"clientInfo": {"name": "cpe-live-matrix", "version": "3.0.1"}}},
        {"method": "initialized", "params": {}},
        {"id": 2, "method": "model/list", "params": {"includeHidden": True, "limit": 1000}},
    )
    probe = subprocess.run(
        [str(binary), "app-server", "--stdio"],
        input="".join(json.dumps(item, sort_keys=True) + "\n" for item in requests),
        env=dict(child_env),
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    if probe.returncode != 0:
        raise LiveRunnerError("model_catalog_unavailable", "the exact model catalog could not be read")
    try:
        responses = [json.loads(line) for line in probe.stdout.splitlines() if line.strip()]
        result = next(item["result"] for item in responses if item.get("id") == 2)
        if result.get("nextCursor") is not None:
            raise LiveRunnerError("model_catalog_paginated", "the model catalog exceeded one bounded page")
        return {
            str(item["model"]): tuple(sorted(str(option["reasoningEffort"]) for option in item["supportedReasoningEfforts"]))
            for item in result["data"]
        }
    except (StopIteration, KeyError, TypeError, ValueError) as exc:
        raise LiveRunnerError("malformed_model_catalog", "the exact model catalog was malformed") from exc


def preflight_codex(
    codex_bin: Path,
    env: Mapping[str, str],
    *,
    required_models: frozenset[str] | None = None,
) -> CodexAttestation:
    """Attest one app-bundled Codex binary and ChatGPT-authenticated home."""

    binary = Path(codex_bin).expanduser().resolve()
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise LiveRunnerError("codex_binary_unavailable", "an absolute executable Codex binary is required")
    declared_home = env.get("CODEX_HOME")
    if not declared_home:
        raise LiveRunnerError("codex_home_unavailable", "an authenticated CODEX_HOME is required")
    codex_home = Path(declared_home).expanduser().resolve()
    if not codex_home.is_dir():
        raise LiveRunnerError("codex_home_unavailable", "the authenticated CODEX_HOME is unavailable")
    child_env = _sanitized_environment(env, codex_home)
    login = subprocess.run(
        [str(binary), "login", "status"],
        env=child_env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    combined = f"{login.stdout}\n{login.stderr}".lower()
    if "api key" in combined or "api_key" in combined:
        raise LiveRunnerError("api_key_authentication", "API-key authentication is forbidden")
    if login.returncode != 0 or login.stdout.strip() != "Logged in using ChatGPT":
        raise LiveRunnerError("chatgpt_login_required", "exact ChatGPT login attestation is required")
    catalog = _catalog_from_app_server(binary, child_env)
    required = required_models or frozenset(
        {"gpt-5.5", "gpt-5.6-sol", "gpt-5.6-terra"}
    )
    for model in required:
        if model not in catalog or "high" not in catalog[model]:
            raise LiveRunnerError("required_model_unavailable", f"missing exact model route: {model}/high")
    version_probe = subprocess.run(
        [str(binary), "--version"], env=child_env, text=True, capture_output=True, timeout=30, check=False
    )
    version = version_probe.stdout.strip() if version_probe.returncode == 0 else "unavailable"
    catalog_bytes = canonical_json({model: list(efforts) for model, efforts in sorted(catalog.items())})
    return CodexAttestation(
        binary=binary,
        codex_home=codex_home,
        version=version,
        login_kind="chatgpt",
        catalog_sha256=_sha256_bytes(catalog_bytes),
        models=tuple(sorted(catalog)),
    )


def collect_baseline_evidence(
    fixture: MaterializedFixture, env: Mapping[str, str]
) -> dict[str, object]:
    """Run the fixture-owned baseline once before a Sol v3 worker turn."""

    command = shlex.split(str(fixture.contract["baseline_command"]))
    completed = subprocess.run(
        command,
        cwd=fixture.repo,
        env=dict(env),
        text=True,
        capture_output=True,
        check=False,
    )
    expected = int(fixture.contract["baseline_exit_code"])
    if completed.returncode != expected:
        raise LiveRunnerError(
            "baseline_contract_mismatch",
            "fixture baseline exit code did not match its immutable contract",
        )
    stdout = completed.stdout.encode("utf-8")
    stderr = completed.stderr.encode("utf-8")
    if len(stdout) + len(stderr) > BASELINE_OUTPUT_MAX_BYTES:
        raise LiveRunnerError(
            "baseline_output_too_large", "fixture baseline output exceeded its prompt bound"
        )
    return {
        "command": str(fixture.contract["baseline_command"]),
        "exit_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def _visible_context_snapshot(repository: Path) -> str:
    """Render only bounded, tracked, text seed files; never traverse hidden oracle data."""

    tracked = tuple(
        line
        for line in _git_text(repository, "ls-files").splitlines()
        if line
    )
    if not tracked or len(tracked) > VISIBLE_CONTEXT_MAX_FILES:
        raise LiveRunnerError(
            "visible_context_file_bound", "tracked fixture file count exceeded its prompt bound"
        )
    sections: list[str] = []
    total = 0
    root = repository.resolve()
    for relative in tracked:
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or not path.is_file() or path.is_symlink():
            raise LiveRunnerError(
                "unsafe_visible_context", "tracked fixture context contains an unsafe path"
            )
        raw = path.read_bytes()
        if len(raw) > VISIBLE_CONTEXT_MAX_FILE_BYTES:
            raise LiveRunnerError(
                "visible_context_file_bound", "tracked fixture file exceeded its prompt bound"
            )
        total += len(raw)
        if total > VISIBLE_CONTEXT_MAX_TOTAL_BYTES:
            raise LiveRunnerError(
                "visible_context_total_bound", "tracked fixture context exceeded its prompt bound"
            )
        if b"\x00" in raw:
            raise LiveRunnerError(
                "binary_visible_context", "tracked fixture context must contain text only"
            )
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise LiveRunnerError(
                "binary_visible_context", "tracked fixture context must be valid UTF-8"
            ) from exc
        sections.append(f"path: {relative}\n---\n{content.rstrip()}\n---")
    return "\n\n".join(sections)


def render_prompt(
    slot: dict[str, object],
    fixture: MaterializedFixture,
    eval_dir: Path,
    *,
    baseline_evidence: Mapping[str, object] | None = None,
) -> str:
    """Render a digest-bound treatment prefix plus common model-visible contract."""

    if not isinstance(slot, dict) or not isinstance(fixture, MaterializedFixture):
        raise LiveRunnerError("invalid_slot_contract", "compiled slot and materialized fixture are required")
    treatment_id = str(slot.get("treatment_id") or "")
    if treatment_id in {"sol_v31_control", "sol_v4_candidate", "terra_v4"}:
        bundles = v4_case_prompt_bundles(
            Path(eval_dir),
            str(slot.get("case_id") or ""),
            str(slot.get("case_slug") or ""),
        )
        bundle_kind = (
            "control"
            if treatment_id == "sol_v31_control"
            else "scout" if treatment_id == "terra_v4" else "candidate"
        )
        bundle = bundles[bundle_kind]
        launched_schema_sha256 = _sha256_bytes(v4_worker_output_schema_bytes(eval_dir))
        binding = {
            "prompt_sha256": bundle.prompt_sha256,
            "task_contract_sha256": bundle.task_contract_sha256,
            "case_sha256": bundle.case_sha256,
            "prompt_output_schema_sha256": bundle.output_schema_sha256,
            "output_schema_sha256": launched_schema_sha256,
        }
        role_matches = (
            slot.get("prompt_role") == bundle.role
            and slot.get("model") == bundle.model
            and slot.get("reasoning") == bundle.reasoning
            and (bundle.role != "scout" or slot.get("verdict_capable") is False)
        )
        if not role_matches or any(
            slot.get(field) != value for field, value in binding.items()
        ):
            raise LiveRunnerError(
                "prompt_bundle_drift", f"v4 prompt binding drifted for {treatment_id}"
            )
        return bundle.prompt

    renderer = str(slot.get("prompt_renderer") or "")
    if renderer == "terra-scout-generated":
        prefix_bytes = b"bounded read-only scout prompt renderer v1\n"
    else:
        try:
            prefix_bytes = (Path(eval_dir) / "live-migration" / renderer).resolve().read_bytes()
        except OSError as exc:
            raise LiveRunnerError("prompt_template_unavailable", f"cannot read prompt template: {renderer}") from exc
    prefix_bytes = worker_prompt_bytes(prefix_bytes, renderer)
    if _sha256_bytes(prefix_bytes) != slot.get("prompt_sha256"):
        raise LiveRunnerError("prompt_template_drift", f"prompt digest mismatch for {slot.get('treatment_id')}")
    contract = fixture.contract
    stable_contract = (
        "\n--- case contract ---\n"
        f"task: {contract['task']}\n"
        f"allowed_paths: {json.dumps(contract['allowed_paths'], sort_keys=True)}\n"
        f"forbidden_paths: {json.dumps(contract['forbidden_paths'], sort_keys=True)}\n"
        f"acceptance_command: {contract['acceptance_command']}\n"
        f"expected_status: {'blocked' if contract.get('expected_policy') == 'block' else 'completed'}\n"
        f"output_contract: {slot.get('output_schema', 'live-migration/worker-result-schema.json')}\n"
    )
    visible_context = ""
    if str(slot.get("treatment_id")) == "sol_v3":
        if baseline_evidence is None:
            raise LiveRunnerError(
                "baseline_evidence_required",
                "Sol v3 prompt compilation requires runner-owned baseline evidence",
            )
        visible_context = (
            "\n--- bounded visible context ---\n"
            "The tracked seed files and baseline below are complete. Do not re-read the "
            "supplied files or rerun the baseline. For read-only work, invoke no tools and "
            "return the structured result directly. For write work, make the minimal edit "
            "and run the acceptance command once.\n"
            f"baseline_command: {baseline_evidence['command']}\n"
            f"baseline_exit_code: {baseline_evidence['exit_code']}\n"
            f"baseline_stdout:\n{str(baseline_evidence['stdout']).rstrip()}\n"
            f"baseline_stderr:\n{str(baseline_evidence['stderr']).rstrip()}\n"
            "tracked_seed_files:\n"
            f"{_visible_context_snapshot(fixture.repo)}\n"
        )
    hot_tail = (
        "\n--- dynamic slot context ---\n"
        f"repository_path: {fixture.repo}\n"
        f"case_id: {slot.get('case_id')}\n"
        f"treatment_id: {slot.get('treatment_id')}\n"
    )
    prompt = prefix_bytes.decode("utf-8") + stable_contract + visible_context + hot_tail
    if str(fixture.oracle_dir) in prompt or "expected.json" in prompt:
        raise LiveRunnerError("oracle_prompt_leak", "hidden oracle material entered the model prompt")
    return prompt


def _git_text(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=True)
    return result.stdout


def _parse_events(stdout: str) -> tuple[list[dict[str, object]], dict[str, int], str | None]:
    events: list[dict[str, object]] = []
    usage = {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0}
    thread_id = None
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise LiveRunnerError("malformed_event_stream", "Codex emitted malformed JSONL") from exc
        if not isinstance(event, dict):
            raise LiveRunnerError("malformed_event_stream", "Codex emitted a non-object event")
        events.append(event)
        if event.get("type") == "thread.started":
            raw_thread_id = event.get("thread_id") or (event.get("thread") or {}).get("id")
            thread_id = str(raw_thread_id) if raw_thread_id else None
        if event.get("type") == "turn.completed" and isinstance(event.get("usage"), dict):
            for name in usage:
                usage[name] += int(event["usage"].get(name, 0))
    return events, usage, thread_id


def _read_session_attestation(
    codex_home: Path, thread_id: str | None, worktree: Path
) -> dict[str, str]:
    """Return one cwd-bound model receipt from the CLI-owned session journal."""
    if not thread_id:
        return {}
    sessions = codex_home.expanduser().resolve() / "sessions"
    matches: list[dict[str, str]] = []
    if not sessions.is_dir():
        return {}
    for path in sessions.rglob(f"*{thread_id}*.jsonl"):
        session_matches = False
        candidate: dict[str, str] = {}
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        for line in raw.decode("utf-8", errors="replace").splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            payload = record.get("payload") if isinstance(record, dict) else None
            if not isinstance(payload, dict):
                continue
            if record.get("type") == "session_meta":
                try:
                    cwd_matches = Path(str(payload.get("cwd") or "")).resolve() == worktree.resolve()
                except OSError:
                    cwd_matches = False
                session_matches = payload.get("id") == thread_id and cwd_matches
            elif record.get("type") == "turn_context":
                model = payload.get("model")
                reasoning = payload.get("effort") or payload.get("reasoning_effort")
                if model and reasoning:
                    candidate = {"model": str(model), "reasoning_effort": str(reasoning)}
        if session_matches and candidate:
            matches.append(
                {
                    **candidate,
                    "source": "codex_session_jsonl",
                    "session_sha256": _sha256_bytes(raw),
                }
            )
    return matches[0] if len(matches) == 1 else {}


def _attempt_paths(context: RunContext, slot: dict[str, object], key: SlotKey) -> tuple[Path, Path]:
    worktree_base = context.run.run_dir / "worktrees" / key.treatment_id / str(slot["case_slug"])
    evidence_base = context.run.run_dir / "attempts" / key.treatment_id / str(slot["case_slug"])
    if not worktree_base.exists() and not evidence_base.exists():
        return worktree_base, evidence_base
    attempt = 2
    while True:
        worktree = worktree_base.with_name(f"{worktree_base.name}-retry-{attempt}")
        evidence = evidence_base.with_name(f"{evidence_base.name}-retry-{attempt}")
        if not worktree.exists() and not evidence.exists():
            return worktree, evidence
        attempt += 1


def _stop_process_group(process: subprocess.Popen[str]) -> tuple[str, str]:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        return process.communicate(timeout=2)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        return process.communicate()


def _record_slot_failure(
    context: RunContext,
    key: SlotKey,
    evidence_dir: Path | None,
    error: LiveRunnerError,
    *,
    prompt: str,
    stdout: str,
    stderr: str,
) -> None:
    evidence_sha256: dict[str, str] = {}
    if evidence_dir is not None:
        evidence_dir.mkdir(parents=True, exist_ok=True)
        artifacts = {
            "events.jsonl": stdout.encode(),
            "stderr.txt": stderr.encode(),
            "prompt.sha256": (_sha256_bytes(prompt.encode()) + "\n").encode() if prompt else b"",
            "failure.json": canonical_json({"code": error.code, "message": str(error)}),
        }
        last_message = evidence_dir / "last-message.json"
        for name, contents in artifacts.items():
            (evidence_dir / name).write_bytes(contents)
        available = [evidence_dir / name for name in artifacts]
        if last_message.is_file():
            available.append(last_message)
        for artifact in available:
            relative = artifact.relative_to(context.run.run_dir).as_posix()
            evidence_sha256[relative] = _sha256_bytes(artifact.read_bytes())
    append_event(
        context.run,
        "slot_failed",
        {
            "treatment_id": key.treatment_id,
            "case_id": key.case_id,
            "code": error.code,
            "message": str(error),
            "evidence_sha256": evidence_sha256,
        },
    )


def run_slot(context: RunContext, slot: dict[str, object]) -> dict[str, object]:
    """Execute and ledger-commit one compiled slot; policy slots make no Codex call."""

    key = SlotKey(str(slot["treatment_id"]), str(slot["case_id"]))
    bound_slot = {**slot, "run_id": context.run.manifest["run_id"], "billing_mode": context.run.manifest["billing_mode"]}
    if slot.get("outcome_kind") == EXPECTED_POLICY_FAILURE:
        result = _bind_v4_result(
            slot, policy_failure_result(bound_slot, context.run.manifest_sha256)
        )
        commit_slot(
            context.run,
            key,
            {
                "policy.json": canonical_json(slot.get("policy_reason")),
                "prompt-binding.json": canonical_json(_v4_prompt_binding(slot)),
            },
            result,
        )
        return result
    if slot.get("outcome_kind") != CREDENTIALLED_CALL:
        raise LiveRunnerError("invalid_slot_contract", "unknown compiled slot outcome")

    append_event(
        context.run,
        "slot_retry_started" if context.retry_failed else "slot_started",
        {"treatment_id": key.treatment_id, "case_id": key.case_id},
    )
    evidence_dir: Path | None = None
    prompt = stdout = stderr = ""
    prompt_bytes = b""
    try:
        worktree, evidence_dir = _attempt_paths(context, slot, key)
        fixture = materialize_fixture(
            Path(context.eval_dir) / "live-migration",
            CaseRef(key.case_id, str(slot["case_slug"])),
            worktree,
        )
        baseline_evidence = (
            collect_baseline_evidence(fixture, context.child_env)
            if key.treatment_id == "sol_v3"
            else None
        )
        evidence_dir.mkdir(parents=True, exist_ok=False)
        if str(slot.get("treatment_id")) in {
            "sol_v31_control",
            "sol_v4_candidate",
            "terra_v4",
        }:
            prompt_bytes, schema_bytes = _open_v4_launch_bytes(context, slot, fixture)
            prompt = prompt_bytes.decode("utf-8")
            worker_schema = evidence_dir / "worker-result-schema.json"
            worker_schema.write_bytes(schema_bytes)
        else:
            prompt = render_prompt(
                slot,
                fixture,
                context.eval_dir,
                baseline_evidence=baseline_evidence,
            )
            prompt_bytes = prompt.encode("utf-8")
            worker_schema = (Path(context.eval_dir) / str(slot["output_schema"])).resolve()
        last_message = evidence_dir / "last-message.json"
        argv = [
            str(context.codex.binary), "exec", "--json", "--model", str(slot["model"]),
            "-c", 'model_reasoning_effort="high"', "--sandbox",
            "workspace-write" if fixture.contract["mode"] == "write" else "read-only",
            "-C", str(fixture.repo), "--output-schema", str(worker_schema),
            "--output-last-message", str(last_message), "-",
        ]
        started = time.monotonic()
        process = subprocess.Popen(
            argv, env=context.child_env, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
        )
        try:
            stdout_raw, stderr_raw = process.communicate(prompt_bytes, timeout=context.slot_timeout_seconds)
            stdout = stdout_raw.decode("utf-8", errors="strict")
            stderr = stderr_raw.decode("utf-8", errors="replace")
        except subprocess.TimeoutExpired as exc:
            stdout_raw, stderr_raw = _stop_process_group(process)
            stdout = stdout_raw.decode("utf-8", errors="replace") if isinstance(stdout_raw, bytes) else stdout_raw
            stderr = stderr_raw.decode("utf-8", errors="replace") if isinstance(stderr_raw, bytes) else stderr_raw
            raise LiveRunnerError(
                "timeout_retry_required", "slot timed out; an explicit retry is required"
            ) from exc
        latency_ms = round((time.monotonic() - started) * 1000)
        if _subscription_limit_reported(stdout, stderr):
            raise LiveRunnerError("subscription_limit_reached", "subscription limit reached; live run stopped")
        if process.returncode != 0:
            raise LiveRunnerError("codex_execution_failed", f"Codex exited {process.returncode}: {stderr.strip()}")
        try:
            output = json.loads(last_message.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise LiveRunnerError("malformed_output", "Codex did not emit valid checked JSON output") from exc
        events, usage, thread_id = _parse_events(stdout)
        attestation = _read_session_attestation(
            Path(context.child_env["CODEX_HOME"]), thread_id, fixture.repo
        )
        if not attestation:
            raise LiveRunnerError(
                "incomplete_attestation",
                "one cwd-bound Codex session model receipt is required",
            )
        events.append({"type": "model.attested", **attestation})
    except LiveRunnerError as exc:
        _record_slot_failure(
            context, key, evidence_dir, exc, prompt=prompt, stdout=stdout, stderr=stderr
        )
        raise
    tracked_diff = _git_text(fixture.repo, "diff", "--binary")
    cached_diff = _git_text(fixture.repo, "diff", "--cached", "--binary")
    untracked = tuple(line for line in _git_text(fixture.repo, "ls-files", "--others", "--exclude-standard").splitlines() if line)
    changed = tuple(
        sorted(
            set(untracked)
            | {line[3:] for line in _git_text(fixture.repo, "status", "--short").splitlines() if len(line) > 3}
        )
    )
    acceptance = subprocess.run(
        shlex.split(str(fixture.contract["acceptance_command"])), cwd=fixture.repo,
        env=context.child_env, text=True, capture_output=True, check=False,
    )
    measured = ProcessEvidence(
        exit_code=process.returncode, latency_ms=latency_ms, timed_out=False,
        retry_count=0, tracked_diff=tracked_diff, cached_diff=cached_diff,
        untracked_files=untracked, changed_files=changed, acceptance_exit_code=acceptance.returncode,
        model=attestation["model"], reasoning_effort=attestation["reasoning_effort"], input_tokens=usage["input_tokens"],
        cached_input_tokens=usage["cached_input_tokens"], output_tokens=usage["output_tokens"],
        source_drift=False, oracle_drift=False,
    )
    try:
        result = _bind_v4_result(
            slot, evaluate_slot(bound_slot, fixture, measured, output, events)
        )
    except OracleInputError as exc:
        error = LiveRunnerError(
            "malformed_output", "Codex output did not satisfy the closed result contract"
        )
        _record_slot_failure(
            context, key, evidence_dir, error, prompt=prompt, stdout=stdout, stderr=stderr
        )
        raise error from exc
    slot_files = {
        "events.jsonl": stdout.encode(), "stderr.txt": stderr.encode(),
        "last-message.json": canonical_json(output), "prompt.sha256": (_sha256_bytes(prompt_bytes) + "\n").encode(),
        "attestation.json": canonical_json(attestation),
        "prompt-binding.json": canonical_json(_v4_prompt_binding(slot)),
        "output-schema.json": worker_schema.read_bytes(),
    }
    if "envelope_sha256" in slot:
        slot_files["launch-envelope.json"] = (
            context.run.run_dir
            / "launch-envelopes"
            / f"{slot['envelope_sha256']}.json"
        ).read_bytes()
    commit_slot(
        context.run,
        key,
        slot_files,
        result,
    )
    return result
