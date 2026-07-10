#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from cpe_runtime.attempt_controller import validate_verdict
from cpe_runtime.events import append_event, read_events
from cpe_runtime.evidence import put_json
from cpe_runtime.kernel import RunKernel, Transition, rebuild_snapshot
from cpe_runtime.manifest import create_manifest, load_verified_manifest
from cpe_runtime.model_policy import CORE_ROUTE
from cpe_runtime.packets import build_packet
from cpe_runtime.projector import project
from cpe_runtime.scheduler import run_tasks
from cpe_runtime.worker import Worker, WorkerError, WorkerRequest
from cpe_runtime.validation import validate_completion, validate_integrity

from check_validation_consumer_parity import (
    EXPECTED_FALSE_COMPLETION_CODES,
    make_v3_run,
    record_revision,
)


def rejected(message: str, fn) -> bool:
    try:
        fn()
    except WorkerError as exc:
        return str(exc) == message
    return False


def worker_rejects_result(message: str, payload: dict[str, object]) -> bool:
    request = WorkerRequest(
        attempt_id="T1.task_review.fault",
        attempt_kind="task_review",
        prompt="{}",
        worktree=Path("/tmp/cpe-verdict-fault-worktree"),
        read_only=True,
        verdict_capable=True,
        task_id="T1",
        packet_path="artifacts/task-packets/T1.json",
        packet_sha256="a" * 64,
        worktree_revision=7,
    )
    provider_payload = {
        **payload,
        "_provider_metadata": {
            "model": "gpt-5.6-sol",
            "reasoning": "high",
            "trusted_source": "fault-fixture",
        },
    }
    return rejected(message, lambda: Worker(provider=lambda _request, _argv: provider_payload).run(request))


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def _scope_result(role: str, revision: int, changed_files: list[str]) -> dict[str, object]:
    verdict = None
    if role in {"task_review", "verification", "final_review"}:
        verdict = {
            "status": "passed",
            "findings": [],
            "missing_evidence": [],
            "worktree_revision": revision,
        }
    return {
        "status": "completed",
        "summary": role,
        "changed_files": changed_files,
        "findings": [],
        "evidence_refs": [],
        "missing_evidence": [],
        "verification": [],
        "verdict": verdict,
        "_provider_metadata": {
            "model": CORE_ROUTE.model,
            "reasoning": CORE_ROUTE.reasoning,
            "trusted_source": "scope-fault-fixture",
        },
    }


def _scope_fixture(
    root: Path,
    *,
    forbidden_paths: list[str] | None = None,
    allowed_paths: list[str] | None = None,
    t1_claims: list[str] | None = None,
) -> tuple[Path, Path, list[dict], RunKernel]:
    plan = root / "plan.md"
    pricing = root / "pricing.json"
    plan.write_text("# scope fault\n", encoding="utf-8")
    pricing.write_text("{}\n", encoding="utf-8")
    worktree = root / "worktree"
    worktree.mkdir()
    _run(["git", "init", "-q"], worktree).check_returncode()
    _run(["git", "config", "user.email", "eval@example.com"], worktree).check_returncode()
    _run(["git", "config", "user.name", "Eval"], worktree).check_returncode()
    (worktree / "owned-a.txt").write_text("a0\n", encoding="utf-8")
    (worktree / "owned-b.txt").write_text("b0\n", encoding="utf-8")
    (worktree / ".gitignore").write_text("ignored-forbidden.bin\n", encoding="utf-8")
    _run(["git", "add", "-A"], worktree).check_returncode()
    _run(["git", "commit", "-q", "-m", "bootstrap"], worktree).check_returncode()
    _run(["git", "branch", "same-commit-branch"], worktree).check_returncode()
    info_exclude = worktree / ".git" / "info" / "exclude"
    info_exclude.write_text(
        info_exclude.read_text(encoding="utf-8") + "\nignored-unclaimed.bin\n",
        encoding="utf-8",
    )
    head = _run(["git", "rev-parse", "HEAD"], worktree).stdout.strip()
    claims = list(t1_claims or ["owned-a.txt"])
    tasks = [
        {
            "id": "T1",
            "title": "owns a",
            "dependencies": [],
            "file_claims": claims,
            "execution_contract": {
                "allowed_paths": list(allowed_paths or claims),
                "forbidden_paths": list(forbidden_paths or []),
            },
            "acceptance_command": "true",
        },
        {
            "id": "T2",
            "title": "owns b",
            "dependencies": ["T1"],
            "file_claims": ["owned-b.txt"],
            "acceptance_command": "true",
        },
    ]
    drafts = [build_packet(SimpleNamespace(sources=(), spec_manifest=None), task) for task in tasks]
    manifest = create_manifest(
        "scope-fault", "interactive", root, worktree, plan, None, tasks, pricing,
        source_head=head,
    )
    kernel = RunKernel.initialize(root / "run", manifest, drafts)
    return worktree, kernel.run_dir, tasks, kernel


def _scope_fault(
    commit_head: bool,
    invalid_worker_result: bool = False,
    *,
    ignored_path: str | None = None,
    ignored_forbidden: bool = False,
    unexpected_exception: bool = False,
    delete_git: bool = False,
    delete_index: bool = False,
    stage_allowed: bool = False,
    switch_same_commit: bool = False,
    nested_git_file: bool = False,
    empty_directory: bool = False,
    chmod_file: bool = False,
    chmod_directory: bool = False,
) -> dict[str, bool]:
    with tempfile.TemporaryDirectory(prefix="cpe-scope-fault-") as raw:
        forbidden_paths = [ignored_path] if ignored_path and ignored_forbidden else []
        worktree, run_dir, tasks, kernel = _scope_fixture(
            Path(raw), forbidden_paths=forbidden_paths
        )
        launched: list[str] = []

        def provider(request, _argv):
            launched.append(request.attempt_kind)
            reported: list[str] = []
            if request.attempt_kind == "implementation" and request.task_id == "T1":
                if delete_git:
                    shutil.rmtree(worktree / ".git")
                elif delete_index:
                    (worktree / ".git" / "index").unlink()
                elif stage_allowed:
                    (worktree / "owned-a.txt").write_text("staged allowed write\n", encoding="utf-8")
                    _run(["git", "add", "owned-a.txt"], worktree).check_returncode()
                    reported = ["owned-a.txt"]
                elif switch_same_commit:
                    _run(["git", "switch", "-q", "same-commit-branch"], worktree).check_returncode()
                elif nested_git_file:
                    (worktree / "hidden").mkdir()
                    (worktree / "hidden" / ".git").write_bytes(b"nested git name")
                elif empty_directory:
                    (worktree / "empty-unclaimed").mkdir()
                elif chmod_file:
                    sealed_file = worktree / "sealed-unclaimed.bin"
                    sealed_file.write_bytes(b"sealed\x00file")
                    sealed_file.chmod(0)
                elif chmod_directory:
                    sealed_directory = worktree / "sealed-unclaimed-dir"
                    sealed_directory.mkdir()
                    sealed_directory.chmod(0)
                elif ignored_path:
                    (worktree / ignored_path).write_bytes(b"\x00ignored write")
                elif commit_head:
                    (worktree / "owned-a.txt").write_text("a1\n", encoding="utf-8")
                    _run(["git", "add", "owned-a.txt"], worktree).check_returncode()
                    _run(["git", "commit", "-q", "-m", "worker commit"], worktree).check_returncode()
                    reported = ["owned-a.txt"]
                else:
                    (worktree / "owned-b.txt").write_text("cross-task\n", encoding="utf-8")
                    reported = ["owned-a.txt"]
                if invalid_worker_result:
                    return {"status": "completed"}
                if unexpected_exception:
                    raise RuntimeError("provider exploded after write")
            return _scope_result(request.attempt_kind, request.worktree_revision, reported)

        try:
            result = run_tasks(tasks, Worker(provider=provider), kernel)
        except Exception as exc:
            result = {"status": "error", "reason": str(exc)}
        manifest = load_verified_manifest(run_dir / "run_manifest.json")
        events = read_events(run_dir / "events.jsonl")
        state = project(manifest, events)
        revision_indexes = [index for index, event in enumerate(events) if event["type"] == "worktree.revision_recorded"]
        blocker_indexes = [index for index, event in enumerate(events) if event["type"] == "blocker.opened"]
        if stage_allowed:
            expected_changed_files = ["owned-a.txt"]
        elif nested_git_file:
            expected_changed_files = ["hidden", "hidden/.git"]
        elif empty_directory:
            expected_changed_files = ["empty-unclaimed"]
        elif chmod_file:
            expected_changed_files = ["sealed-unclaimed.bin"]
        elif chmod_directory:
            expected_changed_files = ["sealed-unclaimed-dir"]
        elif delete_git or delete_index or commit_head or switch_same_commit:
            expected_changed_files = []
        else:
            expected_changed_files = [ignored_path or "owned-b.txt"]
        changed_path = expected_changed_files[0] if expected_changed_files else "owned-b.txt"
        expected_root = (
            "worktree_head_changed"
            if commit_head
            or delete_git
            or delete_index
            or stage_allowed
            or switch_same_commit
            else f"task_scope:T1:{changed_path}"
        )
        expected_scope_errors = [
            (
                f"forbidden_write:{path}"
                if ignored_forbidden
                else f"unclaimed_write:{path}"
            )
            for path in expected_changed_files
        ]
        blocker = state["active_blockers"][0] if state["active_blockers"] else {}
        completed_attempts = [
            event for event in events if event["type"] == "attempt.completed"
        ]
        checks = {
            "blocked_before_downstream": result.get("status") == "blocked"
            and result.get("failure_category") == "policy_violation"
            and "task_review" not in launched
            and "verification" not in launched,
            "revision_advanced": state["worktree_revision"] == 1,
            "policy_blocker_typed": blocker.get("category") == "policy_violation"
            and blocker.get("root_cause_key") == expected_root,
            "scope_error_is_real_path": commit_head
            or delete_git
            or delete_index
            or stage_allowed
            or switch_same_commit
            or blocker.get("scope_errors") == expected_scope_errors,
            "revision_precedes_blocker": bool(revision_indexes and blocker_indexes)
            and revision_indexes[0] < blocker_indexes[0],
            "worker_report_is_diagnostic_only": commit_head
            or delete_git
            or delete_index
            or switch_same_commit
            or any(
                event["type"] == "worktree.revision_recorded"
                and event["payload"].get("changed_files") == expected_changed_files
                for event in events
            ),
            "unexpected_exception_is_failed_attempt": not (
                unexpected_exception or delete_git or chmod_file or chmod_directory
            )
            or (
                len(completed_attempts) == 1
                and completed_attempts[0]["payload"].get("status") == "failed"
                and completed_attempts[0]["payload"].get("failure_category")
                == "unexpected_worker_error"
                and bool(completed_attempts[0]["payload"].get("evidence_refs"))
                and any(
                    item.get("kind") == "worker_result"
                    for item in state["artifact_index"]
                )
                and state["lifecycle"] == "blocked"
            ),
        }
        if chmod_file:
            (worktree / "sealed-unclaimed.bin").chmod(0o600)
        if chmod_directory:
            (worktree / "sealed-unclaimed-dir").chmod(0o700)
        return checks


def _initial_invalid_git_fault() -> dict[str, bool]:
    with tempfile.TemporaryDirectory(prefix="cpe-initial-invalid-git-") as raw:
        worktree, run_dir, tasks, kernel = _scope_fixture(Path(raw))
        shutil.rmtree(worktree / ".git")
        launched: list[str] = []

        def provider(request, _argv):
            launched.append(request.attempt_kind)
            return _scope_result(request.attempt_kind, request.worktree_revision, [])

        try:
            result = run_tasks(tasks, Worker(provider=provider), kernel)
        except Exception as exc:
            result = {"status": "error", "reason": str(exc)}
        manifest = load_verified_manifest(run_dir / "run_manifest.json")
        events = read_events(run_dir / "events.jsonl")
        state = project(manifest, events)
        completed_attempts = [
            event for event in events if event["type"] == "attempt.completed"
        ]
        return {
            "blocked_without_worker_launch": result.get("status") == "blocked"
            and not launched,
            "run_is_not_left_active": state["lifecycle"] == "blocked",
            "no_false_revision": state["worktree_revision"] == 0,
            "failed_attempt_recorded": len(completed_attempts) == 1
            and completed_attempts[0]["payload"].get("status") == "failed"
            and bool(completed_attempts[0]["payload"].get("evidence_refs")),
        }


def _root_unreadable_fault() -> dict[str, bool]:
    with tempfile.TemporaryDirectory(prefix="cpe-root-unreadable-") as raw:
        worktree, run_dir, tasks, kernel = _scope_fixture(Path(raw))
        launched: list[str] = []

        def provider(request, _argv):
            launched.append(request.attempt_kind)
            if request.attempt_kind == "implementation" and request.task_id == "T1":
                worktree.chmod(0)
            return _scope_result(request.attempt_kind, request.worktree_revision, [])

        try:
            try:
                result = run_tasks(tasks, Worker(provider=provider), kernel)
            except Exception as exc:
                result = {"status": "error", "reason": str(exc)}
        finally:
            worktree.chmod(0o700)
        manifest = load_verified_manifest(run_dir / "run_manifest.json")
        events = read_events(run_dir / "events.jsonl")
        state = project(manifest, events)
        revision_indexes = [
            index
            for index, event in enumerate(events)
            if event["type"] == "worktree.revision_recorded"
        ]
        blocker_indexes = [
            index
            for index, event in enumerate(events)
            if event["type"] == "blocker.opened"
        ]
        completed_attempts = [
            event for event in events if event["type"] == "attempt.completed"
        ]
        blocker = state["active_blockers"][0] if state["active_blockers"] else {}
        revision_paths = next(
            (
                event["payload"].get("changed_files")
                for event in events
                if event["type"] == "worktree.revision_recorded"
            ),
            [],
        )
        return {
            "blocked_before_downstream": result.get("status") == "blocked"
            and "task_review" not in launched
            and "verification" not in launched,
            "revision_captures_baseline_union": state["worktree_revision"] == 1
            and ".gitignore" in revision_paths
            and "owned-b.txt" in revision_paths,
            "failed_attempt_recorded": len(completed_attempts) == 1
            and completed_attempts[0]["payload"].get("status") == "failed"
            and bool(completed_attempts[0]["payload"].get("evidence_refs")),
            "typed_policy_blocker": blocker.get("category") == "policy_violation",
            "revision_precedes_blocker": bool(revision_indexes and blocker_indexes)
            and revision_indexes[0] < blocker_indexes[0],
            "run_is_blocked": state["lifecycle"] == "blocked",
        }


def _allowed_parent_directory_fault(allowed_pattern: str) -> dict[str, bool]:
    with tempfile.TemporaryDirectory(prefix="cpe-allowed-parent-") as raw:
        worktree, run_dir, tasks, kernel = _scope_fixture(
            Path(raw),
            allowed_paths=[allowed_pattern],
            t1_claims=["newdir/owned.txt"],
        )
        launched: list[str] = []

        def provider(request, _argv):
            launched.append(request.attempt_kind)
            changed: list[str] = []
            if request.attempt_kind == "implementation" and request.task_id == "T1":
                (worktree / "newdir").mkdir()
                (worktree / "newdir" / "owned.txt").write_text(
                    "owned\n", encoding="utf-8"
                )
                changed = ["newdir/owned.txt"]
            return _scope_result(request.attempt_kind, request.worktree_revision, changed)

        try:
            result = run_tasks(tasks, Worker(provider=provider), kernel)
        except ValueError as exc:
            if not str(exc).startswith("completion gate failed: "):
                raise
            # Task 7 deliberately makes the old scheduler producer fail closed.
            # Reaching this gate still proves the Task 6 scope controller allowed
            # the structural parent; Task 8 supplies revision-bound completion
            # evidence and restores end-to-end completion.
            result = {"status": "completion_gate_pending"}
        manifest = load_verified_manifest(run_dir / "run_manifest.json")
        state = project(manifest, read_events(run_dir / "events.jsonl"))
        return {
            "reached_completion_gate_without_scope_blocker": result.get("status")
            in {"completed", "completion_gate_pending"}
            and not state["active_blockers"],
            "single_revision_recorded": state["worktree_revision"] == 1,
            "downstream_roles_ran": "task_review" in launched
            and "verification" in launched,
        }


def scope_cases() -> dict[str, bool]:
    cross_task = _scope_fault(False)
    head_change = _scope_fault(True)
    failed_worker = _scope_fault(False, invalid_worker_result=True)
    ignored_forbidden = _scope_fault(
        False,
        ignored_path="ignored-forbidden.bin",
        ignored_forbidden=True,
    )
    ignored_unclaimed = _scope_fault(
        False,
        ignored_path="ignored-unclaimed.bin",
    )
    unexpected_exception = _scope_fault(False, unexpected_exception=True)
    deleted_git = _scope_fault(False, delete_git=True)
    deleted_index = _scope_fault(False, delete_index=True)
    staged_index = _scope_fault(False, stage_allowed=True)
    same_commit_branch = _scope_fault(False, switch_same_commit=True)
    nested_git = _scope_fault(False, nested_git_file=True)
    empty_dir = _scope_fault(False, empty_directory=True)
    sealed_file = _scope_fault(False, chmod_file=True)
    sealed_dir = _scope_fault(False, chmod_directory=True)
    initial_invalid_git = _initial_invalid_git_fault()
    root_unreadable = _root_unreadable_fault()
    allowed_exact_parent = _allowed_parent_directory_fault("newdir/owned.txt")
    allowed_glob_parent = _allowed_parent_directory_fault("newdir/**")
    return {
        **{f"cross_task_{name}": passed for name, passed in cross_task.items()},
        **{f"head_change_{name}": passed for name, passed in head_change.items()},
        **{f"failed_worker_{name}": passed for name, passed in failed_worker.items()},
        **{f"ignored_forbidden_{name}": passed for name, passed in ignored_forbidden.items()},
        **{f"ignored_unclaimed_{name}": passed for name, passed in ignored_unclaimed.items()},
        **{f"unexpected_exception_{name}": passed for name, passed in unexpected_exception.items()},
        **{f"deleted_git_{name}": passed for name, passed in deleted_git.items()},
        **{f"deleted_index_{name}": passed for name, passed in deleted_index.items()},
        **{f"staged_index_{name}": passed for name, passed in staged_index.items()},
        **{f"same_commit_branch_{name}": passed for name, passed in same_commit_branch.items()},
        **{f"nested_git_{name}": passed for name, passed in nested_git.items()},
        **{f"empty_dir_{name}": passed for name, passed in empty_dir.items()},
        **{f"sealed_file_{name}": passed for name, passed in sealed_file.items()},
        **{f"sealed_dir_{name}": passed for name, passed in sealed_dir.items()},
        **{f"initial_invalid_git_{name}": passed for name, passed in initial_invalid_git.items()},
        **{f"root_unreadable_{name}": passed for name, passed in root_unreadable.items()},
        **{f"allowed_exact_parent_{name}": passed for name, passed in allowed_exact_parent.items()},
        **{f"allowed_glob_parent_{name}": passed for name, passed in allowed_glob_parent.items()},
    }


def verdict_cases() -> dict[str, bool]:
    base = {
        "findings": [],
        "missing_evidence": [],
        "worktree_revision": 7,
    }
    passed_worker_result = {
        "status": "completed",
        "summary": "contradictory review",
        "changed_files": [],
        "findings": [],
        "evidence_refs": [],
        "missing_evidence": [],
        "verification": [],
        "verdict": {**base, "status": "passed"},
    }
    return {
        "worker_top_level_critical_mismatch_rejected": worker_rejects_result(
            "worker result findings do not match verdict",
            {
                **passed_worker_result,
                "findings": [{"severity": "critical", "summary": "hidden contradiction"}],
            },
        ),
        "worker_top_level_missing_evidence_mismatch_rejected": worker_rejects_result(
            "worker result missing_evidence does not match verdict",
            {**passed_worker_result, "missing_evidence": ["required acceptance output"]},
        ),
        "critical_passed_rejected": rejected(
            "passed verdict conflicts with critical findings",
            lambda: validate_verdict(
                {
                    **base,
                    "status": "passed",
                    "findings": [{"severity": "critical", "summary": "completion is false"}],
                },
                "task_review",
                7,
            ),
        ),
        "missing_evidence_passed_rejected": rejected(
            "passed verdict conflicts with missing evidence",
            lambda: validate_verdict(
                {**base, "status": "passed", "missing_evidence": ["acceptance log"]},
                "verification",
                7,
            ),
        ),
        "empty_changes_requested_rejected": rejected(
            "changes_requested verdict requires an actionable finding",
            lambda: validate_verdict(
                {**base, "status": "changes_requested"}, "final_review", 7
            ),
        ),
        "ownerless_blocked_rejected": rejected(
            "blocked verdict requires owner and resume_condition",
            lambda: validate_verdict({**base, "status": "blocked"}, "task_review", 7),
        ),
        "unbounded_inconclusive_rejected": rejected(
            "inconclusive verdict requires next_evidence_action",
            lambda: validate_verdict(
                {**base, "status": "inconclusive"}, "verification", 7
            ),
        ),
        "stale_revision_rejected": rejected(
            "verdict revision is stale",
            lambda: validate_verdict({**base, "status": "passed"}, "task_review", 8),
        ),
        "write_role_verdict_rejected": rejected(
            "role implementation cannot issue a verdict",
            lambda: validate_verdict({**base, "status": "passed"}, "implementation", 7),
        ),
        "valid_passed_accepted": validate_verdict(
            {**base, "status": "passed"}, "task_review", 7
        )["status"]
        == "passed",
        "valid_changes_requested_accepted": validate_verdict(
            {
                **base,
                "status": "changes_requested",
                "findings": [{"severity": "major", "action": "add the missing assertion"}],
            },
            "final_review",
            7,
        )["status"]
        == "changes_requested",
        "valid_blocked_accepted": validate_verdict(
            {
                **base,
                "status": "blocked",
                "owner": "operator",
                "resume_condition": "provide the signed report",
            },
            "verification",
            7,
        )["status"]
        == "blocked",
        "valid_inconclusive_accepted": validate_verdict(
            {
                **base,
                "status": "inconclusive",
                "next_evidence_action": "run the bounded acceptance command",
            },
            "verification",
            7,
        )["status"]
        == "inconclusive",
    }


def completion_cases() -> dict[str, bool]:
    with tempfile.TemporaryDirectory(prefix="cpe-completion-fault-") as raw:
        root = Path(raw)
        false_run, before = make_v3_run(
            root / "false", false_completion=True, terminal=False
        )
        integrity = validate_integrity(false_run)
        completion = validate_completion(false_run)
        try:
            RunKernel(false_run).transition(
                Transition("run.status_changed", {"from": "running", "to": "completed"})
            )
        except ValueError as exc:
            rejection_codes = str(exc).partition(": ")[2].split(",")
        else:
            rejection_codes = []
        false_manifest = load_verified_manifest(false_run / "run_manifest.json")
        after = project(false_manifest, read_events(false_run / "events.jsonl"))

        healthy_run, healthy_before_audit = make_v3_run(
            root / "healthy",
            false_completion=False,
            terminal=False,
            record_audit=False,
        )
        evidence_refs = [
            item["ref"] for item in healthy_before_audit["artifact_index"]
        ]
        evidence_checklist = [
            {"kind": item["kind"], "task_id": item.get("task_id"), "ref": item["ref"]}
            for item in healthy_before_audit["artifact_index"]
        ]
        with_audit = RunKernel(healthy_run).transition(
            Transition(
                "completion.recorded",
                {
                    "passed": True,
                    "prompt_to_artifact_checklist": evidence_checklist,
                    "verification_evidence": evidence_refs,
                    "residual_risk": [],
                },
            )
        )
        completed = RunKernel(healthy_run).transition(
            Transition("run.status_changed", {"from": "running", "to": "completed"})
        )
        healthy_report = validate_completion(healthy_run)
        healthy_worktree = root / "healthy" / "worktree"
        (healthy_worktree / "owned.txt").write_text(
            "unrecorded post-evidence write\n", encoding="utf-8"
        )
        post_evidence_report = validate_completion(healthy_run)

        ignored_run, _ = make_v3_run(
            root / "ignored-tamper", false_completion=False, terminal=False
        )
        (root / "ignored-tamper" / "worktree" / "ignored.bin").write_bytes(
            b"ignored post-evidence tamper\0"
        )
        ignored_report = validate_completion(ignored_run)

        index_run, _ = make_v3_run(
            root / "index-tamper", false_completion=False, terminal=False
        )
        _run(["git", "add", "owned.txt"], root / "index-tamper" / "worktree").check_returncode()
        index_report = validate_completion(index_run)

        branch_run, _ = make_v3_run(
            root / "branch-tamper", false_completion=False, terminal=False
        )
        _run(
            ["git", "switch", "-q", "-c", "tampered-branch"],
            root / "branch-tamper" / "worktree",
        ).check_returncode()
        branch_report = validate_completion(branch_run)

        stale_run, _ = make_v3_run(
            root / "stale", false_completion=False, terminal=False
        )
        record_revision(stale_run, "T1", b"later revision\n")
        stale_report = validate_completion(stale_run)

        missing_patch_run, _ = make_v3_run(
            root / "missing-patch",
            false_completion=False,
            terminal=False,
            include_patch_ref=False,
        )
        missing_patch_report = validate_integrity(missing_patch_run)

        wrong_scope_run, _ = make_v3_run(
            root / "wrong-scope",
            false_completion=False,
            terminal=False,
            file_claims=["other.txt"],
        )
        wrong_scope_report = validate_integrity(wrong_scope_run)

        unbound_run, _ = make_v3_run(
            root / "unbound", false_completion=False, terminal=False
        )
        unbound_ref = put_json(
            unbound_run,
            "verification",
            {"kind": "verification", "task_id": "T1", "status": "passed"},
        ).as_dict()
        append_event(
            unbound_run / "events.jsonl",
            {
                "type": "evidence.attached",
                "task_id": "T1",
                "attempt_id": "T1.verification.unbound",
                "payload": {"kind": "verification", "ref": unbound_ref},
            },
        )
        rebuild_snapshot(unbound_run)
        unbound_integrity = validate_integrity(unbound_run)
        unbound_completion = validate_completion(unbound_run)

        mismatch_run, _ = make_v3_run(
            root / "kind-mismatch", false_completion=False, terminal=False
        )
        mismatch_ref = put_json(
            mismatch_run,
            "verification",
            {"kind": "verification", "task_id": "T1", "status": "passed"},
        ).as_dict()
        append_event(
            mismatch_run / "events.jsonl",
            {
                "type": "evidence.attached",
                "task_id": "T1",
                "attempt_id": "T1.task_review.mismatch",
                "payload": {"kind": "task_review", "ref": mismatch_ref},
            },
        )
        rebuild_snapshot(mismatch_run)
        mismatch_report = validate_integrity(mismatch_run)

        duplicate_run, duplicate_state = make_v3_run(
            root / "duplicate-artifact", false_completion=False, terminal=False
        )
        duplicate_item = duplicate_state["artifact_index"][0]
        append_event(
            duplicate_run / "events.jsonl",
            {
                "type": "evidence.attached",
                "task_id": duplicate_item.get("task_id"),
                "attempt_id": "T1.duplicate",
                "payload": {"kind": duplicate_item["kind"], "ref": duplicate_item["ref"]},
            },
        )
        rebuild_snapshot(duplicate_run)
        duplicate_report = validate_integrity(duplicate_run)

        changed_mismatch_run, _ = make_v3_run(
            root / "changed-mismatch",
            false_completion=False,
            terminal=False,
            revision_changed_files=["not-the-real-path.txt"],
        )
        changed_mismatch_report = validate_integrity(changed_mismatch_run)

        patch_tamper_run, patch_tamper_state = make_v3_run(
            root / "patch-tamper", false_completion=False, terminal=False
        )
        patch_digest = patch_tamper_state["worktree_patch_sha256"]
        (patch_tamper_run / "artifacts" / "patches" / f"{patch_digest}.patch").write_bytes(
            b"tampered patch"
        )
        patch_tamper_report = validate_integrity(patch_tamper_run)

        contradiction_run, _ = make_v3_run(
            root / "contradiction",
            false_completion=False,
            terminal=False,
            repository_contradiction=True,
        )
        contradiction_report = validate_completion(contradiction_run)

        zero_root = root / "revision-zero"
        zero_root.mkdir()
        _zero_worktree, zero_run, _zero_tasks, zero_kernel = _scope_fixture(zero_root)
        zero_kernel.transition(
            Transition("run.status_changed", {"from": "created", "to": "ready"})
        )
        zero_kernel.transition(
            Transition("run.status_changed", {"from": "ready", "to": "running"})
        )
        zero_integrity = validate_integrity(zero_run)
        zero_completion = validate_completion(zero_run)

        return {
            "healthy_running_integrity_passes": integrity.passed,
            "false_completion_has_exact_codes": completion.errors
            == EXPECTED_FALSE_COMPLETION_CODES,
            "kernel_rejects_same_false_completion_codes": rejection_codes
            == EXPECTED_FALSE_COMPLETION_CODES,
            "rejected_completion_is_non_mutating": after == before,
            "completion_record_authorized_by_canonical_profile": isinstance(
                with_audit.get("completion_audit"), dict
            ),
            "healthy_current_evidence_can_complete": completed.get("lifecycle")
            == "completed"
            and healthy_report.passed,
            "unrecorded_post_evidence_write_fails": (
                "current_revision_worktree_mismatch" in post_evidence_report.errors
            ),
            "ignored_write_invalidates_revision": (
                "current_revision_worktree_mismatch" in ignored_report.errors
            ),
            "index_tamper_invalidates_revision": (
                "current_revision_worktree_mismatch" in index_report.errors
            ),
            "branch_tamper_invalidates_revision": (
                "current_revision_worktree_mismatch" in branch_report.errors
            ),
            "later_revision_invalidates_all_success": (
                "current_revision_acceptance_not_passed" in stale_report.errors
                and "current_revision_task_review_not_passed" in stale_report.errors
                and "current_revision_verification_not_passed" in stale_report.errors
                and "current_revision_final_review_not_passed" in stale_report.errors
                and "current_revision_repository_check_missing" in stale_report.errors
                and "stale_completion_evidence" in stale_report.errors
            ),
            "missing_revision_patch_ref_fails_integrity": (
                "revision_patch_evidence_missing" in missing_patch_report.errors
            ),
            "revision_scope_is_task_local": (
                "revision_scope_violation" in wrong_scope_report.errors
            ),
            "unbound_completion_evidence_warns_and_blocks": (
                "stale_revision_evidence" in unbound_integrity.warnings
                and "unbound_completion_evidence" in unbound_completion.errors
            ),
            "artifact_kind_mismatch_fails_integrity": (
                "artifact_kind_mismatch" in mismatch_report.errors
            ),
            "duplicate_artifact_ref_fails_integrity": (
                "duplicate_artifact_ref" in duplicate_report.errors
            ),
            "revision_changed_files_must_match_patch": (
                "revision_patch_chain_invalid" in changed_mismatch_report.errors
            ),
            "revision_patch_content_tamper_fails_integrity": (
                "revision_patch_evidence_invalid" in patch_tamper_report.errors
            ),
            "contradictory_repository_payload_cannot_pass": (
                "current_revision_repository_check_missing" in contradiction_report.errors
                and "completion_evidence_not_passed" in contradiction_report.errors
            ),
            "revision_zero_is_explicitly_unverified": (
                zero_integrity.passed
                and "revision_zero_baseline_unverified" in zero_integrity.warnings
                and "current_revision_patch_unverifiable" in zero_completion.errors
            ),
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", choices=("verdicts", "scope", "completion"))
    args = parser.parse_args()

    if args.case == "verdicts":
        checks = verdict_cases()
    elif args.case == "scope":
        checks = scope_cases()
    elif args.case == "completion":
        checks = completion_cases()
    else:
        checks = {
            **verdict_cases(),
            **scope_cases(),
            **completion_cases(),
        }
    failures = [name for name, passed in checks.items() if not passed]
    print(json.dumps({"passed": not failures, "checks": checks, "failures": failures}, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
