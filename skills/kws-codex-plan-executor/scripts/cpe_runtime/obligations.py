"""Durable transition obligations with parent-authorized closure semantics."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import AbstractSet, Literal, Sequence

from .state import atomic_private_write


_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_STATUSES = {"open", "satisfied", "waived"}
_MAX_OBLIGATIONS = 512
_MAX_FILE_BYTES = 512 * 1024


@dataclass(frozen=True)
class TransitionObligation:
    obligation_id: str
    opened_by_task_id: str
    must_close_by_task_id: str
    description: str
    status: Literal["open", "satisfied", "waived"]
    closure_evidence_id: str | None
    waiver_reason: str | None
    waiver_event_id: str | None = None


def _valid_identifier(value: object) -> bool:
    return isinstance(value, str) and _IDENTIFIER.fullmatch(value) is not None


def _validate_shape(obligation: TransitionObligation) -> None:
    if not isinstance(obligation, TransitionObligation):
        raise ValueError("transition obligation is invalid")
    if not _valid_identifier(obligation.obligation_id):
        raise ValueError("transition obligation identity is invalid")
    if not _valid_identifier(obligation.opened_by_task_id):
        raise ValueError("transition obligation opening task is invalid")
    if (
        obligation.must_close_by_task_id != "__finish__"
        and not _valid_identifier(obligation.must_close_by_task_id)
    ):
        raise ValueError("transition obligation deadline is invalid")
    if (
        not isinstance(obligation.description, str)
        or not obligation.description.strip()
        or len(obligation.description.encode("utf-8")) > 4096
    ):
        raise ValueError("transition obligation description is invalid")
    if obligation.status not in _STATUSES:
        raise ValueError("transition obligation status is invalid")
    if obligation.closure_evidence_id is not None and not _valid_identifier(
        obligation.closure_evidence_id
    ):
        raise ValueError("transition obligation closure evidence is invalid")
    if obligation.waiver_event_id is not None and not _valid_identifier(
        obligation.waiver_event_id
    ):
        raise ValueError("transition obligation waiver event is invalid")
    if obligation.waiver_reason is not None and (
        not isinstance(obligation.waiver_reason, str)
        or not obligation.waiver_reason.strip()
        or len(obligation.waiver_reason.encode("utf-8")) > 2048
    ):
        raise ValueError("transition obligation waiver reason is invalid")
    if obligation.status == "open" and any((
        obligation.closure_evidence_id,
        obligation.waiver_reason,
        obligation.waiver_event_id,
    )):
        raise ValueError("open transition obligation has closure metadata")
    if obligation.status == "satisfied" and (
        obligation.closure_evidence_id is None
        or obligation.waiver_reason is not None
        or obligation.waiver_event_id is not None
    ):
        raise ValueError("satisfied transition obligation evidence is invalid")
    if obligation.status == "waived" and (
        obligation.closure_evidence_id is not None
        or obligation.waiver_reason is None
        or obligation.waiver_event_id is None
    ):
        raise ValueError("waived transition obligation evidence is invalid")


def validate_transition_obligations(
    *,
    obligations: Sequence[TransitionObligation],
    compiled_task_ids: Sequence[str],
    completed_task_ids: Sequence[str],
    next_task_id: str | None,
    finishing: bool,
    valid_evidence_ids: AbstractSet[str],
    parent_waiver_event_ids: AbstractSet[str] = frozenset(),
) -> tuple[bool, tuple[str, ...]]:
    """Return whether the requested boundary is allowed and blocking IDs.

    An obligation is due only after its deadline task has completed (or at the
    explicit finish boundary).  Closure evidence and waivers are validated even
    before the deadline so invalid child-authored closure cannot become durable.
    """
    task_ids = tuple(compiled_task_ids)
    if (
        not task_ids
        or len(task_ids) != len(set(task_ids))
        or any(not _valid_identifier(task_id) for task_id in task_ids)
    ):
        raise ValueError("compiled task order is invalid")
    positions = {task_id: index for index, task_id in enumerate(task_ids)}
    completed = tuple(completed_task_ids)
    if (
        len(completed) != len(set(completed))
        or any(task_id not in positions for task_id in completed)
        or (next_task_id is not None and next_task_id not in positions)
        or not isinstance(finishing, bool)
    ):
        raise ValueError("transition boundary is invalid")
    completed_set = set(completed)
    blocked: list[str] = []
    seen: set[str] = set()
    for obligation in obligations:
        _validate_shape(obligation)
        if obligation.obligation_id in seen:
            raise ValueError("transition obligation identity is duplicated")
        seen.add(obligation.obligation_id)
        opening = positions.get(obligation.opened_by_task_id)
        deadline = (
            None
            if obligation.must_close_by_task_id == "__finish__"
            else positions.get(obligation.must_close_by_task_id)
        )
        if opening is None or (
            obligation.must_close_by_task_id != "__finish__"
            and (deadline is None or deadline < opening)
        ):
            blocked.append(obligation.obligation_id)
            continue
        if obligation.status == "satisfied":
            if obligation.closure_evidence_id not in valid_evidence_ids:
                blocked.append(obligation.obligation_id)
            continue
        if obligation.status == "waived":
            if obligation.waiver_event_id not in parent_waiver_event_ids:
                blocked.append(obligation.obligation_id)
            continue
        due = (
            finishing
            if obligation.must_close_by_task_id == "__finish__"
            else obligation.must_close_by_task_id in completed_set
        )
        if due:
            blocked.append(obligation.obligation_id)
    result = tuple(sorted(set(blocked)))
    return not result, result


def _canonical_document(
    *, plan_id: str, obligations: Sequence[TransitionObligation]
) -> bytes:
    if not _valid_identifier(plan_id):
        raise ValueError("transition obligation plan identity is invalid")
    if len(obligations) > _MAX_OBLIGATIONS:
        raise ValueError("transition obligation count exceeds limit")
    ordered = sorted(obligations, key=lambda item: item.obligation_id)
    if len({item.obligation_id for item in ordered}) != len(ordered):
        raise ValueError("transition obligation identity is duplicated")
    for obligation in ordered:
        _validate_shape(obligation)
    payload = json.dumps(
        {
            "schema_version": 1,
            "plan_id": plan_id,
            "obligations": [asdict(item) for item in ordered],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(payload) > _MAX_FILE_BYTES:
        raise ValueError("transition obligation file exceeds limit")
    return payload


def _read_private_regular(path: Path) -> bytes:
    if path.is_symlink():
        raise ValueError("transition obligation evidence is redirected")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > _MAX_FILE_BYTES:
            raise ValueError("transition obligation evidence is invalid")
        payload = os.read(descriptor, _MAX_FILE_BYTES + 1)
        if len(payload) != metadata.st_size or len(payload) > _MAX_FILE_BYTES:
            raise ValueError("transition obligation evidence is invalid")
        return payload
    finally:
        os.close(descriptor)


def load_transition_obligations(
    *, evidence_root: Path, plan_id: str, expected_digest: str | None = None
) -> tuple[TransitionObligation, ...]:
    path = evidence_root / "obligations.json"
    try:
        payload = _read_private_regular(path)
        document = json.loads(payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("transition obligation evidence is unavailable") from exc
    if expected_digest is not None and (
        not _DIGEST.fullmatch(expected_digest)
        or hashlib.sha256(payload).hexdigest() != expected_digest
    ):
        raise ValueError("transition obligation digest changed")
    if (
        not isinstance(document, dict)
        or set(document) != {"schema_version", "plan_id", "obligations"}
        or document.get("schema_version") != 1
        or document.get("plan_id") != plan_id
        or not isinstance(document.get("obligations"), list)
    ):
        raise ValueError("transition obligation evidence is invalid")
    try:
        obligations = tuple(
            TransitionObligation(**item)
            for item in document["obligations"]
            if isinstance(item, dict)
        )
    except TypeError as exc:
        raise ValueError("transition obligation evidence is invalid") from exc
    if len(obligations) != len(document["obligations"]):
        raise ValueError("transition obligation evidence is invalid")
    if _canonical_document(plan_id=plan_id, obligations=obligations) != payload:
        raise ValueError("transition obligation evidence is noncanonical")
    return obligations


def persist_transition_obligations(
    *, evidence_root: Path, plan_id: str,
    obligations: Sequence[TransitionObligation],
) -> str:
    """Atomically persist obligations while forbidding resume-time deletion."""
    candidate = tuple(obligations)
    target = evidence_root / "obligations.json"
    if target.exists() or target.is_symlink():
        previous = load_transition_obligations(
            evidence_root=evidence_root, plan_id=plan_id,
        )
        old = {item.obligation_id: item for item in previous}
        new = {item.obligation_id: item for item in candidate}
        if not set(old) <= set(new):
            raise ValueError("persisted transition obligations cannot be dropped")
        for obligation_id, prior in old.items():
            current = new[obligation_id]
            if (
                current.opened_by_task_id != prior.opened_by_task_id
                or current.must_close_by_task_id != prior.must_close_by_task_id
                or current.description != prior.description
                or (prior.status != "open" and current != prior)
            ):
                raise ValueError("persisted transition obligation changed incompatibly")
    payload = _canonical_document(plan_id=plan_id, obligations=candidate)
    atomic_private_write(target, payload)
    return hashlib.sha256(payload).hexdigest()
