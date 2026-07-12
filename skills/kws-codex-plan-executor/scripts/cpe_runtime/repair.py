from __future__ import annotations

import json
import stat
import subprocess
import shutil
from copy import deepcopy
from dataclasses import asdict, dataclass
from pathlib import Path

from .evidence import verify_ref
from .events import read_events
from .kernel import Kernel, Transition, rebuild_snapshot
from .manifest import load_verified_manifest
from .packets import packet_entry
from .projector import RETRY_PHASE_STATES, project
from .reconciliation import reconcile
from .validation import validate_integrity
from .git_delta import matches_path, working_tree_changed_files


SAFE_ACTIONS = {
    "rebuild_snapshot",
    "regenerate_derived_reports",
    "mark_stale_attempt_interrupted",
    "reconnect_existing_evidence",
    "resolve_blocker",
    "schedule_retry",
}


@dataclass(frozen=True)
class RepairPlan:
    actions: list[str]
    findings: list[dict[str, object]]
    dry_run: bool = True

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def scheduler_bookkeeping(state: dict) -> dict:
    """Derive v4 repair roots/backlog from the immutable decision ledger."""

    projected = deepcopy(state)
    roots: dict[str, int] = {}
    backlog: list[dict[str, object]] = []
    for decision in projected.get("decisions", []):
        if not isinstance(decision, dict):
            continue
        if decision.get("decision_kind") == "repair_root_updated":
            root = decision.get("root_cause_key")
            count = decision.get("repair_count")
            if isinstance(root, str) and root and type(count) is int and 0 <= count <= 2:
                roots[root] = max(roots.get(root, 0), count)
        elif decision.get("decision_kind") == "backlog_added":
            item = decision.get("backlog_item")
            if isinstance(item, dict) and item not in backlog:
                backlog.append(dict(item))
    projected["repair_roots"] = roots
    projected["backlog"] = backlog
    return projected


def record_repair_root(kernel: Kernel, *, task_id: str, root_cause_key: str, count: int) -> None:
    if not root_cause_key or type(count) is not int or count not in {1, 2}:
        raise ValueError("invalid_repair_root_update")
    kernel.transition(
        Transition(
            "decision.recorded",
            {
                "decision_kind": "repair_root_updated",
                "selected_action": "repair",
                "basis": "bounded same-root repair policy",
                "approval_basis": "standing_autonomy_policy",
                "root_cause_key": root_cause_key,
                "repair_count": count,
            },
            task_id=task_id,
        )
    )


def record_backlog(
    kernel: Kernel,
    *,
    task_id: str,
    category: str,
    root_cause_key: str,
    finding: dict[str, object],
) -> None:
    item = {
        "task_id": task_id,
        "category": category,
        "root_cause_key": root_cause_key,
        "finding": deepcopy(finding),
    }
    kernel.transition(
        Transition(
            "decision.recorded",
            {
                "decision_kind": "backlog_added",
                "selected_action": "backlog_and_continue",
                "basis": "non-release-impact finding after bounded adjudication",
                "approval_basis": "standing_autonomy_policy",
                "backlog_item": item,
            },
            task_id=task_id,
        )
    )


def prepare_repaired_candidate(product_worktree: Path, rejected: object) -> None:
    """Collapse a rejected candidate plus repair into one new direct child."""

    worktree = product_worktree.expanduser().resolve()
    commit = getattr(rejected, "commit", None)
    predecessor = getattr(rejected, "predecessor", None)
    if not isinstance(commit, str) or not isinstance(predecessor, str):
        raise ValueError("rejected_candidate_invalid")
    head = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=worktree,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if head.returncode or head.stdout.strip() != commit:
        raise ValueError("rejected_candidate_head_mismatch")
    reset = subprocess.run(
        ["git", "reset", "--mixed", predecessor],
        cwd=worktree,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if reset.returncode:
        raise RuntimeError("repair_candidate_reset_failed")


def restore_interrupted_worktree(
    product_worktree: Path,
    target_commit: str,
    *,
    file_claims: tuple[str, ...],
    forbidden_paths: tuple[str, ...],
) -> None:
    """Restore only a measured, wholly in-claim partial task delta."""

    worktree = product_worktree.expanduser().resolve()
    if (
        len(target_commit) != 40
        or any(character not in "0123456789abcdef" for character in target_commit)
    ):
        raise ValueError("restore_target_invalid")
    head_result = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=worktree,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if head_result.returncode:
        raise RuntimeError("evidence_integrity_failure")
    head = head_result.stdout.strip()
    committed = subprocess.run(
        ["git", "diff", "--name-only", "-z", target_commit, head, "--"],
        cwd=worktree,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if committed.returncode:
        raise RuntimeError("evidence_integrity_failure")
    committed_paths = tuple(
        path.decode("utf-8", "surrogateescape")
        for path in committed.stdout.split(b"\0")
        if path
    )
    working_paths = working_tree_changed_files(worktree)
    measured = tuple(dict.fromkeys((*committed_paths, *working_paths)))
    if any(
        matches_path(path, forbidden_paths)
        or not matches_path(path, file_claims)
        for path in measured
    ):
        raise RuntimeError("evidence_integrity_failure")

    reset = subprocess.run(
        ["git", "reset", "--hard", target_commit],
        cwd=worktree,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if reset.returncode:
        raise RuntimeError("evidence_integrity_failure")
    for path in working_paths:
        candidate = worktree / path
        try:
            candidate.relative_to(worktree)
        except ValueError as exc:
            raise RuntimeError("evidence_integrity_failure") from exc
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", path],
            cwd=worktree,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if tracked.returncode == 0 or not candidate.exists():
            continue
        if candidate.is_symlink() or candidate.is_file():
            candidate.unlink()
        elif candidate.is_dir():
            shutil.rmtree(candidate)
        else:
            raise RuntimeError("evidence_integrity_failure")
    final_head = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=worktree,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if (
        final_head.returncode
        or final_head.stdout.strip() != target_commit
        or working_tree_changed_files(worktree)
    ):
        raise RuntimeError("evidence_integrity_failure")


def plan_repairs(run_dir: Path) -> RepairPlan:
    report = reconcile(run_dir)
    actions = list(
        dict.fromkeys(
            str(item["repair_action"])
            for item in report.findings
            if item.get("repair_action") in SAFE_ACTIONS
        )
    )
    return RepairPlan(actions, report.findings)


def _state(run_dir: Path, manifest: dict) -> dict:
    return project(manifest, read_events(run_dir / "events.jsonl"))


def _canonical(value: object) -> str | None:
    return json.dumps(value, sort_keys=True, separators=(",", ":")) if isinstance(value, dict) else None


def _refs_indexed(state: dict, refs: object) -> bool:
    if not isinstance(refs, list) or not refs or any(not isinstance(ref, dict) for ref in refs):
        return False
    indexed = {
        _canonical(item.get("ref"))
        for item in state.get("artifact_index") or []
        if isinstance(item, dict)
    }
    return all(_canonical(ref) in indexed for ref in refs)


def _candidate_evidence(
    run_dir: Path,
    details: dict[str, object],
) -> tuple[dict[str, object], dict[str, object]] | None:
    requested_ref = details.get("ref")
    requested_digest = details.get("sha256")
    if isinstance(requested_ref, dict):
        ref_digest = requested_ref.get("sha256")
        if requested_digest is not None and requested_digest != ref_digest:
            return None
        requested_digest = ref_digest
    if (
        not isinstance(requested_digest, str)
        or len(requested_digest) != 64
        or any(character not in "0123456789abcdef" for character in requested_digest)
    ):
        return None
    evidence_root = run_dir / "artifacts" / "evidence"
    try:
        for ancestor in (run_dir / "artifacts", evidence_root):
            metadata = ancestor.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                return None
    except OSError:
        return None
    candidates: list[tuple[dict[str, object], dict[str, object]]] = []
    try:
        paths = list(evidence_root.glob(f"*/{requested_digest}.json"))
    except OSError:
        return None
    for path in paths:
        kind = path.parent.name
        try:
            parent_metadata = path.parent.lstat()
            path_metadata = path.lstat()
        except OSError:
            continue
        if (
            stat.S_ISLNK(parent_metadata.st_mode)
            or not stat.S_ISDIR(parent_metadata.st_mode)
            or stat.S_ISLNK(path_metadata.st_mode)
            or not stat.S_ISREG(path_metadata.st_mode)
        ):
            continue
        ref: dict[str, object] = {
            "kind": kind,
            "path": path.relative_to(run_dir).as_posix(),
            "sha256": requested_digest,
            "media_type": "application/json",
        }
        if verify_ref(run_dir, ref) != []:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        candidates.append((ref, payload))
    if len(candidates) != 1:
        return None
    candidate_ref, payload = candidates[0]
    if isinstance(requested_ref, dict) and _canonical(requested_ref) != _canonical(candidate_ref):
        return None
    return candidate_ref, payload


def _evidence_provenance(
    manifest: dict,
    state: dict,
    ref: dict[str, object],
    payload: dict[str, object],
    task_id: object,
    attempt_id: object,
) -> bool:
    if not isinstance(task_id, str) or task_id not in state.get("tasks", {}):
        return False
    kind = ref.get("kind")
    if payload.get("kind") != kind:
        return False
    if payload.get("task_id") != task_id:
        return False
    if payload.get("packet_task_id") is not None and payload.get("packet_task_id") != task_id:
        return False
    payload_attempt = payload.get("attempt_id")
    try:
        expected_packet = packet_entry(manifest, task_id)["sha256"]
    except ValueError:
        return False
    state_revision = state.get("worktree_revision")
    payload_revision = payload.get("worktree_revision")
    revisions_are_strict = (
        isinstance(state_revision, int)
        and not isinstance(state_revision, bool)
        and state_revision >= 0
        and isinstance(payload_revision, int)
        and not isinstance(payload_revision, bool)
        and payload_revision >= 0
    )
    binding_ok = (
        revisions_are_strict
        and payload_revision == state_revision
        and payload.get("worktree_patch_sha256") == state.get("worktree_patch_sha256")
        and payload.get("packet_sha256") == expected_packet
    )
    if kind == "acceptance":
        if not isinstance(attempt_id, str) or payload_attempt != attempt_id:
            return False
        prefix = f"{task_id}.acceptance."
        ordinal = attempt_id.removeprefix(prefix) if attempt_id.startswith(prefix) else ""
        expected_ordinal = 1 + sum(
            1
            for artifact in state.get("artifact_index") or []
            if isinstance(artifact, dict)
            and artifact.get("task_id") == task_id
            and artifact.get("kind") == "acceptance"
        )
        return (
            bool(ordinal)
            and ordinal.isdigit()
            and int(ordinal) > 0
            and str(int(ordinal)) == ordinal
            and int(ordinal) == expected_ordinal
            and binding_ok
        )
    if kind == "repository_check":
        if not isinstance(attempt_id, str) or payload_attempt != attempt_id:
            return False
        parts = attempt_id.split(".")
        if len(parts) != 4 or parts[:2] != ["run", "repository_checks"]:
            return False
        revision, ordinal = parts[2:]
        if (
            not revision.isdigit()
            or not ordinal.isdigit()
            or str(int(revision)) != revision
            or str(int(ordinal)) != ordinal
            or int(ordinal) < 1
            or not revisions_are_strict
            or int(revision) != state_revision
            or not binding_ok
        ):
            return False
        by_id = {
            str(task["id"]): task
            for task in manifest.get("task_graph") or []
            if isinstance(task, dict) and task.get("id") is not None
        }
        ordered: list[str] = []
        ready = [identifier for identifier, task in by_id.items() if not task.get("dependencies")]
        seen: set[str] = set()
        while ready:
            identifier = ready.pop(0)
            if identifier in seen:
                continue
            seen.add(identifier)
            ordered.append(identifier)
            for candidate_id, candidate in by_id.items():
                dependencies = [str(item) for item in candidate.get("dependencies") or []]
                if candidate_id not in seen and set(dependencies).issubset(seen):
                    ready.append(candidate_id)
        return len(ordered) == len(by_id) and int(ordinal) <= len(ordered) and ordered[int(ordinal) - 1] == task_id
    if attempt_id is None:
        return payload_attempt is None and ref.get("kind") not in {"task_review", "verification", "final_review"}
    if not isinstance(attempt_id, str) or payload_attempt != attempt_id:
        return False
    attempts = [
        item
        for item in state.get("attempts") or []
        if isinstance(item, dict) and item.get("attempt_id") == attempt_id
    ]
    if len(attempts) != 1:
        return False
    attempt = attempts[0]
    if ref.get("kind") != attempt.get("kind"):
        return False
    if ref.get("kind") == "final_review":
        return attempt.get("task_id") is None and payload.get("packet_task_id") == task_id
    return attempt.get("task_id") == task_id


def _derive_delta(action: str, details: dict[str, object], before: dict) -> dict[str, object]:
    if action == "rebuild_snapshot":
        return {"snapshot_matches_replay": True}
    if action == "mark_stale_attempt_interrupted" and isinstance(details.get("attempt_id"), str):
        return {f"attempt_status:{details['attempt_id']}": "interrupted"}
    if action == "resolve_blocker" and isinstance(details.get("blocker_id"), str):
        return {f"blocker_status:{details['blocker_id']}": "resolved"}
    if action == "schedule_retry" and isinstance(details.get("task_id"), str):
        phase = details.get("phase")
        target = RETRY_PHASE_STATES.get(str(phase))
        return {f"task_status:{details['task_id']}": target} if target else {}
    if action == "reconnect_existing_evidence":
        return {"artifact_index_count": len(before.get("artifact_index") or []) + 1}
    return {}


def _list_record(items: object, identity: str) -> object:
    if not isinstance(items, list):
        return None
    keys = ("attempt_id", "blocker_id", "task_id")
    matches = [item for item in items if isinstance(item, dict) and any(item.get(key) == identity for key in keys)]
    return matches[0] if len(matches) == 1 else None


def _path_value(state: dict, path: str) -> object:
    value: object = state
    for part in path.split("."):
        if isinstance(value, dict):
            if part not in value:
                return None
            value = value[part]
        elif isinstance(value, list):
            value = _list_record(value, part)
            if value is None:
                return None
        else:
            return None
    return value


def _observe(run_dir: Path, state: dict, expected: dict[str, object]) -> tuple[bool, dict[str, object]]:
    observed: dict[str, object] = {}
    for path, wanted in expected.items():
        if path == "snapshot_matches_replay":
            try:
                snapshot = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                value: object = False
            else:
                value = snapshot == state
        elif path == "artifact_index_count":
            value = len(state.get("artifact_index") or [])
        elif path.startswith("attempt_status:"):
            record = _list_record(state.get("attempts"), path.removeprefix("attempt_status:"))
            value = record.get("status") if isinstance(record, dict) else None
        elif path.startswith("blocker_status:"):
            record = _list_record(state.get("blocker_history"), path.removeprefix("blocker_status:"))
            value = record.get("status") if isinstance(record, dict) else None
        elif path.startswith("task_status:"):
            task = state.get("tasks", {}).get(path.removeprefix("task_status:"))
            value = task.get("status") if isinstance(task, dict) else None
        else:
            value = _path_value(state, path)
        observed[path] = value
    return observed == expected, observed


def _not_applied(action: str, expected: dict[str, object], observed: dict[str, object] | None = None) -> dict[str, object]:
    return {
        "action": action,
        "applied": False,
        "reason": "expected_projection_delta_not_observed",
        "expected_projection_delta": expected,
        "observed_projection_delta": observed or {},
    }


def apply_repair(
    run_dir: Path,
    action: str,
    *,
    details: dict[str, object] | None = None,
    expected_projection_delta: dict[str, object] | None = None,
) -> dict[str, object]:
    """Apply one compensating action and prove its declared replay projection."""
    run_dir = run_dir.expanduser().resolve()
    if action not in SAFE_ACTIONS:
        raise ValueError("unsafe repair action")
    manifest = load_verified_manifest(run_dir / "run_manifest.json")
    before = _state(run_dir, manifest)
    details = dict(details or {})
    derived = _derive_delta(action, details, before)
    expected = dict(
        derived
        if expected_projection_delta is None
        else expected_projection_delta
    )
    if not expected or any(not isinstance(path, str) or not path for path in expected):
        raise ValueError("expected_projection_delta_required")
    if not derived or expected != derived:
        raise ValueError("expected_projection_delta_mismatch")

    validation = validate_integrity(run_dir)
    allowed = {"snapshot_missing", "snapshot_replay_mismatch"} if action == "rebuild_snapshot" else set()
    if set(validation.errors) - allowed:
        raise ValueError(f"repair_precondition_invalid:{','.join(validation.errors)}")

    kernel = Kernel(run_dir)
    changed = False
    if action == "rebuild_snapshot":
        if action not in plan_repairs(run_dir).actions:
            return _not_applied(action, expected)
        rebuild_snapshot(run_dir)
        changed = True
    elif action == "regenerate_derived_reports":
        return _not_applied(action, expected)
    elif action == "mark_stale_attempt_interrupted":
        attempt_id = details.get("attempt_id")
        matches = [item for item in before.get("attempts") or [] if item.get("attempt_id") == attempt_id and item.get("status") == "started"]
        refs = details.get("evidence_refs") or (matches[0].get("evidence_refs") if len(matches) == 1 else None)
        if len(matches) == 1 and _refs_indexed(before, refs):
            attempt = matches[0]
            kernel.transition(
                Transition(
                    "attempt.completed",
                    {
                        "status": "interrupted",
                        "attestation": {"verified": False, "source": "recovery"},
                        "usage": {},
                        "latency_ms": 0,
                        "evidence_refs": refs,
                    },
                    task_id=attempt.get("task_id"),
                    attempt_id=str(attempt_id),
                )
            )
            changed = True
    elif action == "reconnect_existing_evidence":
        task_id = details.get("task_id")
        attempt_id = details.get("attempt_id")
        already = [_canonical(item.get("ref")) for item in before.get("artifact_index") or [] if isinstance(item, dict)]
        candidate = _candidate_evidence(run_dir, details)
        ref, payload = candidate if candidate is not None else (None, None)
        if (
            isinstance(ref, dict)
            and isinstance(payload, dict)
            and _canonical(ref) not in already
            and _evidence_provenance(manifest, before, ref, payload, task_id, attempt_id)
        ):
            kernel.transition(
                Transition(
                    "evidence.attached",
                    {"kind": ref.get("kind"), "ref": ref},
                    task_id=task_id,
                    attempt_id=str(attempt_id) if attempt_id is not None else None,
                )
            )
            changed = True
    elif action == "resolve_blocker":
        blocker_id = details.get("blocker_id")
        matches = [item for item in before.get("active_blockers") or [] if item.get("blocker_id") == blocker_id]
        refs = details.get("evidence_refs") or (matches[0].get("evidence_refs") if len(matches) == 1 else None)
        if len(matches) == 1 and _refs_indexed(before, refs):
            blocker = matches[0]
            kernel.transition(
                Transition(
                    "blocker.resolved",
                    {"blocker_id": blocker_id, "evidence_refs": refs, "resolution": "evidence_backed_recovery"},
                    task_id=blocker.get("task_id"),
                )
            )
            changed = True
    elif action == "schedule_retry":
        task_id = details.get("task_id")
        phase = details.get("phase")
        refs = details.get("evidence_refs")
        if (
            isinstance(task_id, str)
            and before.get("tasks", {}).get(task_id, {}).get("status") == "blocked"
            and phase in RETRY_PHASE_STATES
            and not any(item.get("task_id") == task_id for item in before.get("active_blockers") or [])
            and _refs_indexed(before, refs)
        ):
            kernel.transition(
                Transition(
                    "task.retry_scheduled",
                    {
                        "phase": phase,
                        "root_cause_key": str(details.get("root_cause_key") or f"resume:{phase}"),
                        "worktree_revision": before.get("worktree_revision", 0),
                        "evidence_refs": refs,
                    },
                    task_id=task_id,
                )
            )
            changed = True

    after = _state(run_dir, manifest)
    observed_ok, observed = _observe(run_dir, after, expected)
    if not changed or not observed_ok:
        return _not_applied(action, expected, observed)
    kernel.transition(
        Transition(
            "repair.applied",
            {
                "action": action,
                "before": {path: _observe(run_dir, before, {path: value})[1][path] for path, value in expected.items()},
                "after": observed,
                "expected_projection_delta": expected,
                "observed_projection_delta": observed,
                "applied": True,
            },
        )
    )
    return {
        "action": action,
        "applied": True,
        "expected_projection_delta": expected,
        "observed_projection_delta": observed,
        "validation": validate_integrity(run_dir).as_dict(),
    }
