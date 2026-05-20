from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "agentrunway.py"


def test_agentrunway_run_planning_only_creates_state(git_repo: Path, isolated_home: Path) -> None:
    plan = git_repo / "plan.md"
    spec = git_repo / "spec.md"
    spec.write_text("# Spec\n\n## Docs\n\nWrite usage.\n", encoding="utf-8")
    plan.write_text(
        "## Task 1: Docs\n\n"
        "```yaml agentrunway-task\n"
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
    payload = json.loads(result.stdout)
    db_path = next(isolated_home.glob("runs/*/*/state.sqlite"))
    run_dir = db_path.parent
    packet_path = run_dir / "packets" / "task_001.json"
    conn = sqlite3.connect(db_path)
    assert conn.execute("select count(*) from tasks").fetchone()[0] == 1
    assert conn.execute("select count(*) from task_packets").fetchone()[0] == 1
    artifact_event = conn.execute(
        "select payload_json from agentlens_events where event_type='agentrunway.artifacts_ready'"
    ).fetchone()
    assert artifact_event is not None
    artifact_payload = json.loads(artifact_event[0])
    assert artifact_payload["artifact_graph_path"] == str(run_dir / "artifact_graph.json")
    assert artifact_payload["coverage_path"] == str(run_dir / "coverage.json")
    assert artifact_payload["artifact_refs"] == ["contract.json", "artifact_graph.json", "coverage.json"]
    assert packet_path.exists()
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    assert packet["task_id"] == "task_001"
    assert packet["spec_refs"][0]["id"] == "S1.1"
    assert payload["artifacts"]["contract"] == str(run_dir / "contract.json")
    assert payload["artifacts"]["artifact_graph"] == str(run_dir / "artifact_graph.json")
    assert payload["artifacts"]["coverage"] == str(run_dir / "coverage.json")
    assert payload["artifacts"]["packets"] == [str(packet_path)]
    assert payload["packet_summary"] == [
        {
            "task_id": "task_001",
            "path": str(packet_path),
            "context_budget": packet["context_budget"],
            "spec_ref_count": 1,
            "allowed_write_glob_count": 1,
        }
    ]
    graph = json.loads((run_dir / "artifact_graph.json").read_text(encoding="utf-8"))
    packet_nodes = [node for node in graph["nodes"] if node["kind"] == "task_packet"]
    assert packet_nodes == [
        {
            "id": "task_001:packet",
            "kind": "task_packet",
            "path": str(packet_path),
            "status": "done",
            "task_id": "task_001",
        }
    ]
