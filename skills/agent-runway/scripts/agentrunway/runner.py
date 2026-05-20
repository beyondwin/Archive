from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .activity_runner import ActivityRunner
from .adapters.claude import ClaudeAdapter
from .adapters.codex import CodexAdapter
from .adapters.local import LocalAdapter
from .agentlens import create_agentlens_emitter
from .apply import ApplyError, apply_commits_to_source
from .artifact_graph import write_artifact_graph
from .artifacts import ArtifactStore
from .candidate_selection import select_candidate
from .config import BuiltinProfiles, ModelProfile, load_effective_config
from .contract import build_run_contract, canonicalize_task_spec_refs, write_contract
from .db import AgentRunwayDb
from .decision_events import record_candidate_ranked, record_quality_decision
from .durable_resume import plan_activity_resume
from .evidence import EvidenceDecision, validate_merge_evidence
from .events import EventJournal, build_event_payload
from .failure_classifier import classify_gate_failure, classify_plan_failure
from .gate_cache import GateCacheKey, gate_cache_digest, stable_hash
from .gate_runner import GateRunner
from .git_ops import Git, assert_clean_source
from .integration_manager import IntegrationManager
from .merge_queue import MergeCandidate, MergeConflictError
from .packetizer import build_task_packet, materialize_prompt, materialize_worker_prompt, packet_to_json
from .plan_parser import canonical_hash, parse_plan, parse_spec_manifest
from .plan_lint import lint_plan
from .preflight import run_preflight
from .quality_policy import PolicyDecision, candidate_count_for_task
from .reconciliation import apply_reconciliation_plan, plan_reconciliation
from .retention import clean_retention
from .scheduler import schedule_waves
from .supervisor import collect_implementer_attempt, next_worker_id, run_reviewer_attempt, run_verifier_attempt, start_worker_attempt
from .workflow_store import ActivityStatus, WorkflowStore
from .worktrees import create_main_worktree, next_available_run_id, workspace_id
from .worktree_lifecycle import archive_candidate_evidence, lifecycle_for_worker, reviewer_mode_for_task


DEFAULT_MAX_PARALLEL_IMPLEMENTERS = 4


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
    from .spec_refs import SpecRefResolver

    resolver = SpecRefResolver.from_spec(spec)
    manifest = parse_spec_manifest(spec)
    refs = task_refs or tuple(manifest["section_order"][:1])
    slices: list[dict[str, str]] = []
    for ref in refs:
        resolution = resolver.resolve_one(ref)
        canonical_ref = resolution.canonical_ref or ref
        slices.append(
            {
                "id": canonical_ref,
                "input_ref": resolution.input_ref,
                "title": resolution.title or canonical_ref,
                "text": resolution.text,
            }
        )
    return slices


def _write_run_json(run_dir: Path, payload: dict[str, Any]) -> None:
    (run_dir / "run.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _write_early_run_json(run_dir: Path, payload: dict[str, Any]) -> bool:
    try:
        run_dir.mkdir(parents=True, exist_ok=True)
        _write_run_json(run_dir, payload)
    except OSError:
        return False
    return True


def _safe_base_commit(repo: Path, base_ref: str) -> str:
    try:
        return Git(repo).rev_parse(base_ref)
    except Exception:
        return "unknown"


def _persist_early_failure(
    *,
    run_id: str,
    workspace_id: str,
    repo: Path,
    plan: Path,
    spec: Path | None,
    args: Any,
    cfg: Any,
    run_dir: Path,
    status: str,
    event_type: str,
    failure_class: str,
    summary: str,
    decision_payload: dict[str, Any],
    details: dict[str, Any],
) -> dict[str, Any]:
    state_db = run_dir / "state.sqlite"
    events_jsonl = run_dir / "events.jsonl"
    decision_packet_path = run_dir / "artifacts" / "decision_packet.json"
    decision_kind = "plan_lint" if status == "plan_lint_failed" else "preflight"
    decision_packet = {
        "decision_id": f"{run_id}.{decision_kind}.decision",
        "failure_class": failure_class,
        "summary": summary,
        "payload": decision_payload,
    }
    payload: dict[str, Any] = {
        "run_id": run_id,
        "workspace_id": workspace_id,
        "status": status,
        "run_dir": str(run_dir),
        "state_db": str(state_db),
        "events_jsonl": str(events_jsonl),
        "artifacts": {"decision_packet": str(decision_packet_path)},
        "failure_class": failure_class,
        "decision_packet": decision_packet,
        **details,
    }
    try:
        run_dir.mkdir(parents=True, exist_ok=True)
        decision_packet_path.parent.mkdir(parents=True, exist_ok=True)
        db = AgentRunwayDb.open(state_db)
        db.create_run(
            run_id=run_id,
            workspace_id=workspace_id,
            repo_root=str(repo),
            plan_path=str(plan),
            spec_path=str(spec) if spec else None,
            plan_hash=canonical_hash(plan),
            spec_hash=canonical_hash(spec) if spec else None,
            base_commit_sha=_safe_base_commit(repo, str(args.base_ref)),
            model_profile=cfg.default_profile,
            allowed_dirty=args.allow_dirty_source,
            apply_to_source=args.apply_to_source,
        )
        db.set_run_status(run_id, status)
        db.insert_decision_packet(
            run_id=run_id,
            decision_id=str(decision_packet["decision_id"]),
            task_id=None,
            failure_class=failure_class,
            summary=summary,
            payload=decision_payload,
        )
        decision_packet_path.write_text(
            json.dumps(decision_packet, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        journal = EventJournal(db=db, run_dir=run_dir, agentlens_emitter=None)
        journal.record("agentrunway.run_started", build_event_payload(run_id, "run", "success", "run started"))
        _record_agentlens_sink_unavailable(journal, run_id=run_id)
        journal.record(event_type, build_event_payload(run_id, decision_kind, "failed", summary, failure_class=failure_class))
        journal.record(
            "agentrunway.run_blocked",
            build_event_payload(run_id, "run", "blocked", summary, failure_class=failure_class),
        )
        _write_run_json(run_dir, payload)
        payload["state_persisted"] = True
    except Exception as exc:
        payload.update(
            {
                "state_db": None,
                "events_jsonl": None,
                "artifacts": {"decision_packet": None},
                "state_persisted": False,
                "recovery": "early_failure_state_unavailable",
                "state_error": str(exc),
            }
        )
        payload["state_persisted"] = _write_early_run_json(run_dir, payload)
    return payload


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


def _candidate_worktree(db: AgentRunwayDb, candidate: dict[str, Any]) -> Path:
    worker = db.get_worker(str(candidate["worker_id"]))
    return Path(str(worker["worktree_path"]))


def _task_packet_hash(db: AgentRunwayDb, task_id: str) -> str:
    row = db.conn.execute("SELECT packet_hash FROM task_packets WHERE task_id=?", (task_id,)).fetchone()
    return str(row["packet_hash"]) if row is not None else ""


def _tracked_git_status(worktree: Path) -> str:
    return Git(worktree).run("status", "--porcelain", "--untracked-files=no", check=False).stdout


def _register_local_gate_worker(
    *,
    db: AgentRunwayDb,
    task: Any,
    worker_id: str,
    attempt: int,
    output_path: Path,
    result: dict[str, Any],
    handle_json: dict[str, Any],
) -> dict[str, Any]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    db.create_worker_attempt(
        worker_id=worker_id,
        task_id=task.task_id,
        role="verifier",
        runtime="local",
        model="local",
        reasoning_effort="n/a",
        attempt=attempt,
        worktree_path=None,
        branch=None,
        state="running",
        handle_json=handle_json,
    )
    db.mark_worker_started(worker_id)
    db.mark_worker_ended(worker_id, "result_collected")
    db.set_worker_state(worker_id, "validated")
    return result


def _local_first_verification(
    *,
    db: AgentRunwayDb,
    task: Any,
    candidate: dict[str, Any],
    diff: str,
    run_dir: Path,
    worker_id: str,
    attempt: int,
    output_path: Path,
) -> dict[str, Any] | None:
    if task.risk == "high" or not task.acceptance_commands:
        return None
    candidate_tree = _candidate_worktree(db, candidate)
    candidate_commit = str(candidate["commits"][-1]) if candidate.get("commits") else ""
    if not candidate_commit:
        return None
    cache_key = gate_cache_digest(
        GateCacheKey(
            gate="verification",
            base_commit=candidate_commit,
            task_packet_hash=_task_packet_hash(db, task.task_id),
            diff_hash=stable_hash(diff),
            command_hash=stable_hash(list(task.acceptance_commands)),
            tool_version=f"python:{sys.version_info.major}.{sys.version_info.minor}",
        )
    )
    cached = db.get_gate_cache(gate="verification", cache_key=cache_key)
    if cached is not None:
        result = dict(cached["result"])
        result["worker_id"] = worker_id
        result["task_id"] = task.task_id
        method_audit = dict(result.get("method_audit") or {})
        method_audit["gate_cache_hit"] = True
        result["method_audit"] = method_audit
        return _register_local_gate_worker(
            db=db,
            task=task,
            worker_id=worker_id,
            attempt=attempt,
            output_path=output_path,
            result=result,
            handle_json={"local_gate": {"source": "cache", "cache_key": cache_key, "candidate_worker_id": candidate["worker_id"]}},
        )

    checks: list[dict[str, Any]] = []
    verify_tree = run_dir / "verify" / task.task_id / worker_id
    verify_tree.parent.mkdir(parents=True, exist_ok=True)
    source_git = Git(candidate_tree)
    add_result = source_git.run("worktree", "add", "--detach", str(verify_tree), candidate_commit, check=False)
    if add_result.returncode != 0:
        return None
    try:
        if _tracked_git_status(verify_tree):
            return None
        for command in task.acceptance_commands:
            try:
                completed = subprocess.run(
                    command,
                    cwd=verify_tree,
                    shell=True,
                    text=True,
                    capture_output=True,
                    timeout=600,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                checks.append(
                    {
                        "command": command,
                        "status": "failed",
                        "returncode": None,
                        "stdout": (exc.stdout or "")[:4000],
                        "stderr": (exc.stderr or "timeout")[:4000],
                        "source": "local",
                    }
                )
                return None
            tracked_status = _tracked_git_status(verify_tree)
            check = {
                "command": command,
                "status": "passed" if completed.returncode == 0 and not tracked_status else "failed",
                "returncode": completed.returncode,
                "stdout": completed.stdout[:4000],
                "stderr": completed.stderr[:4000],
                "source": "local",
                "tracked_status": tracked_status[:4000],
            }
            checks.append(check)
            if completed.returncode != 0 or tracked_status:
                return None
    finally:
        source_git.run("worktree", "remove", "--force", str(verify_tree), check=False)

    result = {
        "schema": "agentrunway.verification_result.v1",
        "worker_id": worker_id,
        "task_id": task.task_id,
        "status": "passed",
        "checks": checks,
        "method_audit": {"superpowers_used": True, "local_first": True, "gate_cache_hit": False},
    }
    db.put_gate_cache(
        gate="verification",
        cache_key=cache_key,
        result=result,
        metadata={"source": "local", "candidate_worker_id": str(candidate["worker_id"])},
    )
    return _register_local_gate_worker(
        db=db,
        task=task,
        worker_id=worker_id,
        attempt=attempt,
        output_path=output_path,
        result=result,
        handle_json={"local_gate": {"source": "local", "cache_key": cache_key, "candidate_worker_id": candidate["worker_id"]}},
    )


def _start_implementer_batch(
    *,
    db: AgentRunwayDb,
    journal: EventJournal,
    activity_runner: ActivityRunner,
    run_id: str,
    git: Git,
    worktree_root: Path,
    run_dir: Path,
    task: Any,
    packet: Any,
    packet_path: Path,
    adapter: Any,
    runtime: str,
    model: str,
    reasoning_effort: str,
    implementer_context: dict[str, object] | None,
    batch_size: int,
    checkpoint_id: str | None,
    run_json: dict[str, Any],
) -> list[dict[str, Any]]:
    started_implementers: list[dict[str, Any]] = []
    for _ in range(batch_size):
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
        activity_runner.start(
            activity_id=implement_activity_id,
            idempotency_key=f"{run_id}:{task.task_id}:implement:{implementer_attempt:03d}",
            task_id=task.task_id,
            activity_type="implement",
            input_refs={
                "packet": _artifact_ref(run_dir, packet_path),
                "prompt": _artifact_ref(run_dir, prompt_path),
                "checkpoint_id": checkpoint_id,
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
                spec_refs=list(task.spec_refs),
            ),
        )
        try:
            started = start_worker_attempt(
                db=db,
                run_id=run_id,
                git=git,
                worktree_root=worktree_root,
                run_dir=run_dir,
                task=task,
                packet_path=packet_path,
                prompt_path=prompt_path,
                output_path=output_path,
                adapter=adapter,
                runtime=runtime,
                model=model,
                reasoning_effort=reasoning_effort,
                role="implementer",
                base_ref=f"agentrunway/{run_id}/main",
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
            activity_runner.complete(
                activity_id=implement_activity_id,
                status=ActivityStatus.FAILED,
                output_refs={"error": str(exc), "worker_id": worker_id},
                failure_class="needs_infra_fix",
            )
            db.set_run_status(run_id, "failed")
            run_json.update(
                {
                    "status": "failed",
                    "tasks": db.list_tasks(),
                    "error": str(exc),
                }
            )
            _write_run_json(run_dir, run_json)
            _cancel_started_implementers(db=db, adapter=adapter, started_implementers=started_implementers)
            raise
        started_implementers.append(
            {
                "started": started,
                "worker_id": worker_id,
                "attempt": implementer_attempt,
                "output_path": output_path,
                "activity_id": implement_activity_id,
            }
        )
    return started_implementers


def _cancel_started_implementers(
    *,
    db: AgentRunwayDb,
    adapter: Any,
    started_implementers: list[dict[str, Any]],
    skip_worker_id: str | None = None,
) -> None:
    for started_info in started_implementers:
        worker_id = str(started_info["worker_id"])
        if skip_worker_id is not None and worker_id == skip_worker_id:
            continue
        started = started_info["started"]
        try:
            adapter.cancel(started.handle)
        except Exception:
            pass
        db.mark_worker_ended(worker_id, "cancelled")
        if started.worker_tree is not None:
            db.set_worktree_lifecycle(
                str(started.worker_tree),
                lifecycle_for_worker(role="implementer", state="cancelled"),
            )


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


def _record_agentlens_sink_unavailable(journal: EventJournal, *, run_id: str) -> None:
    journal.record(
        "agentrunway.agentlens_sink_unavailable",
        build_event_payload(
            run_id,
            "agentlens",
            "partial",
            "AgentLens sink unavailable; local journal is authoritative",
            evidence={"sink": "disabled", "local_journal": str(journal.events_path)},
        ),
    )


def _record_artifacts_ready(journal: EventJournal, *, run_id: str, run_dir: Path) -> None:
    coverage_path = run_dir / "coverage.json"
    coverage: dict[str, Any] = {}
    if coverage_path.exists():
        try:
            coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            coverage = {}
    artifact_paths = [
        run_dir / "contract.json",
        run_dir / "artifact_graph.json",
        coverage_path,
    ]
    journal.record(
        "agentrunway.artifacts_ready",
        build_event_payload(
            run_id,
            "artifacts",
            "success",
            "artifact graph and coverage ready",
            contract_path=str(run_dir / "contract.json"),
            artifact_graph_path=str(run_dir / "artifact_graph.json"),
            coverage_path=str(coverage_path),
            coverage=coverage,
            artifact_refs=[_artifact_ref(run_dir, path) for path in artifact_paths],
        ),
    )


def _record_merge_blocked(
    journal: EventJournal,
    *,
    run_id: str,
    task_id: str,
    candidate: dict[str, Any],
    decision: EvidenceDecision,
    spec_refs: list[str] | None = None,
) -> None:
    journal.record(
        "agentrunway.merge_blocked",
        build_event_payload(
            run_id,
            "merge",
            "partial",
            "merge blocked by missing evidence",
            task_id=task_id,
            worker_id=candidate.get("worker_id"),
            candidate_id=candidate.get("id"),
            spec_refs=spec_refs or [],
            evidence={"status": "blocked", "reasons": list(decision.reasons)},
            reasons=list(decision.reasons),
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


def _gate_activity_status(*, failure_class: str, decision: PolicyDecision, decision_packet_required: bool = False) -> ActivityStatus:
    if decision.action == "block" and (decision_packet_required or failure_class in _HUMAN_DECISION_FAILURE_CLASSES):
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
    required: bool = False,
) -> dict[str, Any] | None:
    if not required and failure_class not in _HUMAN_DECISION_FAILURE_CLASSES:
        return None
    return store.create_decision_packet(
        run_id=run_id,
        decision_id=f"{task_id}.{gate}.{attempt:03d}.decision",
        task_id=task_id,
        failure_class=failure_class,
        summary=summary,
        payload=payload,
    )


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
        return _persist_early_failure(
            run_id=run_id,
            workspace_id=wsid,
            repo=repo,
            plan=plan,
            spec=spec,
            args=args,
            cfg=cfg,
            run_dir=run_dir,
            status="plan_lint_failed",
            event_type="agentrunway.plan_lint_failed",
            failure_class=classification.failure_class,
            summary=classification.summary,
            decision_payload={
                "next_action": classification.next_action,
                "issues": lint.to_dict().get("errors", []),
                "plan_lint": lint.to_dict(),
            },
            details={"plan_lint": lint.to_dict()},
        )
    preflight = run_preflight(
        adapter_name=str(args.adapter),
        repo=repo,
        run_dir=run_dir,
        worktree_root=worktree_root,
    )
    if not preflight.ok:
        return _persist_early_failure(
            run_id=run_id,
            workspace_id=wsid,
            repo=repo,
            plan=plan,
            spec=spec,
            args=args,
            cfg=cfg,
            run_dir=run_dir,
            status="preflight_failed",
            event_type="agentrunway.preflight_failed",
            failure_class="preflight_failed",
            summary="preflight failed",
            decision_payload={
                "next_action": "fix preflight issues",
                "issues": preflight.to_dict().get("issues", []),
                "preflight": preflight.to_dict(),
            },
            details={"preflight": preflight.to_dict()},
        )
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
    raw_tasks = parse_plan(plan)
    original_spec_refs_by_task = {task.task_id: task.spec_refs for task in raw_tasks}
    tasks = canonicalize_task_spec_refs(raw_tasks, spec)
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
    if agentlens_emitter is None:
        _record_agentlens_sink_unavailable(journal, run_id=run_id)
    journal.record(
        "agentrunway.contract_created",
        build_event_payload(run_id, "contract", "success", "contract created", contract_path=str(contract_path)),
    )
    profile = cfg.profiles[cfg.default_profile]
    packet_paths: list[Path] = []
    packet_summary: list[dict[str, Any]] = []
    for task in tasks:
        db.upsert_task(task)
        packet = build_task_packet(
            run_id,
            task,
            _spec_slices(spec, original_spec_refs_by_task.get(task.task_id, task.spec_refs)) if spec else [],
            profile,
        )
        prompt_path = materialize_prompt(packet, run_dir / "prompts")
        packet_json = packet_to_json(packet)
        packet_path = run_dir / "packets" / f"{task.task_id}.json"
        packet_path.write_text(packet_json, encoding="utf-8")
        packet_paths.append(packet_path)
        packet_summary.append(
            {
                "task_id": task.task_id,
                "path": str(packet_path),
                "context_budget": dict(packet.context_budget),
                "spec_ref_count": len(packet.spec_refs),
                "allowed_write_glob_count": len(packet.allowed_write_globs),
            }
        )
        db.insert_packet(task.task_id, hashlib.sha256(packet_json.encode()).hexdigest(), str(prompt_path), packet_json)
    write_artifact_graph(run_dir=run_dir, db=db)
    _record_artifacts_ready(journal, run_id=run_id, run_dir=run_dir)
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
        "artifacts": {
            "contract": str(contract_path),
            "artifact_graph": str(run_dir / "artifact_graph.json"),
            "coverage": str(run_dir / "coverage.json"),
            "packets": [str(path) for path in packet_paths],
        },
        "packet_summary": packet_summary,
    }
    _write_run_json(run_dir, run_json)
    if args.planning_only:
        db.set_run_status(run_id, "planning_only")
        journal.record(
            "agentrunway.run_finished",
            build_event_payload(
                run_id,
                "run",
                "success",
                "planning-only run finished",
                status="planning_only",
                simulation=False,
            ),
        )
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
    activity_runner = ActivityRunner(store=workflow_store, run_id=run_id)
    gate_runner = GateRunner()
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
    max_parallel_implementers = max(
        1,
        min(DEFAULT_MAX_PARALLEL_IMPLEMENTERS, int(cfg.runtime_caps.get(runtime, DEFAULT_MAX_PARALLEL_IMPLEMENTERS))),
    )
    store = ArtifactStore(run_dir / "artifacts")
    from .checkpoint_scheduler import CheckpointScheduler
    from .durable_projection import durable_operator_next_action, read_durable_projection

    scheduler = CheckpointScheduler()
    tasks_by_id = {task.task_id: task for task in tasks}
    progressed = True
    while progressed:
        progressed = False
        projection = read_durable_projection(run_id=run_id, db=db)
        wave = scheduler.next_wave(projection=projection)
        if not wave:
            break
        prestarted_wave: dict[str, list[dict[str, Any]]] = {}
        if runtime != "local" and len(wave) > 1:
            prestarted_slots = 0
            for task_ref in wave:
                task = tasks_by_id[str(task_ref["task_id"])]
                if str(db.get_task(task.task_id).get("status")) in {"blocked", "failed", "merged"}:
                    continue
                batch_size = candidate_count_for_task(task)
                if prestarted_slots + batch_size > max_parallel_implementers:
                    break
                packet_path = run_dir / "packets" / f"{task.task_id}.json"
                packet_json = db.conn.execute("SELECT packet_json FROM task_packets WHERE task_id=?", (task.task_id,)).fetchone()[
                    "packet_json"
                ]
                packet_path.write_text(packet_json, encoding="utf-8")
                (run_dir / "artifacts" / task.task_id).mkdir(parents=True, exist_ok=True)
                packet = build_task_packet(
                    run_id,
                    task,
                    _spec_slices(spec, original_spec_refs_by_task.get(task.task_id, task.spec_refs)) if spec else [],
                    profile,
                )
                try:
                    prestarted_wave[task.task_id] = _start_implementer_batch(
                        db=db,
                        journal=journal,
                        activity_runner=activity_runner,
                        run_id=run_id,
                        git=git,
                        worktree_root=worktree_root,
                        run_dir=run_dir,
                        task=task,
                        packet=packet,
                        packet_path=packet_path,
                        adapter=adapter,
                        runtime=runtime,
                        model=model,
                        reasoning_effort=reasoning_effort,
                        implementer_context=None,
                        batch_size=batch_size,
                        checkpoint_id=(workflow_store.latest_checkpoint(run_id) or {}).get("checkpoint_id"),
                        run_json=run_json,
                    )
                except Exception:
                    for started_implementers in prestarted_wave.values():
                        _cancel_started_implementers(db=db, adapter=adapter, started_implementers=started_implementers)
                    raise
                prestarted_slots += batch_size
        for task_ref in wave:
            task = tasks_by_id[str(task_ref["task_id"])]
            if str(db.get_task(task.task_id).get("status")) in {"blocked", "failed", "merged"}:
                continue
            progressed = True
            packet_path = run_dir / "packets" / f"{task.task_id}.json"
            packet_json = db.conn.execute("SELECT packet_json FROM task_packets WHERE task_id=?", (task.task_id,)).fetchone()["packet_json"]
            packet_path.write_text(packet_json, encoding="utf-8")
            task_artifact_dir = run_dir / "artifacts" / task.task_id
            task_artifact_dir.mkdir(parents=True, exist_ok=True)
            if runtime == "local":
                local_activity_id = f"{task.task_id}.implement.001"
                activity_runner.start(
                    activity_id=local_activity_id,
                    idempotency_key=f"{run_id}:{task.task_id}:local:implement:001",
                    task_id=task.task_id,
                    activity_type="implement",
                    input_refs={
                        "packet": _artifact_ref(run_dir, packet_path),
                        "checkpoint_id": (workflow_store.latest_checkpoint(run_id) or {}).get("checkpoint_id"),
                    },
                )
                result = adapter.run(packet_path, task_artifact_dir)
                store.write_text(task.task_id, "worker_result.json", json.dumps(asdict(result), indent=2, sort_keys=True))
                if result.status == "simulated_success":
                    activity_runner.complete(
                        activity_id=local_activity_id,
                        status=ActivityStatus.COMPLETED,
                        output_refs={
                            "worker_result": _artifact_ref(run_dir, task_artifact_dir / "worker_result.json"),
                            "simulation": True,
                        },
                        failure_class=None,
                    )
                    db.set_task_status(task.task_id, "simulated_completed")
                    simulation_payload = build_event_payload(
                            run_id,
                            "simulation",
                            "success",
                            "local fake-success simulated task completion",
                            task_id=task.task_id,
                            worker_id=result.worker_id,
                            spec_refs=list(task.spec_refs),
                            simulation=True,
                            worker_status=result.status,
                    )
                    journal.record("agentrunway.simulation", simulation_payload)
                    journal.record("agentrunway.simulation_completed", simulation_payload)
                elif result.status == "success":
                    latest = workflow_store.latest_checkpoint(run_id)
                    checkpoint_id = f"cp-{len(workflow_store.list_checkpoints(run_id)):03d}"
                    checkpoint = workflow_store.create_checkpoint(
                        run_id=run_id,
                        checkpoint_id=checkpoint_id,
                        commit_sha=Git(main_worktree).rev_parse("HEAD"),
                        parent_checkpoint_id=str(latest["checkpoint_id"]) if latest else None,
                        merged_candidate_id=None,
                        reason=f"merged:{task.task_id}",
                    )
                    activity_runner.complete(
                        activity_id=local_activity_id,
                        status=ActivityStatus.COMPLETED,
                        output_refs={
                            "worker_result": _artifact_ref(run_dir, task_artifact_dir / "worker_result.json"),
                            "checkpoint_id": checkpoint_id,
                            "commit_sha": checkpoint["commit_sha"],
                        },
                        failure_class=None,
                    )
                    db.set_task_status(task.task_id, "merged")
                else:
                    activity_runner.complete(
                        activity_id=local_activity_id,
                        status=ActivityStatus.FAILED,
                        output_refs={"worker_result": _artifact_ref(run_dir, task_artifact_dir / "worker_result.json")},
                        failure_class="needs_infra_fix",
                    )
                    db.set_task_status(task.task_id, "blocked")
                    _record_run_blocked(journal, run_id=run_id, task_id=task.task_id, reason="local_worker_failed")
            else:
                packet = build_task_packet(
                    run_id,
                    task,
                    _spec_slices(spec, original_spec_refs_by_task.get(task.task_id, task.spec_refs)) if spec else [],
                    profile,
                )
                target_candidate_count = candidate_count_for_task(task)
                merge_ready_candidate_ids: list[int] = []
                candidate_evidence_by_id: dict[int, dict[str, Any]] = {}
                review_retries = 0
                verification_retries = 0
                implementer_context: dict[str, object] | None = None
                prestarted_for_task = prestarted_wave.pop(task.task_id, [])
                while len(merge_ready_candidate_ids) < target_candidate_count:
                    if str(db.get_task(task.task_id).get("status")) in {"blocked", "failed"}:
                        break
                    batch_size = (
                        1
                        if implementer_context is not None
                        else min(max_parallel_implementers, max(1, target_candidate_count - len(merge_ready_candidate_ids)))
                    )
                    if implementer_context is None and prestarted_for_task:
                        started_implementers = prestarted_for_task
                        prestarted_for_task = []
                    else:
                        started_implementers = _start_implementer_batch(
                            db=db,
                            journal=journal,
                            activity_runner=activity_runner,
                            run_id=run_id,
                            git=git,
                            worktree_root=worktree_root,
                            run_dir=run_dir,
                            task=task,
                            packet=packet,
                            packet_path=packet_path,
                            adapter=adapter,
                            runtime=runtime,
                            model=model,
                            reasoning_effort=reasoning_effort,
                            implementer_context=implementer_context,
                            batch_size=batch_size,
                            checkpoint_id=(workflow_store.latest_checkpoint(run_id) or {}).get("checkpoint_id"),
                            run_json=run_json,
                        )
                    for started_info in started_implementers:
                        worker_id = str(started_info["worker_id"])
                        implementer_attempt = int(started_info["attempt"])
                        output_path = Path(started_info["output_path"])
                        implement_activity_id = str(started_info["activity_id"])
                        try:
                            candidate_id = collect_implementer_attempt(
                                db=db,
                                adapter=adapter,
                                task=task,
                                started=started_info["started"],
                                output_path=output_path,
                            )
                        except Exception as exc:
                            _cancel_started_implementers(
                                db=db,
                                adapter=adapter,
                                started_implementers=started_implementers,
                                skip_worker_id=worker_id,
                            )
                            for pending_started_implementers in prestarted_wave.values():
                                _cancel_started_implementers(
                                    db=db,
                                    adapter=adapter,
                                    started_implementers=pending_started_implementers,
                                )
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
                                    spec_refs=list(task.spec_refs),
                                    error=str(exc),
                                ),
                            )
                            activity_runner.complete(
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
                        activity_runner.complete(
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
                                spec_refs=list(task.spec_refs),
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
                                    spec_refs=list(task.spec_refs),
                                    review_mode=review_mode,
                                ),
                            )
                            _, review_attempt = next_worker_id(db=db, task_id=task.task_id, role="reviewer")
                            review_worker_id = f"{task.task_id}-reviewer-{review_attempt:03d}"
                            review_activity_id = f"{task.task_id}.review.{review_attempt:03d}"
                            review_result_path = run_dir / "artifacts" / task.task_id / review_worker_id / "review_result.json"
                            activity_runner.start(
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
                                    spec_refs=list(task.spec_refs),
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
                                activity_runner.complete(
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
                                activity_runner.complete(
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
                            gate_outcome = gate_runner.decide(
                                task=task,
                                gate="review",
                                status=review_status,
                                result=review,
                                candidate=candidate_snapshot,
                                previous_retries=review_retries,
                            )
                            decision = gate_outcome.policy
                            activity_runner.complete(
                                activity_id=review_activity_id,
                                status=_gate_activity_status(
                                    failure_class=review_classification.failure_class,
                                    decision=decision,
                                    decision_packet_required=gate_outcome.decision_packet_required,
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
                                required=gate_outcome.decision_packet_required,
                                payload=gate_runner.decision_packet_payload(
                                    gate="review",
                                    status=review_status,
                                    result=review,
                                    candidate=candidate_snapshot,
                                    next_action=review_classification.next_action,
                                    policy_reason=decision.reason,
                                ),
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
                            if gate_outcome.action in {"retry_implementer", "redispatch_from_latest_checkpoint"}:
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
                        activity_runner.start(
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
                        verification = _local_first_verification(
                            db=db,
                            task=task,
                            candidate=candidate,
                            diff=diff,
                            run_dir=run_dir,
                            worker_id=verification_worker_id,
                            attempt=verification_attempt,
                            output_path=verification_result_path,
                        )
                        if verification is None:
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
                                spec_refs=list(task.spec_refs),
                            ),
                        )
                        if verification_status == "passed":
                            activity_runner.complete(
                                activity_id=verification_activity_id,
                                status=ActivityStatus.COMPLETED,
                                output_refs={
                                    "candidate_id": candidate_id,
                                    "verification_status": verification_status,
                                    "verification_result": _artifact_ref(run_dir, verification_result_path),
                                },
                                failure_class=None,
                            )
                            candidate_evidence_by_id[candidate_id] = {
                                "review_status": review_status,
                                "verification_status": verification_status,
                                "verification_result": verification,
                            }
                            db.set_merge_candidate_status(candidate_id, "merge_ready")
                            db.set_task_status(task.task_id, "merge_ready")
                            journal.record(
                                "agentrunway.merge_ready",
                                build_event_payload(
                                    run_id,
                                    "merge",
                                    "success",
                                    "merge ready",
                                    task_id=task.task_id,
                                    candidate_id=candidate_id,
                                    spec_refs=list(task.spec_refs),
                                ),
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
                        gate_outcome = gate_runner.decide(
                            task=task,
                            gate="verification",
                            status=verification_status,
                            result=verification,
                            candidate=candidate_snapshot,
                            previous_retries=verification_retries,
                        )
                        decision = gate_outcome.policy
                        activity_runner.complete(
                            activity_id=verification_activity_id,
                            status=_gate_activity_status(
                                failure_class=verification_classification.failure_class,
                                decision=decision,
                                decision_packet_required=gate_outcome.decision_packet_required,
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
                            required=gate_outcome.decision_packet_required,
                            payload=gate_runner.decision_packet_payload(
                                gate="verification",
                                status=verification_status,
                                result=verification,
                                candidate=candidate_snapshot,
                                next_action=verification_classification.next_action,
                                policy_reason=decision.reason,
                            ),
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
                        if gate_outcome.action in {"retry_implementer", "redispatch_from_latest_checkpoint"}:
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
                    candidate_evidence = candidate_evidence_by_id.get(selection.selected_candidate_id, {})
                    evidence_decision = validate_merge_evidence(
                        task=task,
                        candidate=selected_candidate,
                        review_status=candidate_evidence.get("review_status"),
                        verification_status=candidate_evidence.get("verification_status"),
                        verification_result=candidate_evidence.get("verification_result"),
                    )
                    if not evidence_decision.allowed:
                        db.set_merge_candidate_status(
                            selection.selected_candidate_id,
                            "merge_blocked",
                            ",".join(evidence_decision.reasons),
                        )
                        db.set_task_status(selected_candidate["task_id"], "blocked")
                        _record_merge_blocked(
                            journal,
                            run_id=run_id,
                            task_id=str(selected_candidate["task_id"]),
                            candidate=selected_candidate,
                            decision=evidence_decision,
                            spec_refs=list(task.spec_refs),
                        )
                        _record_run_blocked(
                            journal,
                            run_id=run_id,
                            task_id=str(selected_candidate["task_id"]),
                            reason="merge_evidence_missing",
                        )
                        break
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
                        journal.record(
                            "agentrunway.merge_applied",
                            build_event_payload(
                                run_id,
                                "merge",
                                "success",
                                "merge applied",
                                task_id=selected_candidate["task_id"],
                                worker_id=selected_candidate["worker_id"],
                                candidate_id=selection.selected_candidate_id,
                                spec_refs=list(task.spec_refs),
                                evidence={
                                    "status": "merged",
                                    "commits": list(selected_candidate["commits"]),
                                    "changed_files": list(selected_candidate["changed_files"]),
                                },
                            ),
                        )
    write_artifact_graph(run_dir=run_dir, db=db)
    _record_artifacts_ready(journal, run_id=run_id, run_dir=run_dir)
    final_projection = read_durable_projection(run_id=run_id, db=db)
    tasks_snapshot = db.list_tasks()
    blocked = any(str(task.get("status")) == "blocked" for task in tasks_snapshot)
    unfinished = [
        task
        for task in tasks_snapshot
        if str(task.get("status")) not in {"merged", "blocked", "failed"}
    ]
    final_status = final_projection.projection_status
    if final_status == "running" and not final_projection.safe_wave and unfinished:
        final_status = "blocked"
    db.set_run_status(run_id, final_status)
    simulation = final_status == "simulated_finished"
    journal.record(
        "agentrunway.run_finished",
        build_event_payload(
            run_id,
            "run",
            "failed" if final_status == "blocked" else "success",
            "run finished",
            status=final_status,
            simulation=simulation,
            blocked_tasks=[task["task_id"] for task in tasks_snapshot if str(task.get("status")) == "blocked"],
        ),
    )
    if agentlens_emitter is not None:
        agentlens_emitter.close(outcome="failed" if final_status == "blocked" else "success", summary="run finished")
    run_json.update({"status": final_status, "main_worktree": str(main_worktree), "tasks": tasks_snapshot})
    if simulation:
        run_json.update(
            {
                "simulation": True,
                "next_operator_action": "run without --fake-success before applying artifacts",
                "next_action": "run without --fake-success before applying artifacts",
            }
        )
    _write_run_json(run_dir, run_json)
    return run_json


def _missing(run_id: str) -> dict[str, Any]:
    return {"run_id": run_id, "status": "missing"}


def _early_failure_payload(data: dict[str, Any], run_id: str) -> dict[str, Any] | None:
    status_value = str(data.get("status") or "")
    if status_value not in {"plan_lint_failed", "preflight_failed"}:
        return None
    failure_class = data.get("failure_class")
    if not failure_class and isinstance(data.get("decision_packet"), dict):
        failure_class = data["decision_packet"].get("failure_class")
    payload = {
        "run_id": data.get("run_id") or run_id,
        "status": status_value,
        "run_dir": data.get("run_dir"),
        "state_db": data.get("state_db"),
        "events_jsonl": data.get("events_jsonl"),
        "artifacts": data.get("artifacts", {}),
        "failure_class": failure_class,
        "decision_packet": data.get("decision_packet"),
        "next_action": "fix plan lint errors" if status_value == "plan_lint_failed" else "fix preflight issues",
    }
    if "plan_lint" in data:
        payload["plan_lint"] = data["plan_lint"]
    if "preflight" in data:
        payload["preflight"] = data["preflight"]
    payload["diagnosis"] = {
        "run_id": payload["run_id"],
        "status": status_value,
        "reason": failure_class or status_value,
        "next_action": payload["next_action"],
        "safe_actions": ["inspect", "events"],
        "manual_actions": [payload["next_action"]],
        "blocked_tasks": [],
        "conflict": None,
        "agentlens_health": {},
    }
    return payload


def status(run_id: str) -> dict[str, Any]:
    data = _load_run_json_or_reconstruct(run_id)
    if data is None:
        return _missing(run_id)
    from .diagnostics import diagnose_run
    from .status import SIMULATION_NEXT_OPERATOR_ACTION, next_operator_action

    early_data = _early_failure_payload(data, run_id)
    state_db = data.get("state_db")
    if not state_db or not Path(str(state_db)).exists():
        if early_data is not None:
            return early_data
        return {
            "run_id": data.get("run_id") or run_id,
            "status": "missing",
            "run_dir": data.get("run_dir"),
            "reconstructed_from": data.get("reconstructed_from", []),
            "recovery": data.get("recovery", "no_state_sqlite"),
            "next_action": "no recoverable state; inspect run_dir manually",
        }
    db = AgentRunwayDb.open(Path(str(state_db)))
    if early_data is not None:
        early_data["agentlens"] = db.agentlens_summary()
        early_data["diagnosis"]["agentlens_health"] = early_data["agentlens"]
        return early_data
    agentlens = db.agentlens_summary()
    diagnosis = diagnose_run(run_json=data, db=db).to_dict()
    payload = {
        "run_id": run_id,
        "status": data.get("status"),
        "simulation": data.get("simulation") is True or data.get("status") == "simulated_finished",
        "run_dir": data.get("run_dir"),
        "agentlens": agentlens,
        "diagnosis": diagnosis,
        "next_action": diagnosis.get("next_action") or next_operator_action(
            {**data, "diagnosis": diagnosis}, agentlens
        ),
    }
    if payload["simulation"]:
        payload["next_action"] = SIMULATION_NEXT_OPERATOR_ACTION
    payload["next_operator_action"] = payload["next_action"]
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

    early_data = _early_failure_payload(data, run_id)
    state_db = data.get("state_db")
    if not state_db or not Path(str(state_db)).exists():
        if early_data is not None:
            return early_data
        return {
            "run_id": data.get("run_id") or run_id,
            "status": "missing",
            "run_dir": data.get("run_dir"),
            "reconstructed_from": data.get("reconstructed_from", []),
            "recovery": data.get("recovery", "no_state_sqlite"),
            "next_action": "no recoverable state; inspect run_dir manually",
        }
    db = AgentRunwayDb.open(Path(str(state_db)))
    if early_data is not None:
        early_data["agentlens"] = db.agentlens_summary()
        early_data["events"] = db.list_events()
        early_data["diagnosis"]["agentlens_health"] = early_data["agentlens"]
        return early_data
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
    early_data = _early_failure_payload(data, run_id)
    state_db = data.get("state_db")
    if not state_db or not Path(str(state_db)).exists():
        if early_data is not None:
            return early_data
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
    if early_data is not None:
        early_data["agentlens"] = db.agentlens_summary()
        early_data["events"] = db.list_events()
        early_data["diagnosis"]["agentlens_health"] = early_data["agentlens"]
        return early_data
    return build_run_summary(run_json=data, db=db)


def events(run_id: str, event_type: str | None = None) -> dict[str, Any]:
    data = _load_run_json(run_id)
    if data is None:
        return _missing(run_id)
    state_db = data.get("state_db")
    if not state_db or not Path(str(state_db)).exists():
        early = _early_failure_payload(data, run_id)
        if early is not None:
            return {"run_id": run_id, "events": [], "agentlens": {}, "failure": early}
        return _missing(run_id)
    db = AgentRunwayDb.open(Path(str(state_db)))
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
    from .durable_projection import durable_operator_next_action, read_durable_projection
    from .resume_executor import ResumeExecutor
    from .resume_planner import ResumeAction, plan_resume_actions

    plan = plan_reconciliation(run_id=run_id, run_dir=Path(data["run_dir"]), db=db)
    activity_resume = plan_activity_resume(run_id=run_id, db=db)
    durable_projection = read_durable_projection(run_id=run_id, db=db).to_dict()
    resume_actions = plan_resume_actions(run_id=run_id, db=db)
    if durable_projection.get("next_automatic_action") == "classify_stale_activity":
        first_stale = (durable_projection.get("stale_activities") or [{}])[0]
        resume_actions = [
            *resume_actions,
            ResumeAction(
                action="classify_stale_activity",
                task_id=first_stale.get("task_id"),
                candidate_id=None,
                writes=True,
                reason="started_activity_exceeded_timeout",
            ),
        ]

    def resume_merge_handler(action: Any) -> dict[str, Any]:
        if action.task_id is None or action.candidate_id is None:
            raise RuntimeError("missing_merge_refs")
        main_worktree_value = data.get("main_worktree")
        if not main_worktree_value or not Path(str(main_worktree_value)).exists():
            raise RuntimeError("missing_main_worktree")
        candidate = _merge_candidate(db, int(action.candidate_id))
        if str(candidate["task_id"]) != action.task_id:
            raise RuntimeError("candidate_task_mismatch")
        task_row = db.get_task(action.task_id)
        evidence_decision = validate_merge_evidence(
            task_phase=str(task_row["phase"]),
            candidate=candidate,
        )
        if not evidence_decision.allowed:
            db.set_merge_candidate_status(int(action.candidate_id), "merge_blocked", ",".join(evidence_decision.reasons))
            db.set_task_status(action.task_id, "blocked")
            journal = EventJournal(db=db, run_dir=Path(str(data["run_dir"])), agentlens_emitter=None)
            _record_merge_blocked(
                journal,
                run_id=run_id,
                task_id=action.task_id,
                candidate=candidate,
                decision=evidence_decision,
                spec_refs=json.loads(task_row["spec_refs_json"]) if isinstance(task_row.get("spec_refs_json"), str) else [],
            )
            raise RuntimeError("merge_evidence_missing:" + ",".join(evidence_decision.reasons))
        manager = IntegrationManager(
            db=db,
            store=WorkflowStore(db),
            run_id=run_id,
            main_worktree=Path(str(main_worktree_value)),
        )
        checkpoint = manager.merge_selected_candidate(
            candidate_id=int(action.candidate_id),
            candidate=MergeCandidate(
                task_id=str(candidate["task_id"]),
                worker_id=str(candidate["worker_id"]),
                commits=tuple(candidate["commits"]),
                changed_files=tuple(candidate["changed_files"]),
            ),
        )
        db.set_task_status(action.task_id, "merged")
        EventJournal(db=db, run_dir=Path(str(data["run_dir"])), agentlens_emitter=None).record(
            "agentrunway.merge_applied",
            build_event_payload(
                run_id,
                "merge",
                "success",
                "merge applied",
                task_id=action.task_id,
                worker_id=candidate["worker_id"],
                candidate_id=int(action.candidate_id),
                spec_refs=json.loads(task_row["spec_refs_json"]) if isinstance(task_row.get("spec_refs_json"), str) else [],
                evidence={
                    "status": "merged",
                    "commits": list(candidate["commits"]),
                    "changed_files": list(candidate["changed_files"]),
                },
            ),
        )
        return {
            "candidate_id": int(action.candidate_id),
            "checkpoint_id": checkpoint["checkpoint_id"],
            "commit_sha": checkpoint["commit_sha"],
        }

    if dry_run:
        return {
            **plan,
            "activity_resume": activity_resume,
            "durable": durable_projection,
            "resume_actions": [action.__dict__ for action in resume_actions],
            "next_action": durable_operator_next_action(durable_projection, activity_resume.get("next_action")),
        }
    apply_reconciliation_plan(db=db, plan=plan)
    execution = ResumeExecutor(
        db=db,
        run_id=run_id,
        handlers={"schedule_merge": resume_merge_handler},
    ).execute(actions=resume_actions)
    write_artifact_graph(run_dir=Path(str(data["run_dir"])), db=db)
    tasks_snapshot = db.list_tasks()
    final_projection = read_durable_projection(run_id=run_id, db=db)
    if execution.get("blocked") is not None or any(str(task.get("status")) in {"blocked", "failed"} for task in tasks_snapshot):
        final_status = "blocked"
    elif (
        not final_projection.checkpoint_repair_tasks
        and all(str(task.get("status")) == "merged" for task in tasks_snapshot)
    ):
        final_status = "finished"
    else:
        final_status = str(data.get("status") or "running")
    db.set_run_status(run_id, final_status)
    data.update({"status": final_status, "tasks": tasks_snapshot})
    _write_run_json(Path(str(data["run_dir"])), data)
    return {
        "run_id": run_id,
        "status": final_status,
        "run_dir": data.get("run_dir"),
        "reconciliation": plan,
        "activity_resume": activity_resume,
        "resume_actions": [action.__dict__ for action in resume_actions],
        "execution": execution,
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
    if data.get("simulation") is True or data.get("status") == "simulated_finished":
        return {
            "run_id": run_id,
            "status": data.get("status"),
            "simulation": True,
            "applied": False,
            "commits": [],
            "already_applied": [],
            "error": "simulated_run_refused",
            "next_operator_action": "run without --fake-success before applying artifacts",
        }
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
