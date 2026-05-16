#!/usr/bin/env python3
"""Deterministic checks for project-local run event journals."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


RUN_ID = "20260516T000000Z-archive-codex-events-abcdef0-a1b2c3"


def unit_manifest() -> dict:
    return {
        "unit_type": "execute-task",
        "context_mode": "focused",
        "required_skills": ["using-superpowers", "test-driven-development"],
        "tool_policy": "implementation",
        "allowed_write_globs": ["docs/example.md"],
        "forbidden_write_globs": [".git/**"],
        "artifact_policy": "inline-summary",
        "max_context_chars": 60000,
    }


def base_state(repo: Path) -> dict:
    return {
        "schema_version": "1",
        "run_id": RUN_ID,
        "mode": "interactive",
        "workspace": str(repo),
        "plan": str(repo / "plan.md"),
        "branch": "codex/events",
        "worktree": str(repo),
        "run_dir": f".codex-orchestrator/runs/{RUN_ID}",
        "state_path": f".codex-orchestrator/runs/{RUN_ID}/state.json",
        "context_snapshot_path": f".codex-orchestrator/runs/{RUN_ID}/context.json",
        "context_basis_hash": "0" * 64,
        "context_health": {
            "status": "green",
            "last_checked_at": "2026-05-16T00:00:00Z",
            "context_snapshot_present": True,
            "context_basis_hash_recorded": True,
            "active_task_contract_present": True,
            "next_action": "Append an event.",
            "open_questions": [],
            "known_assumptions": [],
            "handoff_ready": True,
        },
        "current_task": "task_0",
        "current_phase": "task_loop",
        "lifecycle_outcome": None,
        "handoff_reason": "",
        "completion_audit": None,
        "tasks": {
            "task_0": {
                "status": "in_progress",
                "risk": "low",
                "files_declared": ["docs/example.md"],
                "contract": {
                    "scope": "Update docs.",
                    "files_to_inspect": ["docs/example.md"],
                    "allowed_edits": ["docs/example.md"],
                    "forbidden_edits": [".git/**"],
                    "acceptance_command_or_honest_substitute": "append event",
                },
                "unit_manifest": unit_manifest(),
                "review_retries": 0,
                "verifier_retries": 0,
            }
        },
        "timestamps": {
            "started_at": "2026-05-16T00:00:00Z",
            "updated_at": "2026-05-16T00:00:00Z",
            "completed_at": None,
        },
    }


def write_state(repo: Path, state: dict) -> Path:
    state_path = repo / state["state_path"]
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    (state_path.parent / "context.json").write_text('{"basis_hash":"' + "0" * 64 + '"}\n', encoding="utf-8")
    (repo / "plan.md").write_text("plan\n", encoding="utf-8")
    return state_path


def run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def append_event(script: Path, repo: Path, state_path: Path, event_type: str, payload: dict) -> subprocess.CompletedProcess[str]:
    return run(
        [
            sys.executable,
            str(script),
            "--state",
            str(state_path),
            "--type",
            event_type,
            "--payload",
            json.dumps(payload),
        ],
        repo,
    )


def read_events(state_path: Path) -> list[dict]:
    journal_path = state_path.parent / "events.jsonl"
    return [json.loads(line) for line in journal_path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> int:
    skill_dir = Path(__file__).resolve().parents[1]
    append_script = skill_dir / "scripts" / "append_run_event.py"
    validate_script = skill_dir / "scripts" / "validate_state.py"
    checks: dict[str, bool] = {}
    failures: list[str] = []

    with tempfile.TemporaryDirectory(prefix="codex-event-journal-") as temp:
        repo = Path(temp)
        state_path = write_state(repo, base_state(repo))

        first = append_event(append_script, repo, state_path, "run_started", {"mode": "interactive"})
        state_after_first = json.loads(state_path.read_text(encoding="utf-8"))
        events = read_events(state_path) if (state_path.parent / "events.jsonl").is_file() else []
        checks["first_event_creates_journal_and_seq_1"] = (
            first.returncode == 0
            and state_after_first.get("last_event_seq") == 1
            and state_after_first.get("event_journal_path") == f".codex-orchestrator/runs/{RUN_ID}/events.jsonl"
            and len(events) == 1
            and events[0].get("seq") == 1
            and events[0].get("run_id") == RUN_ID
        )
        if not checks["first_event_creates_journal_and_seq_1"]:
            failures.append("first event should create events.jsonl and set state last_event_seq=1")

        second = append_event(append_script, repo, state_path, "task_started", {"task_id": "task_0"})
        state_after_second = json.loads(state_path.read_text(encoding="utf-8"))
        events = read_events(state_path) if (state_path.parent / "events.jsonl").is_file() else []
        checks["second_event_increments_seq"] = (
            second.returncode == 0
            and state_after_second.get("last_event_seq") == 2
            and len(events) == 2
            and events[-1].get("seq") == 2
        )
        if not checks["second_event_increments_seq"]:
            failures.append("second event should increment seq and state.last_event_seq")

        wrong_run = append_event(append_script, repo, state_path, "task_started", {"run_id": "wrong"})
        checks["wrong_run_id_rejected"] = wrong_run.returncode != 0 and "run_id" in (wrong_run.stderr + wrong_run.stdout)
        if not checks["wrong_run_id_rejected"]:
            failures.append("payload run_id mismatch should be rejected")

        secret = append_event(
            append_script,
            repo,
            state_path,
            "verification_started",
            {"api_key": "abc123", "nested": {"cookie": "value"}, "long": "x" * 405},
        )
        events = read_events(state_path) if (state_path.parent / "events.jsonl").is_file() else []
        payload = events[-1].get("payload", {}) if events else {}
        checks["secret_payload_redacted"] = (
            secret.returncode == 0
            and payload.get("api_key") == "[REDACTED]"
            and payload.get("nested", {}).get("cookie") == "[REDACTED]"
            and isinstance(payload.get("long"), str)
            and len(payload["long"]) == 400
        )
        if not checks["secret_payload_redacted"]:
            failures.append("secret-like payload keys should be redacted and long strings truncated")

    with tempfile.TemporaryDirectory(prefix="codex-event-journal-state-") as temp:
        repo = Path(temp)
        finished = base_state(repo)
        finished["lifecycle_outcome"] = "finished"
        finished["completion_audit"] = {
            "passed": True,
            "prompt_to_artifact_checklist": ["Task completed"],
            "verification_evidence": [{"command": "true", "status": "passed"}],
            "open_gaps": [],
            "residual_risk": [],
        }
        finished["tasks"]["task_0"]["status"] = "completed"
        finished["timestamps"]["completed_at"] = "2026-05-16T00:00:00Z"
        finished["event_journal_path"] = f".codex-orchestrator/runs/{RUN_ID}/events.jsonl"
        finished["last_event_seq"] = 0
        state_path = write_state(repo, finished)
        result = run([sys.executable, str(validate_script), str(state_path)], repo)
        checks["finished_stale_last_event_seq_fails_validation"] = (
            result.returncode != 0 and "last_event_seq" in (result.stderr + result.stdout)
        )
        if not checks["finished_stale_last_event_seq_fails_validation"]:
            failures.append("finished state should require positive last_event_seq")

    payload = {"passed": not failures, "checks": checks, "failures": failures}
    print(json.dumps(payload, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
