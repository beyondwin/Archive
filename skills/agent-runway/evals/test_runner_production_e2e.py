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


def test_reviewer_and_verifier_worktrees_include_candidate_files(git_repo: Path, isolated_home: Path) -> None:
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
    rows = conn.execute(
        "SELECT role, worktree_path FROM workers WHERE role IN ('reviewer', 'verifier') ORDER BY role"
    ).fetchall()

    assert {row["role"] for row in rows} == {"reviewer", "verifier"}
    for row in rows:
        reviewed_file = Path(row["worktree_path"]) / "src" / "review_visible.py"
        assert reviewed_file.read_text(encoding="utf-8") == "VALUE = 'codex'\n"


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
    assert event_rows[-1]["payload"]["outcome"] == "success"


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
