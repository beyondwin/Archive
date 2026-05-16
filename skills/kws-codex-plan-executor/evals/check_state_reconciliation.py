#!/usr/bin/env python3
"""Deterministic checks for reconcile_state.py."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


RUN_ID = "20260516T000000Z-archive-codex-reconcile-abcdef0-a1b2c3"


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
        "branch": "codex/reconcile",
        "worktree": str(repo),
        "run_dir": f".codex-orchestrator/runs/{RUN_ID}",
        "state_path": f".codex-orchestrator/runs/{RUN_ID}/state.json",
        "context_snapshot_path": f".codex-orchestrator/runs/{RUN_ID}/context.json",
        "context_basis_hash": "0" * 64,
        "event_journal_path": f".codex-orchestrator/runs/{RUN_ID}/events.jsonl",
        "last_event_seq": 1,
        "context_health": {
            "status": "green",
            "last_checked_at": "2026-05-16T00:00:00Z",
            "context_snapshot_present": True,
            "context_basis_hash_recorded": True,
            "active_task_contract_present": False,
            "next_action": "Finished.",
            "open_questions": [],
            "known_assumptions": [],
            "handoff_ready": True,
        },
        "current_task": "task_0",
        "current_phase": "finish",
        "lifecycle_outcome": "finished",
        "handoff_reason": "",
        "completion_audit": {
            "passed": True,
            "prompt_to_artifact_checklist": ["Task completed"],
            "verification_evidence": [{"command": "true", "status": "passed"}],
            "open_gaps": [],
            "residual_risk": [],
        },
        "tasks": {
            "task_0": {
                "status": "completed",
                "risk": "low",
                "files_declared": ["docs/example.md"],
                "contract": {
                    "scope": "Update docs.",
                    "files_to_inspect": ["docs/example.md"],
                    "allowed_edits": ["docs/example.md"],
                    "forbidden_edits": [".git/**"],
                    "acceptance_command_or_honest_substitute": "true",
                },
                "unit_manifest": unit_manifest(),
                "review_retries": 0,
                "verifier_retries": 0,
            }
        },
        "timestamps": {
            "started_at": "2026-05-16T00:00:00Z",
            "updated_at": "2026-05-16T00:00:00Z",
            "completed_at": "2026-05-16T00:00:00Z",
        },
    }


def write_run(repo: Path, state: dict, context_hash: str = "0" * 64, journal_run_id: str | None = None) -> Path:
    state_path = repo / state["state_path"]
    state_path.parent.mkdir(parents=True, exist_ok=True)
    (repo / "plan.md").write_text("plan\n", encoding="utf-8")
    (state_path.parent / "context.json").write_text(
        json.dumps({"basis_hash": context_hash}) + "\n",
        encoding="utf-8",
    )
    event = {
        "schema_version": "1",
        "run_id": journal_run_id or state["run_id"],
        "seq": 1,
        "timestamp": "2026-05-16T00:00:00Z",
        "type": "run_started",
        "payload": {},
    }
    (state_path.parent / "events.jsonl").write_text(json.dumps(event) + "\n", encoding="utf-8")
    state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    return state_path


def run_reconcile(script: Path, state_path: Path, repair: bool) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), "--state", str(state_path), "--repair-safe" if repair else "--check"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def payload(result: subprocess.CompletedProcess[str]) -> dict:
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}


def has_record(data: dict, drift_type: str) -> bool:
    records = data.get("records", [])
    return any(isinstance(record, dict) and record.get("type") == drift_type for record in records)


def repair_case(name: str, mutate_state, assert_state) -> tuple[bool, str]:
    script = Path(__file__).resolve().parents[1] / "scripts" / "reconcile_state.py"
    with tempfile.TemporaryDirectory(prefix=f"codex-reconcile-{name}-") as temp:
        repo = Path(temp)
        state = base_state(repo)
        mutate_state(repo, state)
        state_path = write_run(repo, state)
        result = run_reconcile(script, state_path, repair=True)
        data = payload(result)
        repaired = json.loads(state_path.read_text(encoding="utf-8"))
        ok = result.returncode == 0 and data.get("passed") is True and assert_state(repo, repaired, data)
        if ok:
            return True, ""
        return False, f"{name}: rc={result.returncode} stdout={result.stdout!r} stderr={result.stderr!r}"


def blocking_case(name: str, mutate_state, context_hash: str = "0" * 64) -> tuple[bool, str]:
    script = Path(__file__).resolve().parents[1] / "scripts" / "reconcile_state.py"
    with tempfile.TemporaryDirectory(prefix=f"codex-reconcile-{name}-") as temp:
        repo = Path(temp)
        state = base_state(repo)
        mutate_state(repo, state)
        state_path = write_run(repo, state, context_hash=context_hash)
        result = run_reconcile(script, state_path, repair=False)
        data = payload(result)
        ok = result.returncode == 1 and data.get("passed") is False and has_record(data, name)
        if ok:
            return True, ""
        return False, f"{name}: rc={result.returncode} stdout={result.stdout!r} stderr={result.stderr!r}"


def main() -> int:
    checks: dict[str, bool] = {}
    failures: list[str] = []

    repair_cases = [
        (
            "stale-root-state-pointer",
            lambda repo, state: (repo / ".codex-orchestrator").mkdir(parents=True, exist_ok=True)
            or (repo / ".codex-orchestrator" / "state.json").write_text('{"state_path":"old"}\n', encoding="utf-8"),
            lambda repo, state, data: json.loads((repo / ".codex-orchestrator" / "state.json").read_text(encoding="utf-8"))[
                "state_path"
            ]
            == state["state_path"],
        ),
        (
            "missing-context-health-timestamp",
            lambda repo, state: state["context_health"].update({"last_checked_at": None}),
            lambda repo, state, data: state["context_health"]["last_checked_at"] == state["timestamps"]["updated_at"],
        ),
        (
            "missing-event-journal-path",
            lambda repo, state: state.pop("event_journal_path"),
            lambda repo, state, data: state["event_journal_path"] == f".codex-orchestrator/runs/{RUN_ID}/events.jsonl",
        ),
        (
            "stale-last-event-seq",
            lambda repo, state: state.update({"last_event_seq": 0}),
            lambda repo, state, data: state["last_event_seq"] >= 1,
        ),
    ]

    for name, mutate, assertion in repair_cases:
        ok, failure = repair_case(name, mutate, assertion)
        checks[f"{name}_repairs"] = ok
        if not ok:
            failures.append(failure)

    block_cases = [
        (
            "finished-with-open-carried-acceptance",
            lambda repo, state: state["tasks"]["task_0"].update(
                {
                    "carried_acceptance": {
                        "status": "open",
                        "metric": "bundle size",
                        "baseline_value": "1",
                        "current_value": "2",
                        "reason": "pending later task",
                        "depends_on_task": "task_1",
                        "next_action": "resolve metric",
                    }
                }
            ),
            "0" * 64,
        ),
        (
            "completed-task-missing-unit-manifest",
            lambda repo, state: state["tasks"]["task_0"].pop("unit_manifest"),
            "0" * 64,
        ),
        (
            "context-basis-hash-mismatch",
            lambda repo, state: None,
            "1" * 64,
        ),
    ]

    for name, mutate, context_hash in block_cases:
        ok, failure = blocking_case(name, mutate, context_hash=context_hash)
        checks[f"{name}_blocks"] = ok
        if not ok:
            failures.append(failure)

    payload_out = {"passed": not failures, "checks": checks, "failures": failures}
    print(json.dumps(payload_out, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
