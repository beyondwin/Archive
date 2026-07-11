"""Fail-closed ChatGPT subscription runner for the paid live migration matrix."""

from __future__ import annotations

import hashlib
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
from typing import Any, Mapping

from .contracts import (
    CREDENTIALLED_CALL,
    EXPECTED_POLICY_FAILURE,
    CaseRef,
    SlotKey,
    canonical_json,
)
from .fixtures import MaterializedFixture, materialize_fixture
from .ledger import LiveRun, append_event, commit_slot
from .oracle import OracleInputError, ProcessEvidence, evaluate_slot, policy_failure_result


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


def preflight_codex(codex_bin: Path, env: Mapping[str, str]) -> CodexAttestation:
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
    required = {"gpt-5.5", "gpt-5.6-sol", "gpt-5.6-terra"}
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


def render_prompt(slot: dict[str, object], fixture: MaterializedFixture, eval_dir: Path) -> str:
    """Render a digest-bound treatment prefix plus common model-visible contract."""

    if not isinstance(slot, dict) or not isinstance(fixture, MaterializedFixture):
        raise LiveRunnerError("invalid_slot_contract", "compiled slot and materialized fixture are required")
    renderer = str(slot.get("prompt_renderer") or "")
    if renderer == "terra-scout-generated":
        prefix_bytes = b"bounded read-only scout prompt renderer v1\n"
    else:
        try:
            prefix_bytes = (Path(eval_dir) / "live-migration" / renderer).resolve().read_bytes()
        except OSError as exc:
            raise LiveRunnerError("prompt_template_unavailable", f"cannot read prompt template: {renderer}") from exc
    if _sha256_bytes(prefix_bytes) != slot.get("prompt_sha256"):
        raise LiveRunnerError("prompt_template_drift", f"prompt digest mismatch for {slot.get('treatment_id')}")
    contract = fixture.contract
    stable_contract = (
        "\n--- case contract ---\n"
        f"task: {contract['task']}\n"
        f"allowed_paths: {json.dumps(contract['allowed_paths'], sort_keys=True)}\n"
        f"forbidden_paths: {json.dumps(contract['forbidden_paths'], sort_keys=True)}\n"
        f"acceptance_command: {contract['acceptance_command']}\n"
        f"output_contract: {slot.get('output_schema', 'live-migration/worker-result-schema.json')}\n"
    )
    hot_tail = (
        "\n--- dynamic slot context ---\n"
        f"repository_path: {fixture.repo}\n"
        f"case_id: {slot.get('case_id')}\n"
        f"treatment_id: {slot.get('treatment_id')}\n"
    )
    prompt = prefix_bytes.decode("utf-8") + stable_contract + hot_tail
    if str(fixture.oracle_dir) in prompt or "expected.json" in prompt:
        raise LiveRunnerError("oracle_prompt_leak", "hidden oracle material entered the model prompt")
    return prompt


def _git_text(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=True)
    return result.stdout


def _parse_events(stdout: str) -> tuple[list[dict[str, object]], dict[str, int], str | None, str | None]:
    events: list[dict[str, object]] = []
    usage = {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0}
    model = reasoning = None
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise LiveRunnerError("malformed_event_stream", "Codex emitted malformed JSONL") from exc
        if not isinstance(event, dict):
            raise LiveRunnerError("malformed_event_stream", "Codex emitted a non-object event")
        events.append(event)
        if event.get("type") == "thread.started":
            model = str(event.get("model"))
            reasoning = str(event.get("reasoning_effort"))
        if event.get("type") == "turn.completed" and isinstance(event.get("usage"), dict):
            for name in usage:
                usage[name] += int(event["usage"].get(name, 0))
    return events, usage, model, reasoning


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
        result = policy_failure_result(bound_slot, context.run.manifest_sha256)
        commit_slot(context.run, key, {"policy.json": canonical_json(slot.get("policy_reason"))}, result)
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
    try:
        worktree, evidence_dir = _attempt_paths(context, slot, key)
        fixture = materialize_fixture(
            Path(context.eval_dir) / "live-migration",
            CaseRef(key.case_id, str(slot["case_slug"])),
            worktree,
        )
        prompt = render_prompt(slot, fixture, context.eval_dir)
        worker_schema = (Path(context.eval_dir) / str(slot["output_schema"])).resolve()
        evidence_dir.mkdir(parents=True, exist_ok=False)
        last_message = evidence_dir / "last-message.json"
        argv = [
            str(context.codex.binary), "exec", "--json", "--ephemeral", "--model", str(slot["model"]),
            "-c", 'model_reasoning_effort="high"', "--sandbox",
            "workspace-write" if fixture.contract["mode"] == "write" else "read-only",
            "-C", str(fixture.repo), "--output-schema", str(worker_schema),
            "--output-last-message", str(last_message), "-",
        ]
        started = time.monotonic()
        process = subprocess.Popen(
            argv, env=context.child_env, text=True, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
        )
        try:
            stdout, stderr = process.communicate(prompt, timeout=context.slot_timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            stdout, stderr = _stop_process_group(process)
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
        events, usage, model, reasoning = _parse_events(stdout)
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
        model=model, reasoning_effort=reasoning, input_tokens=usage["input_tokens"],
        cached_input_tokens=usage["cached_input_tokens"], output_tokens=usage["output_tokens"],
        source_drift=False, oracle_drift=False,
    )
    try:
        result = evaluate_slot(bound_slot, fixture, measured, output, events)
    except OracleInputError as exc:
        error = LiveRunnerError(
            "malformed_output", "Codex output did not satisfy the closed result contract"
        )
        _record_slot_failure(
            context, key, evidence_dir, error, prompt=prompt, stdout=stdout, stderr=stderr
        )
        raise error from exc
    commit_slot(
        context.run,
        key,
        {
            "events.jsonl": stdout.encode(), "stderr.txt": stderr.encode(),
            "last-message.json": canonical_json(output), "prompt.sha256": (_sha256_bytes(prompt.encode()) + "\n").encode(),
        },
        result,
    )
    return result
