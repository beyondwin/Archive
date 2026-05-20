from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .adapters.claude import ClaudeAdapter
from .adapters.codex import CodexAdapter
from .adapters.local import LocalAdapter
from .agentlens import create_agentlens_emitter
from .apply import ApplyError, apply_commits_to_source
from .artifact_graph import write_artifact_graph
from .artifacts import ArtifactStore
from .candidate_selection import select_candidate
from .config import BuiltinProfiles, ModelProfile, load_effective_config
from .contract import build_run_contract, write_contract
from .db import AgentRunwayDb
from .decision_events import record_candidate_ranked, record_quality_decision
from .durable_resume import plan_activity_resume
from .events import EventJournal, build_event_payload
from .failure_classifier import classify_gate_failure, classify_plan_failure
from .git_ops import Git, assert_clean_source
from .integration_manager import IntegrationManager
from .merge_queue import MergeCandidate, MergeConflictError
from .packetizer import build_task_packet, materialize_prompt, materialize_worker_prompt, packet_to_json
from .plan_parser import canonical_hash, parse_plan, parse_spec_manifest
from .plan_lint import lint_plan
from .preflight import run_preflight
from .quality_policy import PolicyDecision, candidate_count_for_task, gate_retry_decision
from .reconciliation import apply_reconciliation_plan, plan_reconciliation
from .retention import clean_retention
from .scheduler import schedule_waves
from .supervisor import next_worker_id, run_implementer_attempt, run_reviewer_attempt, run_verifier_attempt
from .workflow_store import ActivityStatus, WorkflowStore
from .worktrees import create_main_worktree, next_available_run_id, workspace_id
from .worktree_lifecycle import archive_candidate_evidence, lifecycle_for_worker, reviewer_mode_for_task


def agentrunway_home() -> Path:
    return Path(os.environ.get("AGENTRUNWAY_HOME", str(Path.home() / ".agentrunway"))).expanduser()


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "run"


def _now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _nonce() -> str:
    return hashlib.sha1(str(datetime.now(timezone.utc).timestamp()).encode()).hexdigest()[:5]


def _state_paths(run_id: str, wsid: str) -> tuple[Path, Path]:
    home = agentrunway_home()
    run_dir = home / "runs" / wsid / run_id
    worktree_root = home / "worktrees" / wsid / run_id
    return run_dir, worktree_root


def allocate_run_id(repo: Path, plan: Path, requested: str | None = None) -> str:
    if requested:
        return requested
    base_run_id = f"{_slug(plan.stem)}-{_now_stamp()}-{_nonce()}"
    return next_available_run_id(repo, base_run_id)


def _find_run_dir(run_id: str) -> Path | None:
    runs_root = agentrunway_home() / "runs"
    if not runs_root.exists():
        return None
    for path in runs_root.glob(f"*/{run_id}"):
        if path.is_dir():
            return path
    return None


def _spec_slices(spec: Path, task_refs: tuple[str, ...]) -> list[dict[str, str]]:
    if not spec:
        return []
    manifest = parse_spec_manifest(spec)
    sections = manifest["sections"]
    refs = task_refs or tuple(manifest["section_order"][:1])
    return [
        {"id": ref, "title": sections.get(ref, {}).get("title", ref), "text": sections.get(ref, {}).get("text", "")}
        for ref in refs
    ]


def _write_run_json(run_dir: Path, payload: dict[str, Any]) -> None:
    (run_dir / "run.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _write_early_run_json(run_dir: Path, payload: dict[str, Any]) -> bool:
    try:
        run_dir.mkdir(parents=True, exist_ok=True)
        _write_run_json(run_dir, payload)
    except OSError:
        return False
    return True


def _load_run_json(run_id: str) -> dict[str, Any] | None:
    run_dir = _find_run_dir(run_id)
    if run_dir is None or not (run_dir / "run.json").exists():
        return None
    return json.loads((run_dir / "run.json").read_text(encoding="utf-8"))


def _load_run_json_or_reconstruct(run_id: str) -> dict[str, Any] | None:
    data = _load_run_json(run_id)
    if data is not None:
        return data
    run_dir = _find_run_dir(run_id)
    if run_dir is None:
        return None
    from .run_summary import reconstruct_run_json

    return reconstruct_run_json(run_id=run_id, run_dir=run_dir)


def _select_adapter(name: str, profile: ModelProfile, *, fake_success: bool = False) -> tuple[Any, str, str, str]:
    model = profile.workers.get("default", profile.orchestrator)
    effort = model.reasoning_effort_resolved or model.reasoning_effort
    if name == "local":
        return LocalAdapter(fake_success=fake_success), "local", "local", "n/a"
    if name == "codex":
        return CodexAdapter(model=model.model, reasoning_effort=effort), "codex", model.model, effort
    if name == "claude":
        return ClaudeAdapter(model=model.model, reasoning_effort=effort), "claude", model.model, effort
    raise ValueError(f"unsupported adapter: {name}")


def _merge_candidate(db: AgentRunwayDb, candidate_id: int) -> dict[str, Any]:
    for candidate in db.list_merge_candidates():
        if int(candidate["id"]) == candidate_id:
            return candidate
    raise KeyError(candidate_id)


def _candidate_for_ranking(candidate: dict[str, Any]) -> dict[str, Any]:
    status = str(candidate.get("status") or "")
    return {
        "id": int(candidate["id"]),
        "task_id": candidate["task_id"],
        "worker_id": candidate["worker_id"],
        "status": status,
        "verification_status": "passed" if status in {"merge_ready", "merged"} else status,
        "review_status": "approved" if status in {"merge_ready", "merged"} else status,
        # v1 stub: signals 3-7 are placeholders pending follow-up.
        "file_claim_violation": False,
        "required_artifacts_present": True,
        "acceptance_evidence_present": bool(candidate.get("commits")),
        "scope_match": True,
        "unexpected_changed_files": 0,
    }


def _candidate_diff(db: AgentRunwayDb, candidate: dict[str, Any], base_ref: str) -> str:
    worker = db.get_worker(str(candidate["worker_id"]))
    worker_tree = Path(str(worker["worktree_path"]))
    return Git(worker_tree).run("diff", base_ref, "HEAD", check=False).stdout


def _retry_context(reason: str, result: dict[str, object], candidate: dict[str, Any]) -> dict[str, object]:
    return {
        "retry_reason": reason,
        "previous_candidate": {
            "id": candidate["id"],
            "worker_id": candidate["worker_id"],
            "status": candidate["status"],
            "changed_files": candidate["changed_files"],
            "commits": candidate["commits"],
        },
        "gate_result": result,
    }


def _record_gate_retry(
    journal: EventJournal,
    *,
    run_id: str,
    task_id: str,
    reason: str,
    next_attempt: int,
) -> None:
    journal.record(
        "agentrunway.gate_retry",
        build_event_payload(
            run_id,
            "gate",
            "partial",
            "gate requested implementer retry",
            task_id=task_id,
            reason=reason,
            next_attempt=next_attempt,
        ),
    )


def _record_run_blocked(journal: EventJournal, *, run_id: str, task_id: str, reason: str) -> None:
    journal.record(
        "agentrunway.run_blocked",
        build_event_payload(
            run_id,
            "run",
            "failed",
            "run blocked",
            task_id=task_id,
            reason=reason,
        ),
    )


_HUMAN_DECISION_FAILURE_CLASSES = {
    "needs_plan_fix",
    "needs_split",
    "needs_human_decision",
    "needs_infra_fix",
    "terminal_rejected",
}


def _artifact_ref(run_dir: Path, path: Path) -> str:
    try:
        return str(path.relative_to(run_dir))
    except ValueError:
        return str(path)


def _gate_activity_status(*, failure_class: str, decision: PolicyDecision) -> ActivityStatus:
    if decision.action == "block" and failure_class in _HUMAN_DECISION_FAILURE_CLASSES:
        return ActivityStatus.BLOCKED
    return ActivityStatus.FAILED


def _gate_decision_packet(
    *,
    store: WorkflowStore,
    run_id: str,
    task_id: str,
    gate: str,
    attempt: int,
    failure_class: str,
    summary: str,
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    if failure_class not in _HUMAN_DECISION_FAILURE_CLASSES:
        return None
    return store.create_decision_packet(
        run_id=run_id,
        decision_id=f"{task_id}.{gate}.{attempt:03d}.decision",
        task_id=task_id,
        failure_class=failure_class,
        summary=summary,
        payload=payload,
    )


def _decision_for_classification(
    *,
    gate: str,
    classification_failure_class: str,
    policy_decision: PolicyDecision,
) -> PolicyDecision:
    if classification_failure_class in _HUMAN_DECISION_FAILURE_CLASSES and policy_decision.action != "block":
        return PolicyDecision(
            action="block",
            reason=f"{gate}_{classification_failure_class}",
            outcome="failed",
        )
    return policy_decision


def run(args: Any) -> dict[str, Any]:
    repo = Path.cwd().resolve()
    plan = args.plan.resolve()
    spec = args.spec.resolve() if args.spec else None
    ignored = {str(plan.relative_to(repo))} if plan.is_relative_to(repo) else set()
    if spec and spec.is_relative_to(repo):
        ignored.add(str(spec.relative_to(repo)))
    assert_clean_source(repo, allow_dirty=bool(args.allow_dirty_source), ignored=ignored)

    cfg = load_effective_config(repo, vars(args))
    wsid = workspace_id(repo)
    run_id = allocate_run_id(repo, plan, getattr(args, "run_id", None))
    run_dir, worktree_root = _state_paths(run_id, wsid)
    lint = lint_plan(plan_path=plan, spec_path=spec)
    if not lint.ok:
        classification = classify_plan_failure(lint_result=lint.to_dict())
        payload = {
            "run_id": run_id,
            "workspace_id": wsid,
            "status": "plan_lint_failed",
            "run_dir": str(run_dir),
            "state_db": None,
            "plan_lint": lint.to_dict(),
            "failure_class": classification.failure_class,
            "decision_packet": {
                "decision_id": f"{run_id}.plan_lint.decision",
                "failure_class": classification.failure_class,
                "summary": classification.summary,
                "payload": {
                    "next_action": classification.next_action,
                    "plan_lint": lint.to_dict(),
                },
            },
        }
        payload["state_persisted"] = _write_early_run_json(run_dir, payload)
        return payload
    preflight = run_preflight(
        adapter_name=str(args.adapter),
        repo=repo,
        run_dir=run_dir,
        worktree_root=worktree_root,
    )
    if not preflight.ok:
        payload = {
            "run_id": run_id,
            "workspace_id": wsid,
            "status": "preflight_failed",
            "run_dir": str(run_dir),
            "state_db": None,
            "preflight": preflight.to_dict(),
        }
        payload["state_persisted"] = _write_early_run_json(run_dir, payload)
        return payload
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "packets").mkdir(exist_ok=True)
    (run_dir / "prompts").mkdir(exist_ok=True)
    (run_dir / "artifacts").mkdir(exist_ok=True)

    git = Git(repo)
    base_commit = git.rev_parse(args.base_ref)
    db = AgentRunwayDb.open(run_dir / "state.sqlite")
    db.create_run(
        run_id=run_id,
        workspace_id=wsid,
        repo_root=str(repo),
        plan_path=str(plan),
        spec_path=str(spec) if spec else None,
        plan_hash=canonical_hash(plan),
        spec_hash=canonical_hash(spec) if spec else None,
        base_commit_sha=base_commit,
        model_profile=cfg.default_profile,
        allowed_dirty=args.allow_dirty_source,
        apply_to_source=args.apply_to_source,
    )
    tasks = parse_plan(plan)
    contract = build_run_contract(
        run_id=run_id,
        workspace_id=wsid,
        repo_root=repo,
        spec_path=spec,
        plan_path=plan,
        base_commit_sha=base_commit,
        tasks=tasks,
        adapter=args.adapter,
        model_profile=cfg.default_profile,
        allow_dirty_source=bool(args.allow_dirty_source),
        apply_to_source=bool(args.apply_to_source),
    )
    contract_path = write_contract(run_dir, contract)
    db.set_run_contract_path(run_id, str(contract_path))
    agentlens_emitter = create_agentlens_emitter(agentrunway_run_id=run_id, workspace=repo)
    db.set_run_agentlens(
        run_id,
        agentlens_run_id=agentlens_emitter.agentlens_run_id if agentlens_emitter is not None else None,
        status="active" if agentlens_emitter is not None else "disabled",
    )
    journal = EventJournal(db=db, run_dir=run_dir, agentlens_emitter=agentlens_emitter)
    journal.record("agentrunway.run_started", build_event_payload(run_id, "run", "success", "run started"))
    journal.record(
        "agentrunway.contract_created",
        build_event_payload(run_id, "contract", "success", "contract created", contract_path=str(contract_path)),
    )
    write_artifact_graph(run_dir=run_dir, db=db)
    profile = cfg.profiles[cfg.default_profile]
    for task in tasks:
        db.upsert_task(task)
        packet = build_task_packet(run_id, task, _spec_slices(spec, task.spec_refs) if spec else [], profile)
        prompt_path = materialize_prompt(packet, run_dir / "prompts")
        db.insert_packet(task.task_id, hashlib.sha256(packet_to_json(packet).encode()).hexdigest(), str(prompt_path), packet_to_json(packet))
    waves = schedule_waves(tasks)
    run_json = {
        "run_id": run_id,
        "workspace_id": wsid,
        "status": "planning_only" if args.planning_only else "created",
        "run_dir": str(run_dir),
        "state_db": str(run_dir / "state.sqlite"),
        "repo_root": str(repo),
        "tasks": [asdict(task) for task in tasks],
        "waves": waves,
    }
    _write_run_json(run_dir, run_json)
    if args.planning_only:
        db.set_run_status(run_id, "planning_only")
        _write_run_json(run_dir, run_json)
        return run_json

    main_worktree = create_main_worktree(git, worktree_root / "main", run_id, base_commit)
    db.register_worktree(
        path=str(main_worktree),
        run_id=run_id,
        branch=f"agentrunway/{run_id}/main",
        lifecycle="run_main_persistent",
    )
    workflow_store = WorkflowStore(db)
    workflow_store.create_checkpoint(
        run_id=run_id,
        checkpoint_id="cp-000",
        commit_sha=Git(main_worktree).rev_parse("HEAD"),
        parent_checkpoint_id=None,
        merged_candidate_id=None,
        reason="initial",
    )
    integration_manager = IntegrationManager(
        db=db,
        store=workflow_store,
        run_id=run_id,
        main_worktree=main_worktree,
    )
    db.set_run_status(run_id, "running")
    run_json.update({"status": "running", "main_worktree": str(main_worktree)})
    _write_run_json(run_dir, run_json)
    adapter, runtime, model, reasoning_effort = _select_adapter(
        args.adapter,
        profile,
        fake_success=bool(args.fake_success),
    )
    store = ArtifactStore(run_dir / "artifacts")
    for task in tasks:
        packet_path = run_dir / "packets" / f"{task.task_id}.json"
        packet_json = db.conn.execute("SELECT packet_json FROM task_packets WHERE task_id=?", (task.task_id,)).fetchone()["packet_json"]
        packet_path.write_text(packet_json, encoding="utf-8")
        task_artifact_dir = run_dir / "artifacts" / task.task_id
        task_artifact_dir.mkdir(parents=True, exist_ok=True)
        if runtime == "local":
            result = adapter.run(packet_path, task_artifact_dir)
            store.write_text(task.task_id, "worker_result.json", json.dumps(asdict(result), indent=2, sort_keys=True))
            db.set_task_status(task.task_id, "merged" if result.status == "success" else "blocked")
            if result.status != "success":
                _record_run_blocked(journal, run_id=run_id, task_id=task.task_id, reason="local_worker_failed")
        else:
            packet = build_task_packet(run_id, task, _spec_slices(spec, task.spec_refs) if spec else [], profile)
            target_candidate_count = candidate_count_for_task(task)
            merge_ready_candidate_ids: list[int] = []
            review_retries = 0
            verification_retries = 0
            implementer_context: dict[str, object] | None = None
            while len(merge_ready_candidate_ids) < target_candidate_count:
                _, implementer_attempt = next_worker_id(db=db, task_id=task.task_id, role="implementer")
                worker_id = f"{task.task_id}-implementer-{implementer_attempt:03d}"
                output_path = run_dir / "artifacts" / task.task_id / worker_id / "worker_result.json"
                prompt_path = materialize_worker_prompt(
                    packet,
                    packet_path,
                    output_path,
                    run_dir / "prompts",
                    context=implementer_context,
                )
                implement_activity_id = f"{task.task_id}.implement.{implementer_attempt:03d}"
                workflow_store.start_activity(
                    run_id=run_id,
                    activity_id=implement_activity_id,
                    idempotency_key=f"{run_id}:{task.task_id}:implement:{implementer_attempt:03d}",
                    task_id=task.task_id,
                    activity_type="implement",
                    input_refs={
                        "packet": _artifact_ref(run_dir, packet_path),
                        "prompt": _artifact_ref(run_dir, prompt_path),
                        "checkpoint_id": (workflow_store.latest_checkpoint(run_id) or {}).get("checkpoint_id"),
                    },
                )
                journal.record(
                    "agentrunway.worker_dispatched",
                    build_event_payload(
                        run_id,
                        "worker",
                        "success",
                        "worker dispatched",
                        task_id=task.task_id,
                        worker_id=worker_id,
                        role="implementer",
                        attempt=implementer_attempt,
                        runtime=runtime,
                        model=model,
                    ),
                )
                try:
                    candidate_id = run_implementer_attempt(
                        db=db,
                        run_id=run_id,
                        git=git,
                        main_worktree=main_worktree,
                        worktree_root=worktree_root,
                        run_dir=run_dir,
                        task=task,
                        packet_path=packet_path,
                        prompt_path=prompt_path,
                        adapter=adapter,
                        runtime=runtime,
                        model=model,
                        reasoning_effort=reasoning_effort,
                        attempt=implementer_attempt,
                        timeout_seconds=600,
                    )
                except Exception as exc:
                    journal.record(
                        "agentrunway.worker_result",
                        build_event_payload(
                            run_id,
                            "worker",
                            "failed",
                            "worker failed",
                            task_id=task.task_id,
                            worker_id=worker_id,
                            role="implementer",
                            attempt=implementer_attempt,
                            error=str(exc),
                        ),
                    )
                    workflow_store.complete_activity(
                        activity_id=implement_activity_id,
                        status=ActivityStatus.FAILED,
                        output_refs={"error": str(exc), "worker_id": worker_id},
                        failure_class="needs_infra_fix",
                    )
                    db.set_run_status(run_id, "failed")
                    run_json.update(
                        {
                            "status": "failed",
                            "main_worktree": str(main_worktree),
                            "tasks": db.list_tasks(),
                            "error": str(exc),
                        }
                    )
                    _write_run_json(run_dir, run_json)
                    raise
                candidate = _merge_candidate(db, candidate_id)
                workflow_store.complete_activity(
                    activity_id=implement_activity_id,
                    status=ActivityStatus.COMPLETED,
                    output_refs={
                        "worker_id": worker_id,
                        "candidate_id": candidate_id,
                        "worker_result": _artifact_ref(run_dir, output_path),
                    },
                    failure_class=None,
                )
                journal.record(
                    "agentrunway.worker_result",
                    build_event_payload(
                        run_id,
                        "worker",
                        "success",
                        "worker result",
                        task_id=task.task_id,
                        worker_id=candidate["worker_id"],
                        candidate_id=candidate_id,
                        changed_files=candidate["changed_files"],
                        commits=candidate["commits"],
                    ),
                )
                base_ref = f"agentrunway/{run_id}/main"
                diff = _candidate_diff(db, candidate, base_ref)
                db.set_task_status(task.task_id, "reviewing")
                review_mode = reviewer_mode_for_task(task)
                needs_context_escalated = False
                while True:
                    journal.record(
                        "agentrunway.review_dispatched",
                        build_event_payload(
                            run_id,
                            "review",
                            "success",
                            "review dispatched",
                            task_id=task.task_id,
                            worker_id=candidate["worker_id"],
                            review_mode=review_mode,
                        ),
                    )
                    _, review_attempt = next_worker_id(db=db, task_id=task.task_id, role="reviewer")
                    review_worker_id = f"{task.task_id}-reviewer-{review_attempt:03d}"
                    review_activity_id = f"{task.task_id}.review.{review_attempt:03d}"
                    review_result_path = run_dir / "artifacts" / task.task_id / review_worker_id / "review_result.json"
                    workflow_store.start_activity(
                        run_id=run_id,
                        activity_id=review_activity_id,
                        idempotency_key=f"{run_id}:{task.task_id}:review:{review_attempt:03d}",
                        task_id=task.task_id,
                        activity_type="review",
                        input_refs={
                            "candidate_id": candidate_id,
                            "worker_id": candidate["worker_id"],
                            "review_mode": review_mode,
                        },
                    )
                    review = run_reviewer_attempt(
                        db=db,
                        run_id=run_id,
                        git=git,
                        worktree_root=worktree_root,
                        run_dir=run_dir,
                        task=task,
                        adapter=adapter,
                        runtime=runtime,
                        model=model,
                        reasoning_effort=reasoning_effort,
                        reviewed_worker_id=str(candidate["worker_id"]),
                        candidate_diff=diff,
                        candidate_commits=tuple(candidate["commits"]),
                        attempt=review_attempt,
                        timeout_seconds=600,
                        review_mode=review_mode,
                    )
                    review_status = str(review["status"])
                    review_classification = None
                    journal.record(
                        "agentrunway.review_result",
                        build_event_payload(
                            run_id,
                            "review",
                            "success" if review_status == "approved" else "partial",
                            "review result",
                            task_id=task.task_id,
                            status=review_status,
                            review_mode=review_mode,
                        ),
                    )
                    if review_status == "needs_context" and review_mode == "diff" and not needs_context_escalated:
                        review_classification = classify_gate_failure(
                            gate="review",
                            status=review_status,
                            result=review,
                            candidate=_merge_candidate(db, candidate_id),
                            task_acceptance_commands=list(task.acceptance_commands),
                        )
                        workflow_store.complete_activity(
                            activity_id=review_activity_id,
                            status=ActivityStatus.FAILED,
                            output_refs={
                                "candidate_id": candidate_id,
                                "review_status": review_status,
                                "review_mode": review_mode,
                                "review_result": _artifact_ref(run_dir, review_result_path),
                                "classification": review_classification.to_dict(),
                            },
                            failure_class=review_classification.failure_class,
                        )
                        needs_context_escalated = True
                        review_mode = "full_tree"
                        journal.record(
                            "agentrunway.review_escalated",
                            build_event_payload(
                                run_id,
                                "review",
                                "partial",
                                "review escalated to full tree",
                                task_id=task.task_id,
                                worker_id=candidate["worker_id"],
                                reason="needs_context",
                                review_mode=review_mode,
                            ),
                        )
                        continue
                    if review_status == "approved":
                        workflow_store.complete_activity(
                            activity_id=review_activity_id,
                            status=ActivityStatus.COMPLETED,
                            output_refs={
                                "candidate_id": candidate_id,
                                "review_status": review_status,
                                "review_mode": review_mode,
                                "review_result": _artifact_ref(run_dir, review_result_path),
                            },
                            failure_class=None,
                        )
                    break
                if review_status != "approved":
                    candidate_snapshot = _merge_candidate(db, candidate_id)
                    review_classification = review_classification or classify_gate_failure(
                        gate="review",
                        status=review_status,
                        result=review,
                        candidate=candidate_snapshot,
                        task_acceptance_commands=list(task.acceptance_commands),
                    )
                    decision = gate_retry_decision(
                        task=task,
                        gate="review",
                        status=review_status,
                        result=review,
                        candidate=candidate_snapshot,
                        previous_retries=review_retries,
                    )
                    decision = _decision_for_classification(
                        gate="review",
                        classification_failure_class=review_classification.failure_class,
                        policy_decision=decision,
                    )
                    workflow_store.complete_activity(
                        activity_id=review_activity_id,
                        status=_gate_activity_status(
                            failure_class=review_classification.failure_class,
                            decision=decision,
                        ),
                        output_refs={
                            "candidate_id": candidate_id,
                            "review_status": review_status,
                            "review_mode": review_mode,
                            "review_result": _artifact_ref(run_dir, review_result_path),
                            "classification": review_classification.to_dict(),
                        },
                        failure_class=review_classification.failure_class,
                    )
                    _gate_decision_packet(
                        store=workflow_store,
                        run_id=run_id,
                        task_id=task.task_id,
                        gate="review",
                        attempt=review_attempt,
                        failure_class=review_classification.failure_class,
                        summary=review_classification.summary,
                        payload={
                            "gate": "review",
                            "status": review_status,
                            "result": review,
                            "candidate": {
                                "id": candidate_snapshot["id"],
                                "worker_id": candidate_snapshot["worker_id"],
                                "changed_files": candidate_snapshot["changed_files"],
                                "commits": candidate_snapshot["commits"],
                            },
                            "next_action": review_classification.next_action,
                            "policy_reason": decision.reason,
                        },
                    )
                    record_quality_decision(
                        journal,
                        run_id=run_id,
                        task_id=task.task_id,
                        decision=decision.action,
                        reason=decision.reason,
                        outcome=decision.outcome,
                        diagnosis_status=None,
                    )
                    db.set_merge_candidate_status(
                        candidate_id,
                        "changes_requested" if review_status == "changes_requested" else "review_rejected",
                    )
                    if decision.action == "retry":
                        review_retries += 1
                        implementer_context = _retry_context(decision.reason, review, _merge_candidate(db, candidate_id))
                        _record_gate_retry(
                            journal,
                            run_id=run_id,
                            task_id=task.task_id,
                            reason=decision.reason,
                            next_attempt=implementer_attempt + 1,
                        )
                        continue
                    db.set_task_status(task.task_id, "blocked")
                    _record_run_blocked(journal, run_id=run_id, task_id=task.task_id, reason=decision.reason)
                    break
                db.set_task_status(task.task_id, "verifying")
                journal.record(
                    "agentrunway.verification_dispatched",
                    build_event_payload(run_id, "verification", "success", "verification dispatched", task_id=task.task_id),
                )
                _, verification_attempt = next_worker_id(db=db, task_id=task.task_id, role="verifier")
                verification_worker_id = f"{task.task_id}-verifier-{verification_attempt:03d}"
                verification_activity_id = f"{task.task_id}.verification.{verification_attempt:03d}"
                verification_result_path = (
                    run_dir / "artifacts" / task.task_id / verification_worker_id / "verification_result.json"
                )
                workflow_store.start_activity(
                    run_id=run_id,
                    activity_id=verification_activity_id,
                    idempotency_key=f"{run_id}:{task.task_id}:verification:{verification_attempt:03d}",
                    task_id=task.task_id,
                    activity_type="verification",
                    input_refs={
                        "candidate_id": candidate_id,
                        "worker_id": candidate["worker_id"],
                        "review_status": review_status,
                    },
                )
                verification = run_verifier_attempt(
                    db=db,
                    run_id=run_id,
                    git=git,
                    worktree_root=worktree_root,
                    run_dir=run_dir,
                    task=task,
                    adapter=adapter,
                    runtime=runtime,
                    model=model,
                    reasoning_effort=reasoning_effort,
                    commits=tuple(candidate["commits"]),
                    changed_files=tuple(candidate["changed_files"]),
                    review_status=review_status,
                    attempt=verification_attempt,
                    timeout_seconds=600,
                )
                verification_status = str(verification["status"])
                journal.record(
                    "agentrunway.verification_result",
                    build_event_payload(
                        run_id,
                        "verification",
                        "success" if verification_status == "passed" else "partial",
                        "verification result",
                        task_id=task.task_id,
                        status=verification_status,
                    ),
                )
                if verification_status == "passed":
                    workflow_store.complete_activity(
                        activity_id=verification_activity_id,
                        status=ActivityStatus.COMPLETED,
                        output_refs={
                            "candidate_id": candidate_id,
                            "verification_status": verification_status,
                            "verification_result": _artifact_ref(run_dir, verification_result_path),
                        },
                        failure_class=None,
                    )
                    db.set_merge_candidate_status(candidate_id, "merge_ready")
                    db.set_task_status(task.task_id, "merge_ready")
                    journal.record(
                        "agentrunway.merge_ready",
                        build_event_payload(run_id, "merge", "success", "merge ready", task_id=task.task_id, candidate_id=candidate_id),
                    )
                    merge_ready_candidate_ids.append(candidate_id)
                    if len(merge_ready_candidate_ids) >= target_candidate_count:
                        break
                    review_retries = 0
                    verification_retries = 0
                    implementer_context = None
                    continue
                candidate_snapshot = _merge_candidate(db, candidate_id)
                verification_classification = classify_gate_failure(
                    gate="verification",
                    status=verification_status,
                    result=verification,
                    candidate=candidate_snapshot,
                    task_acceptance_commands=list(task.acceptance_commands),
                )
                decision = gate_retry_decision(
                    task=task,
                    gate="verification",
                    status=verification_status,
                    result=verification,
                    candidate=candidate_snapshot,
                    previous_retries=verification_retries,
                )
                decision = _decision_for_classification(
                    gate="verification",
                    classification_failure_class=verification_classification.failure_class,
                    policy_decision=decision,
                )
                workflow_store.complete_activity(
                    activity_id=verification_activity_id,
                    status=_gate_activity_status(
                        failure_class=verification_classification.failure_class,
                        decision=decision,
                    ),
                    output_refs={
                        "candidate_id": candidate_id,
                        "verification_status": verification_status,
                        "verification_result": _artifact_ref(run_dir, verification_result_path),
                        "classification": verification_classification.to_dict(),
                    },
                    failure_class=verification_classification.failure_class,
                )
                _gate_decision_packet(
                    store=workflow_store,
                    run_id=run_id,
                    task_id=task.task_id,
                    gate="verification",
                    attempt=verification_attempt,
                    failure_class=verification_classification.failure_class,
                    summary=verification_classification.summary,
                    payload={
                        "gate": "verification",
                        "status": verification_status,
                        "result": verification,
                        "candidate": {
                            "id": candidate_snapshot["id"],
                            "worker_id": candidate_snapshot["worker_id"],
                            "changed_files": candidate_snapshot["changed_files"],
                            "commits": candidate_snapshot["commits"],
                        },
                        "next_action": verification_classification.next_action,
                        "policy_reason": decision.reason,
                    },
                )
                record_quality_decision(
                    journal,
                    run_id=run_id,
                    task_id=task.task_id,
                    decision=decision.action,
                    reason=decision.reason,
                    outcome=decision.outcome,
                    diagnosis_status=None,
                )
                if verification_status == "failed":
                    db.set_merge_candidate_status(candidate_id, "verification_failed")
                else:
                    db.set_merge_candidate_status(candidate_id, "verification_blocked")
                if decision.action == "retry":
                    verification_retries += 1
                    implementer_context = _retry_context(decision.reason, verification, _merge_candidate(db, candidate_id))
                    _record_gate_retry(
                        journal,
                        run_id=run_id,
                        task_id=task.task_id,
                        reason=decision.reason,
                        next_attempt=implementer_attempt + 1,
                    )
                    continue
                db.set_task_status(task.task_id, "blocked")
                _record_run_blocked(journal, run_id=run_id, task_id=task.task_id, reason=decision.reason)
                break
            ready_candidates = [
                candidate
                for candidate in db.list_merge_candidates()
                if candidate["task_id"] == task.task_id and candidate["status"] == "merge_ready"
            ]
            if ready_candidates:
                selection = select_candidate([_candidate_for_ranking(candidate) for candidate in ready_candidates])
                record_candidate_ranked(
                    journal,
                    run_id=run_id,
                    task_id=task.task_id,
                    selected_candidate_id=selection.selected_candidate_id,
                    scores=[score.to_dict() for score in selection.scores],
                )
                db.set_task_status(task.task_id, "merge_ready")
                for candidate in ready_candidates:
                    if int(candidate["id"]) != selection.selected_candidate_id:
                        archive_candidate_evidence(run_dir=run_dir, db=db, candidate=candidate)
                        db.set_merge_candidate_status(int(candidate["id"]), "not_selected")
                        db.set_worker_state(str(candidate["worker_id"]), "not_selected")
                        worker = db.get_worker(str(candidate["worker_id"]))
                        db.set_worktree_lifecycle(str(worker["worktree_path"]), "evidence_archived")
                selected_candidate = next(
                    candidate
                    for candidate in ready_candidates
                    if int(candidate["id"]) == selection.selected_candidate_id
                )
                merge_candidate = MergeCandidate(
                    task_id=selected_candidate["task_id"],
                    worker_id=selected_candidate["worker_id"],
                    commits=tuple(selected_candidate["commits"]),
                    changed_files=tuple(selected_candidate["changed_files"]),
                )
                try:
                    integration_manager.merge_selected_candidate(
                        candidate_id=selection.selected_candidate_id,
                        candidate=merge_candidate,
                    )
                except MergeConflictError as exc:
                    db.set_task_status(selected_candidate["task_id"], "blocked")
                    journal.record(
                        "agentrunway.merge_conflict",
                        build_event_payload(
                            run_id,
                            "merge",
                            "partial",
                            "merge conflict",
                            task_id=selected_candidate["task_id"],
                            worker_id=selected_candidate["worker_id"],
                            candidate_id=selection.selected_candidate_id,
                            error=str(exc),
                        ),
                    )
                    _record_run_blocked(
                        journal,
                        run_id=run_id,
                        task_id=str(selected_candidate["task_id"]),
                        reason="merge_conflict",
                    )
                else:
                    worker = db.get_worker(str(selected_candidate["worker_id"]))
                    db.set_worktree_lifecycle(
                        str(worker["worktree_path"]),
                        lifecycle_for_worker(role="implementer", state="merged"),
                    )
                    db.set_task_status(selected_candidate["task_id"], "merged")
    write_artifact_graph(run_dir=run_dir, db=db)
    tasks_snapshot = db.list_tasks()
    blocked = any(str(task.get("status")) == "blocked" for task in tasks_snapshot)
    final_status = "blocked" if blocked else "finished"
    db.set_run_status(run_id, final_status)
    journal.record(
        "agentrunway.run_finished",
        build_event_payload(
            run_id,
            "run",
            "failed" if blocked else "success",
            "run finished",
            blocked_tasks=[task["task_id"] for task in tasks_snapshot if str(task.get("status")) == "blocked"],
        ),
    )
    if agentlens_emitter is not None:
        agentlens_emitter.close(outcome="failed" if blocked else "success", summary="run finished")
    run_json.update({"status": final_status, "main_worktree": str(main_worktree), "tasks": tasks_snapshot})
    _write_run_json(run_dir, run_json)
    return run_json


def _missing(run_id: str) -> dict[str, Any]:
    return {"run_id": run_id, "status": "missing"}


def _early_failure_payload(data: dict[str, Any], run_id: str) -> dict[str, Any] | None:
    status_value = str(data.get("status") or "")
    if status_value not in {"plan_lint_failed", "preflight_failed"}:
        return None
    payload = {
        "run_id": data.get("run_id") or run_id,
        "status": status_value,
        "run_dir": data.get("run_dir"),
        "state_db": data.get("state_db"),
        "next_action": "fix plan lint errors" if status_value == "plan_lint_failed" else "fix preflight issues",
    }
    if "plan_lint" in data:
        payload["plan_lint"] = data["plan_lint"]
    if "preflight" in data:
        payload["preflight"] = data["preflight"]
    return payload


def status(run_id: str) -> dict[str, Any]:
    data = _load_run_json_or_reconstruct(run_id)
    if data is None:
        return _missing(run_id)
    from .diagnostics import diagnose_run
    from .status import next_operator_action

    state_db = data.get("state_db")
    if not state_db or not Path(str(state_db)).exists():
        early = _early_failure_payload(data, run_id)
        if early is not None:
            return early
        return {
            "run_id": data.get("run_id") or run_id,
            "status": "missing",
            "run_dir": data.get("run_dir"),
            "reconstructed_from": data.get("reconstructed_from", []),
            "recovery": data.get("recovery", "no_state_sqlite"),
            "next_action": "no recoverable state; inspect run_dir manually",
        }
    db = AgentRunwayDb.open(Path(str(state_db)))
    agentlens = db.agentlens_summary()
    diagnosis = diagnose_run(run_json=data, db=db).to_dict()
    payload = {
        "run_id": run_id,
        "status": data.get("status"),
        "run_dir": data.get("run_dir"),
        "agentlens": agentlens,
        "diagnosis": diagnosis,
        "next_action": diagnosis.get("next_action") or next_operator_action(
            {**data, "diagnosis": diagnosis}, agentlens
        ),
    }
    if "reconstructed_from" in data:
        payload["reconstructed_from"] = data["reconstructed_from"]
    if "recovery" in data:
        payload["recovery"] = data["recovery"]
    return payload


def inspect(run_id: str) -> dict[str, Any]:
    data = _load_run_json_or_reconstruct(run_id)
    if data is None:
        return _missing(run_id)
    from .status import build_inspect_payload

    state_db = data.get("state_db")
    if not state_db or not Path(str(state_db)).exists():
        early = _early_failure_payload(data, run_id)
        if early is not None:
            return early
        return {
            "run_id": data.get("run_id") or run_id,
            "status": "missing",
            "run_dir": data.get("run_dir"),
            "reconstructed_from": data.get("reconstructed_from", []),
            "recovery": data.get("recovery", "no_state_sqlite"),
            "next_action": "no recoverable state; inspect run_dir manually",
        }
    db = AgentRunwayDb.open(Path(str(state_db)))
    payload = build_inspect_payload(run_json=data, db=db)
    if "reconstructed_from" in data:
        payload["reconstructed_from"] = data["reconstructed_from"]
    if "recovery" in data:
        payload["recovery"] = data["recovery"]
    return payload


def summarize(run_id: str) -> dict[str, Any]:
    data = _load_run_json_or_reconstruct(run_id)
    if data is None:
        return _missing(run_id)
    state_db = data.get("state_db")
    if not state_db or not Path(str(state_db)).exists():
        early = _early_failure_payload(data, run_id)
        if early is not None:
            return early
        return {
            "run_id": data.get("run_id") or run_id,
            "status": "missing",
            "run_dir": data.get("run_dir"),
            "reconstructed_from": data.get("reconstructed_from", []),
            "recovery": data.get("recovery", "no_state_sqlite"),
            "next_action": "no recoverable state; inspect run_dir manually",
        }
    from .run_summary import build_run_summary

    db = AgentRunwayDb.open(Path(str(state_db)))
    return build_run_summary(run_json=data, db=db)


def events(run_id: str, event_type: str | None = None) -> dict[str, Any]:
    data = _load_run_json(run_id)
    if data is None:
        return _missing(run_id)
    db = AgentRunwayDb.open(Path(data["state_db"]))
    rows = db.list_events()
    if event_type:
        rows = [row for row in rows if row["event_type"] == event_type]
    return {"run_id": run_id, "events": rows, "agentlens": db.agentlens_summary()}


def resume(run_id: str, *, dry_run: bool = False) -> dict[str, Any]:
    data = _load_run_json(run_id)
    if data is None:
        return _missing(run_id)
    state_db = data.get("state_db")
    if not state_db or not Path(str(state_db)).exists():
        early = _early_failure_payload(data, run_id)
        if early is not None:
            return early
        return {
            "run_id": data.get("run_id") or run_id,
            "status": "missing",
            "run_dir": data.get("run_dir"),
            "recovery": data.get("recovery", "no_state_sqlite"),
        }
    db = AgentRunwayDb.open(Path(data["state_db"]))
    plan = plan_reconciliation(run_id=run_id, run_dir=Path(data["run_dir"]), db=db)
    activity_resume = plan_activity_resume(run_id=run_id, db=db)
    if dry_run:
        return {**plan, "activity_resume": activity_resume}
    apply_reconciliation_plan(db=db, plan=plan)
    return {
        "run_id": run_id,
        "status": data.get("status"),
        "run_dir": data.get("run_dir"),
        "reconciliation": plan,
        "activity_resume": activity_resume,
    }


def cancel(run_id: str) -> dict[str, Any]:
    data = _load_run_json(run_id)
    if data is None:
        return _missing(run_id)
    data["status"] = "cancelled"
    _write_run_json(Path(data["run_dir"]), data)
    return {"run_id": run_id, "status": "cancelled"}


def apply(run_id: str, strategy: str = "cherry-pick") -> dict[str, Any]:
    data = _load_run_json(run_id)
    if data is None:
        return _missing(run_id)
    db = AgentRunwayDb.open(Path(data["state_db"]))
    commits: list[str] = []
    for candidate in db.list_merge_candidates():
        if candidate["status"] == "merged":
            commits.extend(candidate["commits"])
    already_applied = tuple(row["commit_sha"] for row in db.list_applied_commits(run_id))
    try:
        applied = apply_commits_to_source(
            Path(data["repo_root"]),
            tuple(commits),
            strategy=strategy,
            already_applied=already_applied,
        )
    except ApplyError as exc:
        return {
            "run_id": run_id,
            "status": data.get("status"),
            "applied": False,
            "commits": [],
            "already_applied": list(already_applied),
            "error": str(exc),
            "conflict_commit": exc.commit,
        }
    for commit in applied:
        db.record_applied_commit(run_id=run_id, commit_sha=commit, strategy=strategy)
    return {
        "run_id": run_id,
        "status": data.get("status"),
        "applied": True,
        "commits": applied,
        "already_applied": list(already_applied),
    }


def clean(older_than: str, *, successful: bool, dry_run: bool = True) -> dict[str, Any]:
    return clean_retention(agentrunway_home(), older_than=older_than, successful=successful, dry_run=dry_run)
