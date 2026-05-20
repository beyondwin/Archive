from __future__ import annotations

import json
from pathlib import Path

from agentrunway.db import AgentRunwayDb
from agentrunway.events import EventJournal, build_agentlens_event_envelope, build_event_payload


V2_EVENT_KEYS = {
    "schema",
    "event_id",
    "run_id",
    "event_type",
    "producer",
    "occurred_at",
    "sequence",
    "phase",
    "outcome",
    "severity",
    "task_id",
    "attempt_id",
    "candidate_id",
    "gate_id",
    "evidence_refs",
    "artifact_refs",
    "projection_hints",
    "trust_impact",
    "summary",
    "payload",
}


class FailingEmitter:
    def emit(self, event_type: str, payload: dict[str, object]) -> None:
        raise RuntimeError(f"agentlens down for {event_type}")


class RecordingEmitter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def emit(self, event_type: str, payload: dict[str, object]) -> None:
        self.calls.append((event_type, payload))


def test_event_journal_writes_events_jsonl_and_db_outbox(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    run_dir = tmp_path / "run"
    db = AgentRunwayDb.open(run_dir / "state.sqlite")
    journal = EventJournal(db=db, run_dir=run_dir, agentlens_emitter=None)

    record = journal.record(
        "agentrunway.run_started",
        build_event_payload("run-1", "run", "success", "started", token="secret-value"),
    )

    assert record.event_type == "agentrunway.run_started"
    assert record.status == "agentlens_disabled"
    lines = (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert event["schema"] == "agentlens.event.v2"
    assert event["event_type"] == "agentrunway.run_started"
    assert "type" not in event
    assert "ts" not in event
    assert event["run_id"] == "run-1"
    assert event["sequence"] == 1
    assert event["producer"]["name"] == "agentrunway"
    assert event["payload"]["agentlens_status"] == "agentlens_disabled"
    assert event["payload"]["token"] == "[REDACTED]"

    rows = db.list_events()
    assert rows[0]["event_type"] == "agentrunway.run_started"
    assert rows[0]["status"] == "agentlens_disabled"


def test_event_journal_records_agentlens_failure_without_raising(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    db = AgentRunwayDb.open(run_dir / "state.sqlite")
    journal = EventJournal(db=db, run_dir=run_dir, agentlens_emitter=FailingEmitter())

    record = journal.record(
        "agentrunway.contract_created",
        build_event_payload("run-1", "contract", "success", "contract created"),
    )

    assert record.status == "agentlens_failed"
    assert "agentlens down" in str(record.error)
    rows = db.list_events()
    assert rows[0]["status"] == "agentlens_failed"
    assert "agentlens down" in str(rows[0]["error"])


def test_event_journal_emits_v2_envelope_to_agentlens_sink(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    db = AgentRunwayDb.open(run_dir / "state.sqlite")
    emitter = RecordingEmitter()
    journal = EventJournal(db=db, run_dir=run_dir, agentlens_emitter=emitter)

    journal.record(
        "agentrunway.run_started",
        build_event_payload("run-1", "run", "success", "started"),
    )

    assert len(emitter.calls) == 1
    event_type, emitted = emitter.calls[0]
    assert event_type == "agentrunway.run_started"
    assert emitted["schema"] == "agentlens.event.v2"
    assert emitted["event_id"] == "evt_000001"
    assert emitted["event_type"] == "agentrunway.run_started"
    assert emitted["payload"]["event_name"] == "agentrunway.run_started"


def test_event_journal_query_returns_redacted_payloads(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    run_dir = tmp_path / "run"
    db = AgentRunwayDb.open(run_dir / "state.sqlite")
    journal = EventJournal(db=db, run_dir=run_dir)
    journal.record(
        "agentrunway.worker_result",
        build_event_payload("run-1", "worker", "success", "done", path=str(home / "repo")),
    )

    events = journal.list()

    assert events[0]["payload"]["path"] == "~/repo"


def test_event_payload_includes_run_id_alias_and_bounds_large_extras() -> None:
    payload = build_event_payload(
        "run-1",
        "gate",
        "partial",
        "x" * 5000,
        gate_result={"details": "y" * 10000},
        changed_files=[f"src/file_{index}.py" for index in range(1000)],
    )

    encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
    assert payload["run_id"] == "run-1"
    assert payload["agentrunway_run_id"] == "run-1"
    assert payload["payload_truncated"] is True
    assert len(payload["summary"]) <= 1200
    assert len(encoded) <= 3500
    assert payload["gate_result"] == {"omitted": True, "reason": "size"}
    assert payload["changed_files"] == {"omitted": True, "reason": "size"}


def test_event_payload_preserves_trust_routing_fields_when_bounded() -> None:
    payload = build_event_payload(
        "run-1",
        "verification",
        "success",
        "verified",
        task_id="task_001",
        artifact_refs=["artifacts/task_001/verification_result.json"],
        evidence_refs=["verification:task_001"],
        opaque="z" * 10000,
    )

    assert payload["payload_truncated"] is True
    assert payload["task_id"] == "task_001"
    assert payload["artifact_refs"] == ["artifacts/task_001/verification_result.json"]
    assert payload["evidence_refs"] == ["verification:task_001"]


def test_agentlens_event_envelope_uses_v2_trust_impact_enum() -> None:
    partial = build_agentlens_event_envelope(
        event_id=1,
        event_type="agentrunway.agentlens_sink_unavailable",
        payload=build_event_payload("run-1", "agentlens", "partial", "sink unavailable"),
        occurred_at="2026-05-21T00:00:00Z",
    )
    failed = build_agentlens_event_envelope(
        event_id=2,
        event_type="agentrunway.run_blocked",
        payload=build_event_payload("run-1", "run", "failed", "blocked"),
        occurred_at="2026-05-21T00:00:00Z",
    )
    simulated = build_agentlens_event_envelope(
        event_id=3,
        event_type="agentrunway.run_finished",
        payload=build_event_payload("run-1", "run", "success", "simulated", simulation=True),
        occurred_at="2026-05-21T00:00:00Z",
    )

    assert partial["trust_impact"] == "requires_attention"
    assert failed["trust_impact"] == "supports_failure"
    assert simulated["trust_impact"] == "downgrades_trust"
    assert simulated["phase"] == "finish"


def test_agentlens_event_envelope_is_strict_v2_shape() -> None:
    event = build_agentlens_event_envelope(
        event_id=7,
        event_type="agentrunway.merge_applied",
        payload=build_event_payload(
            "run-1",
            "agentlens",
            "partial",
            "merge applied",
            task_id="task_001",
            candidate_id=3,
        ),
        occurred_at="2026-05-21T00:00:00Z",
    )

    assert set(event) <= V2_EVENT_KEYS
    assert event["phase"] == "run"
    assert event["candidate_id"] == "3"
