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
    assert (main / "src" / "codex_worker.py").read_text(encoding="utf-8") == "VALUE = 'codex'\n"

    conn = sqlite3.connect(payload["state_db"])
    conn.row_factory = sqlite3.Row
    candidate = dict(conn.execute("SELECT * FROM merge_queue").fetchone())
    rows = conn.execute("SELECT role, state FROM workers ORDER BY worker_id").fetchall()
    states = [(row["role"], row["state"]) for row in rows]
    assert states == [
        ("implementer", "merged"),
        ("reviewer", "validated"),
        ("verifier", "validated"),
    ]
    assert candidate["status"] == "merged"
    assert json.loads(candidate["changed_files_json"]) == ["src/codex_worker.py"]


def test_claude_fake_implementer_uses_claude_default_profile(git_repo: Path, isolated_home: Path) -> None:
    plan, spec = _write_plan(git_repo, path="src/claude_worker.py")
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
            "claude",
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
    assert (main / "src" / "claude_worker.py").read_text(encoding="utf-8") == "VALUE = 'claude'\n"

    conn = sqlite3.connect(payload["state_db"])
    conn.row_factory = sqlite3.Row
    candidate = dict(conn.execute("SELECT * FROM merge_queue").fetchone())
    rows = conn.execute("SELECT role, runtime, model, state FROM workers ORDER BY worker_id").fetchall()
    states = [(row["role"], row["state"]) for row in rows]
    assert states == [
        ("implementer", "merged"),
        ("reviewer", "validated"),
        ("verifier", "validated"),
    ]
    assert candidate["status"] == "merged"
    assert rows[0]["runtime"] == "claude"
    assert rows[0]["model"] == "opus"


def test_review_changes_requested_redispatches_implementer_once(git_repo: Path, isolated_home: Path) -> None:
    plan, spec = _write_plan(git_repo, path="src/review_retry.py")
    env = os.environ.copy()
    env["PATH"] = f"{FAKE_BIN}{os.pathsep}{env['PATH']}"
    env["AGENTRUNWAY_FAKE_TARGET"] = "src/review_retry.py"
    env["AGENTRUNWAY_FAKE_REVIEW_SEQUENCE"] = "changes_requested,approved"
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
    workers = conn.execute("SELECT worker_id, role, state FROM workers ORDER BY worker_id").fetchall()
    candidates = conn.execute("SELECT worker_id, status FROM merge_queue ORDER BY id").fetchall()
    prompts = sorted(Path(payload["run_dir"]).glob("prompts/*.implementer.prompt.txt"))

    assert (Path(payload["main_worktree"]) / "src" / "review_retry.py").read_text(encoding="utf-8") == "VALUE = 'codex'\n"
    assert [(row["worker_id"], row["role"], row["state"]) for row in workers] == [
        ("task_001-implementer-001", "implementer", "validated"),
        ("task_001-implementer-002", "implementer", "merged"),
        ("task_001-reviewer-001", "reviewer", "validated"),
        ("task_001-reviewer-002", "reviewer", "validated"),
        ("task_001-verifier-001", "verifier", "validated"),
    ]
    assert [(row["worker_id"], row["status"]) for row in candidates] == [
        ("task_001-implementer-001", "changes_requested"),
        ("task_001-implementer-002", "merged"),
    ]
    assert any("changes_requested" in path.read_text(encoding="utf-8") for path in prompts)


def test_verifier_failed_redispatches_implementer_once(git_repo: Path, isolated_home: Path) -> None:
    plan, spec = _write_plan(git_repo, path="src/verify_retry.py")
    env = os.environ.copy()
    env["PATH"] = f"{FAKE_BIN}{os.pathsep}{env['PATH']}"
    env["AGENTRUNWAY_FAKE_TARGET"] = "src/verify_retry.py"
    env["AGENTRUNWAY_FAKE_VERIFY_SEQUENCE"] = "failed,passed"
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
    workers = conn.execute("SELECT worker_id, role, state FROM workers ORDER BY worker_id").fetchall()
    candidates = conn.execute("SELECT worker_id, status FROM merge_queue ORDER BY id").fetchall()
    prompts = sorted(Path(payload["run_dir"]).glob("prompts/*.implementer.prompt.txt"))

    assert (Path(payload["main_worktree"]) / "src" / "verify_retry.py").read_text(encoding="utf-8") == "VALUE = 'codex'\n"
    assert [(row["worker_id"], row["role"], row["state"]) for row in workers] == [
        ("task_001-implementer-001", "implementer", "validated"),
        ("task_001-implementer-002", "implementer", "merged"),
        ("task_001-reviewer-001", "reviewer", "validated"),
        ("task_001-reviewer-002", "reviewer", "validated"),
        ("task_001-verifier-001", "verifier", "validated"),
        ("task_001-verifier-002", "verifier", "validated"),
    ]
    assert [(row["worker_id"], row["status"]) for row in candidates] == [
        ("task_001-implementer-001", "verification_failed"),
        ("task_001-implementer-002", "merged"),
    ]
    assert any("verification" in path.read_text(encoding="utf-8") and "failed" in path.read_text(encoding="utf-8") for path in prompts)
