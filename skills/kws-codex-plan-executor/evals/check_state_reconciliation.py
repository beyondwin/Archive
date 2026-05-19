#!/usr/bin/env python3
"""Deterministic checks for reconcile_state.py."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


RUN_ID = "reconcile-plan-20260519-143022"


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


def base_state(home: Path, repo: Path) -> dict:
    run_dir = home / ".codex" / "orchestrator" / RUN_ID
    return {
        "schema_version": "1",
        "run_id": RUN_ID,
        "mode": "interactive",
        "workspace": str(repo),
        "plan": str(repo / "plan.md"),
        "branch": f"codex/{RUN_ID}",
        "worktree": str(home / ".codex" / "worktrees" / RUN_ID),
        "run_dir": str(run_dir),
        "state_path": str(run_dir / "state.json"),
        "context_snapshot_path": str(run_dir / "context.json"),
        "context_basis_hash": "0" * 64,
        "context_health": {
            "status": "green",
            "last_checked_at": "2026-05-19T14:30:22Z",
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
        "subagents_requested": True,
        "subagent_runs": [],
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
            "started_at": "2026-05-19T14:30:22Z",
            "updated_at": "2026-05-19T14:30:22Z",
            "completed_at": "2026-05-19T14:30:22Z",
        },
    }


def write_run(state: dict, context_hash: str = "0" * 64) -> Path:
    state_path = Path(state["state_path"])
    state_path.parent.mkdir(parents=True, exist_ok=True)
    Path(state["plan"]).write_text("plan\n", encoding="utf-8")
    Path(state["context_snapshot_path"]).write_text(json.dumps({"basis_hash": context_hash}) + "\n", encoding="utf-8")
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
    return any(isinstance(record, dict) and record.get("type") == drift_type for record in data.get("records", []))


def main() -> int:
    script = Path(__file__).resolve().parents[1] / "scripts" / "reconcile_state.py"
    checks: dict[str, bool] = {}
    failures: list[str] = []

    with tempfile.TemporaryDirectory(prefix="codex-reconcile-") as temp:
        root = Path(temp)
        home = root / "codex-home"
        repo = root / "repo"
        repo.mkdir()

        state = base_state(home, repo)
        state["context_health"]["last_checked_at"] = None
        state_path = write_run(state)
        before = state_path.read_text(encoding="utf-8")
        check_result = run_reconcile(script, state_path, repair=False)
        after = state_path.read_text(encoding="utf-8")
        checks["check_does_not_mutate_state_file"] = check_result.returncode == 0 and before == after
        if not checks["check_does_not_mutate_state_file"]:
            failures.append("--check should report drift without modifying state.json")

        result = run_reconcile(script, state_path, repair=True)
        repaired = json.loads(state_path.read_text(encoding="utf-8"))
        checks["missing_context_health_timestamp_repairs"] = (
            result.returncode == 0
            and payload(result).get("passed") is True
            and repaired["context_health"]["last_checked_at"] == repaired["timestamps"]["updated_at"]
        )
        if not checks["missing_context_health_timestamp_repairs"]:
            failures.append("missing context health timestamp should repair")

    block_cases = [
        (
            "finished-with-open-carried-acceptance",
            lambda state: state["tasks"]["task_0"].update(
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
        ("completed-task-missing-unit-manifest", lambda state: state["tasks"]["task_0"].pop("unit_manifest"), "0" * 64),
        ("context-basis-hash-mismatch", lambda state: None, "1" * 64),
    ]

    for name, mutate, context_hash in block_cases:
        with tempfile.TemporaryDirectory(prefix=f"codex-reconcile-{name}-") as temp:
            root = Path(temp)
            home = root / "codex-home"
            repo = root / "repo"
            repo.mkdir()
            state = base_state(home, repo)
            mutate(state)
            state_path = write_run(state, context_hash=context_hash)
            result = run_reconcile(script, state_path, repair=False)
            data = payload(result)
            ok = result.returncode == 1 and data.get("passed") is False and has_record(data, name)
            checks[f"{name}_blocks"] = ok
            if not ok:
                failures.append(f"{name}: rc={result.returncode} stdout={result.stdout!r} stderr={result.stderr!r}")

    payload_out = {"passed": not failures, "checks": checks, "failures": failures}
    print(json.dumps(payload_out, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
