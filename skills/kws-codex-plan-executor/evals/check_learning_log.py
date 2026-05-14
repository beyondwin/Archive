#!/usr/bin/env python3
"""Deterministic checks for append_learning_event.py."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "append_learning_event.py"
HEALTH_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_learning_log_health.py"


def base_event(run_id: str) -> dict:
    return {
        "schema_version": "1",
        "run_id": run_id,
        "skill": "kws-codex-plan-executor",
        "skill_version": "1.8.1",
        "mode": "interactive",
        "event_type": "verification_failure",
        "severity": "medium",
        "repo": {"name": "Archive", "remote_hash": None, "branch": "codex/example"},
        "execution": {
            "plan_path": "docs/superpowers/plans/example.md",
            "task_id": "task_2",
            "phase": "verification",
            "run_dir": ".codex-orchestrator/runs/" + run_id,
            "state_path": ".codex-orchestrator/runs/" + run_id + "/state.json",
        },
        "summary": "Acceptance command failed after the implementation touched validator code.",
        "context": {
            "user_intent": "Execute the approved implementation plan.",
            "agent_expectation": "Targeted verification would close the task.",
            "actual_outcome": "A broader Python check was required.",
            "root_cause": "The plan under-declared affected files.",
            "evidence": [{"kind": "command", "value": "python3 scripts/validate_state.py state.json"}],
        },
        "improvement": {
            "target": "references/execution-cycle.md",
            "proposal": "Require risk upgrade when implementation touches files outside the declared block.",
        },
        "privacy": {"redacted": True, "notes": "Home directory omitted."},
    }


def run_helper(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def write_event(repo_root: Path, event: dict, name: str = "event.json") -> Path:
    event_path = repo_root / name
    event_path.write_text(json.dumps(event, ensure_ascii=False), encoding="utf-8")
    return event_path


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def append_jsonl(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")


def run_dir(log_root: Path, run_id: str) -> Path:
    date_part = run_id.split("T", 1)[0]
    return log_root / "runs" / f"{date_part[0:4]}-{date_part[4:6]}-{date_part[6:8]}" / run_id


def make_run(
    log_root: Path,
    run_id: str,
    *,
    pid: int,
    started_at: str,
    outcome: str = "unknown",
    index_outcome: str = "unknown",
    worktree_path: str | None = "/tmp/worktree",
    state_path: str | None = None,
) -> Path:
    rd = run_dir(log_root, run_id)
    resolved_state_path = state_path or f".codex-orchestrator/runs/{run_id}/state.json"
    meta = {
        "schema_version": "1",
        "run_id": run_id,
        "skill": "kws-codex-plan-executor",
        "skill_version": "1.8.1",
        "host": "test.local",
        "pid": pid,
        "repo": {"name": "Fixture", "branch": "codex/test", "remote_hash": "abc123"},
        "mode": "interactive",
        "plan_path": "docs/superpowers/plans/test.md",
        "spec_path": None,
        "worktree_path": worktree_path,
        "project_run_dir": f".codex-orchestrator/runs/{run_id}",
        "state_path": resolved_state_path,
        "started_at": started_at,
        "ended_at": None,
        "outcome": outcome,
        "event_count": 0,
    }
    write_json(rd / "meta.json", meta)
    append_jsonl(
        log_root / "index.jsonl",
        {
            "schema_version": "1",
            "run_id": run_id,
            "skill": "kws-codex-plan-executor",
            "skill_version": "1.8.1",
            "repo": meta["repo"],
            "mode": "interactive",
            "plan_path": meta["plan_path"],
            "project_run_dir": meta["project_run_dir"],
            "state_path": resolved_state_path,
            "started_at": started_at,
            "outcome": index_outcome,
        },
    )
    return rd


def write_project_state(worktree: Path, run_id: str, *, state: dict) -> Path:
    state_path = worktree / ".codex-orchestrator" / "runs" / run_id / "state.json"
    write_json(state_path, state)
    return state_path


def create_dirty_git_worktree(worktree: Path) -> None:
    worktree.mkdir()
    subprocess.run(["git", "init"], cwd=worktree, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    tracked = worktree / "tracked.txt"
    tracked.write_text("clean\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=worktree, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Learning Log Eval",
            "-c",
            "user.email=learning-log-eval@example.invalid",
            "commit",
            "-m",
            "init fixture",
        ],
        cwd=worktree,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    tracked.write_text("dirty\n", encoding="utf-8")
    (worktree / "untracked.txt").write_text("new\n", encoding="utf-8")


def base_project_state(
    run_id: str,
    *,
    worktree: Path,
    current_task: str,
    current_phase: str = "task_loop",
    lifecycle_outcome: str | None = None,
    updated_at: str,
    task_statuses: dict[str, str] | None = None,
) -> dict:
    statuses = task_statuses or {
        "task_1": "completed",
        "task_2": "completed",
        "task_7": "pending",
    }
    return {
        "schema_version": "1",
        "run_id": run_id,
        "mode": "interactive",
        "workspace": str(worktree),
        "plan": str(worktree / "docs/superpowers/plans/example.md"),
        "branch": "codex/example",
        "worktree": str(worktree),
        "run_dir": f".codex-orchestrator/runs/{run_id}",
        "state_path": f".codex-orchestrator/runs/{run_id}/state.json",
        "context_snapshot_path": f".codex-orchestrator/runs/{run_id}/context.json",
        "context_basis_hash": "abc123",
        "context_health": {
            "status": "yellow",
            "last_checked_at": updated_at,
            "context_snapshot_present": True,
            "context_basis_hash_recorded": True,
            "active_task_contract_present": True,
            "next_action": "Run final acceptance verification commands.",
            "open_questions": [],
            "known_assumptions": [],
            "handoff_ready": True,
        },
        "current_task": current_task,
        "current_phase": current_phase,
        "lifecycle_outcome": lifecycle_outcome,
        "handoff_reason": "",
        "tasks": {
            task_id: {
                "status": status,
                "risk": "low",
                "files_declared": [],
                "contract": {},
                "review_retries": 0,
                "verifier_retries": 0,
            }
            for task_id, status in statuses.items()
        },
        "timestamps": {
            "started_at": updated_at,
            "updated_at": updated_at,
            "completed_at": None,
        },
    }


def init_run(log_root: Path, repo_root: Path, **kwargs: str) -> str:
    result = run_helper(
        "init-run",
        "--log-root",
        str(log_root),
        "--repo-root",
        str(repo_root),
        "--repo-name",
        kwargs.get("repo_name", "Archive"),
        "--branch",
        kwargs.get("branch", "codex/example"),
        "--head",
        kwargs.get("head", "7e884a0"),
        "--plan-path",
        kwargs.get("plan_path", "docs/superpowers/plans/example.md"),
        "--spec-path",
        kwargs.get("spec_path", "docs/spec.md"),
        "--mode",
        kwargs.get("mode", "interactive"),
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout)
    return result.stdout.strip()


def run_health_report(log_root: Path, *, latest: int = 5, stale_after_minutes: int = 30) -> dict:
    result = subprocess.run(
        [
            sys.executable,
            str(HEALTH_SCRIPT),
            "--log-root",
            str(log_root),
            "--latest",
            str(latest),
            "--stale-after-minutes",
            str(stale_after_minutes),
            "--json",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout)
    return json.loads(result.stdout)


def main() -> int:
    checks: dict[str, bool] = {}
    failures: list[str] = []

    with tempfile.TemporaryDirectory(prefix="codex-learning-log-") as temp:
        temp_path = Path(temp)
        repo_root = temp_path / "repo"
        repo_root.mkdir()
        log_root = temp_path / "learning"

        try:
            run_id = init_run(log_root, repo_root)
            rd = run_dir(log_root, run_id)
            meta = json.loads((rd / "meta.json").read_text(encoding="utf-8"))
            checks["init_run_creates_sharded_run_dir"] = (
                rd.is_dir()
                and meta.get("run_id") == run_id
                and meta.get("skill") == "kws-codex-plan-executor"
                and meta.get("helper_pid") == meta.get("pid")
                and meta.get("outcome") == "unknown"
                and meta.get("event_count") == 0
                and meta.get("project_run_dir") == f".codex-orchestrator/runs/{run_id}"
                and meta.get("state_path") == f".codex-orchestrator/runs/{run_id}/state.json"
            )
        except Exception as exc:  # noqa: BLE001
            run_id = ""
            checks["init_run_creates_sharded_run_dir"] = False
            failures.append(f"init-run should create per-run meta: {exc}")

        if run_id and not checks["init_run_creates_sharded_run_dir"]:
            failures.append("init-run should create sharded run dir with expected meta fields")

        if run_id:
            index_path = log_root / "index.jsonl"
            checks["init_run_updates_global_index"] = (
                index_path.is_file()
                and any(json.loads(line).get("run_id") == run_id for line in index_path.read_text().splitlines())
            )
            if not checks["init_run_updates_global_index"]:
                failures.append("init-run should append one global index.jsonl row")

        if run_id:
            event_path = write_event(repo_root, base_event(run_id))
            valid = run_helper(
                "append",
                "--log-root",
                str(log_root),
                "--run-id",
                run_id,
                "--event-json",
                str(event_path),
                "--repo-root",
                str(repo_root),
            )
            events_path = run_dir(log_root, run_id) / "events.jsonl"
            lines = events_path.read_text(encoding="utf-8").splitlines() if events_path.is_file() else []
            appended = json.loads(lines[0]) if lines else {}
            checks["append_writes_per_run_event"] = (
                valid.returncode == 0
                and len(lines) == 1
                and appended.get("run_id") == run_id
                and appended.get("execution", {}).get("run_dir") == f".codex-orchestrator/runs/{run_id}"
                and appended.get("execution", {}).get("state_path") == f".codex-orchestrator/runs/{run_id}/state.json"
                and isinstance(appended.get("event_id"), str)
            )
            if not checks["append_writes_per_run_event"]:
                failures.append("append should write one event under the per-run events.jsonl")

        if run_id:
            dry_event_path = write_event(repo_root, base_event(run_id), "dry.json")
            dry = run_helper(
                "append",
                "--log-root",
                str(log_root),
                "--run-id",
                run_id,
                "--event-json",
                str(dry_event_path),
                "--repo-root",
                str(repo_root),
                "--dry-run",
            )
            events_path = run_dir(log_root, run_id) / "events.jsonl"
            checks["dry_run_no_write"] = (
                dry.returncode == 0
                and len(events_path.read_text(encoding="utf-8").splitlines()) == 1
                and '"event_id"' in dry.stdout
            )
            if not checks["dry_run_no_write"]:
                failures.append("dry-run should validate and print sanitized event without writing")

        if run_id:
            mismatch = base_event(run_id + "-wrong")
            mismatch_path = write_event(repo_root, mismatch, "mismatch.json")
            mismatch_result = run_helper(
                "append",
                "--log-root",
                str(log_root),
                "--run-id",
                run_id,
                "--event-json",
                str(mismatch_path),
                "--repo-root",
                str(repo_root),
            )
            checks["run_id_mismatch_rejected"] = mismatch_result.returncode != 0 and "run_id" in (
                mismatch_result.stderr + mismatch_result.stdout
            )
            if not checks["run_id_mismatch_rejected"]:
                failures.append("append should reject cross-run event candidates")

        if run_id:
            close = run_helper(
                "close-run",
                "--log-root",
                str(log_root),
                "--run-id",
                run_id,
                "--outcome",
                "success",
            )
            meta_after = json.loads((run_dir(log_root, run_id) / "meta.json").read_text(encoding="utf-8"))
            final_path = run_dir(log_root, run_id) / "final.json"
            final = json.loads(final_path.read_text(encoding="utf-8")) if final_path.is_file() else {}
            checks["close_run_writes_final"] = (
                close.returncode == 0
                and meta_after.get("outcome") == "success"
                and meta_after.get("event_count") == 1
                and meta_after.get("ended_at")
                and final.get("outcome") == "success"
                and final.get("event_count") == 1
            )
            if not checks["close_run_writes_final"]:
                failures.append("close-run should update meta.json and write final.json")

        missing = base_event(run_id or "20260513T000000Z-archive-unknown-000000")
        del missing["summary"]
        missing_result = run_helper(
            "append",
            "--log-root",
            str(log_root),
            "--run-id",
            missing["run_id"],
            "--event-json",
            str(write_event(repo_root, missing, "missing.json")),
            "--repo-root",
            str(repo_root),
        )
        checks["missing_required_field_fails"] = missing_result.returncode != 0 and "summary" in (
            missing_result.stderr + missing_result.stdout
        )
        if not checks["missing_required_field_fails"]:
            failures.append("missing summary should fail")

        invalid_mode = base_event(run_id or "20260513T000000Z-archive-unknown-000000")
        invalid_mode["mode"] = "prompt"
        invalid_mode_result = run_helper(
            "append",
            "--log-root",
            str(log_root),
            "--run-id",
            invalid_mode["run_id"],
            "--event-json",
            str(write_event(repo_root, invalid_mode, "invalid-mode.json")),
            "--repo-root",
            str(repo_root),
        )
        checks["invalid_mode_fails"] = invalid_mode_result.returncode != 0 and "mode" in (
            invalid_mode_result.stderr + invalid_mode_result.stdout
        )
        if not checks["invalid_mode_fails"]:
            failures.append("prompt mode should fail for learning events")

        home_path = base_event(run_id or "20260513T000000Z-archive-unknown-000000")
        home_path["context"]["evidence"] = [{"kind": "relative_path", "value": str(Path.home() / "secret.txt")}]
        home_result = run_helper(
            "append",
            "--log-root",
            str(log_root),
            "--run-id",
            home_path["run_id"],
            "--event-json",
            str(write_event(repo_root, home_path, "home.json")),
            "--repo-root",
            str(repo_root),
        )
        checks["home_path_rejected"] = home_result.returncode != 0 and "home path" in (
            home_result.stderr + home_result.stdout
        )
        if not checks["home_path_rejected"]:
            failures.append("absolute home path should be rejected")

        secret = base_event(run_id or "20260513T000000Z-archive-unknown-000000")
        secret["context"]["evidence"] = [{"kind": "excerpt", "value": "Authorization: Bearer abc123"}]
        secret_result = run_helper(
            "append",
            "--log-root",
            str(log_root),
            "--run-id",
            secret["run_id"],
            "--event-json",
            str(write_event(repo_root, secret, "secret.json")),
            "--repo-root",
            str(repo_root),
        )
        checks["secret_like_value_rejected"] = secret_result.returncode != 0 and "secret-like" in (
            secret_result.stderr + secret_result.stdout
        )
        if not checks["secret_like_value_rejected"]:
            failures.append("secret-like values should be rejected")

        health_root = temp_path / "health-learning"
        stale_started_at = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat().replace("+00:00", "Z")
        recent_started_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        index_final = "20260513T010000Z-fixture-index-final-abcdef123456-111111"
        index_final_dir = make_run(health_root, index_final, pid=os.getpid(), started_at=recent_started_at)
        write_json(
            index_final_dir / "final.json",
            {
                "schema_version": "1",
                "run_id": index_final,
                "outcome": "success",
                "ended_at": recent_started_at,
                "event_count": 1,
            },
        )

        zero_event = "20260513T020000Z-fixture-zero-event-abcdef123456-222222"
        zero_event_dir = make_run(
            health_root,
            zero_event,
            pid=os.getpid(),
            started_at=recent_started_at,
            index_outcome="success",
        )
        write_json(
            zero_event_dir / "final.json",
            {
                "schema_version": "1",
                "run_id": zero_event,
                "outcome": "success",
                "ended_at": recent_started_at,
                "event_count": 0,
            },
        )

        dead_pid = "20260513T030000Z-fixture-dead-pid-abcdef123456-333333"
        make_run(health_root, dead_pid, pid=999999999, started_at=stale_started_at)

        live_pid = "20260513T040000Z-fixture-live-pid-abcdef123456-444444"
        make_run(health_root, live_pid, pid=os.getpid(), started_at=stale_started_at)

        active_state = "20260513T050000Z-fixture-active-state-abcdef123456-555555"
        active_worktree = temp_path / "active-worktree"
        active_worktree.mkdir()
        write_project_state(
            active_worktree,
            active_state,
            state=base_project_state(
                active_state,
                worktree=active_worktree,
                current_task="task_7",
                updated_at=recent_started_at,
            ),
        )
        make_run(
            health_root,
            active_state,
            pid=999999999,
            started_at=stale_started_at,
            worktree_path=str(active_worktree),
        )

        needs_finalization = "20260513T060000Z-fixture-needs-final-abcdef123456-666666"
        needs_final_worktree = temp_path / "needs-final-worktree"
        needs_final_worktree.mkdir()
        write_project_state(
            needs_final_worktree,
            needs_finalization,
            state=base_project_state(
                needs_finalization,
                worktree=needs_final_worktree,
                current_task="task_7",
                current_phase="final_verification",
                updated_at=recent_started_at,
                task_statuses={"task_1": "completed", "task_2": "completed", "task_7": "completed"},
            ),
        )
        make_run(
            health_root,
            needs_finalization,
            pid=999999999,
            started_at=stale_started_at,
            worktree_path=str(needs_final_worktree),
        )

        stale_project_state = "20260513T070000Z-fixture-stale-state-abcdef123456-777777"
        stale_worktree = temp_path / "stale-worktree"
        stale_worktree.mkdir()
        write_project_state(
            stale_worktree,
            stale_project_state,
            state=base_project_state(
                stale_project_state,
                worktree=stale_worktree,
                current_task="task_1",
                updated_at=stale_started_at,
                task_statuses={"task_1": "pending", "task_2": "pending"},
            ),
        )
        make_run(
            health_root,
            stale_project_state,
            pid=999999999,
            started_at=stale_started_at,
            worktree_path=str(stale_worktree),
        )

        missing_worktree = "20260513T080000Z-fixture-missing-worktree-abcdef123456-888888"
        make_run(
            health_root,
            missing_worktree,
            pid=999999999,
            started_at=stale_started_at,
            worktree_path=str(temp_path / "missing-worktree"),
        )

        dirty_active = "20260513T090000Z-fixture-dirty-active-abcdef123456-999999"
        dirty_worktree = temp_path / "dirty-worktree"
        create_dirty_git_worktree(dirty_worktree)
        write_project_state(
            dirty_worktree,
            dirty_active,
            state=base_project_state(
                dirty_active,
                worktree=dirty_worktree,
                current_task="task_2",
                updated_at=recent_started_at,
                task_statuses={"task_1": "completed", "task_2": "in_progress"},
            ),
        )
        subprocess.run(
            ["git", "add", ".codex-orchestrator"],
            cwd=dirty_worktree,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Learning Log Eval",
                "-c",
                "user.email=learning-log-eval@example.invalid",
                "commit",
                "-m",
                "add state fixture",
            ],
            cwd=dirty_worktree,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        make_run(
            health_root,
            dirty_active,
            pid=os.getpid(),
            started_at=recent_started_at,
            worktree_path=str(dirty_worktree),
        )

        try:
            health = run_health_report(health_root, latest=9, stale_after_minutes=30)
            by_run_id = {item["run_id"]: item for item in health.get("runs", [])}
            checks["health_index_unknown_final_success"] = (
                by_run_id.get(index_final, {}).get("status") == "success"
                and "index_outcome_stale" in by_run_id.get(index_final, {}).get("diagnostics", {}).get("info", [])
                and not by_run_id.get(index_final, {}).get("warnings")
            )
            checks["health_zero_event_success"] = (
                by_run_id.get(zero_event, {}).get("status") == "success"
                and by_run_id.get(zero_event, {}).get("event_count") == 0
                and by_run_id.get(zero_event, {}).get("event_note") == "routine_success_no_notable_events"
                and not by_run_id.get(zero_event, {}).get("warnings")
            )
            checks["health_dead_pid_unclosed_run"] = (
                by_run_id.get(dead_pid, {}).get("status") == "unknown"
                and "helper_pid_dead" in by_run_id.get(dead_pid, {}).get("diagnostics", {}).get("info", [])
            )
            checks["health_live_pid_unclosed_run"] = (
                by_run_id.get(live_pid, {}).get("status") == "unknown"
                and "dead_pid_unclosed" not in by_run_id.get(live_pid, {}).get("warnings", [])
            )
            checks["health_active_project_state_dead_helper_pid"] = (
                by_run_id.get(active_state, {}).get("status") == "in_progress"
                and by_run_id.get(active_state, {}).get("project_state", {}).get("current_task") == "task_7"
                and "helper_pid_dead" in by_run_id.get(active_state, {}).get("diagnostics", {}).get("info", [])
                and "missing_learning_final" in by_run_id.get(active_state, {}).get("diagnostics", {}).get("info", [])
                and not by_run_id.get(active_state, {}).get("diagnostics", {}).get("warnings", [])
            )
            checks["health_needs_finalization_project_state"] = (
                by_run_id.get(needs_finalization, {}).get("status") == "needs_finalization"
                and by_run_id.get(needs_finalization, {}).get("project_state", {}).get("task_counts", {}).get("completed") == 3
                and "missing_learning_final"
                in by_run_id.get(needs_finalization, {}).get("diagnostics", {}).get("info", [])
            )
            checks["health_old_project_state_stale_candidate"] = (
                by_run_id.get(stale_project_state, {}).get("status") == "stale_candidate"
                and "project_state_inactive_past_threshold"
                in by_run_id.get(stale_project_state, {}).get("diagnostics", {}).get("warnings", [])
            )
            checks["health_missing_worktree_unknown"] = (
                by_run_id.get(missing_worktree, {}).get("status") == "unknown"
                and "missing_worktree" in by_run_id.get(missing_worktree, {}).get("diagnostics", {}).get("warnings", [])
                and "missing_project_state"
                in by_run_id.get(missing_worktree, {}).get("diagnostics", {}).get("warnings", [])
            )
            checks["health_dirty_active_git_state"] = (
                by_run_id.get(dirty_active, {}).get("status") == "in_progress"
                and by_run_id.get(dirty_active, {}).get("git_state", {}).get("worktree_exists") is True
                and by_run_id.get(dirty_active, {}).get("git_state", {}).get("git_readable") is True
                and by_run_id.get(dirty_active, {}).get("git_state", {}).get("short_status_count") == 2
                and by_run_id.get(dirty_active, {}).get("git_state", {}).get("modified_count") == 1
                and by_run_id.get(dirty_active, {}).get("git_state", {}).get("untracked_count") == 1
                and by_run_id.get(dirty_active, {}).get("git_state", {}).get("head")
                and by_run_id.get(dirty_active, {}).get("git_state", {}).get("branch")
                and "dirty_worktree_during_in_progress"
                in by_run_id.get(dirty_active, {}).get("diagnostics", {}).get("warnings", [])
            )
        except Exception as exc:  # noqa: BLE001
            checks["health_index_unknown_final_success"] = False
            checks["health_zero_event_success"] = False
            checks["health_dead_pid_unclosed_run"] = False
            checks["health_live_pid_unclosed_run"] = False
            checks["health_active_project_state_dead_helper_pid"] = False
            checks["health_needs_finalization_project_state"] = False
            checks["health_old_project_state_stale_candidate"] = False
            checks["health_missing_worktree_unknown"] = False
            checks["health_dirty_active_git_state"] = False
            failures.append(f"health reporter should summarize fixture runs: {exc}")

        for check, message in {
            "health_index_unknown_final_success": "health reporter should prefer final.json over unknown index outcome",
            "health_zero_event_success": "health reporter should treat zero-event success as routine",
            "health_dead_pid_unclosed_run": "health reporter should not classify old dead-helper-pid runs as stale",
            "health_live_pid_unclosed_run": "health reporter should not classify live-pid unclosed runs as stale",
            "health_active_project_state_dead_helper_pid": "health reporter should prefer active project state over dead helper pid",
            "health_needs_finalization_project_state": "health reporter should detect completed tasks awaiting finalization",
            "health_old_project_state_stale_candidate": "health reporter should report old inactive project state as stale_candidate",
            "health_missing_worktree_unknown": "health reporter should report missing worktree/state diagnostics without crashing",
            "health_dirty_active_git_state": "health reporter should summarize dirty git state for active runs",
        }.items():
            if not checks.get(check):
                failures.append(message)

    payload = {"passed": not failures, "checks": checks, "failures": failures}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
