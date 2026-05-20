from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from agentrunway.db import AgentRunwayDb
from agentrunway.run_summary import build_run_summary


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "agentrunway.py"
FAKE_BIN = ROOT / "evals" / "fixtures" / "fake-bin"


def test_db_records_worker_start_and_terminal_end_once(tmp_path: Path) -> None:
    db = AgentRunwayDb.open(tmp_path / "state.sqlite")
    db.create_worker_attempt(
        worker_id="task_001-implementer-001",
        task_id="task_001",
        role="implementer",
        runtime="codex",
        model="gpt-5.5",
        reasoning_effort="xhigh",
        attempt=1,
        worktree_path="/tmp/worker",
        branch="agentrunway/run/task_001-implementer-001",
        state="worktree_created",
        handle_json={},
    )

    db.mark_worker_started("task_001-implementer-001")
    db.mark_worker_ended("task_001-implementer-001", "result_collected")
    ended_at = db.get_worker("task_001-implementer-001")["ended_at"]
    db.set_worker_state("task_001-implementer-001", "merged")

    row = db.get_worker("task_001-implementer-001")
    assert row["started_at"]
    assert row["ended_at"] == ended_at
    assert row["state"] == "merged"


def test_fake_production_run_records_worker_timing_and_summary(git_repo: Path, isolated_home: Path) -> None:
    spec = git_repo / "spec.md"
    plan = git_repo / "plan.md"
    spec.write_text("# Spec\n\n## A\n\nAdd worker file.\n", encoding="utf-8")
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
        "  - {path: src/timing.py, mode: owned}\n"
        "acceptance_commands: [python -m pytest]\n"
        "required_skills: [test-driven-development]\n"
        "```\n"
        "Add worker file.\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PATH"] = f"{FAKE_BIN}{os.pathsep}{env['PATH']}"
    env["AGENTRUNWAY_FAKE_TARGET"] = "src/timing.py"

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
            "codex",
        ],
        cwd=git_repo,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout)
    conn = sqlite3.connect(payload["state_db"])
    conn.row_factory = sqlite3.Row
    workers = conn.execute("SELECT worker_id, started_at, ended_at FROM workers ORDER BY worker_id").fetchall()
    db = AgentRunwayDb.open(Path(payload["state_db"]))
    summary = build_run_summary(run_json=payload, db=db)

    assert workers
    assert all(row["started_at"] for row in workers)
    assert all(row["ended_at"] for row in workers)
    assert {item["worker_id"] for item in summary["worker_durations"]} == {row["worker_id"] for row in workers}
