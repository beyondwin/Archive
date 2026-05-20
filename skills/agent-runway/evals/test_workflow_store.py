from __future__ import annotations

import json
from pathlib import Path

from agentrunway.db import AgentRunwayDb
from agentrunway.workflow_store import ActivityStatus, WorkflowStore


def test_workflow_store_records_initial_checkpoint_and_event(tmp_path: Path) -> None:
    db = AgentRunwayDb.open(tmp_path / "state.sqlite")
    store = WorkflowStore(db)

    checkpoint = store.create_checkpoint(
        run_id="run-1",
        checkpoint_id="cp-000",
        commit_sha="abc123",
        parent_checkpoint_id=None,
        merged_candidate_id=None,
        reason="initial",
    )
    store.record_event(
        run_id="run-1",
        event_type="CheckpointCreated",
        node_id="run.cp-000",
        payload={"checkpoint_id": checkpoint["checkpoint_id"]},
    )

    assert checkpoint["checkpoint_id"] == "cp-000"
    assert checkpoint["commit_sha"] == "abc123"
    assert store.latest_checkpoint("run-1")["checkpoint_id"] == "cp-000"
    events = store.list_workflow_events("run-1")
    assert [event["event_type"] for event in events] == ["CheckpointCreated", "CheckpointCreated"]
    assert events[1]["payload"] == {"checkpoint_id": "cp-000"}


def test_activity_completion_is_idempotent_by_key(tmp_path: Path) -> None:
    db = AgentRunwayDb.open(tmp_path / "state.sqlite")
    store = WorkflowStore(db)

    first = store.start_activity(
        run_id="run-1",
        activity_id="task_001.implement.001",
        idempotency_key="run-1:task_001:implement:001",
        task_id="task_001",
        activity_type="implement",
        input_refs={"packet": "packets/task_001.json"},
    )
    second = store.start_activity(
        run_id="run-1",
        activity_id="task_001.implement.duplicate",
        idempotency_key="run-1:task_001:implement:001",
        task_id="task_001",
        activity_type="implement",
        input_refs={"packet": "packets/task_001.json"},
    )

    assert first["activity_id"] == second["activity_id"]
    assert first["status"] == ActivityStatus.STARTED.value

    completed = store.complete_activity(
        activity_id=first["activity_id"],
        status=ActivityStatus.COMPLETED,
        output_refs={"worker_result": "artifacts/task_001/worker_result.json"},
        failure_class=None,
    )

    assert completed["status"] == ActivityStatus.COMPLETED.value
    assert completed["output_refs"] == {"worker_result": "artifacts/task_001/worker_result.json"}
    assert store.get_activity(first["activity_id"])["status"] == ActivityStatus.COMPLETED.value


def test_decision_packet_round_trips_json_payload(tmp_path: Path) -> None:
    db = AgentRunwayDb.open(tmp_path / "state.sqlite")
    store = WorkflowStore(db)

    packet = store.create_decision_packet(
        run_id="run-1",
        decision_id="decision-001",
        task_id="task_002",
        failure_class="needs_plan_fix",
        summary="File claim missing for shared CLI module.",
        payload={"proposed_file_claim": "skills/agent-runway/scripts/agentrunway/invocation.py"},
    )

    assert packet["failure_class"] == "needs_plan_fix"
    assert json.loads(packet["payload_json"])["proposed_file_claim"].endswith("invocation.py")
    assert store.list_decision_packets("run-1")[0]["decision_id"] == "decision-001"
