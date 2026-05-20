from __future__ import annotations

import json
from pathlib import Path

from agentrunway.db import AgentRunwayDb
from agentrunway.events import EventJournal, build_event_payload


class FailingEmitter:
    def emit(self, event_type: str, payload: dict[str, object]) -> None:
        raise RuntimeError(f"agentlens down for {event_type}")


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
    payload = json.loads(lines[0])
    assert payload["event_type"] == "agentrunway.run_started"
    assert payload["payload"]["token"] == "[REDACTED]"

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
