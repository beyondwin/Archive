from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "kao.py"


def test_kao_run_planning_only_creates_state(git_repo: Path, isolated_home: Path) -> None:
    plan = git_repo / "plan.md"
    spec = git_repo / "spec.md"
    spec.write_text("# Spec\n\n## Docs\n\nWrite usage.\n", encoding="utf-8")
    plan.write_text(
        "## Task 1: Docs\n\n"
        "```yaml kao-task\n"
        "task_id: task_001\n"
        "title: Docs\n"
        "risk: low\n"
        "phase: docs\n"
        "dependencies: []\n"
        "spec_refs: [S1.1]\n"
        "file_claims:\n"
        "  - {path: docs/usage.md, mode: owned}\n"
        "acceptance_commands: [pytest]\n"
        "required_skills: [test-driven-development]\n"
        "```\n"
        "Write docs.\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "run", "--plan", str(plan), "--spec", str(spec), "--planning-only"],
        cwd=git_repo,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "planning_only" in result.stdout
    db_path = next(isolated_home.glob("runs/*/*/state.sqlite"))
    conn = sqlite3.connect(db_path)
    assert conn.execute("select count(*) from tasks").fetchone()[0] == 1
