#!/usr/bin/env python3
"""Deterministic checks for append_learning_event.py."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "append_learning_event.py"


def base_event(run_id: str) -> dict:
    return {
        "schema_version": "1",
        "run_id": run_id,
        "skill": "kws-codex-plan-executor",
        "skill_version": "1.4.0",
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


def run_dir(log_root: Path, run_id: str) -> Path:
    date_part = run_id.split("T", 1)[0]
    return log_root / "runs" / f"{date_part[0:4]}-{date_part[4:6]}-{date_part[6:8]}" / run_id


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

    payload = {"passed": not failures, "checks": checks, "failures": failures}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
