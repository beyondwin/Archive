# AgentRunway Durable Integration Orchestrator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make AgentRunway advance run main immediately after verified candidate selection, persist durable workflow/checkpoint/activity evidence for every merge, and surface checkpoints, failure classes, and decision hooks in `summarize` so future slices can resume from explicit activity boundaries.

**Architecture:** Add a small durable workflow layer beside the existing SQLite state, then wire it into the current runner incrementally. The first implementation keeps the existing worker/reviewer/verifier supervisor path, but changes integration timing so dependent tasks start from the latest verified run-main checkpoint.

**Slice boundary:** This plan delivers slice 1 of the design (see design §13.1). The initial implementation persisted merge activity records and classified merge failures. The follow-up risk-closure pass also records implement/review/verification activities, routes review/verification/plan failures through `FailureClassifier`, writes decision packets for human-input failures, and exposes the next durable activity boundary from `resume --dry-run`. Runner replacement of `schedule_waves` with checkpoint-aware safe-wave scheduling remains a later slice.

**Tech Stack:** Python 3, SQLite, pytest, git worktrees, existing AgentRunway fake Codex/Claude CLI fixtures.

---

## Scope Check

This plan implements the first durable-orchestrator slice from:

- `docs/superpowers/specs/2026-05-20-agentrunway-durable-integration-orchestrator-design.md`

It does not rewrite AgentRunway into a remote workflow service. It keeps the existing runner, supervisor, merge queue, artifact graph, and AgentLens event journal, then adds durable workflow/checkpoint records and immediate run-main integration behind tests.

## File Structure

- `skills/agent-runway/scripts/agentrunway/db.py`
  - Extend schema and add small persistence helpers for workflow events, activities, checkpoints, and decision packets.
- `skills/agent-runway/scripts/agentrunway/workflow_store.py`
  - New focused wrapper over `AgentRunwayDb` for idempotent activity/checkpoint/event operations.
- `skills/agent-runway/scripts/agentrunway/failure_classifier.py`
  - New pure classifier that maps gate/merge/plan/infra failures to durable recovery classes.
- `skills/agent-runway/scripts/agentrunway/scheduler.py`
  - Extend current wave scheduler with checkpoint-aware ready-task selection and file-claim conflict serialization.
- `skills/agent-runway/scripts/agentrunway/integration_manager.py`
  - New merge/checkpoint helper for selected candidates.
- `skills/agent-runway/scripts/agentrunway/runner.py`
  - Wire the store, classifier, checkpoint scheduler, and integration manager into `run()`.
- `skills/agent-runway/scripts/agentrunway/run_summary.py`
  - Add checkpoint, graph-node, and failure-class summary fields.
- `skills/agent-runway/evals/fixtures/fake-bin/codex`
  - Extend fake adapter controls to support task-specific targets and required prior files.
- New tests:
  - `skills/agent-runway/evals/test_workflow_store.py`
  - `skills/agent-runway/evals/test_failure_classifier.py`
  - `skills/agent-runway/evals/test_checkpoint_scheduler.py`
  - `skills/agent-runway/evals/test_integration_manager.py`
  - `skills/agent-runway/evals/test_durable_orchestrator_e2e.py`

---

### Task 1: Add Durable Workflow Store

```yaml agentrunway-task
task_id: task_001
title: Add Durable Workflow Store
risk: medium
phase: implementation
dependencies: []
spec_refs: [S1.6, S1.7.1, S1.10, S1.12, S1.15]
file_claims:
  - {path: skills/agent-runway/scripts/agentrunway/db.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/workflow_store.py, mode: owned}
  - {path: skills/agent-runway/evals/test_workflow_store.py, mode: owned}
acceptance_commands:
  - cd skills/agent-runway && python -m pytest evals/test_workflow_store.py -v
required_skills: [using-superpowers, test-driven-development]
serial: true
```

**Files:**
- Modify: `skills/agent-runway/scripts/agentrunway/db.py`
- Create: `skills/agent-runway/scripts/agentrunway/workflow_store.py`
- Create: `skills/agent-runway/evals/test_workflow_store.py`

- [ ] **Step 1: Write failing workflow store tests**

Create `skills/agent-runway/evals/test_workflow_store.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from agentrunway.db import AgentRunwayDb
from agentrunway.workflow_store import ActivityStatus, WorkflowStore


def _db(tmp_path: Path) -> AgentRunwayDb:
    return AgentRunwayDb.open(tmp_path / "state.sqlite")


def test_workflow_store_records_initial_checkpoint_and_event(tmp_path: Path) -> None:
    db = _db(tmp_path)
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
    assert [event["event_type"] for event in events] == ["CheckpointCreated"]
    assert events[0]["payload"] == {"checkpoint_id": "cp-000"}


def test_activity_completion_is_idempotent_by_key(tmp_path: Path) -> None:
    db = _db(tmp_path)
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
    db = _db(tmp_path)
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
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
cd skills/agent-runway && python -m pytest evals/test_workflow_store.py -v
```

Expected: fails with `ModuleNotFoundError: No module named 'agentrunway.workflow_store'`.

- [ ] **Step 3: Extend SQLite schema and DB helpers**

Modify `skills/agent-runway/scripts/agentrunway/db.py` by appending these tables to the `SCHEMA_SQL` triple-quoted string (after the existing `watchdog_events` definition and before the closing `"""`):

```python
CREATE TABLE IF NOT EXISTS workflow_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  node_id TEXT,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS activities (
  activity_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  idempotency_key TEXT NOT NULL UNIQUE,
  task_id TEXT,
  activity_type TEXT NOT NULL,
  status TEXT NOT NULL,
  input_refs_json TEXT NOT NULL DEFAULT '{}',
  output_refs_json TEXT NOT NULL DEFAULT '{}',
  failure_class TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS checkpoints (
  checkpoint_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  commit_sha TEXT NOT NULL,
  parent_checkpoint_id TEXT,
  merged_candidate_id INTEGER,
  reason TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS decision_packets (
  decision_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  task_id TEXT,
  failure_class TEXT NOT NULL,
  summary TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

Add these methods to `AgentRunwayDb` after `list_applied_commits`:

```python
    def insert_workflow_event(self, *, run_id: str, event_type: str, node_id: str | None, payload: dict[str, Any]) -> int:
        cursor = self.conn.execute(
            """
            INSERT INTO workflow_events (run_id, event_type, node_id, payload_json)
            VALUES (?, ?, ?, ?)
            """,
            (run_id, event_type, node_id, json.dumps(payload, ensure_ascii=False, sort_keys=True)),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    def list_workflow_events(self, run_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM workflow_events WHERE run_id=? ORDER BY id", (run_id,)).fetchall()
        events: list[dict[str, Any]] = []
        for row in rows:
            data = dict(row)
            data["payload"] = json.loads(data.pop("payload_json"))
            events.append(data)
        return events

    def get_activity_by_idempotency_key(self, idempotency_key: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM activities WHERE idempotency_key=?", (idempotency_key,)).fetchone()
        if row is None:
            return None
        data = dict(row)
        data["input_refs"] = json.loads(data.pop("input_refs_json"))
        data["output_refs"] = json.loads(data.pop("output_refs_json"))
        return data

    def get_activity(self, activity_id: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM activities WHERE activity_id=?", (activity_id,)).fetchone()
        if row is None:
            raise KeyError(activity_id)
        data = dict(row)
        data["input_refs"] = json.loads(data.pop("input_refs_json"))
        data["output_refs"] = json.loads(data.pop("output_refs_json"))
        return data

    def insert_activity(
        self,
        *,
        activity_id: str,
        run_id: str,
        idempotency_key: str,
        task_id: str | None,
        activity_type: str,
        status: str,
        input_refs: dict[str, Any],
    ) -> dict[str, Any]:
        self.conn.execute(
            """
            INSERT INTO activities
              (activity_id, run_id, idempotency_key, task_id, activity_type, status, input_refs_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (activity_id, run_id, idempotency_key, task_id, activity_type, status, json.dumps(input_refs, ensure_ascii=False, sort_keys=True)),
        )
        self.conn.commit()
        return self.get_activity(activity_id)

    def update_activity(
        self,
        *,
        activity_id: str,
        status: str,
        output_refs: dict[str, Any],
        failure_class: str | None,
    ) -> dict[str, Any]:
        self.conn.execute(
            """
            UPDATE activities
            SET status=?, output_refs_json=?, failure_class=?, updated_at=CURRENT_TIMESTAMP
            WHERE activity_id=?
            """,
            (status, json.dumps(output_refs, ensure_ascii=False, sort_keys=True), failure_class, activity_id),
        )
        self.conn.commit()
        return self.get_activity(activity_id)

    def insert_checkpoint(
        self,
        *,
        run_id: str,
        checkpoint_id: str,
        commit_sha: str,
        parent_checkpoint_id: str | None,
        merged_candidate_id: int | None,
        reason: str,
    ) -> dict[str, Any]:
        self.conn.execute(
            """
            INSERT OR REPLACE INTO checkpoints
              (checkpoint_id, run_id, commit_sha, parent_checkpoint_id, merged_candidate_id, reason)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (checkpoint_id, run_id, commit_sha, parent_checkpoint_id, merged_candidate_id, reason),
        )
        self.conn.commit()
        return self.get_checkpoint(checkpoint_id)

    def get_checkpoint(self, checkpoint_id: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM checkpoints WHERE checkpoint_id=?", (checkpoint_id,)).fetchone()
        if row is None:
            raise KeyError(checkpoint_id)
        return dict(row)

    def latest_checkpoint(self, run_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM checkpoints WHERE run_id=? ORDER BY created_at DESC, checkpoint_id DESC LIMIT 1",
            (run_id,),
        ).fetchone()
        return dict(row) if row is not None else None

    def list_checkpoints(self, run_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM checkpoints WHERE run_id=? ORDER BY created_at, checkpoint_id", (run_id,)).fetchall()
        return [dict(row) for row in rows]

    def insert_decision_packet(
        self,
        *,
        run_id: str,
        decision_id: str,
        task_id: str | None,
        failure_class: str,
        summary: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        self.conn.execute(
            """
            INSERT OR REPLACE INTO decision_packets
              (decision_id, run_id, task_id, failure_class, summary, payload_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (decision_id, run_id, task_id, failure_class, summary, json.dumps(payload, ensure_ascii=False, sort_keys=True)),
        )
        self.conn.commit()
        return self.get_decision_packet(decision_id)

    def get_decision_packet(self, decision_id: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM decision_packets WHERE decision_id=?", (decision_id,)).fetchone()
        if row is None:
            raise KeyError(decision_id)
        return dict(row)

    def list_decision_packets(self, run_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM decision_packets WHERE run_id=? ORDER BY created_at, decision_id", (run_id,)).fetchall()
        return [dict(row) for row in rows]
```

- [ ] **Step 4: Implement workflow store wrapper**

Create `skills/agent-runway/scripts/agentrunway/workflow_store.py`:

```python
from __future__ import annotations

from enum import Enum
from typing import Any

from .db import AgentRunwayDb


class ActivityStatus(str, Enum):
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


class WorkflowStore:
    def __init__(self, db: AgentRunwayDb):
        self.db = db

    def record_event(self, *, run_id: str, event_type: str, node_id: str | None, payload: dict[str, Any]) -> int:
        return self.db.insert_workflow_event(
            run_id=run_id,
            event_type=event_type,
            node_id=node_id,
            payload=payload,
        )

    def list_workflow_events(self, run_id: str) -> list[dict[str, Any]]:
        return self.db.list_workflow_events(run_id)

    def start_activity(
        self,
        *,
        run_id: str,
        activity_id: str,
        idempotency_key: str,
        task_id: str | None,
        activity_type: str,
        input_refs: dict[str, Any],
    ) -> dict[str, Any]:
        existing = self.db.get_activity_by_idempotency_key(idempotency_key)
        if existing is not None:
            return existing
        activity = self.db.insert_activity(
            activity_id=activity_id,
            run_id=run_id,
            idempotency_key=idempotency_key,
            task_id=task_id,
            activity_type=activity_type,
            status=ActivityStatus.STARTED.value,
            input_refs=input_refs,
        )
        self.record_event(
            run_id=run_id,
            event_type="ActivityStarted",
            node_id=activity_id,
            payload={"activity_id": activity_id, "activity_type": activity_type, "task_id": task_id},
        )
        return activity

    def complete_activity(
        self,
        *,
        activity_id: str,
        status: ActivityStatus,
        output_refs: dict[str, Any],
        failure_class: str | None,
    ) -> dict[str, Any]:
        activity = self.db.update_activity(
            activity_id=activity_id,
            status=status.value,
            output_refs=output_refs,
            failure_class=failure_class,
        )
        self.record_event(
            run_id=str(activity["run_id"]),
            event_type="ActivityCompleted" if status == ActivityStatus.COMPLETED else "ActivityFailed",
            node_id=activity_id,
            payload={
                "activity_id": activity_id,
                "activity_type": activity["activity_type"],
                "task_id": activity.get("task_id"),
                "status": status.value,
                "failure_class": failure_class,
            },
        )
        return activity

    def get_activity(self, activity_id: str) -> dict[str, Any]:
        return self.db.get_activity(activity_id)

    def create_checkpoint(
        self,
        *,
        run_id: str,
        checkpoint_id: str,
        commit_sha: str,
        parent_checkpoint_id: str | None,
        merged_candidate_id: int | None,
        reason: str,
    ) -> dict[str, Any]:
        checkpoint = self.db.insert_checkpoint(
            run_id=run_id,
            checkpoint_id=checkpoint_id,
            commit_sha=commit_sha,
            parent_checkpoint_id=parent_checkpoint_id,
            merged_candidate_id=merged_candidate_id,
            reason=reason,
        )
        self.record_event(
            run_id=run_id,
            event_type="CheckpointCreated",
            node_id=checkpoint_id,
            payload={
                "checkpoint_id": checkpoint_id,
                "commit_sha": commit_sha,
                "parent_checkpoint_id": parent_checkpoint_id,
                "merged_candidate_id": merged_candidate_id,
                "reason": reason,
            },
        )
        return checkpoint

    def latest_checkpoint(self, run_id: str) -> dict[str, Any] | None:
        return self.db.latest_checkpoint(run_id)

    def list_checkpoints(self, run_id: str) -> list[dict[str, Any]]:
        return self.db.list_checkpoints(run_id)

    def create_decision_packet(
        self,
        *,
        run_id: str,
        decision_id: str,
        task_id: str | None,
        failure_class: str,
        summary: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        packet = self.db.insert_decision_packet(
            run_id=run_id,
            decision_id=decision_id,
            task_id=task_id,
            failure_class=failure_class,
            summary=summary,
            payload=payload,
        )
        self.record_event(
            run_id=run_id,
            event_type="HumanDecisionRequired",
            node_id=decision_id,
            payload={
                "decision_id": decision_id,
                "task_id": task_id,
                "failure_class": failure_class,
                "summary": summary,
            },
        )
        return packet

    def list_decision_packets(self, run_id: str) -> list[dict[str, Any]]:
        return self.db.list_decision_packets(run_id)
```

- [ ] **Step 5: Run workflow store tests**

Run:

```bash
cd skills/agent-runway && python -m pytest evals/test_workflow_store.py -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add skills/agent-runway/scripts/agentrunway/db.py skills/agent-runway/scripts/agentrunway/workflow_store.py skills/agent-runway/evals/test_workflow_store.py
git commit -m "feat: add AgentRunway workflow store"
```

---

### Task 2: Add Failure Classifier

```yaml agentrunway-task
task_id: task_002
title: Add Failure Classifier
risk: medium
phase: implementation
dependencies: [task_001]
spec_refs: [S1.7.5, S1.9, S1.15]
file_claims:
  - {path: skills/agent-runway/scripts/agentrunway/failure_classifier.py, mode: owned}
  - {path: skills/agent-runway/evals/test_failure_classifier.py, mode: owned}
acceptance_commands:
  - cd skills/agent-runway && python -m pytest evals/test_failure_classifier.py -v
required_skills: [using-superpowers, test-driven-development]
serial: true
```

**Files:**
- Create: `skills/agent-runway/scripts/agentrunway/failure_classifier.py`
- Create: `skills/agent-runway/evals/test_failure_classifier.py`

- [ ] **Step 1: Write failing classifier tests**

Create `skills/agent-runway/evals/test_failure_classifier.py`:

```python
from __future__ import annotations

from agentrunway.failure_classifier import FailureClass, classify_gate_failure, classify_merge_failure


def test_review_needs_context_classifies_full_context() -> None:
    result = classify_gate_failure(
        gate="review",
        status="needs_context",
        result={"findings": [{"body": "Need full tree"}]},
        candidate={"changed_files": ["src/tool.py"]},
        task_acceptance_commands=["python -m pytest"],
    )

    assert result.failure_class == FailureClass.NEEDS_FULL_CONTEXT.value
    assert result.next_action == "rerun_review_full_tree"
    assert result.consume_implementer_retry is False


def test_review_mentions_accepted_work_classifies_rebase() -> None:
    result = classify_gate_failure(
        gate="review",
        status="changes_requested",
        result={"findings": [{"body": "Candidate misses prior accepted work from task_001"}]},
        candidate={"changed_files": ["skills/agent-runway/scripts/agentrunway/invocation.py"]},
        task_acceptance_commands=["python -m pytest"],
    )

    assert result.failure_class == FailureClass.NEEDS_REBASE.value
    assert result.next_action == "rerun_implementer_from_latest_checkpoint"
    assert result.consume_implementer_retry is False


def test_verifier_failed_command_classifies_implementer_retry() -> None:
    result = classify_gate_failure(
        gate="verification",
        status="failed",
        result={"checks": [{"command": "python -m pytest", "status": "failed"}]},
        candidate={"changed_files": ["src/tool.py"]},
        task_acceptance_commands=["python -m pytest"],
    )

    assert result.failure_class == FailureClass.NEEDS_IMPLEMENTER_RETRY.value
    assert result.next_action == "rerun_implementer_with_gate_evidence"
    assert result.consume_implementer_retry is True


def test_verifier_blocked_environment_classifies_infra_fix() -> None:
    result = classify_gate_failure(
        gate="verification",
        status="blocked",
        result={"checks": [{"command": "python -m pytest", "status": "blocked", "error": "adapter missing"}]},
        candidate={"changed_files": ["src/tool.py"]},
        task_acceptance_commands=["python -m pytest"],
    )

    assert result.failure_class == FailureClass.NEEDS_INFRA_FIX.value
    assert result.next_action == "fix_infrastructure"
    assert result.consume_implementer_retry is False


def test_missing_plan_metadata_classifies_plan_fix() -> None:
    result = classify_gate_failure(
        gate="review",
        status="changes_requested",
        result={"findings": [{"body": "file claim is missing for invocation.py"}]},
        candidate={"changed_files": ["skills/agent-runway/scripts/agentrunway/invocation.py"]},
        task_acceptance_commands=[],
    )

    assert result.failure_class == FailureClass.NEEDS_PLAN_FIX.value
    assert result.next_action == "fix_plan"


def test_first_merge_conflict_rebase_then_repeated_human_decision() -> None:
    first = classify_merge_failure(previous_conflicts=0, error="conflict in runner.py")
    repeated = classify_merge_failure(previous_conflicts=1, error="conflict in runner.py")

    assert first.failure_class == FailureClass.NEEDS_REBASE.value
    assert first.next_action == "rerun_implementer_from_latest_checkpoint"
    assert repeated.failure_class == FailureClass.NEEDS_HUMAN_DECISION.value
    assert repeated.next_action == "write_decision_packet"
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
cd skills/agent-runway && python -m pytest evals/test_failure_classifier.py -v
```

Expected: fails with `ModuleNotFoundError: No module named 'agentrunway.failure_classifier'`.

- [ ] **Step 3: Implement classifier**

Create `skills/agent-runway/scripts/agentrunway/failure_classifier.py`:

```python
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Literal


class FailureClass(str, Enum):
    NEEDS_REBASE = "needs_rebase"
    NEEDS_FULL_CONTEXT = "needs_full_context"
    NEEDS_PLAN_FIX = "needs_plan_fix"
    NEEDS_SPLIT = "needs_split"
    NEEDS_IMPLEMENTER_RETRY = "needs_implementer_retry"
    NEEDS_INFRA_FIX = "needs_infra_fix"
    NEEDS_HUMAN_DECISION = "needs_human_decision"
    TERMINAL_REJECTED = "terminal_rejected"


@dataclass(frozen=True)
class FailureClassification:
    failure_class: str
    next_action: str
    consume_implementer_retry: bool
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value.lower()
    if isinstance(value, dict):
        return " ".join(_text(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(_text(item) for item in value)
    return str(value).lower()


def classify_gate_failure(
    *,
    gate: Literal["review", "verification"],
    status: str,
    result: dict[str, Any],
    candidate: dict[str, Any],
    task_acceptance_commands: list[str] | tuple[str, ...],
) -> FailureClassification:
    body = _text(result)
    changed_files = list(candidate.get("changed_files") or [])
    has_acceptance = bool(task_acceptance_commands)
    if status == "needs_context" or "need full" in body or "insufficient context" in body:
        return FailureClassification(
            failure_class=FailureClass.NEEDS_FULL_CONTEXT.value,
            next_action="rerun_review_full_tree" if gate == "review" else "rerun_verifier_full_tree",
            consume_implementer_retry=False,
            summary=f"{gate} requires broader context",
        )
    if "prior accepted" in body or "accepted work" in body or "latest checkpoint" in body or "stale base" in body:
        return FailureClassification(
            failure_class=FailureClass.NEEDS_REBASE.value,
            next_action="rerun_implementer_from_latest_checkpoint",
            consume_implementer_retry=False,
            summary=f"{gate} failure points to stale candidate base",
        )
    if "file claim" in body or "spec ref" in body or "acceptance command" in body or (changed_files and not has_acceptance and gate == "review"):
        return FailureClassification(
            failure_class=FailureClass.NEEDS_PLAN_FIX.value,
            next_action="fix_plan",
            consume_implementer_retry=False,
            summary=f"{gate} failure points to plan metadata",
        )
    if status == "blocked" or "adapter" in body or "sandbox" in body or "environment" in body or "preflight" in body:
        return FailureClassification(
            failure_class=FailureClass.NEEDS_INFRA_FIX.value,
            next_action="fix_infrastructure",
            consume_implementer_retry=False,
            summary=f"{gate} failure is infrastructure-related",
        )
    if status in {"failed", "changes_requested"} and (changed_files or has_acceptance):
        return FailureClassification(
            failure_class=FailureClass.NEEDS_IMPLEMENTER_RETRY.value,
            next_action="rerun_implementer_with_gate_evidence",
            consume_implementer_retry=True,
            summary=f"{gate} failure is actionable inside task scope",
        )
    return FailureClassification(
        failure_class=FailureClass.TERMINAL_REJECTED.value,
        next_action="block_task",
        consume_implementer_retry=False,
        summary=f"{gate} returned terminal status {status}",
    )


def classify_merge_failure(*, previous_conflicts: int, error: str) -> FailureClassification:
    if previous_conflicts < 1:
        return FailureClassification(
            failure_class=FailureClass.NEEDS_REBASE.value,
            next_action="rerun_implementer_from_latest_checkpoint",
            consume_implementer_retry=False,
            summary=f"merge conflict can be retried from latest checkpoint: {error}",
        )
    return FailureClassification(
        failure_class=FailureClass.NEEDS_HUMAN_DECISION.value,
        next_action="write_decision_packet",
        consume_implementer_retry=False,
        summary=f"repeated merge conflict requires operator decision: {error}",
    )
```

- [ ] **Step 4: Run classifier tests**

Run:

```bash
cd skills/agent-runway && python -m pytest evals/test_failure_classifier.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add skills/agent-runway/scripts/agentrunway/failure_classifier.py skills/agent-runway/evals/test_failure_classifier.py
git commit -m "feat: classify AgentRunway recovery failures"
```

---

### Task 3: Add Checkpoint-Aware Scheduler

```yaml agentrunway-task
task_id: task_003
title: Add Checkpoint-Aware Scheduler
risk: medium
phase: implementation
dependencies: [task_002]
spec_refs: [S1.7.2, S1.8, S1.12]
file_claims:
  - {path: skills/agent-runway/scripts/agentrunway/scheduler.py, mode: owned}
  - {path: skills/agent-runway/evals/test_checkpoint_scheduler.py, mode: owned}
acceptance_commands:
  - cd skills/agent-runway && python -m pytest evals/test_checkpoint_scheduler.py -v
required_skills: [using-superpowers, test-driven-development]
serial: true
```

**Files:**
- Modify: `skills/agent-runway/scripts/agentrunway/scheduler.py`
- Create: `skills/agent-runway/evals/test_checkpoint_scheduler.py`

- [ ] **Step 1: Write failing scheduler tests**

Create `skills/agent-runway/evals/test_checkpoint_scheduler.py`:

```python
from __future__ import annotations

from agentrunway.models import FileClaim, TaskSpec
from agentrunway.scheduler import ready_tasks_after_checkpoints, schedule_safe_wave


def _task(
    task_id: str,
    *,
    deps: tuple[str, ...] = (),
    path: str = "src/a.py",
    risk: str = "low",
    serial: bool = False,
    mode: str = "owned",
) -> TaskSpec:
    return TaskSpec(
        task_id=task_id,
        title=task_id,
        risk=risk,
        phase="implementation",
        dependencies=deps,
        spec_refs=("S1.1",),
        file_claims=(FileClaim(path=path, mode=mode),),
        acceptance_commands=("python -m pytest",),
        required_skills=("test-driven-development",),
        resource_keys=(),
        serial=serial,
        objective="demo",
        line=1,
    )


def test_ready_tasks_require_dependency_checkpoints() -> None:
    tasks = [
        _task("task_001", path="src/a.py"),
        _task("task_002", deps=("task_001",), path="src/b.py"),
    ]

    assert [task.task_id for task in ready_tasks_after_checkpoints(tasks, completed_checkpoints=set(), completed_tasks=set())] == ["task_001"]
    assert [task.task_id for task in ready_tasks_after_checkpoints(tasks, completed_checkpoints={"task_001"}, completed_tasks={"task_001"})] == ["task_002"]


def test_safe_wave_runs_disjoint_low_risk_tasks_together() -> None:
    tasks = [_task("task_001", path="src/a.py"), _task("task_002", path="src/b.py")]

    assert [task.task_id for task in schedule_safe_wave(tasks)] == ["task_001", "task_002"]


def test_safe_wave_serializes_overlapping_owned_claims() -> None:
    tasks = [_task("task_001", path="src/**", risk="high"), _task("task_002", path="src/a.py")]

    assert [task.task_id for task in schedule_safe_wave(tasks)] == ["task_001"]


def test_safe_wave_serializes_high_risk_task() -> None:
    tasks = [_task("task_001", path="src/a.py", risk="high"), _task("task_002", path="src/b.py")]

    assert [task.task_id for task in schedule_safe_wave(tasks)] == ["task_001"]
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
cd skills/agent-runway && python -m pytest evals/test_checkpoint_scheduler.py -v
```

Expected: fails importing `ready_tasks_after_checkpoints` and `schedule_safe_wave`.

- [ ] **Step 3: Extend scheduler**

Modify `skills/agent-runway/scripts/agentrunway/scheduler.py` by keeping `schedule_waves()` and adding:

```python
import fnmatch
```

Then add these helpers after `schedule_waves()`:

```python
def ready_tasks_after_checkpoints(
    tasks: list[TaskSpec],
    *,
    completed_checkpoints: set[str],
    completed_tasks: set[str],
) -> list[TaskSpec]:
    ready = [
        task
        for task in tasks
        if task.task_id not in completed_tasks
        and set(task.dependencies) <= completed_checkpoints
    ]
    return sorted(ready, key=lambda task: (RISK_ORDER.get(task.risk, 9), task.task_id))


def _claim_patterns(task: TaskSpec) -> list[str]:
    return [claim.path for claim in task.file_claims if claim.mode in {"owned", "shared_append"}]


def _claim_overlaps(left: str, right: str) -> bool:
    if left == right:
        return True
    if any(ch in left for ch in "*?[") and fnmatch.fnmatch(right, left):
        return True
    if any(ch in right for ch in "*?[") and fnmatch.fnmatch(left, right):
        return True
    if left.endswith("/**") and right.startswith(left[:-3]):
        return True
    if right.endswith("/**") and left.startswith(right[:-3]):
        return True
    return False


def _tasks_conflict(left: TaskSpec, right: TaskSpec) -> bool:
    if left.serial or right.serial:
        return True
    if left.risk == "high" or right.risk == "high":
        return True
    for left_claim in _claim_patterns(left):
        for right_claim in _claim_patterns(right):
            if _claim_overlaps(left_claim, right_claim):
                return True
    return bool(set(left.resource_keys) & set(right.resource_keys))


def schedule_safe_wave(ready: list[TaskSpec]) -> list[TaskSpec]:
    ordered = sorted(ready, key=lambda task: (RISK_ORDER.get(task.risk, 9), task.task_id))
    wave: list[TaskSpec] = []
    for task in ordered:
        if any(_tasks_conflict(task, selected) for selected in wave):
            if not wave:
                return [task]
            continue
        wave.append(task)
    return wave
```

- [ ] **Step 4: Run scheduler tests**

Run:

```bash
cd skills/agent-runway && python -m pytest evals/test_checkpoint_scheduler.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Run existing scheduler tests**

Run:

```bash
cd skills/agent-runway && python -m pytest evals/test_scheduler.py -v
```

Expected: existing scheduler tests still pass.

- [ ] **Step 6: Commit**

```bash
git add skills/agent-runway/scripts/agentrunway/scheduler.py skills/agent-runway/evals/test_checkpoint_scheduler.py
git commit -m "feat: schedule AgentRunway tasks from checkpoints"
```

---

### Task 4: Add Integration Manager

```yaml agentrunway-task
task_id: task_004
title: Add Integration Manager
risk: medium
phase: implementation
dependencies: [task_003]
spec_refs: [S1.6, S1.7.4, S1.8.2, S1.9.1, S1.15]
file_claims:
  - {path: skills/agent-runway/scripts/agentrunway/integration_manager.py, mode: owned}
  - {path: skills/agent-runway/evals/test_integration_manager.py, mode: owned}
acceptance_commands:
  - cd skills/agent-runway && python -m pytest evals/test_integration_manager.py -v
required_skills: [using-superpowers, test-driven-development]
serial: true
```

**Files:**
- Create: `skills/agent-runway/scripts/agentrunway/integration_manager.py`
- Create: `skills/agent-runway/evals/test_integration_manager.py`

- [ ] **Step 1: Write failing integration manager tests**

Create `skills/agent-runway/evals/test_integration_manager.py`:

```python
from __future__ import annotations

import subprocess
from pathlib import Path

from agentrunway.db import AgentRunwayDb
from agentrunway.git_ops import Git
from agentrunway.integration_manager import IntegrationManager
from agentrunway.merge_queue import MergeCandidate
from agentrunway.workflow_store import WorkflowStore


def _commit(path: Path, rel: str, text: str, message: str) -> str:
    target = path / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    subprocess.run(["git", "add", rel], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", message], cwd=path, check=True, capture_output=True, text=True)
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=path, check=True, capture_output=True, text=True).stdout.strip()


def test_merge_selected_candidate_records_checkpoint(git_repo: Path, tmp_path: Path) -> None:
    db = AgentRunwayDb.open(tmp_path / "state.sqlite")
    store = WorkflowStore(db)
    main = tmp_path / "main"
    subprocess.run(["git", "worktree", "add", "-b", "agentrunway/test/main", str(main), "HEAD"], cwd=git_repo, check=True, capture_output=True, text=True)
    initial = Git(main).rev_parse("HEAD")
    store.create_checkpoint(
        run_id="run-1",
        checkpoint_id="cp-000",
        commit_sha=initial,
        parent_checkpoint_id=None,
        merged_candidate_id=None,
        reason="initial",
    )

    worker = tmp_path / "worker"
    subprocess.run(["git", "worktree", "add", "-b", "agentrunway/test/worker", str(worker), "HEAD"], cwd=git_repo, check=True, capture_output=True, text=True)
    commit = _commit(worker, "src/merged.py", "VALUE = 'merged'\n", "candidate")
    candidate_id = db.enqueue_merge_candidate(
        task_id="task_001",
        worker_id="task_001-implementer-001",
        commits=(commit,),
        changed_files=("src/merged.py",),
        status="merge_ready",
    )

    manager = IntegrationManager(db=db, store=store, run_id="run-1", main_worktree=main)
    checkpoint = manager.merge_selected_candidate(
        candidate_id=candidate_id,
        candidate=MergeCandidate(
            task_id="task_001",
            worker_id="task_001-implementer-001",
            commits=(commit,),
            changed_files=("src/merged.py",),
        ),
    )

    assert (main / "src" / "merged.py").read_text(encoding="utf-8") == "VALUE = 'merged'\n"
    assert checkpoint["parent_checkpoint_id"] == "cp-000"
    assert checkpoint["merged_candidate_id"] == candidate_id
    assert db.list_merge_candidates()[0]["status"] == "merged"
    assert store.latest_checkpoint("run-1")["checkpoint_id"] == checkpoint["checkpoint_id"]


def test_merge_conflict_records_failed_activity(git_repo: Path, tmp_path: Path) -> None:
    db = AgentRunwayDb.open(tmp_path / "state.sqlite")
    store = WorkflowStore(db)
    main = tmp_path / "main"
    subprocess.run(["git", "worktree", "add", "-b", "agentrunway/test-conflict/main", str(main), "HEAD"], cwd=git_repo, check=True, capture_output=True, text=True)
    initial = Git(main).rev_parse("HEAD")
    store.create_checkpoint(
        run_id="run-1",
        checkpoint_id="cp-000",
        commit_sha=initial,
        parent_checkpoint_id=None,
        merged_candidate_id=None,
        reason="initial",
    )
    _commit(main, "src/conflict.py", "VALUE = 'main'\n", "main change")

    worker = tmp_path / "worker"
    subprocess.run(["git", "worktree", "add", "-b", "agentrunway/test-conflict/worker", str(worker), initial], cwd=git_repo, check=True, capture_output=True, text=True)
    commit = _commit(worker, "src/conflict.py", "VALUE = 'worker'\n", "worker change")
    candidate_id = db.enqueue_merge_candidate(
        task_id="task_001",
        worker_id="task_001-implementer-001",
        commits=(commit,),
        changed_files=("src/conflict.py",),
        status="merge_ready",
    )

    manager = IntegrationManager(db=db, store=store, run_id="run-1", main_worktree=main)

    try:
        manager.merge_selected_candidate(
            candidate_id=candidate_id,
            candidate=MergeCandidate(
                task_id="task_001",
                worker_id="task_001-implementer-001",
                commits=(commit,),
                changed_files=("src/conflict.py",),
            ),
        )
    except Exception as exc:
        assert "conflict" in str(exc).lower()
    else:
        raise AssertionError("expected merge conflict")

    candidate = db.list_merge_candidates()[0]
    assert candidate["status"] == "merge_conflict"
    events = store.list_workflow_events("run-1")
    assert "ActivityFailed" in [event["event_type"] for event in events]
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
cd skills/agent-runway && python -m pytest evals/test_integration_manager.py -v
```

Expected: fails with `ModuleNotFoundError: No module named 'agentrunway.integration_manager'`.

- [ ] **Step 3: Implement IntegrationManager**

Create `skills/agent-runway/scripts/agentrunway/integration_manager.py`:

```python
from __future__ import annotations

from pathlib import Path

from .db import AgentRunwayDb
from .git_ops import Git
from .merge_queue import MergeCandidate, MergeConflictError, apply_candidate
from .workflow_store import ActivityStatus, WorkflowStore


class IntegrationManager:
    def __init__(self, *, db: AgentRunwayDb, store: WorkflowStore, run_id: str, main_worktree: Path):
        self.db = db
        self.store = store
        self.run_id = run_id
        self.main_worktree = main_worktree

    def _next_checkpoint_id(self) -> str:
        count = len(self.store.list_checkpoints(self.run_id))
        return f"cp-{count:03d}"

    def merge_selected_candidate(self, *, candidate_id: int, candidate: MergeCandidate) -> dict[str, object]:
        activity_id = f"{candidate.task_id}.merge.{candidate_id}"
        self.store.start_activity(
            run_id=self.run_id,
            activity_id=activity_id,
            idempotency_key=f"{self.run_id}:{candidate.task_id}:merge:{candidate_id}",
            task_id=candidate.task_id,
            activity_type="merge",
            input_refs={"candidate_id": candidate_id, "commits": list(candidate.commits)},
        )
        latest = self.store.latest_checkpoint(self.run_id)
        main_git = Git(self.main_worktree)
        try:
            apply_candidate(main_git, candidate)
        except MergeConflictError as exc:
            self.db.set_merge_candidate_status(candidate_id, "merge_conflict", str(exc))
            self.store.complete_activity(
                activity_id=activity_id,
                status=ActivityStatus.FAILED,
                output_refs={"error": str(exc)},
                failure_class="needs_rebase",
            )
            raise
        self.db.set_merge_candidate_status(candidate_id, "merged")
        self.db.set_worker_state(candidate.worker_id, "merged")
        checkpoint_id = self._next_checkpoint_id()
        checkpoint = self.store.create_checkpoint(
            run_id=self.run_id,
            checkpoint_id=checkpoint_id,
            commit_sha=main_git.rev_parse("HEAD"),
            parent_checkpoint_id=str(latest["checkpoint_id"]) if latest else None,
            merged_candidate_id=candidate_id,
            reason=f"merged:{candidate.task_id}",
        )
        self.store.complete_activity(
            activity_id=activity_id,
            status=ActivityStatus.COMPLETED,
            output_refs={"checkpoint_id": checkpoint_id, "commit_sha": checkpoint["commit_sha"]},
            failure_class=None,
        )
        return checkpoint
```

- [ ] **Step 4: Run integration manager tests**

Run:

```bash
cd skills/agent-runway && python -m pytest evals/test_integration_manager.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add skills/agent-runway/scripts/agentrunway/integration_manager.py skills/agent-runway/evals/test_integration_manager.py
git commit -m "feat: merge AgentRunway candidates through checkpoints"
```

---

### Task 5: Wire Immediate Integration Into Runner

```yaml agentrunway-task
task_id: task_005
title: Wire Immediate Integration Into Runner
risk: high
phase: implementation
dependencies: [task_004]
spec_refs: [S1.6, S1.8, S1.9, S1.13, S1.15]
file_claims:
  - {path: skills/agent-runway/scripts/agentrunway/runner.py, mode: owned}
  - {path: skills/agent-runway/evals/test_runner_production_e2e.py, mode: shared_append}
acceptance_commands:
  - cd skills/agent-runway && python -m pytest evals/test_runner_production_e2e.py::test_high_risk_task_ranks_two_candidates -v
  - cd skills/agent-runway && python -m pytest evals/test_integration_manager.py -v
required_skills: [using-superpowers, test-driven-development]
serial: true
```

**Files:**
- Modify: `skills/agent-runway/scripts/agentrunway/runner.py`
- Modify: `skills/agent-runway/evals/test_runner_production_e2e.py`

- [ ] **Step 1: Add a runner regression for checkpoint rows**

Append this test to `skills/agent-runway/evals/test_runner_production_e2e.py`:

```python
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
    checkpoints = conn.execute("SELECT checkpoint_id, merged_candidate_id, reason FROM checkpoints ORDER BY checkpoint_id").fetchall()
    activities = conn.execute("SELECT activity_type, status FROM activities ORDER BY activity_id").fetchall()

    assert payload["status"] == "finished"
    assert [(row["checkpoint_id"], row["merged_candidate_id"], row["reason"]) for row in checkpoints] == [
        ("cp-000", None, "initial"),
        ("cp-001", 1, "merged:task_001"),
    ]
    assert ("merge", "completed") in [(row["activity_type"], row["status"]) for row in activities]
```

- [ ] **Step 2: Run the regression and verify it fails**

Run:

```bash
cd skills/agent-runway && python -m pytest evals/test_runner_production_e2e.py::test_finished_run_records_initial_and_task_checkpoints -v
```

Expected: fails because `checkpoints` or `activities` rows are missing.

- [ ] **Step 3: Import workflow and integration helpers**

Modify imports in `skills/agent-runway/scripts/agentrunway/runner.py`:

```python
from .integration_manager import IntegrationManager
from .workflow_store import WorkflowStore
```

- [ ] **Step 4: Create initial checkpoint after run main worktree creation**

In `run()`, immediately after `db.register_worktree(...)` for `main_worktree`, add:

```python
    workflow_store = WorkflowStore(db)
    workflow_store.create_checkpoint(
        run_id=run_id,
        checkpoint_id="cp-000",
        commit_sha=Git(main_worktree).rev_parse("HEAD"),
        parent_checkpoint_id=None,
        merged_candidate_id=None,
        reason="initial",
    )
    integration_manager = IntegrationManager(
        db=db,
        store=workflow_store,
        run_id=run_id,
        main_worktree=main_worktree,
    )
```

- [ ] **Step 5: Replace delayed merge with immediate selected-candidate merge**

In `run()`, find the `if ready_candidates:` block that ranks candidates. After non-selected candidates are archived, add:

```python
                selected = _merge_candidate(db, int(selection.selected_candidate_id))
                merge_candidate = MergeCandidate(
                    task_id=selected["task_id"],
                    worker_id=selected["worker_id"],
                    commits=tuple(selected["commits"]),
                    changed_files=tuple(selected["changed_files"]),
                )
                try:
                    integration_manager.merge_selected_candidate(
                        candidate_id=int(selected["id"]),
                        candidate=merge_candidate,
                    )
                except MergeConflictError as exc:
                    db.set_task_status(selected["task_id"], "blocked")
                    journal.record(
                        "agentrunway.merge_conflict",
                        build_event_payload(
                            run_id,
                            "merge",
                            "partial",
                            "merge conflict",
                            task_id=selected["task_id"],
                            worker_id=selected["worker_id"],
                            candidate_id=selected["id"],
                            error=str(exc),
                        ),
                    )
                    _record_run_blocked(journal, run_id=run_id, task_id=str(selected["task_id"]), reason="merge_conflict")
                else:
                    worker = db.get_worker(str(selected["worker_id"]))
                    db.set_worktree_lifecycle(str(worker["worktree_path"]), lifecycle_for_worker(role="implementer", state="merged"))
                    db.set_task_status(selected["task_id"], "merged")
```

Then remove the final post-task loop that starts with:

```python
    for candidate in db.list_merge_candidates():
        if candidate["status"] != "merge_ready":
            continue
```

Do not remove the final artifact graph, task snapshot, run status, AgentLens close, or `run.json` update code after that loop.

- [ ] **Step 6: Run focused runner tests**

Run:

```bash
cd skills/agent-runway && python -m pytest \
  evals/test_runner_production_e2e.py::test_finished_run_records_initial_and_task_checkpoints \
  evals/test_runner_production_e2e.py::test_high_risk_task_ranks_two_candidates \
  -v
```

Expected: both tests pass. The high-risk test should still show one merged candidate and one `not_selected` candidate.

- [ ] **Step 7: Commit**

```bash
git add skills/agent-runway/scripts/agentrunway/runner.py skills/agent-runway/evals/test_runner_production_e2e.py
git commit -m "feat: merge AgentRunway candidates immediately"
```

---

### Task 6: Add Dependent-Task Integration Regression

```yaml agentrunway-task
task_id: task_006
title: Add Dependent-Task Integration Regression
risk: high
phase: implementation
dependencies: [task_005]
spec_refs: [S1.8, S1.12, S1.15]
file_claims:
  - {path: skills/agent-runway/evals/fixtures/fake-bin/codex, mode: owned}
  - {path: skills/agent-runway/evals/test_durable_orchestrator_e2e.py, mode: owned}
acceptance_commands:
  - cd skills/agent-runway && python -m pytest evals/test_durable_orchestrator_e2e.py -v
required_skills: [using-superpowers, test-driven-development]
serial: true
```

**Files:**
- Modify: `skills/agent-runway/evals/fixtures/fake-bin/codex`
- Create: `skills/agent-runway/evals/test_durable_orchestrator_e2e.py`

- [ ] **Step 1: Write failing dependent-task test**

Create `skills/agent-runway/evals/test_durable_orchestrator_e2e.py`:

```python
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "agentrunway.py"
FAKE_BIN = ROOT / "evals" / "fixtures" / "fake-bin"


def _write_dependent_plan(repo: Path) -> tuple[Path, Path]:
    spec = repo / "spec.md"
    plan = repo / "plan.md"
    spec.write_text(
        "# Spec\n\n"
        "## Producer\n\nCreate producer file.\n\n"
        "## Consumer\n\nCreate consumer file after producer exists.\n",
        encoding="utf-8",
    )
    plan.write_text(
        "## Task 1: Producer\n\n"
        "```yaml agentrunway-task\n"
        "task_id: task_001\n"
        "title: Producer\n"
        "risk: low\n"
        "phase: implementation\n"
        "dependencies: []\n"
        "spec_refs: [S1.1]\n"
        "file_claims:\n"
        "  - {path: src/producer.py, mode: owned}\n"
        "acceptance_commands: [python -m pytest]\n"
        "required_skills: [test-driven-development]\n"
        "```\n"
        "Create producer.\n\n"
        "## Task 2: Consumer\n\n"
        "```yaml agentrunway-task\n"
        "task_id: task_002\n"
        "title: Consumer\n"
        "risk: low\n"
        "phase: implementation\n"
        "dependencies: [task_001]\n"
        "spec_refs: [S1.2]\n"
        "file_claims:\n"
        "  - {path: src/consumer.py, mode: owned}\n"
        "acceptance_commands: [python -m pytest]\n"
        "required_skills: [test-driven-development]\n"
        "```\n"
        "Create consumer only after producer is visible.\n",
        encoding="utf-8",
    )
    return plan, spec


def test_dependent_task_sees_previous_task_checkpoint(git_repo: Path, isolated_home: Path) -> None:
    plan, spec = _write_dependent_plan(git_repo)
    env = os.environ.copy()
    env["PATH"] = f"{FAKE_BIN}{os.pathsep}{env['PATH']}"
    env["AGENTRUNWAY_FAKE_TARGET_MAP"] = "task_001=src/producer.py;task_002=src/consumer.py"
    env["AGENTRUNWAY_FAKE_REQUIRED_FILE_MAP"] = "task_002=src/producer.py"
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
    main = Path(payload["main_worktree"])

    assert payload["status"] == "finished"
    assert (main / "src" / "producer.py").read_text(encoding="utf-8") == "VALUE = 'codex'\n"
    assert (main / "src" / "consumer.py").read_text(encoding="utf-8") == "VALUE = 'codex'\n"

    conn = sqlite3.connect(payload["state_db"])
    conn.row_factory = sqlite3.Row
    checkpoints = conn.execute("SELECT checkpoint_id, reason FROM checkpoints ORDER BY checkpoint_id").fetchall()
    assert [(row["checkpoint_id"], row["reason"]) for row in checkpoints] == [
        ("cp-000", "initial"),
        ("cp-001", "merged:task_001"),
        ("cp-002", "merged:task_002"),
    ]
```

- [ ] **Step 2: Run test and verify fake adapter cannot yet map task targets**

Run:

```bash
cd skills/agent-runway && python -m pytest evals/test_durable_orchestrator_e2e.py -v
```

Expected: fails because fake Codex writes the default target or does not enforce `AGENTRUNWAY_FAKE_REQUIRED_FILE_MAP`.

- [ ] **Step 3: Extend fake Codex task-specific controls**

Modify `skills/agent-runway/evals/fixtures/fake-bin/codex`. Add this helper after `sequence_value`:

```python
def map_value(name: str, task_id: str, default: str | None = None) -> str | None:
    raw = os.environ.get(name, "")
    if not raw:
        return default
    for pair in raw.split(";"):
        if not pair.strip() or "=" not in pair:
            continue
        key, value = pair.split("=", 1)
        if key.strip() == task_id:
            return value.strip()
    return default
```

In the implementer branch, replace:

```python
    target = Path(os.environ.get("AGENTRUNWAY_FAKE_TARGET", "src/codex_worker.py"))
```

with:

```python
    task_id = os.environ["AGENTRUNWAY_TASK_ID"]
    default_target = os.environ.get("AGENTRUNWAY_FAKE_TARGET", "src/codex_worker.py")
    target = Path(map_value("AGENTRUNWAY_FAKE_TARGET_MAP", task_id, default_target) or default_target)
    required = map_value("AGENTRUNWAY_FAKE_REQUIRED_FILE_MAP", task_id)
    if required and not Path(required).exists():
        output.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": "agentrunway.worker_result.v1",
            "worker_id": os.environ["AGENTRUNWAY_WORKER_ID"],
            "task_id": task_id,
            "role": role,
            "status": "failed",
            "changed_files": [],
            "commits": [],
            "summary": f"required file missing: {required}",
            "commands_run": [],
            "method_audit": {"superpowers_used": True, "tdd_red": "failed", "tdd_green": "failed"},
            "residual_risks": [f"required file missing: {required}"],
        }
        output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        print(f"fake codex missing required file {required}")
        return 1
```

The `required` check runs relative to the worker worktree cwd. Because `IntegrationManager` cherry-picks `task_001`'s commit into run main before the runner dispatches `task_002`, the new worker worktree is created from run-main HEAD and the required file is visible — that is what the test is asserting.

- [ ] **Step 4: Run dependent integration test**

Run:

```bash
cd skills/agent-runway && python -m pytest evals/test_durable_orchestrator_e2e.py -v
```

Expected: test passes. This proves `task_002` started from run main after `task_001` checkpoint.

- [ ] **Step 5: Run fake adapter smoke tests**

Run:

```bash
cd skills/agent-runway && python -m pytest evals/test_runner_production_e2e.py::test_codex_fake_implementer_reaches_validated_candidate -v
```

Expected: existing fake Codex behavior still passes without task maps.

- [ ] **Step 6: Commit**

```bash
git add skills/agent-runway/evals/fixtures/fake-bin/codex skills/agent-runway/evals/test_durable_orchestrator_e2e.py
git commit -m "test: prove AgentRunway dependent tasks see checkpoints"
```

---

### Task 7: Surface Checkpoints and Failure Classes in Summary

```yaml agentrunway-task
task_id: task_007
title: Surface Checkpoints and Failure Classes in Summary
risk: medium
phase: implementation
dependencies: [task_006]
spec_refs: [S1.7.6, S1.11, S1.15]
file_claims:
  - {path: skills/agent-runway/scripts/agentrunway/run_summary.py, mode: owned}
  - {path: skills/agent-runway/evals/test_run_summary.py, mode: shared_append}
acceptance_commands:
  - cd skills/agent-runway && python -m pytest evals/test_run_summary.py -v
required_skills: [using-superpowers, test-driven-development]
serial: true
```

**Files:**
- Modify: `skills/agent-runway/scripts/agentrunway/run_summary.py`
- Modify: `skills/agent-runway/evals/test_run_summary.py`

- [ ] **Step 1: Add failing summary test**

Append this test to `skills/agent-runway/evals/test_run_summary.py`:

```python
def test_run_summary_includes_checkpoint_graph_and_failure_class(tmp_path: Path) -> None:
    db = AgentRunwayDb.open(tmp_path / "state.sqlite")
    db.create_run(
        run_id="run-1",
        workspace_id="ws",
        repo_root=str(tmp_path),
        plan_path=str(tmp_path / "plan.md"),
        spec_path=None,
        plan_hash="plan",
        spec_hash=None,
        base_commit_sha="base",
        model_profile="default",
        allowed_dirty=False,
        apply_to_source=False,
    )
    db.insert_checkpoint(
        run_id="run-1",
        checkpoint_id="cp-000",
        commit_sha="base",
        parent_checkpoint_id=None,
        merged_candidate_id=None,
        reason="initial",
    )
    db.insert_activity(
        activity_id="task_001.review.001",
        run_id="run-1",
        idempotency_key="run-1:task_001:review:001",
        task_id="task_001",
        activity_type="review",
        status="failed",
        input_refs={},
    )
    db.update_activity(
        activity_id="task_001.review.001",
        status="failed",
        output_refs={"review_result": "artifacts/task_001/review_result.json"},
        failure_class="needs_plan_fix",
    )
    run_json = {
        "run_id": "run-1",
        "status": "blocked",
        "run_dir": str(tmp_path),
        "state_db": str(tmp_path / "state.sqlite"),
        "base_commit_sha": "base",
    }

    summary = build_run_summary(run_json=run_json, db=db)

    assert summary["latest_checkpoint"] == {"id": "cp-000", "commit": "base", "reason": "initial"}
    assert summary["graph"]["blocked"] == 1
    assert summary["blocked_node"] == "task_001.review.001"
    assert summary["failure_class"] == "needs_plan_fix"
    assert summary["required_human_decision"] == "fix plan"
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
cd skills/agent-runway && python -m pytest evals/test_run_summary.py::test_run_summary_includes_checkpoint_graph_and_failure_class -v
```

Expected: fails because summary lacks `latest_checkpoint`, `graph`, `blocked_node`, `failure_class`, and `required_human_decision`.

- [ ] **Step 3: Add activity summary helpers**

Modify `skills/agent-runway/scripts/agentrunway/run_summary.py`. Add this helper before `build_run_summary`:

```python
_HUMAN_DECISION_BY_FAILURE_CLASS = {
    "needs_plan_fix": "fix plan",
    "needs_split": "approve task split",
    "needs_human_decision": "inspect decision packet",
}


def _workflow_summary(db: AgentRunwayDb, run_id: str) -> dict[str, Any]:
    if not run_id:
        return {}
    latest = db.latest_checkpoint(run_id)
    activities = [
        dict(row)
        for row in db.conn.execute(
            "SELECT activity_id, activity_type, task_id, status, failure_class "
            "FROM activities WHERE run_id=? ORDER BY created_at, activity_id",
            (run_id,),
        ).fetchall()
    ]
    blocked = next((activity for activity in activities if activity.get("status") in {"failed", "blocked"}), None)
    failure_class = blocked.get("failure_class") if blocked else None
    human_decision = _HUMAN_DECISION_BY_FAILURE_CLASS.get(failure_class) if failure_class else None
    return {
        "latest_checkpoint": {
            "id": latest.get("checkpoint_id"),
            "commit": latest.get("commit_sha"),
            "reason": latest.get("reason"),
        } if latest else None,
        "graph": {
            "complete": sum(1 for activity in activities if activity.get("status") == "completed"),
            "ready": 0,
            "running": sum(1 for activity in activities if activity.get("status") == "started"),
            "blocked": sum(1 for activity in activities if activity.get("status") in {"failed", "blocked"}),
        },
        "blocked_node": blocked.get("activity_id") if blocked else None,
        "failure_class": failure_class,
        "next_automatic_action": None if human_decision else ("resume" if blocked else None),
        "required_human_decision": human_decision,
    }
```

The `WHERE run_id=?` filter prevents activity rows from other runs leaking into a summary when a single SQLite file is shared (e.g., resumed runs).

At the end of `build_run_summary`, before `return summary`, add:

```python
    summary.update(_workflow_summary(db, str(run_json.get("run_id"))))
```

- [ ] **Step 4: Run summary tests**

Run:

```bash
cd skills/agent-runway && python -m pytest evals/test_run_summary.py -v
```

Expected: all run summary tests pass.

- [ ] **Step 5: Commit**

```bash
git add skills/agent-runway/scripts/agentrunway/run_summary.py skills/agent-runway/evals/test_run_summary.py
git commit -m "feat: summarize AgentRunway checkpoints"
```

---

### Task 8: Final Verification and Documentation

```yaml agentrunway-task
task_id: task_008
title: Final Verification and Documentation
risk: low
phase: documentation
dependencies: [task_001, task_002, task_003, task_004, task_005, task_006, task_007]
spec_refs: [S1.15]
file_claims:
  - {path: skills/agent-runway/README.md, mode: owned}
  - {path: skills/agent-runway/references/worktree-policy.md, mode: owned}
  - {path: skills/agent-runway/references/context-policy.md, mode: owned}
acceptance_commands:
  - cd skills/agent-runway && ./evals/run.sh
  - cd skills/agent-runway && python3 -m py_compile scripts/agentrunway.py scripts/agentrunway/*.py scripts/agentrunway/adapters/*.py evals/*.py
  - git diff --check
  - graphify update .
required_skills: [using-superpowers, verification-before-completion]
serial: true
```

**Files:**
- Modify: `skills/agent-runway/README.md`
- Modify: `skills/agent-runway/references/worktree-policy.md`
- Modify: `skills/agent-runway/references/context-policy.md`

- [ ] **Step 1: Update README with durable integration section**

Add this section to `skills/agent-runway/README.md` after "Quality-First Hybrid Worktrees":

```markdown
## Durable Integration Orchestrator

AgentRunway advances run main as soon as a selected candidate passes review and
verification. Dependent tasks start from the latest run-main checkpoint instead
of the original base commit, so accepted earlier work is visible to later tasks.

The runner records workflow events, activity rows, checkpoint rows, and (when
written by gate failures in later slices) decision packets in SQLite with JSON
artifacts for audit. These records are the durable evidence later slices will
use to make `resume` advance from the last completed activity instead of
replaying worker state.

Merge-activity failures are classified through `FailureClassifier` into
recovery classes such as `needs_rebase`, `needs_full_context`, `needs_plan_fix`,
and `needs_infra_fix`. Routing review and verification failures through the
classifier is a follow-up slice.
```

- [ ] **Step 2: Update worktree policy**

Append this paragraph to `skills/agent-runway/references/worktree-policy.md`:

```markdown
## Checkpointed Run Main

Run main is checkpointed after creation and after every selected candidate merge.
Worker worktrees are created from the latest applicable run-main checkpoint.
Dependent tasks must not start until every declared dependency has a successful
checkpoint. This preserves isolation while ensuring later tasks see accepted
earlier work.
```

- [ ] **Step 3: Update context policy**

Append this paragraph to `skills/agent-runway/references/context-policy.md`:

```markdown
## Durable Summaries

Normal host context uses `summarize`, which reports the latest checkpoint,
activity graph counts, blocked node, failure class, next automatic action, and
required human decision. The activity counts are scoped to the current
`run_id`, so summaries remain meaningful when a SQLite state file is reused
across resumed runs. Raw worker logs remain deep-inspection artifacts and
should not be loaded into host context unless the summary points to them.
```

- [ ] **Step 4: Run focused tests**

Run:

```bash
cd skills/agent-runway && python -m pytest \
  evals/test_workflow_store.py \
  evals/test_failure_classifier.py \
  evals/test_checkpoint_scheduler.py \
  evals/test_integration_manager.py \
  evals/test_durable_orchestrator_e2e.py \
  evals/test_run_summary.py \
  evals/test_runner_production_e2e.py::test_finished_run_records_initial_and_task_checkpoints \
  evals/test_runner_production_e2e.py::test_high_risk_task_ranks_two_candidates \
  -v
```

Expected: all focused tests pass.

- [ ] **Step 5: Run final verification**

Run:

```bash
cd skills/agent-runway && ./evals/run.sh
cd skills/agent-runway && python3 -m py_compile scripts/agentrunway.py scripts/agentrunway/*.py scripts/agentrunway/adapters/*.py evals/*.py
cd /Users/kws/source/private/Archive && git diff --check
cd /Users/kws/source/private/Archive && graphify update .
cd /Users/kws/source/private/Archive && git status --short
```

Expected:

- full AgentRunway eval suite passes;
- Python files compile;
- `git diff --check` prints no errors;
- `graphify update .` completes;
- `git status --short` shows only intentional files before commit.

- [ ] **Step 6: Commit**

```bash
git add skills/agent-runway/README.md skills/agent-runway/references/worktree-policy.md skills/agent-runway/references/context-policy.md
git commit -m "docs: document AgentRunway durable integration"
```

---

## Final Completion Checklist

Run these commands after all tasks have landed:

```bash
cd /Users/kws/source/private/Archive
cd skills/agent-runway && ./evals/run.sh
cd /Users/kws/source/private/Archive/skills/agent-runway && python3 -m py_compile scripts/agentrunway.py scripts/agentrunway/*.py scripts/agentrunway/adapters/*.py evals/*.py
cd /Users/kws/source/private/Archive && git diff --check
cd /Users/kws/source/private/Archive && graphify update .
cd /Users/kws/source/private/Archive && git status --short
```

Expected final state (slice 1):

- AgentRunway writes workflow events, implement/review/verification/merge activity rows, checkpoint rows, and decision packets for human-input failures.
- Verified selected candidates cherry-pick into run main before dependent tasks start, with `cp-000` initial and `cp-NNN` per-merge checkpoint rows.
- Dependent fake-adapter regression passes and proves task 2 sees task 1's cherry-pick on run main.
- `summarize` reports latest checkpoint, graph counts, blocked node, failure class, next automatic action, and human decision fields; `resume --dry-run` reports the next durable activity boundary.
- Full AgentRunway eval suite passes.

Out of scope for this slice (tracked in design §13.1 and §15.2):

- Replacing `schedule_waves` with `ready_tasks_after_checkpoints` / `schedule_safe_wave` in `runner.run()`.
