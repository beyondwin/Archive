from __future__ import annotations

import json
import hashlib
import os
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable

from .events import read_events, validate_chain
from .evidence import KIND_RE, verify_ref
from .git_delta import GitDelta, capture_snapshot, matches_path, scope_errors
from .manifest import load_manifest, resolve_ref, validate_manifest
from .model_policy import CORE_ROUTE, SCOUT_ROUTE
from .packets import packet_entry, verify_packet
from .projector import project


INTEGRITY_CHECKS = (
    "schema",
    "manifest",
    "packets",
    "event_chain",
    "snapshot_replay",
    "artifacts",
    "worktree_identity",
    "attempt_structure",
    "git_scope",
)
COMPLETION_CHECKS = INTEGRITY_CHECKS + (
    "task_states",
    "current_revision_acceptance",
    "current_revision_verdicts",
    "repository_checks",
    "active_blockers",
    "completion_audit",
)
COMPLETION_EVIDENCE_KINDS = frozenset(
    {"acceptance", "task_review", "verification", "repository_check", "final_review"}
)


@dataclass(frozen=True)
class ValidationReport:
    classification: str
    passed: bool
    errors: list[str]
    warnings: list[str]
    checks: dict[str, list[str]] | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "classification": self.classification,
            "passed": self.passed,
            "errors": self.errors,
            "warnings": self.warnings,
            "checks": self.checks or {},
        }


def _schema_marker(run_dir: Path) -> str | None:
    for name in ("run_manifest.json", "state.json"):
        try:
            payload = json.loads((run_dir / name).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        value = payload.get("schema_version")
        if value is not None:
            return str(value)
    return None


def _context(run_dir: Path, candidate_state: dict | None) -> dict[str, object]:
    context: dict[str, object] = {
        "run_dir": run_dir,
        "candidate_state": candidate_state,
        "manifest": None,
        "manifest_error": None,
        "events": None,
        "event_error": None,
        "replay_state": None,
        "projection_error": None,
        "state": candidate_state,
        "candidate_error": None,
        "artifact_payloads": {},
        "revision_validation": None,
    }
    try:
        manifest = load_manifest(run_dir / "run_manifest.json")
    except ValueError as exc:
        context["manifest_error"] = str(exc)
        return context
    except (OSError, json.JSONDecodeError):
        context["manifest_error"] = "manifest_missing"
        return context
    context["manifest"] = manifest
    try:
        events = read_events(run_dir / "events.jsonl")
    except ValueError:
        context["event_error"] = "event_chain_invalid"
        return context
    context["events"] = events
    try:
        replay_state = project(manifest, events)
    except (KeyError, TypeError, ValueError):
        context["projection_error"] = "event_projection_invalid"
        return context
    context["replay_state"] = replay_state
    context["state"] = replay_state
    if candidate_state is not None:
        allowed_audit_keys = {
            "passed",
            "prompt_to_artifact_checklist",
            "verification_evidence",
            "residual_risk",
        }
        candidate_valid = isinstance(candidate_state, dict)
        if candidate_valid:
            base_without_audit = dict(replay_state)
            candidate_without_audit = dict(candidate_state)
            base_audit = base_without_audit.pop("completion_audit", None)
            candidate_audit = candidate_without_audit.pop("completion_audit", None)
            prospective_audit = (
                base_audit is None
                and isinstance(candidate_audit, dict)
                and set(candidate_audit) == allowed_audit_keys
            )
            candidate_valid = (
                candidate_without_audit == base_without_audit
                and (candidate_audit == base_audit or prospective_audit)
            )
        if candidate_valid:
            context["state"] = candidate_state
        else:
            context["candidate_error"] = "candidate_state_invalid"
    return context


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _check_schema(context: dict[str, object]) -> tuple[list[str], list[str]]:
    if context.get("candidate_error"):
        return [str(context["candidate_error"])], []
    marker = _schema_marker(context["run_dir"])
    if marker is not None and marker != "3":
        return ["unsupported_schema"], []
    state = context.get("state")
    if isinstance(state, dict) and state.get("schema_version") != "3":
        return ["state_schema_invalid"], []
    return [], []


@dataclass(frozen=True)
class _ParsedPatch:
    raw: bytes
    sha256: str
    before_head: str
    after_head: str
    before_snapshot: str
    after_snapshot: str
    before_identity: str
    after_identity: str
    paths: tuple[str, ...]
    before_fingerprints: tuple[str, ...]
    after_fingerprints: tuple[str, ...]


def _decode_ascii(value: bytes) -> str:
    return value.decode("ascii")


def _parse_canonical_patch(raw: bytes) -> _ParsedPatch:
    magic = b"CPE-GIT-DELTA-V1\0"
    if not raw.startswith(magic):
        raise ValueError("invalid patch magic")
    cursor = len(magic)
    fields: list[tuple[bytes, bytes]] = []
    while cursor < len(raw):
        if cursor + 9 > len(raw):
            raise ValueError("truncated patch field")
        label = raw[cursor : cursor + 1]
        size = int.from_bytes(raw[cursor + 1 : cursor + 9], "big")
        cursor += 9
        if size > len(raw) - cursor:
            raise ValueError("truncated patch value")
        fields.append((label, raw[cursor : cursor + size]))
        cursor += size
    if len(fields) < 7 or [label for label, _ in fields[:6]] != [b"B", b"A", b"S", b"T", b"I", b"J"]:
        raise ValueError("invalid patch header")
    if fields[-1][0] != b"D" or (len(fields) - 7) % 3:
        raise ValueError("invalid patch body")
    bodies = fields[6:-1]
    paths: list[str] = []
    before: list[str] = []
    after: list[str] = []
    for index in range(0, len(bodies), 3):
        if [label for label, _ in bodies[index : index + 3]] != [b"P", b"B", b"A"]:
            raise ValueError("invalid patch path record")
        raw_path = bodies[index][1]
        if b"\0" in raw_path:
            raise ValueError("invalid patch path")
        path = os.fsdecode(raw_path)
        safe = PurePosixPath(path)
        if safe.is_absolute() or not safe.parts or ".." in safe.parts:
            raise ValueError("unsafe patch path")
        paths.append(path)
        before.append(_decode_ascii(bodies[index + 1][1]))
        after.append(_decode_ascii(bodies[index + 2][1]))
    if paths != sorted(set(paths)):
        raise ValueError("non-canonical patch paths")
    content = fields[-1][1]
    content_magic = b"CPE-GIT-CONTENT-V1\0"
    if not content.startswith(content_magic):
        raise ValueError("invalid patch content magic")
    content_cursor = len(content_magic)
    content_fields: list[tuple[bytes, bytes]] = []
    while content_cursor < len(content):
        if content_cursor + 9 > len(content):
            raise ValueError("truncated patch content field")
        label = content[content_cursor : content_cursor + 1]
        size = int.from_bytes(content[content_cursor + 1 : content_cursor + 9], "big")
        content_cursor += 9
        if size > len(content) - content_cursor:
            raise ValueError("truncated patch content value")
        content_fields.append(
            (label, content[content_cursor : content_cursor + size])
        )
        content_cursor += size
    if len(content_fields) != len(paths) * 3:
        raise ValueError("patch content path count mismatch")
    content_paths: list[str] = []
    for index in range(0, len(content_fields), 3):
        triple = content_fields[index : index + 3]
        if [label for label, _ in triple] != [b"P", b"F", b"C"]:
            raise ValueError("invalid patch content record")
        raw_path, raw_fingerprint, raw_content = (value for _, value in triple)
        if b"\0" in raw_path:
            raise ValueError("invalid patch content path")
        content_path = os.fsdecode(raw_path)
        content_paths.append(content_path)
        fingerprint = _decode_ascii(raw_fingerprint)
        expected = "deleted" if after[index // 3] == "absent" else after[index // 3]
        if fingerprint != expected:
            raise ValueError("patch content fingerprint mismatch")
        if fingerprint == "deleted":
            if raw_content:
                raise ValueError("deleted patch content is non-empty")
        else:
            parts = fingerprint.split(":")
            if len(parts) < 3 or len(parts[-1]) != 64:
                raise ValueError("invalid patch content fingerprint")
            if hashlib.sha256(raw_content).hexdigest() != parts[-1]:
                raise ValueError("patch content digest mismatch")
    if tuple(content_paths) != tuple(paths):
        raise ValueError("patch content paths mismatch")
    header = [_decode_ascii(value) for _, value in fields[:6]]
    digests = header[2:6]
    if any(len(value) != 64 or any(char not in "0123456789abcdef" for char in value) for value in digests):
        raise ValueError("invalid patch digest")
    return _ParsedPatch(
        raw,
        hashlib.sha256(raw).hexdigest(),
        header[0],
        header[1],
        header[2],
        header[3],
        header[4],
        header[5],
        tuple(paths),
        tuple(before),
        tuple(after),
    )


def _load_patch(run_dir: Path, payload: dict) -> tuple[_ParsedPatch | None, str | None]:
    ref = payload.get("patch_ref")
    digest = payload.get("patch_sha256")
    if not isinstance(ref, dict):
        return None, "revision_patch_evidence_missing"
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(char not in "0123456789abcdef" for char in digest)
    ):
        return None, "revision_patch_evidence_invalid"
    expected_path = f"artifacts/patches/{digest}.patch"
    if (
        ref.get("kind") != "patch"
        or ref.get("path") != expected_path
        or ref.get("sha256") != digest
        or ref.get("media_type") != "application/octet-stream"
    ):
        return None, "revision_patch_evidence_invalid"
    artifacts_root = run_dir / "artifacts"
    patch_root = artifacts_root / "patches"
    for ancestor in (artifacts_root, patch_root):
        try:
            ancestor_metadata = ancestor.lstat()
        except OSError:
            return None, "revision_patch_evidence_missing"
        if stat.S_ISLNK(ancestor_metadata.st_mode) or not stat.S_ISDIR(
            ancestor_metadata.st_mode
        ):
            return None, "revision_patch_evidence_invalid"
    target = patch_root / f"{digest}.patch"
    try:
        metadata = target.lstat()
    except OSError:
        return None, "revision_patch_evidence_missing"
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        return None, "revision_patch_evidence_invalid"
    try:
        resolved = target.resolve()
        if resolved.parent != patch_root or target.parent != patch_root:
            return None, "revision_patch_evidence_invalid"
        raw = target.read_bytes()
    except OSError:
        return None, "revision_patch_evidence_invalid"
    if not isinstance(digest, str) or hashlib.sha256(raw).hexdigest() != digest:
        return None, "revision_patch_evidence_invalid"
    try:
        parsed = _parse_canonical_patch(raw)
    except (UnicodeDecodeError, ValueError):
        return None, "revision_patch_evidence_invalid"
    return parsed, None


def _revision_validation(context: dict[str, object]) -> dict[str, object]:
    cached = context.get("revision_validation")
    if isinstance(cached, dict):
        return cached
    result: dict[str, object] = {
        "errors": [],
        "warnings": [],
        "records": [],
        "zero_unverified": False,
    }
    context["revision_validation"] = result
    manifest = context.get("manifest")
    state = context.get("state")
    events = context.get("events")
    if not isinstance(manifest, dict) or not isinstance(state, dict) or not isinstance(events, list):
        return result
    revisions = [event for event in events if event.get("type") == "worktree.revision_recorded"]
    if not revisions:
        if state.get("worktree_revision") != 0 or state.get("worktree_patch_sha256") is not None:
            result["errors"].append("revision_patch_chain_invalid")
        else:
            write_in_progress = any(
                attempt.get("kind") in {"implementation", "repair"}
                and attempt.get("status") in {"started", "failed", "interrupted"}
                for attempt in state.get("attempts") or []
            )
            if write_in_progress:
                result["errors"].append("revision_zero_write_attempt_unrecorded")
            try:
                worktree = resolve_ref(str(manifest["execution_worktree_ref"]))
                changed, git_error = _git_status(worktree)
                branch = subprocess.run(
                    ["git", "symbolic-ref", "-q", "HEAD"],
                    cwd=worktree,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                worktree_diff = subprocess.run(
                    ["git", "diff", "--quiet"],
                    cwd=worktree,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                index_diff = subprocess.run(
                    ["git", "diff", "--cached", "--quiet"],
                    cwd=worktree,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                index_flags = subprocess.run(
                    ["git", "ls-files", "-v", "-z"],
                    cwd=worktree,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                expected_branch = f"refs/heads/codex/{manifest['run_id']}"
            except (KeyError, OSError, ValueError):
                changed, git_error = [], "worktree_identity_mismatch"
                branch = None
                worktree_diff = None
                index_diff = None
                index_flags = None
                expected_branch = ""
            flags_clean = (
                index_flags is not None
                and index_flags.returncode == 0
                and all(
                    record.startswith(b"H ")
                    for record in index_flags.stdout.split(b"\0")
                    if record
                )
            )
            if (
                git_error
                or changed
                or branch is None
                or branch.returncode
                or branch.stdout.strip() != expected_branch
                or worktree_diff is None
                or worktree_diff.returncode
                or index_diff is None
                or index_diff.returncode
                or not flags_clean
            ):
                result["errors"].append("revision_zero_worktree_dirty")
            if not result["errors"]:
                result["zero_unverified"] = True
                result["warnings"].append("revision_zero_baseline_unverified")
        return result
    previous_after: str | None = None
    previous_head: str | None = None
    previous_identity: str | None = None
    expected_revision = 0
    for event in revisions:
        payload = event.get("payload")
        if not isinstance(payload, dict):
            result["errors"].append("revision_patch_evidence_invalid")
            continue
        parsed, error = _load_patch(context["run_dir"], payload)
        if error:
            result["errors"].append(error)
            continue
        assert parsed is not None
        source = payload.get("from")
        target = payload.get("to")
        changed_files = payload.get("changed_files")
        if (
            source != expected_revision
            or target != expected_revision + 1
            or payload.get("patch_sha256") != parsed.sha256
            or not isinstance(changed_files, list)
            or tuple(changed_files) != parsed.paths
            or (previous_after is not None and parsed.before_snapshot != previous_after)
            or (previous_head is not None and parsed.before_head != previous_head)
            or (previous_identity is not None and parsed.before_identity != previous_identity)
        ):
            result["errors"].append("revision_patch_chain_invalid")
        expected_source_head = (manifest.get("source_git") or {}).get("head")
        if expected_revision == 0 and expected_source_head and parsed.before_head != expected_source_head:
            result["errors"].append("revision_patch_chain_invalid")
        previous_after = parsed.after_snapshot
        previous_head = parsed.after_head
        previous_identity = parsed.after_identity
        expected_revision += 1
        result["records"].append((event, parsed))
    if (
        state.get("worktree_revision") != expected_revision
        or state.get("worktree_patch_sha256") != revisions[-1].get("payload", {}).get("patch_sha256")
    ):
        result["errors"].append("revision_patch_chain_invalid")
    if previous_after is not None:
        try:
            worktree = resolve_ref(str(manifest["execution_worktree_ref"]))
            current = capture_snapshot(worktree)
        except (KeyError, OSError, RuntimeError, ValueError):
            result["errors"].append("current_revision_worktree_mismatch")
        else:
            if current.cumulative_patch_sha256 != previous_after:
                result["errors"].append("current_revision_worktree_mismatch")
    result["errors"] = _dedupe(result["errors"])
    result["warnings"] = _dedupe(result["warnings"])
    return result


def _check_manifest(context: dict[str, object]) -> tuple[list[str], list[str]]:
    error = context.get("manifest_error")
    if error:
        return ["unsupported_schema" if error == "unsupported_schema" else str(error)], []
    manifest = context.get("manifest")
    return (validate_manifest(manifest) if isinstance(manifest, dict) else ["manifest_invalid"]), []


def _check_packets(context: dict[str, object]) -> tuple[list[str], list[str]]:
    manifest = context.get("manifest")
    if not isinstance(manifest, dict):
        return [], []
    task_ids = [str(task.get("id")) for task in manifest.get("task_graph", []) if isinstance(task, dict)]
    entries = manifest.get("task_packets")
    indexed = {
        str(item.get("task_id"))
        for item in entries or []
        if isinstance(item, dict) and isinstance(item.get("task_id"), str)
    }
    errors: list[str] = []
    if indexed != set(task_ids) or len(entries or []) != len(task_ids):
        errors.append("packet_index_incomplete")
    for task_id in task_ids:
        try:
            verify_packet(context["run_dir"], manifest, task_id)
        except (OSError, ValueError):
            errors.append("packet_digest_mismatch")
    return _dedupe(errors), []


def _check_event_chain(context: dict[str, object]) -> tuple[list[str], list[str]]:
    if context.get("manifest") is None:
        return [], []
    if context.get("event_error"):
        return [str(context["event_error"])], []
    events = context.get("events")
    errors = validate_chain(events) if isinstance(events, list) else ["event_chain_invalid"]
    result = ["event_chain_invalid"] if errors else []
    if context.get("projection_error"):
        result.append(str(context["projection_error"]))
    return result, []


def _check_snapshot_replay(context: dict[str, object]) -> tuple[list[str], list[str]]:
    replay = context.get("replay_state")
    if replay is None:
        return [], []
    path = context["run_dir"] / "state.json"
    if not path.is_file():
        return ["snapshot_missing"], []
    try:
        snapshot = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ["snapshot_replay_mismatch"], []
    return (["snapshot_replay_mismatch"] if snapshot != replay else []), []


def _read_ref_payload(run_dir: Path, ref: object) -> object | None:
    if not isinstance(ref, dict) or _verify_evidence_ref(run_dir, ref):
        return None
    try:
        return json.loads((run_dir / str(ref["path"])).read_text(encoding="utf-8"))
    except (OSError, KeyError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def _verify_evidence_ref(run_dir: Path, ref: object) -> list[str]:
    if not isinstance(ref, dict):
        return ["evidence path escapes run root"]
    kind = ref.get("kind")
    digest = ref.get("sha256")
    if (
        not isinstance(kind, str)
        or not KIND_RE.fullmatch(kind)
        or not isinstance(digest, str)
        or len(digest) != 64
        or any(char not in "0123456789abcdef" for char in digest)
        or ref.get("media_type") != "application/json"
        or ref.get("path")
        != f"artifacts/evidence/{kind}/{digest}.json"
    ):
        return ["evidence path escapes run root"]
    artifacts_root = run_dir / "artifacts"
    evidence_root = artifacts_root / "evidence"
    kind_root = evidence_root / kind
    for ancestor in (artifacts_root, evidence_root, kind_root):
        try:
            metadata = ancestor.lstat()
        except OSError:
            return ["evidence missing"]
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            return ["evidence path escapes run root"]
    target = kind_root / f"{digest}.json"
    if target.parent != kind_root:
        return ["evidence path escapes run root"]
    return verify_ref(run_dir, ref)


def _artifact_payloads(context: dict[str, object]) -> dict[int, object | None]:
    cached = context["artifact_payloads"]
    if cached:
        return cached
    state = context.get("state")
    run_dir = context["run_dir"]
    if isinstance(state, dict):
        for index, artifact in enumerate(state.get("artifact_index") or []):
            cached[index] = _read_ref_payload(run_dir, artifact.get("ref"))
    return cached


def _packet_sha(context: dict[str, object], task_id: str) -> str | None:
    manifest = context.get("manifest")
    if not isinstance(manifest, dict):
        return None
    try:
        return str(packet_entry(manifest, task_id)["sha256"])
    except (KeyError, ValueError):
        return None


def _binding_status(record: object, state: dict, packet_sha256: str | None) -> str:
    if not isinstance(record, dict) or not {
        "worktree_revision",
        "worktree_patch_sha256",
        "packet_sha256",
    }.issubset(record):
        return "unbound"
    if (
        record.get("worktree_revision") == state.get("worktree_revision")
        and record.get("worktree_patch_sha256") == state.get("worktree_patch_sha256")
        and packet_sha256 is not None
        and record.get("packet_sha256") == packet_sha256
    ):
        return "current"
    return "stale"


def _bound_to_current(record: object, state: dict, packet_sha256: str | None) -> bool:
    return _binding_status(record, state, packet_sha256) == "current"


def _check_artifacts(context: dict[str, object]) -> tuple[list[str], list[str]]:
    state = context.get("state")
    if not isinstance(state, dict):
        return [], []
    errors: list[str] = []
    warnings: list[str] = []
    payloads = _artifact_payloads(context)
    attempts = {
        item.get("attempt_id"): item for item in state.get("attempts") or []
    }
    canonical_refs = [
        _canonical_ref(artifact.get("ref"))
        for artifact in state.get("artifact_index") or []
    ]
    real_refs = [ref for ref in canonical_refs if ref is not None]
    if len(real_refs) != len(set(real_refs)):
        errors.append("duplicate_artifact_ref")
    for index, artifact in enumerate(state.get("artifact_index") or []):
        ref = artifact.get("ref")
        kind = artifact.get("kind")
        problems = _verify_evidence_ref(context["run_dir"], ref)
        for problem in problems:
            errors.append(
                {
                    "evidence missing": "evidence_missing",
                    "evidence digest mismatch": "evidence_digest_mismatch",
                    "evidence path escapes run root": "evidence_path_invalid",
                }.get(problem, "evidence_invalid")
            )
        payload = payloads.get(index)
        task_id = artifact.get("task_id")
        semantic_kind = payload.get("kind") if isinstance(payload, dict) else None
        if (
            not isinstance(kind, str)
            or not isinstance(ref, dict)
            or ref.get("kind") != kind
            or (semantic_kind is not None and semantic_kind != kind)
            or (kind in COMPLETION_EVIDENCE_KINDS and semantic_kind != kind)
        ):
            errors.append("artifact_kind_mismatch")
        if kind in COMPLETION_EVIDENCE_KINDS:
            packet_task = str(
                (payload.get("packet_task_id") if isinstance(payload, dict) else None)
                or task_id
                or (payload.get("task_id") if isinstance(payload, dict) else None)
                or ""
            )
            if not _bound_to_current(payload, state, _packet_sha(context, packet_task)):
                warnings.append("stale_revision_evidence")
            artifact_task = artifact.get("task_id")
            if (
                not isinstance(payload, dict)
                or not isinstance(artifact_task, str)
                or artifact_task not in (state.get("tasks") or {})
                or payload.get("task_id") != artifact_task
                or (
                    kind == "final_review"
                    and payload.get("packet_task_id") != artifact_task
                )
            ):
                errors.append("artifact_task_mismatch")
            if kind in {"task_review", "verification", "final_review"}:
                attempt = attempts.get(artifact.get("attempt_id"))
                if (
                    not isinstance(attempt, dict)
                    or attempt.get("kind") != kind
                    or (
                        kind != "final_review"
                        and attempt.get("task_id") != artifact_task
                    )
                    or (kind == "final_review" and attempt.get("task_id") is not None)
                ):
                    errors.append("artifact_attempt_mismatch")
    for verdict in state.get("verdicts") or []:
        attempt = attempts.get(verdict.get("attempt_id")) or {}
        packet_task = str(verdict.get("packet_task_id") or verdict.get("task_id") or attempt.get("task_id") or "")
        if not _bound_to_current(verdict, state, _packet_sha(context, packet_task)):
            warnings.append("stale_revision_evidence")
    return _dedupe(errors), _dedupe(warnings)


def _git_status(worktree: Path) -> tuple[list[str], str | None]:
    if not worktree.is_dir():
        return [], "worktree_missing"
    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        cwd=worktree,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode:
        return [], "worktree_identity_mismatch"
    entries = result.stdout.split(b"\0")
    changed: list[str] = []
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if not entry:
            continue
        if len(entry) < 4 or entry[2:3] != b" ":
            return [], "worktree_identity_mismatch"
        status_code = entry[:2]
        changed.append(os.fsdecode(entry[3:]))
        if b"R" in status_code or b"C" in status_code:
            if index >= len(entries) or not entries[index]:
                return [], "worktree_identity_mismatch"
            index += 1
    return changed, None


def _check_worktree_identity(context: dict[str, object]) -> tuple[list[str], list[str]]:
    manifest = context.get("manifest")
    if not isinstance(manifest, dict):
        return [], []
    try:
        worktree = resolve_ref(str(manifest["execution_worktree_ref"]))
    except (KeyError, ValueError):
        return ["worktree_identity_mismatch"], []
    _, error = _git_status(worktree)
    revision = _revision_validation(context)
    revision_errors = list(revision["errors"])
    revision_warnings = list(revision["warnings"])
    if error:
        return _dedupe([error, *revision_errors]), revision_warnings
    expected_head = (manifest.get("source_git") or {}).get("head")
    if expected_head:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=worktree,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if result.returncode or result.stdout.strip() != expected_head:
            return _dedupe(["worktree_identity_mismatch", *revision_errors]), revision_warnings
    return revision_errors, revision_warnings


def _check_attempt_structure(context: dict[str, object]) -> tuple[list[str], list[str]]:
    state = context.get("state")
    if not isinstance(state, dict):
        return [], []
    errors: list[str] = []
    attempts = state.get("attempts") or []
    ids = [item.get("attempt_id") for item in attempts]
    if any(not isinstance(item, str) or not item for item in ids) or len(ids) != len(set(ids)):
        errors.append("attempt_structure_invalid")
    by_id = {item.get("attempt_id"): item for item in attempts}
    for attempt in attempts:
        status = attempt.get("status")
        if status not in {"started", "completed", "failed", "interrupted"}:
            errors.append("attempt_structure_invalid")
            continue
        revision = attempt.get("worktree_revision")
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
            errors.append("attempt_structure_invalid")
        if status == "completed":
            kind = attempt.get("kind")
            attestation = attempt.get("attestation")
            if not isinstance(attestation, dict) or attestation.get("verified") is not True:
                errors.append("model_attestation_missing")
            else:
                route = SCOUT_ROUTE if kind == "scout" else CORE_ROUTE
                if (
                    attestation.get("actual_model") != route.model
                    or attestation.get("actual_reasoning") != route.reasoning
                    or attestation.get("mismatch") is True
                ):
                    errors.append("model_attestation_mismatch")
    for verdict in state.get("verdicts") or []:
        attempt = by_id.get(verdict.get("attempt_id"))
        if (
            not isinstance(attempt, dict)
            or attempt.get("task_id") != verdict.get("task_id")
            or attempt.get("kind") not in {"task_review", "verification", "final_review"}
            or verdict.get("status") not in {"passed", "changes_requested", "blocked", "inconclusive"}
            or not isinstance(verdict.get("findings"), list)
            or not isinstance(verdict.get("missing_evidence"), list)
        ):
            errors.append("verdict_structure_invalid")
    return _dedupe(errors), []


def _check_git_scope(context: dict[str, object]) -> tuple[list[str], list[str]]:
    manifest = context.get("manifest")
    if not isinstance(manifest, dict):
        return [], []
    worktree = resolve_ref(str(manifest.get("execution_worktree_ref", "")))
    changed, error = _git_status(worktree)
    if error:
        return [], []
    allowed: list[str] = []
    forbidden: list[str] = []
    for task in manifest.get("task_graph", []):
        if not isinstance(task, dict):
            continue
        contract = task.get("execution_contract")
        if not isinstance(contract, dict):
            contract = {}
        allowed.extend(str(path) for path in (contract.get("allowed_paths") or task.get("file_claims") or []))
        forbidden.extend(str(path) for path in (contract.get("forbidden_paths") or []))

    def matches(path: str, patterns: list[str]) -> bool:
        return matches_path(path, patterns)

    errors: list[str] = []
    violated = any(matches(path, forbidden) or not matches(path, allowed) for path in changed)
    if violated:
        errors.append("diff_scope_violation")

    tasks = {
        str(task.get("id")): task
        for task in manifest.get("task_graph", [])
        if isinstance(task, dict)
    }
    for event, parsed in _revision_validation(context)["records"]:
        task = tasks.get(str(event.get("task_id")))
        if not isinstance(task, dict):
            errors.append("revision_scope_violation")
            continue
        contract = task.get("execution_contract")
        if not isinstance(contract, dict):
            contract = {}
        task_allowed = [
            str(path)
            for path in (contract.get("allowed_paths") or task.get("file_claims") or [])
        ]
        task_forbidden = [str(path) for path in (contract.get("forbidden_paths") or [])]
        structural = tuple(
            path
            for path, before, after in zip(
                parsed.paths,
                parsed.before_fingerprints,
                parsed.after_fingerprints,
            )
            if (before == "absent") != (after == "absent")
            and (before.startswith("directory:") or after.startswith("directory:"))
        )
        delta = GitDelta(
            parsed.paths,
            parsed.sha256,
            parsed.raw,
            parsed.before_head != parsed.after_head
            or parsed.before_identity != parsed.after_identity,
            structural,
        )
        if scope_errors(delta, task_allowed, task_forbidden):
            errors.append("revision_scope_violation")
    return _dedupe(errors), []


def _check_task_states(context: dict[str, object]) -> tuple[list[str], list[str]]:
    state = context.get("state")
    if not isinstance(state, dict) or not state.get("tasks"):
        return ["task_graph_empty"], []
    return (["task_incomplete"] if any(task.get("status") != "completed" for task in state["tasks"].values()) else []), []


def _task_artifacts(context: dict[str, object], task_id: str, kinds: set[str]) -> list[tuple[dict, object | None]]:
    state = context["state"]
    payloads = _artifact_payloads(context)
    return [
        (artifact, payloads.get(index))
        for index, artifact in enumerate(state.get("artifact_index") or [])
        if artifact.get("task_id") == task_id and artifact.get("kind") in kinds
    ]


def _payload_passed(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    signals: list[bool] = []
    if "passed" in payload:
        signals.append(payload.get("passed") is True)
    if "status" in payload:
        signals.append(payload.get("status") == "passed")
    if "returncode" in payload:
        signals.append(payload.get("returncode") == 0)
    if not signals or not all(signals):
        return False
    findings = payload.get("findings", [])
    missing = payload.get("missing_evidence", [])
    if not isinstance(findings, list) or not all(isinstance(item, dict) for item in findings):
        return False
    if not isinstance(missing, list):
        return False
    if missing:
        return False
    return not any(
        isinstance(item, dict) and str(item.get("severity", "")).lower() == "critical"
        for item in findings
    )


def _payload_claims_pass(payload: object) -> bool:
    return isinstance(payload, dict) and (
        payload.get("passed") is True
        or payload.get("status") == "passed"
        or payload.get("returncode") == 0
    )


def _check_current_revision_acceptance(context: dict[str, object]) -> tuple[list[str], list[str]]:
    state = context.get("state")
    if not isinstance(state, dict):
        return [], []
    errors: list[str] = []
    if _revision_validation(context)["zero_unverified"]:
        errors.append("current_revision_patch_unverifiable")
    for task_id in state.get("tasks") or {}:
        packet_sha = _packet_sha(context, str(task_id))
        history = [
            payload
            for _, payload in _task_artifacts(context, str(task_id), {"acceptance"})
        ]
        latest = history[-1] if history else None
        if not _bound_to_current(latest, state, packet_sha) or not _payload_passed(latest):
            errors.append("current_revision_acceptance_not_passed")
    return _dedupe(errors), []


def _safe_passed_verdict(verdict: object) -> bool:
    return (
        isinstance(verdict, dict)
        and verdict.get("status") == "passed"
        and not verdict.get("missing_evidence")
        and not any(
            isinstance(item, dict) and str(item.get("severity", "")).lower() == "critical"
            for item in verdict.get("findings") or []
        )
    )


def _verdict_evidence_matches(verdict: object, evidence: object) -> bool:
    return (
        isinstance(verdict, dict)
        and isinstance(evidence, dict)
        and all(
            evidence.get(key) == verdict.get(key)
            for key in ("status", "findings", "missing_evidence")
        )
    )


def _check_current_revision_verdicts(context: dict[str, object]) -> tuple[list[str], list[str]]:
    state = context.get("state")
    if not isinstance(state, dict):
        return [], []
    attempts = {item.get("attempt_id"): item for item in state.get("attempts") or []}
    errors: list[str] = []
    for task_id in state.get("tasks") or {}:
        packet_sha = _packet_sha(context, str(task_id))
        for kind, code in (
            ("task_review", "current_revision_task_review_not_passed"),
            ("verification", "current_revision_verification_not_passed"),
        ):
            history = [
                verdict
                for verdict in state.get("verdicts") or []
                if verdict.get("task_id") == task_id
                and (attempts.get(verdict.get("attempt_id")) or {}).get("kind") == kind
            ]
            latest = history[-1] if history else None
            evidence = [
                payload
                for artifact, payload in _task_artifacts(context, str(task_id), {kind})
                if isinstance(latest, dict)
                and artifact.get("attempt_id") == latest.get("attempt_id")
            ]
            latest_evidence = evidence[-1] if evidence else None
            if (
                not _bound_to_current(latest, state, packet_sha)
                or not _safe_passed_verdict(latest)
                or not _bound_to_current(latest_evidence, state, packet_sha)
                or not _payload_passed(latest_evidence)
                or not _verdict_evidence_matches(latest, latest_evidence)
            ):
                errors.append(code)
        final_history = [
            verdict
            for verdict in state.get("verdicts") or []
            if verdict.get("task_id") is None
            and (attempts.get(verdict.get("attempt_id")) or {}).get("kind") == "final_review"
            and verdict.get("packet_task_id") == task_id
        ]
        latest_final = final_history[-1] if final_history else None
        final_evidence = [
            payload
            for artifact, payload in _task_artifacts(context, str(task_id), {"final_review"})
            if isinstance(latest_final, dict)
            and artifact.get("attempt_id") == latest_final.get("attempt_id")
        ]
        latest_final_evidence = final_evidence[-1] if final_evidence else None
        if (
            not _bound_to_current(latest_final, state, packet_sha)
            or not _safe_passed_verdict(latest_final)
            or not _bound_to_current(latest_final_evidence, state, packet_sha)
            or not _payload_passed(latest_final_evidence)
            or not _verdict_evidence_matches(latest_final, latest_final_evidence)
        ):
            errors.append("current_revision_final_review_not_passed")
    return _dedupe(errors), []


def _check_repository_checks(context: dict[str, object]) -> tuple[list[str], list[str]]:
    state = context.get("state")
    if not isinstance(state, dict):
        return [], []
    for task_id in state.get("tasks") or {}:
        packet_sha = _packet_sha(context, str(task_id))
        history = [
            payload
            for _, payload in _task_artifacts(context, str(task_id), {"repository_check", "repository_checks"})
        ]
        latest = history[-1] if history else None
        if not _bound_to_current(latest, state, packet_sha) or not _payload_passed(latest):
            return ["current_revision_repository_check_missing"], []
    return [], []


def _check_active_blockers(context: dict[str, object]) -> tuple[list[str], list[str]]:
    state = context.get("state")
    return (["active_blockers_present"] if isinstance(state, dict) and state.get("active_blockers") else []), []


def _canonical_ref(ref: object) -> str | None:
    return json.dumps(ref, sort_keys=True) if isinstance(ref, dict) else None


def _check_completion_audit(context: dict[str, object]) -> tuple[list[str], list[str]]:
    state = context.get("state")
    if not isinstance(state, dict):
        return [], []
    audit = state.get("completion_audit")
    expected_audit_keys = {
        "passed",
        "prompt_to_artifact_checklist",
        "verification_evidence",
        "residual_risk",
    }
    if not isinstance(audit, dict) or audit.get("passed") is not True:
        return ["completion_audit_missing"], []
    if set(audit) != expected_audit_keys or not isinstance(audit.get("residual_risk"), list):
        return ["completion_audit_incomplete"], []
    refs = audit.get("verification_evidence")
    if not isinstance(refs, list) or not refs:
        return ["completion_evidence_incomplete"], []
    canonical_supplied = [_canonical_ref(ref) for ref in refs]
    if None in canonical_supplied:
        return ["completion_evidence_incomplete"], []
    if len(canonical_supplied) != len(set(canonical_supplied)):
        return ["completion_evidence_duplicate"], []
    indexed = {
        _canonical_ref(item.get("ref")): item
        for item in state.get("artifact_index") or []
        if _canonical_ref(item.get("ref")) is not None
    }
    payloads = _artifact_payloads(context)
    required_records: list[tuple[dict, object]] = []
    unbound = False
    stale_keys: set[tuple[object, str]] = set()
    current_keys: set[tuple[object, str]] = set()
    for index, item in enumerate(state.get("artifact_index") or []):
        if item.get("kind") not in COMPLETION_EVIDENCE_KINDS:
            continue
        payload = payloads.get(index)
        packet_task = str(
            (payload.get("packet_task_id") if isinstance(payload, dict) else None)
            or item.get("task_id")
            or (payload.get("task_id") if isinstance(payload, dict) else None)
            or ""
        )
        binding = _binding_status(payload, state, _packet_sha(context, packet_task))
        evidence_key = (item.get("kind"), packet_task)
        if binding == "current":
            required_records.append((item, payload))
            current_keys.add(evidence_key)
        elif binding == "unbound":
            unbound = True
        else:
            stale_keys.add(evidence_key)
        if isinstance(item.get("ref"), dict) and _verify_evidence_ref(context["run_dir"], item["ref"]):
            return ["completion_evidence_invalid"], []
    if unbound:
        return ["unbound_completion_evidence"], []
    if stale_keys - current_keys:
        return ["stale_completion_evidence"], []
    required_refs = [_canonical_ref(item.get("ref")) for item, _ in required_records]
    if canonical_supplied != required_refs or any(ref not in indexed for ref in canonical_supplied):
        return ["completion_evidence_incomplete"], []
    expected_checklist = [
        {"kind": item.get("kind"), "task_id": item.get("task_id"), "ref": item.get("ref")}
        for item, _ in required_records
    ]
    if audit.get("prompt_to_artifact_checklist") != expected_checklist:
        return ["completion_checklist_incomplete"], []
    for ref, (_item, payload) in zip(refs, required_records):
        if _verify_evidence_ref(context["run_dir"], ref):
            return ["completion_evidence_invalid"], []
        if _payload_claims_pass(payload) and not _payload_passed(payload):
            return ["completion_evidence_not_passed"], []
    return [], []


CHECK_REGISTRY: dict[str, Callable[[dict[str, object]], tuple[list[str], list[str]]]] = {
    "schema": _check_schema,
    "manifest": _check_manifest,
    "packets": _check_packets,
    "event_chain": _check_event_chain,
    "snapshot_replay": _check_snapshot_replay,
    "artifacts": _check_artifacts,
    "worktree_identity": _check_worktree_identity,
    "attempt_structure": _check_attempt_structure,
    "git_scope": _check_git_scope,
    "task_states": _check_task_states,
    "current_revision_acceptance": _check_current_revision_acceptance,
    "current_revision_verdicts": _check_current_revision_verdicts,
    "repository_checks": _check_repository_checks,
    "active_blockers": _check_active_blockers,
    "completion_audit": _check_completion_audit,
}


def _validate(
    run_dir: Path,
    check_names: tuple[str, ...],
    candidate_state: dict | None = None,
) -> ValidationReport:
    run_dir = run_dir.expanduser().resolve()
    context = _context(run_dir, candidate_state)
    checks: dict[str, list[str]] = {}
    errors: list[str] = []
    warnings: list[str] = []
    for name in check_names:
        check_errors, check_warnings = CHECK_REGISTRY[name](context)
        check_errors = _dedupe(check_errors)
        check_warnings = _dedupe(check_warnings)
        checks[name] = check_errors
        errors.extend(check_errors)
        warnings.extend(check_warnings)
    errors = _dedupe(errors)
    warnings = _dedupe(warnings)
    classification = (
        "valid"
        if not errors
        else "unsupported_schema"
        if errors == ["unsupported_schema"]
        else "invalid"
    )
    return ValidationReport(classification, not errors, errors, warnings, checks)


def validate_integrity(run_dir: Path, candidate_state: dict | None = None) -> ValidationReport:
    return _validate(run_dir, INTEGRITY_CHECKS, candidate_state)


def validate_completion(run_dir: Path, candidate_state: dict | None = None) -> ValidationReport:
    return _validate(run_dir, COMPLETION_CHECKS, candidate_state)


def validate_run(run_dir: Path, candidate_state: dict | None = None) -> ValidationReport:
    run_dir = run_dir.expanduser().resolve()
    state = candidate_state
    if state is None:
        context = _context(run_dir, None)
        state = context.get("state") if isinstance(context.get("state"), dict) else None
    if isinstance(state, dict) and state.get("lifecycle") == "completed":
        return validate_completion(run_dir, candidate_state)
    return validate_integrity(run_dir, candidate_state)
