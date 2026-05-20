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


def _write_dependent_plan(repo: Path) -> tuple[Path, Path]:
    spec = repo / "spec.md"
    plan = repo / "plan.md"
    spec.write_text(
        "# Spec\n\n"
        "## A\n\n"
        "Task 1 creates the accepted upstream file.\n\n"
        "## B\n\n"
        "Task 2 must start from a checkpoint that already contains task 1's file.\n",
        encoding="utf-8",
    )
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
        "  - {path: src/upstream.py, mode: owned}\n"
        "acceptance_commands: [python -m pytest]\n"
        "required_skills: [test-driven-development]\n"
        "```\n"
        "Create the upstream file.\n\n"
        "## Task 2: B\n\n"
        "```yaml agentrunway-task\n"
        "task_id: task_002\n"
        "title: B\n"
        "risk: low\n"
        "phase: implementation\n"
        "dependencies: [task_001]\n"
        "spec_refs: [S1.2]\n"
        "file_claims:\n"
        "  - {path: src/downstream.py, mode: owned}\n"
        "acceptance_commands: [python -m pytest]\n"
        "required_skills: [test-driven-development]\n"
        "```\n"
        "Create the downstream file after observing task 1's accepted file.\n",
        encoding="utf-8",
    )
    return plan, spec


def test_dependent_task_starts_from_checkpoint_with_dependency_commit(
    git_repo: Path,
    isolated_home: Path,
) -> None:
    plan, spec = _write_dependent_plan(git_repo)
    env = os.environ.copy()
    env["PATH"] = f"{FAKE_BIN}{os.pathsep}{env['PATH']}"
    env["AGENTRUNWAY_FAKE_TARGET_MAP"] = "task_001=src/upstream.py;task_002=src/downstream.py"
    env["AGENTRUNWAY_FAKE_REQUIRED_FILE_MAP"] = "task_002=src/upstream.py"

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
    assert payload["status"] == "finished"
    main = Path(payload["main_worktree"])
    assert (main / "src" / "upstream.py").read_text(encoding="utf-8") == "VALUE = 'codex'\n"
    assert (main / "src" / "downstream.py").read_text(encoding="utf-8") == "VALUE = 'codex'\n"

    conn = sqlite3.connect(payload["state_db"])
    conn.row_factory = sqlite3.Row
    checkpoints = conn.execute(
        "SELECT checkpoint_id, parent_checkpoint_id, reason FROM checkpoints ORDER BY checkpoint_id"
    ).fetchall()
    candidates = conn.execute(
        "SELECT task_id, status, changed_files_json FROM merge_queue ORDER BY id"
    ).fetchall()
    workers = conn.execute(
        "SELECT task_id, role, state FROM workers WHERE role = 'implementer' ORDER BY worker_id"
    ).fetchall()

    assert [(row["checkpoint_id"], row["parent_checkpoint_id"], row["reason"]) for row in checkpoints] == [
        ("cp-000", None, "initial"),
        ("cp-001", "cp-000", "merged:task_001"),
        ("cp-002", "cp-001", "merged:task_002"),
    ]
    assert [(row["task_id"], row["status"], json.loads(row["changed_files_json"])) for row in candidates] == [
        ("task_001", "merged", ["src/upstream.py"]),
        ("task_002", "merged", ["src/downstream.py"]),
    ]
    assert [(row["task_id"], row["role"], row["state"]) for row in workers] == [
        ("task_001", "implementer", "merged"),
        ("task_002", "implementer", "merged"),
    ]


def test_local_fake_success_records_merge_checkpoints_before_releasing_dependencies(
    git_repo: Path, isolated_home: Path
) -> None:
    plan, spec = _write_dependent_plan(git_repo)

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
    conn = sqlite3.connect(payload["state_db"])
    conn.row_factory = sqlite3.Row
    checkpoints = conn.execute("SELECT reason FROM checkpoints ORDER BY checkpoint_id").fetchall()

    assert payload["status"] == "finished"
    assert [row["reason"] for row in checkpoints] == ["initial", "merged:task_001", "merged:task_002"]


def test_safe_independent_tasks_share_checkpoint_scheduler_wave(git_repo: Path, isolated_home: Path) -> None:
    spec = git_repo / "spec.md"
    plan = git_repo / "plan.md"
    spec.write_text("# Spec\n\n## A\n\nA.\n\n## B\n\nB.\n", encoding="utf-8")
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
        "```\n"
        "Create A.\n\n"
        "## Task 2: B\n\n"
        "```yaml agentrunway-task\n"
        "task_id: task_002\n"
        "title: B\n"
        "risk: low\n"
        "phase: implementation\n"
        "dependencies: []\n"
        "spec_refs: [S1.2]\n"
        "file_claims:\n"
        "  - {path: src/b.py, mode: owned}\n"
        "acceptance_commands: [python -m pytest]\n"
        "required_skills: [test-driven-development]\n"
        "```\n"
        "Create B.\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PATH"] = f"{FAKE_BIN}{os.pathsep}{env['PATH']}"
    env["AGENTRUNWAY_FAKE_TARGET_MAP"] = "task_001=src/a.py;task_002=src/b.py"

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "run", "--plan", str(plan), "--spec", str(spec), "--adapter", "codex"],
        cwd=git_repo,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    conn = sqlite3.connect(payload["state_db"])
    conn.row_factory = sqlite3.Row
    checkpoints = conn.execute("SELECT reason FROM checkpoints ORDER BY checkpoint_id").fetchall()
    assert payload["status"] == "finished"
    assert [row["reason"] for row in checkpoints] == ["initial", "merged:task_001", "merged:task_002"]
