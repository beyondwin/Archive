from __future__ import annotations

import json
from pathlib import Path

from agentrunway.artifact_graph import build_artifact_graph, write_artifact_graph
from agentrunway.db import AgentRunwayDb
from agentrunway.models import FileClaim, TaskSpec
from agentrunway.status import build_inspect_payload, format_inspect_payload, next_operator_action


def _task() -> TaskSpec:
    return TaskSpec(
        task_id="task_001",
        title="Example",
        risk="low",
        phase="implementation",
        dependencies=(),
        spec_refs=("S1",),
        file_claims=(FileClaim(path="src/example.py", mode="owned"),),
        acceptance_commands=("python -m pytest",),
    )


def test_artifact_graph_marks_contract_packet_result_and_merge_nodes(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    (run_dir / "contract.json").parent.mkdir(parents=True)
    (run_dir / "contract.json").write_text(
        json.dumps({"coverage": {"covered": ["S1"], "unreferenced": ["S2"]}}),
        encoding="utf-8",
    )
    (run_dir / "packets").mkdir()
    (run_dir / "packets" / "task_001.json").write_text("{}", encoding="utf-8")
    (run_dir / "artifacts" / "task_001" / "task_001-implementer-001").mkdir(parents=True)
    (run_dir / "artifacts" / "task_001" / "task_001-implementer-001" / "worker_result.json").write_text("{}", encoding="utf-8")
    db = AgentRunwayDb.open(run_dir / "state.sqlite")
    db.upsert_task(_task())
    db.create_worker_attempt(
        worker_id="task_001-implementer-001",
        task_id="task_001",
        role="implementer",
        runtime="codex",
        model="gpt-5.5",
        reasoning_effort="high",
        attempt=1,
        worktree_path=str(run_dir / "worker"),
        branch="agentrunway/run-1/task_001-implementer-001",
        state="merged",
        handle_json={},
    )
    db.enqueue_merge_candidate(
        task_id="task_001",
        worker_id="task_001-implementer-001",
        commits=("abc123",),
        changed_files=("src/example.py",),
        status="merged",
    )

    graph = build_artifact_graph(run_dir=run_dir, db=db)

    statuses = {node["id"]: node["status"] for node in graph["nodes"]}
    assert statuses["contract"] == "done"
    assert statuses["task_001:packet"] == "done"
    assert statuses["task_001:task_001-implementer-001:worker_result"] == "done"
    assert statuses["task_001:task_001-implementer-001:merge_candidate"] == "done"
    assert graph["coverage"]["covered"] == ["S1"]


def test_write_artifact_graph_creates_json_file(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    db = AgentRunwayDb.open(run_dir / "state.sqlite")
    payload = write_artifact_graph(run_dir=run_dir, db=db)
    assert (run_dir / "artifact_graph.json").exists()
    assert payload["nodes"][0]["id"] == "contract"


def test_inspect_payload_includes_agentlens_and_coverage(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    db = AgentRunwayDb.open(run_dir / "state.sqlite")
    db.insert_event(event_type="agentrunway.run_started", payload={"run_id": "run-1"}, status="agentlens_failed", error="down")
    (run_dir / "run.json").write_text(
        json.dumps({"run_id": "run-1", "status": "finished", "run_dir": str(run_dir), "state_db": str(run_dir / "state.sqlite")}),
        encoding="utf-8",
    )
    (run_dir / "coverage.json").write_text(
        json.dumps({"covered": ["S1"], "partial": [], "blocked": [], "unreferenced": []}),
        encoding="utf-8",
    )

    payload = build_inspect_payload(run_json=json.loads((run_dir / "run.json").read_text()), db=db)
    text = format_inspect_payload(payload)

    assert payload["agentlens"]["failed"] == 1
    assert payload["coverage"]["covered"] == ["S1"]
    assert "agentlens_failed=1" in text


def test_next_operator_action_prioritizes_terminal_status_over_agentlens_failure() -> None:
    agentlens = {"last_status": "agentlens_failed", "failed": 1}

    assert (
        next_operator_action({"run_id": "run-1", "status": "finished", "tasks": []}, agentlens)
        == "apply or inspect artifacts"
    )
    assert (
        next_operator_action({"run_id": "run-1", "status": "blocked", "tasks": []}, agentlens)
        == "inspect blocked tasks and run resume --dry-run"
    )


def test_next_operator_action_for_running_agentlens_failure() -> None:
    assert (
        next_operator_action({"run_id": "run-1", "status": "running", "tasks": []}, {"failed": 2})
        == "inspect AgentLens failures and continue monitoring"
    )


def test_inspect_payload_and_format_include_next_action(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    db = AgentRunwayDb.open(run_dir / "state.sqlite")
    run_json = {"run_id": "run-1", "status": "finished", "run_dir": str(run_dir), "tasks": []}

    payload = build_inspect_payload(run_json=run_json, db=db)
    text = format_inspect_payload(payload)

    assert payload["next_action"] == "apply or inspect artifacts"
    assert "next_action=apply or inspect artifacts" in text
