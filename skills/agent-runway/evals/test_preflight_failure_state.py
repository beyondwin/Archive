from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "agentrunway.py"


def _write_spec(repo: Path) -> Path:
    spec = repo / "spec.md"
    spec.write_text("# Spec\n\n## A\n\nDetails.\n", encoding="utf-8")
    return spec


def _write_valid_plan(repo: Path) -> Path:
    plan = repo / "plan.md"
    plan.write_text(
        "## Task 1: A\n\n"
        "```yaml agentrunway-task\n"
        "task_id: task_001\n"
        "title: A\n"
        "risk: low\n"
        "phase: implementation\n"
        "dependencies: []\n"
        "spec_refs: [S1.1]\n"
        "file_claims:\n"
        "  - {path: src/a.py, mode: owned}\n"
        "acceptance_commands: [python -m pytest]\n"
        "required_skills: [test-driven-development]\n"
        "```\n",
        encoding="utf-8",
    )
    return plan


def _write_invalid_plan(repo: Path) -> Path:
    plan = repo / "plan.md"
    plan.write_text(
        "## Task 1: Bad\n\n"
        "```yaml agentrunway-task\n"
        "task_id: task_001\n"
        "title: Bad\n"
        "risk: low\n"
        "phase: implementation\n"
        "dependencies: []\n"
        "spec_refs: [S1.1]\n"
        "file_claims:\n"
        "  - {path: graphify-out/GRAPH_REPORT.md, mode: owned}\n"
        "acceptance_commands: [python -m pytest]\n"
        "required_skills: [test-driven-development]\n"
        "```\n",
        encoding="utf-8",
    )
    return plan


def _run_agentrunway(repo: Path, plan: Path, spec: Path, *, run_id: str, adapter: str = "local") -> dict[str, object]:
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "run",
            "--plan",
            str(plan),
            "--spec",
            str(spec),
            "--adapter",
            adapter,
            "--run-id",
            run_id,
        ],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(result.stdout)


def _events_cli(repo: Path, run_id: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "events", "--run", run_id],
        cwd=repo,
        text=True,
        capture_output=True,
    )


def _inspect_cli(repo: Path, run_id: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "inspect", "--run", run_id, "--json"],
        cwd=repo,
        text=True,
        capture_output=True,
    )


def _assert_durable_failure_payload(payload: dict[str, object], repo: Path, expected_status: str, expected_event: str) -> None:
    assert payload["status"] == expected_status
    assert payload["state_db"]
    state_db = Path(str(payload["state_db"]))
    assert state_db.exists()
    assert payload["events_jsonl"]
    assert Path(str(payload["events_jsonl"])).exists()
    artifacts = payload["artifacts"]
    assert isinstance(artifacts, dict)
    assert artifacts["decision_packet"]
    assert Path(str(artifacts["decision_packet"])).exists()

    conn = sqlite3.connect(state_db)
    run_status = conn.execute("SELECT status FROM runs WHERE run_id=?", (payload["run_id"],)).fetchone()[0]
    assert run_status == expected_status
    assert conn.execute("SELECT COUNT(*) FROM decision_packets WHERE run_id=?", (payload["run_id"],)).fetchone()[0] == 1

    events = _events_cli(repo, str(payload["run_id"]))
    assert events.returncode == 0, events.stderr
    event_payload = json.loads(events.stdout)
    assert expected_event in [event["event_type"] for event in event_payload["events"]]

    inspect = _inspect_cli(repo, str(payload["run_id"]))
    assert inspect.returncode == 0, inspect.stderr
    inspect_payload = json.loads(inspect.stdout)
    assert inspect_payload["status"] == expected_status
    assert inspect_payload["failure_class"]
    assert inspect_payload["artifacts"]["decision_packet"] == artifacts["decision_packet"]


def test_lint_failure_writes_state_db_and_events(git_repo: Path, isolated_home: Path) -> None:
    spec = _write_spec(git_repo)
    plan = _write_invalid_plan(git_repo)

    payload = _run_agentrunway(git_repo, plan, spec, run_id="lint-failure-test")

    _assert_durable_failure_payload(payload, git_repo, "plan_lint_failed", "agentrunway.plan_lint_failed")


def test_preflight_failure_writes_state_db_and_events(git_repo: Path, isolated_home: Path) -> None:
    spec = _write_spec(git_repo)
    plan = _write_valid_plan(git_repo)

    payload = _run_agentrunway(git_repo, plan, spec, run_id="preflight-failure-test", adapter="badapter")

    _assert_durable_failure_payload(payload, git_repo, "preflight_failed", "agentrunway.preflight_failed")
