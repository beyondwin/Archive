# AgentRunway Hybrid Scheduler Failure Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make AgentRunway parallelize only checkpoint-ready independent work, serialize shared-core work, and stop or repair correctly when failures make downstream dispatch unsafe.

**Architecture:** Add a small task classifier first, then make the durable projection authoritative for ready, withheld, stale, and blocked state. Runtime dispatch continues to read `projection.safe_wave`, while resume and final status use the same projection to prevent task-status drift. Gate depth becomes classification-aware so low-risk independent work stays fast and shared-core work still gets full review.

**Tech Stack:** Python 3, SQLite, pytest, git worktrees, AgentRunway fake runtime fixtures, existing durable projection/checkpoint scheduler/resume executor modules.

---

## Scope Check

This plan implements:

- `docs/superpowers/specs/2026-05-21-agentrunway-hybrid-scheduler-failure-recovery-design.md`

It is a single implementation slice because task classification, durable projection barriers, runtime dispatch, resume recovery, and gate depth all depend on the same state model. The plan keeps the work split by module boundary so independent tasks can still be reviewed and landed incrementally.

## File Structure

- `skills/agent-runway/scripts/agentrunway/task_classifier.py`
  - New pure classifier for `independent`, `soft_overlap`, `shared_core`, `barrier`, and `blocked_dependent` task classes.
- `skills/agent-runway/scripts/agentrunway/durable_projection.py`
  - Add withheld task reasons, stale activity detection, upstream blocked dependency barriers, and projection-derived run status.
- `skills/agent-runway/scripts/agentrunway/checkpoint_scheduler.py`
  - Keep runtime dispatch as a thin reader of `projection.safe_wave`, but expose classification metadata for diagnostics.
- `skills/agent-runway/scripts/agentrunway/resume_executor.py`
  - Normalize automatic resume failures into blocked results, including non-`RuntimeError` exceptions.
- `skills/agent-runway/scripts/agentrunway/resume_planner.py`
  - Add stale activity and missing handler action names to the action model.
- `skills/agent-runway/scripts/agentrunway/worktree_lifecycle.py`
  - Make reviewer mode classification-aware.
- `skills/agent-runway/scripts/agentrunway/runner.py`
  - Use projection-derived final status and refresh artifact graph after resume execution.
- `skills/agent-runway/scripts/agentrunway/run_summary.py`
  - Surface scheduler classes, withheld tasks, stale activities, and projection status.
- `skills/agent-runway/scripts/agentrunway/status.py`
  - Surface the same projection details in inspect/status payloads.
- `skills/agent-runway/evals/test_task_classifier.py`
  - New unit tests for classification semantics.
- `skills/agent-runway/evals/test_durable_projection.py`
  - Extend with blocked dependency, withheld task, stale activity, and projection status tests.
- `skills/agent-runway/evals/test_checkpoint_scheduler_runtime.py`
  - Extend with shared-core serialization and barrier visibility tests.
- `skills/agent-runway/evals/test_resume_executor.py`
  - Extend with exception normalization and stale/missing-handler blocking tests.
- `skills/agent-runway/evals/test_runner_production_e2e.py`
  - Extend with a regression that blocked upstream work prevents downstream worktree creation.
- `skills/agent-runway/evals/test_run_summary.py`
  - Extend with projection diagnostics assertions.
- `skills/agent-runway/README.md`
  - Document the hybrid scheduler and failure barrier rules.
- `skills/agent-runway/references/worktree-policy.md`
  - Document lazy worker worktree creation and checkpoint-start policy.

---

### Task 1: Add Task Classification

```yaml agentrunway-task
task_id: task_001
title: Add Task Classification
risk: medium
phase: implementation
dependencies: []
spec_refs: [S4, S8, S11]
file_claims:
  - {path: skills/agent-runway/scripts/agentrunway/task_classifier.py, mode: owned}
  - {path: skills/agent-runway/evals/test_task_classifier.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/worktree_lifecycle.py, mode: shared_append}
  - {path: skills/agent-runway/evals/test_worktree_lifecycle.py, mode: shared_append}
acceptance_commands:
  - cd skills/agent-runway && python -m pytest evals/test_task_classifier.py evals/test_worktree_lifecycle.py -v
required_skills: [test-driven-development]
serial: true
```

**Files:**
- Create: `skills/agent-runway/scripts/agentrunway/task_classifier.py`
- Create: `skills/agent-runway/evals/test_task_classifier.py`
- Modify: `skills/agent-runway/scripts/agentrunway/worktree_lifecycle.py`
- Modify: `skills/agent-runway/evals/test_worktree_lifecycle.py`

- [ ] **Step 1: Write failing task classifier tests**

Create `skills/agent-runway/evals/test_task_classifier.py`:

```python
from __future__ import annotations

from agentrunway.models import FileClaim, TaskSpec
from agentrunway.task_classifier import TaskExecutionClass, classify_task


def _task(
    task_id: str = "task_001",
    *,
    risk: str = "low",
    claims: tuple[FileClaim, ...] = (FileClaim("src/a.py", "owned"),),
    resources: tuple[str, ...] = (),
    serial: bool = False,
) -> TaskSpec:
    return TaskSpec(
        task_id=task_id,
        title=task_id,
        risk=risk,  # type: ignore[arg-type]
        phase="implementation",
        dependencies=(),
        spec_refs=("S1",),
        file_claims=claims,
        acceptance_commands=("python -m pytest",),
        resource_keys=resources,
        serial=serial,
    )


def test_independent_owned_low_risk_task() -> None:
    result = classify_task(_task())

    assert result.execution_class == "independent"
    assert result.review_mode == "diff"
    assert result.serial_required is False
    assert result.reasons == ("owned_files", "low_or_medium_risk")


def test_shared_core_runner_task_is_serial_full_tree() -> None:
    result = classify_task(
        _task(claims=(FileClaim("skills/agent-runway/scripts/agentrunway/runner.py", "owned"),))
    )

    assert result.execution_class == "shared_core"
    assert result.review_mode == "full_tree"
    assert result.serial_required is True
    assert "shared_core_path" in result.reasons


def test_broad_claim_is_barrier() -> None:
    result = classify_task(_task(claims=(FileClaim("skills/agent-runway/scripts/agentrunway/**", "owned"),)))

    assert result.execution_class == "barrier"
    assert result.serial_required is True
    assert "broad_claim" in result.reasons


def test_schema_and_generated_surfaces_are_barriers() -> None:
    schema = classify_task(_task(claims=(FileClaim("migrations/001_add_table.sql", "owned"),)))
    generated = classify_task(_task(claims=(FileClaim("src/generated/client.py", "owned"),)))

    assert schema.execution_class == "barrier"
    assert schema.review_mode == "full_tree"
    assert "schema_or_generated_surface" in schema.reasons
    assert generated.execution_class == "barrier"
    assert generated.review_mode == "full_tree"
    assert "schema_or_generated_surface" in generated.reasons


def test_shared_append_is_soft_overlap() -> None:
    result = classify_task(_task(claims=(FileClaim("skills/agent-runway/README.md", "shared_append"),)))

    assert result.execution_class == "soft_overlap"
    assert result.review_mode == "diff"
    assert result.serial_required is False


def test_blocked_dependency_overrides_other_classes() -> None:
    result = classify_task(_task(), blocked_dependencies={"task_000"})

    assert result.execution_class == "blocked_dependent"
    assert result.serial_required is True
    assert result.blocked_dependencies == ("task_000",)
```

- [ ] **Step 2: Run classifier tests to verify failure**

Run:

```bash
cd skills/agent-runway && python -m pytest evals/test_task_classifier.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'agentrunway.task_classifier'`.

- [ ] **Step 3: Implement `task_classifier.py`**

Create `skills/agent-runway/scripts/agentrunway/task_classifier.py`:

```python
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

from .models import TaskSpec


TaskClassName = Literal["independent", "soft_overlap", "shared_core", "barrier", "blocked_dependent"]
ReviewMode = Literal["diff", "full_tree"]

_SHARED_CORE_PATHS = (
    "skills/agent-runway/scripts/agentrunway/runner.py",
    "skills/agent-runway/scripts/agentrunway/scheduler.py",
    "skills/agent-runway/scripts/agentrunway/checkpoint_scheduler.py",
    "skills/agent-runway/scripts/agentrunway/durable_projection.py",
    "skills/agent-runway/scripts/agentrunway/resume_executor.py",
    "skills/agent-runway/scripts/agentrunway/resume_planner.py",
    "skills/agent-runway/scripts/agentrunway/gate_runner.py",
    "skills/agent-runway/scripts/agentrunway/db.py",
    "skills/agent-runway/scripts/agentrunway/workflow_store.py",
)
_FULL_TREE_PATH_MARKERS = (
    "migration",
    "migrations/",
    "schema",
    "generated/",
    ".generated",
)


@dataclass(frozen=True)
class TaskExecutionClass:
    task_id: str
    execution_class: TaskClassName
    review_mode: ReviewMode
    serial_required: bool
    reasons: tuple[str, ...]
    blocked_dependencies: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _has_broad_claim(task: TaskSpec) -> bool:
    return any(any(ch in claim.path for ch in "*?[") or claim.path.endswith("/**") for claim in task.file_claims)


def _touches_shared_core(task: TaskSpec) -> bool:
    return any(claim.path in _SHARED_CORE_PATHS for claim in task.file_claims)


def _touches_schema_or_generated_surface(task: TaskSpec) -> bool:
    for claim in task.file_claims:
        normalized = claim.path.replace("\\", "/").lower()
        if any(marker in normalized for marker in _FULL_TREE_PATH_MARKERS):
            return True
    return False


def _has_shared_append_only(task: TaskSpec) -> bool:
    return bool(task.file_claims) and all(claim.mode in {"shared_append", "read_only"} for claim in task.file_claims)


def classify_task(task: TaskSpec, *, blocked_dependencies: set[str] | None = None) -> TaskExecutionClass:
    blocked = tuple(sorted(blocked_dependencies or set()))
    if blocked:
        return TaskExecutionClass(
            task_id=task.task_id,
            execution_class="blocked_dependent",
            review_mode="full_tree",
            serial_required=True,
            reasons=("blocked_dependency",),
            blocked_dependencies=blocked,
        )
    if task.serial or task.risk == "high" or _has_broad_claim(task) or _touches_schema_or_generated_surface(task):
        reasons = []
        if task.serial:
            reasons.append("task_serial")
        if task.risk == "high":
            reasons.append("high_risk")
        if _has_broad_claim(task):
            reasons.append("broad_claim")
        if _touches_schema_or_generated_surface(task):
            reasons.append("schema_or_generated_surface")
        return TaskExecutionClass(
            task_id=task.task_id,
            execution_class="barrier",
            review_mode="full_tree",
            serial_required=True,
            reasons=tuple(reasons),
        )
    if _touches_shared_core(task):
        return TaskExecutionClass(
            task_id=task.task_id,
            execution_class="shared_core",
            review_mode="full_tree",
            serial_required=True,
            reasons=("shared_core_path",),
        )
    if _has_shared_append_only(task):
        return TaskExecutionClass(
            task_id=task.task_id,
            execution_class="soft_overlap",
            review_mode="diff",
            serial_required=False,
            reasons=("shared_append_or_read_only",),
        )
    return TaskExecutionClass(
        task_id=task.task_id,
        execution_class="independent",
        review_mode="diff",
        serial_required=False,
        reasons=("owned_files", "low_or_medium_risk"),
    )
```

- [ ] **Step 4: Make reviewer mode classification-aware**

Modify `skills/agent-runway/scripts/agentrunway/worktree_lifecycle.py` so `reviewer_mode_for_task()` starts with:

```python
from .task_classifier import classify_task
```

and replace the function body with:

```python
def reviewer_mode_for_task(task: TaskSpec, *, force_full_tree: bool = False) -> str:
    if force_full_tree:
        return "full_tree"
    return classify_task(task).review_mode
```

- [ ] **Step 5: Add reviewer mode regression tests**

Append to `skills/agent-runway/evals/test_worktree_lifecycle.py`:

```python
def test_reviewer_mode_uses_diff_for_independent_task() -> None:
    assert reviewer_mode_for_task(_review_task("src/a.py")) == "diff"


def test_reviewer_mode_uses_full_tree_for_shared_core_task() -> None:
    task = _review_task("skills/agent-runway/scripts/agentrunway/runner.py")
    assert reviewer_mode_for_task(task) == "full_tree"
```

- [ ] **Step 6: Run Task 1 tests**

Run:

```bash
cd skills/agent-runway && python -m pytest evals/test_task_classifier.py evals/test_worktree_lifecycle.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit Task 1**

```bash
git add skills/agent-runway/scripts/agentrunway/task_classifier.py \
  skills/agent-runway/scripts/agentrunway/worktree_lifecycle.py \
  skills/agent-runway/evals/test_task_classifier.py \
  skills/agent-runway/evals/test_worktree_lifecycle.py
git commit -m "feat: classify AgentRunway task execution"
```

---

### Task 2: Make Durable Projection Enforce Failure Barriers

```yaml agentrunway-task
task_id: task_002
title: Make Durable Projection Enforce Failure Barriers
risk: high
phase: implementation
dependencies: [task_001]
spec_refs: [S6, S7, S9, S11]
file_claims:
  - {path: skills/agent-runway/scripts/agentrunway/durable_projection.py, mode: owned}
  - {path: skills/agent-runway/evals/test_durable_projection.py, mode: owned}
acceptance_commands:
  - cd skills/agent-runway && python -m pytest evals/test_durable_projection.py -v
required_skills: [test-driven-development]
serial: true
```

**Files:**
- Modify: `skills/agent-runway/scripts/agentrunway/durable_projection.py`
- Modify: `skills/agent-runway/evals/test_durable_projection.py`

- [ ] **Step 1: Add failing projection barrier tests**

Append to `skills/agent-runway/evals/test_durable_projection.py`:

```python
from datetime import datetime, timedelta, timezone


def test_projection_blocks_dependent_when_upstream_task_is_blocked(tmp_path: Path) -> None:
    db = _db(tmp_path)
    db.upsert_task(_task("task_001"))
    db.upsert_task(_task("task_002", deps=("task_001",)))
    db.set_task_status("task_001", "blocked")

    projection = read_durable_projection(run_id="run-1", db=db)

    assert [task["task_id"] for task in projection.safe_wave] == []
    assert projection.withheld_tasks == [
        {
            "task_id": "task_002",
            "reason": "blocked_dependency",
            "blocked_dependencies": ["task_001"],
        }
    ]
    assert projection.projection_status == "blocked"


def test_projection_withholds_all_dispatch_when_human_decision_exists(tmp_path: Path) -> None:
    db = _db(tmp_path)
    store = WorkflowStore(db)
    db.upsert_task(_task("task_001"))
    db.upsert_task(_task("task_002"))
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
        failure_class="needs_infra_fix",
    )
    store.create_decision_packet(
        run_id="run-1",
        decision_id="task_001.review.001.decision",
        task_id="task_001",
        failure_class="needs_infra_fix",
        summary="infra fix",
        payload={"candidate_id": 7},
    )

    projection = read_durable_projection(run_id="run-1", db=db)

    assert projection.required_human_decision == "fix infrastructure"
    assert projection.safe_wave == []
    assert projection.projection_status == "blocked"


def test_projection_marks_started_activity_as_stale(tmp_path: Path) -> None:
    db = _db(tmp_path)
    store = WorkflowStore(db)
    db.upsert_task(_task("task_001"))
    store.start_activity(
        run_id="run-1",
        activity_id="task_001.implement.001",
        idempotency_key="run-1:task_001:implement:001",
        task_id="task_001",
        activity_type="implement",
        input_refs={},
    )
    stale_time = (datetime.now(timezone.utc) - timedelta(hours=3)).replace(microsecond=0).isoformat()
    db.conn.execute(
        "UPDATE activities SET created_at=?, updated_at=? WHERE activity_id=?",
        (stale_time, stale_time, "task_001.implement.001"),
    )
    db.conn.commit()

    projection = read_durable_projection(run_id="run-1", db=db, stale_after_seconds=60)

    assert projection.stale_activities[0]["activity_id"] == "task_001.implement.001"
    assert projection.next_automatic_action == "classify_stale_activity"
    assert projection.safe_wave == []
    assert projection.projection_status == "blocked"
```

- [ ] **Step 2: Run projection tests to verify failure**

Run:

```bash
cd skills/agent-runway && python -m pytest evals/test_durable_projection.py -v
```

Expected: FAIL because `withheld_tasks`, `stale_activities`, `projection_status`, and `stale_after_seconds` do not exist yet.

- [ ] **Step 3: Extend the projection dataclass**

In `skills/agent-runway/scripts/agentrunway/durable_projection.py`, update `DurableProjection` to include:

```python
    withheld_tasks: list[dict[str, Any]]
    stale_activities: list[dict[str, Any]]
    task_classes: list[dict[str, Any]]
    projection_status: str
```

Keep `to_dict()` as:

```python
    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["ready_queue"] = [task["task_id"] for task in self.ready_tasks]
        payload["safe_wave"] = [task["task_id"] for task in self.safe_wave]
        return payload
```

- [ ] **Step 4: Add stale and blocked dependency helpers**

Add these imports near the top:

```python
from datetime import datetime, timezone

from .task_classifier import classify_task
```

Add helper functions below `_compact_activity()`:

```python
def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _stale_activities(activities: list[dict[str, Any]], *, stale_after_seconds: int) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)
    stale: list[dict[str, Any]] = []
    for activity in activities:
        if activity.get("status") != "started":
            continue
        started = _parse_timestamp(activity.get("created_at"))
        if started is None:
            continue
        age = max((now - started).total_seconds(), 0)
        if age >= stale_after_seconds:
            payload = _compact_activity(activity)
            payload["age_seconds"] = int(age)
            stale.append(payload)
    return stale


def _blocked_dependency_map(task_rows: list[dict[str, Any]], tasks: list[TaskSpec]) -> dict[str, set[str]]:
    blocked_ids = {
        str(row["task_id"])
        for row in task_rows
        if str(row.get("status") or "") in {"blocked", "failed"}
    }
    return {
        task.task_id: set(task.dependencies) & blocked_ids
        for task in tasks
        if set(task.dependencies) & blocked_ids
    }
```

- [ ] **Step 5: Update `read_durable_projection()` signature and ready calculation**

Change the function signature to:

```python
def read_durable_projection(*, run_id: str, db: AgentRunwayDb, stale_after_seconds: int = 3600) -> DurableProjection:
```

Inside the function, after `tasks = _task_specs(db)`, compute:

```python
    blocked_dependencies = _blocked_dependency_map(task_rows, tasks)
    completed_tasks = {
        str(row["task_id"])
        for row in task_rows
        if str(row.get("status") or "") in _TERMINAL_TASK_STATUSES
    }
    ready = [
        task
        for task in ready_tasks_after_checkpoints(
            tasks,
            completed_checkpoints=set(completed_checkpoint_tasks),
            completed_tasks=completed_tasks,
        )
        if task.task_id not in blocked_dependencies
    ]
```

Replace the existing `completed_tasks` and `ready` block with that code.

- [ ] **Step 6: Add task classes, stale activities, barriers, and projection status**

After `activities = db.list_activities(run_id)`, add:

```python
    stale = _stale_activities(activities, stale_after_seconds=stale_after_seconds)
    task_classes = [
        classify_task(task, blocked_dependencies=blocked_dependencies.get(task.task_id, set())).to_dict()
        for task in tasks
    ]
    withheld_tasks = [
        {
            "task_id": task_id,
            "reason": "blocked_dependency",
            "blocked_dependencies": sorted(blocked),
        }
        for task_id, blocked in sorted(blocked_dependencies.items())
    ]
```

After `human_decision` and `decision_packet`, compute:

```python
    blocked_task_exists = any(str(row.get("status") or "") in {"blocked", "failed"} for row in task_rows)
    automatic_action = None if human_decision else ("verify_checkpoint" if checkpoint_repair_tasks else ("classify_stale_activity" if stale else ("resume" if blocked else None)))
    if human_decision or stale or blocked_task_exists or withheld_tasks:
        projection_status = "blocked"
    elif running:
        projection_status = "running"
    elif all(str(row.get("status") or "") == "merged" for row in task_rows) and not checkpoint_repair_tasks:
        projection_status = "finished"
    elif ready:
        projection_status = "running"
    else:
        projection_status = "blocked"
```

In the `DurableProjection(...)` return call:

```python
        safe_wave=[] if human_decision or stale else [_compact_task(task) for task in safe_wave],
        withheld_tasks=withheld_tasks,
        stale_activities=stale,
        task_classes=task_classes,
        next_automatic_action=automatic_action,
        projection_status=projection_status,
```

Replace the old `safe_wave` and `next_automatic_action` arguments with those values.

- [ ] **Step 7: Run Task 2 tests**

Run:

```bash
cd skills/agent-runway && python -m pytest evals/test_durable_projection.py -v
```

Expected: PASS.

- [ ] **Step 8: Commit Task 2**

```bash
git add skills/agent-runway/scripts/agentrunway/durable_projection.py \
  skills/agent-runway/evals/test_durable_projection.py
git commit -m "feat: block AgentRunway dispatch from durable projection"
```

---

### Task 3: Wire Hybrid Scheduler Diagnostics Into Runtime

```yaml agentrunway-task
task_id: task_003
title: Wire Hybrid Scheduler Diagnostics Into Runtime
risk: high
phase: implementation
dependencies: [task_002]
spec_refs: [S3, S4, S5, S7, S11]
file_claims:
  - {path: skills/agent-runway/scripts/agentrunway/checkpoint_scheduler.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/runner.py, mode: shared_append}
  - {path: skills/agent-runway/evals/test_checkpoint_scheduler_runtime.py, mode: owned}
  - {path: skills/agent-runway/evals/test_runner_production_e2e.py, mode: shared_append}
acceptance_commands:
  - cd skills/agent-runway && python -m pytest evals/test_checkpoint_scheduler_runtime.py evals/test_runner_production_e2e.py -v
required_skills: [test-driven-development]
serial: true
```

**Files:**
- Modify: `skills/agent-runway/scripts/agentrunway/checkpoint_scheduler.py`
- Modify: `skills/agent-runway/scripts/agentrunway/runner.py`
- Modify: `skills/agent-runway/evals/test_checkpoint_scheduler_runtime.py`
- Modify: `skills/agent-runway/evals/test_runner_production_e2e.py`

- [ ] **Step 1: Add failing scheduler metadata tests**

Append to `skills/agent-runway/evals/test_checkpoint_scheduler_runtime.py`:

```python
def test_scheduler_serializes_shared_core_ready_tasks(tmp_path: Path) -> None:
    db = _db(tmp_path)
    db.upsert_task(
        _task("task_001", claims=(FileClaim("skills/agent-runway/scripts/agentrunway/runner.py", "owned"),))
    )
    db.upsert_task(
        _task("task_002", claims=(FileClaim("skills/agent-runway/scripts/agentrunway/resume_executor.py", "owned"),))
    )
    projection = read_durable_projection(run_id="run-1", db=db)

    wave = CheckpointScheduler().next_wave(projection=projection)
    diagnostics = CheckpointScheduler().diagnostics(projection=projection)

    assert [task["task_id"] for task in wave] == ["task_001"]
    assert diagnostics["task_classes"]["task_001"]["execution_class"] == "shared_core"
    assert diagnostics["task_classes"]["task_002"]["serial_required"] is True


def test_scheduler_reports_withheld_tasks(tmp_path: Path) -> None:
    db = _db(tmp_path)
    db.upsert_task(_task("task_001"))
    db.upsert_task(_task("task_002", deps=("task_001",)))
    db.set_task_status("task_001", "blocked")
    projection = read_durable_projection(run_id="run-1", db=db)

    diagnostics = CheckpointScheduler().diagnostics(projection=projection)

    assert diagnostics["safe_wave"] == []
    assert diagnostics["withheld_tasks"][0]["task_id"] == "task_002"
    assert diagnostics["projection_status"] == "blocked"
```

- [ ] **Step 2: Run scheduler tests to verify failure**

Run:

```bash
cd skills/agent-runway && python -m pytest evals/test_checkpoint_scheduler_runtime.py -v
```

Expected: FAIL because `CheckpointScheduler.diagnostics()` does not exist and shared-core tasks may still share a wave.

- [ ] **Step 3: Make `schedule_safe_wave()` respect classifier serial requirements**

In `skills/agent-runway/scripts/agentrunway/scheduler.py`, import:

```python
from .task_classifier import classify_task
```

At the top of `_tasks_conflict()` add:

```python
    if classify_task(left).serial_required or classify_task(right).serial_required:
        return True
```

This preserves existing high-risk and broad-claim behavior while adding shared-core serialization.

- [ ] **Step 4: Add scheduler diagnostics**

Replace `skills/agent-runway/scripts/agentrunway/checkpoint_scheduler.py` with:

```python
from __future__ import annotations

from typing import Any


class CheckpointScheduler:
    def _payload(self, *, projection: Any) -> dict[str, Any]:
        if hasattr(projection, "to_dict"):
            return projection.to_dict()
        return dict(projection)

    def next_wave(self, *, projection: Any) -> list[dict[str, Any]]:
        safe_wave = getattr(projection, "safe_wave", None)
        if safe_wave is not None:
            return list(safe_wave)
        return list(self._payload(projection=projection).get("safe_wave") or [])

    def diagnostics(self, *, projection: Any) -> dict[str, Any]:
        payload = self._payload(projection=projection)
        return {
            "projection_status": payload.get("projection_status"),
            "safe_wave": payload.get("safe_wave") or [],
            "withheld_tasks": payload.get("withheld_tasks") or [],
            "stale_activities": payload.get("stale_activities") or [],
            "task_classes": {
                str(item["task_id"]): item
                for item in payload.get("task_classes") or []
                if isinstance(item, dict) and item.get("task_id")
            },
        }
```

- [ ] **Step 5: Add runtime regression for blocked upstream dispatch**

Append to `skills/agent-runway/evals/test_runner_production_e2e.py`:

```python
def test_blocked_upstream_prevents_downstream_worker_dispatch(git_repo: Path, isolated_home: Path) -> None:
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
        "dependencies: [task_001]\n"
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
    env["AGENTRUNWAY_FAKE_REVIEW_STATUS"] = "changes_requested"
    env["AGENTRUNWAY_FAKE_REVIEW_FINDING"] = "needs infrastructure repair before continuing"

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
    workers = conn.execute("SELECT task_id, role FROM workers ORDER BY worker_id").fetchall()
    tasks = conn.execute("SELECT task_id, status FROM tasks ORDER BY task_id").fetchall()
    assert payload["status"] == "blocked"
    assert ("task_002", "implementer") not in [(row[0], row[1]) for row in workers]
    assert dict(tasks)["task_002"] == "pending"
```

- [ ] **Step 6: Use projection status for final run status**

In `skills/agent-runway/scripts/agentrunway/runner.py`, replace the final status calculation block:

```python
    final_status = "blocked" if blocked or unfinished or final_projection.checkpoint_repair_tasks else "finished"
    if unfinished and not blocked and not final_projection.safe_wave:
        final_status = "blocked"
```

with:

```python
    final_status = final_projection.projection_status
    if final_status == "running" and not final_projection.safe_wave and unfinished:
        final_status = "blocked"
```

- [ ] **Step 7: Run Task 3 tests**

Run:

```bash
cd skills/agent-runway && python -m pytest evals/test_checkpoint_scheduler_runtime.py evals/test_runner_production_e2e.py -v
```

Expected: PASS.

- [ ] **Step 8: Commit Task 3**

```bash
git add skills/agent-runway/scripts/agentrunway/scheduler.py \
  skills/agent-runway/scripts/agentrunway/checkpoint_scheduler.py \
  skills/agent-runway/scripts/agentrunway/runner.py \
  skills/agent-runway/evals/test_checkpoint_scheduler_runtime.py \
  skills/agent-runway/evals/test_runner_production_e2e.py
git commit -m "feat: enforce AgentRunway hybrid scheduler barriers"
```

---

### Task 4: Harden Resume Failure Handling

```yaml agentrunway-task
task_id: task_004
title: Harden Resume Failure Handling
risk: high
phase: implementation
dependencies: [task_002]
spec_refs: [S6, S7, S9, S11]
file_claims:
  - {path: skills/agent-runway/scripts/agentrunway/resume_executor.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/resume_planner.py, mode: shared_append}
  - {path: skills/agent-runway/scripts/agentrunway/runner.py, mode: shared_append}
  - {path: skills/agent-runway/evals/test_resume_executor.py, mode: owned}
  - {path: skills/agent-runway/evals/test_resume_apply.py, mode: shared_append}
acceptance_commands:
  - cd skills/agent-runway && python -m pytest evals/test_resume_executor.py evals/test_resume_apply.py -v
required_skills: [test-driven-development]
serial: true
```

**Files:**
- Modify: `skills/agent-runway/scripts/agentrunway/resume_executor.py`
- Modify: `skills/agent-runway/scripts/agentrunway/resume_planner.py`
- Modify: `skills/agent-runway/scripts/agentrunway/runner.py`
- Modify: `skills/agent-runway/evals/test_resume_executor.py`
- Modify: `skills/agent-runway/evals/test_resume_apply.py`

- [ ] **Step 1: Add failing resume hardening tests**

Append to `skills/agent-runway/evals/test_resume_executor.py`:

```python
def test_resume_executor_blocks_non_runtime_handler_errors(tmp_path: Path) -> None:
    store = _store(tmp_path)
    action = ResumeAction(
        action="schedule_merge",
        task_id="task_001",
        candidate_id=7,
        writes=True,
        reason="verification_passed_merge_not_started",
    )

    def fail(_: ResumeAction) -> dict[str, object]:
        raise ValueError("bad handler")

    result = ResumeExecutor(
        db=store.db,
        run_id="run-1",
        handlers={"schedule_merge": fail},
    ).execute(actions=[action])

    assert result["executed"] == []
    assert result["blocked"] == {
        "action": "schedule_merge",
        "task_id": "task_001",
        "candidate_id": 7,
        "reason": "resume_action_failed:ValueError:bad handler",
    }


def test_resume_executor_blocks_classify_stale_activity_without_dispatch(tmp_path: Path) -> None:
    store = _store(tmp_path)
    action = ResumeAction(
        action="classify_stale_activity",
        task_id="task_001",
        candidate_id=None,
        writes=True,
        reason="started_activity_exceeded_timeout",
    )

    result = ResumeExecutor(db=store.db, run_id="run-1").execute(actions=[action])

    assert result["executed"] == []
    assert result["blocked"]["reason"] == "missing_resume_handler"
    assert store.db.list_workflow_events("run-1") == []
```

- [ ] **Step 2: Run resume tests to verify failure**

Run:

```bash
cd skills/agent-runway && python -m pytest evals/test_resume_executor.py -v
```

Expected: FAIL because `classify_stale_activity` is not a valid `ResumeActionName`, and non-`RuntimeError` exceptions are not normalized.

- [ ] **Step 3: Extend resume action names**

In `skills/agent-runway/scripts/agentrunway/resume_planner.py`, add `"classify_stale_activity"` to `ResumeActionName`:

```python
ResumeActionName = Literal[
    "schedule_review",
    "schedule_verification",
    "schedule_merge",
    "verify_checkpoint",
    "schedule_implementer_retry",
    "await_human_decision",
    "classify_stale_activity",
]
```

- [ ] **Step 4: Normalize non-runtime resume errors**

In `skills/agent-runway/scripts/agentrunway/resume_executor.py`, replace:

```python
            except RuntimeError as exc:
                return self._block(executed=executed, action=action, reason=str(exc))
```

with:

```python
            except RuntimeError as exc:
                return self._block(executed=executed, action=action, reason=str(exc))
            except Exception as exc:
                reason = f"resume_action_failed:{exc.__class__.__name__}:{exc}"
                return self._block(executed=executed, action=action, reason=reason)
```

- [ ] **Step 5: Add stale action planning from projection in `runner.resume()`**

In `skills/agent-runway/scripts/agentrunway/runner.py`, after:

```python
    resume_actions = plan_resume_actions(run_id=run_id, db=db)
```

add:

```python
    if durable_projection.get("next_automatic_action") == "classify_stale_activity":
        first_stale = (durable_projection.get("stale_activities") or [{}])[0]
        resume_actions = [
            *resume_actions,
            ResumeAction(
                action="classify_stale_activity",
                task_id=first_stale.get("task_id"),
                candidate_id=None,
                writes=True,
                reason="started_activity_exceeded_timeout",
            ),
        ]
```

Also import `ResumeAction` next to `plan_resume_actions` in the local import block:

```python
    from .resume_planner import ResumeAction, plan_resume_actions
```

- [ ] **Step 6: Refresh artifact graph after resume execution**

In `runner.resume()`, after `execution = ResumeExecutor(...).execute(...)`, add:

```python
    write_artifact_graph(run_dir=Path(str(data["run_dir"])), db=db)
```

- [ ] **Step 7: Run Task 4 tests**

Run:

```bash
cd skills/agent-runway && python -m pytest evals/test_resume_executor.py evals/test_resume_apply.py -v
```

Expected: PASS.

- [ ] **Step 8: Commit Task 4**

```bash
git add skills/agent-runway/scripts/agentrunway/resume_executor.py \
  skills/agent-runway/scripts/agentrunway/resume_planner.py \
  skills/agent-runway/scripts/agentrunway/runner.py \
  skills/agent-runway/evals/test_resume_executor.py \
  skills/agent-runway/evals/test_resume_apply.py
git commit -m "feat: harden AgentRunway resume failure handling"
```

---

### Task 5: Surface Hybrid Scheduler State In Inspect And Summary

```yaml agentrunway-task
task_id: task_005
title: Surface Hybrid Scheduler State In Inspect And Summary
risk: medium
phase: implementation
dependencies: [task_002, task_003]
spec_refs: [S4, S7, S9, S11]
file_claims:
  - {path: skills/agent-runway/scripts/agentrunway/run_summary.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/status.py, mode: owned}
  - {path: skills/agent-runway/evals/test_run_summary.py, mode: owned}
  - {path: skills/agent-runway/evals/test_status_payload.py, mode: owned}
acceptance_commands:
  - cd skills/agent-runway && python -m pytest evals/test_run_summary.py evals/test_status_payload.py -v
required_skills: [test-driven-development]
serial: true
```

**Files:**
- Modify: `skills/agent-runway/scripts/agentrunway/run_summary.py`
- Modify: `skills/agent-runway/scripts/agentrunway/status.py`
- Modify: `skills/agent-runway/evals/test_run_summary.py`
- Create: `skills/agent-runway/evals/test_status_payload.py`

- [ ] **Step 1: Add failing summary diagnostics test**

Append to `skills/agent-runway/evals/test_run_summary.py`:

```python
def test_run_summary_includes_hybrid_scheduler_diagnostics(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    db = AgentRunwayDb.open(run_dir / "state.sqlite")
    db.upsert_task(
        TaskSpec(
            task_id="task_001",
            title="Task 1",
            risk="low",
            phase="implementation",
            dependencies=(),
            spec_refs=("S1",),
            file_claims=(FileClaim("skills/agent-runway/scripts/agentrunway/runner.py", "owned"),),
            acceptance_commands=("python -m pytest",),
        )
    )
    run_json = {
        "run_id": "run-1",
        "status": "running",
        "run_dir": str(run_dir),
        "state_db": str(run_dir / "state.sqlite"),
        "events": str(run_dir / "events.jsonl"),
    }
    (run_dir / "run.json").write_text(json.dumps(run_json), encoding="utf-8")
    (run_dir / "events.jsonl").write_text("", encoding="utf-8")

    summary = summarize_run(run_dir)

    assert summary["scheduler"]["projection_status"] == "running"
    assert summary["scheduler"]["safe_wave"] == ["task_001"]
    assert summary["scheduler"]["task_classes"][0]["execution_class"] == "shared_core"
```

- [ ] **Step 2: Run summary test to verify failure**

Run:

```bash
cd skills/agent-runway && python -m pytest evals/test_run_summary.py::test_run_summary_includes_hybrid_scheduler_diagnostics -v
```

Expected: FAIL with `KeyError: 'scheduler'`.

- [ ] **Step 3: Add inspect formatter test**

Create `skills/agent-runway/evals/test_status_payload.py`:

```python
from __future__ import annotations

from agentrunway.status import format_inspect_payload


def test_format_inspect_payload_includes_scheduler_state() -> None:
    text = format_inspect_payload(
        {
            "run_id": "run-1",
            "status": "blocked",
            "diagnosis": {"status": "blocked", "reason": "blocked_dependency"},
            "tasks": [{"task_id": "task_001"}],
            "workers": [],
            "coverage": {"covered": [], "blocked": []},
            "agentlens": {"failed": 0},
            "next_action": "await_human_decision",
            "durable": {
                "projection_status": "blocked",
                "safe_wave": [],
                "withheld_tasks": [{"task_id": "task_002"}],
                "stale_activities": [{"activity_id": "task_001.implement.001"}],
            },
        }
    )

    assert "projection=blocked" in text
    assert "safe_wave=0" in text
    assert "withheld=1" in text
    assert "stale=1" in text
```

- [ ] **Step 4: Add top-level scheduler summary**

In `skills/agent-runway/scripts/agentrunway/run_summary.py`, after `summary.update(workflow)`, add:

```python
    durable = workflow.get("durable") if isinstance(workflow, dict) else {}
    if isinstance(durable, dict):
        summary["scheduler"] = {
            "projection_status": durable.get("projection_status"),
            "safe_wave": durable.get("safe_wave") or [],
            "withheld_tasks": durable.get("withheld_tasks") or [],
            "stale_activities": durable.get("stale_activities") or [],
            "task_classes": durable.get("task_classes") or [],
        }
```

- [ ] **Step 5: Add scheduler fields to inspect formatter**

In `skills/agent-runway/scripts/agentrunway/status.py`, replace `format_inspect_payload()` with:

```python
def format_inspect_payload(payload: dict[str, Any]) -> str:
    agentlens = payload.get("agentlens", {})
    coverage = payload.get("coverage", {})
    diagnosis = payload.get("diagnosis", {})
    durable = payload.get("durable") if isinstance(payload.get("durable"), dict) else {}
    return (
        f"{payload.get('run_id')} status={payload.get('status')} "
        f"diagnosis={diagnosis.get('status')} "
        f"reason={diagnosis.get('reason')} "
        f"tasks={len(payload.get('tasks', []))} "
        f"workers={len(payload.get('workers', []))} "
        f"covered={len(coverage.get('covered', []))} "
        f"blocked={len(coverage.get('blocked', []))} "
        f"projection={durable.get('projection_status')} "
        f"safe_wave={len(durable.get('safe_wave') or [])} "
        f"withheld={len(durable.get('withheld_tasks') or [])} "
        f"stale={len(durable.get('stale_activities') or [])} "
        f"agentlens_failed={agentlens.get('failed', 0)} "
        f"next_action={payload.get('next_action')}"
    )
```

- [ ] **Step 6: Run Task 5 tests**

Run:

```bash
cd skills/agent-runway && python -m pytest evals/test_run_summary.py evals/test_status_payload.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit Task 5**

```bash
git add skills/agent-runway/scripts/agentrunway/run_summary.py \
  skills/agent-runway/scripts/agentrunway/status.py \
  skills/agent-runway/evals/test_run_summary.py \
  skills/agent-runway/evals/test_status_payload.py
git commit -m "feat: expose AgentRunway hybrid scheduler diagnostics"
```

---

### Task 6: Documentation And Final Verification

```yaml agentrunway-task
task_id: task_006
title: Documentation And Final Verification
risk: medium
phase: verification
dependencies: [task_003, task_004, task_005]
spec_refs: [S5, S8, S9, S10, S11]
file_claims:
  - {path: skills/agent-runway/README.md, mode: shared_append}
  - {path: skills/agent-runway/references/worktree-policy.md, mode: shared_append}
  - {path: docs/superpowers/specs/2026-05-21-agentrunway-hybrid-scheduler-failure-recovery-design.md, mode: shared_append}
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
- Modify: `skills/agent-runway/references/worktree-policy.md`
- Modify: `docs/superpowers/specs/2026-05-21-agentrunway-hybrid-scheduler-failure-recovery-design.md`

- [ ] **Step 1: Document hybrid scheduler behavior**

Append to `skills/agent-runway/README.md`:

```markdown
### Hybrid Scheduler And Failure Barriers

AgentRunway dispatches work from the durable projection. A task enters a worker
worktree only when dependency checkpoints exist and the task is in the current
safe wave. Independent low/medium-risk tasks can share a safe wave. Shared core
control-flow work, broad claims, high-risk tasks, blocked dependencies, stale
activities, and missing checkpoint repairs serialize or stop dispatch.

Failure classes are scheduling barriers. Human-decision classes stop with a
decision packet, repeated `needs_rebase` stops after one checkpoint redispatch,
and missing resume handlers block instead of recording fake progress.
```

- [ ] **Step 2: Document lazy worktree policy**

Append to `skills/agent-runway/references/worktree-policy.md`:

```markdown
## Lazy Worker Worktrees

Worker worktrees are created only after the durable projection places a task in
`safe_wave`. Tasks withheld by blocked dependencies, missing checkpoints, stale
activities, or missing resume handlers must not create mutable worker
worktrees. Successful tasks merge into run-main immediately and create a
`merged:<task_id>` checkpoint before dependent work is released.
```

- [ ] **Step 3: Mark the design as implemented**

In `docs/superpowers/specs/2026-05-21-agentrunway-hybrid-scheduler-failure-recovery-design.md`, change:

```markdown
Status: Draft for user review
```

to:

```markdown
Status: Implemented
```

Append:

```markdown
## 12. Implementation Note

Implemented through the hybrid scheduler failure recovery plan. The durable
projection is the authoritative dispatch source, task classification drives
parallel versus serial execution, resume failures block durably, and
inspect/summarize expose the same scheduler diagnostics used by runtime
dispatch.
```

- [ ] **Step 4: Run full AgentRunway evals**

Run:

```bash
cd skills/agent-runway && ./evals/run.sh
```

Expected: all tests pass.

- [ ] **Step 5: Compile Python modules**

Run:

```bash
cd skills/agent-runway && python -m py_compile scripts/agentrunway/*.py scripts/agentrunway/adapters/*.py
```

Expected: command exits 0.

- [ ] **Step 6: Check whitespace and graph**

Run:

```bash
git diff --check
graphify update .
```

Expected: no diff-check errors; graphify completes AST extraction and graph update.

- [ ] **Step 7: Commit Task 6**

```bash
git add skills/agent-runway/README.md \
  skills/agent-runway/references/worktree-policy.md \
  docs/superpowers/specs/2026-05-21-agentrunway-hybrid-scheduler-failure-recovery-design.md
git commit -m "docs: document AgentRunway hybrid scheduler recovery"
```

---

## Final Verification Checklist

- [ ] `cd skills/agent-runway && ./evals/run.sh`
- [ ] `cd skills/agent-runway && python -m py_compile scripts/agentrunway/*.py scripts/agentrunway/adapters/*.py`
- [ ] `git diff --check`
- [ ] `graphify update .`
- [ ] `git status --short`

## Self-Review

- Spec coverage:
  - Parallel versus serial classification: Task 1 and Task 3.
  - Lazy worktree policy and checkpoint release: Task 3 and Task 6.
  - Failure barriers for blocked dependencies, stale activities, missing checkpoints, and missing handlers: Task 2 and Task 4.
  - Projection-derived final status and diagnostics: Task 2, Task 3, and Task 5.
  - Risk-based gate depth: Task 1.
  - Final docs and verification: Task 6.
- Placeholder scan: no placeholder work remains in this plan.
- Type consistency:
  - `TaskExecutionClass.execution_class` values match the spec classes.
  - `DurableProjection` new fields are used consistently by scheduler, summary, and status.
  - `ResumeActionName` includes `classify_stale_activity` before runner creates that action.
