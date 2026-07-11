#!/usr/bin/env python3
"""Run, resume, or export a CPE v3 implementation plan."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import subprocess
from datetime import datetime
from pathlib import Path

from preflight_dependencies import check_requirements

from cpe_runtime.events import read_events, validate_chain
from cpe_runtime.evidence import put_json
from cpe_runtime.kernel import Kernel, RunKernel, Transition, rebuild_snapshot
from cpe_runtime.manifest import canonical_hash, file_record, load_verified_manifest, relative_ref, resolve_ref
from cpe_runtime.model_policy import policy_hash, policy_payload
from cpe_runtime.packets import build_packet
from cpe_runtime.plan_compiler import CompileBlocked, compile_run
from cpe_runtime.projector import project
from cpe_runtime.prompt_export import render_export_bundle
from cpe_runtime.public_result import PublicResult, blocked_result, failed_result
from cpe_runtime.reconciliation import select_resume
from cpe_runtime.repair import apply_repair
from cpe_runtime.scheduler import run_tasks
from cpe_runtime.validation import validate_completion, validate_integrity
from cpe_runtime.worker import Worker


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
    return {
        "schema_version": "3",
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
        "task_packets": [],
    }


def _emit(result: PublicResult) -> int:
    print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
    return result.exit_code()


def _context_artifacts(run_dir: Path) -> dict[str, str | None]:
    return {
        "spec_manifest_path": str(run_dir / "run_manifest.json"),
        "task_packet_dir": str(run_dir / "artifacts" / "task-packets"),
        "decisions_path": None,
    }


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
    branch = _create_worktree(workspace, worktree, run_id, head)
    pricing = Path(__file__).resolve().parents[1] / "data" / "pricing-snapshot.json"
    try:
        manifest = _compiled_manifest(run_id, args.mode, workspace, worktree, run_dir, compiled, pricing)
        packet_drafts = [build_packet(compiled, task) for task in tasks]
        kernel = RunKernel.initialize(run_dir, manifest, packet_drafts, input_sources=compiled.sources)
    except (ValueError, OSError, RuntimeError) as exc:
        _cleanup_unpublished_worktree(workspace, worktree, branch, head, run_id, run_dir)
        return _emit(
            failed_result(
                str(exc) or type(exc).__name__,
                category="environment" if isinstance(exc, OSError) else "state_integrity",
                run_id=run_id,
                next_action="Correct initialization inputs and start a new run.",
            )
        )
    except BaseException:
        _cleanup_unpublished_worktree(workspace, worktree, branch, head, run_id, run_dir)
        raise
    kernel.transition(Transition("run.status_changed", {"from": "created", "to": "ready"}))
    try:
        result = run_tasks(tasks, Worker(), kernel)
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
        state = kernel.state
        blocker = (state.get("active_blockers") or [{}])[-1]
        summary = str(result.get("reason") or blocker.get("category") or "run blocked")
        phase = str(result.get("phase") or "")
        reason = str(result.get("reason") or blocker.get("category") or "")
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
    completion = validate_completion(run_dir)
    if not completion.passed:
        return _emit(
            failed_result(
                "completion validation failed: " + ",".join(completion.errors),
                category="state_integrity",
                run_id=run_id,
                state_path=str(run_dir / "state.json"),
            )
        )
    return _emit(
        PublicResult(
            status="success",
            run_id=run_id,
            state_path=str(run_dir / "state.json"),
            summary="Run completed and passed canonical completion validation.",
            changed_files=_changed_files(worktree),
            verification=({"command": "validate_completion", "status": "passed"},),
            residual_risk=("paid live migration gate pending",),
            context_artifacts=_context_artifacts(run_dir),
            next_action="Review the isolated worktree changes.",
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

    decision = select_resume(state, integrity)
    if decision.action == "reject":
        return _structured_resume_failure(run_id, "resume_rejected", errors=integrity.errors)
    if decision.action == "remain_blocked":
        return _emit(blocked_result(
            f"run remains blocked: {decision.blocker_id}",
            category="operator_review",
            run_id=run_id,
            state_path=str(run_dir / "state.json"),
        ))
    if decision.action != "retry" or decision.phase is None:
        return _structured_resume_failure(run_id, "resume_state_invalid")

    refs = [dict(ref) for ref in decision.evidence_refs]
    blocker_id = decision.blocker_id
    if blocker_id is not None:
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
            return resume_run(args.run_id)
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
