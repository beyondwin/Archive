"""Content-free coordination telemetry and SDD production inventory."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Literal, Mapping, Sequence

from .state import atomic_private_write


SUPPORTED_EVENTS = {
    "coordination.spawn", "coordination.wait", "coordination.list",
    "coordination.send", "coordination.followup", "coordination.finish",
    "coordination.compaction",
}
SUPPORTED_ROLES = {
    "implementer", "reviewer", "fixer", "final_reviewer", "coordinator",
}
CONTEXT_CLASSES = {
    "task_brief", "implementer_report", "review_package", "review_diff",
    "finding_delta", "progress_ledger", "spec_slice", "plan_slice",
    "other_bounded",
}
MAX_COORDINATION_EVENTS = 2048
MAX_COORDINATION_EVENT_BYTES = 16 * 1024
MAX_CONTEXT_REFS = 128
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_REASONS = {
    "source_requires_shared_context", "source_requires_cross_task_coordination",
    "source_requires_integrated_review",
}
_CHILD_FIELDS = {
    "schema_version", "event", "plan_index", "task_id", "role", "depth",
    "fork_turns", "duration_ms", "operation_count", "agent_id_digest",
    "source_context_refs", "context_ref_count", "context_ref_bytes",
    "context_measurement_kind", "context_classes", "source",
    "source_span_digest", "reason_code", "usage_scope", "usage_attribution",
    "usage_attribution_unavailable_reason",
}


@dataclass(frozen=True)
class ContextReferenceMetadata:
    artifact_class: str
    sha256: str
    byte_length: int


@dataclass(frozen=True)
class CoordinationObservation:
    event: str
    plan_index: int
    task_id: str | None
    role: str | None
    depth: int | None
    fork_turns: str | None
    duration_ms: int | None
    operation_count: int | None
    agent_id_digest: str | None
    context_ref_count: int | None
    context_ref_bytes: int | None
    context_measurement_kind: Literal[
        "declared_refs_not_provider_ingestion", "unavailable"
    ]
    context_classes: Mapping[str, int] | None
    context_refs: tuple[ContextReferenceMetadata, ...]
    usage_scope: Literal["controller_and_nested_agents_aggregate"]
    usage_attribution: Literal["parent_observed", "child_attested", "unavailable"]
    usage_attribution_unavailable_reason: str | None
    source: Literal["parent_observed", "child_attested"]
    full_context_exception_valid: bool | None = None
    data_quality_warnings: tuple[str, ...] = ()
    field_sources: Mapping[str, str] | None = None


def _bounded_int(value: object, *, maximum: int = (1 << 63) - 1) -> int | None:
    return (
        value if isinstance(value, int) and not isinstance(value, bool)
        and 0 <= value <= maximum else None
    )


def _optional_identifier(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise ValueError("coordination identifier is invalid")
    return value


def _digest_agent_id(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > 1024:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _safe_context_path(worktree: Path, raw_path: object) -> Path:
    if not isinstance(raw_path, str) or not raw_path or "\\" in raw_path:
        raise ValueError("coordination context path is invalid")
    relative = PurePosixPath(raw_path)
    if relative.is_absolute() or any(
        part in {"", ".", ".."} for part in relative.parts
    ):
        raise ValueError("coordination context path escapes worktree")
    root = worktree.resolve(strict=True)
    current = root
    for part in relative.parts:
        current = current / part
        try:
            metadata = current.lstat()
        except OSError as exc:
            raise ValueError("coordination context file is unavailable") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise ValueError("coordination context file is redirected")
    resolved = current.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("coordination context path escapes worktree") from exc
    if not resolved.is_file():
        raise ValueError("coordination context file is not regular")
    return resolved


def _read_context_metadata(
    reference: object, *, worktree: Path,
) -> ContextReferenceMetadata:
    if not isinstance(reference, dict) or set(reference) != {"class", "path", "sha256"}:
        raise ValueError("coordination context reference is invalid")
    artifact_class = reference["class"]
    expected = reference["sha256"]
    if artifact_class not in CONTEXT_CLASSES or not isinstance(expected, str) or not _DIGEST.fullmatch(expected):
        raise ValueError("coordination context reference is invalid")
    path = _safe_context_path(worktree, reference["path"])
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("coordination context file is not regular")
        digest = hashlib.sha256()
        observed = 0
        while True:
            chunk = os.read(descriptor, 65_536)
            if not chunk:
                break
            observed += len(chunk)
            digest.update(chunk)
    finally:
        os.close(descriptor)
    actual = digest.hexdigest()
    if actual != expected or observed != metadata.st_size:
        raise ValueError("coordination context reference digest changed")
    return ContextReferenceMetadata(str(artifact_class), actual, observed)


def _exception_matches(
    *, event: Mapping[str, object], exceptions: Sequence[Mapping[str, object]],
) -> bool:
    for exception in exceptions:
        if (
            exception.get("task_id") == event.get("task_id")
            and exception.get("role") == event.get("role")
            and exception.get("fork_turns") == "all"
            and exception.get("reason_code") == event.get("reason_code")
            and exception.get("source_text_sha256") == event.get("source_span_digest")
            and exception.get("reason_code") in _REASONS
        ):
            return True
    return False


def validate_child_coordination_event(
    event: Mapping[str, object], *, worktree: Path,
    coordination_exceptions: Sequence[Mapping[str, object]],
) -> CoordinationObservation:
    """Validate one child ledger event and immediately discard raw paths."""
    encoded = json.dumps(event, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_COORDINATION_EVENT_BYTES:
        raise ValueError("coordination event exceeds size limit")
    if set(event) - _CHILD_FIELDS or event.get("schema_version") != 1:
        raise ValueError("coordination event fields are invalid")
    event_name = event.get("event")
    if event_name not in SUPPORTED_EVENTS or event.get("source") != "child_attested":
        raise ValueError("coordination event source or type is invalid")
    plan_index = _bounded_int(event.get("plan_index"), maximum=1_000_000)
    if plan_index is None:
        raise ValueError("coordination plan index is invalid")
    task_id = _optional_identifier(event.get("task_id"))
    role = event.get("role")
    if role is not None and role not in SUPPORTED_ROLES:
        raise ValueError("coordination role is invalid")
    if event_name == "coordination.spawn" and role is None:
        raise ValueError("coordination spawn role is required")
    depth = _bounded_int(event.get("depth"), maximum=64)
    if event.get("depth") is not None and depth is None:
        raise ValueError("coordination depth is invalid")
    fork_turns = event.get("fork_turns")
    if fork_turns is None and event_name == "coordination.spawn" and role in {"implementer", "reviewer"}:
        fork_turns = "none"
    if fork_turns not in {None, "none", "all"}:
        raise ValueError("coordination fork scope is invalid")
    duration = _bounded_int(event.get("duration_ms"))
    operation_count = _bounded_int(event.get("operation_count"), maximum=1_000_000)
    if event.get("duration_ms") is not None and duration is None:
        raise ValueError("coordination duration is invalid")
    if event.get("operation_count") is not None and operation_count is None:
        raise ValueError("coordination operation count is invalid")

    raw_refs = event.get("source_context_refs")
    references: tuple[ContextReferenceMetadata, ...] = ()
    if raw_refs is not None:
        if not isinstance(raw_refs, list) or len(raw_refs) > MAX_CONTEXT_REFS:
            raise ValueError("coordination context references are invalid")
        references = tuple(
            _read_context_metadata(reference, worktree=worktree)
            for reference in raw_refs
        )
        count: int | None = len(references)
        byte_length: int | None = sum(item.byte_length for item in references)
        classes: dict[str, int] | None = {}
        for reference in references:
            classes[reference.artifact_class] = classes.get(reference.artifact_class, 0) + 1
        measurement: Literal["declared_refs_not_provider_ingestion", "unavailable"] = "declared_refs_not_provider_ingestion"
        declared = {
            "context_ref_count": count,
            "context_ref_bytes": byte_length,
            "context_measurement_kind": measurement,
            "context_classes": classes,
        }
        for name, actual in declared.items():
            if name in event and event[name] != actual:
                raise ValueError("coordination context declaration changed")
    else:
        if any(name in event for name in (
            "context_ref_count", "context_ref_bytes", "context_classes",
        )):
            raise ValueError("coordination context metadata lacks validated references")
        count = byte_length = None
        classes = None
        measurement = "unavailable"

    provided_agent_digest = event.get("agent_id_digest")
    if provided_agent_digest is not None and (
        not isinstance(provided_agent_digest, str)
        or not _DIGEST.fullmatch(provided_agent_digest)
    ):
        raise ValueError("coordination agent digest is invalid")
    if event.get("usage_scope", "controller_and_nested_agents_aggregate") != "controller_and_nested_agents_aggregate":
        raise ValueError("coordination usage scope is invalid")
    if event.get("usage_attribution", "unavailable") not in {"child_attested", "unavailable"}:
        raise ValueError("child coordination usage cannot be parent-observed")
    if (
        "usage_attribution_unavailable_reason" in event
        and event["usage_attribution_unavailable_reason"]
        != "provider_event_not_agent_scoped"
    ):
        raise ValueError("coordination usage unavailable reason is invalid")
    exception_valid = (
        _exception_matches(event=event, exceptions=coordination_exceptions)
        if fork_turns == "all" else None
    )
    return CoordinationObservation(
        event=str(event_name), plan_index=plan_index, task_id=task_id,
        role=str(role) if role is not None else None, depth=depth,
        fork_turns=str(fork_turns) if fork_turns is not None else None,
        duration_ms=duration, operation_count=operation_count,
        agent_id_digest=str(provided_agent_digest) if provided_agent_digest else None,
        context_ref_count=count, context_ref_bytes=byte_length,
        context_measurement_kind=measurement, context_classes=classes,
        context_refs=references,
        usage_scope="controller_and_nested_agents_aggregate",
        usage_attribution="unavailable",
        usage_attribution_unavailable_reason="provider_event_not_agent_scoped",
        source="child_attested", full_context_exception_valid=exception_valid,
        field_sources={"context": "child_attested", "usage": "unavailable"},
    )


def extract_coordination_observation(
    codex_event: Mapping[str, object], *, plan_index: int,
) -> CoordinationObservation | None:
    """Extract the stable provider fields; raw event content is not retained."""
    event_name = codex_event.get("type")
    if event_name not in SUPPORTED_EVENTS:
        return None
    if _bounded_int(plan_index, maximum=1_000_000) is None:
        raise ValueError("coordination plan index is invalid")
    try:
        task_id = _optional_identifier(codex_event.get("task_id"))
    except ValueError:
        task_id = None
    role_value = codex_event.get("role")
    role = str(role_value) if role_value in SUPPORTED_ROLES else None
    depth = _bounded_int(codex_event.get("depth"), maximum=64)
    fork_turns = codex_event.get("fork_turns")
    if fork_turns not in {"none", "all"}:
        fork_turns = "none" if event_name == "coordination.spawn" and role in {"implementer", "reviewer"} else None
    duration = _bounded_int(codex_event.get("duration_ms"))
    operation_count = _bounded_int(codex_event.get("operation_count"), maximum=1_000_000)
    agent_digest = _digest_agent_id(codex_event.get("agent_id"))
    agent_scoped = codex_event.get("usage_agent_scoped") is True and agent_digest is not None
    return CoordinationObservation(
        event=str(event_name), plan_index=plan_index, task_id=task_id,
        role=role, depth=depth, fork_turns=str(fork_turns) if fork_turns else None,
        duration_ms=duration, operation_count=operation_count,
        agent_id_digest=agent_digest if agent_scoped else None,
        context_ref_count=None, context_ref_bytes=None,
        context_measurement_kind="unavailable", context_classes=None,
        context_refs=(), usage_scope="controller_and_nested_agents_aggregate",
        usage_attribution="parent_observed" if agent_scoped else "unavailable",
        usage_attribution_unavailable_reason=(
            None if agent_scoped else "provider_event_not_agent_scoped"
        ),
        source="parent_observed",
        field_sources={"coordination": "parent_observed", "context": "unavailable"},
    )


def _identity(observation: CoordinationObservation) -> tuple[object, ...]:
    return (
        observation.event, observation.plan_index, observation.task_id,
        observation.role, observation.depth,
    )


def reconcile_coordination_observations(
    *, parent: Sequence[CoordinationObservation],
    child: Sequence[CoordinationObservation],
) -> tuple[CoordinationObservation, ...]:
    """Prefer parent-observed values and expose mismatches as data quality."""
    remaining = list(child)
    output: list[CoordinationObservation] = []
    for observed in parent:
        match_index = next((
            index for index, candidate in enumerate(remaining)
            if _identity(candidate) == _identity(observed)
        ), None)
        if match_index is None:
            output.append(observed)
            continue
        attested = remaining.pop(match_index)
        warnings = list(observed.data_quality_warnings)
        comparable = ("fork_turns", "duration_ms", "operation_count")
        if any(
            getattr(observed, name) is not None
            and getattr(attested, name) is not None
            and getattr(observed, name) != getattr(attested, name)
            for name in comparable
        ):
            warnings.append("parent_child_mismatch")
        output.append(replace(
            observed,
            context_ref_count=attested.context_ref_count,
            context_ref_bytes=attested.context_ref_bytes,
            context_measurement_kind=attested.context_measurement_kind,
            context_classes=attested.context_classes,
            context_refs=attested.context_refs,
            full_context_exception_valid=attested.full_context_exception_valid,
            data_quality_warnings=tuple(sorted(set(warnings))),
            field_sources={
                "coordination": "parent_observed",
                "context": "child_attested" if attested.context_ref_count is not None else "unavailable",
                "usage": observed.usage_attribution,
            },
        ))
    output.extend(remaining)
    return tuple(output)


def _artifact_class(path: Path) -> str:
    name = path.name.lower()
    if name == "progress.md" or "progress" in name:
        return "progress_ledger"
    if "brief" in name:
        return "task_brief"
    if "report" in name:
        return "implementer_report"
    if "finding" in name and "diff" in name:
        return "finding_delta"
    if "review" in name and path.suffix == ".diff":
        return "review_diff"
    if "review" in name:
        return "review_package"
    if "spec" in name:
        return "spec_slice"
    if "plan" in name:
        return "plan_slice"
    return "other_bounded"


def inventory_sdd_artifacts(
    worktree: Path, *, known_receipt_digests: Sequence[str] = (),
    max_files: int = 128, max_total_bytes: int = 8 * 1024 * 1024,
) -> dict[str, object]:
    """Measure produced files without reading their content or inferring tokens."""
    root = worktree.resolve(strict=True) / ".superpowers" / "sdd"
    if not root.exists():
        return {
            "files": 0, "bytes": 0, "by_class": {}, "largest_file_bytes": 0,
            "review_diff_files": 0, "review_diff_bytes": 0,
            "whole_branch_diff_files": 0, "finding_delta_diff_files": 0,
            "duplicate_digest_count": len(known_receipt_digests) - len(set(known_receipt_digests)),
            "sealed_evidence_limit_exceeded": False,
        }
    if root.is_symlink() or not root.is_dir():
        raise ValueError("SDD artifact root is redirected")
    files = total = largest = review_files = review_bytes = 0
    whole_branch = finding_delta = 0
    by_class: dict[str, dict[str, int]] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any((root / Path(*relative.parts[:index])).is_symlink() for index in range(1, len(relative.parts) + 1)):
            raise ValueError("SDD artifact is redirected")
        if not path.is_file():
            continue
        metadata = path.stat()
        files += 1
        total += metadata.st_size
        largest = max(largest, metadata.st_size)
        artifact_class = _artifact_class(path)
        bucket = by_class.setdefault(artifact_class, {"files": 0, "bytes": 0})
        bucket["files"] += 1
        bucket["bytes"] += metadata.st_size
        if artifact_class in {"review_diff", "finding_delta"}:
            review_files += 1
            review_bytes += metadata.st_size
            finding_delta += int(artifact_class == "finding_delta")
            whole_branch += int("whole" in path.name.lower() or "final" in path.name.lower())
    return {
        "files": files, "bytes": total,
        "by_class": dict(sorted(by_class.items())),
        "largest_file_bytes": largest,
        "review_diff_files": review_files, "review_diff_bytes": review_bytes,
        "whole_branch_diff_files": whole_branch,
        "finding_delta_diff_files": finding_delta,
        "duplicate_digest_count": len(known_receipt_digests) - len(set(known_receipt_digests)),
        "sealed_evidence_limit_exceeded": files > max_files or total > max_total_bytes,
    }


def derive_coordination_efficiency(
    observations: Sequence[CoordinationObservation], *,
    produced_artifacts: Mapping[str, object] | None = None,
) -> dict[str, object]:
    spawns = [item for item in observations if item.event == "coordination.spawn"]
    context_complete = all(item.context_ref_count is not None for item in spawns)
    usage_attribution = (
        "parent_observed"
        if any(item.usage_attribution == "parent_observed" for item in observations)
        else "unavailable"
    )
    summary: dict[str, object] = {
        "spawns": len(spawns),
        "max_depth": max((item.depth or 0 for item in observations), default=0),
        "fork_turns": {
            "none": sum(item.fork_turns == "none" for item in spawns),
            "all": sum(item.fork_turns == "all" for item in spawns),
        },
        "unjustified_full_context_forks": sum(
            item.fork_turns == "all" and item.full_context_exception_valid is not True
            for item in spawns
        ),
        "wait_calls": sum(item.event == "coordination.wait" for item in observations),
        "list_calls": sum(item.event == "coordination.list" for item in observations),
        "send_calls": sum(item.event == "coordination.send" for item in observations),
        "followup_calls": sum(item.event == "coordination.followup" for item in observations),
        "compactions": sum(item.event == "coordination.compaction" for item in observations),
        "duration_seconds": sum(item.duration_ms or 0 for item in observations) // 1000,
        "declared_context_refs": (
            sum(item.context_ref_count or 0 for item in spawns) if context_complete else None
        ),
        "declared_context_bytes": (
            sum(item.context_ref_bytes or 0 for item in spawns) if context_complete else None
        ),
        "context_measurement_kind": (
            "declared_refs_not_provider_ingestion" if context_complete else "unavailable"
        ),
        "usage_scope": "controller_and_nested_agents_aggregate",
        "usage_attribution": usage_attribution,
        "usage_attribution_unavailable_reason": (
            None if usage_attribution == "parent_observed" else "provider_event_not_agent_scoped"
        ),
        "data_quality_warnings": sorted({
            warning for item in observations for warning in item.data_quality_warnings
        }),
    }
    if produced_artifacts is not None:
        summary["produced_artifacts"] = dict(produced_artifacts)
    return summary


def persist_coordination_observations(
    *, evidence_root: Path, plan_id: str,
    observations: Sequence[CoordinationObservation],
) -> str:
    if not isinstance(plan_id, str) or _IDENTIFIER.fullmatch(plan_id) is None:
        raise ValueError("coordination plan identity is invalid")
    if len(observations) > MAX_COORDINATION_EVENTS:
        raise ValueError("coordination event count exceeds limit")
    payload = _coordination_document(plan_id=plan_id, observations=observations)
    atomic_private_write(evidence_root / "coordination.json", payload)
    return hashlib.sha256(payload).hexdigest()


def _coordination_document(
    *, plan_id: str, observations: Sequence[CoordinationObservation],
) -> bytes:
    if not isinstance(plan_id, str) or _IDENTIFIER.fullmatch(plan_id) is None:
        raise ValueError("coordination plan identity is invalid")
    if len(observations) > MAX_COORDINATION_EVENTS:
        raise ValueError("coordination event count exceeds limit")
    serialized: list[dict[str, object]] = []
    for item in observations:
        serialized.append({
            "event": item.event, "plan_index": item.plan_index,
            "task_id": item.task_id, "role": item.role, "depth": item.depth,
            "fork_turns": item.fork_turns, "duration_ms": item.duration_ms,
            "operation_count": item.operation_count,
            "agent_id_digest": item.agent_id_digest,
            "context_ref_count": item.context_ref_count,
            "context_ref_bytes": item.context_ref_bytes,
            "context_measurement_kind": item.context_measurement_kind,
            "context_classes": item.context_classes,
            "context_refs": [
                {"class": ref.artifact_class, "sha256": ref.sha256, "byte_length": ref.byte_length}
                for ref in item.context_refs
            ],
            "usage_scope": item.usage_scope,
            "usage_attribution": item.usage_attribution,
            "usage_attribution_unavailable_reason": item.usage_attribution_unavailable_reason,
            "source": item.source,
            "full_context_exception_valid": item.full_context_exception_valid,
            "data_quality_warnings": list(item.data_quality_warnings),
            "field_sources": item.field_sources,
        })
    return json.dumps(
        {"schema_version": 1, "plan_id": plan_id, "observations": serialized},
        sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def load_coordination_observations(
    *, evidence_root: Path, plan_id: str, expected_digest: str | None = None,
) -> tuple[CoordinationObservation, ...]:
    path = evidence_root / "coordination.json"
    if path.is_symlink():
        raise ValueError("coordination evidence is redirected")
    try:
        payload = path.read_bytes()
        document = json.loads(payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("coordination evidence is unavailable") from exc
    if expected_digest is not None and (
        not _DIGEST.fullmatch(expected_digest)
        or hashlib.sha256(payload).hexdigest() != expected_digest
    ):
        raise ValueError("coordination evidence digest changed")
    if (
        not isinstance(document, dict)
        or set(document) != {"schema_version", "plan_id", "observations"}
        or document.get("schema_version") != 1
        or document.get("plan_id") != plan_id
        or not isinstance(document.get("observations"), list)
        or len(document["observations"]) > MAX_COORDINATION_EVENTS
    ):
        raise ValueError("coordination evidence is invalid")
    observations: list[CoordinationObservation] = []
    try:
        for item in document["observations"]:
            if not isinstance(item, dict):
                raise ValueError("coordination evidence is invalid")
            references = tuple(
                ContextReferenceMetadata(
                    artifact_class=reference["class"],
                    sha256=reference["sha256"],
                    byte_length=reference["byte_length"],
                )
                for reference in item.pop("context_refs")
            )
            observations.append(CoordinationObservation(
                context_refs=references,
                data_quality_warnings=tuple(item.pop("data_quality_warnings")),
                **item,
            ))
    except (KeyError, TypeError) as exc:
        raise ValueError("coordination evidence is invalid") from exc
    result = tuple(observations)
    if _coordination_document(plan_id=plan_id, observations=result) != payload:
        raise ValueError("coordination evidence is noncanonical")
    return result


def ingest_child_coordination_ledger(
    *, path: Path, worktree: Path,
    coordination_exceptions: Sequence[Mapping[str, object]],
) -> tuple[CoordinationObservation, ...]:
    """Bound and validate an append-only child ledger without retaining bodies."""
    if path.is_symlink():
        raise ValueError("coordination ledger is redirected")
    try:
        lines = path.read_bytes().splitlines()
    except OSError as exc:
        raise ValueError("coordination ledger is unavailable") from exc
    if len(lines) > MAX_COORDINATION_EVENTS:
        raise ValueError("coordination event count exceeds limit")
    observations: list[CoordinationObservation] = []
    for line in lines:
        if not line or len(line) > MAX_COORDINATION_EVENT_BYTES:
            raise ValueError("coordination event exceeds size limit")
        try:
            event = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("coordination event is invalid JSON") from exc
        if not isinstance(event, dict):
            raise ValueError("coordination event is invalid")
        observations.append(validate_child_coordination_event(
            event, worktree=worktree,
            coordination_exceptions=coordination_exceptions,
        ))
    return tuple(observations)
