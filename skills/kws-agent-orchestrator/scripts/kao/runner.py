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

from .adapters.local import LocalAdapter
from .artifacts import ArtifactStore
from .config import BuiltinProfiles, load_effective_config
from .db import KaoDb
from .git_ops import Git, assert_clean_source
from .packetizer import build_task_packet, materialize_prompt, packet_to_json
from .plan_parser import canonical_hash, parse_plan, parse_spec_manifest
from .scheduler import schedule_waves
from .worktrees import create_main_worktree, next_available_run_id, workspace_id


def kao_home() -> Path:
    return Path(os.environ.get("KAO_HOME", str(Path.home() / ".kao"))).expanduser()


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "run"


def _now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _nonce() -> str:
    return hashlib.sha1(str(datetime.now(timezone.utc).timestamp()).encode()).hexdigest()[:5]


def _state_paths(run_id: str, wsid: str) -> tuple[Path, Path]:
    home = kao_home()
    run_dir = home / "runs" / wsid / run_id
    worktree_root = home / "worktrees" / wsid / run_id
    return run_dir, worktree_root


def _find_run_dir(run_id: str) -> Path | None:
    runs_root = kao_home() / "runs"
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
    db = KaoDb.open(run_dir / "state.sqlite")
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
    adapter = LocalAdapter(fake_success=bool(args.fake_success)) if args.adapter == "local" else LocalAdapter(fake_success=False)
    store = ArtifactStore(run_dir / "artifacts")
    for task in tasks:
        packet_path = run_dir / "packets" / f"{task.task_id}.json"
        packet_json = db.conn.execute("SELECT packet_json FROM task_packets WHERE task_id=?", (task.task_id,)).fetchone()["packet_json"]
        packet_path.write_text(packet_json, encoding="utf-8")
        task_artifact_dir = run_dir / "artifacts" / task.task_id
        task_artifact_dir.mkdir(parents=True, exist_ok=True)
        result = adapter.run(packet_path, task_artifact_dir)
        store.write_text(task.task_id, "worker_result.json", json.dumps(asdict(result), indent=2, sort_keys=True))
        db.set_task_status(task.task_id, "merged" if result.status == "success" else "blocked")
    db.set_run_status(run_id, "finished")
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
    db_path = Path(data["state_db"])
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    tasks = [dict(row) for row in conn.execute("SELECT task_id, title, status FROM tasks ORDER BY task_id")]
    return {"run_id": run_id, "status": data.get("status"), "tasks": tasks}


def events(run_id: str) -> dict[str, Any]:
    data = _load_run_json(run_id)
    if data is None:
        return _missing(run_id)
    return {"run_id": run_id, "events": []}


def resume(run_id: str) -> dict[str, Any]:
    data = _load_run_json(run_id)
    if data is None:
        return _missing(run_id)
    return {"run_id": run_id, "status": data.get("status"), "resumed": data.get("status") not in {"finished", "cancelled"}}


def cancel(run_id: str) -> dict[str, Any]:
    data = _load_run_json(run_id)
    if data is None:
        return _missing(run_id)
    data["status"] = "cancelled"
    _write_run_json(Path(data["run_dir"]), data)
    return {"run_id": run_id, "status": "cancelled"}


def apply(run_id: str) -> dict[str, Any]:
    data = _load_run_json(run_id)
    if data is None:
        return _missing(run_id)
    return {"run_id": run_id, "status": data.get("status"), "applied": False, "reason": "explicit source apply is not automatic in MVP"}


def clean(older_than: str, *, successful: bool) -> dict[str, Any]:
    return {"removed": 0, "older_than": older_than, "successful": successful}
