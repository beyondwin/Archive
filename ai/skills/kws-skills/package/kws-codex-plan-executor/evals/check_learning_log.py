#!/usr/bin/env python3
"""Deterministic checks for append_learning_event.py."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


def base_event() -> dict:
    return {
        "schema_version": "1",
        "skill": "kws-codex-plan-executor",
        "skill_version": "1.3.1",
        "mode": "interactive",
        "event_type": "verification_failure",
        "severity": "medium",
        "repo": {"name": "Archive", "remote_hash": None, "branch": "codex/example"},
        "execution": {
            "plan_path": "docs/superpowers/plans/example.md",
            "task_id": "task_2",
            "phase": "verification",
            "state_path": ".codex-orchestrator/state.json",
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


def run_helper(
    script: Path, event: dict, log_path: Path, repo_root: Path, *extra: str
) -> subprocess.CompletedProcess[str]:
    event_path = repo_root / "event.json"
    event_path.write_text(json.dumps(event, ensure_ascii=False), encoding="utf-8")
    return subprocess.run(
        [
            sys.executable,
            str(script),
            "--event-json",
            str(event_path),
            "--log-path",
            str(log_path),
            "--repo-root",
            str(repo_root),
            *extra,
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def main() -> int:
    script = Path(__file__).resolve().parents[1] / "scripts" / "append_learning_event.py"
    checks: dict[str, bool] = {}
    failures: list[str] = []

    with tempfile.TemporaryDirectory(prefix="codex-learning-log-") as temp:
        repo_root = Path(temp) / "repo"
        repo_root.mkdir()
        log_path = Path(temp) / "events.jsonl"

        valid = run_helper(script, base_event(), log_path, repo_root)
        checks["valid_event_appends"] = (
            valid.returncode == 0 and log_path.is_file() and len(log_path.read_text().splitlines()) == 1
        )
        if not checks["valid_event_appends"]:
            failures.append("valid event should append one JSONL line")

        appended = json.loads(log_path.read_text(encoding="utf-8").splitlines()[0]) if log_path.is_file() else {}
        checks["event_id_added"] = isinstance(appended.get("event_id"), str) and len(appended.get("event_id", "")) >= 12
        if not checks["event_id_added"]:
            failures.append("appended event should include event_id")

        dry_log = Path(temp) / "dry.jsonl"
        dry = run_helper(script, base_event(), dry_log, repo_root, "--dry-run")
        checks["dry_run_no_write"] = dry.returncode == 0 and not dry_log.exists() and '"event_id"' in dry.stdout
        if not checks["dry_run_no_write"]:
            failures.append("dry-run should validate and print sanitized event without writing")

        missing = base_event()
        del missing["summary"]
        missing_result = run_helper(script, missing, Path(temp) / "missing.jsonl", repo_root)
        checks["missing_required_field_fails"] = missing_result.returncode != 0 and "summary" in (
            missing_result.stderr + missing_result.stdout
        )
        if not checks["missing_required_field_fails"]:
            failures.append("missing summary should fail")

        invalid_mode = base_event()
        invalid_mode["mode"] = "prompt"
        invalid_mode_result = run_helper(script, invalid_mode, Path(temp) / "invalid-mode.jsonl", repo_root)
        checks["invalid_mode_fails"] = invalid_mode_result.returncode != 0 and "mode" in (
            invalid_mode_result.stderr + invalid_mode_result.stdout
        )
        if not checks["invalid_mode_fails"]:
            failures.append("prompt mode should fail for learning events")

        home_path = base_event()
        home_path["context"]["evidence"] = [{"kind": "relative_path", "value": str(Path.home() / "secret.txt")}]
        home_result = run_helper(script, home_path, Path(temp) / "home.jsonl", repo_root)
        checks["home_path_rejected"] = home_result.returncode != 0 and "home path" in (
            home_result.stderr + home_result.stdout
        )
        if not checks["home_path_rejected"]:
            failures.append("absolute home path should be rejected")

        secret = base_event()
        secret["context"]["evidence"] = [{"kind": "excerpt", "value": "Authorization: Bearer abc123"}]
        secret_result = run_helper(script, secret, Path(temp) / "secret.jsonl", repo_root)
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
