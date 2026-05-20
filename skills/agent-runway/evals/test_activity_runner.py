from __future__ import annotations

from pathlib import Path

from agentrunway.activity_runner import ActivityRunner
from agentrunway.db import AgentRunwayDb
from agentrunway.workflow_store import ActivityStatus, WorkflowStore


def test_activity_runner_starts_and_completes_activity_once(tmp_path: Path) -> None:
    db = AgentRunwayDb.open(tmp_path / "state.sqlite")
    runner = ActivityRunner(store=WorkflowStore(db), run_id="run-1")

    started = runner.start(
        activity_id="task_001.implement.001",
        idempotency_key="run-1:task_001:implement:001",
        task_id="task_001",
        activity_type="implement",
        input_refs={"checkpoint_id": "cp-000"},
    )
    completed = runner.complete(
        activity_id="task_001.implement.001",
        status=ActivityStatus.COMPLETED,
        output_refs={"candidate_id": 7},
        failure_class=None,
    )

    assert started["status"] == "started"
    assert completed["status"] == "completed"
    assert db.get_activity("task_001.implement.001")["output_refs"] == {"candidate_id": 7}
