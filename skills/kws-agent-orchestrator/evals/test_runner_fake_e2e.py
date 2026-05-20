from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "kao.py"


def test_fake_adapter_execution_finishes_and_creates_main_worktree(git_repo: Path, isolated_home: Path) -> None:
    plan = git_repo / "plan.md"
    spec = git_repo / "spec.md"
    spec.write_text("# Spec\n\n## A\n\nAdd A.\n", encoding="utf-8")
    plan.write_text(
        "## Task 1: A\n\n"
        "```yaml kao-task\n"
        "task_id: task_001\n"
        "title: A\n"
        "risk: low\n"
        "phase: implementation\n"
        "dependencies: []\n"
        "spec_refs: [S1.1]\n"
        "file_claims:\n"
        "  - {path: src/a.py, mode: owned}\n"
        "acceptance_commands: [pytest]\n"
        "required_skills: [test-driven-development]\n"
        "```\n"
        "Add A.\n",
        encoding="utf-8",
    )
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
            "local",
            "--fake-success",
        ],
        cwd=git_repo,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout)
    assert payload["status"] == "finished"
    assert Path(payload["main_worktree"]).exists()
    assert (Path(payload["run_dir"]) / "artifacts" / "task_001" / "worker_result.json").exists()
