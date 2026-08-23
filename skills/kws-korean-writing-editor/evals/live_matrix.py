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
from collections.abc import Sequence
from dataclasses import dataclass
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
RECEIPT_DIRECTORY_NAME = "receipts"
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
        values: dict[str, Any] = {
            "identity": identity if identity is not None else RunIdentity.for_test(),
            "call_id": call_id,
            "call_number": 1,
            "host": "test-host",
            "requested_model": "test-model",
            "reported_model": "test-model",
            "case_id": "test-case",
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


def _git_status_is_clean(repository_root: pathlib.Path) -> bool:
    capture = run_command(
        ("git", "status", "--porcelain=v1", "-z", "--untracked-files=all"),
        cwd=repository_root,
        timeout=30,
    )
    if capture.returncode != 0:
        raise LiveMatrixError("git status preflight failed")
    return capture.stdout == b""


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
    if not _git_status_is_clean(repo_root):
        raise LiveMatrixError("relevant checkout is not clean")
    branch = _git_value(repo_root, "branch", "--show-current")
    head = _git_value(repo_root, "rev-parse", "HEAD")
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
    call: PlannedCall, producer: Producer, identity: RunIdentity, reason: str
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
) -> CallReceipt:
    return CallReceipt(
        identity=identity,
        call_id=call.call_id,
        call_number=call_number,
        host=producer.host,
        requested_model=producer.requested_model,
        reported_model=None,
        case_id=call.case_id,
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
        )
    findings = evaluate_response(case, response)
    return CallReceipt(
        identity=preflight.identity,
        call_id=call.call_id,
        call_number=call_number,
        host=producer.host,
        requested_model=producer.requested_model,
        reported_model=reported_model,
        case_id=call.case_id,
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
        response_sha256=hashlib.sha256(response.encode("utf-8")).hexdigest(),
        status=case_status(case, findings),
        findings=findings,
        raw_paths=raw_paths,
    )


def validate_dispatch_identity(preflight: PreflightResult) -> None:
    """Fail closed if the checked checkout or manifests drift before dispatch."""
    if not _git_status_is_clean(preflight.repository_root):
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
                    call, producer, preflight.identity, "requested Cursor model is unavailable"
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
        )
        if args.execute:
            cases = load_live_cases(source_root / "evals" / "live_cases.json")
            receipts = dispatch_calls(
                preflight,
                build_producer_plan(cases, build_producers()),
                cases,
                jobs=args.jobs,
                max_calls=max_calls,
            )
            payload = {
                "attempted_calls": sum(receipt.call_number > 0 for receipt in receipts),
                "not_measured": sum(receipt.status == "not_measured" for receipt in receipts),
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
