from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "agentrunway.py"
FAKE_BIN = ROOT / "evals" / "fixtures" / "fake-bin"


def _write_plan(repo: Path, path: str = "src/codex_worker.py") -> tuple[Path, Path]:
    spec = repo / "spec.md"
    plan = repo / "plan.md"
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
        f"  - {{path: {path}, mode: owned}}\n"
        "acceptance_commands: [python -m pytest]\n"
        "required_skills: [test-driven-development]\n"
        "```\n"
        "Add worker file.\n",
        encoding="utf-8",
    )
    return plan, spec


def test_codex_fake_implementer_reaches_validated_candidate(git_repo: Path, isolated_home: Path) -> None:
    plan, spec = _write_plan(git_repo)
    env = os.environ.copy()
    env["PATH"] = f"{FAKE_BIN}{os.pathsep}{env['PATH']}"
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
            "--skip-review",
            "--skip-verify",
        ],
        cwd=git_repo,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout)
    assert payload["status"] == "finished"
    assert Path(payload["main_worktree"]).exists()

    conn = sqlite3.connect(payload["state_db"])
    conn.row_factory = sqlite3.Row
    candidate = dict(conn.execute("SELECT * FROM merge_queue").fetchone())
    worker = dict(conn.execute("SELECT * FROM workers").fetchone())
    assert candidate["status"] == "merge_ready"
    assert json.loads(candidate["changed_files_json"]) == ["src/codex_worker.py"]
    assert worker["state"] == "validated"
