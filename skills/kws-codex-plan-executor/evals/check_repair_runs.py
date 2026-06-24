#!/usr/bin/env python3
"""Deterministic checks for conservative CPE run repair."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "repair_runs.py"


def iso(index: int) -> str:
    return f"2026-06-23T00:00:{index:02d}Z"


def base_state(
    codex_home: Path,
    run_id: str,
    *,
    outcome: str | None = None,
    create_worktree: bool = True,
) -> dict:
    run_dir = codex_home / "orchestrator" / run_id
    worktree = codex_home / "worktrees" / run_id
    if create_worktree:
        worktree.mkdir(parents=True, exist_ok=True)
    return {
        "schema_version": "1",
        "run_id": run_id,
        "mode": "interactive",
        "workspace": str(worktree),
        "plan": "docs/plan.md",
        "branch": f"codex/{run_id}",
        "worktree": str(worktree),
        "execution_worktree": str(worktree),
        "run_dir": str(run_dir),
        "state_path": str(run_dir / "state.json"),
        "context_snapshot_path": str(run_dir / "context.json"),
        "context_basis_hash": "0" * 64,
        "spec_manifest_path": str(run_dir / "spec_manifest.json"),
        "task_packet_dir": str(run_dir / "task_packets"),
        "current_task_packet_path": str(run_dir / "task_packets" / "task_0.json"),
        "decisions_register": [],
        "preflight_warnings": [],
        "last_completed_task": None,
        "last_completed_at": None,
        "compaction": {"points": [], "last_compaction_after_task": None, "context_drop_count": 0},
        "current_task": "task_0",
        "current_phase": "task_loop",
        "lifecycle_outcome": outcome,
        "handoff_reason": "" if outcome is None else "Run ended by fixture.",
        "completion_audit": None,
        "subagents_requested": False,
        "subagent_runs": [],
        "tasks": {
            "task_0": {
                "status": "in_progress",
                "risk": "low",
                "files_declared": ["docs/example.md"],
                "contract": {
                    "scope": "fixture",
                    "files_to_inspect": ["docs/plan.md"],
                    "allowed_edits": ["docs/example.md"],
                    "forbidden_edits": [".codex/**"],
                    "acceptance_command_or_honest_substitute": "python3 evals/check_repair_runs.py",
                },
                "review_retries": 0,
                "verifier_retries": 0,
            }
        },
        "risk_levels": {},
        "review_issue_keys": [],
        "verification": [],
        "cache_strategy": {
            "mode": "interactive-default",
            "stable_prefix_policy": "static-first-hot-tail",
            "provider_cache_control": "unavailable",
            "prompt_audit_version": "1",
        },
        "cache_observations": [],
        "prompt_audit": None,
        "graphify_audit": None,
        "dispatch_decisions": [],
        "session_owned_resources": [],
        "last_checkpoint": None,
        "timestamps": {"started_at": iso(0), "updated_at": iso(1), "completed_at": None},
        "context_health": {
            "status": "yellow",
            "last_checked_at": iso(1),
            "next_action": "Continue task_0.",
            "open_questions": [],
            "known_assumptions": [],
            "handoff_ready": False,
            "context_snapshot_present": True,
            "context_basis_hash_recorded": True,
            "active_task_contract_present": True,
        },
    }


def write_state(
    codex_home: Path,
    run_id: str,
    *,
    outcome: str | None = None,
    create_worktree: bool = True,
    existing_blocker: bool = False,
    schema_drift: bool = False,
) -> Path:
    state = base_state(codex_home, run_id, outcome=outcome, create_worktree=create_worktree)
    run_dir = codex_home / "orchestrator" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "task_packets").mkdir(parents=True, exist_ok=True)
    if existing_blocker:
        state["current_blocker"] = {
            "category": "plan_contract_gap",
            "summary": "Existing operator blocker.",
            "recoverable": True,
            "next_action_kind": "operator_decision",
        }
    if outcome == "finished":
        state["agentlens_orchestration_run"] = "agentlens-run-123"
        state["current_phase"] = "complete"
        state["handoff_reason"] = ""
        state["completion_audit"] = {
            "passed": True,
            "prompt_to_artifact_checklist": ["fixture complete"],
            "verification_evidence": ["fixture evidence"],
            "residual_risk": [],
        }
        state["run_quality"] = {
            "schema_version": "1",
            "validation_status": "passed",
            "terminal_state": "finished",
            "stale": False,
            "workspace_matches_execution_worktree": True,
            "score": 90,
            "grade": "green",
            "schema_drift": [],
            "open_followups": [],
            "readiness": {"task_count": 1, "fixable_issue_count": 0, "blocking_issue_count": 0},
            "dispatch_consistency": {"mismatch_count": 0, "override_count": 0},
            "context_quality": {"full_spec_fallback_count": 0},
            "verification_quality": {"completion_audit_passed": True, "verification_evidence_count": 1},
            "recommendations": [],
            "summary": "Fixture run finished.",
        }
        state["tasks"]["task_0"]["status"] = "completed"
        state["tasks"]["task_0"]["unit_manifest"] = {
            "unit_type": "execute-task",
            "context_mode": "focused",
            "tool_policy": "implementation",
            "artifact_policy": "inline-summary",
            "required_skills": [],
            "allowed_write_globs": ["docs/example.md"],
            "forbidden_write_globs": [".codex/**"],
            "max_context_chars": 1000,
        }
        state["tasks"]["task_0"]["timing"] = {
            "started": iso(0),
            "completed": iso(2),
            "verified": iso(2),
        }
        state["timestamps"]["completed_at"] = iso(2)
        state["context_health"]["handoff_ready"] = True
        state["context_health"]["next_action"] = "No action."
    if schema_drift:
        state.pop("tasks")
    state_path = run_dir / "state.json"
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (run_dir / "context.json").write_text(json.dumps({"context_budget": {"status": "green"}}), encoding="utf-8")
    old_time = time.time() - 7200
    os.utime(state_path, (old_time, old_time))
    return state_path


def run_repair(codex_home: Path, *extra: str) -> tuple[subprocess.CompletedProcess[str], dict]:
    output = codex_home / "repair-plan.json"
    cmd = [
        sys.executable,
        str(SCRIPT),
        "--codex-home",
        str(codex_home),
        "--recent",
        "20",
        "--stale-hours",
        "0",
        "--output",
        str(output),
        *extra,
    ]
    result = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    data = json.loads(output.read_text(encoding="utf-8")) if output.is_file() else {}
    return result, data


def run_repair_jsonl(codex_home: Path, *extra: str) -> tuple[subprocess.CompletedProcess[str], list[dict]]:
    output = codex_home / "repair-plan.jsonl"
    cmd = [
        sys.executable,
        str(SCRIPT),
        "--codex-home",
        str(codex_home),
        "--recent",
        "20",
        "--stale-hours",
        "0",
        "--jsonl",
        "--output",
        str(output),
        *extra,
    ]
    result = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines() if line.strip()] if output.is_file() else []
    return result, rows


def run_repair_stdout(codex_home: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    cmd = [
        sys.executable,
        str(SCRIPT),
        "--codex-home",
        str(codex_home),
        "--recent",
        "20",
        "--stale-hours",
        "0",
        *extra,
    ]
    return subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def main() -> int:
    failures: list[str] = []
    checks: dict[str, bool] = {}

    with tempfile.TemporaryDirectory(prefix="cpe-repair-") as temp:
        home = Path(temp) / ".codex"
        state_path = write_state(home, "stale-missing", create_worktree=False)
        before = state_path.read_text(encoding="utf-8")
        result, data = run_repair(home)
        candidate = (data.get("candidates") or [{}])[0]
        checks["dry_run_stale_missing_worktree"] = (
            result.returncode == 0
            and data.get("dry_run") is True
            and data.get("summary", {}).get("candidate_count") == 1
            and candidate.get("recommended_action") == "mark-blocked-stale"
            and candidate.get("apply_safe") is True
            and "stale_non_terminal_run" in candidate.get("detected_followups", [])
            and state_path.read_text(encoding="utf-8") == before
        )
        if not checks["dry_run_stale_missing_worktree"]:
            failures.append("dry-run should report one apply-safe stale missing-worktree candidate without mutating state")

    with tempfile.TemporaryDirectory(prefix="cpe-repair-") as temp:
        home = Path(temp) / ".codex"
        state_path = write_state(home, "apply-stale", create_worktree=False)
        result, _ = run_repair(home, "--run-id", "apply-stale", "--action", "mark-blocked-stale", "--apply")
        repaired = json.loads(state_path.read_text(encoding="utf-8"))
        checks["apply_mark_blocked_stale"] = (
            result.returncode == 0
            and repaired.get("lifecycle_outcome") == "blocked"
            and repaired.get("current_phase") == "recover"
            and repaired.get("current_blocker", {}).get("category") == "state_integrity_drift"
            and repaired.get("current_blocker", {}).get("recoverable") is True
            and repaired.get("context_health", {}).get("handoff_ready") is True
            and repaired.get("timestamps", {}).get("completed_at") is not None
        )
        if not checks["apply_mark_blocked_stale"]:
            failures.append("apply should mark one stale missing-worktree run as blocked and handoff-ready")

    with tempfile.TemporaryDirectory(prefix="cpe-repair-") as temp:
        home = Path(temp) / ".codex"
        write_state(home, "finished-cleaned", outcome="finished", create_worktree=False)
        result, data = run_repair(home, "--run-id", "finished-cleaned", "--action", "mark-blocked-stale", "--apply")
        candidate = (data.get("candidates") or [{}])[0]
        checks["finished_missing_worktree_not_applied"] = (
            result.returncode != 0
            and candidate.get("recommended_action") == "acknowledge-cleaned-worktree"
            and candidate.get("apply_safe") is False
        )
        if not checks["finished_missing_worktree_not_applied"]:
            failures.append("finished missing-worktree runs should be reported but never marked blocked")

    with tempfile.TemporaryDirectory(prefix="cpe-repair-") as temp:
        home = Path(temp) / ".codex"
        state_path = write_state(home, "schema-drift", create_worktree=False, schema_drift=True)
        before = state_path.read_text(encoding="utf-8")
        result, data = run_repair(home)
        candidate = (data.get("candidates") or [{}])[0]
        checks["schema_drift_blocks_repair"] = (
            result.returncode == 0
            and candidate.get("recommended_action") == "manual-review-required"
            and candidate.get("apply_safe") is False
            and "state_schema_drift" in candidate.get("detected_followups", [])
            and state_path.read_text(encoding="utf-8") == before
        )
        if not checks["schema_drift_blocks_repair"]:
            failures.append("schema drift should force manual review and no mutation")

    with tempfile.TemporaryDirectory(prefix="cpe-repair-") as temp:
        home = Path(temp) / ".codex"
        state_path = write_state(home, "existing-blocker", create_worktree=False, existing_blocker=True)
        before = state_path.read_text(encoding="utf-8")
        result, data = run_repair(home)
        candidate = (data.get("candidates") or [{}])[0]
        checks["existing_blocker_blocks_overwrite"] = (
            result.returncode == 0
            and candidate.get("recommended_action") == "manual-review-required"
            and candidate.get("apply_safe") is False
            and "existing current_blocker" in candidate.get("reason", "")
            and state_path.read_text(encoding="utf-8") == before
        )
        if not checks["existing_blocker_blocks_overwrite"]:
            failures.append("existing current_blocker should not be overwritten")

    with tempfile.TemporaryDirectory(prefix="cpe-repair-") as temp:
        home = Path(temp) / ".codex"
        state_path = write_state(home, "unsafe-path", create_worktree=False)
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        payload["state_path"] = str(home / "outside" / "unsafe-path" / "state.json")
        state_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        result, _ = run_repair(home, "--run-id", "unsafe-path", "--action", "mark-blocked-stale", "--apply")
        current = json.loads(state_path.read_text(encoding="utf-8"))
        checks["unsafe_state_path_blocks_apply"] = result.returncode != 0 and current.get("lifecycle_outcome") is None
        if not checks["unsafe_state_path_blocks_apply"]:
            failures.append("unsafe state_path invariant should block apply")

    with tempfile.TemporaryDirectory(prefix="cpe-repair-") as temp:
        home = Path(temp) / ".codex"
        write_state(home, "active-worktree", create_worktree=True)
        result, data = run_repair(home, "--stale-hours", "24")
        checks["no_candidates"] = (
            result.returncode == 0
            and data.get("candidates") == []
            and data.get("summary", {}).get("candidate_count") == 0
            and data.get("summary", {}).get("apply_safe_count") == 0
        )
        if not checks["no_candidates"]:
            failures.append("clean active non-stale runs should produce an empty repair plan")

    with tempfile.TemporaryDirectory(prefix="cpe-repair-") as temp:
        home = Path(temp) / ".codex"
        write_state(home, "jsonl-one", create_worktree=False)
        write_state(home, "jsonl-two", create_worktree=False, existing_blocker=True)
        result, rows = run_repair_jsonl(home)
        checks["jsonl_output"] = (
            result.returncode == 0
            and len(rows) == 2
            and {row.get("run_id") for row in rows} == {"jsonl-one", "jsonl-two"}
        )
        if not checks["jsonl_output"]:
            failures.append("jsonl output should emit one valid JSON object per candidate line")

    with tempfile.TemporaryDirectory(prefix="cpe-repair-") as temp:
        home = Path(temp) / ".codex"
        write_state(home, "jsonl-apply", create_worktree=False)
        result = run_repair_stdout(home, "--jsonl", "--run-id", "jsonl-apply", "--action", "mark-blocked-stale", "--apply")
        parsed_stdout = []
        parse_error = None
        for line in result.stdout.splitlines():
            if not line.strip():
                continue
            try:
                parsed_stdout.append(json.loads(line))
            except json.JSONDecodeError as exc:
                parse_error = str(exc)
                break
        checks["jsonl_apply_stdout_parseable"] = (
            result.returncode == 0
            and parse_error is None
            and len(parsed_stdout) == 1
            and parsed_stdout[0].get("run_id") == "jsonl-apply"
        )
        if not checks["jsonl_apply_stdout_parseable"]:
            failures.append("jsonl apply stdout should contain only JSON objects, with human summary off stdout")

    payload = {"passed": not failures, "checks": checks, "failures": failures}
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
