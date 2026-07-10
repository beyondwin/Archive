from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .model_policy import attest_launcher, launcher_argv, route_for


class WorkerError(RuntimeError):
    pass


@dataclass(frozen=True)
class WorkerRequest:
    attempt_id: str
    attempt_kind: str
    prompt: str
    worktree: Path
    read_only: bool
    verdict_capable: bool
    task_id: str = ""
    packet_path: str = ""
    packet_sha256: str = ""
    worktree_revision: int = 0


@dataclass(frozen=True)
class WorkerResult:
    status: str
    payload: dict[str, object]
    attestation: dict[str, object]
    usage: dict[str, int]
    latency_ms: int
    raw_event_digest: str
    diagnostics: str = ""


REQUIRED_RESULT_FIELDS = {
    "status", "summary", "changed_files", "findings", "evidence_refs",
    "missing_evidence", "verification", "verdict",
}
ALLOWED_RESULT_FIELDS = REQUIRED_RESULT_FIELDS | {"root_cause_key", "failure_category"}
DOCUMENTED_EVENT_TYPES = {
    "thread.started", "turn.started", "item.started", "item.updated",
    "item.completed", "turn.completed", "turn.failed", "error",
}
USAGE_FIELDS = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens")


def _bounded(value: str, limit: int = 4000) -> str:
    text = value.replace(str(Path.home()), "~")
    return text[-limit:]


def _validate_result(payload: object, *, role: str, revision: int) -> dict[str, object]:
    from .attempt_controller import ROLE_POLICIES, canonical_role, validate_verdict

    if not isinstance(payload, dict):
        raise WorkerError("worker result must be an object")
    missing = REQUIRED_RESULT_FIELDS - payload.keys()
    extra = payload.keys() - ALLOWED_RESULT_FIELDS
    if missing or extra:
        raise WorkerError(f"worker result schema mismatch: missing={sorted(missing)} extra={sorted(extra)}")
    if payload.get("status") not in {"completed", "blocked", "failed"}:
        raise WorkerError("worker result has invalid status")
    if not isinstance(payload.get("summary"), str) or len(str(payload["summary"])) > 2000:
        raise WorkerError("worker summary is invalid")
    for key in ("changed_files", "findings", "evidence_refs", "missing_evidence", "verification"):
        if not isinstance(payload.get(key), list):
            raise WorkerError(f"worker result {key} must be a list")
    normalized_role = canonical_role(role)
    policy = ROLE_POLICIES[normalized_role]
    if normalized_role == "scout" and (payload["changed_files"] or payload["verification"]):
        raise WorkerError("scout output attempted write or verdict evidence")
    verdict = payload.get("verdict")
    if policy.verdict_capable:
        normalized_verdict = validate_verdict(verdict, normalized_role, revision)
        if payload["findings"] != normalized_verdict["findings"]:
            raise WorkerError("worker result findings do not match verdict")
        if payload["missing_evidence"] != normalized_verdict["missing_evidence"]:
            raise WorkerError("worker result missing_evidence does not match verdict")
        payload["verdict"] = normalized_verdict
    elif verdict is not None:
        raise WorkerError(f"role {normalized_role} cannot issue a verdict")
    return payload


def _normalize_usage(value: object) -> dict[str, int]:
    source = value if isinstance(value, dict) else {}
    return {key: max(0, int(source.get(key, 0) or 0)) for key in USAGE_FIELDS}


class Worker:
    def __init__(
        self,
        provider: Callable[[WorkerRequest, list[str]], dict[str, object]] | None = None,
        *,
        timeout_seconds: int = 900,
        max_transient_retries: int = 2,
        schema_path: Path | None = None,
    ):
        self.provider = provider
        self.timeout_seconds = timeout_seconds
        self.max_transient_retries = max_transient_retries
        self.schema_path = schema_path or Path(__file__).resolve().parents[2] / "templates" / "worker-result-schema.json"

    def _provider_once(self, request: WorkerRequest, argv: list[str]) -> tuple[dict, dict, dict, str]:
        response = self.provider(request, argv)  # type: ignore[misc]
        if not isinstance(response, dict):
            raise WorkerError("provider adapter returned a non-object")
        if isinstance(response.get("result"), dict):
            payload = dict(response["result"])
            metadata = response.get("provider_metadata") if isinstance(response.get("provider_metadata"), dict) else {}
            usage = response.get("usage")
            raw = json.dumps(response.get("events", []), ensure_ascii=False, sort_keys=True)
        else:
            payload = dict(response)
            metadata = payload.pop("_provider_metadata", {})
            usage = payload.pop("usage", {})
            raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return payload, dict(metadata), _normalize_usage(usage), raw

    def _subprocess_once(
        self,
        request: WorkerRequest,
        route,
        sandbox: str,
        last_message: Path,
    ) -> tuple[dict, dict, dict, str, str]:
        argv = launcher_argv(
            route,
            request.worktree,
            sandbox=sandbox,
            output_schema=self.schema_path,
            output_last_message=last_message,
        )
        process = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        try:
            stdout, stderr = process.communicate(request.prompt, timeout=self.timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            raise WorkerError("worker_timeout") from exc
        except BaseException:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
            raise
        diagnostics = _bounded(stderr)
        if process.returncode != 0:
            raise WorkerError(f"worker_exit_{process.returncode}: {diagnostics}")
        events: list[dict] = []
        metadata: dict[str, object] = {}
        usage: dict[str, int] = _normalize_usage({})
        for line in stdout.splitlines():
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise WorkerError("invalid codex JSONL") from exc
            if not isinstance(event, dict) or event.get("type") not in DOCUMENTED_EVENT_TYPES:
                continue
            events.append(event)
            if event.get("type") == "thread.started":
                model = event.get("model") or (event.get("thread") or {}).get("model")
                reasoning = event.get("reasoning_effort") or (event.get("thread") or {}).get("reasoning_effort")
                if model and reasoning:
                    metadata = {"model": model, "reasoning": reasoning, "trusted_source": "codex_cli_jsonl"}
            if event.get("type") == "turn.completed":
                usage = _normalize_usage(event.get("usage") or (event.get("turn") or {}).get("usage"))
        if not last_message.is_file():
            raise WorkerError("worker last-message artifact missing")
        try:
            payload = json.loads(last_message.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise WorkerError("worker last-message is not result JSON") from exc
        return payload, metadata, usage, json.dumps(events, ensure_ascii=False, sort_keys=True), diagnostics

    def run(self, request: WorkerRequest) -> WorkerResult:
        from .attempt_controller import validate_role_request

        policy = validate_role_request(request.attempt_kind, request)
        route = route_for(
            request.attempt_kind,
            read_only=policy.read_only,
            verdict_capable=policy.verdict_capable,
        )
        sandbox = "read-only" if policy.read_only else "workspace-write"
        started = time.monotonic()
        last_error: WorkerError | None = None
        for attempt in range(self.max_transient_retries + 1):
            with tempfile.TemporaryDirectory(prefix="cpe-worker-") as raw:
                last_message = Path(raw) / "last-message.json"
                argv = launcher_argv(
                    route,
                    request.worktree,
                    sandbox=sandbox,
                    output_schema=self.schema_path,
                    output_last_message=last_message,
                )
                try:
                    diagnostics = ""
                    if self.provider is not None:
                        payload, metadata, usage, raw_events = self._provider_once(request, argv)
                    else:
                        payload, metadata, usage, raw_events, diagnostics = self._subprocess_once(
                            request, route, sandbox, last_message
                        )
                    payload = _validate_result(
                        payload,
                        role=request.attempt_kind,
                        revision=request.worktree_revision,
                    )
                    attestation = attest_launcher(
                        route,
                        argv,
                        provider_model=str(metadata["model"]) if metadata.get("model") else None,
                        provider_reasoning=str(metadata["reasoning"]) if metadata.get("reasoning") else None,
                        trusted_source=str(metadata["trusted_source"]) if metadata.get("trusted_source") else None,
                    )
                    return WorkerResult(
                        str(payload["status"]),
                        payload,
                        attestation,
                        usage,
                        int((time.monotonic() - started) * 1000),
                        hashlib.sha256(raw_events.encode()).hexdigest(),
                        diagnostics,
                    )
                except WorkerError as exc:
                    last_error = exc
                    transient = str(exc).startswith(("worker_timeout", "worker_exit_75", "worker_exit_111"))
                    if not transient or attempt >= self.max_transient_retries:
                        raise
        raise last_error or WorkerError("worker failed")
