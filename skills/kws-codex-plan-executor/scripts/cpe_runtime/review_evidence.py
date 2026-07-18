"""Structural Superpowers review evidence validation and efficiency metrics.

This module deliberately does not interpret review prose or implementation
quality.  It verifies only identifiers, lifecycle linkage, exact HEADs, and
parent-observed metadata for bounded worktree artifacts.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal, Mapping, Sequence

from .state import atomic_private_write


MAX_REVIEW_ARTIFACT_BYTES = 128 * 1024 * 1024
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_HEAD = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_PREFIXED_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_SCOPES = {"task", "delta", "whole_branch"}
_SCOPE_DIFF_KIND = {
    "task": "task",
    "delta": "finding_delta",
    "whole_branch": "whole_branch",
}
_DISPOSITIONS = {"accepted", "changes_requested"}
_RECEIPT_REQUIRED_FIELDS = {
    "review_id",
    "scope",
    "base_head",
    "head",
    "task_ids",
    "finding_set_id",
    "finding_ids",
    "evidence_digest",
    "diff_kind",
    "diff_artifact_path",
    "diff_artifact_digest",
    "diff_artifact_bytes",
    "review_package_path",
    "review_package_digest",
    "review_package_bytes",
    "disposition",
    "reviewer_attestation_path",
}
_RECEIPT_OPTIONAL_FIELDS = {"reconstruction_command_id"}


@dataclass(frozen=True)
class ReviewReceipt:
    review_id: str
    scope: Literal["task", "delta", "whole_branch"]
    base_head: str
    head: str
    task_ids: tuple[str, ...]
    finding_set_id: str | None
    finding_ids: tuple[str, ...]
    evidence_digest: str
    diff_kind: Literal["task", "finding_delta", "whole_branch"]
    diff_artifact_digest: str
    diff_artifact_bytes: int
    review_package_digest: str
    review_package_bytes: int
    disposition: Literal["accepted", "changes_requested"]
    reviewer_attestation_path: str
    reconstruction_command_id: str = "git.diff.base-head"


@dataclass(frozen=True)
class ReviewLifecycleDecision:
    valid: bool
    reason_code: str
    missing_scopes: tuple[str, ...]
    stale_review_ids: tuple[str, ...]


@dataclass(frozen=True)
class FindingFixReceipt:
    fix_id: str
    finding_set_id: str
    source_review_id: str
    before_head: str
    after_head: str
    finding_ids: tuple[str, ...]


def _identifier(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"review {name} is invalid")
    return value


def _head(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not _HEAD.fullmatch(value):
        raise ValueError(f"review {name} is invalid")
    return value


def _identifiers(value: object, *, name: str, allow_empty: bool) -> tuple[str, ...]:
    if (
        not isinstance(value, (list, tuple))
        or (not allow_empty and not value)
        or len(value) > 1024
        or any(not isinstance(item, str) or not _IDENTIFIER.fullmatch(item) for item in value)
        or len(value) != len(set(value))
    ):
        raise ValueError(f"review {name} are invalid")
    return tuple(value)


def _safe_relative(value: object) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("review artifact path is not safe worktree-relative")
    relative = PurePosixPath(value)
    if relative.is_absolute() or any(
        part in {"", ".", ".."} for part in relative.parts
    ):
        raise ValueError("review artifact path is not safe worktree-relative")
    return relative


def _verified_regular_metadata(worktree: Path, declared: object) -> tuple[str, int]:
    relative = _safe_relative(declared)
    try:
        root = worktree.resolve(strict=True)
        root_stat = os.lstat(worktree)
    except OSError as error:
        raise ValueError("review artifact path is not safe worktree-relative") from error
    if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
        raise ValueError("review artifact path is not safe worktree-relative")

    current = root
    try:
        for part in relative.parts:
            current = current / part
            metadata = os.lstat(current)
            if stat.S_ISLNK(metadata.st_mode):
                raise ValueError("review artifact path is not safe worktree-relative")
    except OSError as error:
        raise ValueError("review artifact path is not safe worktree-relative") from error

    try:
        descriptor = os.open(
            current, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        )
    except OSError as error:
        raise ValueError("review artifact path is not safe worktree-relative") from error
    digest = hashlib.sha256()
    observed_bytes = 0
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("review artifact path is not safe worktree-relative")
        if metadata.st_size > MAX_REVIEW_ARTIFACT_BYTES:
            raise ValueError("review artifact exceeds bounded metadata limit")
        while True:
            chunk = os.read(descriptor, 65_536)
            if not chunk:
                break
            observed_bytes += len(chunk)
            if observed_bytes > MAX_REVIEW_ARTIFACT_BYTES:
                raise ValueError("review artifact exceeds bounded metadata limit")
            digest.update(chunk)
        after = os.fstat(descriptor)
        if (
            metadata.st_dev != after.st_dev
            or metadata.st_ino != after.st_ino
            or metadata.st_size != after.st_size
        ):
            raise ValueError("review artifact changed during parent observation")
    finally:
        os.close(descriptor)
    return "sha256:" + digest.hexdigest(), observed_bytes


def _validate_declared_metadata(
    *,
    worktree: Path,
    path: object,
    digest: object,
    byte_length: object,
    label: str,
) -> tuple[str, int]:
    if (
        not isinstance(digest, str)
        or not _PREFIXED_DIGEST.fullmatch(digest)
        or not isinstance(byte_length, int)
        or isinstance(byte_length, bool)
        or byte_length < 0
    ):
        raise ValueError(f"{label} metadata is invalid")
    observed_digest, observed_bytes = _verified_regular_metadata(worktree, path)
    if digest != observed_digest or byte_length != observed_bytes:
        raise ValueError(f"{label} metadata does not match parent observation")
    return observed_digest, observed_bytes


def validate_review_receipt(
    run_root: Path, worktree: Path, receipt: Mapping[str, object]
) -> ReviewReceipt:
    """Validate a child receipt without interpreting its review disposition."""
    if (
        not isinstance(receipt, Mapping)
        or not _RECEIPT_REQUIRED_FIELDS.issubset(receipt)
        or set(receipt) - _RECEIPT_REQUIRED_FIELDS - _RECEIPT_OPTIONAL_FIELDS
    ):
        raise ValueError("review receipt fields are invalid")
    # Resolve both owned roots up front.  The current receipt sources are
    # intentionally worktree-relative; the run root is reserved for sealing.
    try:
        resolved_run_root = run_root.resolve(strict=True)
    except OSError as error:
        raise ValueError("review run root is invalid") from error
    if run_root.is_symlink() or not resolved_run_root.is_dir():
        raise ValueError("review run root is invalid")

    review_id = _identifier(receipt["review_id"], name="ID")
    scope = receipt["scope"]
    diff_kind = receipt["diff_kind"]
    if scope not in _SCOPES or diff_kind != _SCOPE_DIFF_KIND.get(str(scope)):
        raise ValueError("review scope and diff kind do not match")
    base_head = _head(receipt["base_head"], name="base HEAD")
    head = _head(receipt["head"], name="HEAD")
    task_ids = _identifiers(
        receipt["task_ids"], name="task IDs", allow_empty=scope == "delta"
    )
    if scope == "task" and len(task_ids) != 1:
        raise ValueError("task review must cover exactly one task")

    raw_finding_set = receipt["finding_set_id"]
    finding_set_id = (
        None
        if raw_finding_set is None
        else _identifier(raw_finding_set, name="finding set ID")
    )
    finding_ids = _identifiers(
        receipt["finding_ids"], name="finding IDs", allow_empty=True
    )
    if (finding_set_id is None) != (not finding_ids):
        raise ValueError("review finding set linkage is invalid")
    disposition = receipt["disposition"]
    if disposition not in _DISPOSITIONS:
        raise ValueError("review disposition is invalid")
    if disposition == "changes_requested" and finding_set_id is None:
        raise ValueError("changes-requested review requires a finding set")
    if scope == "delta" and finding_set_id is None:
        raise ValueError("delta review requires a finding set")

    evidence_digest = receipt["evidence_digest"]
    if not isinstance(evidence_digest, str) or not _DIGEST.fullmatch(evidence_digest):
        raise ValueError("review evidence digest is invalid")
    reconstruction = _identifier(
        receipt.get("reconstruction_command_id", "git.diff.base-head"),
        name="reconstruction command ID",
    )
    diff_digest, diff_bytes = _validate_declared_metadata(
        worktree=worktree,
        path=receipt["diff_artifact_path"],
        digest=receipt["diff_artifact_digest"],
        byte_length=receipt["diff_artifact_bytes"],
        label="diff artifact",
    )
    package_digest, package_bytes = _validate_declared_metadata(
        worktree=worktree,
        path=receipt["review_package_path"],
        digest=receipt["review_package_digest"],
        byte_length=receipt["review_package_bytes"],
        label="review package",
    )
    attestation = _safe_relative(receipt["reviewer_attestation_path"])
    _verified_regular_metadata(worktree, attestation.as_posix())

    return ReviewReceipt(
        review_id=review_id,
        scope=scope,  # type: ignore[arg-type]
        base_head=base_head,
        head=head,
        task_ids=task_ids,
        finding_set_id=finding_set_id,
        finding_ids=finding_ids,
        evidence_digest=evidence_digest,
        diff_kind=diff_kind,  # type: ignore[arg-type]
        diff_artifact_digest=diff_digest,
        diff_artifact_bytes=diff_bytes,
        review_package_digest=package_digest,
        review_package_bytes=package_bytes,
        disposition=disposition,  # type: ignore[arg-type]
        reviewer_attestation_path=attestation.as_posix(),
        reconstruction_command_id=reconstruction,
    )


def _validate_fix(fix: FindingFixReceipt, review_ids: set[str]) -> None:
    for value, name in (
        (fix.fix_id, "fix ID"),
        (fix.finding_set_id, "finding set ID"),
        (fix.source_review_id, "source review ID"),
    ):
        _identifier(value, name=name)
    _head(fix.before_head, name="fix before HEAD")
    _head(fix.after_head, name="fix after HEAD")
    finding_ids = _identifiers(fix.finding_ids, name="fix finding IDs", allow_empty=False)
    if finding_ids != fix.finding_ids:
        raise ValueError("fix finding IDs are invalid")
    if fix.source_review_id not in review_ids:
        raise ValueError("fix source review is missing")


def _redundant_receipt_count(receipts: Sequence[ReviewReceipt]) -> int:
    seen: set[tuple[object, ...]] = set()
    redundant = 0
    for receipt in receipts:
        identity = (
            receipt.scope,
            receipt.base_head,
            receipt.head,
            tuple(sorted(receipt.task_ids)),
            receipt.evidence_digest,
        )
        if identity in seen:
            redundant += 1
        else:
            seen.add(identity)
    return redundant


def validate_review_lifecycle(
    *,
    completed_task_ids: Sequence[str],
    current_head: str,
    receipts: Sequence[ReviewReceipt],
    fixes: Sequence[FindingFixReceipt],
) -> ReviewLifecycleDecision:
    """Validate structural lifecycle coverage, never review semantics."""
    current_head = _head(current_head, name="current HEAD")
    completed = _identifiers(
        tuple(completed_task_ids), name="completed task IDs", allow_empty=True
    )
    review_ids = [receipt.review_id for receipt in receipts]
    if len(review_ids) != len(set(review_ids)):
        raise ValueError("review ID is duplicated")
    review_id_set = set(review_ids)
    for fix in fixes:
        _validate_fix(fix, review_id_set)
    fix_ids = [fix.fix_id for fix in fixes]
    if len(fix_ids) != len(set(fix_ids)):
        raise ValueError("fix ID is duplicated")
    if review_id_set & set(fix_ids):
        raise ValueError("review and fix IDs overlap")

    covered_tasks = {
        task_id
        for receipt in receipts
        if receipt.scope == "task"
        for task_id in receipt.task_ids
    }
    missing_tasks = tuple(
        f"task:{task_id}" for task_id in sorted(set(completed) - covered_tasks)
    )
    if missing_tasks:
        return ReviewLifecycleDecision(
            False, "missing_task_review", missing_tasks, ()
        )

    current_whole = [
        receipt
        for receipt in receipts
        if receipt.scope == "whole_branch"
        and receipt.disposition == "accepted"
        and receipt.head == current_head
    ]
    if not current_whole:
        stale = tuple(sorted(
            receipt.review_id
            for receipt in receipts
            if receipt.scope == "whole_branch"
            and receipt.disposition == "accepted"
            and receipt.head != current_head
        ))
        if stale:
            return ReviewLifecycleDecision(
                False, "stale_whole_branch_review", ("whole_branch",), stale
            )
        return ReviewLifecycleDecision(
            False, "missing_whole_branch_review", ("whole_branch",), ()
        )
    if not any(set(receipt.task_ids) == set(completed) for receipt in current_whole):
        return ReviewLifecycleDecision(
            False,
            "incomplete_whole_branch_coverage",
            tuple(f"whole_branch:{task_id}" for task_id in sorted(completed)),
            (),
        )

    requested_by_set: dict[str, list[ReviewReceipt]] = {}
    for receipt in receipts:
        if receipt.disposition == "changes_requested":
            assert receipt.finding_set_id is not None
            requested_by_set.setdefault(receipt.finding_set_id, []).append(receipt)
    duplicate_openers = sorted(
        finding_set
        for finding_set, grouped in requested_by_set.items()
        if len(grouped) > 1
    )
    if duplicate_openers:
        return ReviewLifecycleDecision(
            False,
            "duplicate_finding_set_opener",
            tuple(f"finding_set:{item}" for item in duplicate_openers),
            (),
        )
    fixes_by_set: dict[str, list[FindingFixReceipt]] = {}
    for fix in fixes:
        fixes_by_set.setdefault(fix.finding_set_id, []).append(fix)
    orphaned_sets = sorted(set(fixes_by_set) - set(requested_by_set))
    if orphaned_sets:
        return ReviewLifecycleDecision(
            False,
            "invalid_fix_linkage",
            tuple(f"finding_set:{item}" for item in orphaned_sets),
            (),
        )
    duplicate_sets = sorted(
        finding_set for finding_set, grouped in fixes_by_set.items() if len(grouped) > 1
    )
    if duplicate_sets:
        return ReviewLifecycleDecision(
            False,
            "duplicate_fix_cycle",
            tuple(f"finding_set:{item}" for item in duplicate_sets),
            (),
        )

    for finding_set, reviews in sorted(requested_by_set.items()):
        grouped_fixes = fixes_by_set.get(finding_set, [])
        if not grouped_fixes:
            return ReviewLifecycleDecision(
                False, "missing_consolidated_fix",
                (f"finding_set:{finding_set}",), ()
            )
        fix = grouped_fixes[0]
        source_reviews = {
            receipt.review_id: receipt for receipt in reviews
        }
        source = source_reviews.get(fix.source_review_id)
        if source is None or source.head != fix.before_head:
            return ReviewLifecycleDecision(
                False, "invalid_fix_linkage",
                (f"finding_set:{finding_set}",), ()
            )
        if set(source.finding_ids) != set(fix.finding_ids):
            return ReviewLifecycleDecision(
                False, "invalid_fix_linkage",
                (f"finding_set:{finding_set}",), ()
            )
        deltas = [
            receipt for receipt in receipts
            if receipt.scope == "delta"
            and receipt.disposition == "accepted"
            and receipt.finding_set_id == finding_set
            and receipt.base_head == fix.before_head
            and receipt.head == fix.after_head
            and set(receipt.finding_ids) == set(fix.finding_ids)
        ]
        if not deltas:
            return ReviewLifecycleDecision(
                False, "missing_delta_review",
                (f"finding_set:{finding_set}",), ()
            )

    reason = (
        "redundant_review_receipt"
        if _redundant_receipt_count(receipts)
        else "review_lifecycle_valid"
    )
    return ReviewLifecycleDecision(True, reason, (), ())


def derive_review_efficiency_metrics(
    receipts: Sequence[ReviewReceipt], fixes: Sequence[FindingFixReceipt]
) -> dict[str, object]:
    """Derive content-free review payload and duplicate-work observations."""
    bytes_by_kind = {"task": 0, "finding_delta": 0, "whole_branch": 0}
    duplicate_payloads = 0
    seen_payloads: set[tuple[str, str, str, str, str]] = set()
    for receipt in receipts:
        bytes_by_kind[receipt.diff_kind] += receipt.diff_artifact_bytes
        identity = (
            receipt.scope,
            receipt.base_head,
            receipt.head,
            receipt.diff_kind,
            receipt.diff_artifact_digest,
        )
        if identity in seen_payloads:
            duplicate_payloads += 1
        else:
            seen_payloads.add(identity)
    return {
        "task_reviews": sum(receipt.scope == "task" for receipt in receipts),
        "delta_reviews": sum(receipt.scope == "delta" for receipt in receipts),
        "whole_branch_reviews": sum(
            receipt.scope == "whole_branch" for receipt in receipts
        ),
        "redundant_review_receipts": _redundant_receipt_count(receipts),
        "consolidated_fix_cycles": len({fix.finding_set_id for fix in fixes}),
        "review_package_bytes": sum(
            receipt.review_package_bytes for receipt in receipts
        ),
        "review_diff_bytes": sum(receipt.diff_artifact_bytes for receipt in receipts),
        "review_diff_bytes_by_kind": bytes_by_kind,
        "duplicate_review_diff_digests": duplicate_payloads,
    }


def _seal_metadata_receipt(
    run_root: Path, *, identity: str, document: Mapping[str, object]
) -> Path:
    root = run_root.resolve(strict=True)
    if run_root.is_symlink() or not root.is_dir():
        raise ValueError("review run root is invalid")
    _identifier(identity, name="evidence ID")
    target = run_root / "evidence" / "reviews" / f"{identity}.json"
    payload = (
        json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    if target.exists() or target.is_symlink():
        if target.is_symlink() or not target.is_file() or target.read_bytes() != payload:
            raise ValueError("sealed review receipt conflicts with accepted evidence")
        return target
    atomic_private_write(target, payload, mode=0o400)
    return target


def seal_review_receipt(run_root: Path, receipt: ReviewReceipt) -> Path:
    """Seal metadata only; raw review packages and diff bodies stay unsealed."""
    return _seal_metadata_receipt(
        run_root, identity=receipt.review_id, document=dataclasses.asdict(receipt)
    )


def seal_finding_fix_receipt(run_root: Path, receipt: FindingFixReceipt) -> Path:
    """Seal one consolidated finding-set fix as content-free metadata."""
    _validate_fix(receipt, {receipt.source_review_id})
    return _seal_metadata_receipt(
        run_root, identity=receipt.fix_id, document=dataclasses.asdict(receipt)
    )
