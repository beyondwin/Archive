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
from .apply import apply_commits_to_source
from .artifact_graph import write_artifact_graph
from .artifacts import ArtifactStore
from .config import BuiltinProfiles, ModelProfile, load_effective_config
from .contract import build_run_contract, write_contract
from .db import AgentRunwayDb
from .events import EventJournal, build_event_payload
from .git_ops import Git, assert_clean_source
from .merge_queue import MergeCandidate, MergeConflictError, apply_candidate
from .packetizer import build_task_packet, materialize_prompt, materialize_worker_prompt, packet_to_json
from .plan_parser import canonical_hash, parse_plan, parse_spec_manifest
from .reconciliation import apply_reconciliation_plan, plan_reconciliation
from .scheduler import schedule_waves
from .supervisor import run_implementer_attempt, run_reviewer_attempt, run_verifier_attempt
from .worktrees import create_main_worktree, next_available_run_id, workspace_id


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


def _load_run_json(run_id: str) -> dict[str, Any] | None:
    run_dir = _find_run_dir(run_id)
    if run_dir is None or not (run_dir / "run.json").exists():
        return None
    return json.loads((run_dir / "run.json").read_text(encoding="utf-8"))


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


def _candidate_diff(db: AgentRunwayDb, candidate: dict[str, Any], base_ref: str) -> str:
    worker = db.get_worker(str(candidate["worker_id"]))
    worker_tree = Path(str(worker["worktree_path"]))
    return Git(worker_tree).run("diff", base_ref, "HEAD", check=False).stdout


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
    base_run_id = f"{_slug(plan.stem)}-{_now_stamp()}-{_nonce()}"
    run_id = next_available_run_id(repo, base_run_id)
    run_dir, worktree_root = _state_paths(run_id, wsid)
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
    journal = EventJournal(db=db, run_dir=run_dir)
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
    if args.planning_only:
        db.set_run_status(run_id, "planning_only")
        _write_run_json(run_dir, run_json)
        return run_json

    main_worktree = create_main_worktree(git, worktree_root / "main", run_id, base_commit)
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
        else:
            packet = build_task_packet(run_id, task, _spec_slices(spec, task.spec_refs) if spec else [], profile)
            worker_id = f"{task.task_id}-implementer-001"
            output_path = run_dir / "artifacts" / task.task_id / worker_id / "worker_result.json"
            prompt_path = materialize_worker_prompt(packet, packet_path, output_path, run_dir / "prompts")
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
                attempt=1,
                timeout_seconds=600,
            )
            candidate = _merge_candidate(db, candidate_id)
            base_ref = f"agentrunway/{run_id}/main"
            diff = _candidate_diff(db, candidate, base_ref)
            db.set_task_status(task.task_id, "reviewing")
            journal.record(
                "agentrunway.review_dispatched",
                build_event_payload(run_id, "review", "success", "review dispatched", task_id=task.task_id, worker_id=candidate["worker_id"]),
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
                attempt=1,
                timeout_seconds=600,
            )
            review_status = str(review["status"])
            journal.record(
                "agentrunway.review_result",
                build_event_payload(run_id, "review", "success", "review result", task_id=task.task_id, status=review_status),
            )
            if review_status != "approved":
                db.set_task_status(task.task_id, "blocked")
                continue
            db.set_task_status(task.task_id, "verifying")
            journal.record(
                "agentrunway.verification_dispatched",
                build_event_payload(run_id, "verification", "success", "verification dispatched", task_id=task.task_id),
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
                attempt=1,
                timeout_seconds=600,
            )
            verification_status = str(verification["status"])
            journal.record(
                "agentrunway.verification_result",
                build_event_payload(run_id, "verification", "success", "verification result", task_id=task.task_id, status=verification_status),
            )
            if verification_status == "passed":
                db.set_merge_candidate_status(candidate_id, "merge_ready")
                db.set_task_status(task.task_id, "merge_ready")
                journal.record(
                    "agentrunway.merge_ready",
                    build_event_payload(run_id, "merge", "success", "merge ready", task_id=task.task_id, candidate_id=candidate_id),
                )
            else:
                db.set_task_status(task.task_id, "blocked")
    for candidate in db.list_merge_candidates():
        if candidate["status"] != "merge_ready":
            continue
        main_git = Git(main_worktree)
        merge_candidate = MergeCandidate(
            task_id=candidate["task_id"],
            worker_id=candidate["worker_id"],
            commits=tuple(candidate["commits"]),
            changed_files=tuple(candidate["changed_files"]),
        )
        try:
            apply_candidate(main_git, merge_candidate)
        except MergeConflictError as exc:
            db.set_merge_candidate_status(int(candidate["id"]), "merge_conflict", str(exc))
            db.set_task_status(candidate["task_id"], "blocked")
        else:
            db.set_merge_candidate_status(int(candidate["id"]), "merged")
            db.set_worker_state(candidate["worker_id"], "merged")
            db.set_task_status(candidate["task_id"], "merged")
    write_artifact_graph(run_dir=run_dir, db=db)
    db.set_run_status(run_id, "finished")
    journal.record("agentrunway.run_finished", build_event_payload(run_id, "run", "success", "run finished"))
    run_json.update({"status": "finished", "main_worktree": str(main_worktree)})
    _write_run_json(run_dir, run_json)
    return run_json


def _missing(run_id: str) -> dict[str, Any]:
    return {"run_id": run_id, "status": "missing"}


def status(run_id: str) -> dict[str, Any]:
    data = _load_run_json(run_id)
    if data is None:
        return _missing(run_id)
    return {"run_id": run_id, "status": data.get("status"), "run_dir": data.get("run_dir")}


def inspect(run_id: str) -> dict[str, Any]:
    data = _load_run_json(run_id)
    if data is None:
        return _missing(run_id)
    from .status import build_inspect_payload

    db = AgentRunwayDb.open(Path(data["state_db"]))
    return build_inspect_payload(run_json=data, db=db)


def events(run_id: str) -> dict[str, Any]:
    data = _load_run_json(run_id)
    if data is None:
        return _missing(run_id)
    db = AgentRunwayDb.open(Path(data["state_db"]))
    return {"run_id": run_id, "events": db.list_events(), "agentlens": db.agentlens_summary()}


def resume(run_id: str, *, dry_run: bool = False) -> dict[str, Any]:
    data = _load_run_json(run_id)
    if data is None:
        return _missing(run_id)
    db = AgentRunwayDb.open(Path(data["state_db"]))
    plan = plan_reconciliation(run_id=run_id, run_dir=Path(data["run_dir"]), db=db)
    if dry_run:
        return plan
    apply_reconciliation_plan(db=db, plan=plan)
    return {
        "run_id": run_id,
        "status": data.get("status"),
        "run_dir": data.get("run_dir"),
        "reconciliation": plan,
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
    applied = apply_commits_to_source(
        Path(data["repo_root"]),
        tuple(commits),
        strategy=strategy,
        already_applied=already_applied,
    )
    for commit in applied:
        db.record_applied_commit(run_id=run_id, commit_sha=commit, strategy=strategy)
    return {
        "run_id": run_id,
        "status": data.get("status"),
        "applied": True,
        "commits": applied,
        "already_applied": list(already_applied),
    }


def clean(older_than: str, *, successful: bool) -> dict[str, Any]:
    return {"removed": 0, "older_than": older_than, "successful": successful}
