#!/usr/bin/env python3
"""Synthetic live-case manifest and provider-free call-plan contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import subprocess
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="print the provider-free call budget")
    args = parser.parse_args(argv)
    if not args.dry_run:
        parser.error("only --dry-run is available in the matrix contract")

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
        "approved_total_ceiling": 160,
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
