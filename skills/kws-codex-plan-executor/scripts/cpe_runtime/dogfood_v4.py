"""Derive sanitized v4 release dogfood evidence from one real CPE run directory."""

from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path

from .events import read_events, validate_chain
from .git_delta import committed_patch_digest, working_tree_changed_files
from .manifest import load_verified_manifest, resolve_ref
from .projector import project


def _git(worktree: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=worktree, text=True, capture_output=True
    )
    if result.returncode:
        raise ValueError("dogfood_checkpoint_invalid")
    return result.stdout.strip()


def _elapsed_seconds(events: list[dict[str, object]]) -> float:
    if not events:
        raise ValueError("dogfood_run_incomplete")
    try:
        started = datetime.fromisoformat(str(events[0]["at"]))
        finished = datetime.fromisoformat(str(events[-1]["at"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("dogfood_run_integrity_invalid") from exc
    elapsed = (finished - started).total_seconds()
    if elapsed < 0 or elapsed > 3600:
        raise ValueError("dogfood_elapsed_invalid")
    return elapsed


def verify_v4_dogfood_run(
    run_dir: Path,
    *,
    expected_implementation_commit: str,
    expected_implementation_tree: str,
    expected_task_contract_sha256: str,
) -> dict[str, object]:
    """Verify and field-select one production CPE v4 dogfood run."""

    root = run_dir.expanduser().resolve()
    if not root.is_dir() or root.is_symlink():
        raise ValueError("dogfood_run_missing")
    try:
        manifest = load_verified_manifest(root / "run_manifest.json")
        events = read_events(root / "events.jsonl")
        if validate_chain(events):
            raise ValueError("dogfood_run_integrity_invalid")
        replayed = project(manifest, events)
    except (OSError, KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, ValueError) and str(exc).startswith("dogfood_"):
            raise
        raise ValueError("dogfood_run_integrity_invalid") from exc
    state_path = root / "state.json"
    try:
        stored_state = state_path.read_text(encoding="utf-8")
        import json

        if json.loads(stored_state) != replayed:
            raise ValueError("dogfood_run_integrity_invalid")
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("dogfood_run_integrity_invalid") from exc
    tasks = replayed.get("tasks")
    if (
        not isinstance(tasks, dict)
        or not tasks
        or any(not isinstance(task, dict) or task.get("status") != "completed" for task in tasks.values())
    ):
        raise ValueError("dogfood_run_incomplete")
    task_graph = manifest.get("task_graph")
    verified = replayed.get("verified_checkpoints")
    candidates = replayed.get("candidate_checkpoints")
    if (
        not isinstance(task_graph, list)
        or len(task_graph) != 1
        or not isinstance(verified, list)
        or len(verified) != 1
        or not isinstance(candidates, list)
        or not candidates
    ):
        raise ValueError("dogfood_checkpoint_count_invalid")
    checkpoint = verified[0]
    if (
        not isinstance(checkpoint, dict)
        or checkpoint.get("contract_sha256") != expected_task_contract_sha256
    ):
        raise ValueError("dogfood_task_contract_invalid")
    candidate = next(
        (
            item
            for item in candidates
            if isinstance(item, dict)
            and item.get("task_id") == checkpoint.get("task_id")
            and item.get("commit") == checkpoint.get("commit")
        ),
        None,
    )
    if candidate is None:
        raise ValueError("dogfood_checkpoint_invalid")
    workspace = resolve_ref(str(manifest["workspace_ref"]))
    worktree = resolve_ref(str(manifest["execution_worktree_ref"]))
    source = manifest.get("source_git")
    runtime = manifest.get("runtime")
    if (
        not isinstance(source, dict)
        or source.get("head") != expected_implementation_commit
        or source.get("status") != []
        or not isinstance(runtime, dict)
        or runtime.get("runtime_commit") != expected_implementation_commit
        or _git(workspace, "rev-parse", "HEAD") != expected_implementation_commit
        or _git(workspace, "rev-parse", f"{expected_implementation_commit}^{{tree}}")
        != expected_implementation_tree
        or working_tree_changed_files(workspace)
    ):
        raise ValueError("dogfood_source_checkpoint_invalid")
    commit = str(checkpoint.get("commit"))
    predecessor = str(checkpoint.get("predecessor"))
    if (
        _git(worktree, "rev-parse", "HEAD") != commit
        or _git(worktree, "rev-parse", f"{commit}^{{tree}}") != checkpoint.get("tree")
        or len(_git(worktree, "rev-list", "--parents", "-n", "1", commit).split()) != 2
        or working_tree_changed_files(worktree)
    ):
        raise ValueError("dogfood_checkpoint_invalid")
    _files, patch_sha256 = committed_patch_digest(worktree, predecessor, commit)
    if patch_sha256 != candidate.get("patch_sha256"):
        raise ValueError("dogfood_checkpoint_invalid")
    attempts = [event for event in events if event.get("type") == "attempt.started"]
    if not 1 <= len(attempts) <= 4:
        raise ValueError("dogfood_attempt_count_invalid")
    repair_roots = replayed.get("repair_roots", {})
    if not isinstance(repair_roots, dict) or max(repair_roots.values(), default=0) > 2:
        raise ValueError("dogfood_repair_limit_invalid")
    if any(event.get("type") in {"merge.applied", "patch.applied"} for event in events):
        raise ValueError("dogfood_apply_forbidden")
    return {
        "schema_version": "cpe.dogfood-result.v4",
        "status": "passed",
        "run_ids_created": 1,
        "model_attempts": len(attempts),
        "max_same_root_repairs": max(repair_roots.values(), default=0),
        "verified_checkpoints": [commit],
        "elapsed_seconds": _elapsed_seconds(events),
        "source_checkout_unchanged": True,
        "runtime_patch_required": False,
    }
