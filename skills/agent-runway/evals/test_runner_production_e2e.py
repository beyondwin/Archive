from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from agentrunway.worktrees import workspace_id


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


def _write_high_risk_plan(repo: Path) -> tuple[Path, Path]:
    spec = repo / "spec.md"
    plan = repo / "plan.md"
    spec.write_text("# Spec\n\n## A\n\nAdd high-risk worker file.\n", encoding="utf-8")
    plan.write_text(
        "## Task 1: A\n\n"
        "```yaml agentrunway-task\n"
        "task_id: task_001\n"
        "title: A\n"
        "risk: high\n"
        "phase: implementation\n"
        "dependencies: []\n"
        "spec_refs: [S1.1]\n"
        "file_claims:\n"
        "  - {path: src/high_risk.py, mode: owned}\n"
        "acceptance_commands: [python -m pytest]\n"
        "required_skills: [test-driven-development]\n"
        "```\n"
        "Add high-risk worker file.\n",
        encoding="utf-8",
    )
    return plan, spec


def _write_safe_wave_plan(repo: Path) -> tuple[Path, Path]:
    spec = repo / "spec.md"
    plan = repo / "plan.md"
    spec.write_text("# Spec\n\n## A\n\nAdd two independent files.\n", encoding="utf-8")
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
        "  - {path: src/safe_a.py, mode: owned}\n"
        "acceptance_commands:\n"
        "  - python -m py_compile src/safe_a.py\n"
        "required_skills: [test-driven-development]\n"
        "```\n"
        "Add first safe file.\n\n"
        "## Task 2: B\n\n"
        "```yaml agentrunway-task\n"
        "task_id: task_002\n"
        "title: B\n"
        "risk: low\n"
        "phase: implementation\n"
        "dependencies: []\n"
        "spec_refs: [S1.1]\n"
        "file_claims:\n"
        "  - {path: src/safe_b.py, mode: owned}\n"
        "acceptance_commands:\n"
        "  - python -m py_compile src/safe_b.py\n"
        "required_skills: [test-driven-development]\n"
        "```\n"
        "Add second safe file.\n",
        encoding="utf-8",
    )
    return plan, spec


def _write_many_safe_wave_plan(repo: Path, count: int) -> tuple[Path, Path]:
    spec = repo / "spec.md"
    plan = repo / "plan.md"
    spec.write_text("# Spec\n\n## A\n\nAdd independent files.\n", encoding="utf-8")
    sections: list[str] = []
    for index in range(1, count + 1):
        task_id = f"task_{index:03d}"
        target = f"src/safe_{index}.py"
        sections.append(
            f"## Task {index}: {task_id}\n\n"
            "```yaml agentrunway-task\n"
            f"task_id: {task_id}\n"
            f"title: {task_id}\n"
            "risk: low\n"
            "phase: implementation\n"
            "dependencies: []\n"
            "spec_refs: [S1.1]\n"
            "file_claims:\n"
            f"  - {{path: {target}, mode: owned}}\n"
            "acceptance_commands:\n"
            f"  - python -m py_compile {target}\n"
            "required_skills: [test-driven-development]\n"
            "```\n"
            f"Add {target}.\n"
        )
    plan.write_text("\n".join(sections), encoding="utf-8")
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


def test_repeated_review_rebase_blocks_after_one_redispatch(git_repo: Path, isolated_home: Path) -> None:
    plan, spec = _write_plan(git_repo, path="src/review_rebase.py")
    env = os.environ.copy()
    env["PATH"] = f"{FAKE_BIN}{os.pathsep}{env['PATH']}"
    env["AGENTRUNWAY_FAKE_TARGET"] = "src/review_rebase.py"
    env["AGENTRUNWAY_FAKE_REVIEW_SEQUENCE"] = "changes_requested,changes_requested"
    env["AGENTRUNWAY_FAKE_REVIEW_FINDING_BODY"] = "prior accepted work changed this base"
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
    decisions = conn.execute("SELECT failure_class FROM decision_packets ORDER BY created_at").fetchall()

    assert payload["status"] == "blocked"
    assert [(row["worker_id"], row["role"], row["state"]) for row in workers] == [
        ("task_001-implementer-001", "implementer", "validated"),
        ("task_001-implementer-002", "implementer", "validated"),
        ("task_001-reviewer-001", "reviewer", "validated"),
        ("task_001-reviewer-002", "reviewer", "validated"),
    ]
    assert [row["failure_class"] for row in decisions][-1] == "needs_rebase"


def test_review_plan_fix_writes_decision_packet(git_repo: Path, isolated_home: Path) -> None:
    plan, spec = _write_plan(git_repo, path="src/review_plan_fix.py")
    env = os.environ.copy()
    env["PATH"] = f"{FAKE_BIN}{os.pathsep}{env['PATH']}"
    env["AGENTRUNWAY_FAKE_TARGET"] = "src/review_plan_fix.py"
    env["AGENTRUNWAY_FAKE_REVIEW_STATUS"] = "changes_requested"
    env["AGENTRUNWAY_FAKE_REVIEW_FINDING_BODY"] = "file claim is missing for src/review_plan_fix.py"
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
    workers = conn.execute("SELECT role FROM workers ORDER BY worker_id").fetchall()
    review_activity = dict(conn.execute("SELECT * FROM activities WHERE activity_type='review'").fetchone())
    decision_packet = dict(conn.execute("SELECT * FROM decision_packets").fetchone())

    assert payload["status"] == "blocked"
    assert [row["role"] for row in workers] == ["implementer", "reviewer"]
    assert review_activity["status"] == "blocked"
    assert review_activity["failure_class"] == "needs_plan_fix"
    assert decision_packet["failure_class"] == "needs_plan_fix"


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


def test_verifier_blocked_does_not_redispatch(git_repo: Path, isolated_home: Path) -> None:
    plan, spec = _write_plan(git_repo, path="src/verify_blocked.py")
    env = os.environ.copy()
    env["PATH"] = f"{FAKE_BIN}{os.pathsep}{env['PATH']}"
    env["AGENTRUNWAY_FAKE_TARGET"] = "src/verify_blocked.py"
    env["AGENTRUNWAY_FAKE_VERIFY_STATUS"] = "blocked"
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
    workers = conn.execute("SELECT role FROM workers ORDER BY worker_id").fetchall()
    events = conn.execute("SELECT event_type, payload_json FROM agentlens_events ORDER BY id").fetchall()
    verification_activity = dict(conn.execute("SELECT * FROM activities WHERE activity_type='verification'").fetchone())
    decision_packet = dict(conn.execute("SELECT * FROM decision_packets").fetchone())
    quality_payloads = [
        json.loads(row["payload_json"])
        for row in events
        if row["event_type"] == "agentrunway.quality_decision"
    ]

    assert payload["status"] == "blocked"
    assert [row["role"] for row in workers] == ["implementer", "reviewer", "verifier"]
    assert quality_payloads[-1]["decision"] == "block"
    assert quality_payloads[-1]["reason"] == "verification_blocked"
    assert verification_activity["status"] == "blocked"
    assert verification_activity["failure_class"] == "needs_infra_fix"
    assert decision_packet["failure_class"] == "needs_infra_fix"


def test_failed_implementer_run_persists_run_json(git_repo: Path, isolated_home: Path) -> None:
    plan, spec = _write_plan(git_repo, path="src/allowed.py")
    env = os.environ.copy()
    env["PATH"] = f"{FAKE_BIN}{os.pathsep}{env['PATH']}"
    env["AGENTRUNWAY_FAKE_TARGET"] = "README.md"
    run_id = "scope-failure-run"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "run",
            "--run-id",
            run_id,
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
        check=False,
    )

    run_json_path = isolated_home / "runs" / workspace_id(git_repo) / run_id / "run.json"
    payload = json.loads(run_json_path.read_text(encoding="utf-8"))

    assert result.returncode != 0
    assert payload["status"] == "failed"
    assert payload["run_id"] == run_id
    assert payload["main_worktree"]


def test_diff_reviewer_uses_no_worktree_and_verifier_keeps_candidate_visibility(
    git_repo: Path, isolated_home: Path
) -> None:
    plan, spec = _write_plan(git_repo, path="src/review_visible.py")
    env = os.environ.copy()
    env["PATH"] = f"{FAKE_BIN}{os.pathsep}{env['PATH']}"
    env["AGENTRUNWAY_FAKE_TARGET"] = "src/review_visible.py"
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
    rows = conn.execute("SELECT role, runtime, worktree_path FROM workers WHERE role IN ('reviewer', 'verifier') ORDER BY role").fetchall()

    assert {row["role"] for row in rows} == {"reviewer", "verifier"}
    reviewer = next(row for row in rows if row["role"] == "reviewer")
    verifier = next(row for row in rows if row["role"] == "verifier")
    assert reviewer["worktree_path"] is None
    assert reviewer["runtime"] == "codex"
    reviewed_file = Path(verifier["worktree_path"]) / "src" / "review_visible.py"
    assert reviewed_file.read_text(encoding="utf-8") == "VALUE = 'codex'\n"


def test_local_first_verifier_passes_without_llm_verifier_worktree(git_repo: Path, isolated_home: Path) -> None:
    spec = git_repo / "spec.md"
    plan = git_repo / "plan.md"
    spec.write_text("# Spec\n\n## A\n\nAdd local-first file.\n", encoding="utf-8")
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
        "  - {path: src/local_first.py, mode: owned}\n"
        "acceptance_commands: [python -m py_compile src/local_first.py]\n"
        "required_skills: [test-driven-development]\n"
        "```\n"
        "Add local-first file.\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PATH"] = f"{FAKE_BIN}{os.pathsep}{env['PATH']}"
    env["AGENTRUNWAY_FAKE_TARGET"] = "src/local_first.py"
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
    verifier = conn.execute("SELECT runtime, worktree_path, handle_json FROM workers WHERE role='verifier'").fetchone()
    verification = json.loads(
        (Path(payload["run_dir"]) / "artifacts" / "task_001" / "task_001-verifier-001" / "verification_result.json").read_text(
            encoding="utf-8"
        )
    )

    assert payload["status"] == "finished"
    assert verifier["runtime"] == "local"
    assert verifier["worktree_path"] is None
    assert json.loads(verifier["handle_json"])["local_gate"]["source"] == "local"
    assert verification["status"] == "passed"
    assert verification["checks"][0]["source"] == "local"


def test_local_first_verifier_falls_back_if_acceptance_mutates_tracked_files(
    git_repo: Path,
    isolated_home: Path,
) -> None:
    tools = git_repo / "tools"
    tools.mkdir()
    (tools / "mutate_tracked.py").write_text(
        "from pathlib import Path\n"
        "import sys\n"
        "Path(sys.argv[1]).write_text(\"VALUE = 'mutated'\\n\", encoding=\"utf-8\")\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "tools/mutate_tracked.py"], cwd=git_repo, check=True)
    subprocess.run(["git", "commit", "-m", "add dirty acceptance helper"], cwd=git_repo, check=True, capture_output=True)
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
        "  - {path: src/local_dirty.py, mode: owned}\n"
        "acceptance_commands:\n"
        "  - python tools/mutate_tracked.py src/local_dirty.py\n"
        "required_skills: [test-driven-development]\n"
        "```\n"
        "Add worker file.\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PATH"] = f"{FAKE_BIN}{os.pathsep}{env['PATH']}"
    env["AGENTRUNWAY_FAKE_TARGET"] = "src/local_dirty.py"
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
    verifier = dict(conn.execute("SELECT runtime, worktree_path FROM workers WHERE role='verifier'").fetchone())
    implementer = dict(conn.execute("SELECT worktree_path FROM workers WHERE role='implementer'").fetchone())
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=Path(implementer["worktree_path"]),
        text=True,
        capture_output=True,
        check=True,
    )

    assert payload["status"] == "finished"
    assert verifier["runtime"] == "codex"
    assert verifier["worktree_path"] is not None
    assert status.stdout == ""


def test_high_risk_candidates_are_started_in_parallel(git_repo: Path, isolated_home: Path, tmp_path: Path) -> None:
    plan, spec = _write_high_risk_plan(git_repo)
    timing_log = tmp_path / "timing.jsonl"
    env = os.environ.copy()
    env["PATH"] = f"{FAKE_BIN}{os.pathsep}{env['PATH']}"
    env["AGENTRUNWAY_FAKE_CANDIDATE_VARIANT"] = "1"
    env["AGENTRUNWAY_FAKE_TARGET"] = "src/high_risk.py"
    env["AGENTRUNWAY_FAKE_IMPLEMENT_SLEEP_SECONDS"] = "1.0"
    env["AGENTRUNWAY_FAKE_TIMING_LOG"] = str(timing_log)
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
    implementers = conn.execute("SELECT worker_id FROM workers WHERE role='implementer' ORDER BY worker_id").fetchall()
    timing = [json.loads(line) for line in timing_log.read_text(encoding="utf-8").splitlines()]
    starts = {item["worker_id"]: item["time"] for item in timing if item["event"] == "start"}
    ends = {item["worker_id"]: item["time"] for item in timing if item["event"] == "end"}

    assert [row["worker_id"] for row in implementers] == ["task_001-implementer-001", "task_001-implementer-002"]
    assert max(starts.values()) < min(ends.values())


def test_safe_wave_tasks_start_implementers_in_parallel(git_repo: Path, isolated_home: Path, tmp_path: Path) -> None:
    plan, spec = _write_safe_wave_plan(git_repo)
    timing_log = tmp_path / "safe-wave-timing.jsonl"
    env = os.environ.copy()
    env["PATH"] = f"{FAKE_BIN}{os.pathsep}{env['PATH']}"
    env["AGENTRUNWAY_FAKE_TARGET_MAP"] = json.dumps({"task_001": "src/safe_a.py", "task_002": "src/safe_b.py"})
    env["AGENTRUNWAY_FAKE_IMPLEMENT_SLEEP_SECONDS"] = "1.0"
    env["AGENTRUNWAY_FAKE_TIMING_LOG"] = str(timing_log)
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
    implementers = conn.execute("SELECT worker_id FROM workers WHERE role='implementer' ORDER BY worker_id").fetchall()
    timing = [json.loads(line) for line in timing_log.read_text(encoding="utf-8").splitlines()]
    starts = {item["worker_id"]: item["time"] for item in timing if item["event"] == "start"}
    ends = {item["worker_id"]: item["time"] for item in timing if item["event"] == "end"}

    assert payload["status"] == "finished"
    assert [row["worker_id"] for row in implementers] == ["task_001-implementer-001", "task_002-implementer-001"]
    assert max(starts.values()) < min(ends.values())


def test_safe_wave_prestart_is_bounded_to_default_max_workers(
    git_repo: Path,
    isolated_home: Path,
    tmp_path: Path,
) -> None:
    plan, spec = _write_many_safe_wave_plan(git_repo, 5)
    timing_log = tmp_path / "bounded-safe-wave-timing.jsonl"
    target_map = {f"task_{index:03d}": f"src/safe_{index}.py" for index in range(1, 6)}
    env = os.environ.copy()
    env["PATH"] = f"{FAKE_BIN}{os.pathsep}{env['PATH']}"
    env["AGENTRUNWAY_FAKE_TARGET_MAP"] = json.dumps(target_map)
    env["AGENTRUNWAY_FAKE_IMPLEMENT_SLEEP_SECONDS"] = "1.0"
    env["AGENTRUNWAY_FAKE_TIMING_LOG"] = str(timing_log)
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
    timing = [json.loads(line) for line in timing_log.read_text(encoding="utf-8").splitlines()]
    starts = {item["worker_id"]: item["time"] for item in timing if item["event"] == "start"}
    ends = {item["worker_id"]: item["time"] for item in timing if item["event"] == "end"}
    first_four = [f"task_{index:03d}-implementer-001" for index in range(1, 5)]
    fifth = "task_005-implementer-001"

    assert payload["status"] == "finished"
    assert max(starts[worker_id] for worker_id in first_four) < min(ends[worker_id] for worker_id in first_four)
    assert starts[fifth] > min(ends[worker_id] for worker_id in first_four)


def test_safe_wave_prestart_respects_runtime_cap(
    git_repo: Path,
    isolated_home: Path,
    tmp_path: Path,
) -> None:
    plan, spec = _write_many_safe_wave_plan(git_repo, 3)
    global_cfg = Path(os.environ["HOME"]) / ".agentrunway" / "global.yaml"
    global_cfg.parent.mkdir(parents=True, exist_ok=True)
    global_cfg.write_text(
        "runtime_caps:\n"
        "  codex:\n"
        "    max_concurrent_workers: 2\n",
        encoding="utf-8",
    )
    timing_log = tmp_path / "runtime-cap-safe-wave-timing.jsonl"
    target_map = {f"task_{index:03d}": f"src/safe_{index}.py" for index in range(1, 4)}
    env = os.environ.copy()
    env["PATH"] = f"{FAKE_BIN}{os.pathsep}{env['PATH']}"
    env["AGENTRUNWAY_FAKE_TARGET_MAP"] = json.dumps(target_map)
    env["AGENTRUNWAY_FAKE_IMPLEMENT_SLEEP_SECONDS"] = "1.0"
    env["AGENTRUNWAY_FAKE_TIMING_LOG"] = str(timing_log)
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
    timing = [json.loads(line) for line in timing_log.read_text(encoding="utf-8").splitlines()]
    starts = {item["worker_id"]: item["time"] for item in timing if item["event"] == "start"}
    ends = {item["worker_id"]: item["time"] for item in timing if item["event"] == "end"}
    first_two = ["task_001-implementer-001", "task_002-implementer-001"]
    third = "task_003-implementer-001"

    assert payload["status"] == "finished"
    assert max(starts[worker_id] for worker_id in first_two) < min(ends[worker_id] for worker_id in first_two)
    assert starts[third] > min(ends[worker_id] for worker_id in first_two)


def test_prestarted_sibling_workers_are_cancelled_when_collect_fails(
    git_repo: Path,
    isolated_home: Path,
    tmp_path: Path,
) -> None:
    plan, spec = _write_safe_wave_plan(git_repo)
    timing_log = tmp_path / "cancel-sibling-timing.jsonl"
    run_id = "cancel-prestarted-sibling"
    env = os.environ.copy()
    env["PATH"] = f"{FAKE_BIN}{os.pathsep}{env['PATH']}"
    env["AGENTRUNWAY_FAKE_TARGET_MAP"] = json.dumps({"task_001": "src/safe_a.py", "task_002": "src/safe_b.py"})
    env["AGENTRUNWAY_FAKE_FAIL_TASKS"] = "task_001"
    env["AGENTRUNWAY_FAKE_IMPLEMENT_SLEEP_SECONDS_MAP"] = json.dumps({"task_002": "2.0"})
    env["AGENTRUNWAY_FAKE_TIMING_LOG"] = str(timing_log)
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "run",
            "--run-id",
            run_id,
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
        check=False,
    )
    run_json = isolated_home / "runs" / workspace_id(git_repo) / run_id / "run.json"
    payload = json.loads(run_json.read_text(encoding="utf-8"))
    conn = sqlite3.connect(payload["state_db"])
    conn.row_factory = sqlite3.Row
    workers = {
        row["worker_id"]: dict(row)
        for row in conn.execute("SELECT worker_id, state, ended_at FROM workers ORDER BY worker_id").fetchall()
    }

    assert result.returncode != 0
    assert workers["task_001-implementer-001"]["state"] == "malformed_result"
    assert workers["task_002-implementer-001"]["state"] == "cancelled"
    assert workers["task_002-implementer-001"]["ended_at"] is not None


def test_reviewer_needs_context_escalates_once_to_full_tree(git_repo: Path, isolated_home: Path) -> None:
    plan, spec = _write_plan(git_repo, path="src/needs_context.py")
    env = os.environ.copy()
    env["PATH"] = f"{FAKE_BIN}{os.pathsep}{env['PATH']}"
    env["AGENTRUNWAY_FAKE_TARGET"] = "src/needs_context.py"
    env["AGENTRUNWAY_FAKE_REVIEW_SEQUENCE"] = "needs_context,approved"
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
    reviewers = conn.execute("SELECT worker_id, handle_json FROM workers WHERE role='reviewer' ORDER BY worker_id").fetchall()
    events = conn.execute("SELECT event_type, payload_json FROM agentlens_events ORDER BY id").fetchall()
    modes = [
        json.loads(row["handle_json"])["metadata"]["spec"]["metadata"]["AGENTRUNWAY_REVIEW_MODE"]
        for row in reviewers
    ]
    escalations = [
        json.loads(row["payload_json"])
        for row in events
        if row["event_type"] == "agentrunway.review_escalated"
    ]

    assert payload["status"] == "finished"
    assert [row["worker_id"] for row in reviewers] == ["task_001-reviewer-001", "task_001-reviewer-002"]
    assert modes == ["diff", "full_tree"]
    assert escalations[-1]["reason"] == "needs_context"


def test_agentlens_fake_cli_receives_runner_events(git_repo: Path, isolated_home: Path, tmp_path: Path) -> None:
    plan, spec = _write_plan(git_repo, path="src/agentlens_worker.py")
    log = tmp_path / "agentlens.jsonl"
    env = os.environ.copy()
    env["PATH"] = f"{FAKE_BIN}{os.pathsep}{env['PATH']}"
    env["AGENTRUNWAY_FAKE_TARGET"] = "src/agentlens_worker.py"
    env["AGENTLENS_FAKE_LOG"] = str(log)

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
    rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    event_rows = [row for row in rows if "event_type" in row]
    emitted_types = [row["event_type"] for row in event_rows]
    conn = sqlite3.connect(payload["state_db"])
    conn.row_factory = sqlite3.Row
    db_statuses = [row["status"] for row in conn.execute("SELECT status FROM agentlens_events").fetchall()]

    assert "agentrunway.worker_dispatched" in emitted_types
    assert "agentrunway.worker_result" in emitted_types
    assert "agentrunway.run_finished" in emitted_types
    assert all(status == "agentlens_emitted" for status in db_statuses)
    assert event_rows[-1]["payload"]["schema"] == "agentlens.event.v2"
    assert event_rows[-1]["payload"]["outcome"] == "success"
    assert event_rows[-1]["payload"]["payload"]["agentlens_status"] == "agentlens_emitted"


def test_finished_run_records_initial_and_task_checkpoints(git_repo: Path, isolated_home: Path) -> None:
    plan, spec = _write_plan(git_repo, path="src/checkpointed.py")
    env = os.environ.copy()
    env["PATH"] = f"{FAKE_BIN}{os.pathsep}{env['PATH']}"
    env["AGENTRUNWAY_FAKE_TARGET"] = "src/checkpointed.py"
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
    checkpoints = conn.execute(
        "SELECT checkpoint_id, parent_checkpoint_id, merged_candidate_id, reason FROM checkpoints ORDER BY checkpoint_id"
    ).fetchall()
    activities = conn.execute(
        "SELECT task_id, activity_type, status, failure_class FROM activities ORDER BY activity_id"
    ).fetchall()
    selected = conn.execute("SELECT id FROM merge_queue WHERE status='merged'").fetchone()

    assert payload["status"] == "finished"
    assert [(row["checkpoint_id"], row["parent_checkpoint_id"], row["reason"]) for row in checkpoints] == [
        ("cp-000", None, "initial"),
        ("cp-001", "cp-000", "merged:task_001"),
    ]
    assert checkpoints[1]["merged_candidate_id"] == selected["id"]
    assert {(row["task_id"], row["activity_type"], row["status"], row["failure_class"]) for row in activities} == {
        ("task_001", "implement", "completed", None),
        ("task_001", "review", "completed", None),
        ("task_001", "verification", "completed", None),
        ("task_001", "merge", "completed", None),
    }


def test_high_risk_task_ranks_two_candidates(git_repo: Path, isolated_home: Path) -> None:
    plan, spec = _write_high_risk_plan(git_repo)
    env = os.environ.copy()
    env["PATH"] = f"{FAKE_BIN}{os.pathsep}{env['PATH']}"
    env["AGENTRUNWAY_FAKE_TARGET"] = "src/high_risk.py"
    env["AGENTRUNWAY_FAKE_CANDIDATE_VARIANT"] = "1"
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
    implementers = conn.execute("SELECT worker_id FROM workers WHERE role='implementer' ORDER BY worker_id").fetchall()
    ranking = conn.execute(
        "SELECT payload_json FROM agentlens_events WHERE event_type='agentrunway.candidate_ranked' ORDER BY id DESC LIMIT 1"
    ).fetchone()

    assert payload["status"] == "finished"
    assert [row["worker_id"] for row in implementers] == [
        "task_001-implementer-001",
        "task_001-implementer-002",
    ]
    assert json.loads(ranking["payload_json"])["selected_candidate_id"] is not None
    non_selected = conn.execute(
        "SELECT worker_id FROM merge_queue WHERE status='not_selected' ORDER BY worker_id"
    ).fetchone()
    assert non_selected is not None
    evidence_dir = Path(payload["run_dir"]) / "artifacts" / "task_001" / non_selected["worker_id"] / "candidate_evidence"
    assert json.loads((evidence_dir / "commits.json").read_text(encoding="utf-8"))
    assert json.loads((evidence_dir / "changed_files.json").read_text(encoding="utf-8")) == ["src/high_risk.py"]
    worker = json.loads((evidence_dir / "worker.json").read_text(encoding="utf-8"))
    assert worker["worker_id"] == non_selected["worker_id"]


def test_blocked_upstream_prevents_downstream_worker_dispatch(git_repo: Path, isolated_home: Path) -> None:
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
        "dependencies: [task_001]\n"
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
    env["AGENTRUNWAY_FAKE_TARGET"] = "src/a.py"
    env["AGENTRUNWAY_FAKE_REVIEW_STATUS"] = "changes_requested"
    env["AGENTRUNWAY_FAKE_REVIEW_FINDING"] = "needs infrastructure repair before continuing"

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
    workers = conn.execute("SELECT task_id, role FROM workers ORDER BY worker_id").fetchall()
    tasks = conn.execute("SELECT task_id, status FROM tasks ORDER BY task_id").fetchall()
    assert payload["status"] == "blocked"
    assert ("task_002", "implementer") not in [(row[0], row[1]) for row in workers]
    assert dict(tasks)["task_002"] == "pending"
