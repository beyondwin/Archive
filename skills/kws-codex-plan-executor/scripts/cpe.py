#!/usr/bin/env python3
"""Run, resume, or export a CPE v3 implementation plan."""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from preflight_dependencies import check_requirements

from cpe_runtime.events import read_events, validate_chain
from cpe_runtime.evidence import put_json
from cpe_runtime.kernel import Kernel, RunKernel, Transition, rebuild_snapshot
from cpe_runtime.manifest import create_manifest, load_verified_manifest, resolve_ref
from cpe_runtime.packets import build_packet
from cpe_runtime.plan_compiler import CompileBlocked, compile_run
from cpe_runtime.projector import project
from cpe_runtime.prompt_export import render_export_bundle
from cpe_runtime.reconciliation import select_resume
from cpe_runtime.repair import apply_repair
from cpe_runtime.scheduler import run_tasks
from cpe_runtime.validation import validate_integrity, validate_run
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


def _create_worktree(workspace: Path, worktree: Path, run_id: str) -> str:
    worktree.parent.mkdir(parents=True, exist_ok=True)
    branch = f"codex/{run_id}"
    result = _run(["git", "worktree", "add", "-q", "-b", branch, str(worktree), "HEAD"], workspace)
    if result.returncode:
        raise PreflightError(f"worktree creation failed: {result.stderr.strip()}")
    return branch


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
    status = list(compiled.source_status)
    run_id, run_dir, worktree = _allocate_paths(plan)
    _create_worktree(workspace, worktree, run_id)
    pricing = Path(__file__).resolve().parents[1] / "data" / "pricing-snapshot.json"
    manifest = create_manifest(
        run_id,
        args.mode,
        workspace,
        worktree,
        plan,
        spec,
        tasks,
        pricing,
        docs=docs,
        source_head=head,
        source_status=status,
    )
    packet_drafts = [build_packet(compiled, task) for task in tasks]
    kernel = RunKernel.initialize(run_dir, manifest, packet_drafts)
    kernel.transition(Transition("run.status_changed", {"from": "created", "to": "ready"}))
    result = run_tasks(tasks, Worker(), kernel)
    payload = {"run_id": run_id, "run_dir": str(run_dir), "worktree": str(worktree), **result}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "completed" else 1


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
    print(
        json.dumps({"classification": classification, "run_id": run_id, **extra}, ensure_ascii=False),
        file=sys.stderr,
    )
    return 2


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
        validation = validate_run(run_dir)
        if not validation.passed:
            return _structured_resume_failure(run_id, "completed_run_invalid", errors=validation.errors)
        print(json.dumps({"run_id": run_id, "status": "completed"}))
        return 0
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
        print(json.dumps({"run_id": run_id, "status": "blocked", "category": "workspace_precondition", "evidence_refs": refs}, ensure_ascii=False))
        return 1

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
        print(json.dumps({"run_id": run_id, "status": "blocked", "blocker_id": decision.blocker_id}, ensure_ascii=False))
        return 1
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
    result = run_tasks(list(manifest["task_graph"]), worker or Worker(), kernel)
    print(json.dumps({"run_id": run_id, **result}, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "completed" else 1


def export_plan(args: argparse.Namespace) -> int:
    plan = Path(args.plan).expanduser().resolve()
    workspace = Path(args.workspace).expanduser().resolve()
    spec = Path(args.spec).expanduser().resolve() if args.spec else None
    if not plan.is_file() or not workspace.is_dir() or (spec and not spec.is_file()):
        raise PreflightError("workspace, plan, or spec path is unreadable")
    body = plan.read_text(encoding="utf-8")
    if spec:
        body += f"\n\nSPEC PATH: {spec}\n"
    for doc in args.docs or []:
        doc_path = Path(doc).expanduser().resolve()
        if not doc_path.is_file():
            raise PreflightError(f"docs path is unreadable: {doc_path}")
        body += f"\n\nDOC PATH: {doc_path}\n{doc_path.read_text(encoding='utf-8')}\n"
    if args.mode == "handoff":
        body = "HANDOFF CHECKPOINT\n\n" + body
    print(render_export_bundle(body, workspace), end="")
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
        print(
            json.dumps(
                {
                    "classification": "preflight_blocked",
                    "category": exc.category,
                    "error": exc.summary,
                    "evidence": exc.evidence,
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2
    except PreflightError as exc:
        print(json.dumps({"classification": "preflight_blocked", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
