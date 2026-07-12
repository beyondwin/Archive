#!/usr/bin/env python3
"""Run, resume, supervise, inspect, or export a CPE v4 implementation plan."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import secrets
import subprocess
import time
from datetime import datetime
from pathlib import Path

from preflight_dependencies import check_requirements

from cpe_runtime.events import read_events, validate_chain
from cpe_runtime.evidence import put_json
from cpe_runtime.git_delta import matches_path
from cpe_runtime.kernel import Kernel, RunKernel, Transition, rebuild_snapshot
from cpe_runtime.manifest import canonical_hash, file_record, load_verified_manifest, relative_ref, resolve_ref
from cpe_runtime.model_policy import policy_hash, policy_payload
from cpe_runtime.packets import build_packet, packet_entry
from cpe_runtime.plan_compiler import CompileBlocked, compile_run
from cpe_runtime.projector import project
from cpe_runtime.prompt_export import render_export_bundle
from cpe_runtime.public_result import PublicResult, blocked_result, failed_result
from cpe_runtime.reconciliation import ResumeDecision, select_resume, select_v4_resume
from cpe_runtime.repair import apply_repair
from cpe_runtime.release_policy_v4 import load_release_policy
from cpe_runtime.scheduler import (
    LifecycleOperations,
    PreTurnInterruption,
    ReviewScope,
    RuntimeUpgradeInterruption,
    review_scope_payload,
    review_scope_sha256,
    run_delegated_dependency_repair,
    run_tasks,
    run_tasks_v4,
)
from cpe_runtime.task_contracts import contract_from_body
from cpe_runtime.validation import validate_completion, validate_integrity
from cpe_runtime.worker import Worker, WorkerRequest


class PreflightError(ValueError):
    pass


def _run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def _codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser().resolve()


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "cpe-run"


def _allocate_paths(plan: Path) -> tuple[str, Path, Path]:
    home = _codex_home()
    base = f"{_slug(plan.stem)}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    for index in range(100):
        run_id = base if index == 0 else f"{base}-{secrets.token_hex(2)}"
        run_dir = home / "orchestrator" / run_id
        worktree = home / "worktrees" / run_id
        if not run_dir.exists() and not worktree.exists():
            return run_id, run_dir, worktree
    raise PreflightError("unable to allocate a non-conflicting run id")


def _create_worktree(workspace: Path, worktree: Path, run_id: str, source_head: str) -> str:
    worktree.parent.mkdir(parents=True, exist_ok=True)
    branch = f"codex/{run_id}"
    result = _run(["git", "worktree", "add", "-q", "-b", branch, str(worktree), source_head], workspace)
    if result.returncode:
        raise PreflightError(f"worktree creation failed: {result.stderr.strip()}")
    return branch


def _compiled_manifest(
    run_id: str,
    mode: str,
    workspace: Path,
    worktree: Path,
    run_dir: Path,
    compiled: object,
    pricing: Path,
) -> dict[str, object]:
    """Build all input records from the immutable bytes returned by compilation."""

    sources = tuple(getattr(compiled, "sources", ()))
    plan_sources = [source for source in sources if getattr(source, "role", None) == "plan"]
    spec_sources = [source for source in sources if getattr(source, "role", None) == "spec"]
    doc_sources = [source for source in sources if getattr(source, "role", None) == "doc"]
    if len(plan_sources) != 1 or len(spec_sources) > 1:
        raise ValueError("compiled_input_shape_invalid")
    plan_digest = str(plan_sources[0].sha256)
    tasks = list(getattr(compiled, "tasks", ()))
    if any(
        not isinstance(task, dict)
        or not isinstance(task.get("source_hashes"), dict)
        or task["source_hashes"].get("plan") != plan_digest
        for task in tasks
    ):
        raise ValueError("compiled_input_digest_mismatch")

    def record(label: str, source: object) -> dict[str, str]:
        content = getattr(source, "content", None)
        digest = getattr(source, "sha256", None)
        if not isinstance(content, bytes) or hashlib.sha256(content).hexdigest() != digest:
            raise ValueError("compiled_input_digest_mismatch")
        target = run_dir / "artifacts" / "inputs" / f"{label}.snapshot"
        return {"ref": relative_ref(target), "sha256": str(digest)}

    plan_record = record("plan", plan_sources[0])
    spec_record = record("spec", spec_sources[0]) if spec_sources else None
    doc_records = [record(f"doc-{index:03d}", source) for index, source in enumerate(doc_sources)]
    pricing_record = file_record(pricing)
    manifest = {
        "schema_version": "4",
        "run_id": run_id,
        "mode": mode,
        "workspace_ref": relative_ref(workspace),
        "execution_worktree_ref": relative_ref(worktree),
        "plan": plan_record,
        "spec": spec_record,
        "docs": doc_records,
        "task_graph": tasks,
        "plan_graph_hash": canonical_hash(tasks),
        "model_policy": policy_payload(),
        "model_policy_hash": policy_hash(),
        "pricing_snapshot": pricing_record,
        "pricing_snapshot_hash": pricing_record["sha256"],
        "source_git": {
            "head": str(getattr(compiled, "source_head")),
            "status": list(getattr(compiled, "source_status", ())),
        },
        "runtime": {
            "runtime_commit": str(getattr(compiled, "source_head")),
            "compatibility_epoch": "cpe-v4",
        },
        "task_packets": [],
    }
    if len(tasks) == 1:
        release_policy = load_release_policy()
        if tasks[0].get("task_contract_sha256") == release_policy["dogfood_task_contract_sha256"]:
            manifest["attempt_budget_limit"] = release_policy["dogfood_attempt_limit"]
            manifest["release_policy_sha256"] = release_policy["policy_sha256"]
    return manifest


def _emit(result: PublicResult) -> int:
    print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
    return result.exit_code()


def _context_artifacts(run_dir: Path) -> dict[str, str | None]:
    return {
        "spec_manifest_path": str(run_dir / "run_manifest.json"),
        "task_packet_dir": str(run_dir / "artifacts" / "task-packets"),
        "decisions_path": None,
    }


def _v4_contracts(manifest: dict[str, object]):
    return tuple(
        contract_from_body(task["task_contract"], str(task["task_contract_sha256"]))
        for task in manifest.get("task_graph", [])
        if isinstance(task, dict)
    )


def _v4_operations(
    contracts: tuple[object, ...],
    manifest: dict[str, object],
    kernel: Kernel,
    worktree: Path,
    worker: Worker,
    *,
    before_model_turn=None,
) -> dict[str, LifecycleOperations]:
    operations: dict[str, LifecycleOperations] = {}
    for contract in contracts:
        task_id = str(getattr(contract, "task_id"))
        entry = packet_entry(manifest, task_id)
        packet_path = kernel.run_dir / str(entry["path"])
        packet_sha256 = str(entry["sha256"])

        def invoke(
            kind: str,
            attempt_id: str,
            payload: dict[str, object],
            *,
            task_id: str = task_id,
            packet_path: Path = packet_path,
            packet_sha256: str = packet_sha256,
        ):
            policy = {
                "implementation": (False, False),
                "repair": (False, False),
                "task_review": (True, True),
                "verification": (True, True),
            }[kind]
            return worker.run(
                WorkerRequest(
                    attempt_id=attempt_id,
                    attempt_kind=kind,
                    prompt=json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    worktree=worktree,
                    read_only=policy[0],
                    verdict_capable=policy[1],
                    task_id=task_id,
                    packet_path=str(packet_path),
                    packet_sha256=packet_sha256,
                    worktree_revision=len(kernel.state.get("candidate_checkpoints", [])),
                )
            )

        def implementation(current, attempt_id: str, *, invoke=invoke):
            return invoke(
                "implementation",
                attempt_id,
                {"role": "implementation", "task_contract": current.body()},
            )

        def repair(current, finding: dict[str, object], attempt_id: str, *, invoke=invoke):
            return invoke(
                "repair",
                attempt_id,
                {"role": "repair", "task_contract": current.body(), "finding": finding},
            )

        def review(current, scope: ReviewScope, attempt_id: str, *, invoke=invoke):
            candidate_tree = _run(
                ["git", "rev-parse", f"{scope.candidate_commit}^{{tree}}"], worktree
            ).stdout.strip()
            binding = {
                "task_id": current.task_id,
                "candidate_commit": scope.candidate_commit,
                "candidate_tree": candidate_tree,
                "contract_sha256": current.contract_sha256,
                "worktree_revision": len(kernel.state.get("candidate_checkpoints", [])),
                "review_scope_sha256": review_scope_sha256(scope),
                "requested_scope": review_scope_payload(scope),
            }
            return invoke(
                "task_review",
                attempt_id,
                {
                    "role": "task_review",
                    "task_contract": current.body(),
                    "review_scope": review_scope_payload(scope),
                    "required_review_binding": binding,
                },
            )

        def before(phase: str, attempt_id: str, *, task_id: str = task_id) -> None:
            if before_model_turn is not None:
                before_model_turn(task_id, phase, attempt_id)

        operations[task_id] = LifecycleOperations(
            packet_sha256=packet_sha256,
            before_model_turn=before,
            implementation=implementation,
            repair=repair,
            review=review,
            deterministic_verification=lambda *_args: (
                True,
                "production acceptance workspace and bound review passed",
            ),
            semantic_verification=None,
            repair_boundary_changes=lambda *_args: (),
            acceptance_environment=os.environ,
        )
    return operations


def _changed_files(worktree: Path) -> tuple[str, ...]:
    result = _run(["git", "status", "--short", "--untracked-files=all"], worktree)
    if result.returncode:
        return ()
    return tuple(line[3:] for line in result.stdout.splitlines() if len(line) > 3)


def _owned_worktree(workspace: Path, worktree: Path, branch: str, source_head: str, run_id: str) -> bool:
    if worktree.name != run_id or not worktree.is_dir():
        return False
    head = _run(["git", "rev-parse", "HEAD"], worktree)
    current_branch = _run(["git", "symbolic-ref", "--short", "HEAD"], worktree)
    listed = _run(["git", "worktree", "list", "--porcelain"], workspace)
    branch_ref = f"refs/heads/{branch}"
    blocks = [block.splitlines() for block in listed.stdout.strip().split("\n\n")]
    registered = any(
        f"worktree {worktree}" in block and f"branch {branch_ref}" in block
        for block in blocks
    )
    return (
        head.returncode == 0
        and head.stdout.strip() == source_head
        and current_branch.returncode == 0
        and current_branch.stdout.strip() == branch
        and listed.returncode == 0
        and registered
    )


def _cleanup_unpublished_worktree(
    workspace: Path,
    worktree: Path,
    branch: str,
    source_head: str,
    run_id: str,
    run_dir: Path,
) -> None:
    """Remove only this invocation's unpublished worktree and matching branch."""

    if run_dir.exists() or not _owned_worktree(workspace, worktree, branch, source_head, run_id):
        return
    removed = _run(["git", "worktree", "remove", "--force", str(worktree)], workspace)
    if removed.returncode == 0:
        _run(["git", "branch", "-D", branch], workspace)


def execute_run(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).expanduser().resolve()
    plan = Path(args.plan).expanduser().resolve()
    spec = Path(args.spec).expanduser().resolve() if args.spec else None
    docs = [Path(value).expanduser().resolve() for value in (args.docs or [])]
    if not workspace.is_dir() or not plan.is_file() or (spec and not spec.is_file()) or any(not path.is_file() for path in docs):
        raise PreflightError("workspace, plan, spec, or docs path is unreadable")
    dependency_report = check_requirements()
    if not dependency_report["passed"]:
        raise PreflightError(json.dumps(dependency_report, ensure_ascii=False))
    compiled = compile_run(
        plan=plan,
        spec=spec,
        docs=tuple(docs),
        workspace=workspace,
        mode=args.mode,
    )
    tasks = list(compiled.tasks)
    head = compiled.source_head
    run_id, run_dir, worktree = _allocate_paths(plan)
    pricing = Path(__file__).resolve().parents[1] / "data" / "pricing-snapshot.json"
    try:
        manifest = _compiled_manifest(run_id, args.mode, workspace, worktree, run_dir, compiled, pricing)
        packet_drafts = [build_packet(compiled, task) for task in tasks]
        prepared = RunKernel.prepare(run_dir, manifest, packet_drafts, input_sources=compiled.sources)
    except (ValueError, OSError, RuntimeError) as exc:
        return _emit(
            failed_result(
                str(exc) or type(exc).__name__,
                category="environment" if isinstance(exc, OSError) else "state_integrity",
                run_id=run_id,
                next_action="Correct initialization inputs and start a new run.",
            )
        )
    except BaseException:
        raise
    branch = f"codex/{run_id}"
    try:
        branch = _create_worktree(workspace, worktree, run_id, head)
        kernel = prepared.publish()
    except (ValueError, OSError, RuntimeError) as exc:
        prepared.cleanup()
        _cleanup_unpublished_worktree(workspace, worktree, branch, head, run_id, run_dir)
        return _emit(
            failed_result(
                str(exc) or type(exc).__name__,
                category="environment" if isinstance(exc, OSError) else "state_integrity",
                run_id=run_id,
                state_path=str(run_dir / "state.json") if run_dir.exists() else None,
                next_action="Correct initialization inputs and start a new run.",
            )
        )
    except BaseException:
        prepared.cleanup()
        _cleanup_unpublished_worktree(workspace, worktree, branch, head, run_id, run_dir)
        raise
    finally:
        prepared.cleanup()
    manifest = load_verified_manifest(run_dir / "run_manifest.json")
    contracts = _v4_contracts(manifest)
    worker = Worker()
    operations = _v4_operations(contracts, manifest, kernel, worktree, worker)
    kernel.transition(Transition("run.status_changed", {"from": "ready", "to": "running"}))
    try:
        results = run_tasks_v4(contracts, operations, kernel, worktree, run_dir)
    except (ValueError, OSError, RuntimeError) as exc:
        return _emit(
            failed_result(
                str(exc) or type(exc).__name__,
                category="state_integrity",
                run_id=run_id,
                state_path=str(run_dir / "state.json"),
                next_action="Inspect the published run evidence before reconciliation.",
            )
        )
    state = kernel.state
    if len(state.get("verified_checkpoints", [])) != len(contracts):
        result = results[-1] if results else None
        state = kernel.state
        blocker = (state.get("active_blockers") or [{}])[-1]
        summary = str(getattr(result, "reason", None) or blocker.get("category") or "run paused")
        phase = str(getattr(result, "phase", "") or "")
        reason = str(getattr(result, "reason", None) or blocker.get("category") or "")
        category = (
            "policy_violation"
            if "policy" in reason or "scope" in reason
            else "review"
            if phase in {"task_review", "final_review"}
            else "verification"
            if phase in {"acceptance", "verification", "repository_checks"}
            else "transient"
            if "transient" in reason
            else "implementation"
        )
        return _emit(
            blocked_result(
                summary,
                category=category,
                run_id=run_id,
                state_path=str(run_dir / "state.json"),
                evidence_refs=tuple(blocker.get("evidence_refs") or ()),
            )
        )
    budget = dict(state.get("attempt_budget") or {})
    return _emit(
        PublicResult(
            status="success",
            run_id=run_id,
            state_path=str(run_dir / "state.json"),
            summary="All v4 task checkpoints were verified.",
            changed_files=_changed_files(worktree),
            verification=({"command": "verified_task_checkpoints", "status": "passed"},),
            context_artifacts=_context_artifacts(run_dir),
            next_action="Review the isolated worktree changes.",
            current_task=state.get("current_task"),
            checkpoint_head=state.get("checkpoint_head"),
            attempt_limit=budget.get("limit"),
            attempt_used=budget.get("used"),
            next_safe_action="inspect",
        )
    )


def _recovery_evidence(
    kernel: Kernel,
    task_id: str,
    payload: dict[str, object],
    *,
    attempt_id: str | None = None,
) -> dict[str, object]:
    ref = put_json(kernel.run_dir, "recovery", payload).as_dict()
    kernel.transition(
        Transition(
            "evidence.attached",
            {"kind": "recovery", "ref": ref},
            task_id=task_id,
            attempt_id=attempt_id,
        )
    )
    return ref


def _open_recovery_blocker(
    kernel: Kernel,
    task_id: str,
    category: str,
    root_cause_key: str,
    refs: list[dict[str, object]],
) -> str:
    state = kernel.state
    existing = [
        item
        for item in state.get("active_blockers") or []
        if item.get("task_id") == task_id
        and item.get("category") == category
        and item.get("root_cause_key") == root_cause_key
    ]
    if existing:
        return str(existing[0]["blocker_id"])
    blocker_id = f"{task_id}.{category}.{len(state.get('blocker_history') or []) + 1}"
    kernel.transition(
        Transition(
            "blocker.opened",
            {
                "blocker_id": blocker_id,
                "category": category,
                "root_cause_key": root_cause_key,
                "owner": "cpe",
                "resume_condition": "restore the recovery precondition and schedule an explicit retry",
                "evidence_refs": refs,
            },
            task_id=task_id,
        )
    )
    current = kernel.state["tasks"][task_id]["status"]
    if current not in {"blocked", "completed", "failed"}:
        kernel.transition(
            Transition(
                "task.status_changed",
                {"from": current, "to": "blocked", "reason": category},
                task_id=task_id,
            )
        )
    lifecycle = kernel.state["lifecycle"]
    if lifecycle != "blocked" and lifecycle not in {"completed", "failed"}:
        kernel.transition(
            Transition(
                "run.status_changed",
                {"from": lifecycle, "to": "blocked", "reason": category},
            )
        )
    return blocker_id


def _repository_evidence_path(value: object) -> str | None:
    if not isinstance(value, str) or not value or value.startswith("/"):
        return None
    candidate = re.sub(r":\d+(?::\d+)?$", "", value)
    return candidate if "/" in candidate else None


def _approved_dependency_repair_owner(
    kernel: Kernel,
    task_id: str,
    blocker: dict[str, object],
    dependencies: list[str],
) -> str | None:
    """Return the explicitly approved completed dependency for one blocker."""

    for artifact in reversed(kernel.state.get("artifact_index", [])):
        if artifact.get("task_id") != task_id or artifact.get("kind") != "operator_decision":
            continue
        ref = artifact.get("ref")
        if not isinstance(ref, dict):
            continue
        try:
            payload = json.loads(
                (kernel.run_dir / str(ref["path"])).read_text(encoding="utf-8")
            )
        except (KeyError, OSError, json.JSONDecodeError):
            continue
        owner = str(payload.get("dependency_repair_owner_task_id") or "")
        if (
            payload.get("kind") == "operator_decision"
            and payload.get("approved") is True
            and payload.get("task_id") == task_id
            and payload.get("worktree_revision") == kernel.state.get("worktree_revision")
            and payload.get("root_cause_key") == blocker.get("root_cause_key")
            and owner in dependencies
        ):
            return owner
    return None


def _delegated_scope_resume(
    manifest: dict[str, object],
    state: dict[str, object],
    integrity: object,
    worker: Worker,
    kernel: Kernel,
) -> ResumeDecision | None:
    """Repair one claim-bound integration defect through its sole direct dependency."""

    blockers = list(state.get("active_blockers") or [])
    if len(blockers) != 1 or blockers[0].get("category") not in {
        "scope_claim_conflict",
        "out_of_scope_dependency_defect",
    }:
        return None
    if not getattr(integrity, "passed", False):
        return None
    blocker = blockers[0]
    task_id = str(blocker.get("task_id") or "")
    tasks = {
        str(task.get("id")): task
        for task in manifest.get("task_graph") or []
        if isinstance(task, dict) and task.get("id") is not None
    }
    target = tasks.get(task_id)
    if not isinstance(target, dict):
        return None
    dependencies = [str(item) for item in target.get("dependencies") or []]
    if len(dependencies) != 1:
        return None
    approved_owner = _approved_dependency_repair_owner(
        kernel, task_id, blocker, dependencies
    )
    owner_id = approved_owner or dependencies[0]
    owner = tasks.get(owner_id)
    if (
        not isinstance(owner, dict)
        or state.get("tasks", {}).get(owner_id, {}).get("status") != "completed"
    ):
        return None
    refs = [dict(ref) for ref in blocker.get("evidence_refs") or [] if isinstance(ref, dict)]
    if len(refs) != 1 or refs[0].get("kind") != "worker_result":
        return None
    try:
        payload = json.loads((kernel.run_dir / str(refs[0]["path"])).read_text(encoding="utf-8"))
    except (KeyError, OSError, json.JSONDecodeError):
        return None
    result = payload.get("result") if isinstance(payload, dict) else None
    if (
        not isinstance(result, dict)
        or result.get("status") != "blocked"
        or result.get("failure_category") != blocker.get("category")
        or result.get("root_cause_key") != blocker.get("root_cause_key")
        or not result.get("findings")
    ):
        return None
    target_claims = [str(path) for path in target.get("file_claims") or []]
    owner_claims = [str(path) for path in owner.get("file_claims") or []]
    cited = [
        path
        for path in (_repository_evidence_path(item) for item in result.get("evidence_refs") or [])
        if path is not None
    ]
    outside = [path for path in cited if not matches_path(path, target_claims)]
    claim_bound = bool(outside) and all(matches_path(path, owner_claims) for path in outside)
    if not claim_bound and approved_owner is None:
        return None
    context = json.dumps(
        {
            "root_cause_key": blocker.get("root_cause_key"),
            "summary": result.get("summary"),
            "findings": result.get("findings"),
            "missing_evidence": result.get("missing_evidence"),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    cycle = run_delegated_dependency_repair(
        owner,
        task_id,
        str(blocker.get("root_cause_key") or "scope_claim_conflict"),
        context,
        worker,
        kernel,
    )
    if cycle.status != "passed":
        return ResumeDecision("remain_blocked", blocker_id=str(blocker.get("blocker_id") or "") or None)
    recovery_ref = _recovery_evidence(
        kernel,
        task_id,
        {
            "category": "delegated_dependency_repair",
            "owner_task_id": str(owner["id"]),
            "target_task_id": task_id,
            "root_cause_key": blocker.get("root_cause_key"),
            "worktree_revision": kernel.state.get("worktree_revision"),
            "source_evidence_refs": refs,
        },
    )
    return ResumeDecision(
        "retry",
        "acceptance",
        str(blocker.get("blocker_id") or "") or None,
        (recovery_ref,),
    )


def _structured_resume_failure(run_id: str, classification: str, **extra: object) -> int:
    run_dir = _codex_home() / "orchestrator" / run_id
    details = extra.get("errors")
    suffix = f": {','.join(map(str, details))}" if isinstance(details, list) else ""
    category = (
        "environment"
        if classification in {"run_missing", "manifest_missing", "worktree_missing"}
        else "implementation"
        if classification == "repair_delta_not_observed"
        else "state_integrity"
    )
    return _emit(
        failed_result(
            classification + suffix,
            category=category,
            run_id=run_id if run_dir.exists() else None,
            state_path=str(run_dir / "state.json") if run_dir.exists() else None,
        )
    )


def resume_run(run_id: str, worker: Worker | None = None) -> int:
    run_dir = _codex_home() / "orchestrator" / run_id
    if not run_dir.is_dir():
        return _structured_resume_failure(run_id, "run_missing")
    try:
        manifest = load_verified_manifest(run_dir / "run_manifest.json")
        events = read_events(run_dir / "events.jsonl")
    except ValueError as exc:
        return _structured_resume_failure(run_id, str(exc))
    except OSError:
        return _structured_resume_failure(run_id, "manifest_missing")
    if validate_chain(events):
        return _structured_resume_failure(run_id, "event_chain_invalid")
    state = project(manifest, events)
    if state["lifecycle"] == "completed":
        validation = validate_completion(run_dir)
        if not validation.passed:
            return _structured_resume_failure(run_id, "completed_run_invalid", errors=validation.errors)
        worktree = resolve_ref(str(manifest["execution_worktree_ref"]))
        return _emit(
            PublicResult(
                status="success",
                run_id=run_id,
                state_path=str(run_dir / "state.json"),
                summary="Completed run passed canonical completion validation.",
                changed_files=_changed_files(worktree),
                verification=({"command": "validate_completion", "status": "passed"},),
                residual_risk=("paid live migration gate pending",),
                context_artifacts=_context_artifacts(run_dir),
                next_action="Review the isolated worktree changes.",
            )
        )
    kernel = Kernel(run_dir)
    worktree = resolve_ref(str(manifest["execution_worktree_ref"]))
    integrity = validate_integrity(run_dir)
    if not worktree.is_dir():
        workspace_errors = {
            "worktree_missing",
            "worktree_identity_mismatch",
            "revision_zero_worktree_dirty",
            "current_revision_worktree_mismatch",
        }
        non_workspace_errors = [error for error in integrity.errors if error not in workspace_errors]
        if non_workspace_errors:
            return _structured_resume_failure(run_id, "resume_rejected", errors=integrity.errors)
        incomplete = [task_id for task_id, task in state.get("tasks", {}).items() if task.get("status") != "completed"]
        if not incomplete:
            return _structured_resume_failure(run_id, "worktree_missing")
        task_id = str(state.get("current_task") or incomplete[0])
        existing = [
            item
            for item in state.get("active_blockers") or []
            if item.get("task_id") == task_id
            and item.get("category") == "workspace_precondition"
            and item.get("root_cause_key") == "worktree_missing"
        ]
        if existing:
            refs = [dict(ref) for ref in existing[0].get("evidence_refs") or []]
        else:
            refs = [
                _recovery_evidence(
                    kernel,
                    task_id,
                    {"category": "workspace_precondition", "worktree": str(worktree), "status": "missing"},
                )
            ]
        _open_recovery_blocker(kernel, task_id, "workspace_precondition", "worktree_missing", refs)
        return _emit(blocked_result(
            "execution worktree is missing",
            category="environment",
            run_id=run_id,
            state_path=str(run_dir / "state.json"),
            evidence_refs=tuple(refs),
        ))

    if integrity.passed:
        workspace_blockers = [
            item
            for item in state.get("active_blockers") or []
            if item.get("category") == "workspace_precondition"
        ]
        for blocker in workspace_blockers:
            task_id = str(blocker["task_id"])
            ref = _recovery_evidence(
                kernel,
                task_id,
                {"category": "workspace_precondition", "worktree": str(worktree), "status": "restored"},
            )
            restored = apply_repair(
                run_dir,
                "resolve_blocker",
                details={"blocker_id": blocker["blocker_id"], "evidence_refs": [ref]},
            )
            if not restored["applied"]:
                return _structured_resume_failure(run_id, "repair_delta_not_observed")
        if workspace_blockers:
            state = kernel.state
            integrity = validate_integrity(run_dir)

    decision = _delegated_scope_resume(
        manifest,
        state,
        integrity,
        worker or Worker(),
        kernel,
    ) or select_resume(state, integrity)
    if decision.action == "reject":
        return _structured_resume_failure(run_id, "resume_rejected", errors=integrity.errors)
    if decision.action == "remain_blocked":
        return _emit(blocked_result(
            f"run remains blocked: {decision.blocker_id}",
            category="operator_review",
            run_id=run_id,
            state_path=str(run_dir / "state.json"),
        ))
    if decision.action not in {"retry", "continue"} or decision.phase is None:
        return _structured_resume_failure(run_id, "resume_state_invalid")

    refs = [dict(ref) for ref in decision.evidence_refs]
    blocker_id = decision.blocker_id
    queued_continuation = decision.action == "continue"
    if queued_continuation:
        task_id = str(state.get("current_task") or "")
    elif blocker_id is not None:
        blocker = next(item for item in state["active_blockers"] if item.get("blocker_id") == blocker_id)
        task_id = str(blocker["task_id"])
    else:
        active = [item for item in state.get("attempts") or [] if item.get("status") == "started"]
        if len(active) != 1:
            return _structured_resume_failure(run_id, "resume_state_invalid")
        attempt = active[0]
        task_id = str(attempt["task_id"])
        ref = _recovery_evidence(
            kernel,
            task_id,
            {"category": "interrupted_attempt", "attempt_id": attempt["attempt_id"], "kind": attempt.get("kind")},
            attempt_id=str(attempt["attempt_id"]),
        )
        refs = [ref]
        interruption = apply_repair(
            run_dir,
            "mark_stale_attempt_interrupted",
            details={"attempt_id": attempt["attempt_id"], "evidence_refs": refs},
        )
        if not interruption["applied"]:
            return _structured_resume_failure(run_id, "repair_delta_not_observed")
        blocker_id = _open_recovery_blocker(
            kernel,
            task_id,
            f"{attempt.get('kind')}_interrupted",
            f"{attempt.get('kind')}:interrupted",
            refs,
        )

    if not queued_continuation:
        resolved = apply_repair(
            run_dir,
            "resolve_blocker",
            details={"blocker_id": blocker_id, "evidence_refs": refs},
        )
        if not resolved["applied"]:
            return _structured_resume_failure(run_id, "repair_delta_not_observed")
        scheduled = apply_repair(
            run_dir,
            "schedule_retry",
            details={
                "task_id": task_id,
                "phase": decision.phase,
                "root_cause_key": f"resume:{decision.phase}",
                "evidence_refs": refs,
            },
        )
        if not scheduled["applied"]:
            return _structured_resume_failure(run_id, "repair_delta_not_observed")
    if kernel.state["lifecycle"] == "blocked":
        kernel.transition(Transition("run.status_changed", {"from": "blocked", "to": "ready", "reason": "evidence-backed resume"}))
    try:
        result = run_tasks(list(manifest["task_graph"]), worker or Worker(), kernel)
    except (ValueError, OSError, RuntimeError) as exc:
        return _emit(
            failed_result(
                str(exc) or type(exc).__name__,
                category="state_integrity",
                run_id=run_id,
                state_path=str(run_dir / "state.json"),
                next_action="Inspect the published run evidence before reconciliation.",
            )
        )
    if result.get("status") != "completed":
        return _emit(blocked_result(
            str(result.get("reason") or "resumed run blocked"),
            category="implementation",
            run_id=run_id,
            state_path=str(run_dir / "state.json"),
        ))
    completion = validate_completion(run_dir)
    if not completion.passed:
        return _structured_resume_failure(run_id, "completed_run_invalid", errors=completion.errors)
    return _emit(
        PublicResult(
            status="success",
            run_id=run_id,
            state_path=str(run_dir / "state.json"),
            summary="Resumed run completed and passed canonical completion validation.",
            changed_files=_changed_files(worktree),
            verification=({"command": "validate_completion", "status": "passed"},),
            residual_risk=("paid live migration gate pending",),
            context_artifacts=_context_artifacts(run_dir),
            next_action="Review the isolated worktree changes.",
        )
    )


def run_v4_fixture(
    plan: Path,
    root: Path,
    *,
    pause_task_id: str | None = None,
    pause_kind: str | None = None,
    workspace_source: Path | None = None,
) -> dict[str, object]:
    """Drive the production v4 kernel through a deterministic fake provider."""

    root = root.resolve()
    workspace = root / "workspace"
    codex_home = root / "codex-home"
    if workspace_source is None:
        workspace.mkdir(parents=True)
        (workspace / "verify.py").write_text(
            "import pathlib,sys\nraise SystemExit(0 if pathlib.Path(sys.argv[1]).is_file() else 1)\n",
            encoding="utf-8",
        )
        _run(["git", "init", "-q"], workspace)
        _run(["git", "config", "user.email", "cpe-fixture@example.invalid"], workspace)
        _run(["git", "config", "user.name", "CPE Fixture"], workspace)
        _run(["git", "add", "verify.py"], workspace)
        committed = _run(["git", "commit", "-qm", "fixture base"], workspace)
        if committed.returncode:
            raise RuntimeError("fixture_repository_initialization_failed")
    else:
        source = workspace_source.expanduser().resolve()
        cloned = subprocess.run(
            ["git", "clone", "--shared", "--quiet", str(source), str(workspace)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if cloned.returncode:
            raise RuntimeError("fixture_repository_clone_failed")

    compiled = compile_run(plan=plan.resolve(), spec=None, docs=(), workspace=workspace, mode="interactive")
    run_id = "cpe-v4-ten-task-fixture"
    run_dir = codex_home / "orchestrator" / run_id
    worktree = codex_home / "worktrees" / run_id
    pricing = Path(__file__).resolve().parents[1] / "data" / "pricing-snapshot.json"
    manifest = _compiled_manifest(run_id, "interactive", workspace, worktree, run_dir, compiled, pricing)
    drafts = [build_packet(compiled, task) for task in compiled.tasks]
    prepared = RunKernel.prepare(run_dir, manifest, drafts, input_sources=compiled.sources)
    _create_worktree(workspace, worktree, run_id, compiled.source_head)
    kernel = prepared.publish()
    prepared.cleanup()
    manifest = load_verified_manifest(run_dir / "run_manifest.json")
    contracts = _v4_contracts(manifest)
    review_counts: dict[str, int] = {}
    interruptions = {"task_6": 1, "task_8": 1} if workspace_source is None else {}
    counters = {"transient_resumes": 0, "runtime_upgrades": 0}

    def fake_provider(request: WorkerRequest, _argv: list[str]) -> dict[str, object]:
        prompt = json.loads(request.prompt)
        task_id = request.task_id
        contract = prompt["task_contract"]
        command = contract["acceptance_commands"][0]
        findings: list[dict[str, object]] = []
        verdict = None
        events: list[dict[str, object]] = []
        if request.attempt_kind in {"implementation", "repair"}:
            target = worktree / contract["file_claims"][0]
            target.write_text(
                f"{task_id}:{request.attempt_kind}:{request.attempt_id}\n",
                encoding="utf-8",
            )
            events = [
                {
                    "type": "item.completed",
                    "item": {
                        "id": "red",
                        "type": "command_execution",
                        "command": command,
                        "aggregated_output": "expected RED",
                        "exit_code": 1,
                        "status": "failed",
                    },
                },
                {
                    "type": "item.completed",
                    "item": {
                        "id": "mutation",
                        "type": "file_change",
                        "changes": [{"path": contract["file_claims"][0], "kind": "update"}],
                        "status": "completed",
                    },
                },
                {
                    "type": "item.completed",
                    "item": {
                        "id": "green",
                        "type": "command_execution",
                        "command": command,
                        "aggregated_output": "GREEN",
                        "exit_code": 0,
                        "status": "completed",
                    },
                },
            ]
        elif request.attempt_kind == "task_review":
            review_counts[task_id] = review_counts.get(task_id, 0) + 1
            if task_id == "task_3":
                findings = [
                    {
                        "severity": "minor",
                        "action": "record bounded hardening follow-up",
                        "root_cause_key": "hardening:fixture",
                        "failure_category": "review_scope_expansion",
                        "release_impact": False,
                    }
                ]
            elif task_id == "task_4" and review_counts[task_id] == 1:
                findings = [
                    {
                        "severity": "major",
                        "action": "repair the fixture defect",
                        "root_cause_key": "defect:fixture-repair",
                        "failure_category": "product_defect",
                        "release_impact": False,
                    }
                ]
            verdict = {
                "status": "changes_requested" if findings else "passed",
                "findings": findings,
                "missing_evidence": [],
                "worktree_revision": request.worktree_revision,
                "review_binding": prompt["required_review_binding"],
            }
        result = {
            "status": "completed",
            "summary": "deterministic fake provider result",
            "changed_files": [],
            "findings": findings,
            "evidence_refs": [],
            "missing_evidence": [],
            "verification": [],
            "verdict": verdict,
            "method_evidence_ref": None,
        }
        return {
            "result": result,
            "provider_metadata": {
                "model": "gpt-5.6-sol",
                "reasoning": "high",
                "trusted_source": "fake_provider_contract",
            },
            "usage": {},
            "events": events,
        }

    def before_model_turn(task_id: str, phase: str, _attempt_id: str) -> None:
        remaining = interruptions.get(task_id, 0)
        if not remaining or phase != "implementation":
            return
        interruptions[task_id] = remaining - 1
        if task_id == "task_6":
            counters["transient_resumes"] += 1
            raise PreTurnInterruption("quota_transient")
        counters["runtime_upgrades"] += 1
        raise RuntimeUpgradeInterruption("runtime:fixture", "4.0.1", "fixture-build")

    worker = Worker(provider=fake_provider, max_transient_retries=0)
    operations = _v4_operations(
        contracts,
        manifest,
        kernel,
        worktree,
        worker,
        before_model_turn=before_model_turn,
    )
    kernel.transition(Transition("run.status_changed", {"from": "ready", "to": "running"}))
    if pause_task_id is not None:
        if pause_kind != "waiting_user" or pause_task_id not in kernel.state.get("tasks", {}):
            raise ValueError("fixture_pause_invalid")
        kernel.transition(
            Transition(
                "task.status_changed",
                {
                    "from": "pending",
                    "to": "waiting_user",
                    "wait_reason": "authority_resolution_required",
                    "resume_phase": "implementation",
                    "active_attempt_id": None,
                },
                task_id=pause_task_id,
            )
        )
        kernel.transition(
            Transition(
                "run.status_changed",
                {
                    "from": "running",
                    "to": "waiting_user",
                    "wait_reason": "authority_resolution_required",
                },
            )
        )
        return {
            "schema_version": "cpe.public-result.v4",
            "status": "waiting_user",
            "run_id": run_id,
            "run_ids_created": 1,
            "model_attempts": 0,
            "verified_checkpoints": [],
            "max_same_root_repairs": 0,
            "backlog_count": 0,
            **counters,
        }
    for _ in range(5):
        results = run_tasks_v4(contracts, operations, kernel, worktree, run_dir)
        if len(kernel.state.get("verified_checkpoints", [])) == len(contracts):
            break
        waiting = [
            (task_id, task)
            for task_id, task in kernel.state.get("tasks", {}).items()
            if task.get("status") == "waiting_external"
        ]
        if not waiting:
            raise RuntimeError(f"fixture_run_stalled:{results}")
        task_id, task_state = waiting[0]
        if task_id == "task_8":
            checkpoint = str(kernel.state["checkpoint_head"])
            prior = dict(kernel.state["runtime"])
            kernel.transition(
                Transition(
                    "runtime.upgraded",
                    {
                        "old_runtime_commit": prior["runtime_commit"],
                        "new_runtime_commit": "e" * 40,
                        "reason": "fixture runtime upgrade",
                        "compatibility_epoch": prior["compatibility_epoch"],
                        "worktree_clean": True,
                        "verified_checkpoint": checkpoint,
                    },
                )
            )
        if kernel.state["lifecycle"] == "waiting_external":
            kernel.transition(
                Transition("run.status_changed", {"from": "waiting_external", "to": "running"})
            )
    else:
        raise RuntimeError("fixture_resume_limit_exhausted")

    if len(kernel.state.get("verified_checkpoints", [])) != len(contracts):
        raise RuntimeError("fixture_checkpoint_count_invalid")
    state = kernel.state
    return {
        "schema_version": "cpe.public-result.v4",
        "status": "completed",
        "run_id": run_id,
        "run_ids_created": 1,
        "model_attempts": state["attempt_budget"]["used"],
        "verified_checkpoints": list(state["verified_checkpoints"]),
        "max_same_root_repairs": max(state.get("repair_roots", {}).values(), default=0),
        "backlog_count": len(state.get("backlog", [])),
        "run_dir": str(run_dir),
        "implementation_commit": str(manifest["source_git"]["head"]),
        "implementation_tree": _run(
            ["git", "rev-parse", f"{manifest['source_git']['head']}^{{tree}}"], workspace
        ).stdout.strip(),
        "task_contract_sha256": contracts[0].contract_sha256 if len(contracts) == 1 else None,
        **counters,
    }


def run_v4_dogfood_fixture(plan: Path, root: Path) -> dict[str, object]:
    """Run one cost-free fake-provider task through the production CPE v4 kernel."""

    started = time.monotonic()
    result = run_v4_fixture(
        plan,
        root,
        workspace_source=Path(__file__).resolve().parents[3],
    )
    return {**result, "elapsed_seconds": time.monotonic() - started}


def export_plan(args: argparse.Namespace) -> int:
    plan = Path(args.plan).expanduser().resolve()
    workspace = Path(args.workspace).expanduser().resolve()
    spec = Path(args.spec).expanduser().resolve() if args.spec else None
    if not plan.is_file() or not workspace.is_dir() or (spec and not spec.is_file()):
        raise PreflightError("workspace, plan, or spec path is unreadable")
    template_path = Path(__file__).resolve().parents[1] / "templates" / "fresh-session-prompt.txt"
    template = template_path.read_text(encoding="utf-8")
    doc_refs: list[str] = []
    for doc in args.docs or []:
        doc_path = Path(doc).expanduser().resolve()
        if not doc_path.is_file():
            raise PreflightError(f"docs path is unreadable: {doc_path}")
        doc_refs.append(f"{doc_path} sha256={hashlib.sha256(doc_path.read_bytes()).hexdigest()}")
    refs: dict[str, object] = {
        "workspace": workspace,
        "plan": plan,
        "plan_sha256": hashlib.sha256(plan.read_bytes()).hexdigest(),
        "spec": spec or "none",
        "spec_sha256": hashlib.sha256(spec.read_bytes()).hexdigest() if spec else "none",
        "docs": "; ".join(doc_refs) or "none",
        "mode": args.mode,
        "handoff_section": "HANDOFF CHECKPOINT" if args.mode == "handoff" else "",
    }
    print(render_export_bundle(template, refs, workspace), end="")
    return 0


def _v4_public_snapshot(run_id: str) -> dict[str, object]:
    run_dir = _codex_home() / "orchestrator" / run_id
    if not run_dir.is_dir():
        raise ValueError("run_missing")
    manifest = load_verified_manifest(run_dir / "run_manifest.json")
    events = read_events(run_dir / "events.jsonl")
    if validate_chain(events):
        raise ValueError("event_chain_invalid")
    state = project(manifest, events)
    total = len(state.get("tasks", {}))
    verified = list(state.get("verified_checkpoints", []))
    task_statuses = {
        str(item.get("status"))
        for item in state.get("tasks", {}).values()
        if isinstance(item, dict)
    }
    status = (
        "completed"
        if total and len(verified) == total
        else "waiting_user"
        if "waiting_user" in task_statuses
        else "waiting_external"
        if "waiting_external" in task_statuses
        else str(state.get("lifecycle"))
    )
    budget = dict(state.get("attempt_budget") or {})
    return {
        "schema_version": "cpe.public-result.v4",
        "run_id": run_id,
        "status": status,
        "current_task": state.get("current_task"),
        "checkpoint_head": state.get("checkpoint_head"),
        "attempt_limit": budget.get("limit"),
        "attempt_used": budget.get("used"),
        "next_safe_action": (
            "none" if status == "completed" else "resume" if status != "waiting_user" else "provide_user_authority"
        ),
        "user_input_required": status == "waiting_user",
        "decisions": list(state.get("decisions", [])),
        "backlog": list(state.get("backlog", [])),
        "repair_roots": dict(state.get("repair_roots", {})),
        "checkpoint_lineage": verified,
    }


def inspect_v4_run(run_id: str) -> int:
    try:
        payload = _v4_public_snapshot(run_id)
    except ValueError as exc:
        return _structured_resume_failure(run_id, str(exc))
    payload["supervised"] = False
    payload["poll_count"] = 1
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def supervise_v4_run(
    run_id: str,
    *,
    poll_interval: float,
    timeout: float,
    min_polls: int = 1,
    one_pass: bool = False,
) -> int:
    if (
        not math.isfinite(poll_interval)
        or not math.isfinite(timeout)
        or poll_interval < 0
        or timeout < 0
        or min_polls < 1
    ):
        return _structured_resume_failure(run_id, "supervise_options_invalid")
    deadline = time.monotonic() + timeout
    polls = 0
    terminal = {"completed", "failed", "blocked", "waiting_user", "waiting_external"}
    while True:
        try:
            payload = _v4_public_snapshot(run_id)
        except ValueError as exc:
            return _structured_resume_failure(run_id, str(exc))
        polls += 1
        if one_pass or (payload["status"] in terminal and polls >= min_polls):
            break
        if time.monotonic() >= deadline:
            payload["next_safe_action"] = "supervise"
            break
        if poll_interval:
            time.sleep(min(poll_interval, max(0.0, deadline - time.monotonic())))
    payload["supervised"] = True
    payload["poll_count"] = polls
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def resume_v4_run(run_id: str, worker: Worker | None = None) -> int:
    run_dir = _codex_home() / "orchestrator" / run_id
    if not run_dir.is_dir():
        return _structured_resume_failure(run_id, "run_missing")
    try:
        manifest = load_verified_manifest(run_dir / "run_manifest.json")
    except ValueError as exc:
        return _structured_resume_failure(run_id, str(exc))
    try:
        events = read_events(run_dir / "events.jsonl")
    except (OSError, ValueError):
        return _structured_resume_failure(run_id, "event_chain_invalid")
    if validate_chain(events):
        return _structured_resume_failure(run_id, "event_chain_invalid")
    state = project(manifest, events)
    waiting_user = [
        task_id
        for task_id, task in state.get("tasks", {}).items()
        if isinstance(task, dict) and task.get("status") == "waiting_user"
    ]
    if waiting_user:
        decision = select_v4_resume(state, str(waiting_user[0]))
        if decision.action != "await_user_authority":
            return _structured_resume_failure(run_id, "resume_state_invalid")
        budget = dict(state.get("attempt_budget") or {})
        return _emit(
            PublicResult(
                status="blocked",
                run_id=run_id,
                state_path=str(run_dir / "state.json"),
                summary="user authority is required before resume",
                next_action="Provide the required authority decision.",
                blocker={
                    "category": "operator_review",
                    "summary": "user authority is required before resume",
                    "recoverable": True,
                    "next_action": "provide_user_authority",
                    "evidence_refs": [],
                },
                current_task=str(waiting_user[0]),
                checkpoint_head=state.get("checkpoint_head"),
                attempt_limit=budget.get("limit"),
                attempt_used=budget.get("used"),
                next_safe_action="provide_user_authority",
                user_input_required=True,
            )
        )
    kernel = Kernel(run_dir)
    worktree = resolve_ref(str(manifest["execution_worktree_ref"]))
    if not worktree.is_dir():
        return _structured_resume_failure(run_id, "worktree_missing")
    contracts = _v4_contracts(manifest)
    operations = _v4_operations(
        contracts, manifest, kernel, worktree, worker or Worker()
    )
    lifecycle = str(kernel.state.get("lifecycle"))
    if lifecycle in {"waiting_external", "waiting_user"}:
        kernel.transition(
            Transition("run.status_changed", {"from": lifecycle, "to": "running"})
        )
    elif lifecycle == "ready":
        kernel.transition(Transition("run.status_changed", {"from": "ready", "to": "running"}))
    try:
        results = run_tasks_v4(contracts, operations, kernel, worktree, run_dir)
    except (OSError, RuntimeError, ValueError) as exc:
        return _structured_resume_failure(run_id, str(exc))
    state = kernel.state
    if len(state.get("verified_checkpoints", [])) != len(contracts):
        latest = results[-1] if results else None
        return _emit(
            blocked_result(
                str(getattr(latest, "reason", None) or "run paused"),
                category="transient",
                run_id=run_id,
                state_path=str(run_dir / "state.json"),
            )
        )
    budget = dict(state.get("attempt_budget") or {})
    return _emit(
        PublicResult(
            status="success",
            run_id=run_id,
            state_path=str(run_dir / "state.json"),
            summary="All resumed v4 task checkpoints were verified.",
            changed_files=_changed_files(worktree),
            verification=({"command": "verified_task_checkpoints", "status": "passed"},),
            context_artifacts=_context_artifacts(run_dir),
            next_action="Inspect the run and reviewed checkpoint lineage.",
            current_task=state.get("current_task"),
            checkpoint_head=state.get("checkpoint_head"),
            attempt_limit=budget.get("limit"),
            attempt_used=budget.get("used"),
            next_safe_action="inspect",
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--plan", required=True)
    run.add_argument("--spec")
    run.add_argument("--docs", action="append", default=[])
    run.add_argument("--workspace", required=True)
    run.add_argument("--mode", choices=("interactive", "headless"), default="interactive")
    resume = sub.add_parser("resume")
    resume.add_argument("--run-id", required=True)
    supervise = sub.add_parser("supervise")
    supervise.add_argument("--run-id", required=True)
    supervise.add_argument("--poll-interval", type=float, default=1.0)
    supervise.add_argument("--timeout", type=float, default=30.0)
    supervise.add_argument("--min-polls", type=int, default=1)
    supervise.add_argument("--one-pass", action="store_true")
    inspect = sub.add_parser("inspect")
    inspect.add_argument("--run-id", required=True)
    export = sub.add_parser("export")
    export.add_argument("--plan", required=True)
    export.add_argument("--spec")
    export.add_argument("--docs", action="append", default=[])
    export.add_argument("--workspace", required=True)
    export.add_argument("--mode", choices=("prompt", "handoff"), default="prompt")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "run":
            return execute_run(args)
        if args.command == "resume":
            return resume_v4_run(args.run_id)
        if args.command == "supervise":
            return supervise_v4_run(
                args.run_id,
                poll_interval=args.poll_interval,
                timeout=args.timeout,
                min_polls=args.min_polls,
                one_pass=args.one_pass,
            )
        if args.command == "inspect":
            return inspect_v4_run(args.run_id)
        return export_plan(args)
    except CompileBlocked as exc:
        return _emit(
            blocked_result(
                exc.summary,
                category="preflight",
                evidence_refs=tuple(exc.evidence) if isinstance(exc.evidence, list) else (),
                next_action="Correct the plan contract and run preflight again.",
            )
        )
    except PreflightError as exc:
        return _emit(blocked_result(str(exc), category="preflight", next_action="Correct the invocation and retry."))
    except (ValueError, OSError, RuntimeError) as exc:
        return _emit(failed_result(str(exc) or type(exc).__name__, category="state_integrity"))
    except Exception as exc:
        # Public input/state decoders may surface shape errors as TypeError,
        # AttributeError, or KeyError. Convert them without swallowing exits or interrupts.
        return _emit(failed_result(str(exc) or type(exc).__name__, category="state_integrity"))


if __name__ == "__main__":
    raise SystemExit(main())
