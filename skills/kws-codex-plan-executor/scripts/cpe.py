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
from cpe_runtime.kernel import Kernel, RunKernel, Transition, rebuild_snapshot
from cpe_runtime.manifest import create_manifest, load_verified_manifest
from cpe_runtime.packets import build_packet
from cpe_runtime.plan_compiler import CompileBlocked, compile_run
from cpe_runtime.projector import project
from cpe_runtime.prompt_export import render_export_bundle
from cpe_runtime.scheduler import run_tasks
from cpe_runtime.validation import validate_run
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


def resume_run(run_id: str) -> int:
    run_dir = _codex_home() / "orchestrator" / run_id
    if not run_dir.is_dir():
        print(json.dumps({"classification": "run_missing", "run_id": run_id}), file=sys.stderr)
        return 2
    try:
        manifest = load_verified_manifest(run_dir / "run_manifest.json")
        events = read_events(run_dir / "events.jsonl")
    except ValueError as exc:
        print(json.dumps({"classification": str(exc), "run_id": run_id}), file=sys.stderr)
        return 2
    except OSError:
        print(json.dumps({"classification": "manifest_missing", "run_id": run_id}), file=sys.stderr)
        return 2
    if validate_chain(events):
        print(json.dumps({"classification": "event_chain_invalid", "run_id": run_id}), file=sys.stderr)
        return 2
    state = project(manifest, events)
    if state["lifecycle"] == "completed":
        validation = validate_run(run_dir)
        if not validation.passed:
            print(json.dumps({"classification": "completed_run_invalid", "run_id": run_id, "errors": validation.errors}), file=sys.stderr)
            return 2
        print(json.dumps({"run_id": run_id, "status": "completed"}))
        return 0
    if state["lifecycle"] == "blocked":
        Kernel(run_dir).transition(Transition("run.status_changed", {"from": "blocked", "to": "ready", "reason": "explicit resume"}))
    rebuild_snapshot(run_dir)
    result = run_tasks(list(manifest["task_graph"]), Worker(), Kernel(run_dir))
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
