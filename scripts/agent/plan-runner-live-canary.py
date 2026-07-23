#!/usr/bin/env python
"""Disposable live canaries for the two provider-specific plan runners.

Only bounded, normalized probe results are written to stdout. Provider prompts,
native streams, credentials, and stderr are deliberately never returned.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import sysconfig
import tempfile
import time
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
RESULT_LIMIT = 2_048
STREAM_LIMIT = 1_048_576
VERSION_LIMIT = 160
COMMAND_DEADLINE_SECONDS = 600.0
RUNNER_DEADLINE_SECONDS = 7_200.0
TERM_GRACE_SECONDS = 1.0
GIT_ENV = {
    "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+00:00",
    "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+00:00",
}
AUTH_CODES = frozenset(
    {
        "authentication_error",
        "auth_error",
        "invalid_api_key",
        "login_required",
        "not_authenticated",
        "unauthorized",
    }
)
AUTH_TEXT = re.compile(
    r"(?:not[ -]?logged[ -]?in|authentication|authenticate|unauthorized|"
    r"invalid[ _-]?(?:api[ _-]?)?key|login required|credential)",
    re.IGNORECASE,
)
FULL_HEAD = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
CANARY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "nonce": {
            "type": "string",
            "minLength": 32,
            "maxLength": 64,
            "pattern": "^[a-f0-9]+$",
        }
    },
    "required": ["nonce"],
}


class CanaryError(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


class InvocationError(ValueError):
    pass


class ContractArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise InvocationError(message)


@dataclasses.dataclass(frozen=True)
class RuntimeIdentity:
    executable: str
    version: str
    architecture: str
    uv_version: str


@dataclasses.dataclass(frozen=True)
class CommandResult:
    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool


@dataclasses.dataclass(frozen=True)
class ParsedStream:
    status: str
    reason_code: str | None
    session_id: str | None
    structured: Mapping[str, Any] | None
    normalized: Mapping[str, Any]


@dataclasses.dataclass(frozen=True)
class SessionEvidence:
    initial_session_id: str | None
    resumed_session_id: str | None
    initial_nonce: str | None
    resumed_nonce: str | None
    head_before: str
    head_after: str
    porcelain: str


def _bounded_text(value: object, limit: int) -> str:
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    return text[:limit]


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def require_runtime() -> RuntimeIdentity:
    if sys.implementation.name != "cpython" or not (
        (3, 13) <= sys.version_info[:2] < (3, 14)
    ):
        raise CanaryError("runtime_incompatible")
    if bool(sysconfig.get_config_var("Py_GIL_DISABLED")):
        raise CanaryError("runtime_incompatible")
    is_gil_enabled = getattr(sys, "_is_gil_enabled", None)
    if callable(is_gil_enabled) and not is_gil_enabled():
        raise CanaryError("runtime_incompatible")
    executable = Path(sys.executable)
    try:
        resolved = executable.resolve(strict=True)
    except OSError as error:
        raise CanaryError("runtime_missing") from error
    if not resolved.is_file():
        raise CanaryError("runtime_missing")
    try:
        uv = subprocess.run(
            ["uv", "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise CanaryError("runtime_missing") from error
    if uv.returncode != 0 or not uv.stdout.strip():
        raise CanaryError("runtime_missing")
    return RuntimeIdentity(
        executable=str(resolved),
        version=platform.python_version(),
        architecture=platform.machine(),
        uv_version=_bounded_text(uv.stdout, VERSION_LIMIT),
    )


def codex_session_argv(
    *,
    root: Path,
    schema_path: Path,
    output_path: Path,
    session_id: str | None,
) -> list[str]:
    argv = [
        "codex",
        "exec",
        "--ignore-user-config",
        "--json",
        "--output-schema",
        str(schema_path),
        "--output-last-message",
        str(output_path),
        "--cd",
        str(root),
        "--sandbox",
        "read-only",
    ]
    if session_id is None:
        argv.append("-")
    else:
        uuid.UUID(session_id)
        argv.extend(("resume", session_id, "-"))
    return argv


def codex_probe_paths(root: Path) -> tuple[Path, Path]:
    return root.parent / "nonce.schema.json", root.parent / "nonce-result.json"


def claude_session_argv(
    *, prompt: str, session_id: str, resume: bool
) -> list[str]:
    canonical = str(uuid.UUID(session_id))
    argv = [
        "claude",
        "-p",
        prompt,
        "--output-format",
        "stream-json",
        "--verbose",
        "--json-schema",
        json.dumps(CANARY_SCHEMA, sort_keys=True, separators=(",", ":")),
        "--permission-mode",
        "plan",
        "--disallowedTools",
        "Bash",
        "Edit",
        "Write",
        "NotebookEdit",
    ]
    if resume:
        argv.extend(("--resume", canonical))
    else:
        argv.extend(("--session-id", canonical))
    return argv


def run_bounded(
    argv: Sequence[str],
    *,
    cwd: Path,
    timeout: float,
    input_text: str | None = None,
    env: Mapping[str, str] | None = None,
) -> CommandResult:
    process = subprocess.Popen(
        list(argv),
        cwd=str(cwd),
        env=None if env is None else dict(env),
        stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        shell=False,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(input=input_text, timeout=timeout)
        timed_out = False
    except subprocess.TimeoutExpired:
        timed_out = True
        os.killpg(process.pid, signal.SIGTERM)
        try:
            stdout, stderr = process.communicate(timeout=TERM_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate()
    return CommandResult(
        process.returncode,
        (stdout or "")[-STREAM_LIMIT:],
        (stderr or "")[-STREAM_LIMIT:],
        timed_out,
    )


def _json_lines(raw: str) -> tuple[list[Mapping[str, Any]], bool]:
    if len(raw.encode("utf-8", errors="replace")) > STREAM_LIMIT:
        return [], False
    events: list[Mapping[str, Any]] = []
    try:
        for line in raw.splitlines():
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, Mapping):
                return [], False
            events.append(value)
    except (UnicodeError, json.JSONDecodeError):
        return [], False
    return events, bool(events)


def _event_error_code(event: Mapping[str, Any]) -> str | None:
    candidates: list[object] = [
        event.get("code"),
        event.get("error_code"),
        event.get("api_error_status"),
    ]
    error = event.get("error")
    if isinstance(error, Mapping):
        candidates.extend((error.get("code"), error.get("type")))
    for candidate in candidates:
        if isinstance(candidate, str) and candidate:
            return re.sub(r"[^a-z0-9]+", "_", candidate.lower()).strip("_")[:80]
    return None


def parse_codex_stream(raw: str) -> ParsedStream:
    events, valid = _json_lines(raw)
    if not valid:
        return ParsedStream(
            "failed",
            "stream_malformed",
            None,
            None,
            {"status": "failed", "reason_code": "stream_malformed"},
        )
    session_id: str | None = None
    error_codes: list[str] = []
    malformed = False
    for event in events:
        candidate = None
        if event.get("type") in {"thread.started", "session.started"}:
            candidate = event.get("thread_id") or event.get("session_id")
        if candidate is not None:
            try:
                normalized = str(uuid.UUID(str(candidate)))
            except ValueError:
                malformed = True
                continue
            if session_id is not None and session_id != normalized:
                malformed = True
            session_id = normalized
        code = _event_error_code(event)
        if code:
            error_codes.append(code)
    if malformed:
        return ParsedStream(
            "failed",
            "session_discontinuous",
            session_id,
            None,
            {"status": "failed", "reason_code": "session_discontinuous"},
        )
    auth = next((code for code in error_codes if code in AUTH_CODES), None)
    if auth is not None:
        return ParsedStream(
            "blocked",
            "provider_auth_blocked",
            session_id,
            None,
            {"status": "blocked", "reason_code": "provider_auth_blocked"},
        )
    return ParsedStream(
        "ok",
        None,
        session_id,
        None,
        {"status": "ok", "session_captured": session_id is not None},
    )


def parse_claude_stream(raw: str, *, expected_session_id: str) -> ParsedStream:
    try:
        expected = str(uuid.UUID(expected_session_id))
    except ValueError:
        expected = ""
    events, valid = _json_lines(raw)
    if not valid:
        return ParsedStream(
            "failed",
            "stream_malformed",
            None,
            None,
            {"status": "failed", "reason_code": "stream_malformed"},
        )
    session_id: str | None = None
    structured: Mapping[str, Any] | None = None
    error_codes: list[str] = []
    malformed = False
    for event in events:
        if event.get("type") == "system" and event.get("subtype") == "init":
            candidate = event.get("session_id")
            try:
                normalized = str(uuid.UUID(str(candidate)))
            except ValueError:
                malformed = True
                continue
            if normalized != expected or (
                session_id is not None and session_id != normalized
            ):
                malformed = True
            session_id = normalized
        if event.get("type") == "result":
            candidate = event.get("session_id")
            if candidate is not None:
                try:
                    if str(uuid.UUID(str(candidate))) != expected:
                        malformed = True
                except ValueError:
                    malformed = True
            value = event.get("structured_output")
            if isinstance(value, Mapping):
                structured = dict(value)
        code = _event_error_code(event)
        if code:
            error_codes.append(code)
    if malformed:
        return ParsedStream(
            "failed",
            "session_discontinuous",
            session_id,
            None,
            {"status": "failed", "reason_code": "session_discontinuous"},
        )
    auth = next((code for code in error_codes if code in AUTH_CODES), None)
    if auth is not None:
        return ParsedStream(
            "blocked",
            "provider_auth_blocked",
            session_id,
            None,
            {"status": "blocked", "reason_code": "provider_auth_blocked"},
        )
    return ParsedStream(
        "ok",
        None,
        session_id,
        structured,
        {
            "status": "ok",
            "session_captured": session_id is not None,
            "structured_result": structured is not None,
        },
    )


def classify_provider_result(
    command: CommandResult, parsed: ParsedStream
) -> tuple[str, str | None]:
    if command.timed_out:
        return "failed", "provider_deadline"
    if parsed.status == "blocked":
        return "blocked", parsed.reason_code
    if parsed.status == "failed":
        return "failed", parsed.reason_code
    if command.returncode != 0:
        if AUTH_TEXT.search(command.stderr):
            return "blocked", "provider_auth_blocked"
        return "failed", "provider_command_failed"
    if parsed.session_id is None:
        return "failed", "session_missing"
    return "passed", None


def validate_session_evidence(
    evidence: SessionEvidence,
) -> tuple[bool, str | None]:
    if (
        evidence.initial_session_id is None
        or evidence.resumed_session_id is None
        or evidence.initial_session_id != evidence.resumed_session_id
    ):
        return False, "session_discontinuous"
    if (
        evidence.initial_nonce is None
        or evidence.resumed_nonce is None
        or evidence.initial_nonce != evidence.resumed_nonce
    ):
        return False, "nonce_discontinuous"
    if evidence.head_before != evidence.head_after:
        return False, "repository_head_changed"
    if evidence.porcelain:
        return False, "repository_dirty"
    return True, None


def normalized_result(
    *,
    provider: str,
    mode: str,
    status: str,
    provider_version: str | None,
    session_action: str,
    final_head: str | None,
    elapsed: float,
    reason_code: str | None = None,
) -> dict[str, object]:
    result: dict[str, object] = {
        "provider": provider,
        "mode": mode,
        "status": status,
        "provider_version": (
            _bounded_text(provider_version, VERSION_LIMIT)
            if provider_version
            else None
        ),
        "session_action": _bounded_text(session_action, 80),
        "final_head": final_head if final_head and FULL_HEAD.fullmatch(final_head) else None,
        "elapsed_seconds": round(max(0.0, elapsed), 3),
    }
    if reason_code is not None:
        result["reason_code"] = _bounded_text(reason_code, 80)
    if len(json.dumps(result, sort_keys=True)) > RESULT_LIMIT:
        raise CanaryError("normalized_result_too_large")
    return result


def _git(root: Path, *arguments: str, env: Mapping[str, str] | None = None) -> str:
    merged = dict(os.environ if env is None else env)
    merged.update(GIT_ENV)
    result = subprocess.run(
        ["git", *arguments],
        cwd=root,
        env=merged,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise CanaryError("git_command_failed")
    return result.stdout.strip()


def _create_repository(root: Path) -> str:
    root.mkdir(parents=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.name", "Plan Runner Canary")
    _git(root, "config", "user.email", "plan-runner-canary@example.invalid")
    (root / "seed.txt").write_text("plan runner live canary\n", encoding="utf-8")
    _git(root, "add", "seed.txt")
    _git(root, "commit", "-q", "-m", "test: seed canary repository")
    return _git(root, "rev-parse", "HEAD")


def _provider_version(provider: str, root: Path) -> tuple[str | None, str | None]:
    executable = shutil.which(provider)
    if executable is None:
        return None, "provider_unavailable"
    command = run_bounded([executable, "--version"], cwd=root, timeout=20)
    if command.timed_out or command.returncode != 0:
        return None, "provider_unavailable"
    version = (command.stdout or command.stderr).strip()
    if not version:
        return None, "provider_unavailable"
    return _bounded_text(version, VERSION_LIMIT), None


def _read_nonce(path: Path) -> str | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    nonce = value.get("nonce") if isinstance(value, Mapping) else None
    return nonce if isinstance(nonce, str) else None


def _probe_codex_session(root: Path) -> tuple[str, str | None, str]:
    schema, output = codex_probe_paths(root)
    schema.write_bytes(_canonical_json(CANARY_SCHEMA))
    head_before = _git(root, "rev-parse", "HEAD")
    nonce = uuid.uuid4().hex
    prompt = (
        "Return only the requested structured object with nonce "
        f"{nonce}. Remember it for the next turn. Do not modify files or Git."
    )
    first = run_bounded(
        codex_session_argv(
            root=root,
            schema_path=schema,
            output_path=output,
            session_id=None,
        ),
        cwd=root,
        timeout=COMMAND_DEADLINE_SECONDS,
        input_text=prompt,
    )
    parsed_first = parse_codex_stream(first.stdout)
    status, reason = classify_provider_result(first, parsed_first)
    if status != "passed":
        return status, reason, "fresh_session"
    first_nonce = _read_nonce(output)
    session_id = parsed_first.session_id
    if session_id is None:
        return "failed", "session_missing", "fresh_session"
    output.unlink(missing_ok=True)
    second_prompt = (
        "Return only the requested structured object containing exactly the "
        "nonce remembered from the previous turn. Do not modify files or Git."
    )
    second = run_bounded(
        codex_session_argv(
            root=root,
            schema_path=schema,
            output_path=output,
            session_id=session_id,
        ),
        cwd=root,
        timeout=COMMAND_DEADLINE_SECONDS,
        input_text=second_prompt,
    )
    parsed_second = parse_codex_stream(second.stdout)
    second_status, second_reason = classify_provider_result(second, parsed_second)
    if second_status != "passed":
        return second_status, second_reason, "resume_explicit"
    evidence = SessionEvidence(
        session_id,
        parsed_second.session_id,
        first_nonce,
        _read_nonce(output),
        head_before,
        _git(root, "rev-parse", "HEAD"),
        _git(root, "status", "--porcelain=v1"),
    )
    valid, reason = validate_session_evidence(evidence)
    return ("passed", None, "fresh_then_resume") if valid else (
        "failed",
        reason,
        "fresh_then_resume",
    )


def _probe_claude_session(root: Path) -> tuple[str, str | None, str]:
    head_before = _git(root, "rev-parse", "HEAD")
    nonce = uuid.uuid4().hex
    session_id = str(uuid.uuid4())
    prompt = (
        "Return only the requested structured object with nonce "
        f"{nonce}. Remember it for the next turn. Do not modify files or Git."
    )
    first = run_bounded(
        claude_session_argv(
            prompt=prompt, session_id=session_id, resume=False
        ),
        cwd=root,
        timeout=COMMAND_DEADLINE_SECONDS,
    )
    parsed_first = parse_claude_stream(
        first.stdout, expected_session_id=session_id
    )
    status, reason = classify_provider_result(first, parsed_first)
    if status != "passed":
        return status, reason, "fresh_session"
    first_nonce = (
        parsed_first.structured.get("nonce")
        if isinstance(parsed_first.structured, Mapping)
        else None
    )
    second_prompt = (
        "Return only the requested structured object containing exactly the "
        "nonce remembered from the previous turn. Do not modify files or Git."
    )
    second = run_bounded(
        claude_session_argv(
            prompt=second_prompt, session_id=session_id, resume=True
        ),
        cwd=root,
        timeout=COMMAND_DEADLINE_SECONDS,
    )
    parsed_second = parse_claude_stream(
        second.stdout, expected_session_id=session_id
    )
    second_status, second_reason = classify_provider_result(second, parsed_second)
    if second_status != "passed":
        return second_status, second_reason, "resume_explicit"
    resumed_nonce = (
        parsed_second.structured.get("nonce")
        if isinstance(parsed_second.structured, Mapping)
        else None
    )
    evidence = SessionEvidence(
        parsed_first.session_id,
        parsed_second.session_id,
        first_nonce if isinstance(first_nonce, str) else None,
        resumed_nonce if isinstance(resumed_nonce, str) else None,
        head_before,
        _git(root, "rev-parse", "HEAD"),
        _git(root, "status", "--porcelain=v1"),
    )
    valid, reason = validate_session_evidence(evidence)
    return ("passed", None, "fresh_then_resume") if valid else (
        "failed",
        reason,
        "fresh_then_resume",
    )


def probe_session(provider: str) -> dict[str, object]:
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix=f"{provider}-session-canary-") as raw:
        root = Path(raw) / "repository"
        version, unavailable = _provider_version(provider, Path(raw))
        if unavailable:
            return normalized_result(
                provider=provider,
                mode="session",
                status="blocked",
                provider_version=None,
                session_action="not_started",
                final_head=None,
                elapsed=time.monotonic() - started,
                reason_code=unavailable,
            )
        try:
            _create_repository(root)
            if provider == "codex":
                status, reason, action = _probe_codex_session(root)
            else:
                status, reason, action = _probe_claude_session(root)
        except (CanaryError, OSError, ValueError) as error:
            status = "failed"
            reason = (
                error.reason_code
                if isinstance(error, CanaryError)
                else "session_probe_failed"
            )
            action = "not_completed"
        return normalized_result(
            provider=provider,
            mode="session",
            status=status,
            provider_version=version,
            session_action=action,
            final_head=None,
            elapsed=time.monotonic() - started,
            reason_code=reason,
        )


def _write_runner_documents(root: Path) -> tuple[list[Path], list[Path]]:
    docs = root / "immutable-inputs"
    docs.mkdir()
    specs = [docs / "01-product.md", docs / "02-verification.md"]
    plans = [docs / "01-alpha.md", docs / "02-beta.md"]
    specs[0].write_text(
        "# Canary product spec\n\n"
        "The repository exposes `alpha()` returning `alpha` and `beta()` "
        "returning `beta`. Preserve both behaviors once implemented.\n",
        encoding="utf-8",
    )
    specs[1].write_text(
        "# Canary verification spec\n\n"
        "Use only the Python standard library. The final required command is "
        f"`{Path(sys.executable).resolve()} -m unittest -v`. Commit every plan. "
        "Never merge, push, deploy, or modify source repository refs.\n",
        encoding="utf-8",
    )
    plans[0].write_text(
        "# Plan 1: alpha\n\n"
        "Implement only this plan. Create `behaviors.py` with `alpha()` "
        "returning `alpha`. Create deterministic unittest coverage for alpha. "
        "Run the focused test, commit the implementation, and report every task "
        "done through the runner protocol. Do not implement beta yet.\n",
        encoding="utf-8",
    )
    plans[1].write_text(
        "# Plan 2: beta\n\n"
        "Implement only this plan after preserving alpha. Add `beta()` returning "
        "`beta` and deterministic unittest coverage. Run all unittests, commit "
        "the implementation, and report every task done. For finalization declare "
        f"`{Path(sys.executable).resolve()} -m unittest -v` as the complete "
        "required verification set and perform the whole-branch review.\n",
        encoding="utf-8",
    )
    for path in (*specs, *plans):
        path.chmod(0o400)
    return specs, plans


def _artifact(run_root: Path, state: Mapping[str, Any], kind: str) -> Mapping[str, Any]:
    refs = [
        ref
        for ref in state.get("artifact_refs", [])
        if isinstance(ref, Mapping) and ref.get("kind") == kind
    ]
    if kind in {"verification_receipt"}:
        raise CanaryError("artifact_cardinality_ambiguous")
    if len(refs) != 1:
        raise CanaryError(f"{kind}_missing")
    ref = refs[0]
    relative = ref.get("relative_path")
    digest = ref.get("digest")
    if not isinstance(relative, str) or not isinstance(digest, str):
        raise CanaryError("artifact_reference_invalid")
    path = run_root / relative
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise CanaryError("artifact_missing") from error
    if hashlib.sha256(raw).hexdigest() != digest:
        raise CanaryError("artifact_digest_mismatch")
    value = json.loads(raw)
    if not isinstance(value, Mapping):
        raise CanaryError("artifact_invalid")
    return value


def validate_runner_state(
    state: Mapping[str, Any], *, observed_head: str, porcelain: str
) -> tuple[bool, str | None, str | None]:
    if state.get("status") != "ready_for_integration":
        return False, "run_not_ready", None
    if state.get("integration") != "not_observed":
        return False, "integration_observed", None
    plans = state.get("plans")
    if not isinstance(plans, list) or len(plans) != 2 or any(
        not isinstance(plan, Mapping) or plan.get("status") != "implemented"
        for plan in plans
    ):
        return False, "plans_not_implemented", None
    sessions = state.get("sessions")
    if not isinstance(sessions, list):
        return False, "sessions_missing", None
    implementation: dict[int, str] = {}
    final_sessions: list[str] = []
    for session in sessions:
        if not isinstance(session, Mapping):
            continue
        identifier = session.get("session_id")
        if not isinstance(identifier, str) or not identifier:
            continue
        if session.get("mode") == "implementation" and session.get(
            "plan_index"
        ) in (0, 1):
            implementation[int(session["plan_index"])] = identifier
        if session.get("mode") == "finalization":
            final_sessions.append(identifier)
    if set(implementation) != {0, 1}:
        return False, "plan_sessions_missing", None
    if len(set(implementation.values())) != 2:
        return False, "plan_session_not_distinct", None
    if not final_sessions or final_sessions[-1] in set(implementation.values()):
        return False, "final_session_not_separate", None
    finalization = state.get("finalization")
    if not isinstance(finalization, Mapping):
        return False, "finalization_missing", None
    candidate = finalization.get("candidate_head")
    if (
        not isinstance(candidate, str)
        or FULL_HEAD.fullmatch(candidate) is None
        or candidate != observed_head
    ):
        return False, "final_head_mismatch", None
    review_head = finalization.get("review_head", candidate)
    if review_head != candidate:
        return False, "review_head_mismatch", None
    commands = finalization.get("verification_commands")
    if commands is not None:
        if not isinstance(commands, list) or not commands or any(
            not isinstance(item, Mapping)
            or item.get("status") != "passed"
            or item.get("candidate_head") != candidate
            for item in commands
        ):
            return False, "verification_not_passed", None
    review = finalization.get("review")
    if review is not None and (
        not isinstance(review, Mapping)
        or review.get("status") not in {"approved", "reviewed"}
        or review.get("candidate_head") != candidate
    ):
        return False, "review_not_approved", None
    if porcelain:
        return False, "runner_worktree_dirty", None
    return True, None, candidate


def _validate_runner_artifacts(
    state: Mapping[str, Any], run_root: Path, candidate: str
) -> tuple[bool, str | None]:
    try:
        final_set = _artifact(run_root, state, "final_verification_set")
        review = _artifact(run_root, state, "final_review_receipt")
        handoff = _artifact(run_root, state, "branch_handoff")
        refs = [
            ref
            for ref in state.get("artifact_refs", [])
            if isinstance(ref, Mapping) and ref.get("kind") == "verification_receipt"
        ]
        commands = final_set.get("commands")
        if (
            final_set.get("candidate_head") != candidate
            or not isinstance(commands, list)
            or not commands
            or len(refs) != len(commands)
        ):
            return False, "verification_set_invalid"
        for ref in refs:
            relative = ref.get("relative_path")
            digest = ref.get("digest")
            if not isinstance(relative, str) or not isinstance(digest, str):
                return False, "verification_receipt_invalid"
            raw = (run_root / relative).read_bytes()
            if hashlib.sha256(raw).hexdigest() != digest:
                return False, "verification_receipt_invalid"
            receipt = json.loads(raw)
            if not valid_receipt_payload(receipt, candidate):
                return False, "verification_receipt_invalid"
        if (
            review.get("status") != "reviewed"
            or review.get("candidate_head") != candidate
            or review.get("review_head") != candidate
            or review.get("open_findings") != []
            or review.get("open_obligation_ids") != []
        ):
            return False, "review_not_approved"
        if (
            handoff.get("status") != "ready_for_integration"
            or handoff.get("candidate_head") != candidate
            or handoff.get("review_head") != candidate
            or handoff.get("integration") != "not_observed"
        ):
            return False, "handoff_invalid"
    except (CanaryError, OSError, ValueError, json.JSONDecodeError) as error:
        return False, (
            error.reason_code
            if isinstance(error, CanaryError)
            else "final_evidence_invalid"
        )
    return True, None


def valid_receipt_payload(value: object, candidate: str) -> bool:
    if not isinstance(value, Mapping):
        return False
    identity = value.get("identity")
    return (
        isinstance(identity, Mapping)
        and identity.get("candidate_head") == candidate
        and value.get("outcome") == "success"
        and value.get("exit_code") == 0
    )


def _runner_environment(provider: str, home: Path) -> dict[str, str]:
    env = dict(os.environ)
    operator_home = Path.home()
    env["HOME"] = str(home)
    if provider == "codex":
        env.setdefault("CODEX_HOME", str(operator_home / ".codex"))
    else:
        env.setdefault("CLAUDE_CONFIG_DIR", str(operator_home / ".claude"))
    env.pop("KWS_PLAN_RUNNER_HELPER_SOCKET", None)
    env.pop("KWS_PLAN_RUNNER_HELPER_NONCE", None)
    return env


def probe_runner(provider: str) -> dict[str, object]:
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix=f"{provider}-runner-canary-") as raw:
        root = Path(raw)
        version, unavailable = _provider_version(provider, root)
        if unavailable:
            return normalized_result(
                provider=provider,
                mode="runner",
                status="blocked",
                provider_version=None,
                session_action="not_started",
                final_head=None,
                elapsed=time.monotonic() - started,
                reason_code=unavailable,
            )
        workspace = root / "source"
        home = root / "operator-home"
        home.mkdir(mode=0o700)
        try:
            _create_repository(workspace)
            specs, plans = _write_runner_documents(root)
            runner = (
                REPO_ROOT
                / f"skills/kws-{provider}-plan-runner/scripts/runner"
            )
            argv = [str(runner), "run"]
            for spec in specs:
                argv.extend(("--spec", str(spec)))
            for plan in plans:
                argv.extend(("--plan", str(plan)))
            argv.extend(("--workspace", str(workspace)))
            command = run_bounded(
                argv,
                cwd=root,
                timeout=RUNNER_DEADLINE_SECONDS,
                env=_runner_environment(provider, home),
            )
            if command.timed_out:
                raise CanaryError("runner_deadline")
            summaries = [
                value
                for line in command.stdout.splitlines()
                if line.strip()
                for value in [json.loads(line)]
                if isinstance(value, Mapping)
            ]
            summary = summaries[-1] if summaries else None
            if (
                command.returncode != 0
                or not isinstance(summary, Mapping)
                or summary.get("status") != "ready_for_integration"
                or not isinstance(summary.get("run_id"), str)
            ):
                if AUTH_TEXT.search(command.stderr):
                    return normalized_result(
                        provider=provider,
                        mode="runner",
                        status="blocked",
                        provider_version=version,
                        session_action="not_completed",
                        final_head=None,
                        elapsed=time.monotonic() - started,
                        reason_code="provider_auth_blocked",
                    )
                raise CanaryError("runner_not_ready")
            run_id = summary["run_id"]
            state_root = home / f".{provider}" / "plan-runner" / run_id
            state = json.loads((state_root / "state.json").read_text(encoding="utf-8"))
            worktree = Path(state["repository"]["worktree"])
            observed = _git(worktree, "rev-parse", "HEAD")
            porcelain = _git(worktree, "status", "--porcelain=v1")
            valid, reason, candidate = validate_runner_state(
                state, observed_head=observed, porcelain=porcelain
            )
            if not valid or candidate is None:
                raise CanaryError(reason or "runner_state_invalid")
            valid, reason = _validate_runner_artifacts(state, state_root, candidate)
            if not valid:
                raise CanaryError(reason or "final_evidence_invalid")
            before = hashlib.sha256((state_root / "state.json").read_bytes()).hexdigest()
            inspect = run_bounded(
                [str(runner), "inspect", "--run-id", run_id],
                cwd=root,
                timeout=60,
                env=_runner_environment(provider, home),
            )
            after = hashlib.sha256((state_root / "state.json").read_bytes()).hexdigest()
            if inspect.returncode != 0 or before != after:
                raise CanaryError("inspect_mutated_state")
            inspect_lines = [
                json.loads(line)
                for line in inspect.stdout.splitlines()
                if line.strip()
            ]
            if (
                not inspect_lines
                or inspect_lines[-1].get("status") != "ready_for_integration"
                or inspect_lines[-1].get("integration") != "not_observed"
            ):
                raise CanaryError("inspect_facts_mismatch")
            return normalized_result(
                provider=provider,
                mode="runner",
                status="passed",
                provider_version=version,
                session_action="distinct_plan_and_final_sessions",
                final_head=candidate,
                elapsed=time.monotonic() - started,
            )
        except (CanaryError, OSError, ValueError, KeyError, json.JSONDecodeError) as error:
            reason = (
                error.reason_code
                if isinstance(error, CanaryError)
                else "runner_probe_failed"
            )
            return normalized_result(
                provider=provider,
                mode="runner",
                status="failed",
                provider_version=version,
                session_action="not_completed",
                final_head=None,
                elapsed=time.monotonic() - started,
                reason_code=reason,
            )


def _parser() -> argparse.ArgumentParser:
    parser = ContractArgumentParser(prog="plan-runner-live-canary")
    parser.add_argument(
        "--provider", choices=("codex", "claude", "all"), required=True
    )
    parser.add_argument("--mode", choices=("session", "runner", "all"), required=True)
    return parser


def _requested(value: str, choices: tuple[str, str]) -> tuple[str, ...]:
    return choices if value == "all" else (value,)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        arguments = _parser().parse_args(argv)
    except InvocationError:
        print(
            json.dumps(
                normalized_result(
                    provider="invalid",
                    mode="invalid",
                    status="failed",
                    provider_version=None,
                    session_action="not_started",
                    final_head=None,
                    elapsed=0,
                    reason_code="invalid_invocation",
                ),
                sort_keys=True,
            )
        )
        return 64
    try:
        require_runtime()
    except CanaryError as error:
        for provider in _requested(arguments.provider, ("codex", "claude")):
            for mode in _requested(arguments.mode, ("session", "runner")):
                print(
                    json.dumps(
                        normalized_result(
                            provider=provider,
                            mode=mode,
                            status="blocked",
                            provider_version=None,
                            session_action="not_started",
                            final_head=None,
                            elapsed=0,
                            reason_code=error.reason_code,
                        ),
                        sort_keys=True,
                    )
                )
        return 3
    results: list[Mapping[str, object]] = []
    for provider in _requested(arguments.provider, ("codex", "claude")):
        for mode in _requested(arguments.mode, ("session", "runner")):
            result = probe_session(provider) if mode == "session" else probe_runner(provider)
            results.append(result)
            print(json.dumps(result, sort_keys=True))
    if any(result["status"] == "failed" for result in results):
        return 4
    if any(result["status"] == "blocked" for result in results):
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
