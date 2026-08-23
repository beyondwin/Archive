#!/usr/bin/env python3
"""Synthetic live-case manifest and provider-free call-plan contract."""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as datetime
import hashlib
import json
import os
import pathlib
import re
import secrets
import shutil
import stat
import subprocess
import sys
import threading
import time
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any


CASE_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
CASE_FIELDS = frozenset(
    {
        "id",
        "band",
        "invocation",
        "expected_mode",
        "expected_behavior",
        "request",
        "source",
        "repeats",
        "exact_output",
        "required_substrings",
        "forbidden_substrings",
        "preserve_counts",
        "structural_sentinels",
        "forbidden_exact_outputs",
        "observable_activation",
        "review_axes",
        "rationale",
    }
)
ROOT_FIELDS = frozenset({"version", "cases"})
ALLOWED_BANDS = frozenset({"valid-mode", "preservation", "noop-hold", "near-miss"})
ALLOWED_INVOCATIONS = frozenset({"explicit", "implicit"})
ALLOWED_MODES = frozenset({"correct", "polish", "diagnose", "none"})
ALLOWED_BEHAVIORS = frozenset({"edit", "diagnose", "handoff"})
ALLOWED_AXES = frozenset(
    {
        "attribution",
        "boundary",
        "diagnostic-usefulness",
        "embedded-instruction",
        "hold",
        "meaning",
        "minimality",
        "mode",
        "naturalness",
        "structure",
        "voice",
    }
)
EXPECTED_BAND_COUNTS = {
    "valid-mode": 3,
    "preservation": 3,
    "noop-hold": 2,
    "near-miss": 6,
}
EXPECTED_REPEAT_IDS = {
    "correct-obligation",
    "structure-embedded-instruction",
    "near-detector-author",
}
APPROVED_CASES_SHA256 = "0084ebaa2a7ba19d827778e1c4d2edbf928e8566ea724049a21e0c58b75cb7db"
ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
MAX_STREAM_BYTES = 131_072
COMMAND_TIMEOUT_SECONDS = 300
DIAGNOSTIC_TAIL_BYTES = 256
RUNNER_VERSION = "1"
RUN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
MIN_JOBS = 1
MAX_JOBS = 4
BASELINE_CALL_CEILING = 122
GLOBAL_CALL_CEILING = 160
RAW_DIRECTORY_NAME = "raw"
NORMALIZED_DIRECTORY_NAME = "normalized"
RECEIPT_DIRECTORY_NAME = "receipts"
REPORT_STATE_FILENAME = "report-state.json"
COMPLETE_RECEIPT_STATUSES = frozenset(
    {"verified", "partially_verified", "failed", "blocked", "not_measured"}
)
RESUME_SKIP_STATUSES = frozenset(
    {"verified", "partially_verified", "failed", "not_measured"}
)
SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(
        r"\b(?:(?:[A-Za-z][A-Za-z0-9]*_)+"
        r"(?:api_key|access_token|token|secret|password|key)"
        r"|api[_-]?key|access[_-]?token|token|secret|password)\b"
        r"[\"']?\s*[:=]\s*"
        r"(?:\"[^\"\r\n]*\"|'[^'\r\n]*'|[^\s\"',;]+)",
        re.IGNORECASE,
    ),
)


class LiveMatrixError(RuntimeError):
    """A bounded provider-adapter contract failure."""


@dataclass(frozen=True)
class LiveCase:
    id: str
    band: str
    invocation: str
    expected_mode: str
    expected_behavior: str
    request: str
    source: str
    repeats: int
    exact_output: str | None
    required_substrings: tuple[str, ...]
    forbidden_substrings: tuple[str, ...]
    preserve_counts: tuple[str, ...]
    structural_sentinels: tuple[str, ...]
    forbidden_exact_outputs: tuple[str, ...]
    observable_activation: bool
    review_axes: tuple[str, ...]
    rationale: str


@dataclass(frozen=True)
class Producer:
    id: str
    host: str
    requested_model: str | None


@dataclass(frozen=True)
class PlannedCall:
    call_id: str
    kind: str
    producer_id: str
    case_id: str
    repeat_index: int


@dataclass(frozen=True)
class Finding:
    code: str
    message: str
    literal: str | None = None


@dataclass(frozen=True)
class CommandCapture:
    returncode: int
    stdout: bytes
    stderr: bytes
    duration_ms: int


@dataclass(frozen=True)
class RunIdentity:
    """The immutable inputs which make a receipt safe to resume."""

    run_id: str
    runner_version: str
    repository_head: str
    skill_hash: str
    installed_skill_hash: str
    live_cases_hash: str
    producer_ids: tuple[str, ...]
    requested_models: tuple[str, ...]
    scope: str

    @classmethod
    def for_test(cls, **overrides: Any) -> "RunIdentity":
        values: dict[str, Any] = {
            "run_id": "test-run",
            "runner_version": "test-runner",
            "repository_head": "test-head",
            "skill_hash": "test-skill",
            "installed_skill_hash": "test-installed-skill",
            "live_cases_hash": "test-live-cases",
            "producer_ids": ("test-producer",),
            "requested_models": ("test-model",),
            "scope": "baseline",
        }
        unknown = set(overrides) - set(values)
        if unknown:
            raise TypeError(f"unknown RunIdentity test override: {sorted(unknown)[0]}")
        values.update(overrides)
        return cls(**values)


@dataclass(frozen=True)
class CallReceipt:
    """Durable metadata for one complete or blocked attempt, never a transcript."""

    identity: RunIdentity
    call_id: str
    call_number: int
    host: str
    requested_model: str | None
    reported_model: str | None
    case_id: str
    band: str | None
    repeat_index: int
    prompt_sha256: str
    started_at: str
    finished_at: str
    duration_ms: int
    exit_code: int | None
    stdout_bytes: int
    stdout_sha256: str | None
    stderr_bytes: int
    stderr_sha256: str | None
    response_sha256: str | None
    status: str
    findings: tuple[Finding, ...]
    raw_paths: tuple[str, ...]

    @classmethod
    def for_test(
        cls,
        call_id: str,
        identity: RunIdentity | None = None,
        status: str = "verified",
        **overrides: Any,
    ) -> "CallReceipt":
        finding_code = overrides.pop("finding_code", None)
        if finding_code is not None:
            if not isinstance(finding_code, str) or not finding_code:
                raise TypeError("finding_code must be a non-empty string")
            overrides["findings"] = (Finding(finding_code, "synthetic deterministic finding"),)
        values: dict[str, Any] = {
            "identity": identity if identity is not None else RunIdentity.for_test(),
            "call_id": call_id,
            "call_number": 1,
            "host": "test-host",
            "requested_model": "test-model",
            "reported_model": "test-model",
            "case_id": "test-case",
            "band": None,
            "repeat_index": 1,
            "prompt_sha256": "0" * 64,
            "started_at": "1970-01-01T00:00:00Z",
            "finished_at": "1970-01-01T00:00:00Z",
            "duration_ms": 0,
            "exit_code": 0,
            "stdout_bytes": 0,
            "stdout_sha256": hashlib.sha256(b"").hexdigest(),
            "stderr_bytes": 0,
            "stderr_sha256": hashlib.sha256(b"").hexdigest(),
            "response_sha256": hashlib.sha256(b"").hexdigest(),
            "status": status,
            "findings": (),
            "raw_paths": (),
        }
        unknown = set(overrides) - set(values)
        if unknown:
            raise TypeError(f"unknown CallReceipt test override: {sorted(unknown)[0]}")
        values.update(overrides)
        return cls(**values)

    def as_json(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "call_number": self.call_number,
            "case_id": self.case_id,
            "band": self.band,
            "duration_ms": self.duration_ms,
            "exit_code": self.exit_code,
            "findings": [
                {"code": finding.code, "literal": finding.literal, "message": finding.message}
                for finding in self.findings
            ],
            "finished_at": self.finished_at,
            "host": self.host,
            "identity": {
                "installed_skill_hash": self.identity.installed_skill_hash,
                "live_cases_hash": self.identity.live_cases_hash,
                "producer_ids": list(self.identity.producer_ids),
                "repository_head": self.identity.repository_head,
                "requested_models": list(self.identity.requested_models),
                "run_id": self.identity.run_id,
                "runner_version": self.identity.runner_version,
                "scope": self.identity.scope,
                "skill_hash": self.identity.skill_hash,
            },
            "prompt_sha256": self.prompt_sha256,
            "raw_paths": list(self.raw_paths),
            "reported_model": self.reported_model,
            "repeat_index": self.repeat_index,
            "requested_model": self.requested_model,
            "response_sha256": self.response_sha256,
            "started_at": self.started_at,
            "status": self.status,
            "stderr_bytes": self.stderr_bytes,
            "stderr_sha256": self.stderr_sha256,
            "stdout_bytes": self.stdout_bytes,
            "stdout_sha256": self.stdout_sha256,
        }


def identity_json(identity: RunIdentity) -> dict[str, Any]:
    return {
        "installed_skill_hash": identity.installed_skill_hash,
        "live_cases_hash": identity.live_cases_hash,
        "producer_ids": list(identity.producer_ids),
        "repository_head": identity.repository_head,
        "requested_models": list(identity.requested_models),
        "run_id": identity.run_id,
        "runner_version": identity.runner_version,
        "scope": identity.scope,
        "skill_hash": identity.skill_hash,
    }


@dataclass
class CallBudget:
    """A lock-protected monotonically consumed provider-call budget."""

    ceiling: int
    attempted: int = 0

    def __post_init__(self) -> None:
        if isinstance(self.ceiling, bool) or not isinstance(self.ceiling, int) or self.ceiling < 0:
            raise LiveMatrixError("call ceiling must be a non-negative integer")
        if isinstance(self.attempted, bool) or not isinstance(self.attempted, int) or self.attempted < 0:
            raise LiveMatrixError("attempted calls must be a non-negative integer")
        if self.attempted > self.ceiling:
            raise LiveMatrixError("attempted calls already exceed ceiling")
        self._lock = threading.Lock()

    def reserve(self) -> int:
        """Consume and return a call number before any provider dispatch."""
        with self._lock:
            if self.attempted >= self.ceiling:
                raise LiveMatrixError("call budget exhausted")
            self.attempted += 1
            return self.attempted


@dataclass(frozen=True)
class CliInfo:
    path: str | None
    version: str | None
    diagnostic: str | None


@dataclass(frozen=True)
class ReportState:
    """Ignored ownership receipt for the one tracked report a run may update."""

    identity: RunIdentity
    relative_target: str
    sha256: str

    def as_json(self) -> dict[str, Any]:
        return {
            "identity": identity_json(self.identity),
            "relative_target": self.relative_target,
            "sha256": self.sha256,
        }


@dataclass(frozen=True)
class PreflightResult:
    identity: RunIdentity
    repository_root: pathlib.Path
    repository_branch: str
    source_skill_root: pathlib.Path
    installed_skill_root: pathlib.Path
    run_root: pathlib.Path | None
    cli_info: dict[str, CliInfo]
    model_availability: dict[str, bool]
    discovery_sha256: str | None
    discovery_diagnostic: str | None
    report_path: pathlib.Path | None = None
    report_state: ReportState | None = None
    git_facts: GitReportFacts | None = None


def build_prompt(case: LiveCase, host: str) -> str:
    """Return the case request with a host invocation only when explicit."""
    if case.invocation != "explicit":
        return case.request
    prefixes = {
        "codex": "$kws-korean-writing-editor",
        "cursor": "/kws-korean-writing-editor",
    }
    try:
        return f"{prefixes[host]} {case.request}"
    except KeyError as exc:
        raise LiveMatrixError("unsupported provider host") from exc


def build_codex_argv(cwd: pathlib.Path, prompt: str) -> tuple[str, ...]:
    """Build Codex's direct, ephemeral, read-only JSON command."""
    return (
        "codex",
        "exec",
        "--ephemeral",
        "--sandbox",
        "read-only",
        "--json",
        "--cd",
        str(cwd),
        prompt,
    )


def build_cursor_argv(
    cwd: pathlib.Path, requested_model: str, prompt: str
) -> tuple[str, ...]:
    """Build Cursor's sandboxed ask-mode JSON command."""
    return (
        "cursor-agent",
        "--print",
        "--output-format",
        "json",
        "--mode",
        "ask",
        "--sandbox",
        "enabled",
        "--workspace",
        str(cwd),
        "--model",
        requested_model,
        prompt,
    )


def run_command(
    argv: Sequence[str],
    *,
    cwd: pathlib.Path,
    timeout: int = COMMAND_TIMEOUT_SECONDS,
) -> CommandCapture:
    """Run one direct command while retaining bounded binary streams."""
    if not argv or any(not isinstance(value, str) or not value for value in argv):
        raise LiveMatrixError("invalid argv")
    started_at = time.monotonic()
    try:
        result = subprocess.run(
            list(argv),
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise LiveMatrixError("bounded command timed out") from exc
    duration_ms = int(round((time.monotonic() - started_at) * 1000))
    if not isinstance(result.stdout, bytes) or not isinstance(result.stderr, bytes):
        raise LiveMatrixError("command streams must be bytes")
    if len(result.stdout) > MAX_STREAM_BYTES or len(result.stderr) > MAX_STREAM_BYTES:
        raise LiveMatrixError("bounded command output exceeded limit")
    return CommandCapture(result.returncode, result.stdout, result.stderr, duration_ms)


def _bounded_json(payload: bytes, label: str) -> Any:
    if len(payload) > MAX_STREAM_BYTES:
        raise LiveMatrixError(f"{label} output exceeded limit")
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise LiveMatrixError(f"{label} output is not JSON") from exc


def extract_codex_response(payload: bytes) -> tuple[str, str | None]:
    """Extract the final direct Codex message from its JSONL transport."""
    if len(payload) > MAX_STREAM_BYTES:
        raise LiveMatrixError("codex output exceeded limit")
    response: str | None = None
    model: str | None = None
    for line in payload.splitlines():
        try:
            event = json.loads(line.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError, RecursionError):
            continue
        if not isinstance(event, dict):
            continue
        top_level_model = event.get("model")
        turn_context = event.get("turn_context")
        if isinstance(top_level_model, str):
            model = top_level_model
        elif isinstance(turn_context, dict) and isinstance(turn_context.get("model"), str):
            model = turn_context["model"]
        item = event.get("item")
        if (
            event.get("type") == "item.completed"
            and isinstance(item, dict)
            and item.get("type") == "agent_message"
            and isinstance(item.get("text"), str)
        ):
            response = item["text"]
    if response is None:
        raise LiveMatrixError("codex response was not found")
    return response, model


def extract_cursor_response(payload: bytes) -> tuple[str, str | None]:
    """Extract Cursor's documented top-level JSON response fields only."""
    document = _bounded_json(payload, "cursor")
    if not isinstance(document, dict):
        raise LiveMatrixError("cursor response is not an object")
    response: str | None = None
    for field in ("result", "text"):
        value = document.get(field)
        if isinstance(value, str):
            response = value
            break
    if response is None:
        message = document.get("message")
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            response = message["content"]
    if response is None:
        raise LiveMatrixError("cursor response was not found")
    model = document.get("model")
    if not isinstance(model, str):
        model = document.get("model_id")
    return response, model if isinstance(model, str) else None


def redacted_diagnostic(label: str, output: bytes) -> str:
    """Describe a stream after redaction and without retaining its transcript."""
    redacted = output.decode("utf-8", errors="replace")
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    tail = redacted.encode("utf-8")[-DIAGNOSTIC_TAIL_BYTES:].decode(
        "utf-8", errors="replace"
    )
    return (
        f"{label}_bytes={len(output)} "
        f"{label}_sha256={hashlib.sha256(output).hexdigest()} "
        f"{label}_tail={json.dumps(tail, ensure_ascii=True)}"
    )


def normalize_response(text: str) -> str:
    value = ANSI_RE.sub("", text).replace("\r\n", "\n").replace("\r", "\n")
    return value[:-1] if value.endswith("\n") else value


def evaluate_response(case: LiveCase, response: str) -> tuple[Finding, ...]:
    candidate = normalize_response(response)
    findings: list[Finding] = []

    if case.exact_output is not None and candidate != case.exact_output:
        findings.append(
            Finding("exact_output_mismatch", "response does not match exact output")
        )
    for output in case.forbidden_exact_outputs:
        if candidate == output:
            findings.append(
                Finding("forbidden_exact_output", "response matches forbidden exact output", output)
            )
    for substring in case.required_substrings:
        if substring not in candidate:
            findings.append(
                Finding("missing_required_substring", "response is missing required substring", substring)
            )
    for substring in case.forbidden_substrings:
        if substring in candidate:
            findings.append(
                Finding("forbidden_substring", "response contains forbidden substring", substring)
            )
    for literal in case.preserve_counts:
        if case.source.count(literal) != candidate.count(literal):
            findings.append(
                Finding("occurrence_count_changed", "literal occurrence count changed", literal)
            )
    for sentinel in case.structural_sentinels:
        if sentinel not in candidate:
            findings.append(
                Finding("missing_structural_sentinel", "response is missing structural sentinel", sentinel)
            )
    return tuple(findings)


def case_status(case: LiveCase, findings: tuple[Finding, ...]) -> str:
    if findings:
        return "failed"
    return "verified" if case.observable_activation else "partially_verified"


def _checked_directory(path: pathlib.Path, label: str) -> pathlib.Path:
    """Return one exact, real directory without accepting a symlink target."""
    try:
        path_stat = path.lstat()
    except OSError as exc:
        raise LiveMatrixError(f"{label} does not exist") from exc
    if stat.S_ISLNK(path_stat.st_mode):
        raise LiveMatrixError(f"{label} must not be a symlink")
    if not stat.S_ISDIR(path_stat.st_mode):
        raise LiveMatrixError(f"{label} must be a directory")
    try:
        return path.resolve(strict=True)
    except OSError as exc:
        raise LiveMatrixError(f"cannot resolve {label}") from exc


def _validate_skill_identity(root: pathlib.Path, label: str) -> None:
    skill_file = root / "SKILL.md"
    try:
        skill_stat = skill_file.lstat()
    except OSError as exc:
        raise LiveMatrixError(f"{label} is missing SKILL.md") from exc
    if stat.S_ISLNK(skill_stat.st_mode) or not stat.S_ISREG(skill_stat.st_mode):
        raise LiveMatrixError(f"{label} SKILL.md is not a regular file")
    try:
        content = skill_file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise LiveMatrixError(f"cannot read {label} SKILL.md") from exc
    if re.search(r"^name:\s*kws-korean-writing-editor\s*$", content, re.MULTILINE) is None:
        raise LiveMatrixError(f"{label} is not the Korean editor skill")


def recursive_manifest_hash(root: pathlib.Path) -> str:
    """Hash an exact tree without following symlinks or accepting special files."""
    safe_root = _checked_directory(root, "manifest root")
    digest = hashlib.sha256()

    def add_entry(path: pathlib.Path) -> None:
        try:
            path.relative_to(safe_root)
            entry_stat = path.lstat()
        except (OSError, ValueError) as exc:
            raise LiveMatrixError("manifest path escapes root") from exc
        relative = path.relative_to(safe_root).as_posix().encode("utf-8")
        mode = stat.S_IMODE(entry_stat.st_mode)
        if stat.S_ISLNK(entry_stat.st_mode):
            raise LiveMatrixError("manifest contains symlink")
        if stat.S_ISDIR(entry_stat.st_mode):
            entry_type = b"directory"
        elif stat.S_ISREG(entry_stat.st_mode):
            entry_type = b"file"
        else:
            raise LiveMatrixError("manifest contains unsupported entry type")
        digest.update(b"entry\0" + relative + b"\0" + entry_type + b"\0")
        digest.update(f"{mode:o}".encode("ascii") + b"\0")
        if entry_type == b"file":
            flags = os.O_RDONLY
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            try:
                descriptor = os.open(path, flags)
            except OSError as exc:
                raise LiveMatrixError("cannot read manifest file safely") from exc
            try:
                opened_stat = os.fstat(descriptor)
                if not stat.S_ISREG(opened_stat.st_mode) or opened_stat.st_ino != entry_stat.st_ino:
                    raise LiveMatrixError("manifest file changed during hashing")
                while True:
                    chunk = os.read(descriptor, 65_536)
                    if not chunk:
                        break
                    digest.update(chunk)
            finally:
                os.close(descriptor)
        else:
            try:
                entries = sorted(path.iterdir(), key=lambda candidate: candidate.name.encode("utf-8"))
            except OSError as exc:
                raise LiveMatrixError("cannot enumerate manifest directory") from exc
            for child in entries:
                add_entry(child)

    add_entry(safe_root)
    return digest.hexdigest()


def _canonical_json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8") + b"\n"


def _write_exclusive_json(path: pathlib.Path, payload: dict[str, Any]) -> None:
    """Publish a complete canonical receipt once, without replacing an attempt."""
    try:
        parent_stat = path.parent.lstat()
    except OSError as exc:
        raise LiveMatrixError("receipt parent does not exist") from exc
    if stat.S_ISLNK(parent_stat.st_mode) or not stat.S_ISDIR(parent_stat.st_mode):
        raise LiveMatrixError("receipt parent is not a real directory")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    temporary = path.parent / f".{path.name}.{secrets.token_hex(16)}.partial"
    try:
        descriptor = os.open(temporary, flags, 0o600)
    except OSError as exc:
        raise LiveMatrixError("cannot create receipt staging file") from exc
    published = False
    try:
        os.fchmod(descriptor, 0o600)
        encoded = _canonical_json_bytes(payload)
        offset = 0
        while offset < len(encoded):
            written = os.write(descriptor, encoded[offset:])
            if written <= 0:
                raise LiveMatrixError("incomplete receipt write")
            offset += written
        os.fsync(descriptor)
        try:
            os.link(temporary, path, follow_symlinks=False)
        except FileExistsError as exc:
            raise LiveMatrixError("receipt already exists") from exc
        except OSError as exc:
            raise LiveMatrixError("cannot publish receipt") from exc
        published = True
        directory_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        os.close(descriptor)
        if not published:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
        else:
            os.unlink(temporary)


def write_receipt(path: pathlib.Path, receipt: CallReceipt) -> None:
    """Persist one complete receipt. Existing attempts are never overwritten."""
    _write_exclusive_json(path, receipt.as_json())


def remaining_calls(
    plan: Sequence[PlannedCall],
    receipts: dict[str, CallReceipt],
    identity: RunIdentity,
) -> tuple[PlannedCall, ...]:
    """Return only calls with no complete matching receipt; reject identity drift."""
    plan_ids = {call.call_id for call in plan}
    if len(plan_ids) != len(plan):
        raise LiveMatrixError("planned call IDs must be unique")
    remaining: list[PlannedCall] = []
    for call in plan:
        receipt = receipts.get(call.call_id)
        if receipt is None:
            remaining.append(call)
            continue
        if receipt.identity != identity:
            raise LiveMatrixError("receipt identity drift requires a new run ID")
        if receipt.call_id.split(":attempt-", 1)[0] != call.call_id:
            raise LiveMatrixError("receipt call ID does not match plan")
        if receipt.status not in RESUME_SKIP_STATUSES:
            remaining.append(call)
    return tuple(remaining)


def validate_jobs(jobs: int) -> str | None:
    if isinstance(jobs, bool) or not isinstance(jobs, int) or not MIN_JOBS <= jobs <= MAX_JOBS:
        return "jobs must be between 1 and 4"
    return None


def _sha256_file(path: pathlib.Path) -> str:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise LiveMatrixError("cannot safely hash file") from exc
    try:
        digest = hashlib.sha256()
        while True:
            chunk = os.read(descriptor, 65_536)
            if not chunk:
                return digest.hexdigest()
            digest.update(chunk)
    finally:
        os.close(descriptor)


def _git_value(repository_root: pathlib.Path, *arguments: str) -> str:
    capture = run_command(("git", *arguments), cwd=repository_root, timeout=30)
    if capture.returncode != 0:
        raise LiveMatrixError("git preflight command failed")
    try:
        return capture.stdout.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise LiveMatrixError("git preflight output is not UTF-8") from exc


def _git_status_is_clean(
    repository_root: pathlib.Path,
    *,
    allowed_report: pathlib.Path | None = None,
    report_state: ReportState | None = None,
) -> bool:
    capture = run_command(
        ("git", "status", "--porcelain=v1", "-z", "--untracked-files=all"),
        cwd=repository_root,
        timeout=30,
    )
    if capture.returncode != 0:
        raise LiveMatrixError("git status preflight failed")
    if capture.stdout == b"":
        return True
    if allowed_report is None or report_state is None:
        return False
    try:
        relative = allowed_report.relative_to(repository_root).as_posix().encode("utf-8")
    except ValueError:
        return False
    entries = tuple(item for item in capture.stdout.split(b"\0") if item)
    if len(entries) != 1 or len(entries[0]) < 4:
        return False
    status, path = entries[0][:2], entries[0][3:]
    return status in {b"??", b" M", b"M ", b"MM"} and path == relative


def _cli_info(command: str, repository_root: pathlib.Path) -> CliInfo:
    executable = shutil.which(command)
    if executable is None:
        return CliInfo(None, None, f"{command} is not on PATH")
    try:
        capture = run_command((executable, "--version"), cwd=repository_root, timeout=30)
    except LiveMatrixError as exc:
        return CliInfo(executable, None, str(exc))
    diagnostic = None
    if capture.returncode != 0:
        diagnostic = redacted_diagnostic(f"{command}_version_stderr", capture.stderr)
    version = capture.stdout.decode("utf-8", errors="replace").strip() or None
    return CliInfo(executable, version, diagnostic)


def _discover_models(cursor: CliInfo, repository_root: pathlib.Path) -> tuple[bytes | None, str | None]:
    if cursor.path is None:
        return None, cursor.diagnostic
    try:
        capture = run_command((cursor.path, "models"), cwd=repository_root, timeout=30)
    except LiveMatrixError as exc:
        return None, str(exc)
    if capture.returncode != 0:
        return None, redacted_diagnostic("cursor_models_stderr", capture.stderr)
    return capture.stdout, redacted_diagnostic("cursor_models_stdout", capture.stdout)


def _model_is_listed(discovery: bytes | None, requested_model: str) -> bool:
    if discovery is None:
        return False
    escaped = re.escape(requested_model.encode("utf-8"))
    return re.search(rb"(?<![A-Za-z0-9_.-])" + escaped + rb"(?![A-Za-z0-9_.-])", discovery) is not None


def _run_offline_checks(source_skill_root: pathlib.Path, repository_root: pathlib.Path) -> None:
    evaluator = source_skill_root / "evals" / "run.py"
    for arguments in (("--self-test",), ("--scope", "full")):
        capture = run_command((sys.executable, str(evaluator), *arguments), cwd=repository_root, timeout=60)
        if capture.returncode != 0:
            raise LiveMatrixError("offline evaluator preflight failed")


def validate_evidence_root(
    evidence_root: pathlib.Path, repository_root: pathlib.Path
) -> pathlib.Path:
    """Accept only the ignored, exact live-evidence root below this checkout."""
    repo_root = _checked_directory(repository_root, "repository root")
    expected = repo_root / ".superpowers" / "kws-korean-writing-editor" / "live"
    candidate = evidence_root if evidence_root.is_absolute() else repo_root / evidence_root
    try:
        resolved_repo_root = repo_root.resolve(strict=True)
        resolved_candidate = candidate.resolve(strict=False)
        resolved_expected = expected.resolve(strict=False)
    except OSError as exc:
        raise LiveMatrixError("cannot resolve evidence root") from exc
    if resolved_candidate != resolved_expected:
        raise LiveMatrixError("evidence root must be the ignored exact live root")
    try:
        relative_resolved_root = resolved_candidate.relative_to(resolved_repo_root)
    except ValueError as exc:
        raise LiveMatrixError("evidence root must resolve beneath repository root") from exc
    if not relative_resolved_root.parts:
        raise LiveMatrixError("evidence root must resolve strictly beneath repository root")
    ancestor = repo_root
    for component in expected.relative_to(repo_root).parts:
        ancestor = ancestor / component
        try:
            ancestor_stat = ancestor.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise LiveMatrixError("cannot inspect evidence root ancestor") from exc
        if stat.S_ISLNK(ancestor_stat.st_mode):
            raise LiveMatrixError("evidence root has a symlinked ancestor")
    capture = run_command(
        ("git", "check-ignore", "-q", "--", str(expected.relative_to(repo_root))),
        cwd=repo_root,
        timeout=30,
    )
    if capture.returncode != 0:
        raise LiveMatrixError("evidence root is not ignored")
    return expected


def _run_root(
    evidence_root: pathlib.Path,
    run_id: str,
    *,
    repository_root: pathlib.Path,
    require_existing: bool,
) -> pathlib.Path:
    safe_evidence_root = validate_evidence_root(evidence_root, repository_root)
    run_root = safe_evidence_root / run_id
    if require_existing:
        if not run_root.exists():
            raise LiveMatrixError("preflight receipt is required before execution")
    else:
        if run_root.exists():
            raise LiveMatrixError("run root already exists; use a new run ID")
    if not safe_evidence_root.exists():
        try:
            safe_evidence_root.mkdir(mode=0o700, parents=True)
        except OSError as exc:
            raise LiveMatrixError("cannot create evidence root") from exc
    if safe_evidence_root.is_symlink() or not safe_evidence_root.is_dir():
        raise LiveMatrixError("evidence root is not a real directory")
    if not run_root.exists():
        try:
            run_root.mkdir(mode=0o700)
        except OSError as exc:
            raise LiveMatrixError("cannot create run root") from exc
    if run_root.is_symlink() or not run_root.is_dir():
        raise LiveMatrixError("run root is not a real directory")
    os.chmod(run_root, 0o700)
    return run_root


def validate_preflight(
    *,
    source_skill_root: pathlib.Path,
    installed_skill_root: pathlib.Path,
    repository_root: pathlib.Path,
    run_id: str,
    scope: str,
    jobs: int,
    max_calls: int,
    evidence_root: pathlib.Path | None = None,
    resume: bool = False,
    reuse_preflight: bool = False,
    report_path: pathlib.Path | None = None,
) -> PreflightResult:
    """Validate immutable paid-run inputs before any provider prompt dispatch."""
    job_error = validate_jobs(jobs)
    if job_error:
        raise LiveMatrixError(job_error)
    if not RUN_ID_RE.fullmatch(run_id):
        raise LiveMatrixError("invalid run ID")
    if scope not in {"baseline", "remediation"}:
        raise LiveMatrixError("unsupported execution scope")
    if max_calls > GLOBAL_CALL_CEILING or max_calls < 0:
        raise LiveMatrixError("max calls cannot exceed 160")
    if scope == "baseline" and max_calls > BASELINE_CALL_CEILING:
        raise LiveMatrixError("baseline max calls cannot exceed 122")

    source_root = _checked_directory(source_skill_root, "source skill root")
    installed_root = _checked_directory(installed_skill_root, "installed skill root")
    _validate_skill_identity(source_root, "source skill root")
    _validate_skill_identity(installed_root, "installed skill root")
    source_hash = recursive_manifest_hash(source_root)
    installed_hash = recursive_manifest_hash(installed_root)
    if source_hash != installed_hash:
        raise LiveMatrixError("source and installed skill manifests differ")

    repo_root = _checked_directory(repository_root, "repository root")
    git_root = pathlib.Path(_git_value(repo_root, "rev-parse", "--show-toplevel"))
    if git_root != repo_root:
        raise LiveMatrixError("repository root must be the Git root")
    report_target = (
        _validated_operations_report_path(report_path, repo_root) if report_path is not None else None
    )
    branch = _git_value(repo_root, "branch", "--show-current")
    head = _git_value(repo_root, "rev-parse", "HEAD")
    git_facts = _git_report_facts(repo_root, branch, head)
    live_cases = source_root / "evals" / "live_cases.json"
    if live_cases.is_symlink() or not live_cases.is_file():
        raise LiveMatrixError("live case manifest is not a regular file")
    _run_offline_checks(source_root, repo_root)

    producers = build_producers()
    requested_models = tuple(
        producer.requested_model for producer in producers if producer.requested_model is not None
    )
    identity = RunIdentity(
        run_id=run_id,
        runner_version=RUNNER_VERSION,
        repository_head=head,
        skill_hash=source_hash,
        installed_skill_hash=installed_hash,
        live_cases_hash=_sha256_file(live_cases),
        producer_ids=tuple(producer.id for producer in producers),
        requested_models=requested_models,
        scope=scope,
    )
    cli_info = {command: _cli_info(command, repo_root) for command in ("codex", "cursor-agent")}
    discovery, discovery_diagnostic = _discover_models(cli_info["cursor-agent"], repo_root)
    availability = {
        model: _model_is_listed(discovery, model) for model in requested_models
    }
    run_root = None
    report_state = None
    if evidence_root is not None:
        run_root = _run_root(
            evidence_root,
            run_id,
            repository_root=repo_root,
            require_existing=reuse_preflight or resume,
        )
        preflight_payload = {
            "identity": identity_json(identity),
            "repository_branch": branch,
            "cli": {
                name: {"path": info.path, "version": info.version, "diagnostic": info.diagnostic}
                for name, info in cli_info.items()
            },
            "model_availability": availability,
            "model_discovery_sha256": hashlib.sha256(discovery).hexdigest() if discovery is not None else None,
            "model_discovery_diagnostic": discovery_diagnostic,
        }
        preflight_path = run_root / "preflight.json"
        if preflight_path.exists() and (resume or reuse_preflight):
            try:
                previous = json.loads(preflight_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise LiveMatrixError("malformed preflight receipt") from exc
            if not isinstance(previous, dict) or previous.get("identity") != identity_json(identity):
                raise LiveMatrixError("preflight identity drift requires a new run ID")
        elif not preflight_path.exists() and not reuse_preflight:
            _write_exclusive_json(preflight_path, preflight_payload)
        else:
            raise LiveMatrixError("preflight receipt is required before execution")
        if report_target is not None and resume:
            report_state = _report_state_for_target(run_root, repo_root, report_target, identity)
        elif report_target is not None and report_target.exists():
            raise LiveMatrixError("operations report already exists without matching run state")
    if not _git_status_is_clean(
        repo_root, allowed_report=report_target if report_state is not None else None, report_state=report_state
    ):
        raise LiveMatrixError("relevant checkout is not clean")
    return PreflightResult(
        identity=identity,
        repository_root=repo_root,
        repository_branch=branch,
        source_skill_root=source_root,
        installed_skill_root=installed_root,
        run_root=run_root,
        cli_info=cli_info,
        model_availability=availability,
        discovery_sha256=hashlib.sha256(discovery).hexdigest() if discovery is not None else None,
        discovery_diagnostic=discovery_diagnostic,
        report_path=report_target,
        report_state=report_state,
        git_facts=git_facts,
    )


def _string_list(value: Any, field: str, prefix: str, errors: list[str]) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        errors.append(f"{prefix}: {field} must be a string list")
        return ()
    return tuple(value)


def _cases_fingerprint(cases: list[Any]) -> str:
    canonical = json.dumps(
        cases,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def validate_live_cases(raw: Any) -> tuple[str, ...]:
    """Return manifest validation errors without constructing runtime objects."""

    errors: list[str] = []
    if not isinstance(raw, dict):
        return ("root must be a JSON object",)
    unknown_root = set(raw) - ROOT_FIELDS
    missing_root = ROOT_FIELDS - set(raw)
    errors.extend(f"root: unknown key {key}" for key in sorted(unknown_root))
    errors.extend(f"root: missing key {key}" for key in sorted(missing_root))
    if raw.get("version") != "1":
        errors.append('root: version must be "1"')
    cases = raw.get("cases")
    if not isinstance(cases, list):
        errors.append("root: cases must be an array")
        return tuple(errors)
    if _cases_fingerprint(cases) != APPROVED_CASES_SHA256:
        errors.append("manifest: approved case matrix fingerprint mismatch")

    seen: set[str] = set()
    bands: dict[str, int] = {band: 0 for band in EXPECTED_BAND_COUNTS}
    repeat_ids: set[str] = set()
    repeat_total = 0
    for index, case in enumerate(cases):
        prefix = f"case[{index}]"
        if not isinstance(case, dict):
            errors.append(f"{prefix}: must be an object")
            continue
        unknown = set(case) - CASE_FIELDS
        missing = CASE_FIELDS - set(case)
        errors.extend(f"{prefix}: unknown key {key}" for key in sorted(unknown))
        errors.extend(f"{prefix}: missing key {key}" for key in sorted(missing))

        case_id = case.get("id")
        if not isinstance(case_id, str) or not CASE_ID_RE.fullmatch(case_id):
            errors.append(f"{prefix}: invalid id")
            case_id = None
        elif case_id in seen:
            errors.append(f"{prefix}: duplicate id {case_id}")
        else:
            seen.add(case_id)

        for field, allowed in (
            ("band", ALLOWED_BANDS),
            ("invocation", ALLOWED_INVOCATIONS),
            ("expected_mode", ALLOWED_MODES),
            ("expected_behavior", ALLOWED_BEHAVIORS),
        ):
            value = case.get(field)
            if not isinstance(value, str) or value not in allowed:
                errors.append(f"{prefix}: invalid {field}")

        for field in ("request", "rationale"):
            value = case.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{prefix}: {field} must be non-empty string")
        if not isinstance(case.get("source"), str):
            errors.append(f"{prefix}: source must be a string")

        repeats = case.get("repeats")
        if isinstance(repeats, bool) or not isinstance(repeats, int) or repeats not in {1, 2}:
            errors.append(f"{prefix}: repeats must be 1 or 2")
        else:
            repeat_total += repeats
            if repeats == 2 and isinstance(case_id, str):
                repeat_ids.add(case_id)

        exact_output = case.get("exact_output")
        if exact_output is not None and not isinstance(exact_output, str):
            errors.append(f"{prefix}: exact_output must be string or null")

        for field in (
            "required_substrings",
            "forbidden_substrings",
            "preserve_counts",
            "structural_sentinels",
            "forbidden_exact_outputs",
            "review_axes",
        ):
            values = _string_list(case.get(field), field, prefix, errors)
            if field == "review_axes":
                if not values:
                    errors.append(f"{prefix}: review_axes must not be empty")
                for axis in values:
                    if axis not in ALLOWED_AXES:
                        errors.append(f"{prefix}: unknown review axis {axis}")

        observable = case.get("observable_activation")
        if not isinstance(observable, bool):
            errors.append(f"{prefix}: observable_activation must be boolean")

        band = case.get("band")
        if isinstance(band, str) and band in bands:
            bands[band] += 1

    if len(cases) != 14:
        errors.append(f"manifest: expected 14 cases, got {len(cases)}")
    if repeat_total != 17:
        errors.append(f"manifest: expected 17 repeats, got {repeat_total}")
    if repeat_ids != EXPECTED_REPEAT_IDS:
        errors.append(
            "manifest: repeat IDs drifted: "
            f"expected {sorted(EXPECTED_REPEAT_IDS)}, got {sorted(repeat_ids)}"
        )
    for band, expected in EXPECTED_BAND_COUNTS.items():
        if bands[band] != expected:
            errors.append(f"manifest: expected {expected} {band} cases, got {bands[band]}")
    return tuple(errors)


def load_live_cases(path: pathlib.Path) -> tuple[LiveCase, ...]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    errors = validate_live_cases(raw)
    if errors:
        raise ValueError("invalid live case manifest:\n" + "\n".join(errors))
    return tuple(
        LiveCase(
            id=case["id"],
            band=case["band"],
            invocation=case["invocation"],
            expected_mode=case["expected_mode"],
            expected_behavior=case["expected_behavior"],
            request=case["request"],
            source=case["source"],
            repeats=case["repeats"],
            exact_output=case["exact_output"],
            required_substrings=tuple(case["required_substrings"]),
            forbidden_substrings=tuple(case["forbidden_substrings"]),
            preserve_counts=tuple(case["preserve_counts"]),
            structural_sentinels=tuple(case["structural_sentinels"]),
            forbidden_exact_outputs=tuple(case["forbidden_exact_outputs"]),
            observable_activation=case["observable_activation"],
            review_axes=tuple(case["review_axes"]),
            rationale=case["rationale"],
        )
        for case in raw["cases"]
    )


def build_producers() -> tuple[Producer, ...]:
    return (
        Producer("codex-direct", "codex", None),
        Producer("cursor-auto", "cursor", "auto"),
        Producer("cursor-claude", "cursor", "claude-sonnet-5-thinking-high"),
        Producer("cursor-gemini", "cursor", "gemini-3.7-flash-high"),
        Producer("cursor-grok", "cursor", "cursor-grok-4.6-high"),
        Producer("cursor-kimi", "cursor", "kimi-k3-high"),
        Producer("cursor-glm", "cursor", "glm-5.2-high"),
    )


def build_producer_plan(
    cases: tuple[LiveCase, ...] | list[LiveCase],
    producers: tuple[Producer, ...] | list[Producer],
) -> tuple[PlannedCall, ...]:
    plan: list[PlannedCall] = []
    for producer in producers:
        for case in cases:
            for repeat_index in range(1, case.repeats + 1):
                plan.append(
                    PlannedCall(
                        call_id=f"{producer.id}:{case.id}:{repeat_index}",
                        kind="producer",
                        producer_id=producer.id,
                        case_id=case.id,
                        repeat_index=repeat_index,
                    )
                )
    return tuple(plan)


def _utc_now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _receipt_filename(call_id: str, attempt: int) -> str:
    token = hashlib.sha256(f"{call_id}\0{attempt}".encode("utf-8")).hexdigest()
    return f"{token}.json"


def _write_raw_file(run_root: pathlib.Path, relative_path: str, payload: bytes) -> None:
    pure_path = pathlib.PurePosixPath(relative_path)
    if pure_path.is_absolute() or any(part in {"", ".", ".."} for part in pure_path.parts):
        raise LiveMatrixError("raw evidence path escapes run root")
    target = run_root / relative_path
    try:
        target.relative_to(run_root)
    except ValueError as exc:
        raise LiveMatrixError("raw evidence path escapes run root") from exc
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        parent_stat = target.parent.lstat()
    except OSError as exc:
        raise LiveMatrixError("raw evidence parent does not exist") from exc
    if stat.S_ISLNK(parent_stat.st_mode) or not stat.S_ISDIR(parent_stat.st_mode):
        raise LiveMatrixError("raw evidence parent is not a real directory")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(target, flags, 0o600)
    except OSError as exc:
        raise LiveMatrixError("cannot create raw evidence") from exc
    try:
        os.fchmod(descriptor, 0o600)
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise LiveMatrixError("incomplete raw evidence write")
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _read_evidence_file(run_root: pathlib.Path, relative_path: str) -> bytes:
    pure_path = pathlib.PurePosixPath(relative_path)
    if pure_path.is_absolute() or any(part in {"", ".", ".."} for part in pure_path.parts):
        raise LiveMatrixError("evidence path escapes run root")
    path = run_root / relative_path
    try:
        path.relative_to(run_root)
        path_stat = path.lstat()
    except (OSError, ValueError) as exc:
        raise LiveMatrixError("normalized evidence is unavailable") from exc
    if stat.S_ISLNK(path_stat.st_mode) or not stat.S_ISREG(path_stat.st_mode):
        raise LiveMatrixError("normalized evidence is unsafe")
    if path_stat.st_size > MAX_STREAM_BYTES:
        raise LiveMatrixError("normalized evidence exceeds limit")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise LiveMatrixError("cannot read normalized evidence") from exc
    try:
        payload = os.read(descriptor, MAX_STREAM_BYTES + 1)
    finally:
        os.close(descriptor)
    if len(payload) > MAX_STREAM_BYTES:
        raise LiveMatrixError("normalized evidence exceeds limit")
    return payload


def _identity_from_json(payload: Any, *, label: str) -> RunIdentity:
    if not isinstance(payload, dict):
        raise LiveMatrixError(f"malformed {label} identity")
    try:
        producer_ids = payload["producer_ids"]
        requested_models = payload["requested_models"]
        if not all(isinstance(item, str) for item in producer_ids) or not all(
            isinstance(item, str) for item in requested_models
        ):
            raise TypeError
        return RunIdentity(
            run_id=payload["run_id"],
            runner_version=payload["runner_version"],
            repository_head=payload["repository_head"],
            skill_hash=payload["skill_hash"],
            installed_skill_hash=payload["installed_skill_hash"],
            live_cases_hash=payload["live_cases_hash"],
            producer_ids=tuple(producer_ids),
            requested_models=tuple(requested_models),
            scope=payload["scope"],
        )
    except (KeyError, TypeError) as exc:
        raise LiveMatrixError(f"malformed {label} identity") from exc


def _report_state_path(run_root: pathlib.Path) -> pathlib.Path:
    return run_root / REPORT_STATE_FILENAME


def _load_report_state(run_root: pathlib.Path) -> ReportState | None:
    path = _report_state_path(run_root)
    if not path.exists():
        return None
    try:
        payload = json.loads(_read_evidence_file(run_root, REPORT_STATE_FILENAME).decode("utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("relative_target"), str):
            raise ValueError
        sha256 = payload.get("sha256")
        if not isinstance(sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", sha256):
            raise ValueError
        target = pathlib.PurePosixPath(payload["relative_target"])
        if target.is_absolute() or any(part in {"", ".", ".."} for part in target.parts):
            raise ValueError
        return ReportState(
            _identity_from_json(payload.get("identity"), label="report state"),
            target.as_posix(),
            sha256,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise LiveMatrixError("malformed report state") from exc


def _report_state_for_target(
    run_root: pathlib.Path, repository_root: pathlib.Path, target: pathlib.Path, identity: RunIdentity
) -> ReportState:
    state = _load_report_state(run_root)
    if state is None:
        raise LiveMatrixError("report state is required for report-bearing resume")
    try:
        relative = target.relative_to(repository_root).as_posix()
    except ValueError as exc:
        raise LiveMatrixError("report target escapes repository") from exc
    if state.identity != identity or state.relative_target != relative:
        raise LiveMatrixError("report state identity or target drift")
    try:
        target_stat = target.lstat()
    except OSError as exc:
        raise LiveMatrixError("owned operations report is unavailable") from exc
    if stat.S_ISLNK(target_stat.st_mode) or not stat.S_ISREG(target_stat.st_mode):
        raise LiveMatrixError("owned operations report is unsafe")
    if _sha256_file(target) != state.sha256:
        raise LiveMatrixError("owned operations report hash drift")
    return state


def load_normalized_responses(
    run_root: pathlib.Path | None, receipts: Sequence[CallReceipt]
) -> dict[str, str]:
    """Read only exact, ignored normalized producer responses for local packet assembly."""
    if run_root is None:
        return {}
    responses: dict[str, str] = {}
    for receipt in receipts:
        for path in receipt.raw_paths:
            if not path.startswith(f"{NORMALIZED_DIRECTORY_NAME}/") or not path.endswith(".response.txt"):
                continue
            try:
                responses[receipt.call_id] = normalize_response(
                    _read_evidence_file(run_root, path).decode("utf-8")
                )
            except UnicodeDecodeError as exc:
                raise LiveMatrixError("normalized response is not UTF-8") from exc
    return responses


def _receipt_from_json(payload: Any) -> CallReceipt:
    if not isinstance(payload, dict) or not isinstance(payload.get("identity"), dict):
        raise LiveMatrixError("malformed receipt")
    identity_data = payload["identity"]
    try:
        raw_path_values = payload["raw_paths"]
        if not isinstance(raw_path_values, list) or any(
            not isinstance(value, str)
            or pathlib.PurePosixPath(value).is_absolute()
            or any(part in {"", ".", ".."} for part in pathlib.PurePosixPath(value).parts)
            for value in raw_path_values
        ):
            raise ValueError("unsafe raw path")
        identity = RunIdentity(
            run_id=identity_data["run_id"],
            runner_version=identity_data["runner_version"],
            repository_head=identity_data["repository_head"],
            skill_hash=identity_data["skill_hash"],
            installed_skill_hash=identity_data["installed_skill_hash"],
            live_cases_hash=identity_data["live_cases_hash"],
            producer_ids=tuple(identity_data["producer_ids"]),
            requested_models=tuple(identity_data["requested_models"]),
            scope=identity_data["scope"],
        )
        findings = tuple(
            Finding(item["code"], item["message"], item.get("literal"))
            for item in payload["findings"]
        )
        return CallReceipt(
            identity=identity,
            call_id=payload["call_id"],
            call_number=payload["call_number"],
            host=payload["host"],
            requested_model=payload["requested_model"],
            reported_model=payload["reported_model"],
            case_id=payload["case_id"],
            band=payload.get("band"),
            repeat_index=payload["repeat_index"],
            prompt_sha256=payload["prompt_sha256"],
            started_at=payload["started_at"],
            finished_at=payload["finished_at"],
            duration_ms=payload["duration_ms"],
            exit_code=payload["exit_code"],
            stdout_bytes=payload["stdout_bytes"],
            stdout_sha256=payload["stdout_sha256"],
            stderr_bytes=payload["stderr_bytes"],
            stderr_sha256=payload["stderr_sha256"],
            response_sha256=payload["response_sha256"],
            status=payload["status"],
            findings=findings,
            raw_paths=tuple(raw_path_values),
    )
    except (KeyError, TypeError, ValueError) as exc:
        raise LiveMatrixError("malformed receipt") from exc


def _load_receipt_attempts(run_root: pathlib.Path) -> tuple[CallReceipt, ...]:
    receipt_root = run_root / RECEIPT_DIRECTORY_NAME
    if not receipt_root.exists():
        return ()
    if receipt_root.is_symlink() or not receipt_root.is_dir():
        raise LiveMatrixError("receipt directory is not a real directory")
    attempts: list[CallReceipt] = []
    seen_attempts: set[tuple[str, int]] = set()
    seen_call_numbers: set[int] = set()
    for path in sorted(receipt_root.iterdir(), key=lambda item: item.name):
        if path.name.endswith(".partial") and path.name.startswith("."):
            continue
        if path.is_symlink() or not path.is_file() or path.suffix != ".json":
            raise LiveMatrixError("receipt directory contains unsafe entry")
        try:
            receipt = _receipt_from_json(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LiveMatrixError("malformed receipt") from exc
        key = (receipt.call_id, receipt.call_number)
        if key in seen_attempts:
            raise LiveMatrixError("duplicate receipt attempt")
        if receipt.call_number > 0 and receipt.call_number in seen_call_numbers:
            raise LiveMatrixError("duplicate reserved call number")
        seen_attempts.add(key)
        if receipt.call_number > 0:
            seen_call_numbers.add(receipt.call_number)
        attempts.append(receipt)
    return tuple(attempts)


def _load_receipts(run_root: pathlib.Path) -> dict[str, CallReceipt]:
    """Expose only the latest durable receipt for each logical planned call."""
    receipts: dict[str, CallReceipt] = {}
    for receipt in _load_receipt_attempts(run_root):
        logical_id = receipt.call_id.split(":attempt-", 1)[0]
        existing = receipts.get(logical_id)
        if existing is None or receipt.call_number > existing.call_number:
            receipts[logical_id] = receipt
    return receipts


def attempted_call_count(attempts: Sequence[CallReceipt]) -> int:
    """Restore the monotonic call counter without reusing historical numbers."""
    return max((attempt.call_number for attempt in attempts), default=0)


def _write_call_receipt(run_root: pathlib.Path, receipt: CallReceipt) -> None:
    receipt_root = run_root / RECEIPT_DIRECTORY_NAME
    receipt_root.mkdir(mode=0o700, exist_ok=True)
    os.chmod(receipt_root, 0o700)
    attempt = receipt.call_number if receipt.call_number > 0 else 0
    write_receipt(receipt_root / _receipt_filename(receipt.call_id, attempt), receipt)


def _not_measured_receipt(
    call: PlannedCall,
    producer: Producer,
    identity: RunIdentity,
    reason: str,
    band: str | None = None,
) -> CallReceipt:
    timestamp = _utc_now()
    return CallReceipt(
        identity=identity,
        call_id=call.call_id,
        call_number=0,
        host=producer.host,
        requested_model=producer.requested_model,
        reported_model=None,
        case_id=call.case_id,
        band=band,
        repeat_index=call.repeat_index,
        prompt_sha256=hashlib.sha256(b"").hexdigest(),
        started_at=timestamp,
        finished_at=timestamp,
        duration_ms=0,
        exit_code=None,
        stdout_bytes=0,
        stdout_sha256=None,
        stderr_bytes=0,
        stderr_sha256=None,
        response_sha256=None,
        status="not_measured",
        findings=(Finding("model_unavailable", reason),),
        raw_paths=(),
    )


def _blocked_receipt(
    *,
    call: PlannedCall,
    producer: Producer,
    identity: RunIdentity,
    call_number: int,
    prompt_sha256: str,
    started_at: str,
    message: str,
    capture: CommandCapture | None = None,
    raw_paths: tuple[str, ...] = (),
    band: str | None = None,
) -> CallReceipt:
    return CallReceipt(
        identity=identity,
        call_id=call.call_id,
        call_number=call_number,
        host=producer.host,
        requested_model=producer.requested_model,
        reported_model=None,
        case_id=call.case_id,
        band=band,
        repeat_index=call.repeat_index,
        prompt_sha256=prompt_sha256,
        started_at=started_at,
        finished_at=_utc_now(),
        duration_ms=capture.duration_ms if capture is not None else 0,
        exit_code=capture.returncode if capture is not None else None,
        stdout_bytes=len(capture.stdout) if capture is not None else 0,
        stdout_sha256=hashlib.sha256(capture.stdout).hexdigest() if capture is not None else None,
        stderr_bytes=len(capture.stderr) if capture is not None else 0,
        stderr_sha256=hashlib.sha256(capture.stderr).hexdigest() if capture is not None else None,
        response_sha256=None,
        status="blocked",
        findings=(Finding("provider_blocked", message),),
        raw_paths=raw_paths,
    )


def _dispatch_one(
    call: PlannedCall,
    producer: Producer,
    case: LiveCase,
    preflight: PreflightResult,
    budget: CallBudget,
) -> CallReceipt:
    call_number = budget.reserve()
    started_at = _utc_now()
    prompt_sha256 = hashlib.sha256(b"").hexdigest()
    try:
        prompt = build_prompt(case, producer.host)
        prompt_sha256 = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        if producer.host == "codex":
            executable = preflight.cli_info["codex"].path
            if executable is None:
                raise LiveMatrixError("codex CLI is unavailable")
            argv = (executable, *build_codex_argv(preflight.repository_root, prompt)[1:])
        elif producer.host == "cursor":
            executable = preflight.cli_info["cursor-agent"].path
            if executable is None or producer.requested_model is None:
                raise LiveMatrixError("cursor-agent CLI is unavailable")
            argv = (executable, *build_cursor_argv(preflight.repository_root, producer.requested_model, prompt)[1:])
        else:
            raise LiveMatrixError("unsupported provider host")
        capture = run_command(argv, cwd=preflight.repository_root)
    except LiveMatrixError as exc:
        return _blocked_receipt(
            call=call,
            producer=producer,
            identity=preflight.identity,
            call_number=call_number,
            prompt_sha256=prompt_sha256,
            started_at=started_at,
            message=str(exc),
            band=case.band,
        )

    raw_paths = (
        f"{RAW_DIRECTORY_NAME}/{call_number:04d}.stdout.bin",
        f"{RAW_DIRECTORY_NAME}/{call_number:04d}.stderr.bin",
    )
    if preflight.run_root is None:
        raise LiveMatrixError("execution requires an evidence root")
    _write_raw_file(preflight.run_root, raw_paths[0], capture.stdout)
    _write_raw_file(preflight.run_root, raw_paths[1], capture.stderr)
    if capture.returncode != 0:
        return _blocked_receipt(
            call=call,
            producer=producer,
            identity=preflight.identity,
            call_number=call_number,
            prompt_sha256=prompt_sha256,
            started_at=started_at,
            message="provider returned non-zero exit status",
            capture=capture,
            raw_paths=raw_paths,
            band=case.band,
        )
    try:
        if producer.host == "codex":
            response, reported_model = extract_codex_response(capture.stdout)
        else:
            response, reported_model = extract_cursor_response(capture.stdout)
    except LiveMatrixError as exc:
        return _blocked_receipt(
            call=call,
            producer=producer,
            identity=preflight.identity,
            call_number=call_number,
            prompt_sha256=prompt_sha256,
            started_at=started_at,
            message=str(exc),
            capture=capture,
            raw_paths=raw_paths,
            band=case.band,
        )
    normalized_response = normalize_response(response)
    normalized_path = f"{NORMALIZED_DIRECTORY_NAME}/{call_number:04d}.response.txt"
    _write_raw_file(preflight.run_root, normalized_path, normalized_response.encode("utf-8"))
    findings = evaluate_response(case, normalized_response)
    return CallReceipt(
        identity=preflight.identity,
        call_id=call.call_id,
        call_number=call_number,
        host=producer.host,
        requested_model=producer.requested_model,
        reported_model=reported_model,
        case_id=call.case_id,
        band=case.band,
        repeat_index=call.repeat_index,
        prompt_sha256=prompt_sha256,
        started_at=started_at,
        finished_at=_utc_now(),
        duration_ms=capture.duration_ms,
        exit_code=capture.returncode,
        stdout_bytes=len(capture.stdout),
        stdout_sha256=hashlib.sha256(capture.stdout).hexdigest(),
        stderr_bytes=len(capture.stderr),
        stderr_sha256=hashlib.sha256(capture.stderr).hexdigest(),
        response_sha256=hashlib.sha256(normalized_response.encode("utf-8")).hexdigest(),
        status=case_status(case, findings),
        findings=findings,
        raw_paths=raw_paths + (normalized_path,),
    )


def validate_dispatch_identity(preflight: PreflightResult) -> None:
    """Fail closed if the checked checkout or manifests drift before dispatch."""
    report_state = preflight.report_state
    if preflight.report_path is not None:
        report_target = _validated_operations_report_path(preflight.report_path, preflight.repository_root)
        if report_state is not None:
            if preflight.run_root is None:
                raise LiveMatrixError("report state requires an evidence run root")
            _report_state_for_target(
                preflight.run_root, preflight.repository_root, report_target, preflight.identity
            )
    if not _git_status_is_clean(
        preflight.repository_root,
        allowed_report=preflight.report_path if report_state is not None else None,
        report_state=report_state,
    ):
        raise LiveMatrixError("dispatch identity drift: relevant checkout is not clean")
    if _git_value(preflight.repository_root, "rev-parse", "HEAD") != preflight.identity.repository_head:
        raise LiveMatrixError("dispatch identity drift: repository HEAD changed")
    source_hash = recursive_manifest_hash(preflight.source_skill_root)
    installed_hash = recursive_manifest_hash(preflight.installed_skill_root)
    live_cases = preflight.source_skill_root / "evals" / "live_cases.json"
    if source_hash != installed_hash:
        raise LiveMatrixError("dispatch identity drift: source and installed skill manifests differ")
    if source_hash != preflight.identity.skill_hash:
        raise LiveMatrixError("dispatch identity drift: source skill changed")
    if installed_hash != preflight.identity.installed_skill_hash:
        raise LiveMatrixError("dispatch identity drift: installed skill changed")
    if live_cases.is_symlink() or not live_cases.is_file():
        raise LiveMatrixError("dispatch identity drift: live case manifest is unsafe")
    if _sha256_file(live_cases) != preflight.identity.live_cases_hash:
        raise LiveMatrixError("dispatch identity drift: live cases changed")


def dispatch_calls(
    preflight: PreflightResult,
    plan: Sequence[PlannedCall],
    cases: Sequence[LiveCase],
    *,
    jobs: int,
    max_calls: int,
) -> tuple[CallReceipt, ...]:
    """Dispatch only preflight-approved independent calls with bounded workers."""
    if preflight.run_root is None:
        raise LiveMatrixError("dispatch requires an evidence run root")
    job_error = validate_jobs(jobs)
    if job_error:
        raise LiveMatrixError(job_error)
    if preflight.identity.skill_hash != preflight.identity.installed_skill_hash:
        raise LiveMatrixError("source and installed skill manifests differ")
    validate_dispatch_identity(preflight)
    current_producers = build_producers()
    if (
        preflight.identity.producer_ids != tuple(producer.id for producer in current_producers)
        or preflight.identity.requested_models
        != tuple(producer.requested_model for producer in current_producers if producer.requested_model is not None)
    ):
        raise LiveMatrixError("preflight producer identity drift requires a new run ID")
    attempts = _load_receipt_attempts(preflight.run_root)
    receipts = _load_receipts(preflight.run_root)
    pending = remaining_calls(plan, receipts, preflight.identity)
    producers = {producer.id: producer for producer in current_producers}
    case_by_identifier = {case.id: case for case in cases}
    budget = CallBudget(max_calls, attempted=attempted_call_count(attempts))
    result: list[CallReceipt] = []
    eligible: list[tuple[PlannedCall, Producer, LiveCase]] = []
    not_measured: list[CallReceipt] = []
    for call in pending:
        producer = producers.get(call.producer_id)
        case = case_by_identifier.get(call.case_id)
        if producer is None or case is None:
            raise LiveMatrixError("plan references unknown producer or case")
        if producer.host == "cursor" and producer.requested_model is not None:
            if not preflight.model_availability.get(producer.requested_model, False):
                receipt = _not_measured_receipt(
                    call,
                    producer,
                    preflight.identity,
                    "requested Cursor model is unavailable",
                    case.band,
                )
                not_measured.append(receipt)
                continue
        eligible.append((call, producer, case))
    if budget.attempted + len(eligible) > max_calls:
        raise LiveMatrixError("call budget exhausted before dispatch")
    for receipt in not_measured:
        _write_call_receipt(preflight.run_root, receipt)
        result.append(receipt)
    eligible = [
        (
            PlannedCall(
                f"{call.call_id}:attempt-{receipts[call.call_id].call_number + 1}",
                call.kind,
                call.producer_id,
                call.case_id,
                call.repeat_index,
            )
            if call.call_id in receipts
            else call,
            producer,
            case,
        )
        for call, producer, case in eligible
    ]
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as executor:
        iterator = iter(eligible)
        in_flight: set[concurrent.futures.Future[CallReceipt]] = set()
        for _ in range(jobs):
            try:
                call, producer, case = next(iterator)
            except StopIteration:
                break
            in_flight.add(executor.submit(_dispatch_one, call, producer, case, preflight, budget))
        while in_flight:
            completed, _ = concurrent.futures.wait(
                in_flight, return_when=concurrent.futures.FIRST_COMPLETED
            )
            for future in completed:
                in_flight.remove(future)
                receipt = future.result()
                _write_call_receipt(preflight.run_root, receipt)
                result.append(receipt)
                try:
                    call, producer, case = next(iterator)
                except StopIteration:
                    continue
                in_flight.add(executor.submit(_dispatch_one, call, producer, case, preflight, budget))
    return tuple(result)


REVIEWER_MODELS = (
    ("reviewer-claude", "claude-sonnet-5-thinking-high"),
    ("reviewer-gemini", "gemini-3.7-flash-high"),
    ("reviewer-grok", "cursor-grok-4.6-high"),
)
REVIEW_CONTROL_BANDS = ("valid-mode", "preservation", "noop-hold", "near-miss")
STATUS_PRIORITY = {
    "not_measured": 0,
    "verified": 1,
    "partially_verified": 2,
    "blocked": 3,
    "failed": 4,
}
REVIEW_ASSESSMENTS = frozenset({"pass", "concern"})
REVIEW_ISSUE_SEVERITIES = frozenset({"material", "minor"})
SUPERVISORY_CLASSIFICATIONS = frozenset({"pending_adjudication"})
REVIEW_IDENTITY_RE = re.compile(
    r"\b(?:codex-direct|cursor-[A-Za-z0-9.-]+|claude-[A-Za-z0-9.-]+|"
    r"gemini-[A-Za-z0-9.-]+|grok-[A-Za-z0-9.-]+|kimi-[A-Za-z0-9.-]+|glm-[A-Za-z0-9.-]+)\b"
)
POSIX_ABSOLUTE_PATH_RE = re.compile(r"(?<![A-Za-z0-9_.])/(?:[^\s|`'\"]+)")
WINDOWS_DRIVE_PATH_RE = re.compile(r"(?i)(?<![A-Za-z0-9_.-])[A-Z]:[\\/](?:[^\s|`'\"]+)")
WINDOWS_UNC_PATH_RE = re.compile(r"\\\\(?:[^\\/\s|`'\"]+)[\\/](?:[^\s|`'\"]+)")
RAW_EVIDENCE_PATH_RE = re.compile(r"\b(?:raw|normalized)/[^\s`'\"]+")
REPORT_REMOVED_CATEGORIES = frozenset({"Cc", "Cf", "Zl", "Zp"})
EMPTY_REPORT_TEXT = "empty"
OPERATIONS_REPORT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}-kws-korean-writing-editor-cross-model-evaluation\.md$"
)


@dataclass(frozen=True)
class ReviewSample:
    """A bounded anonymous review candidate, never a raw provider transcript."""

    candidate_id: str
    is_failure: bool
    missing_control: bool
    case_id: str
    band: str
    request: str
    source: str
    candidate: str
    hard_findings: tuple[str, ...]
    axes: tuple[str, ...]
    response_sha256: str | None


@dataclass(frozen=True)
class ReviewIssue:
    axis: str
    severity: str
    reason: str


@dataclass(frozen=True)
class ReviewAssessment:
    candidate_id: str
    issues: tuple[ReviewIssue, ...]
    assessment: str


@dataclass(frozen=True)
class ReviewResponse:
    samples: tuple[ReviewAssessment, ...]
    packet_limitations: tuple[str, ...]


@dataclass(frozen=True)
class ReviewerCall:
    reviewer_id: str
    requested_model: str
    prompt: str


@dataclass(frozen=True)
class ReportInput:
    """Facts available to the renderer; raw streams are deliberately absent."""

    identity: RunIdentity
    producer_receipts: tuple[CallReceipt, ...]
    reviewer_receipts: tuple[CallReceipt, ...]
    branch: str
    head: str
    source_skill_hash: str
    installed_skill_hash: str
    producer_attempted_calls: int
    reviewer_attempted_calls: int
    approved_baseline_ceiling: int
    approved_total_ceiling: int
    verification_results: tuple[tuple[str, str], ...]
    git_state: str
    installation_state: str
    producer_ids: tuple[str, ...]
    responses: Mapping[str, str]
    cases: Mapping[str, LiveCase]
    review_responses: tuple[ReviewResponse, ...]
    report_date: str
    cli_versions: Mapping[str, str | None]
    skill_version: str
    case_counts: Mapping[str, int]
    changed_files: tuple[str, ...]
    local_state: str
    remote_state: str
    supervisory_classification: str = "pending_adjudication"

    @classmethod
    def for_test(cls, *, receipts: Sequence[CallReceipt], **overrides: Any) -> "ReportInput":
        identity = RunIdentity.for_test(producer_ids=("test-producer",))
        values: dict[str, Any] = {
            "identity": identity,
            "producer_receipts": tuple(receipts),
            "reviewer_receipts": (),
            "branch": "test-branch",
            "head": "test-head",
            "source_skill_hash": "test-source-hash",
            "installed_skill_hash": "test-installed-hash",
            "producer_attempted_calls": sum(receipt.call_number > 0 for receipt in receipts),
            "reviewer_attempted_calls": 0,
            "approved_baseline_ceiling": BASELINE_CALL_CEILING,
            "approved_total_ceiling": GLOBAL_CALL_CEILING,
            "verification_results": (("synthetic renderer", "partially_verified"),),
            "git_state": "clean synthetic checkout",
            "installation_state": "not installed (synthetic)",
            "producer_ids": ("test-producer",),
            "responses": {},
            "cases": {},
            "review_responses": (),
            "report_date": "2026-08-23",
            "cli_versions": {"codex": "test-codex", "cursor-agent": "test-cursor"},
            "skill_version": "test-skill-version",
            "case_counts": {"total": 14, "repeats": 17},
            "changed_files": (),
            "local_state": "local synthetic only",
            "remote_state": "not published; remote unchanged",
            "supervisory_classification": "pending_adjudication",
        }
        unknown = set(overrides) - set(values)
        if unknown:
            raise TypeError(f"unknown ReportInput test override: {sorted(unknown)[0]}")
        values.update(overrides)
        return cls(**values)


@dataclass(frozen=True)
class GitReportFacts:
    """Read-only local Git facts, explicitly not a remote fetch or publication check."""

    merge_base: str
    ahead: int
    behind: int
    changed_files: tuple[str, ...]
    local_state: str
    remote_state: str


def _bounded_utf8(value: str) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= 240:
        return value
    limit = 237
    clipped: list[str] = []
    used = 0
    for character in value:
        width = len(character.encode("utf-8"))
        if used + width > limit:
            break
        clipped.append(character)
        used += width
    return "".join(clipped) + "..."


def _review_excerpt(value: str, identity_tokens: Sequence[str] = ()) -> str:
    """Redact known secrets and identities, then cap at 240 UTF-8 bytes."""
    redacted = normalize_response(value)
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    redacted = REVIEW_IDENTITY_RE.sub("[REDACTED]", redacted)
    for token in sorted({token for token in identity_tokens if token}, key=len, reverse=True):
        redacted = re.sub(re.escape(token), "[REDACTED]", redacted, flags=re.IGNORECASE)
    return _bounded_utf8(redacted)


def _finding_class(finding: Finding, case: LiveCase | None) -> str:
    """Classify real evaluator evidence from its checked property, not a name hint."""
    if finding.code == "occurrence_count_changed":
        return "literal"
    if finding.code == "missing_structural_sentinel":
        return "embedded"
    if case is None:
        return "general"
    literal = (finding.literal or "").lower()
    if finding.code == "exact_output_mismatch" and case.exact_output is not None:
        return "literal"
    if finding.code in {"missing_required_substring", "forbidden_substring", "forbidden_exact_output"}:
        if any(token in literal for token in ("않", "없", "아니", "not ")):
            return "negation"
        if "attribution" in case.review_axes:
            return "attribution"
        if "embedded-instruction" in case.review_axes or case.structural_sentinels:
            return "embedded"
        if case.preserve_counts:
            return "literal"
    return "general"


def _failure_priority(finding: Finding, case: LiveCase | None) -> tuple[int, str]:
    classes = {"literal": 0, "negation": 1, "attribution": 2, "embedded": 3, "general": 4}
    return classes[_finding_class(finding, case)], finding.code


def _case_for_sample(receipt: CallReceipt, cases: Mapping[str, LiveCase]) -> LiveCase | None:
    return cases.get(receipt.case_id)


def _sample_from_receipt(
    receipt: CallReceipt | None,
    *,
    candidate_id: str,
    is_failure: bool,
    band: str,
    responses: Mapping[str, str],
    cases: Mapping[str, LiveCase],
    identity_tokens: Sequence[str],
    finding_code: str | None = None,
) -> ReviewSample:
    if receipt is None:
        return ReviewSample(
            candidate_id=candidate_id,
            is_failure=False,
            missing_control=True,
            case_id="not-measured",
            band=band,
            request="[not measured control]",
            source="[not measured control]",
            candidate="[not measured control]",
            hard_findings=("control_not_measured",),
            axes=(),
            response_sha256=None,
        )
    case = _case_for_sample(receipt, cases)
    hard_findings = (
        (finding_code,)
        if finding_code is not None
        else tuple(finding.code for finding in receipt.findings)
    )
    return ReviewSample(
        candidate_id=candidate_id,
        is_failure=is_failure,
        missing_control=False,
        case_id=receipt.case_id,
        band=band,
        request=_review_excerpt(case.request if case is not None else "[case request unavailable]", identity_tokens),
        source=_review_excerpt(case.source if case is not None else "[case source unavailable]", identity_tokens),
        candidate=_review_excerpt(responses.get(receipt.call_id, "[response unavailable]"), identity_tokens),
        hard_findings=tuple(_review_excerpt(code, identity_tokens) for code in hard_findings),
        axes=case.review_axes if case is not None else (),
        response_sha256=receipt.response_sha256,
    )


def select_review_samples(
    receipts: Sequence[CallReceipt],
    *,
    responses: Mapping[str, str] | None = None,
    cases: Mapping[str, LiveCase] | None = None,
) -> tuple[ReviewSample, ...]:
    """Choose a deterministic capped failure packet plus one control per band."""
    response_map = responses or {}
    case_map = cases or {}
    identity_tokens = tuple(
        token
        for receipt in receipts
        for token in (
            receipt.call_id.split(":", 1)[0] if ":" in receipt.call_id else "",
            *receipt.identity.producer_ids,
            receipt.requested_model or "",
            receipt.reported_model or "",
        )
    )
    representatives: dict[str, tuple[CallReceipt, Finding]] = {}
    for receipt in sorted(receipts, key=lambda item: (item.case_id, item.repeat_index, item.call_id)):
        if receipt.status != "failed":
            continue
        for finding in receipt.findings or (Finding("failed_without_finding", "failed receipt lacks finding"),):
            representatives.setdefault(finding.code, (receipt, finding))
    ordered_codes = sorted(
        representatives,
        key=lambda code: _failure_priority(
            representatives[code][1], _case_for_sample(representatives[code][0], case_map)
        ),
    )[:8]
    selected: list[tuple[CallReceipt | None, bool, str, str | None]] = [
        (representatives[code][0], True, representatives[code][0].band or "unclassified", code)
        for code in ordered_codes
    ]
    for band in REVIEW_CONTROL_BANDS:
        control_candidates = sorted(
            (receipt for receipt in receipts if receipt.status == "verified" and receipt.band == band),
            key=lambda item: (item.case_id, item.repeat_index, item.call_id),
        )
        selected.append((control_candidates[0] if control_candidates else None, False, band, None))
    return tuple(
        _sample_from_receipt(
            receipt,
            candidate_id=f"candidate-{index:03d}",
            is_failure=is_failure,
            band=band,
            responses=response_map,
            cases=case_map,
            identity_tokens=identity_tokens,
            finding_code=finding_code,
        )
        for index, (receipt, is_failure, band, finding_code) in enumerate(selected, start=1)
    )


def build_review_prompt(samples: Sequence[ReviewSample]) -> str:
    """Build the identity-free JSON-only review packet without provider metadata."""
    packet = {
        "samples": [
            {
                "candidate_id": sample.candidate_id,
                "request": sample.request,
                "source": sample.source,
                "candidate": sample.candidate,
                "hard_findings": list(sample.hard_findings),
                "axes": list(sample.axes),
                "band": sample.band,
                "missing_control": sample.missing_control,
            }
            for sample in samples
        ]
    }
    contract = (
        'Return one JSON object only:\n'
        '{"samples":[{"candidate_id":"candidate-001","issues":[{"axis":"meaning","severity":"material|minor","reason":"..."}],"assessment":"pass|concern"}],"packet_limitations":["..."]}\n'
        "Do not score or rank models, rewrite candidates, infer producers, or claim that agreement proves general Korean quality."
    )
    return f"{contract}\n\nReview packet:\n{json.dumps(packet, ensure_ascii=False, sort_keys=True)}"


def build_reviewer_plan(samples: Sequence[ReviewSample]) -> tuple[ReviewerCall, ...]:
    """Describe exactly three fresh Cursor reviews; dispatch remains opt-in."""
    prompt = build_review_prompt(samples)
    return tuple(ReviewerCall(reviewer_id, requested_model, prompt) for reviewer_id, requested_model in REVIEWER_MODELS)


def _reviewer_call(reviewer: ReviewerCall, call_id: str) -> tuple[PlannedCall, Producer]:
    return (
        PlannedCall(call_id, "reviewer", reviewer.reviewer_id, "review-packet", 1),
        Producer(reviewer.reviewer_id, "cursor", reviewer.requested_model),
    )


def _reviewer_receipt(
    *,
    call: PlannedCall,
    producer: Producer,
    identity: RunIdentity,
    call_number: int,
    prompt: str,
    started_at: str,
    capture: CommandCapture,
    response: str,
    reported_model: str | None,
    raw_paths: tuple[str, ...],
) -> CallReceipt:
    return CallReceipt(
        identity=identity,
        call_id=call.call_id,
        call_number=call_number,
        host=producer.host,
        requested_model=producer.requested_model,
        reported_model=reported_model,
        case_id=call.case_id,
        band=None,
        repeat_index=call.repeat_index,
        prompt_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        started_at=started_at,
        finished_at=_utc_now(),
        duration_ms=capture.duration_ms,
        exit_code=capture.returncode,
        stdout_bytes=len(capture.stdout),
        stdout_sha256=hashlib.sha256(capture.stdout).hexdigest(),
        stderr_bytes=len(capture.stderr),
        stderr_sha256=hashlib.sha256(capture.stderr).hexdigest(),
        response_sha256=hashlib.sha256(response.encode("utf-8")).hexdigest(),
        status="verified",
        findings=(),
        raw_paths=raw_paths,
    )


def dispatch_reviewer_calls(
    preflight: PreflightResult,
    samples: Sequence[ReviewSample],
    *,
    max_calls: int,
) -> tuple[tuple[CallReceipt, ...], tuple[ReviewResponse, ...]]:
    """Dispatch each approved reviewer once, sharing the durable run call budget."""
    if preflight.run_root is None:
        raise LiveMatrixError("reviewer dispatch requires an evidence run root")
    validate_dispatch_identity(preflight)
    attempts = _load_receipt_attempts(preflight.run_root)
    latest = _load_receipts(preflight.run_root)
    budget = CallBudget(max_calls, attempted=attempted_call_count(attempts))
    result: list[CallReceipt] = []
    responses: list[ReviewResponse] = []
    for reviewer in build_reviewer_plan(samples):
        logical_id = f"{reviewer.reviewer_id}:packet:1"
        existing = latest.get(logical_id)
        if existing is not None and existing.status in RESUME_SKIP_STATUSES:
            result.append(existing)
            continue
        call_id = logical_id if existing is None else f"{logical_id}:attempt-{existing.call_number + 1}"
        call, producer = _reviewer_call(reviewer, call_id)
        if not preflight.model_availability.get(reviewer.requested_model, False):
            receipt = _not_measured_receipt(
                call,
                producer,
                preflight.identity,
                "requested Cursor reviewer model is unavailable",
            )
            _write_call_receipt(preflight.run_root, receipt)
            result.append(receipt)
            continue
        call_number = budget.reserve()
        started_at = _utc_now()
        prompt_sha256 = hashlib.sha256(reviewer.prompt.encode("utf-8")).hexdigest()
        try:
            executable = preflight.cli_info["cursor-agent"].path
            if executable is None:
                raise LiveMatrixError("cursor-agent CLI is unavailable")
            capture = run_command(
                (executable, *build_cursor_argv(preflight.repository_root, reviewer.requested_model, reviewer.prompt)[1:]),
                cwd=preflight.repository_root,
            )
        except LiveMatrixError as exc:
            receipt = _blocked_receipt(
                call=call,
                producer=producer,
                identity=preflight.identity,
                call_number=call_number,
                prompt_sha256=prompt_sha256,
                started_at=started_at,
                message=str(exc),
            )
            _write_call_receipt(preflight.run_root, receipt)
            result.append(receipt)
            continue
        raw_paths = (
            f"{RAW_DIRECTORY_NAME}/{call_number:04d}.stdout.bin",
            f"{RAW_DIRECTORY_NAME}/{call_number:04d}.stderr.bin",
        )
        _write_raw_file(preflight.run_root, raw_paths[0], capture.stdout)
        _write_raw_file(preflight.run_root, raw_paths[1], capture.stderr)
        if capture.returncode != 0:
            receipt = _blocked_receipt(
                call=call,
                producer=producer,
                identity=preflight.identity,
                call_number=call_number,
                prompt_sha256=prompt_sha256,
                started_at=started_at,
                message="reviewer returned non-zero exit status",
                capture=capture,
                raw_paths=raw_paths,
            )
            _write_call_receipt(preflight.run_root, receipt)
            result.append(receipt)
            continue
        try:
            response, reported_model = extract_cursor_response(capture.stdout)
        except LiveMatrixError as exc:
            receipt = _blocked_receipt(
                call=call,
                producer=producer,
                identity=preflight.identity,
                call_number=call_number,
                prompt_sha256=prompt_sha256,
                started_at=started_at,
                message=str(exc),
                capture=capture,
                raw_paths=raw_paths,
            )
            _write_call_receipt(preflight.run_root, receipt)
            result.append(receipt)
            continue
        receipt = _reviewer_receipt(
            call=call,
            producer=producer,
            identity=preflight.identity,
            call_number=call_number,
            prompt=reviewer.prompt,
            started_at=started_at,
            capture=capture,
            response=response,
            reported_model=reported_model,
            raw_paths=raw_paths,
        )
        parsed, receipt = parse_reviewer_response_or_block(receipt, response, samples)
        if parsed is not None:
            normalized_path = f"{NORMALIZED_DIRECTORY_NAME}/{call_number:04d}.review.json"
            _write_raw_file(preflight.run_root, normalized_path, response.encode("utf-8"))
            receipt = replace(receipt, raw_paths=receipt.raw_paths + (normalized_path,))
            responses.append(parsed)
        _write_call_receipt(preflight.run_root, receipt)
        result.append(receipt)
    return tuple(result), tuple(responses)


def load_review_responses(
    run_root: pathlib.Path | None, receipts: Sequence[CallReceipt], samples: Sequence[ReviewSample]
) -> tuple[ReviewResponse, ...]:
    if run_root is None:
        return ()
    responses: list[ReviewResponse] = []
    for receipt in receipts:
        for path in receipt.raw_paths:
            if path.startswith(f"{NORMALIZED_DIRECTORY_NAME}/") and path.endswith(".review.json"):
                try:
                    payload = _read_evidence_file(run_root, path).decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise LiveMatrixError("normalized reviewer response is not UTF-8") from exc
                responses.append(parse_review_response(payload, samples))
    return tuple(responses)


def parse_review_response(payload: str, samples: Sequence[ReviewSample]) -> ReviewResponse:
    """Accept only the declared reviewer JSON object; never repair or retry it."""
    if not isinstance(payload, str) or not payload.strip().startswith("{"):
        raise LiveMatrixError("review response is not one JSON object")
    try:
        document = json.loads(payload)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise LiveMatrixError("review response is not valid JSON") from exc
    if not isinstance(document, dict) or set(document) != {"samples", "packet_limitations"}:
        raise LiveMatrixError("review response does not match exact contract")
    raw_samples = document["samples"]
    limitations = document["packet_limitations"]
    expected_ids = [sample.candidate_id for sample in samples]
    if not isinstance(raw_samples, list) or not isinstance(limitations, list):
        raise LiveMatrixError("review response has invalid collections")
    parsed: list[ReviewAssessment] = []
    for item in raw_samples:
        if not isinstance(item, dict) or set(item) != {"candidate_id", "issues", "assessment"}:
            raise LiveMatrixError("review response sample does not match exact contract")
        candidate_id = item["candidate_id"]
        if not isinstance(candidate_id, str) or not isinstance(item["issues"], list):
            raise LiveMatrixError("review response sample has invalid fields")
        if item["assessment"] not in {"pass", "concern"}:
            raise LiveMatrixError("review response assessment is invalid")
        issues: list[ReviewIssue] = []
        for issue in item["issues"]:
            if not isinstance(issue, dict) or set(issue) != {"axis", "severity", "reason"}:
                raise LiveMatrixError("review response issue does not match exact contract")
            if issue["axis"] not in ALLOWED_AXES or issue["severity"] not in {"material", "minor"}:
                raise LiveMatrixError("review response issue is invalid")
            if not isinstance(issue["reason"], str) or not issue["reason"].strip():
                raise LiveMatrixError("review response issue reason is invalid")
            issues.append(ReviewIssue(issue["axis"], issue["severity"], _review_excerpt(issue["reason"])))
        parsed.append(ReviewAssessment(candidate_id, tuple(issues), item["assessment"]))
    if [assessment.candidate_id for assessment in parsed] != expected_ids:
        raise LiveMatrixError("review response candidate IDs do not match packet")
    if any(not isinstance(item, str) for item in limitations):
        raise LiveMatrixError("review response limitations are invalid")
    return ReviewResponse(tuple(parsed), tuple(_review_excerpt(item) for item in limitations))


def parse_reviewer_response_or_block(
    receipt: CallReceipt, payload: str, samples: Sequence[ReviewSample]
) -> tuple[ReviewResponse | None, CallReceipt]:
    """Convert one malformed reviewer reply to one blocked receipt without a repair call."""
    try:
        return parse_review_response(payload, samples), receipt
    except LiveMatrixError as exc:
        return None, replace(
            receipt,
            status="blocked",
            findings=(Finding("review_json_invalid", "review response rejected without repair", _review_excerpt(str(exc))),),
        )


def _producer_for_receipt(receipt: CallReceipt, producer_ids: Sequence[str]) -> str:
    for producer_id in producer_ids:
        if receipt.call_id.startswith(f"{producer_id}:"):
            return producer_id
    return receipt.call_id.split(":", 1)[0]


def aggregate_statuses(
    receipts: Sequence[CallReceipt],
    *,
    producer_ids: Sequence[str] = (),
    bands: Sequence[str] = REVIEW_CONTROL_BANDS,
) -> dict[tuple[str, str], str]:
    """Reduce each producer/band with failure precedence; no status is averaged."""
    known_producers = list(dict.fromkeys((*producer_ids, *(_producer_for_receipt(r, producer_ids) for r in receipts))))
    result: dict[tuple[str, str], str] = {}
    for producer_id in known_producers:
        for band in bands:
            statuses = [
                receipt.status
                for receipt in receipts
                if _producer_for_receipt(receipt, producer_ids) == producer_id and receipt.band == band
            ]
            if any(status not in STATUS_PRIORITY for status in statuses):
                raise LiveMatrixError("unknown receipt status for aggregation")
            result[(producer_id, band)] = max(statuses, key=STATUS_PRIORITY.__getitem__) if statuses else "not_measured"
    return result


def _render_status(status: str) -> str:
    if not isinstance(status, str) or status not in STATUS_PRIORITY:
        raise LiveMatrixError("report status is invalid")
    return status.replace("_", " ")


def _render_review_assessment(value: str) -> str:
    if not isinstance(value, str) or value not in REVIEW_ASSESSMENTS:
        raise LiveMatrixError("review assessment is invalid")
    return value


def _render_review_severity(value: str) -> str:
    if not isinstance(value, str) or value not in REVIEW_ISSUE_SEVERITIES:
        raise LiveMatrixError("review issue severity is invalid")
    return value


def _render_supervisory_classification(value: str) -> str:
    if not isinstance(value, str) or value not in SUPERVISORY_CLASSIFICATIONS:
        raise LiveMatrixError("supervisory classification is invalid")
    return value.replace("_", " ")


def _finding_severity(finding: Finding, case: LiveCase | None) -> str:
    return "material" if _failure_priority(finding, case)[0] < 4 else "minor"


def _normalize_report_characters(value: str) -> str:
    """Remove controls, formats, and line/paragraph separators."""
    return "".join(
        character
        for character in value
        if unicodedata.category(character) not in REPORT_REMOVED_CATEGORIES
    )


def _safe_report_text(value: str | None) -> str:
    """Render one bounded external fact as inert Markdown inline code."""
    if value is None:
        return "not measured"
    if not isinstance(value, str):
        raise LiveMatrixError("report fact must be a string")
    redacted = _normalize_report_characters(normalize_response(value))
    redacted = redacted.translate(
        str.maketrans({
            "&": "＆", "<": "‹", ">": "›", "[": "［", "]": "］",
            "(": "（", ")": "）", "|": "¦", "#": "＃", "*": "＊", "`": "｀",
        })
    )
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    redacted = POSIX_ABSOLUTE_PATH_RE.sub("[REDACTED_PATH]", redacted)
    redacted = WINDOWS_DRIVE_PATH_RE.sub("[REDACTED_PATH]", redacted)
    redacted = WINDOWS_UNC_PATH_RE.sub("[REDACTED_PATH]", redacted)
    redacted = RAW_EVIDENCE_PATH_RE.sub("[REDACTED_PATH]", redacted)
    # Backticks delimit the positive inline-code boundary. The translation
    # above also keeps raw HTML/link text and GFM table pipes visibly inert.
    inert = redacted.strip() or EMPTY_REPORT_TEXT
    return f"`{_bounded_utf8(inert)}`"


def render_operations_report(report_input: ReportInput) -> str:
    """Render fact-only markdown without raw streams, identities, paths, or response bodies."""
    receipts = report_input.producer_receipts
    producer_ids = report_input.producer_ids or report_input.identity.producer_ids
    matrix = aggregate_statuses(receipts, producer_ids=producer_ids)
    lines = [
        "# KWS Korean Writing Editor Cross-Model Evaluation",
        "",
        "## Fixed Evidence",
        "",
        f"- Report date: {_safe_report_text(report_input.report_date)}",
        f"- Run ID: {_safe_report_text(report_input.identity.run_id)}",
        f"- Branch: {_safe_report_text(report_input.branch)}",
        f"- Repository HEAD: {_safe_report_text(report_input.head)}",
        f"- Source skill hash: {_safe_report_text(report_input.source_skill_hash)}",
        f"- Installed skill hash: {_safe_report_text(report_input.installed_skill_hash)}",
        f"- Skill version: {_safe_report_text(report_input.skill_version)}",
        "- CLI versions: " + ", ".join(
            f"{_safe_report_text(name)}={_safe_report_text(version)}"
            for name, version in sorted(report_input.cli_versions.items())
        ),
        "- Case counts: " + ", ".join(
            f"{_safe_report_text(name)}={count}" for name, count in sorted(report_input.case_counts.items())
        ),
        f"- Producer attempted calls: {report_input.producer_attempted_calls}",
        f"- Reviewer attempted calls: {report_input.reviewer_attempted_calls}",
        f"- Approved ceilings: baseline {report_input.approved_baseline_ceiling}; total {report_input.approved_total_ceiling}",
        "",
        "## Model Matrix",
        "",
        "| Producer | valid mode | preservation | noop hold | near miss |",
        "| --- | --- | --- | --- | --- |",
    ]
    for producer_id in producer_ids:
        lines.append(
            "| " + _safe_report_text(producer_id) + " | " + " | ".join(
                _render_status(matrix.get((producer_id, band), "not_measured")) for band in REVIEW_CONTROL_BANDS
            ) + " |"
        )
    for receipt in receipts:
        lines.append(
            f"- Producer receipt: requested={_safe_report_text(receipt.requested_model)}; "
            f"reported={_safe_report_text(receipt.reported_model)}; "
            f"response_sha256={_safe_report_text(receipt.response_sha256)}."
        )
    lines.extend(("", "## Results By Band", ""))
    for band in REVIEW_CONTROL_BANDS:
        counts = {status: 0 for status in STATUS_PRIORITY}
        for producer_id in producer_ids:
            counts[matrix.get((producer_id, band), "not_measured")] += 1
        lines.append(
            f"- {band}: " + ", ".join(f"{_render_status(status)}={counts[status]}" for status in STATUS_PRIORITY)
        )
    lines.extend(("", "## Defect Register", ""))
    defect_number = 0
    for receipt in sorted(receipts, key=lambda item: (item.case_id, item.repeat_index, item.call_id)):
        if receipt.status != "failed":
            continue
        for finding in receipt.findings:
            defect_number += 1
            case = report_input.cases.get(receipt.case_id)
            excerpt = _safe_report_text(finding.literal or finding.message)
            lines.append(
                f"- D-{defect_number:03d} | {_finding_severity(finding, case)} | case={_safe_report_text(receipt.case_id)} | "
                f"repeat={receipt.repeat_index} | response_sha256={_safe_report_text(receipt.response_sha256)} | "
                f"{_safe_report_text(finding.code)}: {excerpt}"
            )
    if defect_number == 0:
        lines.append("- No deterministic failures recorded.")
    lines.extend(("", "## Review Findings", ""))
    if not report_input.review_responses:
        lines.append("- No reviewer opinion recorded; reviewer evidence is not model truth.")
        lines.append("- Cross-review coverage=0/3; insufficient cross-review evidence.")
    else:
        candidate_assessments: dict[str, list[ReviewAssessment]] = {}
        for index, response in enumerate(report_input.review_responses, start=1):
            concerns = sum(
                _render_review_assessment(assessment.assessment) == "concern"
                for assessment in response.samples
            )
            details = "; ".join(
                f"{_safe_report_text(assessment.candidate_id)}={_render_review_assessment(assessment.assessment)}:"
                f"{','.join(_safe_report_text(issue.axis) for issue in assessment.issues) or 'no issues'}"
                for assessment in response.samples
            )
            lines.append(f"- Reviewer packet {index}: concerns={concerns}; {details}.")
            for assessment in response.samples:
                candidate_assessments.setdefault(assessment.candidate_id, []).append(assessment)
            if response.packet_limitations:
                lines.append(
                    "- Reviewer packet " + str(index) + " limitations: " + "; ".join(
                        _safe_report_text(limitation) for limitation in response.packet_limitations
                    ) + "."
                )
        for candidate_id, assessments in sorted(candidate_assessments.items()):
            labels = {_render_review_assessment(assessment.assessment) for assessment in assessments}
            if len(assessments) < 2:
                verdict = "insufficient cross-review evidence"
            elif len(labels) == 1:
                verdict = "agreement"
            else:
                verdict = "disagreement"
            issue_details = "; ".join(
                ", ".join(
                    f"{_safe_report_text(issue.axis)}/{_render_review_severity(issue.severity)}/{_safe_report_text(issue.reason)}"
                    for issue in assessment.issues
                ) or "no issues"
                for assessment in assessments
            )
            coverage = f"{len(assessments)}/{len(REVIEWER_MODELS)}"
            coverage_label = "partial reviewer coverage" if len(assessments) < len(REVIEWER_MODELS) else "reviewer coverage"
            lines.append(
                f"- {_safe_report_text(candidate_id)}: {verdict}; {coverage_label}={coverage}; "
                f"assessments={','.join(_render_review_assessment(assessment.assessment) for assessment in assessments)}; details={issue_details}."
            )
        lines.append("- Agreement and disagreement are retained as diagnostic evidence and are not aggregate quality scores.")
    for receipt in report_input.reviewer_receipts:
        blocked = "; ".join(
            f"{_safe_report_text(finding.code)}: {_safe_report_text(finding.message)}"
            for finding in receipt.findings
        )
        lines.append(
            f"- Reviewer receipt: requested={_safe_report_text(receipt.requested_model)}; "
            f"reported={_safe_report_text(receipt.reported_model)}; status={_render_status(receipt.status)}; "
            f"response_sha256={_safe_report_text(receipt.response_sha256)}; cause={blocked or 'none'}."
        )
    lines.extend(
        (
            "",
            "## Adopted And Rejected Improvements",
            "",
            f"- Supervisory classification: {_render_supervisory_classification(report_input.supervisory_classification)}.",
            "- No reviewer suggestion is adopted or rejected before evidence-based adjudication.",
            "",
            "## Verification",
            "",
        )
    )
    lines.extend(
        f"- {_safe_report_text(command)}: {_safe_report_text(status)}"
        for command, status in report_input.verification_results
    )
    lines.extend(
        (
            "",
            "## Limitations And Residual Risks",
            "",
            "- Review packets use redacted 240-byte excerpts and do not establish general Korean quality.",
            "- Failed evidence has precedence in aggregation and is never averaged away.",
            "- Pending adjudication remains until the dedicated Task 8 classification step.",
            "",
            "## Git And Installation State",
            "",
            "- Changed files: " + (", ".join(_safe_report_text(path) for path in report_input.changed_files) or "not measured"),
            f"- Local: {_safe_report_text(report_input.local_state)}",
            f"- Remote: {_safe_report_text(report_input.remote_state)}",
            f"- Git: {_safe_report_text(report_input.git_state)}",
            f"- Installation: {_safe_report_text(report_input.installation_state)}",
        )
    )
    return "\n".join(lines) + "\n"


def _skill_version(skill_root: pathlib.Path) -> str:
    try:
        content = (skill_root / "SKILL.md").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise LiveMatrixError("cannot read skill version") from exc
    match = re.search(r'^\s*version:\s*["\']?([^"\'\s]+)', content, re.MULTILINE)
    if match is None:
        raise LiveMatrixError("skill version is unavailable")
    return match.group(1)


def _git_report_facts(repository_root: pathlib.Path, branch: str, head: str) -> GitReportFacts:
    """Collect reportable Git facts from current local refs without network access."""
    merge_base = _git_value(repository_root, "merge-base", "main", head)
    divergence = _git_value(repository_root, "rev-list", "--left-right", "--count", f"main...{head}")
    fields = divergence.split()
    if len(fields) != 2 or not all(field.isdigit() for field in fields):
        raise LiveMatrixError("git divergence output is malformed")
    behind, ahead = (int(field) for field in fields)
    capture = run_command(
        ("git", "diff", "--name-only", f"{merge_base}..{head}"), cwd=repository_root, timeout=30
    )
    if capture.returncode != 0:
        raise LiveMatrixError("git changed-file report command failed")
    try:
        files = tuple(sorted(line for line in capture.stdout.decode("utf-8").splitlines() if line))
    except UnicodeDecodeError as exc:
        raise LiveMatrixError("changed file list is not UTF-8") from exc
    if any(pathlib.PurePosixPath(path).is_absolute() or ".." in pathlib.PurePosixPath(path).parts for path in files):
        raise LiveMatrixError("changed file list is unsafe")
    containing = _git_value(
        repository_root,
        "for-each-ref",
        "--format=%(refname:short)",
        "--contains",
        head,
        "refs/remotes",
    )
    refs = tuple(line for line in containing.splitlines() if line)
    remote_state = (
        "current local refs: remote-tracking refs containing HEAD: " + ", ".join(refs)
        if refs
        else "current local remote-tracking refs contain no HEAD; no fetch or publication was performed"
    )
    return GitReportFacts(
        merge_base=merge_base,
        ahead=ahead,
        behind=behind,
        changed_files=files,
        local_state=(
            f"current local refs: branch={branch}; base=main; merge_base={merge_base}; "
            f"divergence main...HEAD behind={behind} ahead={ahead}"
        ),
        remote_state=remote_state,
    )


def _latest_by_logical_id(receipts: Sequence[CallReceipt]) -> dict[str, CallReceipt]:
    latest: dict[str, CallReceipt] = {}
    for receipt in receipts:
        logical_id = receipt.call_id.split(":attempt-", 1)[0]
        previous = latest.get(logical_id)
        if previous is None or receipt.call_number >= previous.call_number:
            latest[logical_id] = receipt
    return latest


def _all_attempts_with_new(
    run_root: pathlib.Path | None, new_receipts: Sequence[CallReceipt]
) -> tuple[CallReceipt, ...]:
    persisted = _load_receipt_attempts(run_root) if isinstance(run_root, pathlib.Path) else ()
    attempts: dict[tuple[str, int], CallReceipt] = {
        (receipt.call_id, receipt.call_number): receipt for receipt in persisted
    }
    attempts.update({(receipt.call_id, receipt.call_number): receipt for receipt in new_receipts})
    return tuple(attempts.values())


def _is_reviewer_receipt(receipt: CallReceipt) -> bool:
    return any(receipt.call_id.startswith(f"{reviewer_id}:") for reviewer_id, _ in REVIEWER_MODELS)


def build_report_input(
    preflight: PreflightResult,
    cases: Sequence[LiveCase],
    producer_receipts: Sequence[CallReceipt],
    reviewer_receipts: Sequence[CallReceipt],
    review_responses: Sequence[ReviewResponse],
    *,
    producer_attempted_calls: int,
    reviewer_attempted_calls: int,
) -> ReportInput:
    case_counts: dict[str, int] = {"total": len(cases), "repeats": sum(case.repeats for case in cases)}
    case_counts.update({band: sum(case.band == band for case in cases) for band in REVIEW_CONTROL_BANDS})
    cli_versions = {name: info.version for name, info in preflight.cli_info.items()}
    git_facts = preflight.git_facts or _git_report_facts(
        preflight.repository_root, preflight.repository_branch, preflight.identity.repository_head
    )
    return ReportInput(
        identity=preflight.identity,
        producer_receipts=tuple(producer_receipts),
        reviewer_receipts=tuple(reviewer_receipts),
        branch=preflight.repository_branch,
        head=preflight.identity.repository_head,
        source_skill_hash=preflight.identity.skill_hash,
        installed_skill_hash=preflight.identity.installed_skill_hash,
        producer_attempted_calls=producer_attempted_calls,
        reviewer_attempted_calls=reviewer_attempted_calls,
        approved_baseline_ceiling=BASELINE_CALL_CEILING,
        approved_total_ceiling=GLOBAL_CALL_CEILING,
        verification_results=(
            ("python3 evals/run.py --self-test", "verified"),
            ("python3 evals/run.py --scope full", "verified"),
            ("receipt identity and bounds", "verified"),
        ),
        git_state="local execution evidence only",
        installation_state="retained source/install manifest equality required",
        producer_ids=preflight.identity.producer_ids,
        responses={},
        cases={case.id: case for case in cases},
        review_responses=tuple(review_responses),
        report_date=datetime.date.today().isoformat(),
        cli_versions=cli_versions,
        skill_version=_skill_version(preflight.source_skill_root),
        case_counts=case_counts,
        changed_files=git_facts.changed_files,
        local_state=git_facts.local_state,
        remote_state=git_facts.remote_state,
    )


def _validated_operations_report_path(path: pathlib.Path, repository_root: pathlib.Path) -> pathlib.Path:
    """Validate the fixed report location and every existing ancestor without mutation."""
    lexical_root = repository_root.absolute()
    raw_target = path if path.is_absolute() else lexical_root / path
    lexical_parent = raw_target.parent
    if raw_target.name == "" or not OPERATIONS_REPORT_RE.fullmatch(raw_target.name):
        raise LiveMatrixError("report path must use the dated operations-report name")
    if lexical_parent.name != "operations" or lexical_parent.parent.name != "docs":
        raise LiveMatrixError("report path must be below docs/operations")
    try:
        lexical_repository = lexical_parent.parent.parent
        canonical_repository = repository_root.resolve(strict=True)
        if lexical_repository.resolve(strict=True) != canonical_repository:
            raise LiveMatrixError("report path must be below docs/operations")
    except OSError as exc:
        raise LiveMatrixError("cannot resolve report repository root") from exc
    ancestor = lexical_repository
    for component in ("docs", "operations"):
        ancestor = ancestor / component
        try:
            ancestor_stat = ancestor.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise LiveMatrixError("cannot inspect report parent") from exc
        if stat.S_ISLNK(ancestor_stat.st_mode) or not stat.S_ISDIR(ancestor_stat.st_mode):
            raise LiveMatrixError("report parent is unsafe")
    try:
        target = raw_target.resolve(strict=False)
        expected_parent = canonical_repository / "docs" / "operations"
    except OSError as exc:
        raise LiveMatrixError("cannot resolve operations report path") from exc
    try:
        target.relative_to(expected_parent)
    except ValueError as exc:
        raise LiveMatrixError("report path must be below docs/operations") from exc
    if target.parent != expected_parent or not OPERATIONS_REPORT_RE.fullmatch(target.name):
        raise LiveMatrixError("report path must use the dated operations-report name")
    try:
        target_stat = target.lstat()
    except FileNotFoundError:
        return target
    except OSError as exc:
        raise LiveMatrixError("cannot inspect operations report") from exc
    if stat.S_ISLNK(target_stat.st_mode) or not stat.S_ISREG(target_stat.st_mode):
        raise LiveMatrixError("operations report target is unsafe")
    return target


def _atomic_replace_file(path: pathlib.Path, payload: bytes, *, mode: int) -> None:
    temporary = path.parent / f".{path.name}.{secrets.token_hex(16)}.partial"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(temporary, flags, mode)
    except OSError as exc:
        raise LiveMatrixError("cannot create report staging file") from exc
    published = False
    try:
        os.fchmod(descriptor, mode)
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise LiveMatrixError("incomplete operations report write")
            offset += written
        os.fsync(descriptor)
        os.replace(temporary, path)
        published = True
        directory_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        os.close(descriptor)
        if not published:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass


def _write_report_state(run_root: pathlib.Path, state: ReportState, *, replace_existing: bool) -> None:
    path = _report_state_path(run_root)
    if not replace_existing:
        _write_exclusive_json(path, state.as_json())
        return
    _atomic_replace_file(path, _canonical_json_bytes(state.as_json()), mode=0o600)


def write_operations_report(
    path: pathlib.Path,
    report: str,
    repository_root: pathlib.Path,
    *,
    run_root: pathlib.Path | None = None,
    identity: RunIdentity | None = None,
    report_state: ReportState | None = None,
) -> None:
    """Safely publish or atomically update only the report owned by this run."""
    try:
        repository_root = repository_root.resolve(strict=True)
    except OSError as exc:
        raise LiveMatrixError("cannot resolve repository root for report") from exc
    target = _validated_operations_report_path(path, repository_root)
    parent = target.parent
    ancestor = repository_root
    for component in parent.relative_to(repository_root).parts:
        ancestor = ancestor / component
        if ancestor.exists():
            if ancestor.is_symlink() or not ancestor.is_dir():
                raise LiveMatrixError("report parent is unsafe")
            continue
        try:
            ancestor.mkdir(mode=0o755)
        except OSError as exc:
            raise LiveMatrixError("cannot create report parent") from exc
    if parent.is_symlink() or not parent.is_dir():
        raise LiveMatrixError("report parent is unsafe")
    payload = report.encode("utf-8")
    if report_state is not None:
        if run_root is None or identity is None:
            raise LiveMatrixError("report state update requires run identity")
        _report_state_for_target(run_root, repository_root, target, identity)
        _atomic_replace_file(target, payload, mode=0o644)
    else:
        if target.exists() or target.is_symlink():
            raise LiveMatrixError("operations report already exists")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(target, flags, 0o644)
        except OSError as exc:
            raise LiveMatrixError("cannot create operations report") from exc
        try:
            offset = 0
            while offset < len(payload):
                written = os.write(descriptor, payload[offset:])
                if written <= 0:
                    raise LiveMatrixError("incomplete operations report write")
                offset += written
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    if run_root is not None or identity is not None:
        if run_root is None or identity is None:
            raise LiveMatrixError("report state requires run identity")
        try:
            relative = target.relative_to(repository_root).as_posix()
        except ValueError as exc:
            raise LiveMatrixError("report target escapes repository") from exc
        _write_report_state(
            run_root,
            ReportState(identity, relative, hashlib.sha256(payload).hexdigest()),
            replace_existing=report_state is not None,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="print the provider-free call budget")
    parser.add_argument("--preflight", action="store_true", help="perform zero-inference paid-run checks")
    parser.add_argument("--execute", action="store_true", help="allow provider dispatch after preflight")
    parser.add_argument("--resume", action="store_true", help="resume matching interrupted run evidence")
    parser.add_argument("--scope", choices=("baseline", "remediation"), default="baseline")
    parser.add_argument("--run-id")
    parser.add_argument("--jobs", type=int, default=3)
    parser.add_argument("--max-calls", type=int)
    parser.add_argument("--evidence-root", type=pathlib.Path)
    parser.add_argument("--report", type=pathlib.Path)
    parser.add_argument("--source-skill-root", type=pathlib.Path)
    parser.add_argument("--installed-skill-root", type=pathlib.Path)
    parser.add_argument("--repository-root", type=pathlib.Path)
    parser.add_argument("--compare-skill-roots", nargs=2, metavar=("ROOT_A", "ROOT_B"))
    args = parser.parse_args(argv)

    if args.compare_skill_roots is not None:
        if any((args.dry_run, args.preflight, args.execute, args.resume)):
            parser.error("--compare-skill-roots is read-only and cannot combine with run modes")
        left, right = (pathlib.Path(value) for value in args.compare_skill_roots)
        try:
            payload = {"left": recursive_manifest_hash(left), "right": recursive_manifest_hash(right)}
        except LiveMatrixError as exc:
            print(json.dumps({"error": str(exc)}, sort_keys=True), file=sys.stderr)
            return 1
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0 if payload["left"] == payload["right"] else 1

    if args.dry_run:
        if any((args.preflight, args.execute, args.resume)):
            parser.error("--dry-run cannot combine with live run modes")
        manifest = pathlib.Path(__file__).with_name("live_cases.json")
        cases = load_live_cases(manifest)
        plan = build_producer_plan(cases, build_producers())
        producer_calls = len(plan)
        reviewer_calls = 3
        baseline_calls = producer_calls + reviewer_calls
        payload = {
            "producer_calls": producer_calls,
            "reviewer_calls": reviewer_calls,
            "baseline_calls": baseline_calls,
            "approved_total_ceiling": GLOBAL_CALL_CEILING,
        }
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0

    if not args.preflight and not args.execute:
        parser.error("choose --dry-run, --preflight, --execute, or --compare-skill-roots")
    if args.resume and not args.execute:
        parser.error("--resume requires --execute")
    if args.run_id is None:
        parser.error("--run-id is required for preflight or execution")
    job_error = validate_jobs(args.jobs)
    if job_error:
        parser.error(job_error)
    max_calls = args.max_calls
    if max_calls is None:
        max_calls = BASELINE_CALL_CEILING if args.scope == "baseline" else GLOBAL_CALL_CEILING
    if max_calls > GLOBAL_CALL_CEILING or max_calls < 0:
        parser.error("max calls cannot exceed 160")
    if args.scope == "baseline" and max_calls > BASELINE_CALL_CEILING:
        parser.error("baseline max calls cannot exceed 122")

    source_root = args.source_skill_root or pathlib.Path(__file__).resolve().parent.parent
    installed_root = args.installed_skill_root or (
        pathlib.Path.home() / ".agents" / "skills" / "kws-korean-writing-editor"
    )
    repository_root = args.repository_root or pathlib.Path.cwd()
    evidence_root = args.evidence_root or (
        repository_root / ".superpowers" / "kws-korean-writing-editor" / "live"
    )
    try:
        preflight = validate_preflight(
            source_skill_root=source_root,
            installed_skill_root=installed_root,
            repository_root=repository_root,
            run_id=args.run_id,
            scope=args.scope,
            jobs=args.jobs,
            max_calls=max_calls,
            evidence_root=evidence_root,
            resume=args.resume,
            reuse_preflight=args.execute,
            report_path=args.report,
        )
        if args.execute:
            report_path = (
                _validated_operations_report_path(args.report, preflight.repository_root)
                if args.report is not None
                else None
            )
            cases = load_live_cases(source_root / "evals" / "live_cases.json")
            dispatched_producers = dispatch_calls(
                preflight,
                build_producer_plan(cases, build_producers()),
                cases,
                jobs=args.jobs,
                max_calls=max_calls,
            )
            durable_after_producers = _latest_by_logical_id(
                (*_load_receipts(preflight.run_root).values(), *dispatched_producers)
            )
            producer_receipts = tuple(
                receipt for receipt in durable_after_producers.values() if not _is_reviewer_receipt(receipt)
            )
            samples = select_review_samples(
                producer_receipts,
                responses=load_normalized_responses(preflight.run_root, producer_receipts),
                cases={case.id: case for case in cases},
            )
            dispatched_reviewers, new_review_responses = dispatch_reviewer_calls(
                preflight,
                samples,
                max_calls=max_calls,
            )
            all_attempts = _all_attempts_with_new(
                preflight.run_root,
                (*dispatched_producers, *dispatched_reviewers),
            )
            durable_receipts = _latest_by_logical_id(
                (*_load_receipts(preflight.run_root).values(), *dispatched_producers, *dispatched_reviewers)
            )
            producer_receipts = tuple(
                receipt for receipt in durable_receipts.values() if not _is_reviewer_receipt(receipt)
            )
            reviewer_receipts = tuple(
                receipt for receipt in durable_receipts.values() if _is_reviewer_receipt(receipt)
            )
            review_responses = load_review_responses(preflight.run_root, reviewer_receipts, samples)
            if not review_responses:
                review_responses = new_review_responses
            producer_attempted_calls = sum(
                receipt.call_number > 0 for receipt in all_attempts if not _is_reviewer_receipt(receipt)
            )
            reviewer_attempted_calls = sum(
                receipt.call_number > 0 for receipt in all_attempts if _is_reviewer_receipt(receipt)
            )
            if report_path is not None:
                report_input = build_report_input(
                    preflight,
                    cases,
                    producer_receipts,
                    reviewer_receipts,
                    review_responses,
                    producer_attempted_calls=producer_attempted_calls,
                    reviewer_attempted_calls=reviewer_attempted_calls,
                )
                write_operations_report(
                    report_path,
                    render_operations_report(report_input),
                    preflight.repository_root,
                    run_root=preflight.run_root,
                    identity=preflight.identity,
                    report_state=preflight.report_state,
                )
            payload = {
                "producer_attempted_calls": producer_attempted_calls,
                "reviewer_attempted_calls": reviewer_attempted_calls,
                "attempted_calls": sum(receipt.call_number > 0 for receipt in all_attempts),
                "not_measured": sum(receipt.status == "not_measured" for receipt in durable_receipts.values()),
                "run_id": preflight.identity.run_id,
            }
        else:
            payload = {
                "model_availability": preflight.model_availability,
                "repository_head": preflight.identity.repository_head,
                "run_id": preflight.identity.run_id,
            }
    except LiveMatrixError as exc:
        print(json.dumps({"error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 1
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
