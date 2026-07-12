"""Normalize Codex command items into fail-closed method evidence."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from .task_contracts import TASK_TYPES


class MethodEvidenceError(ValueError):
    pass


MAX_COMMAND_CHARS = 2048
MAX_OUTPUT_CHARS = 16384
_HOME_PATH_RE = re.compile(r"/(?:Users|home)/[^\s'\"]+(?:/[^\s'\"]*)?")
_HIDDEN_PATH_RE = re.compile(r"[^\s'\"]*(?:\.superpowers|hidden[-_]?oracle)[^\s'\"]*", re.I)
_SECRET_RES = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{6,}\b"),
    re.compile(r"\b(?:ghp_|github_pat_|glpat-|xox[baprs]-)[A-Za-z0-9_-]{8,}\b", re.I),
    re.compile(r"\bAKIA[A-Z0-9]{12,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.I),
    re.compile(r"\b(?:api[_-]?key|access[_-]?token|password)\s*[=:]\s*[^\s'\"]+", re.I),
)


@dataclass(frozen=True)
class CommandObservation:
    command: str
    status: str
    exit_code: int | None
    output_sha256: str
    sequence: int
    before_first_mutation: bool


@dataclass(frozen=True)
class MethodEvidence:
    method: str
    red: CommandObservation | None
    green: CommandObservation | None
    observations_sha256: str


def _sanitize(value: str, *, limit: int) -> str:
    text = value.replace(str(Path.home()), "<private-path>")
    text = _HOME_PATH_RE.sub("<private-path>", text)
    text = _HIDDEN_PATH_RE.sub("<hidden-path>", text)
    for pattern in _SECRET_RES:
        text = pattern.sub("<redacted>", text)
    return text[:limit]


def _output_digest(value: object) -> str:
    output = value if isinstance(value, str) else ""
    sanitized = _sanitize(output, limit=MAX_OUTPUT_CHARS)
    return hashlib.sha256(sanitized.encode("utf-8")).hexdigest()


def _exit_code(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def normalize_codex_items(events: Iterable[object]) -> tuple[CommandObservation, ...]:
    """Retain only completed command items and the first file-change boundary."""

    observations: list[CommandObservation] = []
    mutation_seen = False
    for sequence, event in enumerate(events):
        if not isinstance(event, dict) or event.get("type") != "item.completed":
            continue
        item = event.get("item")
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if item_type == "file_change":
            mutation_seen = True
            continue
        if item_type != "command_execution":
            continue
        raw_command = item.get("command")
        if not isinstance(raw_command, str) or not raw_command.strip():
            continue
        observations.append(
            CommandObservation(
                command=_sanitize(raw_command.strip(), limit=MAX_COMMAND_CHARS),
                status=str(item.get("status") or ""),
                exit_code=_exit_code(item.get("exit_code")),
                output_sha256=_output_digest(item.get("aggregated_output")),
                sequence=sequence,
                before_first_mutation=not mutation_seen,
            )
        )
    return tuple(observations)


def _canonical_observations(observations: tuple[CommandObservation, ...]) -> bytes:
    return (
        json.dumps(
            [asdict(item) for item in observations],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _validate_status(observation: CommandObservation) -> None:
    if observation.exit_code is None:
        raise MethodEvidenceError("command_exit_code_missing")
    expected = "completed" if observation.exit_code == 0 else "failed"
    if observation.status != expected:
        raise MethodEvidenceError("command_status_exit_contradiction")


def build_method_evidence(
    task_type: str, observations: Iterable[CommandObservation]
) -> MethodEvidence:
    """Select an observed same-command RED/GREEN pair without using prose."""

    if task_type not in TASK_TYPES:
        raise MethodEvidenceError("task_type_invalid")
    normalized = tuple(observations)
    for observation in normalized:
        if not isinstance(observation, CommandObservation):
            raise MethodEvidenceError("command_observation_invalid")
        _validate_status(observation)
    digest = hashlib.sha256(_canonical_observations(normalized)).hexdigest()
    if task_type != "tdd_implementation":
        return MethodEvidence(task_type, None, None, digest)

    red_candidates = [
        item
        for item in normalized
        if item.before_first_mutation and item.exit_code is not None and item.exit_code != 0
    ]
    if not red_candidates:
        raise MethodEvidenceError("tdd_red_missing_before_first_mutation")
    red = red_candidates[-1]
    green = next(
        (
            item
            for item in normalized
            if item.sequence > red.sequence
            and not item.before_first_mutation
            and item.command == red.command
            and item.exit_code == 0
        ),
        None,
    )
    if green is None:
        raise MethodEvidenceError("tdd_green_missing_after_mutation")
    return MethodEvidence(task_type, red, green, digest)


def method_evidence_payload(evidence: MethodEvidence) -> dict[str, object]:
    if not isinstance(evidence, MethodEvidence):
        raise MethodEvidenceError("method_evidence_invalid")
    return {
        "schema_version": "cpe.method-evidence.v4",
        "method": evidence.method,
        "red": asdict(evidence.red) if evidence.red is not None else None,
        "green": asdict(evidence.green) if evidence.green is not None else None,
        "observations_sha256": evidence.observations_sha256,
    }
