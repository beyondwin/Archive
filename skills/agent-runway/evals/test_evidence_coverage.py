from __future__ import annotations

import json
from pathlib import Path

from agentrunway.artifact_graph import build_artifact_graph, write_artifact_graph
from agentrunway.db import AgentRunwayDb
from agentrunway.models import FileClaim, TaskSpec
from agentrunway.run_summary import build_run_summary
from agentrunway.status import build_inspect_payload, format_inspect_payload


def _task() -> TaskSpec:
    return TaskSpec(
        task_id="task_001",
        title="Trust Task",
        risk="low",
        phase="implementation",
        dependencies=(),
        spec_refs=("S1.6.4",),
        file_claims=(FileClaim("src/trust.py", "owned"),),
        acceptance_commands=("python -m pytest",),
    )


def _contract(run_dir: Path) -> None:
    (run_dir / "contract.json").parent.mkdir(parents=True, exist_ok=True)
    (run_dir / "contract.json").write_text(
        json.dumps({"coverage": {"covered": ["S1.6.4"], "partial": [], "blocked": [], "unreferenced": []}}),
        encoding="utf-8",
    )


def test_simulated_task_does_not_count_as_implemented_evidence(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _contract(run_dir)
    db = AgentRunwayDb.open(run_dir / "state.sqlite")
    db.upsert_task(_task())
    db.set_task_status("task_001", "simulated_completed")

    graph = build_artifact_graph(run_dir=run_dir, db=db)

    implementation = graph["coverage"]["implementation_evidence_coverage"]
    assert graph["coverage"]["covered"] == ["S1.6.4"]
    assert implementation["planned"] == ["S1.6.4"]
    assert implementation["simulated"] == ["S1.6.4"]
    assert implementation["implemented"] == []


def test_merged_task_with_candidate_evidence_counts_as_implemented(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _contract(run_dir)
    db = AgentRunwayDb.open(run_dir / "state.sqlite")
    db.upsert_task(_task())
    db.set_task_status("task_001", "merged")
    db.enqueue_merge_candidate(
        task_id="task_001",
        worker_id="task_001-implementer-001",
        commits=("abc123",),
        changed_files=("src/trust.py",),
        status="merged",
    )

    graph = build_artifact_graph(run_dir=run_dir, db=db)

    implementation = graph["coverage"]["implementation_evidence_coverage"]
    assert implementation["planned"] == ["S1.6.4"]
    assert implementation["implemented"] == ["S1.6.4"]
    assert implementation["simulated"] == []


def test_merge_blocked_task_counts_as_blocked_evidence(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _contract(run_dir)
    db = AgentRunwayDb.open(run_dir / "state.sqlite")
    db.upsert_task(_task())
    db.set_task_status("task_001", "blocked")
    db.enqueue_merge_candidate(
        task_id="task_001",
        worker_id="task_001-implementer-001",
        commits=(),
        changed_files=(),
        status="merge_blocked",
    )

    graph = build_artifact_graph(run_dir=run_dir, db=db)

    implementation = graph["coverage"]["implementation_evidence_coverage"]
    assert implementation["blocked"] == ["S1.6.4"]
    assert implementation["implemented"] == []


def test_coverage_json_and_operator_outputs_show_both_views(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _contract(run_dir)
    db = AgentRunwayDb.open(run_dir / "state.sqlite")
    db.upsert_task(_task())
    db.set_task_status("task_001", "simulated_completed")
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "run_id": "run-1",
                "status": "simulated_finished",
                "simulation": True,
                "run_dir": str(run_dir),
                "state_db": str(run_dir / "state.sqlite"),
            }
        ),
        encoding="utf-8",
    )

    write_artifact_graph(run_dir=run_dir, db=db)
    coverage = json.loads((run_dir / "coverage.json").read_text(encoding="utf-8"))
    inspect_payload = build_inspect_payload(run_json=json.loads((run_dir / "run.json").read_text()), db=db)
    inspect_text = format_inspect_payload(inspect_payload)
    summary = build_run_summary(run_json=json.loads((run_dir / "run.json").read_text()), db=db)

    assert coverage["covered"] == ["S1.6.4"]
    assert coverage["implementation_evidence_coverage"]["implemented"] == []
    assert inspect_payload["coverage"]["implementation_evidence_coverage"]["simulated"] == ["S1.6.4"]
    assert "planned=1" in inspect_text
    assert "implemented=0" in inspect_text
    assert summary["coverage_summary"] == {
        "spec_refs_planned": 1,
        "spec_refs_implemented_with_evidence": 0,
    }
