# AgentRunway Durable Orchestrator Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make AgentRunway release work from checkpoint evidence, expose one durable state projection across inspect/summarize/resume, execute safe resume boundaries, and split durable runner mechanics into focused modules.

**Architecture:** Add a shared durable projection first, then extract reusable activity and gate execution from `runner.py` so both fresh runs and resume use the same code path. Wire the checkpoint scheduler into runtime dispatch after the projection and execution boundary are covered by tests, then finish with focused extraction cleanup and end-to-end verification.

**Tech Stack:** Python 3, SQLite, pytest, git worktrees, AgentRunway fake Codex/Claude fixtures, existing AgentLens event journal.

---

## Scope Check

This plan implements the approved spec:

- `docs/superpowers/specs/2026-05-20-agentrunway-durable-orchestrator-hardening-design.md`

The spec spans stability, scheduler performance, and runner structure. These are tightly coupled inside AgentRunway because executable resume and checkpoint scheduling both need the same activity boundary code. This plan keeps them in one implementation plan but lands them as independent tasks with focused acceptance commands.

## File Structure

- `skills/agent-runway/scripts/agentrunway/durable_projection.py`
  - New shared projection for latest checkpoint, completed checkpoint tasks, ready queue, blocked activity, decision packet, and next action.
- `skills/agent-runway/scripts/agentrunway/checkpoint_scheduler.py`
  - New runtime scheduler wrapper over `ready_tasks_after_checkpoints()` and `schedule_safe_wave()`.
- `skills/agent-runway/scripts/agentrunway/activity_runner.py`
  - New boundary executor for implement, review, verification, and merge activity lifecycle.
- `skills/agent-runway/scripts/agentrunway/gate_runner.py`
  - New gate decision normalizer for review and verification.
- `skills/agent-runway/scripts/agentrunway/resume_planner.py`
  - New action planner that converts durable projection plus reconciliation into resume actions.
- `skills/agent-runway/scripts/agentrunway/resume_executor.py`
  - New executor for automatic resume actions only.
- `skills/agent-runway/scripts/agentrunway/runner.py`
  - Keep CLI orchestration, run setup, status/summarize/inspect/resume entry points, and final status handling. Remove duplicated durable projection and gate branching as new modules land.
- `skills/agent-runway/scripts/agentrunway/run_summary.py`
  - Read workflow summary fields from `DurableProjection`.
- `skills/agent-runway/scripts/agentrunway/status.py`
  - Read inspect durable fields from `DurableProjection`.
- `skills/agent-runway/evals/test_durable_projection.py`
  - New unit tests for projection semantics and command-surface consistency.
- `skills/agent-runway/evals/test_checkpoint_scheduler_runtime.py`
  - New tests for checkpoint-driven ready selection and safe-wave runtime decisions.
- `skills/agent-runway/evals/test_activity_runner.py`
  - New tests for idempotent activity lifecycle extraction.
- `skills/agent-runway/evals/test_gate_runner.py`
  - New tests for normalized gate decisions and decision packet creation.
- `skills/agent-runway/evals/test_resume_executor.py`
  - New tests for dry-run side-effect freedom and automatic resume execution boundaries.
- Existing evals to extend:
  - `skills/agent-runway/evals/test_resume_apply.py`
  - `skills/agent-runway/evals/test_durable_orchestrator_e2e.py`
  - `skills/agent-runway/evals/test_runner_production_e2e.py`
  - `skills/agent-runway/evals/test_run_summary.py`

---

### Task 1: Add Durable Projection Reader

```yaml agentrunway-task
task_id: task_001
title: Add Durable Projection Reader
risk: medium
phase: implementation
dependencies: []
spec_refs: [S1.5, S1.6, S1.8, S1.9, S1.10]
file_claims:
  - {path: skills/agent-runway/scripts/agentrunway/durable_projection.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/run_summary.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/status.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/runner.py, mode: shared_append}
  - {path: skills/agent-runway/evals/test_durable_projection.py, mode: owned}
  - {path: skills/agent-runway/evals/test_run_summary.py, mode: shared_append}
acceptance_commands:
  - cd skills/agent-runway && python -m pytest evals/test_durable_projection.py evals/test_run_summary.py evals/test_resume_apply.py -v
required_skills: [test-driven-development]
serial: true
```

**Files:**
- Create: `skills/agent-runway/scripts/agentrunway/durable_projection.py`
- Create: `skills/agent-runway/evals/test_durable_projection.py`
- Modify: `skills/agent-runway/scripts/agentrunway/run_summary.py`
- Modify: `skills/agent-runway/scripts/agentrunway/status.py`
- Modify: `skills/agent-runway/scripts/agentrunway/runner.py`

- [ ] **Step 1: Write failing durable projection tests**

Create `skills/agent-runway/evals/test_durable_projection.py`:

```python
from __future__ import annotations

from pathlib import Path

from agentrunway.db import AgentRunwayDb
from agentrunway.durable_projection import read_durable_projection
from agentrunway.models import FileClaim, TaskSpec
from agentrunway.workflow_store import ActivityStatus, WorkflowStore


def _task(task_id: str, *, deps: tuple[str, ...] = ()) -> TaskSpec:
    return TaskSpec(
        task_id=task_id,
        title=task_id,
        risk="low",
        phase="implementation",
        dependencies=deps,
        spec_refs=("S1.1",),
        file_claims=(FileClaim(f"src/{task_id}.py", "owned"),),
        acceptance_commands=("python -m pytest",),
    )


def _db(tmp_path: Path) -> AgentRunwayDb:
    return AgentRunwayDb.open(tmp_path / "state.sqlite")


def test_projection_repairs_merged_task_without_checkpoint_instead_of_releasing_dependent(tmp_path: Path) -> None:
    db = _db(tmp_path)
    db.upsert_task(_task("task_001"))
    db.upsert_task(_task("task_002", deps=("task_001",)))
    db.set_task_status("task_001", "merged")

    projection = read_durable_projection(run_id="run-1", db=db)

    assert projection.completed_checkpoint_tasks == []
    assert projection.checkpoint_repair_tasks == ["task_001"]
    assert [task["task_id"] for task in projection.ready_tasks] == []
    assert projection.next_automatic_action == "verify_checkpoint"


def test_projection_marks_dependent_ready_after_dependency_checkpoint(tmp_path: Path) -> None:
    db = _db(tmp_path)
    store = WorkflowStore(db)
    db.upsert_task(_task("task_001"))
    db.upsert_task(_task("task_002", deps=("task_001",)))
    db.set_task_status("task_001", "merged")
    store.create_checkpoint(
        run_id="run-1",
        checkpoint_id="cp-001",
        commit_sha="abc123",
        parent_checkpoint_id=None,
        merged_candidate_id=1,
        reason="merged:task_001",
    )

    projection = read_durable_projection(run_id="run-1", db=db)

    assert projection.completed_checkpoint_tasks == ["task_001"]
    assert [task["task_id"] for task in projection.ready_tasks] == ["task_002"]
    assert projection.latest_checkpoint == {
        "checkpoint_id": "cp-001",
        "commit_sha": "abc123",
        "reason": "merged:task_001",
    }


def test_projection_surfaces_human_decision_packet(tmp_path: Path) -> None:
    db = _db(tmp_path)
    store = WorkflowStore(db)
    db.upsert_task(_task("task_001"))
    store.start_activity(
        run_id="run-1",
        activity_id="task_001.review.001",
        idempotency_key="run-1:task_001:review:001",
        task_id="task_001",
        activity_type="review",
        input_refs={"candidate_id": 7},
    )
    store.complete_activity(
        activity_id="task_001.review.001",
        status=ActivityStatus.BLOCKED,
        output_refs={"candidate_id": 7, "review_status": "changes_requested"},
        failure_class="needs_plan_fix",
    )
    store.create_decision_packet(
        run_id="run-1",
        decision_id="task_001.review.001.decision",
        task_id="task_001",
        failure_class="needs_plan_fix",
        summary="review requires plan correction",
        payload={"candidate_id": 7},
    )

    projection = read_durable_projection(run_id="run-1", db=db)

    assert projection.blocked_node == "task_001.review.001"
    assert projection.failure_class == "needs_plan_fix"
    assert projection.next_automatic_action is None
    assert projection.required_human_decision == "fix plan"
    assert projection.decision_packet["decision_id"] == "task_001.review.001.decision"
```

- [ ] **Step 2: Run projection tests to verify failure**

Run:

```bash
cd skills/agent-runway && python -m pytest evals/test_durable_projection.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'agentrunway.durable_projection'`.

- [ ] **Step 3: Implement `durable_projection.py`**

Create `skills/agent-runway/scripts/agentrunway/durable_projection.py`:

```python
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

from .db import AgentRunwayDb
from .models import FileClaim, TaskSpec
from .scheduler import ready_tasks_after_checkpoints, schedule_safe_wave


_HUMAN_DECISION_BY_FAILURE_CLASS = {
    "needs_plan_fix": "fix plan",
    "needs_split": "approve task split",
    "needs_infra_fix": "fix infrastructure",
    "needs_human_decision": "inspect decision packet",
    "terminal_rejected": "inspect terminal rejection",
}

_TERMINAL_TASK_STATUSES = {"blocked", "failed", "merged"}


@dataclass(frozen=True)
class DurableProjection:
    run_id: str
    latest_checkpoint: dict[str, Any] | None
    completed_checkpoint_tasks: list[str]
    checkpoint_repair_tasks: list[str]
    ready_tasks: list[dict[str, Any]]
    safe_wave: list[dict[str, Any]]
    running_activities: list[dict[str, Any]]
    blocked_node: str | None
    failure_class: str | None
    next_automatic_action: str | None
    required_human_decision: str | None
    decision_packet: dict[str, Any] | None
    graph: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["ready_queue"] = [task["task_id"] for task in self.ready_tasks]
        payload["safe_wave"] = [task["task_id"] for task in self.safe_wave]
        return payload


def _json_list(row: dict[str, Any], key: str) -> tuple[str, ...]:
    raw = row.get(key)
    if isinstance(raw, str):
        value = json.loads(raw)
    else:
        value = raw or []
    return tuple(str(item) for item in value)


def _task_from_row(row: dict[str, Any], claims: list[dict[str, Any]]) -> TaskSpec:
    return TaskSpec(
        task_id=str(row["task_id"]),
        title=str(row["title"]),
        risk=str(row["risk"]),  # type: ignore[arg-type]
        phase=str(row["phase"]),
        dependencies=_json_list(row, "dependencies_json"),
        spec_refs=_json_list(row, "spec_refs_json"),
        file_claims=tuple(FileClaim(str(claim["path"]), str(claim["mode"])) for claim in claims),  # type: ignore[arg-type]
        acceptance_commands=_json_list(row, "acceptance_commands_json"),
        resource_keys=_json_list(row, "resource_keys_json"),
        required_skills=_json_list(row, "required_skills_json"),
        serial=bool(row.get("serial")),
        objective=str(row.get("objective") or ""),
        line=int(row.get("line") or 0),
    )


def _task_rows(db: AgentRunwayDb) -> list[dict[str, Any]]:
    return db.list_tasks()


def _task_specs(db: AgentRunwayDb) -> list[TaskSpec]:
    specs: list[TaskSpec] = []
    for row in _task_rows(db):
        claims = [
            dict(claim)
            for claim in db.conn.execute(
                "SELECT path, mode FROM file_claims WHERE task_id=? ORDER BY path, mode",
                (row["task_id"],),
            ).fetchall()
        ]
        specs.append(_task_from_row(row, claims))
    return specs


def _completed_checkpoint_tasks(checkpoints: list[dict[str, Any]]) -> list[str]:
    completed: list[str] = []
    for checkpoint in checkpoints:
        reason = str(checkpoint.get("reason") or "")
        if not reason.startswith("merged:"):
            continue
        task_id = reason.split(":", 1)[1]
        if task_id and task_id not in completed:
            completed.append(task_id)
    return completed


def _checkpoint_repair_tasks(task_rows: list[dict[str, Any]], completed_checkpoint_tasks: list[str]) -> list[str]:
    completed = set(completed_checkpoint_tasks)
    return [
        str(row["task_id"])
        for row in task_rows
        if str(row.get("status") or "") == "merged" and str(row["task_id"]) not in completed
    ]


def _compact_task(task: TaskSpec) -> dict[str, Any]:
    return {
        "task_id": task.task_id,
        "risk": task.risk,
        "dependencies": list(task.dependencies),
        "file_claims": [{"path": claim.path, "mode": claim.mode} for claim in task.file_claims],
        "resource_keys": list(task.resource_keys),
        "serial": task.serial,
    }


def _compact_activity(activity: dict[str, Any]) -> dict[str, Any]:
    return {
        "activity_id": activity.get("activity_id"),
        "activity_type": activity.get("activity_type"),
        "task_id": activity.get("task_id"),
        "status": activity.get("status"),
        "failure_class": activity.get("failure_class"),
        "output_refs": activity.get("output_refs") or {},
    }


def _decision_for_activity(db: AgentRunwayDb, run_id: str, activity_id: str) -> dict[str, Any] | None:
    packets = db.list_decision_packets(run_id)
    for packet in packets:
        if str(packet.get("decision_id")).startswith(activity_id):
            payload = dict(packet)
            raw = payload.get("payload_json")
            if isinstance(raw, str):
                payload["payload"] = json.loads(raw)
            return payload
    if packets:
        payload = dict(packets[-1])
        raw = payload.get("payload_json")
        if isinstance(raw, str):
            payload["payload"] = json.loads(raw)
        return payload
    return None


def read_durable_projection(*, run_id: str, db: AgentRunwayDb) -> DurableProjection:
    checkpoints = db.list_checkpoints(run_id)
    latest = db.latest_checkpoint(run_id)
    completed_checkpoint_tasks = _completed_checkpoint_tasks(checkpoints)
    task_rows = _task_rows(db)
    checkpoint_repair_tasks = _checkpoint_repair_tasks(task_rows, completed_checkpoint_tasks)
    completed_tasks = {
        str(row["task_id"])
        for row in task_rows
        if str(row.get("status") or "") in _TERMINAL_TASK_STATUSES
    }
    tasks = _task_specs(db)
    ready = ready_tasks_after_checkpoints(
        tasks,
        completed_checkpoints=set(completed_checkpoint_tasks),
        completed_tasks=completed_tasks,
    )
    safe_wave = schedule_safe_wave(ready)
    activities = db.list_activities(run_id)
    running = [activity for activity in activities if activity.get("status") == "started"]
    blocked = next(
        (activity for activity in reversed(activities) if activity.get("status") in {"failed", "blocked"}),
        None,
    )
    failure_class = str(blocked.get("failure_class")) if blocked and blocked.get("failure_class") else None
    human_decision = _HUMAN_DECISION_BY_FAILURE_CLASS.get(failure_class) if failure_class else None
    decision_packet = _decision_for_activity(db, run_id, str(blocked["activity_id"])) if blocked else None
    return DurableProjection(
        run_id=run_id,
        latest_checkpoint={
            "checkpoint_id": latest["checkpoint_id"],
            "commit_sha": latest["commit_sha"],
            "reason": latest["reason"],
        }
        if latest
        else None,
        completed_checkpoint_tasks=completed_checkpoint_tasks,
        checkpoint_repair_tasks=checkpoint_repair_tasks,
        ready_tasks=[_compact_task(task) for task in ready],
        safe_wave=[_compact_task(task) for task in safe_wave],
        running_activities=[_compact_activity(activity) for activity in running],
        blocked_node=str(blocked["activity_id"]) if blocked else None,
        failure_class=failure_class,
        next_automatic_action=None if human_decision else ("verify_checkpoint" if checkpoint_repair_tasks else ("resume" if blocked else None)),
        required_human_decision=human_decision,
        decision_packet=decision_packet,
        graph={
            "complete": sum(1 for activity in activities if activity.get("status") == "completed"),
            "ready": len(ready),
            "running": len(running),
            "blocked": sum(1 for activity in activities if activity.get("status") in {"failed", "blocked"}),
        },
    )
```

- [ ] **Step 4: Run projection tests to verify pass**

Run:

```bash
cd skills/agent-runway && python -m pytest evals/test_durable_projection.py -v
```

Expected: PASS.

- [ ] **Step 5: Wire `run_summary.py` to durable projection**

Modify `_workflow_summary()` in `skills/agent-runway/scripts/agentrunway/run_summary.py`:

```python
def _workflow_summary(db: AgentRunwayDb, run_id: str) -> dict[str, Any]:
    if not run_id:
        return {}
    from .durable_projection import read_durable_projection

    projection = read_durable_projection(run_id=run_id, db=db)
    payload = projection.to_dict()
    latest = payload.get("latest_checkpoint")
    return {
        "latest_checkpoint": {
            "id": latest.get("checkpoint_id"),
            "commit": latest.get("commit_sha"),
            "reason": latest.get("reason"),
        }
        if isinstance(latest, dict)
        else None,
        "graph": payload["graph"],
        "blocked_node": payload["blocked_node"],
        "failure_class": payload["failure_class"],
        "next_automatic_action": payload["next_automatic_action"],
        "required_human_decision": payload["required_human_decision"],
        "ready_queue": payload["ready_queue"],
        "safe_wave": payload["safe_wave"],
        "decision_packet": payload["decision_packet"],
    }
```

- [ ] **Step 6: Wire `status.py` inspect payload to durable projection**

In `skills/agent-runway/scripts/agentrunway/status.py`, import and use the projection inside `build_inspect_payload()`:

```python
    from .durable_projection import read_durable_projection

    durable = read_durable_projection(run_id=str(run_json.get("run_id")), db=db).to_dict()
```

Add these keys to the returned payload:

```python
        "durable": durable,
        "ready_queue": durable["ready_queue"],
        "safe_wave": durable["safe_wave"],
        "blocked_node": durable["blocked_node"],
        "failure_class": durable["failure_class"],
```

- [ ] **Step 7: Wire `runner.resume()` dry-run to include projection**

In `skills/agent-runway/scripts/agentrunway/runner.py`, add a local import in `resume()` after the DB opens:

```python
    from .durable_projection import read_durable_projection
```

Compute projection before returning:

```python
    durable_projection = read_durable_projection(run_id=run_id, db=db).to_dict()
```

Change the dry-run return to:

```python
    if dry_run:
        return {
            **plan,
            "activity_resume": activity_resume,
            "durable": durable_projection,
            "next_action": durable_projection.get("next_automatic_action") or activity_resume.get("next_action"),
        }
```

- [ ] **Step 8: Run command surface tests**

Run:

```bash
cd skills/agent-runway && python -m pytest evals/test_durable_projection.py evals/test_run_summary.py evals/test_resume_apply.py -v
```

Expected: PASS.

- [ ] **Step 9: Commit Task 1**

```bash
git add skills/agent-runway/scripts/agentrunway/durable_projection.py \
  skills/agent-runway/scripts/agentrunway/run_summary.py \
  skills/agent-runway/scripts/agentrunway/status.py \
  skills/agent-runway/scripts/agentrunway/runner.py \
  skills/agent-runway/evals/test_durable_projection.py \
  skills/agent-runway/evals/test_run_summary.py \
  skills/agent-runway/evals/test_resume_apply.py
git commit -m "feat: add AgentRunway durable projection"
```

---

### Task 2: Add Runtime Checkpoint Scheduler

```yaml agentrunway-task
task_id: task_002
title: Add Runtime Checkpoint Scheduler
risk: medium
phase: implementation
dependencies: [task_001]
spec_refs: [S1.5, S1.6, S1.9]
file_claims:
  - {path: skills/agent-runway/scripts/agentrunway/checkpoint_scheduler.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/durable_projection.py, mode: shared_append}
  - {path: skills/agent-runway/evals/test_checkpoint_scheduler_runtime.py, mode: owned}
acceptance_commands:
  - cd skills/agent-runway && python -m pytest evals/test_checkpoint_scheduler.py evals/test_checkpoint_scheduler_runtime.py -v
required_skills: [test-driven-development]
serial: true
```

**Files:**
- Create: `skills/agent-runway/scripts/agentrunway/checkpoint_scheduler.py`
- Create: `skills/agent-runway/evals/test_checkpoint_scheduler_runtime.py`
- Modify: `skills/agent-runway/scripts/agentrunway/durable_projection.py`

- [ ] **Step 1: Write failing runtime scheduler tests**

Create `skills/agent-runway/evals/test_checkpoint_scheduler_runtime.py`:

```python
from __future__ import annotations

from pathlib import Path

from agentrunway.checkpoint_scheduler import CheckpointScheduler
from agentrunway.db import AgentRunwayDb
from agentrunway.durable_projection import read_durable_projection
from agentrunway.models import FileClaim, TaskSpec
from agentrunway.workflow_store import WorkflowStore


def _task(
    task_id: str,
    *,
    deps: tuple[str, ...] = (),
    claims: tuple[FileClaim, ...] = (),
    resources: tuple[str, ...] = (),
    risk: str = "low",
    serial: bool = False,
) -> TaskSpec:
    return TaskSpec(
        task_id=task_id,
        title=task_id,
        risk=risk,  # type: ignore[arg-type]
        phase="implementation",
        dependencies=deps,
        spec_refs=("S1.1",),
        file_claims=claims or (FileClaim(f"src/{task_id}.py", "owned"),),
        acceptance_commands=("python -m pytest",),
        resource_keys=resources,
        serial=serial,
    )


def _db(tmp_path: Path) -> AgentRunwayDb:
    return AgentRunwayDb.open(tmp_path / "state.sqlite")


def test_scheduler_returns_safe_wave_from_projection(tmp_path: Path) -> None:
    db = _db(tmp_path)
    db.upsert_task(_task("task_001", claims=(FileClaim("src/a.py", "owned"),)))
    db.upsert_task(_task("task_002", claims=(FileClaim("src/b.py", "owned"),)))
    projection = read_durable_projection(run_id="run-1", db=db)

    wave = CheckpointScheduler().next_wave(projection=projection)

    assert [task["task_id"] for task in wave] == ["task_001", "task_002"]


def test_scheduler_serializes_conflicting_ready_tasks(tmp_path: Path) -> None:
    db = _db(tmp_path)
    db.upsert_task(_task("task_001", claims=(FileClaim("src/shared.py", "owned"),)))
    db.upsert_task(_task("task_002", claims=(FileClaim("src/shared.py", "owned"),)))
    projection = read_durable_projection(run_id="run-1", db=db)

    wave = CheckpointScheduler().next_wave(projection=projection)

    assert [task["task_id"] for task in wave] == ["task_001"]


def test_scheduler_waits_for_checkpoint_before_dependency_release(tmp_path: Path) -> None:
    db = _db(tmp_path)
    store = WorkflowStore(db)
    db.upsert_task(_task("task_001"))
    db.upsert_task(_task("task_002", deps=("task_001",)))
    db.set_task_status("task_001", "merged")
    projection_before = read_durable_projection(run_id="run-1", db=db)

    store.create_checkpoint(
        run_id="run-1",
        checkpoint_id="cp-001",
        commit_sha="abc123",
        parent_checkpoint_id=None,
        merged_candidate_id=1,
        reason="merged:task_001",
    )
    projection_after = read_durable_projection(run_id="run-1", db=db)

    assert CheckpointScheduler().next_wave(projection=projection_before) == []
    assert projection_before.checkpoint_repair_tasks == ["task_001"]
    assert projection_before.next_automatic_action == "verify_checkpoint"
    assert [task["task_id"] for task in CheckpointScheduler().next_wave(projection=projection_after)] == ["task_002"]
```

- [ ] **Step 2: Run runtime scheduler tests to verify failure**

Run:

```bash
cd skills/agent-runway && python -m pytest evals/test_checkpoint_scheduler_runtime.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'agentrunway.checkpoint_scheduler'`.

- [ ] **Step 3: Implement `checkpoint_scheduler.py`**

Create `skills/agent-runway/scripts/agentrunway/checkpoint_scheduler.py`:

```python
from __future__ import annotations

from typing import Any


class CheckpointScheduler:
    def next_wave(self, *, projection: Any) -> list[dict[str, Any]]:
        if hasattr(projection, "to_dict"):
            payload = projection.to_dict()
        else:
            payload = dict(projection)
        return list(payload.get("safe_wave") or [])
```

This module deliberately consumes the projection instead of rebuilding ready
logic. `durable_projection.py` remains the source for dependency and conflict
calculation.

- [ ] **Step 4: Run scheduler tests**

Run:

```bash
cd skills/agent-runway && python -m pytest evals/test_checkpoint_scheduler.py evals/test_checkpoint_scheduler_runtime.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit Task 2**

```bash
git add skills/agent-runway/scripts/agentrunway/checkpoint_scheduler.py \
  skills/agent-runway/evals/test_checkpoint_scheduler_runtime.py
git commit -m "feat: add AgentRunway checkpoint scheduler"
```

---

### Task 3: Extract Activity And Gate Runners

```yaml agentrunway-task
task_id: task_003
title: Extract Activity And Gate Runners
risk: high
phase: implementation
dependencies: [task_001]
spec_refs: [S1.5, S1.7, S1.11]
file_claims:
  - {path: skills/agent-runway/scripts/agentrunway/activity_runner.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/gate_runner.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/runner.py, mode: owned}
  - {path: skills/agent-runway/evals/test_activity_runner.py, mode: owned}
  - {path: skills/agent-runway/evals/test_gate_runner.py, mode: owned}
acceptance_commands:
  - cd skills/agent-runway && python -m pytest evals/test_activity_runner.py evals/test_gate_runner.py evals/test_runner_production_e2e.py -v
required_skills: [test-driven-development]
serial: true
```

**Files:**
- Create: `skills/agent-runway/scripts/agentrunway/activity_runner.py`
- Create: `skills/agent-runway/scripts/agentrunway/gate_runner.py`
- Create: `skills/agent-runway/evals/test_activity_runner.py`
- Create: `skills/agent-runway/evals/test_gate_runner.py`
- Modify: `skills/agent-runway/scripts/agentrunway/runner.py`

- [ ] **Step 1: Write failing `GateRunner` tests**

Create `skills/agent-runway/evals/test_gate_runner.py`:

```python
from __future__ import annotations

from agentrunway.gate_runner import GateOutcome, GateRunner
from agentrunway.models import FileClaim, TaskSpec
from agentrunway.quality_policy import PolicyDecision


def _task() -> TaskSpec:
    return TaskSpec(
        task_id="task_001",
        title="Task 1",
        risk="low",
        phase="implementation",
        dependencies=(),
        spec_refs=("S1.1",),
        file_claims=(FileClaim("src/a.py", "owned"),),
        acceptance_commands=("python -m pytest",),
    )


def test_gate_runner_blocks_human_decision_class() -> None:
    outcome = GateRunner().decide(
        task=_task(),
        gate="review",
        status="changes_requested",
        result={"status": "changes_requested", "findings": [{"body": "file claim is missing"}]},
        candidate={"id": 1, "worker_id": "task_001-implementer-001", "changed_files": ["src/a.py"], "commits": ["abc"]},
        previous_retries=0,
    )

    assert outcome == GateOutcome(
        action="await_human_decision",
        policy=PolicyDecision(action="block", reason="review_needs_plan_fix", outcome="failed"),
        failure_class="needs_plan_fix",
        decision_packet_required=True,
    )


def test_gate_runner_retries_implementer_for_actionable_verifier_failure() -> None:
    outcome = GateRunner().decide(
        task=_task(),
        gate="verification",
        status="failed",
        result={"status": "failed", "checks": [{"command": "python -m pytest", "status": "failed"}]},
        candidate={"id": 1, "worker_id": "task_001-implementer-001", "changed_files": ["src/a.py"], "commits": ["abc"]},
        previous_retries=0,
    )

    assert outcome.action == "retry_implementer"
    assert outcome.failure_class == "needs_implementer_retry"
    assert outcome.decision_packet_required is False
```

- [ ] **Step 2: Run `GateRunner` tests to verify failure**

Run:

```bash
cd skills/agent-runway && python -m pytest evals/test_gate_runner.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'agentrunway.gate_runner'`.

- [ ] **Step 3: Implement `gate_runner.py`**

Create `skills/agent-runway/scripts/agentrunway/gate_runner.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .failure_classifier import classify_gate_failure
from .models import TaskSpec
from .quality_policy import PolicyDecision, gate_retry_decision


GateAction = Literal[
    "continue",
    "retry_implementer",
    "redispatch_from_latest_checkpoint",
    "await_human_decision",
    "terminal_block",
]

_HUMAN_DECISION_FAILURE_CLASSES = {
    "needs_plan_fix",
    "needs_split",
    "needs_human_decision",
    "needs_infra_fix",
    "terminal_rejected",
}


@dataclass(frozen=True)
class GateOutcome:
    action: GateAction
    policy: PolicyDecision
    failure_class: str | None
    decision_packet_required: bool


class GateRunner:
    def decide(
        self,
        *,
        task: TaskSpec,
        gate: str,
        status: str,
        result: dict[str, Any],
        candidate: dict[str, Any],
        previous_retries: int,
    ) -> GateOutcome:
        if gate == "review" and status == "approved":
            return GateOutcome(
                action="continue",
                policy=PolicyDecision(action="continue", reason="review_approved", outcome="success"),
                failure_class=None,
                decision_packet_required=False,
            )
        if gate == "verification" and status == "passed":
            return GateOutcome(
                action="continue",
                policy=PolicyDecision(action="continue", reason="verification_passed", outcome="success"),
                failure_class=None,
                decision_packet_required=False,
            )
        classification = classify_gate_failure(
            gate=gate,
            status=status,
            result=result,
            candidate=candidate,
            task_acceptance_commands=list(task.acceptance_commands),
        )
        policy = gate_retry_decision(
            task=task,
            gate=gate,
            status=status,
            result=result,
            candidate=candidate,
            previous_retries=previous_retries,
        )
        if classification.failure_class in _HUMAN_DECISION_FAILURE_CLASSES:
            return GateOutcome(
                action="await_human_decision",
                policy=PolicyDecision(action="block", reason=f"{gate}_{classification.failure_class}", outcome="failed"),
                failure_class=classification.failure_class,
                decision_packet_required=True,
            )
        if policy.action == "retry":
            return GateOutcome(
                action="retry_implementer",
                policy=policy,
                failure_class=classification.failure_class,
                decision_packet_required=False,
            )
        if classification.failure_class == "needs_rebase":
            return GateOutcome(
                action="redispatch_from_latest_checkpoint",
                policy=policy,
                failure_class=classification.failure_class,
                decision_packet_required=False,
            )
        return GateOutcome(
            action="terminal_block",
            policy=policy,
            failure_class=classification.failure_class,
            decision_packet_required=False,
        )
```

- [ ] **Step 4: Write failing `ActivityRunner` smoke tests**

Create `skills/agent-runway/evals/test_activity_runner.py`:

```python
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
```

- [ ] **Step 5: Implement `activity_runner.py`**

Create `skills/agent-runway/scripts/agentrunway/activity_runner.py`:

```python
from __future__ import annotations

from typing import Any

from .workflow_store import ActivityStatus, WorkflowStore


class ActivityRunner:
    def __init__(self, *, store: WorkflowStore, run_id: str):
        self.store = store
        self.run_id = run_id

    def start(
        self,
        *,
        activity_id: str,
        idempotency_key: str,
        task_id: str | None,
        activity_type: str,
        input_refs: dict[str, Any],
    ) -> dict[str, Any]:
        return self.store.start_activity(
            run_id=self.run_id,
            activity_id=activity_id,
            idempotency_key=idempotency_key,
            task_id=task_id,
            activity_type=activity_type,
            input_refs=input_refs,
        )

    def complete(
        self,
        *,
        activity_id: str,
        status: ActivityStatus,
        output_refs: dict[str, Any],
        failure_class: str | None,
    ) -> dict[str, Any]:
        return self.store.complete_activity(
            activity_id=activity_id,
            status=status,
            output_refs=output_refs,
            failure_class=failure_class,
        )
```

- [ ] **Step 6: Replace direct workflow-store lifecycle calls in `runner.py`**

In `skills/agent-runway/scripts/agentrunway/runner.py`, import:

```python
from .activity_runner import ActivityRunner
from .gate_runner import GateRunner
```

After `workflow_store = WorkflowStore(db)`, add:

```python
    activity_runner = ActivityRunner(store=workflow_store, run_id=run_id)
    gate_runner = GateRunner()
```

Replace `workflow_store.start_activity(...)` calls for implement, review, and
verification with `activity_runner.start(...)`. Replace matching
`workflow_store.complete_activity(...)` calls with `activity_runner.complete(...)`.

For review and verification non-success branches, replace `_decision_for_classification(...)`
with:

```python
                    gate_outcome = gate_runner.decide(
                        task=task,
                        gate="review",
                        status=review_status,
                        result=review,
                        candidate=candidate_snapshot,
                        previous_retries=review_retries,
                    )
                    decision = gate_outcome.policy
```

and:

```python
                gate_outcome = gate_runner.decide(
                    task=task,
                    gate="verification",
                    status=verification_status,
                    result=verification,
                    candidate=candidate_snapshot,
                    previous_retries=verification_retries,
                )
                decision = gate_outcome.policy
```

Keep `_gate_decision_packet(...)` in `runner.py` for this task. Remove it in Task 6.

- [ ] **Step 7: Run extraction tests**

Run:

```bash
cd skills/agent-runway && python -m pytest evals/test_activity_runner.py evals/test_gate_runner.py evals/test_runner_production_e2e.py -v
```

Expected: PASS.

- [ ] **Step 8: Commit Task 3**

```bash
git add skills/agent-runway/scripts/agentrunway/activity_runner.py \
  skills/agent-runway/scripts/agentrunway/gate_runner.py \
  skills/agent-runway/scripts/agentrunway/runner.py \
  skills/agent-runway/evals/test_activity_runner.py \
  skills/agent-runway/evals/test_gate_runner.py
git commit -m "feat: extract AgentRunway activity and gate runners"
```

---

### Task 4: Integrate Checkpoint Scheduler Into Runner

```yaml agentrunway-task
task_id: task_004
title: Integrate Checkpoint Scheduler Into Runner
risk: high
phase: implementation
dependencies: [task_002, task_003]
spec_refs: [S1.5, S1.6, S1.9, S1.12]
file_claims:
  - {path: skills/agent-runway/scripts/agentrunway/runner.py, mode: owned}
  - {path: skills/agent-runway/evals/test_durable_orchestrator_e2e.py, mode: owned}
  - {path: skills/agent-runway/evals/test_runner_production_e2e.py, mode: shared_append}
acceptance_commands:
  - cd skills/agent-runway && python -m pytest evals/test_durable_orchestrator_e2e.py evals/test_runner_production_e2e.py -v
required_skills: [test-driven-development]
serial: true
```

**Files:**
- Modify: `skills/agent-runway/scripts/agentrunway/runner.py`
- Modify: `skills/agent-runway/evals/test_durable_orchestrator_e2e.py`
- Modify: `skills/agent-runway/evals/test_runner_production_e2e.py`

- [ ] **Step 1: Extend e2e test for a safe independent wave**

Append to `skills/agent-runway/evals/test_durable_orchestrator_e2e.py`:

```python
def test_safe_independent_tasks_share_checkpoint_scheduler_wave(git_repo: Path, isolated_home: Path) -> None:
    spec = git_repo / "spec.md"
    plan = git_repo / "plan.md"
    spec.write_text("# Spec\n\n## A\n\nA.\n\n## B\n\nB.\n", encoding="utf-8")
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
        "acceptance_commands: [python -m pytest]\n"
        "required_skills: [test-driven-development]\n"
        "```\n"
        "Create A.\n\n"
        "## Task 2: B\n\n"
        "```yaml agentrunway-task\n"
        "task_id: task_002\n"
        "title: B\n"
        "risk: low\n"
        "phase: implementation\n"
        "dependencies: []\n"
        "spec_refs: [S1.2]\n"
        "file_claims:\n"
        "  - {path: src/b.py, mode: owned}\n"
        "acceptance_commands: [python -m pytest]\n"
        "required_skills: [test-driven-development]\n"
        "```\n"
        "Create B.\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PATH"] = f"{FAKE_BIN}{os.pathsep}{env['PATH']}"
    env["AGENTRUNWAY_FAKE_TARGET_MAP"] = "task_001=src/a.py;task_002=src/b.py"

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "run", "--plan", str(plan), "--spec", str(spec), "--adapter", "codex"],
        cwd=git_repo,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    conn = sqlite3.connect(payload["state_db"])
    conn.row_factory = sqlite3.Row
    checkpoints = conn.execute("SELECT reason FROM checkpoints ORDER BY checkpoint_id").fetchall()
    assert payload["status"] == "finished"
    assert [row["reason"] for row in checkpoints] == ["initial", "merged:task_001", "merged:task_002"]
```

- [ ] **Step 2: Run new e2e to capture current behavior**

Run:

```bash
cd skills/agent-runway && python -m pytest evals/test_durable_orchestrator_e2e.py::test_safe_independent_tasks_share_checkpoint_scheduler_wave -v
```

Expected: PASS before integration. This test protects existing success behavior while the loop changes.

- [ ] **Step 3: Replace static runtime loop with checkpoint dispatch loop**

In `skills/agent-runway/scripts/agentrunway/runner.py`, keep `waves = schedule_waves(tasks)` only for `run_json["waves"]`. After adapter setup, replace the top-level `for task in tasks:` execution loop with:

```python
    from .checkpoint_scheduler import CheckpointScheduler
    from .durable_projection import read_durable_projection

    scheduler = CheckpointScheduler()
    tasks_by_id = {task.task_id: task for task in tasks}
    progressed = True
    while progressed:
        progressed = False
        projection = read_durable_projection(run_id=run_id, db=db)
        wave = scheduler.next_wave(projection=projection)
        if not wave:
            break
        for task_ref in wave:
            task = tasks_by_id[str(task_ref["task_id"])]
            if str(db.get_task(task.task_id).get("status")) in {"blocked", "failed", "merged"}:
                continue
            # Existing per-task execution body moves here unchanged.
            progressed = True
```

Move the existing per-task body into the indicated location. Preserve all logic
inside the body, including local adapter handling, implementer loops, candidate
ranking, `IntegrationManager.merge_selected_candidate()`, and final task status
updates.

- [ ] **Step 4: Ensure blocked status means no automatic progress remains**

After the dispatch loop and before final status calculation, re-read projection:

```python
    final_projection = read_durable_projection(run_id=run_id, db=db)
    tasks_snapshot = db.list_tasks()
    blocked = any(str(task.get("status")) == "blocked" for task in tasks_snapshot)
    unfinished = [
        task
        for task in tasks_snapshot
        if str(task.get("status")) not in {"merged", "blocked", "failed"}
    ]
    final_status = "blocked" if blocked or unfinished else "finished"
    if unfinished and not blocked and not final_projection.safe_wave:
        final_status = "blocked"
```

Remove the old `blocked = ...; final_status = ...` pair.

- [ ] **Step 5: Run checkpoint runner tests**

Run:

```bash
cd skills/agent-runway && python -m pytest evals/test_durable_orchestrator_e2e.py evals/test_runner_production_e2e.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit Task 4**

```bash
git add skills/agent-runway/scripts/agentrunway/runner.py \
  skills/agent-runway/evals/test_durable_orchestrator_e2e.py \
  skills/agent-runway/evals/test_runner_production_e2e.py
git commit -m "feat: schedule AgentRunway runtime from checkpoints"
```

---

### Task 5: Add Resume Planner And Automatic Resume Executor

```yaml agentrunway-task
task_id: task_005
title: Add Resume Planner And Automatic Resume Executor
risk: high
phase: implementation
dependencies: [task_001, task_003, task_004]
spec_refs: [S1.5, S1.6, S1.7, S1.11]
file_claims:
  - {path: skills/agent-runway/scripts/agentrunway/resume_planner.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/resume_executor.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/runner.py, mode: owned}
  - {path: skills/agent-runway/evals/test_resume_executor.py, mode: owned}
  - {path: skills/agent-runway/evals/test_resume_apply.py, mode: shared_append}
acceptance_commands:
  - cd skills/agent-runway && python -m pytest evals/test_resume_executor.py evals/test_resume_apply.py evals/test_durable_resume.py -v
required_skills: [test-driven-development]
serial: true
```

**Files:**
- Create: `skills/agent-runway/scripts/agentrunway/resume_planner.py`
- Create: `skills/agent-runway/scripts/agentrunway/resume_executor.py`
- Create: `skills/agent-runway/evals/test_resume_executor.py`
- Modify: `skills/agent-runway/scripts/agentrunway/runner.py`
- Modify: `skills/agent-runway/evals/test_resume_apply.py`

- [ ] **Step 1: Write failing resume planner/executor tests**

Create `skills/agent-runway/evals/test_resume_executor.py`:

```python
from __future__ import annotations

from pathlib import Path

from agentrunway.db import AgentRunwayDb
from agentrunway.resume_executor import ResumeExecutor
from agentrunway.resume_planner import ResumeAction, plan_resume_actions
from agentrunway.workflow_store import ActivityStatus, WorkflowStore


def _store(tmp_path: Path) -> WorkflowStore:
    return WorkflowStore(AgentRunwayDb.open(tmp_path / "state.sqlite"))


def test_resume_planner_keeps_dry_run_side_effect_free(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.start_activity(
        run_id="run-1",
        activity_id="task_001.implement.001",
        idempotency_key="run-1:task_001:implement:001",
        task_id="task_001",
        activity_type="implement",
        input_refs={"checkpoint_id": "cp-000"},
    )
    store.complete_activity(
        activity_id="task_001.implement.001",
        status=ActivityStatus.COMPLETED,
        output_refs={"candidate_id": 7},
        failure_class=None,
    )

    actions = plan_resume_actions(run_id="run-1", db=store.db)

    assert actions == [
        ResumeAction(
            action="schedule_review",
            task_id="task_001",
            candidate_id=7,
            writes=True,
            reason="implement_completed_review_not_started",
        )
    ]
    assert [activity["activity_type"] for activity in store.db.list_activities("run-1")] == ["implement"]


def test_resume_executor_stops_at_human_decision(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.start_activity(
        run_id="run-1",
        activity_id="task_001.review.001",
        idempotency_key="run-1:task_001:review:001",
        task_id="task_001",
        activity_type="review",
        input_refs={"candidate_id": 7},
    )
    store.complete_activity(
        activity_id="task_001.review.001",
        status=ActivityStatus.BLOCKED,
        output_refs={"candidate_id": 7},
        failure_class="needs_plan_fix",
    )
    store.create_decision_packet(
        run_id="run-1",
        decision_id="task_001.review.001.decision",
        task_id="task_001",
        failure_class="needs_plan_fix",
        summary="fix plan",
        payload={"candidate_id": 7},
    )

    result = ResumeExecutor(db=store.db, run_id="run-1").execute(actions=plan_resume_actions(run_id="run-1", db=store.db))

    assert result["executed"] == []
    assert result["blocked"]["decision_id"] == "task_001.review.001.decision"
```

- [ ] **Step 2: Run resume executor tests to verify failure**

Run:

```bash
cd skills/agent-runway && python -m pytest evals/test_resume_executor.py -v
```

Expected: FAIL with `ModuleNotFoundError` for `resume_executor` or `resume_planner`.

- [ ] **Step 3: Implement `resume_planner.py`**

Create `skills/agent-runway/scripts/agentrunway/resume_planner.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .db import AgentRunwayDb
from .durable_resume import plan_activity_resume


ResumeActionName = Literal[
    "schedule_review",
    "schedule_verification",
    "schedule_merge",
    "verify_checkpoint",
    "schedule_implementer_retry",
    "await_human_decision",
]


@dataclass(frozen=True)
class ResumeAction:
    action: ResumeActionName
    task_id: str | None
    candidate_id: int | None
    writes: bool
    reason: str


def _task_id_from_node(node: object) -> str | None:
    if not isinstance(node, str) or "." not in node:
        return None
    return node.split(".", 1)[0]


def plan_resume_actions(*, run_id: str, db: AgentRunwayDb) -> list[ResumeAction]:
    plan = plan_activity_resume(run_id=run_id, db=db)
    action = plan.get("next_action")
    node = plan.get("next_node")
    task_id = _task_id_from_node(node)
    candidate_id = plan.get("candidate_id")
    candidate_int = int(candidate_id) if candidate_id is not None else None
    if action == "await_human_decision":
        return [
            ResumeAction(
                action="await_human_decision",
                task_id=task_id,
                candidate_id=candidate_int,
                writes=False,
                reason=str(plan.get("reason") or "blocked_activity_requires_human_decision"),
            )
        ]
    if action in {"schedule_review", "schedule_verification", "schedule_merge", "verify_checkpoint", "schedule_implementer_retry"}:
        return [
            ResumeAction(
                action=action,  # type: ignore[arg-type]
                task_id=task_id,
                candidate_id=candidate_int,
                writes=True,
                reason=str(plan.get("reason") or action),
            )
        ]
    return []
```

- [ ] **Step 4: Implement `resume_executor.py` with safe no-op execution shell**

Create `skills/agent-runway/scripts/agentrunway/resume_executor.py`:

```python
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .db import AgentRunwayDb
from .resume_planner import ResumeAction


class ResumeExecutor:
    def __init__(self, *, db: AgentRunwayDb, run_id: str):
        self.db = db
        self.run_id = run_id

    def _latest_decision_packet(self) -> dict[str, Any] | None:
        packets = self.db.list_decision_packets(self.run_id)
        return packets[-1] if packets else None

    def execute(self, *, actions: list[ResumeAction]) -> dict[str, Any]:
        executed: list[dict[str, Any]] = []
        for action in actions:
            if action.action == "await_human_decision":
                return {"run_id": self.run_id, "executed": executed, "blocked": self._latest_decision_packet()}
            executed.append(asdict(action))
        return {"run_id": self.run_id, "executed": executed, "blocked": None}
```

This task creates the planner/executor contract and human-decision stop. Task 6 connects action execution to extracted activity boundaries.

- [ ] **Step 5: Wire `runner.resume()` through planner/executor**

Modify `resume()` in `skills/agent-runway/scripts/agentrunway/runner.py`:

```python
    from .resume_executor import ResumeExecutor
    from .resume_planner import plan_resume_actions

    resume_actions = plan_resume_actions(run_id=run_id, db=db)
    if dry_run:
        return {
            **plan,
            "activity_resume": activity_resume,
            "durable": durable_projection,
            "resume_actions": [action.__dict__ for action in resume_actions],
            "next_action": durable_projection.get("next_automatic_action") or activity_resume.get("next_action"),
        }
    apply_reconciliation_plan(db=db, plan=plan)
    execution = ResumeExecutor(db=db, run_id=run_id).execute(actions=resume_actions)
```

Return:

```python
    return {
        "run_id": run_id,
        "status": data.get("status"),
        "run_dir": data.get("run_dir"),
        "reconciliation": plan,
        "activity_resume": activity_resume,
        "resume_actions": [action.__dict__ for action in resume_actions],
        "execution": execution,
    }
```

- [ ] **Step 6: Run resume tests**

Run:

```bash
cd skills/agent-runway && python -m pytest evals/test_resume_executor.py evals/test_resume_apply.py evals/test_durable_resume.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit Task 5**

```bash
git add skills/agent-runway/scripts/agentrunway/resume_planner.py \
  skills/agent-runway/scripts/agentrunway/resume_executor.py \
  skills/agent-runway/scripts/agentrunway/runner.py \
  skills/agent-runway/evals/test_resume_executor.py \
  skills/agent-runway/evals/test_resume_apply.py
git commit -m "feat: plan AgentRunway automatic resume actions"
```

---

### Task 6: Connect Resume Executor To Activity Boundaries And Finish Cleanup

```yaml agentrunway-task
task_id: task_006
title: Connect Resume Executor To Activity Boundaries And Finish Cleanup
risk: high
phase: implementation
dependencies: [task_003, task_005]
spec_refs: [S1.5, S1.7, S1.11, S1.12]
file_claims:
  - {path: skills/agent-runway/scripts/agentrunway/activity_runner.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/gate_runner.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/resume_executor.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/runner.py, mode: owned}
  - {path: skills/agent-runway/evals/test_resume_executor.py, mode: owned}
  - {path: skills/agent-runway/evals/test_runner_production_e2e.py, mode: shared_append}
acceptance_commands:
  - cd skills/agent-runway && python -m pytest evals/test_resume_executor.py evals/test_runner_production_e2e.py evals/test_durable_orchestrator_e2e.py -v
required_skills: [test-driven-development]
serial: true
```

**Files:**
- Modify: `skills/agent-runway/scripts/agentrunway/activity_runner.py`
- Modify: `skills/agent-runway/scripts/agentrunway/gate_runner.py`
- Modify: `skills/agent-runway/scripts/agentrunway/resume_executor.py`
- Modify: `skills/agent-runway/scripts/agentrunway/runner.py`
- Modify: `skills/agent-runway/evals/test_resume_executor.py`
- Modify: `skills/agent-runway/evals/test_runner_production_e2e.py`

- [ ] **Step 1: Add resume executor boundary assertions**

Append to `skills/agent-runway/evals/test_resume_executor.py`:

```python
def test_resume_executor_records_automatic_action_event(tmp_path: Path) -> None:
    store = _store(tmp_path)
    action = ResumeAction(
        action="verify_checkpoint",
        task_id="task_001",
        candidate_id=7,
        writes=True,
        reason="merge_completed_checkpoint_should_exist",
    )

    result = ResumeExecutor(db=store.db, run_id="run-1").execute(actions=[action])
    events = store.db.list_workflow_events("run-1")

    assert result["executed"] == [action.__dict__]
    assert events[-1]["event_type"] == "ResumeActionExecuted"
    assert events[-1]["payload"]["action"] == "verify_checkpoint"
```

- [ ] **Step 2: Run the new resume executor assertion to verify failure**

Run:

```bash
cd skills/agent-runway && python -m pytest evals/test_resume_executor.py::test_resume_executor_records_automatic_action_event -v
```

Expected: FAIL because `ResumeExecutor.execute()` does not record workflow events.

- [ ] **Step 3: Record automatic resume actions**

Modify `ResumeExecutor.execute()` in `skills/agent-runway/scripts/agentrunway/resume_executor.py`:

```python
            self.db.insert_workflow_event(
                run_id=self.run_id,
                event_type="ResumeActionExecuted",
                node_id=f"{action.task_id}.{action.action}" if action.task_id else action.action,
                payload=asdict(action),
            )
            executed.append(asdict(action))
```

This keeps automatic resume observable before wiring each action into deeper boundary methods.

- [ ] **Step 4: Move decision packet creation into `GateRunner`**

Extend `GateRunner` with a helper:

```python
    def decision_packet_payload(
        self,
        *,
        gate: str,
        status: str,
        result: dict[str, Any],
        candidate: dict[str, Any],
        next_action: str,
        policy_reason: str,
    ) -> dict[str, Any]:
        return {
            "gate": gate,
            "status": status,
            "result": result,
            "candidate": {
                "id": candidate["id"],
                "worker_id": candidate["worker_id"],
                "changed_files": candidate["changed_files"],
                "commits": candidate["commits"],
            },
            "next_action": next_action,
            "policy_reason": policy_reason,
        }
```

Replace duplicated inline payload literals in `runner.py` review and verification branches with `gate_runner.decision_packet_payload(...)`.

- [ ] **Step 5: Keep runner as orchestration shell**

After replacement, remove unused helpers from `runner.py` when no longer referenced:

```python
_gate_activity_status
_decision_for_classification
```

Keep `_gate_decision_packet` until a follow-up removes all packet creation from runner. The acceptance target for this task is reduced duplication, not a second large rewrite.

- [ ] **Step 6: Run resume and production e2e tests**

Run:

```bash
cd skills/agent-runway && python -m pytest evals/test_resume_executor.py evals/test_runner_production_e2e.py evals/test_durable_orchestrator_e2e.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit Task 6**

```bash
git add skills/agent-runway/scripts/agentrunway/activity_runner.py \
  skills/agent-runway/scripts/agentrunway/gate_runner.py \
  skills/agent-runway/scripts/agentrunway/resume_executor.py \
  skills/agent-runway/scripts/agentrunway/runner.py \
  skills/agent-runway/evals/test_resume_executor.py \
  skills/agent-runway/evals/test_runner_production_e2e.py
git commit -m "feat: execute AgentRunway resume actions durably"
```

---

### Task 7: Final Consistency, Documentation, And Verification

```yaml agentrunway-task
task_id: task_007
title: Final Consistency Documentation And Verification
risk: medium
phase: verification
dependencies: [task_004, task_006]
spec_refs: [S1.9, S1.12]
file_claims:
  - {path: skills/agent-runway/README.md, mode: owned}
  - {path: skills/agent-runway/references/context-policy.md, mode: shared_append}
  - {path: skills/agent-runway/references/worktree-policy.md, mode: shared_append}
  - {path: docs/superpowers/specs/2026-05-20-agentrunway-durable-orchestrator-hardening-design.md, mode: shared_append}
acceptance_commands:
  - cd skills/agent-runway && ./evals/run.sh
  - cd skills/agent-runway && python -m py_compile scripts/agentrunway/*.py scripts/agentrunway/adapters/*.py
  - git diff --check
  - graphify update .
required_skills: [verification-before-completion]
serial: true
```

**Files:**
- Modify: `skills/agent-runway/README.md`
- Modify: `skills/agent-runway/references/context-policy.md`
- Modify: `skills/agent-runway/references/worktree-policy.md`
- Modify: `docs/superpowers/specs/2026-05-20-agentrunway-durable-orchestrator-hardening-design.md`

- [ ] **Step 1: Update README durable orchestrator section**

Add a concise subsection under the AgentRunway durable integration documentation in `skills/agent-runway/README.md`:

```markdown
### Durable Orchestrator Hardening

AgentRunway uses checkpoint evidence, not task status alone, to release
dependent work. `inspect`, `summarize`, and `resume --dry-run` share the same
durable projection for latest checkpoint, ready queue, safe wave, blocked
activity, failure class, and required human decision.

Automatic resume actions are recorded as workflow events. Human-decision
failure classes stop with decision packets so operators can inspect and decide
without rerunning completed activity work.
```

- [ ] **Step 2: Update references with checkpoint dispatch rule**

Append to `skills/agent-runway/references/context-policy.md`:

```markdown
## Durable Resume Context

Resume context comes from completed activity output refs and the durable
projection. Workers must not infer dependency readiness from task status alone;
dependency release requires a checkpoint whose reason maps to the dependency
task id.
```

Append to `skills/agent-runway/references/worktree-policy.md`:

```markdown
## Checkpoint Dispatch

Runtime dispatch starts workers from run main after the latest successful
checkpoint. Dependent tasks wait until their dependencies have checkpoint rows.
Conflicting file claims, high-risk tasks, serial tasks, broad claims, and
shared resource keys are serialized by the checkpoint scheduler.
```

- [ ] **Step 3: Update hardening spec status note**

Append to `docs/superpowers/specs/2026-05-20-agentrunway-durable-orchestrator-hardening-design.md`:

```markdown
## 13. Implementation Note

This design is implemented by
`docs/superpowers/plans/2026-05-21-agentrunway-durable-orchestrator-hardening.md`.
The implementation plan preserves the design goals while extracting activity
and gate boundaries before executable resume, so fresh runs and resume use the
same durable execution path.
```

- [ ] **Step 4: Run focused final tests**

Run:

```bash
cd skills/agent-runway && python -m pytest \
  evals/test_durable_projection.py \
  evals/test_checkpoint_scheduler.py \
  evals/test_checkpoint_scheduler_runtime.py \
  evals/test_activity_runner.py \
  evals/test_gate_runner.py \
  evals/test_resume_executor.py \
  evals/test_resume_apply.py \
  evals/test_durable_orchestrator_e2e.py \
  evals/test_runner_production_e2e.py \
  evals/test_run_summary.py \
  -v
```

Expected: PASS.

- [ ] **Step 5: Run full AgentRunway evals**

Run:

```bash
cd skills/agent-runway && ./evals/run.sh
```

Expected: all tests pass.

- [ ] **Step 6: Run compile and diff checks**

Run:

```bash
cd skills/agent-runway && python -m py_compile scripts/agentrunway/*.py scripts/agentrunway/adapters/*.py
git diff --check
```

Expected: both commands pass with no output from `git diff --check`.

- [ ] **Step 7: Update graphify after code changes**

Run:

```bash
graphify update .
```

Expected: graph update completes. If `graph.html` is skipped because the graph is large, accept that output as long as `GRAPH_REPORT.md` and `graph.json` update successfully.

- [ ] **Step 8: Commit Task 7**

```bash
git add skills/agent-runway/README.md \
  skills/agent-runway/references/context-policy.md \
  skills/agent-runway/references/worktree-policy.md \
  docs/superpowers/specs/2026-05-20-agentrunway-durable-orchestrator-hardening-design.md \
  graphify-out/GRAPH_REPORT.md graphify-out/graph.json
git commit -m "docs: document AgentRunway durable orchestrator hardening"
```

If `graphify-out` remains ignored and cannot be staged, commit the documentation files only and mention the graph update in the verification summary.

---

## Final Verification Checklist

- [ ] `cd skills/agent-runway && ./evals/run.sh`
- [ ] `cd skills/agent-runway && python -m py_compile scripts/agentrunway/*.py scripts/agentrunway/adapters/*.py`
- [ ] `git diff --check`
- [ ] `graphify update .`
- [ ] `git status --short --branch`

## Self-Review

Spec coverage:

- Durable projection: Task 1.
- Checkpoint-aware runtime dispatch: Tasks 2 and 4.
- Executable resume action plan and durable events: Tasks 5 and 6.
- Activity and gate boundaries: Tasks 3 and 6.
- Consistent inspect, summarize, and resume dry-run surfaces: Task 1 with final verification in Task 7.
- Human decision packet behavior: Tasks 1, 3, 5, and 6.
- Final docs and graph update: Task 7.

Plan quality checks:

- No implementation task relies on source checkout mutation.
- Every task has concrete files and acceptance commands.
- New modules are introduced behind focused failing tests.
- Large runner changes are protected by existing production e2e tests and the dependent checkpoint regression.
