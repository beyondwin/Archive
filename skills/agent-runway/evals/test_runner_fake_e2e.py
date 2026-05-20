from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "agentrunway.py"


def test_fake_adapter_execution_finishes_and_creates_main_worktree(git_repo: Path, isolated_home: Path) -> None:
    plan = git_repo / "plan.md"
    spec = git_repo / "spec.md"
    spec.write_text("# Spec\n\n## A\n\nAdd A.\n", encoding="utf-8")
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
    assert payload["status"] == "simulated_finished"
    assert payload["simulation"] is True
    assert payload["next_operator_action"] == "run without --fake-success before applying artifacts"
    assert Path(payload["main_worktree"]).exists()
    run_dir = Path(payload["run_dir"])
    assert (run_dir / "artifacts" / "task_001" / "worker_result.json").exists()

    run_json = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert run_json["status"] == "simulated_finished"
    assert run_json["tasks"][0]["status"] == "simulated_completed"

    events = [
        json.loads(line)
        for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert any(event["event_type"] == "agentrunway.simulation" for event in events)
    assert not any(
        event["event_type"] == "agentrunway.run_finished"
        and event["payload"].get("outcome") == "success"
        and event["payload"].get("simulation") is not True
        for event in events
    )

    checkpoints = json.loads(
        subprocess.run(
            [
                sys.executable,
                "-c",
                "import json, sqlite3, sys; "
                "conn=sqlite3.connect(sys.argv[1]); conn.row_factory=sqlite3.Row; "
                "print(json.dumps([dict(row) for row in conn.execute('select reason from checkpoints order by checkpoint_id')]))",
                str(run_dir / "state.sqlite"),
            ],
            text=True,
            capture_output=True,
            check=True,
        ).stdout
    )
    assert {checkpoint["reason"] for checkpoint in checkpoints} == {"initial"}

    status = json.loads(
        subprocess.run(
            [sys.executable, str(SCRIPT), "status", "--run", payload["run_id"], "--json"],
            cwd=git_repo,
            text=True,
            capture_output=True,
            check=True,
        ).stdout
    )
    assert status["status"] == "simulated_finished"
    assert status["simulation"] is True
    assert status["next_operator_action"] == "run without --fake-success before applying artifacts"

    summary = json.loads(
        subprocess.run(
            [sys.executable, str(SCRIPT), "summarize", "--run", payload["run_id"], "--json"],
            cwd=git_repo,
            text=True,
            capture_output=True,
            check=True,
        ).stdout
    )
    assert summary["status"] == "simulated_finished"
    assert summary["simulation"] is True
    assert summary["task_counts"] == {"simulated_completed": 1}
    assert summary["next_operator_action"] == "run without --fake-success before applying artifacts"

    inspect = json.loads(
        subprocess.run(
            [sys.executable, str(SCRIPT), "inspect", "--run", payload["run_id"], "--json"],
            cwd=git_repo,
            text=True,
            capture_output=True,
            check=True,
        ).stdout
    )
    assert inspect["status"] == "simulated_finished"
    assert inspect["simulation"] is True
    assert inspect["next_action"] == "run without --fake-success before applying artifacts"
    assert inspect["next_operator_action"] == "run without --fake-success before applying artifacts"

    apply = json.loads(
        subprocess.run(
            [sys.executable, str(SCRIPT), "apply", "--run", payload["run_id"]],
            cwd=git_repo,
            text=True,
            capture_output=True,
            check=True,
        ).stdout
    )
    assert apply["applied"] is False
    assert apply["error"] == "simulated_run_refused"
