from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable

from .events import read_events, validate_chain
from .evidence import verify_ref
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
        "artifact_payloads": {},
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
    if candidate_state is None:
        context["state"] = replay_state
    return context


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _check_schema(context: dict[str, object]) -> tuple[list[str], list[str]]:
    marker = _schema_marker(context["run_dir"])
    if marker is not None and marker != "3":
        return ["unsupported_schema"], []
    state = context.get("state")
    if isinstance(state, dict) and state.get("schema_version") != "3":
        return ["state_schema_invalid"], []
    return [], []


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
    if not isinstance(ref, dict) or verify_ref(run_dir, ref):
        return None
    try:
        return json.loads((run_dir / str(ref["path"])).read_text(encoding="utf-8"))
    except (OSError, KeyError, json.JSONDecodeError, UnicodeDecodeError):
        return None


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


def _bound_to_current(record: object, state: dict, packet_sha256: str | None) -> bool:
    return (
        isinstance(record, dict)
        and "worktree_revision" in record
        and "worktree_patch_sha256" in record
        and "packet_sha256" in record
        and record.get("worktree_revision") == state.get("worktree_revision")
        and record.get("worktree_patch_sha256") == state.get("worktree_patch_sha256")
        and packet_sha256 is not None
        and record.get("packet_sha256") == packet_sha256
    )


def _check_artifacts(context: dict[str, object]) -> tuple[list[str], list[str]]:
    state = context.get("state")
    if not isinstance(state, dict):
        return [], []
    errors: list[str] = []
    warnings: list[str] = []
    payloads = _artifact_payloads(context)
    for index, artifact in enumerate(state.get("artifact_index") or []):
        ref = artifact.get("ref")
        problems = verify_ref(context["run_dir"], ref) if isinstance(ref, dict) else ["evidence missing"]
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
        if isinstance(payload, dict) and {
            "worktree_revision",
            "worktree_patch_sha256",
            "packet_sha256",
        }.issubset(payload):
            packet_task = str(payload.get("packet_task_id") or task_id or payload.get("task_id") or "")
            if not _bound_to_current(payload, state, _packet_sha(context, packet_task)):
                warnings.append("stale_revision_evidence")
    attempts = {item.get("attempt_id"): item for item in state.get("attempts") or []}
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
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=worktree,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode:
        return [], "worktree_identity_mismatch"
    return [line[3:].split(" -> ")[-1] for line in result.stdout.splitlines() if len(line) >= 4], None


def _check_worktree_identity(context: dict[str, object]) -> tuple[list[str], list[str]]:
    manifest = context.get("manifest")
    if not isinstance(manifest, dict):
        return [], []
    try:
        worktree = resolve_ref(str(manifest["execution_worktree_ref"]))
    except (KeyError, ValueError):
        return ["worktree_identity_mismatch"], []
    _, error = _git_status(worktree)
    if error:
        return [error], []
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
            return ["worktree_identity_mismatch"], []
    return [], []


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
        candidate = PurePosixPath(path)
        return any(
            path == pattern
            or candidate.match(pattern)
            or (
                pattern.endswith("/**")
                and bool(pattern[:-3].rstrip("/"))
                and (
                    path == pattern[:-3].rstrip("/")
                    or path.startswith(f"{pattern[:-3].rstrip('/')}/")
                )
            )
            for pattern in patterns
        )

    violated = any(matches(path, forbidden) or not matches(path, allowed) for path in changed)
    return (["diff_scope_violation"] if violated else []), []


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
    return isinstance(payload, dict) and (
        payload.get("passed") is True
        or payload.get("status") == "passed"
        or (payload.get("returncode") == 0 and payload.get("passed") is not False)
    )


def _check_current_revision_acceptance(context: dict[str, object]) -> tuple[list[str], list[str]]:
    state = context.get("state")
    if not isinstance(state, dict):
        return [], []
    errors: list[str] = []
    for task_id in state.get("tasks") or {}:
        packet_sha = _packet_sha(context, str(task_id))
        current = [
            payload
            for _, payload in _task_artifacts(context, str(task_id), {"acceptance"})
            if _bound_to_current(payload, state, packet_sha)
        ]
        if not any(_payload_passed(payload) for payload in current):
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
            candidates = [
                verdict
                for verdict in state.get("verdicts") or []
                if verdict.get("task_id") == task_id
                and (attempts.get(verdict.get("attempt_id")) or {}).get("kind") == kind
                and _bound_to_current(verdict, state, packet_sha)
            ]
            if not any(_safe_passed_verdict(verdict) for verdict in candidates):
                errors.append(code)
        final_candidates = [
            verdict
            for verdict in state.get("verdicts") or []
            if verdict.get("task_id") is None
            and (attempts.get(verdict.get("attempt_id")) or {}).get("kind") == "final_review"
            and verdict.get("packet_task_id") == task_id
            and _bound_to_current(verdict, state, packet_sha)
        ]
        if not any(_safe_passed_verdict(verdict) for verdict in final_candidates):
            errors.append("current_revision_final_review_not_passed")
    return _dedupe(errors), []


def _check_repository_checks(context: dict[str, object]) -> tuple[list[str], list[str]]:
    state = context.get("state")
    if not isinstance(state, dict):
        return [], []
    for task_id in state.get("tasks") or {}:
        packet_sha = _packet_sha(context, str(task_id))
        current = [
            payload
            for _, payload in _task_artifacts(context, str(task_id), {"repository_check", "repository_checks"})
            if _bound_to_current(payload, state, packet_sha)
        ]
        if not any(_payload_passed(payload) for payload in current):
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
    if not isinstance(audit, dict) or audit.get("passed") is not True:
        return ["completion_audit_missing"], []
    if not audit.get("prompt_to_artifact_checklist"):
        return ["completion_audit_incomplete"], []
    refs = audit.get("verification_evidence")
    if not isinstance(refs, list) or not refs:
        return ["completion_evidence_incomplete"], []
    indexed = {
        _canonical_ref(item.get("ref")): item
        for item in state.get("artifact_index") or []
        if _canonical_ref(item.get("ref")) is not None
    }
    payloads = _artifact_payloads(context)
    required = {
        _canonical_ref(item.get("ref"))
        for index, item in enumerate(state.get("artifact_index") or [])
        if item.get("kind") in {"acceptance", "repository_check", "repository_checks"}
        and _bound_to_current(
            payloads.get(index),
            state,
            _packet_sha(context, str(item.get("task_id") or "")),
        )
    }
    supplied = {_canonical_ref(ref) for ref in refs}
    if None in supplied or not supplied.issubset(indexed) or not required.issubset(supplied):
        return ["completion_evidence_incomplete"], []
    for ref in refs:
        if verify_ref(context["run_dir"], ref):
            return ["completion_evidence_invalid"], []
        artifact = indexed[_canonical_ref(ref)]
        payload = _read_ref_payload(context["run_dir"], ref)
        task_id = str(artifact.get("task_id") or (payload.get("task_id") if isinstance(payload, dict) else "") or "")
        if not _bound_to_current(payload, state, _packet_sha(context, task_id)):
            return ["stale_completion_evidence"], []
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
